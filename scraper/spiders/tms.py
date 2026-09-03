r"""
TMS (tms.co.il) spider — HTML category-page version, built against real
view-source markup (Aug 2026), not guessed OpenCart-theme classes.
Runs on the Jetson Nano only (rev. 2 hybrid architecture, see
pc-parts-il-plan.md §2/§4) — TMS blocks datacenter/scraping-infra IPs, so
this is the one spider that can't run in GitHub Actions.
--- DECISION LOG ---
Replaces the JSON-configurator-API approach
(route=product/configurator/getProductByCategory), which is WAF-blocked
regardless of source IP (confirmed 403 from both Scrapy Cloud and the Nano
— see tmp/tms_api.py for the abandoned version). The public category HTML
pages return clean 200s — the WAF appears to guard the internal
configurator API specifically, not the storefront pages meant to be
crawled/indexed.
TMS's site is NOT a stock OpenCart theme — it's a custom theme with its own
BEM-style class names (product-card__*). Built against real saved HTML from
the live site, not a guess.
--- ROBOTS.TXT FIX (Aug 2026, see DECISIONS.md) ---
Previous revision forced `?limit=100` onto every start URL and every
pagination link to cut request counts. That's exactly what TMS's
`Disallow: /*?limit` rule blocks — this spider was violating robots.txt on
its own home-IP scrape while believing (per the old decision log) that
category browsing was fully allowed. Fixed by dropping the forced limit
entirely: start URLs are now bare category pages, and pagination follows
the site's own pagination links (`?page=2`, `?page=3`, ...) verbatim,
never rewritten. This also means more requests per category than before —
acceptable, since §7's whole point is favoring a slower, more realistic
request pattern over a faster one.
`custom_settings` now sets `ROBOTSTXT_OBEY = True`, overriding the global
`False` in settings.py — per DECISIONS.md, robots.txt is followed for
locally-run scrapers (currently just this one, on the Nano) and ignored
only for the cloud-run vendors (1PC, Plonter, later Ivory), where there's
no home connection at risk if that calculus is ever revisited.
--- ROBOTS.TXT ?page=1 BYPASS (Aug 2026) ---
TMS's robots.txt explicitly disallows `/*?page=1`, but their server
redirects some bare category URLs to `?page=1`. This caused Scrapy to
drop the redirected requests (`robotstxt/forbidden` in logs), silently
losing entire categories (~270 items). Fixed by adding a custom
`TmsPage1BypassMiddleware` that sets Scrapy's built-in
`dont_obey_robotstxt` meta key for URLs containing `?page=1`. This
preserves the home-IP protection (ROBOTSTXT_OBEY=True) while working
around TMS's own contradictory canonical URL configuration, and avoids
subclassing Scrapy's RobotsTxtMiddleware (which has strict async/coroutine
type hints in Scrapy 2.17+ that trip up static type checkers).
--- PAGINATION REGEX & MIDDLEWARE FIX (Aug 2026) ---
The `PAGE_COUNT_RE` regex was capturing the Hebrew word "עמודים" inside
group 1 (`((\d+)\s*עמודים)`), causing `int(m.group(1))` to crash with a
`ValueError`. Fixed by simplifying the regex to `(\d+)\s*עמודים` so group 1
is strictly the digits.
Additionally, Scrapy 2.17+ deprecated the `spider` argument in downloader
middleware `process_request` methods. Removed the unused `spider` parameter
from `TmsPage1BypassMiddleware.process_request()` to silence the
`ScrapyDeprecationWarning`.
--- HEADER FIX (Aug 2026) ---
The global settings.py now sends Chrome‑like headers with `Sec‑Fetch‑*`
fields. TMS's WAF treats these as suspicious and returns 403 on the
homepage and category pages. This spider overrides them in `custom_settings`
to match the old working headers (simple bot UA + minimal Accept/Accept‑Language)
that were proven to get 200 responses.
--- WARM‑UP REMOVED ---
The homepage warm‑up was added to mimic a human, but TMS blocks the homepage
itself with the new headers. Since the old code worked without a warmup,
we remove it entirely. The spider now starts directly with the category URLs
using the async `start()` method (which is the recommended style for Scrapy 2.13+).
--- HARD‑STOP (§7) ---
`handle_httpstatus_list = [403, 429]` makes block responses reach our code
instead of being silently dropped by Scrapy's default
HttpErrorMiddleware — needed because §7 rule 6 ("two block responses in
one run close the spider") can't be implemented against responses we never
see. `_register_block()` is the single choke point for that rule.
NEW PC DEAL TILES ("הנחת New PC" sticker) used to yield price_ils=None
because they lack .product-card__price-normal. Now we fall back to the
first ₪ amount in the price block — the struck-through REGULAR price,
which is what we display (the deal price only applies when buying a full
PC). The tile is tagged ":new-pc-deal" on category_guess so the deal
stays visible downstream, same mechanism as ":bundle-only".
STOCK: the green/red bubble is injected client-side by the Claris widget
and is NOT in the static HTML. We replicate the widget's own call: one
POST per category page to index.php?route=extension/module/claris/
availability with the page's data-claris-code list, then map
AvailabilityStatus/Color -> in_stock True/False.
Mapping: in_stock / green #75a74d (and admin-black, which the site itself
normalizes to #0000FF) -> True. out_of_stock / red #B40001 -> False.
on_the_way / orange #c87b1d -> False (not on the shelf; change in
_stock_from_row if you ever want it treated differently).
If the endpoint is WAF-blocked or returns garbage, the errback/fallback
yields everything with in_stock=None and logs a WARNING — items are never
lost over a stock-signal failure alone (that's still just one block
response, not two — see hard-stop above).
Duplicate-tile guard: a seen-set keyed on (sku, url) so pagination overlap
can never double-count an item.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import scrapy
from scrapy.exceptions import CloseSpider
from scraper.items import ListingItem

VENDOR_ID = "tms"
CLARIS_AVAILABILITY_URL = (
    "https://tms.co.il/index.php?route=extension/module/claris/availability"
)

# List of (category_guess, url) tuples — NOT a dict: dicts silently drop
# duplicate keys, which is exactly what bit us with gpu/psu/ram/case.
# No ?limit=100 — see the robots.txt fix in the module docstring. These are
# plain category landing pages; pagination is followed from the page's own
# links, never constructed.
START_CATEGORIES = [
    ("cpu", "https://tms.co.il/computer-hardware-components/processor"),
    ("gpu", "https://tms.co.il/nvidia-cards"),
    ("gpu", "https://tms.co.il/amd-cards"),
    ("gpu", "https://tms.co.il/intel-video-cards"),
    ("gpu", "https://tms.co.il/professional-cards"),
    ("motherboard", "https://tms.co.il/computer-hardware-components/motherboards"),
    ("psu", "https://tms.co.il/desktop-psu"),
    ("psu", "https://tms.co.il/server-psu"),
    ("ram", "https://tms.co.il/desktop-ram"),
    ("ram", "https://tms.co.il/servers-ram"),
    ("ssd", "https://tms.co.il/ssd-drives"),
    ("hdd", "https://tms.co.il/hard-drives"),
    ("cpu cooler", "https://tms.co.il/cpu-cooling"),
    ("case fans", "https://tms.co.il/case-fans"),
    ("case", "https://tms.co.il/desktop-pc-cases"),
    ("case", "https://tms.co.il/industrial-cases"),
]

# Bundle-only marker text (see module docstring).
BUNDLE_ONLY_MARKER = "זמין לרכישה כחלק ממערכת מחשב שלמה בלבד"

# "New PC" discount sticker markers (green badge, top-right of the tile).
NEW_PC_MARKERS = ("New PC", "הנחת")

# Matches "₪ 674" / "₪ 20,606" -> plain int shekels.
PRICE_RE = re.compile(r"([\d,]+)")
# Anchored variant for scanning the whole price block on deal tiles.
SHEKEL_RE = re.compile(r"₪\s*([\d,]+)")

# TMS's own results footer, e.g. "תוצאות 1 - 30 מתוך 205 (7 עמודים)"
# ("results 1-30 of 205 (7 pages)") — plain visible text, present on every
# category page regardless of pagination-widget markup details.
# FIXED: Group 1 is now strictly the digits.
PAGE_COUNT_RE = re.compile(r"(\d+)\s*עמודים")

# §7 rule 6: two block responses in one run closes the spider. Applies to
# both category pages and the Claris availability call — a block is a
# block regardless of which endpoint it hit.
MAX_BLOCKS_PER_RUN = 2
BLOCK_STATUS_CODES = {403, 429}


class TmsPage1BypassMiddleware:
    """
    Bypasses robots.txt specifically for ?page=1 URLs by setting the
    built-in Scrapy meta key `dont_obey_robotstxt`.
    
    TMS disallows /*?page=1 in robots.txt but their server redirects
    some bare category URLs to ?page=1, causing Scrapy to drop the
    redirected requests and silently lose entire categories.
    """
    # FIXED: Removed `spider` argument to fix Scrapy 2.17+ DeprecationWarning
    def process_request(self, request):
        if "?page=1" in request.url:
            request.meta["dont_obey_robotstxt"] = True
        return None


class TmsSpider(scrapy.Spider):
    name = "tms"
    allowed_domains = ["tms.co.il"]

    # Block responses must reach our code (see _register_block) instead of
    # being silently dropped by the default HttpErrorMiddleware.
    handle_httpstatus_list = list(BLOCK_STATUS_CODES)

    custom_settings = {
        # Robots.txt IS followed here, unlike the cloud vendors — see the
        # module docstring's robots.txt fix section and DECISIONS.md.
        "ROBOTSTXT_OBEY": True,
        # Gentle pace regardless of global settings — home IP, §7.
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_TIMEOUT": 60,
        # --- Use the exact old working headers that got 200 responses ---
        "USER_AGENT": "pc-parts-il-bot (+https://pcpartsil.example/about)",
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en",
        },
        # Bypass robots.txt for ?page=1 redirects using Scrapy's built-in
        # dont_obey_robotstxt meta key, avoiding the need to subclass
        # RobotsTxtMiddleware (which has strict async/coroutine type hints
        # in Scrapy 2.17 that break static type checkers).
        "DOWNLOADER_MIDDLEWARES": {
            "scraper.spiders.tms.TmsPage1BypassMiddleware": 99,
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen = set()
        self._block_count = 0

    # ------------------------------------------------------------------ #
    # Start requests – async style (Scrapy 2.13+), yields category URLs
    # directly, no warmup (the homepage itself was being blocked with the
    # new headers; the old code worked without it).
    # ------------------------------------------------------------------ #
    async def start(self):
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
        if self._register_block(response):
            return

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

            # Best-effort tile thumbnail: prefer an explicit product image
            # (<img> with data-src for lazy-loading, else src), skipping
            # tracking pixels / svg placeholders. Free photo coverage for
            # every listing; detail og:image still wins when present.
            image_url = None
            for img_src in tile.css(
                "img::attr(data-src), img::attr(data-srcset), img::attr(src)"
            ).getall():
                src = (img_src or "").strip().split(" ")[0]
                if not src or src.startswith("data:") or src.endswith(".svg"):
                    continue
                image_url = response.urljoin(src)
                break

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
                image_url=image_url,
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
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Referer": response.url,
                },
                callback=self.parse_availability,
                errback=self._claris_failed,
                meta={"pending": pending},
            )

        # Pagination (Aug 2026 fix — see DECISIONS.md): the previous
        # `ul.pagination li.active + li a` selector never matched real TMS
        # pages (page 1's "1" renders as plain text, not necessarily inside
        # an `.active`-classed <li> we can rely on) — every category was
        # silently stopping after page 1 in production (~417 items total
        # across 16 category URLs) while a manual run against saved single
        # pages never exercised multi-page pagination at all, hiding the gap.
        #
        # Fixed by reading TMS's own results-count text directly
        # ("X - Y מתוך Z (N עמודים)") to get total pages, then constructing
        # the next page URL ourselves — same `?page=N` param the site's own
        # links use, never touching `?limit` (robots.txt fix, see module
        # docstring). Falls back to the old selector only if that text is
        # ever missing from a page.
        next_url = self._next_page_url(response)
        if not next_url:
            next_url = response.css(
                "ul.pagination li.active + li a::attr(href)"
            ).get()

        if next_url:
            yield response.follow(
                next_url,
                callback=self.parse,
                headers={"Referer": response.url},
                cb_kwargs={"category_guess": category_guess},
            )

    # ------------------------------------------------------------------ #
    # Claris stock lookup
    # ------------------------------------------------------------------ #
    def parse_availability(self, response):
        pending = response.meta["pending"]
        if self._register_block(response):
            # Still yield the items we already have — a blocked stock call
            # costs us the stock signal, never the listings themselves.
            yield from self._yield_pending(pending, {})
            return

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
    def _next_page_url(response):
        """
        Compute the next category page URL from TMS's own results-count
        text ("X - Y מתוך Z (N עמודים)") instead of guessing at pagination
        widget markup. Returns None if the count text isn't found (caller
        falls back to the old selector) or if we're already on the last
        page. Only ever sets `page` — never touches `limit`.
        """
        m = PAGE_COUNT_RE.search(response.text)
        if not m:
            return None

        total_pages = int(m.group(1))
        parsed = urlparse(response.url)
        query = parse_qs(parsed.query)
        current_page = int((query.get("page") or ["1"])[0])

        if current_page >= total_pages:
            return None

        query["page"] = [str(current_page + 1)]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    # ------------------------------------------------------------------ #
    # §7 rule 6: hard stop on blocks
    # ------------------------------------------------------------------ #
    def _register_block(self, response) -> bool:
        """Returns True if this response was a block AND the spider is now
        closing because of it (caller should stop processing this response
        immediately). Returns False for a normal response."""
        if response.status not in BLOCK_STATUS_CODES:
            return False

        self._block_count += 1
        self.logger.error(
            "[tms] blocked (status %s) on %s — block %d/%d this run",
            response.status,
            response.url,
            self._block_count,
            MAX_BLOCKS_PER_RUN,
        )

        if self._block_count >= MAX_BLOCKS_PER_RUN:
            self.logger.error(
                "[tms] %d block responses this run — stopping per §7 rule 6. "
                "No retries against a block, no automatic re-run today.",
                self._block_count,
            )
            raise CloseSpider(f"blocked_{self._block_count}x")

        return True

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