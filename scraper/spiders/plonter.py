"""
Plonter spider.

## robots.txt: NOT observed for this project (see decisions.md). This
spider deliberately hits a path (`/pnp/alon.tmpl`) that Plonter's
robots.txt disallows (`Disallow: /pnp/`) — an intentional, documented
decision, not an oversight. See settings.py (ROBOTSTXT_OBEY = False).

## Canonical domain: plonter.co.il only

plonter.com/main.tmpl was also checked and appears to serve the same
content without redirecting — a genuinely separate, independently-served
site rather than a mirror. Only plonter.co.il has been characterized. Do
not point this spider at plonter.com without separately re-verifying it.

## The data source: /pnp/alon.tmpl — full catalog feed

  GET https://www.plonter.co.il/pnp/alon.tmpl

Response is windows-1255-encoded HTML containing one `<pre>` tag per row
(the first `<pre>` is the tab-separated header):

  sku  title  description  category  division  shelf  price_total  tree
  image_file  amount  engdivision

Entire catalog in one response — no pagination.

## Product URL (RESOLVED, Aug 2026 — see PlonterFindings.md)

  https://www.plonter.co.il/detail.tmpl?sku={sku}

Confirmed directly from Plonter's own recon doc, not guessed. Previously
this spider shipped with url=None; that gap is closed below.

## `tree` field (Aug 2026: now wired into vendor_meta)

Space-separated list of internal category IDs per listing (e.g. `ACAM4`
for AMD AM4 CPUs, `B1700D5ATX` for Intel LGA1700 DDR5 ATX boards) — a much
finer-grained taxonomy than `category`/`division`. Passed through as
vendor_meta["tree"]; scraper/extractors.py's PLONTER_TREE_LABELS decodes
it into socket/chipset/memory_type/form_factor attributes instead of
re-deriving them from title text alone.

## WAF (Imperva Incapsula) — read this before changing the fetch

Plonter fronts the whole site with Imperva Incapsula. An unrecognized client
gets a JS-challenge page instead of the feed — and *which* build of Chromium
we ask for decides whether that challenge ever clears:

  - Playwright's default headless **shell** is detected: every navigation
    returns the challenge (Sep 2026 status 200 with an `_Incapsula_Resource`
    iframe, or 403 from the CI datacenter IP), so the spider yielded zero
    items and scrape-cloud's §10 count-check failed the job.
  - The full Chromium build (`channel: "chromium"` in settings.py) solves the
    challenge and gets the real feed.

Even so, the *first* response can still be the challenge page while the
solved cookie is being set, so `parse()` re-requests the feed a bounded
number of times (MAX_FEED_ATTEMPTS) before giving up loudly. Cookies live on
the shared `default` Playwright context, so the retry is what makes the
solved challenge stick.

## Known gaps (still open)
- `amount` blank in several sampled rows — unclear whether blank means
  "in stock, quantity not tracked" or "out of stock, 0 suppressed."
  Treating blank as unknown (in_stock=None) rather than assuming.
- Content spans well beyond PC-hardware (storage controllers, USB devices,
  etc.) — no filtering applied here; normalize_and_match.py should expect
  out-of-scope rows and filter by category/division/tree downstream.
  (Encoding: this feed arrives via Playwright as decoded Unicode — do NOT
  force windows-1255 on the response; that mojibakes Hebrew. See parse().)

## Also available, not yet wired in
`/pnp/alonDT.tmpl` returns the category tree as JSON
(`categories['systems']['Platform']['subsystems']['Form Factor'][]` etc.,
per PlonterFindings.md). Not necessary for the raw scrape — noted here in
case the matcher wants richer category structure later.
"""
import scrapy
from datetime import datetime, timezone
from urllib.parse import quote
from scraper.items import ListingItem

VENDOR_ID = "plonter"
ALON_FEED_URL = "https://www.plonter.co.il/pnp/alon.tmpl"
PRODUCT_URL_TEMPLATE = "https://www.plonter.co.il/detail.tmpl?sku={sku}"

# Incapsula answers an unrecognized client with 403 (CI) or a 200-status
# challenge body.
BLOCK_STATUS_CODES = {403, 429}
# The challenge clears on a subsequent request against the same browser
# context, so a couple of extra tries is all this needs — this is not a
# "keep hammering a blocking WAF" loop (see the module docstring).
MAX_FEED_ATTEMPTS = 4

COLUMNS = [
    "sku", "title", "description", "category", "division",
    "shelf", "price_total", "tree", "image_file", "amount", "engdivision",
]

# Only include relevant PC building components. 
# Normalized to lowercase for case-insensitive matching against the feed.
ALLOWED_ENGDIVISIONS = {
    "hard drives",          # Includes SSDs per feed structure
    "motherboards",
    "cpus",
    "fans and cooling solutions",
    "liquid cooling",
    "computer cases",
    "memory",
    "display adapters",
    "power supply",
    "power supplies",       # Added plural just in case the feed varies
}

class PlonterSpider(scrapy.Spider):
    name = "plonter"
    allowed_domains = ["plonter.co.il"]
    # Let a blocked response reach parse() instead of Scrapy's
    # HttpErrorMiddleware swallowing it as "Ignoring non-200 response"
    # before anything can retry the challenge.
    handle_httpstatus_list = sorted(BLOCK_STATUS_CODES)

    def start_requests(self):
        # Fallback for Scrapy <2.13
        yield from self._build_requests()

    async def start(self):
        # Scrapy >=2.13 entrypoint (StartSpiderMiddleware calls this)
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        self.logger.info("Plonter _build_requests – requesting alon.tmpl with Playwright")
        yield self._feed_request(1)

    def _feed_request(self, attempt: int):
        return scrapy.Request(
            ALON_FEED_URL,
            meta={
                "playwright": True,
                "playwright_include_page": False,
                "playwright_context": "default",
                "plonter_attempt": attempt,
            },
            callback=self.parse,
            errback=self._error,
            # The challenge retry re-requests an already-seen URL, which the
            # duplicate filter would otherwise drop.
            dont_filter=True,
        )

    def parse(self, response):
        attempt = int(response.meta.get("plonter_attempt") or 1)
        self.logger.info(f"Plonter parse called with status {response.status}")

        # NOTE: no response.replace(encoding="windows-1255") here. The feed
        # arrives via Playwright, which hands us already-decoded Unicode
        # re-serialized as UTF-8; forcing windows-1255 re-interprets those
        # UTF-8 bytes and mojibakes every Hebrew string (same bug that
        # poisoned the detail scrape — see detail_pages.py). Scrapy's
        # default decoding is correct as-is.

        pre_blocks = response.css("pre::text").getall()
        if response.status in BLOCK_STATUS_CODES or len(pre_blocks) < 2:
            if attempt < MAX_FEED_ATTEMPTS:
                self.logger.warning(
                    f"Plonter feed attempt {attempt}/{MAX_FEED_ATTEMPTS} got a "
                    f"blocked/challenge page (status {response.status}, "
                    f"{len(pre_blocks)} <pre> block(s)) - retrying; the "
                    "Incapsula challenge clears on the next request once the "
                    "browser has run its JS."
                )
                yield self._feed_request(attempt + 1)
                return
            self.logger.error(
                f"Plonter feed still blocked after {MAX_FEED_ATTEMPTS} attempts "
                f"(status {response.status}) - Plonter's WAF is refusing this "
                "client/IP. Zero items are written, so run_spider.py's "
                "count-check (section 10) fails the job instead of shipping an "
                "empty day."
            )
            return

        for raw_row in pre_blocks[1:]:
            fields = raw_row.strip("\r\n").split("\t")
            row = dict(zip(COLUMNS, fields))
            
            sku = row.get("sku")
            if not sku:
                continue
            
            # Filter by engdivision to only include relevant PC parts
            eng_div = (row.get("engdivision") or "").strip().lower()
            if eng_div not in ALLOWED_ENGDIVISIONS:
                continue  # Skip networking, peripherals, cables, etc.

            # The feed's image_file is a filename (e.g. MG07ACA12TE.jpg);
            # full-size images live under graphics/product_images/full/
            # (same path as the detail pages' og:image:url). Free photo
            # coverage for every listing; detail og:image still wins when
            # present (see _merge_detail_specs).
            image_file = (row.get("image_file") or "").strip()
            image_url = (
                f"https://www.plonter.co.il/graphics/product_images/full/{image_file}"
                if image_file
                else None
            )

            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=sku,
                title_raw=row.get("title"),
                url=PRODUCT_URL_TEMPLATE.format(sku=quote(sku)),
                price_ils=row.get("price_total"),
                in_stock=True,  # Explicitly set to True
                category_guess=row.get("engdivision"),  # Clean English category
                image_url=image_url,
                vendor_meta={
                    # Space-separated internal taxonomy IDs (e.g. "ACAM4",
                    # "B1700D5ATX") — decoded downstream via the static
                    # PLONTER_TREE_LABELS table in extractors.py (see
                    # PlonterFindings.md). Finer-grained than engdivision.
                    "tree": row.get("tree"),
                },
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

    def _error(self, failure):
        """Network/HTTP failure (403/429 are handled in parse() instead)."""
        request = getattr(failure, "request", None)
        attempt = int((request.meta.get("plonter_attempt") if request else 0) or 1)
        self.logger.error(f"Plonter request failed: {failure.value}")
        if attempt < MAX_FEED_ATTEMPTS:
            self.logger.warning(
                f"Plonter feed attempt {attempt}/{MAX_FEED_ATTEMPTS} failed "
                "— retrying"
            )
            yield self._feed_request(attempt + 1)