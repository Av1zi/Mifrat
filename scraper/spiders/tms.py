"""
TMS (tms.co.il) spider — HTML category-page version, built against real
view-source markup (Aug 2026), not guessed OpenCart-theme classes.

--- DECISION LOG ---
Replaces the JSON-configurator-API approach
(route=product/configurator/getProductByCategory), which is blocked by TMS's
WAF from Scrapy Cloud (confirmed HTTP 403, see HANDOFF.md). The public
category HTML pages returned clean 200s in a local test even with the old
bot-like User-Agent still in settings.py — the WAF appears to guard the
internal configurator API specifically, not the storefront pages meant to be
crawled/indexed.

TMS's site is NOT a stock OpenCart theme — it's a custom theme with its own
BEM-style class names (product-card__*). Built against real saved HTML from
the live site, not a guess.

--- FIXES IN THIS REVISION ---
1. START_CATEGORIES is now a LIST OF TUPLES. As a dict, duplicate keys
   (gpu/psu/ram/case) were silently overwritten — only the last URL per key
   ever ran.
2. Start URLs carry ?limit=100 — the max page size the site's own UI offers
   (looks like normal browsing, cuts pagination to ~1-2 pages per category).
   Pagination links are also force-rewritten to limit=100 for consistency.
3. NEW PC DEAL TILES ("הנחת New PC" sticker) used to yield price_ils=None
   because they lack .product-card__price-normal. Now we fall back to the
   first ₪ amount in the price block — the struck-through REGULAR price,
   which is what we display (the deal price only applies when buying a full
   PC). The tile is tagged ":new-pc-deal" on category_guess so the deal
   stays visible downstream, same mechanism as ":bundle-only".
4. STOCK: the green/red bubble is injected client-side by the Claris widget
   and is NOT in the static HTML. We replicate the widget's own call: one
   POST per category page to index.php?route=extension/module/claris/
   availability with the page's data-claris-code list, then map
   AvailabilityStatus/Color -> in_stock True/False.
   Mapping: in_stock / green #75a74d (and admin-black, which the site itself
   normalizes to #0000FF) -> True. out_of_stock / red #B40001 -> False.
   on_the_way / orange #c87b1d -> False (not on the shelf; change in
   _stock_from_row if you ever want it treated differently).
   If the endpoint is WAF-blocked (like the configurator API was) or returns
   garbage, the errback/fallback yields everything with in_stock=None and
   logs a WARNING — items are never lost.
5. Duplicate-tile guard: a seen-set keyed on (sku, url) so pagination overlap
   can never double-count an item.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import scrapy

from scraper.items import ListingItem

VENDOR_ID = "tms"

CLARIS_AVAILABILITY_URL = (
    "https://tms.co.il/index.php?route=extension/module/claris/availability"
)

# List of (category_guess, url) tuples — NOT a dict: dicts silently drop
# duplicate keys, which is exactly what bit us with gpu/psu/ram/case.
START_CATEGORIES = [
    ("cpu", "https://tms.co.il/computer-hardware-components/processor?limit=100"),
    ("gpu", "https://tms.co.il/nvidia-cards?limit=100"),
    ("gpu", "https://tms.co.il/amd-cards?limit=100"),
    ("gpu", "https://tms.co.il/intel-video-cards?limit=100"),
    ("gpu", "https://tms.co.il/professional-cards?limit=100"),
    ("motherboard", "https://tms.co.il/computer-hardware-components/motherboards?limit=100"),
    ("psu", "https://tms.co.il/desktop-psu?limit=100"),
    ("psu", "https://tms.co.il/server-psu?limit=100"),
    ("ram", "https://tms.co.il/desktop-ram?limit=100"),
    ("ram", "https://tms.co.il/servers-ram?limit=100"),
    ("ssd", "https://tms.co.il/ssd-drives?limit=100"),
    ("hdd", "https://tms.co.il/hard-drives?limit=100"),
    ("cpu cooler", "https://tms.co.il/cpu-cooling?limit=100"),
    ("case fans", "https://tms.co.il/case-fans?limit=100"),
    ("case", "https://tms.co.il/desktop-pc-cases?limit=100"),
    ("case", "https://tms.co.il/industrial-cases?limit=100"),
]

# Bundle-only marker text (see module docstring).
BUNDLE_ONLY_MARKER = "זמין לרכישה כחלק ממערכת מחשב שלמה בלבד"
# "New PC" discount sticker markers (green badge, top-right of the tile).
NEW_PC_MARKERS = ("New PC", "הנחת")

# Matches "₪ 674" / "₪ 20,606" -> plain int shekels.
PRICE_RE = re.compile(r"([\d,]+)")
# Anchored variant for scanning the whole price block on deal tiles.
SHEKEL_RE = re.compile(r"₪\s*([\d,]+)")


class TmsSpider(scrapy.Spider):
    name = "tms"
    allowed_domains = ["tms.co.il"]
    custom_settings = {
        # Gentle pace regardless of global settings — this is the vendor
        # whose WAF already flagged the JSON API once.
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        # limit=100 pages are big; give the server time to render them.
        "DOWNLOAD_TIMEOUT": 60,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen = set()

    async def start(self):
        # Project convention: Scrapy 2.13+ deprecated start_requests() in
        # favor of async start(). Using the old-style method silently
        # produces zero requests under StartSpiderMiddleware on 2.17 — it
        # doesn't error, it just never runs.
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for category_guess, url in START_CATEGORIES:
            yield scrapy.Request(
                url,
                callback=self.parse,
                cb_kwargs={"category_guess": category_guess},
            )

    # ------------------------------------------------------------------ #
    # Category pages
    # ------------------------------------------------------------------ #
    def parse(self, response, category_guess):
        tiles = response.css("div.product-card")
        if not tiles:
            self.logger.warning(
                f"[tms] zero product tiles found on {response.url} "
                f"(status {response.status}) — selectors likely need "
                "correcting against real view-source, not a WAF block."
            )

        pending = {}  # claris code (upper) -> [item dicts awaiting stock]
        for tile in tiles:
            header = tile.css("div.product-card__header")
            if not header:
                continue

            sku = header.css(".product-card__model a::text").get()
            title = header.css(".product-card__name a::text").get()
            url = header.css(".product-card__name a::attr(href)").get()

            dedupe_key = (sku.strip() if sku else None, url)
            if dedupe_key in self._seen:
                continue
            self._seen.add(dedupe_key)

            # --- New PC deal detection (sticker badge) ---
            sticker_text = " ".join(
                header.css(".stickers-product-wrapper ::text").getall()
            ).strip()
            new_pc_deal = any(m in sticker_text for m in NEW_PC_MARKERS)

            # --- Price: normal span first; deal tiles lack it, so fall back
            # to the first ₪ amount in the price block (the struck-through
            # regular price — the one we want to display). ---
            price_ils = None
            price_raw = header.css(
                ".product-card__price .product-card__price-normal::text"
            ).get()
            if price_raw:
                m = PRICE_RE.search(price_raw)
                if m:
                    price_ils = int(m.group(1).replace(",", ""))
            if price_ils is None:
                amounts = SHEKEL_RE.findall(
                    " ".join(header.css(".product-card__price ::text").getall())
                )
                if amounts:
                    price_ils = int(amounts[0].replace(",", ""))
                if len(amounts) > 1:
                    # Regular + deal price present => deal tile even if the
                    # sticker markup ever changes.
                    new_pc_deal = True

            tile_text = " ".join(tile.css("*::text").getall())
            bundle_only = BUNDLE_ONLY_MARKER in tile_text

            cat = category_guess
            if bundle_only:
                cat += ":bundle-only"
            if new_pc_deal:
                cat += ":new-pc-deal"

            item = dict(
                vendor_id=VENDOR_ID,
                vendor_sku=sku.strip() if sku else None,
                title_raw=title.strip() if title else None,
                url=response.urljoin(url) if url else None,
                price_ils=price_ils,
                category_guess=cat,
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

            claris_code = self._claris_key(
                tile.css(".info-storage-button::attr(data-claris-code)").get()
            )
            if claris_code:
                pending.setdefault(claris_code, []).append(item)
            else:
                # No claris hook on the tile — nothing to look up.
                yield ListingItem(in_stock=None, **item)

        # One Claris availability POST for the whole page (same as the
        # site's own widget does client-side).
        if pending:
            yield scrapy.Request(
                CLARIS_AVAILABILITY_URL,
                method="POST",
                body=json.dumps({"models": sorted(pending)}),
                headers={"Content-Type": "application/json; charset=UTF-8"},
                callback=self.parse_availability,
                errback=self._claris_failed,
                meta={"pending": pending},
            )

        # Pagination: li immediately after the active one. Force limit=100
        # so page 2+ stays the same page size as page 1.
        next_page = response.css("ul.pagination li.active + li a::attr(href)").get()
        if next_page:
            yield response.follow(
                self._force_limit(next_page),
                callback=self.parse,
                cb_kwargs={"category_guess": category_guess},
            )

    # ------------------------------------------------------------------ #
    # Claris stock lookup
    # ------------------------------------------------------------------ #
    def parse_availability(self, response):
        pending = response.meta["pending"]
        stock_by_code = {}
        rows = []
        try:
            data = json.loads(response.text)
            rows = data.get("productsData") or []
        except (json.JSONDecodeError, AttributeError, TypeError):
            rows = []

        if response.status != 200 or not rows:
            self.logger.warning(
                "[tms] Claris availability returned status %s / no usable "
                "payload; in_stock left None for %d items",
                response.status,
                sum(len(v) for v in pending.values()),
            )
            yield from self._yield_pending(pending, stock_by_code)
            return

        for row in rows:
            code = self._claris_key(row.get("Code"))
            if code:
                stock_by_code[code] = self._stock_from_row(row)
        yield from self._yield_pending(pending, stock_by_code)

    def _claris_failed(self, failure):
        # WAF block / network error on the Claris endpoint: lose the stock
        # signal, never the items.
        pending = failure.request.meta["pending"]
        self.logger.warning(
            "[tms] Claris availability request failed (%s); yielding %d "
            "items with in_stock=None",
            failure.value,
            sum(len(v) for v in pending.values()),
        )
        yield from self._yield_pending(pending, {})

    def _yield_pending(self, pending, stock_by_code):
        for code, items in pending.items():
            stock = stock_by_code.get(code)  # None if Claris didn't answer for it
            for item in items:
                yield ListingItem(in_stock=stock, **item)

    @staticmethod
    def _stock_from_row(row):
        """Mirror the site's own color/status logic (see claris.js)."""
        status = (row.get("AvailabilityStatus") or "").strip()
        color = (row.get("Color") or "").strip().lower()
        # The site normalizes admin "black" to blue and treats it as in-stock.
        if color in ("#000000", "#000", "black", "rgb(0, 0, 0)", "rgb(0,0,0)"):
            color = "#0000ff"
        if status == "in_stock" or color in ("#75a74d", "#0000ff"):
            return True
        # Red = out of stock; orange = on the way (not on the shelf).
        if status in ("out_of_stock", "on_the_way") or color in ("#b40001", "#c87b1d"):
            return False
        return None

    @staticmethod
    def _claris_key(code):
        """Same normalization the site's JS applies to data-claris-code."""
        if not code:
            return None
        cleaned = re.sub(r"[‎‏\ufeff]", "", code)
        cleaned = re.sub(r"&lrm;|&#8206;|&#x200E;", "", cleaned, flags=re.I)
        cleaned = cleaned.strip().upper()
        return cleaned or None

    @staticmethod
    def _force_limit(url, limit="100"):
        parts = urlparse(url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "limit"]
        query.append(("limit", limit))
        return urlunparse(parts._replace(query=urlencode(query)))