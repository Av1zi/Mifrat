"""
1PC (1pc.co.il) spider — rebuilt for the Oct 2026 storefront redesign.
(See pc-parts-il-plan.md and decisions.md for full context)

## Why this file was rewritten (2026-10-13)

1PC replaced its storefront. The old spider POSTed to
`/en/PCBuilder/CategoryViewData` and parsed an HTML fragment; that endpoint
now answers 404, which is what CI reported as "1PC suspended (Oct 2026)" —
the datacenter IP was never the problem, the page was. This rewrite targets
the replacement API.

## The find: /web/builder/candidates

The new PC Builder (https://1pc.co.il/web/builder) loads each slot over:

  GET https://1pc.co.il/web/builder/candidates?slot=case&offset=12&limit=12
  Accept: application/json          (an XHR in the browser)

  {"ok":true,"slot":"case","q":"","items":[
     {"id":214748,"name":"מארז מחשב Lian-Li Vector V100 Mini","sku":"V100MIX",
      "price":206,"stock_qty":5,"image":"/media/pictures/313677.jpeg"}, ...],
   "total":339,"offset":12,"limit":12,"has_more":true,"next_offset":24}

Confirmed against the live site 2026-10-13:
- Real slots are exactly cpu, motherboard, ram, gpu, storage, psu, cooling,
  case (plus os/other/speakers/headset/keyboard/mouse, which are not PC
  parts and stay out of scope, as before). Rows per slot: motherboard 445,
  case 339, cooling 256, ram 224, storage 200, psu 184, gpu 144, cpu 100 —
  1,891 component listings, the same ballpark as the 1,986 the old endpoint
  produced.
- `limit` is clamped server-side (asking 200 returned 48), so page with
  PAGE_SIZE and follow the response's own next_offset/has_more.
- An UNKNOWN slot name silently answers with the `case` slot (probed with
  fans/hdd/monitor/software/... — every one returned the 339 cases). The
  parser therefore refuses a response whose `slot` is not the one it
  requested, instead of filing 339 cases as case fans.
- The builder carries no case-fan and no hard-drive slot: those listings
  (208 + 65 on the last old snapshot) have no equivalent here. They are
  recovered from the server-rendered category pages instead — /web/cat/428
  (case fans) and /web/cat/356 (HDDs), 24 cards/page with ?page=N
  pagination, parsed from article.pcard[data-product-id] (see CAT_PAGES).
  Measured 2026-10-13: 256 fan + 66 HDD ids with ZERO overlap against the
  builder feed, while /web/cat/358 (SSDs) overlaps builder `storage`
  200/200, so only the two gap categories are scraped and nothing is
  duplicated. The old numeric categoryIds still address the new pages
  (breadcrumb on /web/item/107265 reads /web/cat/86 > /web/cat/158, the
  pre-redesign CPU id), which is why the pre-redesign ids work unchanged.
- The builder lists only what can currently be BUILT, so sold-out products
  are absent even when their page is live. Checked 2026-10-13:
  /web/product/192587 (MSI RTX 5070 12G TRIO OC, in the last old snapshot)
  answers 200 with a price and the text "אזל מהמלאי" and no schema.org
  availability — the old CategoryViewData endpoint returned it and the old
  spider stamped it in_stock=true anyway. So this source is stricter, not
  lossier: the ~360 stale 1PC listings that fall out of the catalogue on
  the first new snapshot are sold out (plus the fan/HDD gap above), not
  data we are silently dropping.
- robots.txt explicitly ALLOWS /web/ and disallows only
  account/cart/checkout/login/register/forgot/reset/wishlist/admin, so this
  path is allowed (cloud vendors ignore robots per plan §14; TMS is the
  single override).

## What the API gives us that the old fragment did not

- `id` — 1PC's numeric database key. This stays `vendor_sku`: the detail
  ledger (data/detail_pending/onepc.json), the accumulated detail corpus
  and normalize_and_match._merge_detail_specs all key on it.
- `sku` — the manufacturer part number ("V100MIX"). Not used here on
  purpose: the detail page's JSON-LD mpn is what replaces the numeric id
  downstream, and that path already reconciles truncated spellings. Wiring
  this in as a matching hint is a separate, measurable change.
- `price` — integer shekels, already exact (no floating-point noise here).
- `image` — the product photo, as a site-relative path.

## Deliberate non-decisions

`stock_qty` is NOT used as an availability signal. Every builder row carries
a quantity, but the `case` slot reports exactly 5 for 46 of 48 rows — those
are per-order caps, not stock. An unverified number baked in as truth is
worse than an honest "unknown", so `in_stock` stays True (the builder lists
only buildable items), exactly as the old spider behaved. Revisit only with
evidence from the product page.

## Gotcha hit during the first implementation (Aug 2026, still binding)
Scrapy >=2.13 moved to an `async def start(self)` entrypoint and by 2.17 the
old-style `start_requests()` override wasn't called at all — spider opened,
found nothing to crawl, closed instantly with 0 requests/0 items, no error.
Keep BOTH `start()` and `start_requests()` defined, sharing
`_build_requests()`. (Same fix in spiders/tms.py and ivory.py.)

## Price rounding (Aug 2026, kept)
The old endpoint's data-price carried floating-point noise (1148.99998400
for a real ₪1149) and the displayed ₪NNN was the charged price, so prices
are rounded half-up with Decimal (not round(), which is round-half-to-even
and disagrees exactly at .50 boundaries). The new API returns whole shekels
already; the same helper keeps any future 1148.99998400 honest.
"""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urljoin

import scrapy
from scrapy.exceptions import CloseSpider

from scraper.items import ListingItem

VENDOR_ID = "1pc"

CANDIDATES_URL = "https://1pc.co.il/web/builder/candidates"
CAT_URL = "https://1pc.co.il/web/cat/{cid}"
SITE_BASE = "https://1pc.co.il"
PRODUCT_URL = "https://1pc.co.il/web/product/{pid}"

# A real browser UA: the candidates endpoint served the Scrapy default UA
# fine on 2026-10-13, but a storefront that just replaced its frontend is
# exactly the kind of site that starts filtering bot UAs next. Cheap
# insurance, same as the TMS browser-headers rule.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# The endpoint clamps `limit` to 48 (asking for 200 served 48), so page at
# the observed maximum and trust the response's next_offset.
PAGE_SIZE = 48

# --- Oct 2026 DDOS-protection stop signal (binding, see decisions.md §Never break) ---
# Starting 2026-10-23 1PC fronts the whole /web/ storefront (listing AND detail
# pages) with a self-hosted "DDOS protection page" / zhCAPTCHA v0.2 checkbox
# challenge. Cloud (and, after enough volume, home) clients get HTTP 403/423
# with that HTML instead of the product data, so the crawl yields zero items
# and the cloud job fails. Per plan §14 and decisions.md this is a stop signal,
# NOT something to work around: no retries, no cookie-jar games, no browser
# automation to tick the box. The vendor was moved to the Nano (home IP, next
# to TMS) on 2026-10-24; this spider's job is only to recognise the block
# loudly and stop before it hammers the home connection.
BLOCK_STATUS_CODES = {403, 423, 429}
MAX_BLOCKS_PER_RUN = 2
_BLOCK_MARKERS = (
    "ddos protection",
    "zhcaptcha",
    "captcha",
    "i'm not a robot",
    "challenge-platform",
    "cf-chl",
    "_incapsula_",
)

# builder slot -> category_guess. The guesses use the vocabulary
# matching.CATEGORY_ALIASES already knows, kept identical to the
# pre-redesign spider for snapshot continuity ("memory", "cpu_cooling",
# "storage" rather than the slot names).
SLOTS = {
    "cpu": "cpu",
    "motherboard": "motherboard",
    "ram": "memory",
    "gpu": "gpu",
    "storage": "storage",
    "psu": "psu",
    "cooling": "cpu_cooling",
    "case": "case",
}

# Category pages (/web/cat/<id>, server-rendered HTML, 24 cards/page,
# `?page=N` pagination) for the two PC-part categories the builder has no
# slot for. Verified 2026-10-13: cat 428 (case fans, 256 products) and cat
# 356 (internal HDDs, 66 products) have ZERO id overlap with the builder
# feed, while cat 358 (SSDs, 200 products) overlaps the builder `storage`
# slot 200/200 — so only these two are scraped, and nothing is duplicated.
# Labels reuse the pre-redesign spider's exact strings ("case_fans",
# "harddrive") so matching.CATEGORY_ALIASES resolves them as before.
CAT_PAGES = {
    428: "case_fans",
    356: "harddrive",
}


def _round_price(raw_price):
    """Whole shekels, round-half-up (see the module docstring)."""
    if raw_price is None or raw_price == "":
        return None
    try:
        return int(Decimal(str(raw_price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


class OnePcSpider(scrapy.Spider):
    name = "onepc"
    allowed_domains = ["1pc.co.il"]

    # Runs on the Nano from the home IP since 2026-10-24 (the cloud leg met
    # a CAPTCHA page, see decisions.md), so the TMS home-IP rules apply:
    # sequential, throttled, robots.txt obeyed (it allows /web/), and a hard
    # stop after two block responses. No retries against blocks.
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 2,
        "RETRY_HTTP_CODES": [500, 502, 503, 504],
    }
    MAX_BLOCKS = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._blocks = 0

    # Let 403/423/429 bodies reach our callbacks instead of being swallowed by
    # Scrapy's HttpErrorMiddleware, so the DDOS challenge can be named (see the
    # constants above). Default behaviour would just drop them and look like a
    # silent zero-item run.
    handle_httpstatus_list = [403, 423, 429]

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _response_is_blocked(self, response):
        if response.status in BLOCK_STATUS_CODES:
            return True
        # The challenge arrives as HTML; keep JSON candidates out of this path.
        head = response.body[:4000].decode("utf-8", "replace").lower()
        return any(marker in head for marker in _BLOCK_MARKERS)

    def _register_block(self, response):
        self._block_count = getattr(self, "_block_count", 0) + 1
        challenge = self._response_is_blocked(response)
        self.logger.error(
            "[1pc] BLOCKED (status %s, challenge=%s) on %s — no retry: a block "
            "is a stop signal (§14), block %d/%d this run",
            response.status, challenge, response.url,
            self._block_count, MAX_BLOCKS_PER_RUN,
        )
        if self._block_count >= MAX_BLOCKS_PER_RUN:
            raise CloseSpider(f"blocked_{self._block_count}x")

    def _build_requests(self):
        for slot in SLOTS:
            yield self._slot_request(slot, 0)
        for cid in CAT_PAGES:
            yield self._cat_request(cid, 1)

    def _base_headers(self):
        return {
            "User-Agent": USER_AGENT,
            "Accept-Language": "he-IL,he;q=0.9",
        }

    def _slot_request(self, slot, offset):
        return scrapy.Request(
            url=f"{CANDIDATES_URL}?slot={slot}&offset={offset}&limit={PAGE_SIZE}",
            headers={
                **self._base_headers(),
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            callback=self.parse_candidates,
            errback=self.handle_error,
            meta={"slot": slot, "offset": offset},
        )

    def _cat_request(self, cid, page):
        url = CAT_URL.format(cid=cid)
        if page > 1:
            url += f"?page={page}"
        return scrapy.Request(
            url=url,
            headers=self._base_headers(),
            callback=self.parse_category,
            errback=self.handle_error,
            meta={"cid": cid, "page": page},
        )

    def handle_error(self, failure):
        request = failure.request
        status = getattr(getattr(failure.value, "response", None), "status", None)
        if status in (403, 429):
            self._blocks += 1
            if self._blocks >= self.MAX_BLOCKS:
                self.logger.error(
                    "[1pc] %d block responses (HTTP %s) - hard stop, not "
                    "retrying against the block", self._blocks, status,
                )
                engine = self.crawler.engine
                if engine is not None:
                    engine.close_spider(self, "blocked")
        self.logger.error(
            "[1pc] request failed: %s meta=%s (%s)",
            request.url, request.meta, failure.value,
        )

    def parse_candidates(self, response):
        slot = response.meta["slot"]
        offset = response.meta["offset"]

        if self._response_is_blocked(response):
            self._register_block(response)
            return

        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            self.logger.error(
                "[1pc] slot=%s offset=%s: response is not JSON (%d bytes) - "
                "the endpoint may have moved again",
                slot, offset, len(response.body),
            )
            return

        if data.get("slot") != slot:
            # Unknown slot names fall back to `case` server-side, so a
            # mismatch means this response is NOT the category we asked for.
            self.logger.error(
                "[1pc] slot=%s: server answered for %r - refusing to file "
                "another category's rows", slot, data.get("slot"),
            )
            return

        items = data.get("items") or []
        self.logger.info(
            "[1pc] slot=%s offset=%s: %d/%s rows",
            slot, offset, len(items), data.get("total"),
        )
        for raw in items:
            listing = self._to_listing(raw, slot)
            if listing is not None:
                yield listing

        next_offset = data.get("next_offset")
        if data.get("has_more"):
            if isinstance(next_offset, int) and next_offset > offset:
                yield self._slot_request(slot, next_offset)
            else:
                self.logger.warning(
                    "[1pc] slot=%s: has_more with an unusable next_offset "
                    "(%r) - stopping pagination for this slot", slot, next_offset,
                )

    def parse_category(self, response):
        cid = response.meta["cid"]
        page = response.meta["page"]
        guess = CAT_PAGES[cid]

        cards = response.css("article.pcard[data-product-id]")
        self.logger.info(
            "[1pc] cat=%s page=%s: %d cards", cid, page, len(cards),
        )
        for card in cards:
            listing = self._to_card_listing(card, guess)
            if listing is not None:
                yield listing

        if cards and response.css('a[rel="next"]::attr(href)').get():
            yield self._cat_request(cid, page + 1)
        elif len(cards) >= 24:
            # Full pages carry a rel=next while more exist; a full page
            # without one means the pagination markup changed and we may
            # be truncating the category silently.
            self.logger.warning(
                "[1pc] cat=%s page=%s: %d cards but no rel=next link - "
                "stopping, verify pagination markup", cid, page, len(cards),
            )

    def _to_card_listing(self, card, guess):
        try:
            product_id = int(card.attrib["data-product-id"])
        except (KeyError, ValueError, TypeError):
            return None
        title = (card.css(".pcard-name::text").get() or "").strip()
        if not title:
            return None
        price_text = "".join(card.css(".pcard-prices ::text").getall())
        price_digits = re.sub(r"[^\d]", "", price_text)
        image = card.css("img.thumb::attr(src)").get()
        return ListingItem(
            vendor_id=VENDOR_ID,
            vendor_sku=str(product_id),
            title_raw=title,
            url=PRODUCT_URL.format(pid=product_id),
            price_ils=_round_price(price_digits) if price_digits else None,
            in_stock=True,
            category_guess=guess,
            image_url=urljoin(SITE_BASE + "/", image) if image else None,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    def _to_listing(self, raw, slot):
        product_id = raw.get("id")
        title = (raw.get("name") or "").strip()
        if product_id is None or not title:
            return None
        image = raw.get("image")
        return ListingItem(
            vendor_id=VENDOR_ID,
            # 1PC's numeric database id (see the module docstring).
            vendor_sku=str(product_id),
            title_raw=title,
            url=PRODUCT_URL.format(pid=product_id),
            price_ils=_round_price(raw.get("price")),
            in_stock=True,
            category_guess=SLOTS[slot],
            image_url=urljoin(SITE_BASE + "/", image) if image else None,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
