"""
YahavPC (yahavpc.co.il) spider — the store's PC-builder JSON API.

## Why this file exists (2026-10-14)

YahavPC ("יהב מחשבים") is a fourth Israeli vendor. Its storefront is a
server-rendered PHP page with an AngularJS front-end, and the category
pages do NOT carry products in their HTML: every listing on the site is
rendered from the store's own build-a-PC backend. Probing the real
browser (Postman-style replay of the XHRs on /build and /category/15)
surfaced two endpoints:

  POST https://www.yahavpc.co.il/api/BuildInit      body {}
  POST https://www.yahavpc.co.il/api/BuildSearch    body {"Categories":[15]}

BuildInit answers with the builder's slot list — each slot is a
human name plus the store's category ids:

  {"categories":[{"ids":[11,12],"name":"מעבד"},
                 {"ids":[27,28],"name":"מערכת קירור מעבד"}, ...],
   "discount":0.99}

BuildSearch answers with every product in the requested categories:

  {"products":[{"name":"מעבד חברת AMD דגם Threadripper Pro 9995WX ...",
                "id":10957,"price":51990,
                "attributes":[1032,63,1030,525,116],"image":true}, ...]}

That is the whole catalogue for those categories: measured 2026-10-14,
the /category/24 page renders 266 case tiles and a fresh BuildSearch for
[24] returns the same 266 ids, and client-side filtering in
dist/search.js runs over the ONE response — there is no second page.

Scope: the builder's PC-part slots only (see SCOPED_SLOTS). Software,
monitors, peripherals, UPSes, printers and the "recommended by" slot are
deliberately left out — they are not build parts and this catalogue is a
parts/compatibility index. The site sells 2,557 products in total
(sitemap.xml); the builder's part slots account for ~1,850 of them, and
the remaining ~700 sitemap-only products are cables, adapters, cases and
consoles (verified by sampling: MD836ZM/A, E-USB-HUB7, GT-B6156,
QSW-3205-5T, CH-PL-PL-5).

## Rates, politeness and a note on TLS

The storefront sits behind nginx and its chain sometimes fails strict
verification with a certificai/OpenSSL store (observed once on the first
probe, clean on eight consecutive retries afterwards — the leaf itself is
a valid SSL.com EV certificate for yahavpc.co.il). Nothing special is
configured here: robots.txt is `User-agent: * / Disallow:` (i.e. allow
everything), and the spider inherits the project's global DOWNLOAD_DELAY
+ AutoThrottle. Slot requests are chained one-at-a-time rather than
fired in parallel — 11 requests total, so the extra ~15s buys
deterministic ordering (see below) and a gentler burst.

## Deliberate design choices

- Requests are CHAINED (each slot's response schedules the next slot)
  instead of all eleven going out at once. Two slots can legitimately
  contain the same product — the vendor files a product under every
  category it fits — and with parallel requests the winner of the
  "which category_guess survives dedupe" race would depend on which
  response landed first, flipping a listing's category between days and
  churning its price history. A fixed slot order — the SCOPED_SLOTS
  definition order, deliberately not the order BuildInit lists the slots
  in — makes the first entry always win, and the duplicate is logged.
- `attributes` (numeric filter-facet ids, e.g. [1032,63,1030,525,116])
  is NOT used. The descriptor table that maps those ids to labels lives
  behind the category page's filter markup, and the facet ids do not
  appear anywhere in the server-rendered HTML (checked for 1032/1030/
  525/116 on /category/15). Guessing a label from an opaque id would
  invent facts. Real specs come from the product page's `p-attr` block
  via the detail spider (spiders/detail_pages.py, YahavDetailSpider).
- `stock_qty` does not exist in this feed at all, and neither does an
  availability flag. BuildSearch returns only what the builder still
  offers, so `in_stock` stays True for everything it returns — the same
  reading the 1PC builder spider settled on.
- `image: true` is a boolean flag, not a URL. The store's real path
  shape is /img/p/<id>/<variant>.png with variants xs1 (listing tile),
  sm1 and g1 (full) — verified 200 on all three, and PNG only (the .jpg
  variants all 404). The listing stores the full-size g1 URL; the detail
  spider re-derives the same URL from the page's itemprop=image.
- `id` is the store's numeric product key. It stays `vendor_sku` here
  for the same reason as 1PC: data/detail_pending/yahav.json, the
  accumulated detail corpus and _merge_detail_specs all key on it. The
  real manufacturer part number is on the product page ("מק"ט: ..."),
  and the detail spider hands it over as extra.real_sku.

## Price semantics

`price` is an integer in ILS and already exact — spot-checked against
the product pages (builder 8750 vs page 400/6700/2990 for ids 11270,
9750, 10506, all equal). The build feed multiplies by a session discount
worth 1% ("discount":0.99), which is the store's own rounding of the
same list price: the page microdata and the API agree to the shekel, so
no adjustment is applied. _round_price mirrors the 1PC helper so any
future 999.99998 noise still lands on whole shekels (Decimal
ROUND_HALF_UP, not round(), which is half-to-even).

## Gotcha (binding, same as every other spider here)
Scrapy >=2.13 uses `async def start()`; older environments only call
`start_requests()`. Both are defined and share `_build_requests()` —
removing either silently yields a 0-request, 0-item, instant close.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import scrapy

from scraper.items import ListingItem

VENDOR_ID = "yahav"
SITE_BASE = "https://www.yahavpc.co.il"
BUILD_INIT_URL = f"{SITE_BASE}/api/BuildInit"
BUILD_SEARCH_URL = f"{SITE_BASE}/api/BuildSearch"
PRODUCT_URL = f"{SITE_BASE}/product/{{pid}}"
IMAGE_URL = f"{SITE_BASE}/img/p/{{pid}}/g1.png"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# BuildInit slot ids -> (expected slot name, category_guess).
#
# Keyed on the ids, not on the display name: ids are the store's own CMS
# keys and keep addressing the same taxonomy even after the pre-redesign
# 1PC precedent showed vendors rename and re-title slots. The name is
# checked and a drift is logged loudly, but it does not stop the scrape —
# a renamed slot must still produce its products.
#
# category_guess strings intentionally reuse the vocabulary the other
# spiders emit ("ram" like TMS, "cpu_cooling"/"case_fans"/"harddrive"
# like 1PC, "storage"/"case" everywhere) so matching.CATEGORY_ALIASES
# resolves them unchanged.
SCOPED_SLOTS = {
    (11, 12): ("מעבד", "cpu"),
    (13, 14): ("לוח אם", "motherboard"),
    (15,): ("זיכרון", "ram"),
    (17,): ("כרטיס מסך", "gpu"),
    (18, 21): ("כונן קשיח", "harddrive"),
    (19,): ("כונן SSD", "storage"),
    (24,): ("מארז", "case"),
    (26,): ("ספק כוח", "psu"),
    (27, 28): ("מערכת קירור מעבד", "cpu_cooling"),
    (29, 73): ("מאווררים למארז", "case_fans"),
    (31,): ("משחה טרמית (אופציונלי)", "thermal_paste"),
}


def _round_price(raw_price):
    """Whole shekels, round-half-up (see the module docstring)."""
    if raw_price is None or raw_price == "":
        return None
    try:
        return int(Decimal(str(raw_price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def _slot_key(ids):
    """Normalize a BuildInit slot's ids into the SCOPED_SLOTS key shape."""
    try:
        return tuple(sorted(int(i) for i in ids))
    except (TypeError, ValueError):
        return None


class YahavSpider(scrapy.Spider):
    name = "yahav"
    allowed_domains = ["yahavpc.co.il"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slot_order: list[tuple] = []
        self._seen: dict[str, str] = {}

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        yield self._init_request()

    def _base_headers(self):
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "he-IL,he;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
        }

    def _post(self, url, payload, callback, meta=None):
        return scrapy.Request(
            url=url,
            method="POST",
            body=json.dumps(payload).encode("utf-8"),
            headers=self._base_headers(),
            callback=callback,
            errback=self.handle_error,
            meta=meta or {},
            dont_filter=True,
        )

    def _init_request(self):
        return self._post(BUILD_INIT_URL, {}, self.parse_init)

    def handle_error(self, failure):
        """Keep the chain alive — one failed slot must not cancel the rest.

        Deliberately a plain function returning either a Request or None:
        a generator errback would raise on the `return` path, and returning
        a request is the documented way to hand a new request back from an
        errback. `slot_index` is absent when BuildInit itself failed, and
        there is nothing sensible to chain into without a slot list.
        """
        request = failure.request
        self.logger.error(
            "[yahav] request failed: %s meta=%s (%s)",
            request.url, request.meta, failure.value,
        )
        if "slot_index" not in request.meta:
            return None
        return self._slot_request(request.meta["slot_index"] + 1)

    def parse_init(self, response):
        """Read the builder's slot list, keep the part slots, start the walk."""
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.error(
                "[yahav] /api/BuildInit is not JSON (%d bytes) — the "
                "endpoint may have moved", len(response.body),
            )
            return

        categories = data.get("categories")
        if not isinstance(categories, list) or not categories:
            self.logger.error(
                "[yahav] /api/BuildInit returned no categories: %r",
                str(data)[:200],
            )
            return

        offered: dict[tuple, str] = {}
        for entry in categories:
            if not isinstance(entry, dict):
                continue
            key = _slot_key(entry.get("ids") or ())
            if key is None or key not in SCOPED_SLOTS:
                continue
            offered.setdefault(key, str(entry.get("name") or "").strip())

        # Walk the slots in SCOPED_SLOTS order, not the order BuildInit
        # happens to list them in: that order decides which category a
        # product that appears in two slots keeps (see the module
        # docstring), and it must be ours, not something the vendor can
        # reshuffle by re-ordering its builder page.
        slot_ids: list[tuple] = []
        for key in SCOPED_SLOTS:
            if key not in offered:
                continue
            expected_name, _ = SCOPED_SLOTS[key]
            name = offered[key]
            if name != expected_name:
                self.logger.warning(
                    "[yahav] slot %s was named %r, now %r — ids are the "
                    "key, scraping anyway; update SCOPED_SLOTS if the "
                    "taxonomy really changed",
                    key, expected_name, name,
                )
            slot_ids.append(key)

        missing = [k for k in SCOPED_SLOTS if k not in slot_ids]
        if missing:
            self.logger.error(
                "[yahav] BuildInit no longer offers these part slots: %s "
                "— their categories will be absent from today's snapshot",
                missing,
            )

        self._slot_order = slot_ids
        self.logger.info(
            "[yahav] builder offers %d categories, %d are in scope: %s",
            len(categories), len(slot_ids),
            [SCOPED_SLOTS[k][1] for k in slot_ids],
        )

        request = self._slot_request(0)
        if request is not None:
            yield request

    def _slot_request(self, index):
        """Build the request for one slot, or None past the last slot."""
        if index < 0 or index >= len(self._slot_order):
            return None
        key = self._slot_order[index]
        _, guess = SCOPED_SLOTS[key]
        return self._post(
            BUILD_SEARCH_URL,
            {"Categories": list(key)},
            self.parse_candidates,
            meta={"slot_index": index, "slot_ids": key, "guess": guess},
        )

    def parse_candidates(self, response):
        index = response.meta["slot_index"]
        key = response.meta["slot_ids"]
        guess = response.meta["guess"]

        products = None
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.error(
                "[yahav] slot %s: /api/BuildSearch answered non-JSON (%d "
                "bytes) — skipping this slot", key, len(response.body),
            )
        else:
            products = data.get("products") if isinstance(data, dict) else None
            if not isinstance(products, list):
                self.logger.error(
                    "[yahav] slot %s: no 'products' list in the response "
                    "(%r) — skipping this slot", key, str(data)[:200],
                )
                products = None

        if products is not None:
            self.logger.info(
                "[yahav] slot %s (%s): %d products", key, guess, len(products),
            )
            for raw in products:
                listing = self._to_listing(raw, guess)
                if listing is not None:
                    yield listing

        request = self._slot_request(index + 1)
        if request is not None:
            yield request

    def _to_listing(self, raw, guess):
        if not isinstance(raw, dict):
            return None
        product_id = raw.get("id")
        title = str(raw.get("name") or "").strip()
        if product_id is None or not title:
            return None

        sku = str(product_id)
        previous = self._seen.get(sku)
        if previous is not None:
            # The vendor files one product under several categories; the
            # chained slot order decides which one is kept (see module
            # docstring). Log it so a systematic mis-filing is visible.
            self.logger.warning(
                "[yahav] product %s appears in both %s and %s — keeping %s",
                sku, previous, guess, previous,
            )
            return None
        self._seen[sku] = guess

        return ListingItem(
            vendor_id=VENDOR_ID,
            vendor_sku=sku,
            title_raw=title,
            url=PRODUCT_URL.format(pid=product_id),
            price_ils=_round_price(raw.get("price")),
            in_stock=True,
            category_guess=guess,
            image_url=IMAGE_URL.format(pid=product_id) if raw.get("image") else None,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
