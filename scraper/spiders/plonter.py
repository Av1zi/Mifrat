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

## Known gaps (still open)
- `amount` blank in several sampled rows — unclear whether blank means
  "in stock, quantity not tracked" or "out of stock, 0 suppressed."
  Treating blank as unknown (in_stock=None) rather than assuming.
- Content spans well beyond PC-hardware (storage controllers, USB devices,
  etc.) — no filtering applied here; normalize_and_match.py should expect
  out-of-scope rows and filter by category/division/tree downstream.
- windows-1255 decoding confirmed fine on sampled rows, not yet checked
  against the full catalog for mojibake in less-common characters.

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

    def start_requests(self):
        # Fallback for Scrapy <2.13
        yield from self._build_requests()

    async def start(self):
        # Scrapy >=2.13 entrypoint (StartSpiderMiddleware calls this)
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        self.logger.info("Plonter _build_requests – requesting alon.tmpl with Playwright")
        yield scrapy.Request(
            ALON_FEED_URL,
            meta={
                "playwright": True,
                "playwright_include_page": False,
                "playwright_context": "default",
            },
            callback=self.parse,
            errback=self._error,
        )

    def parse(self, response):
        self.logger.info(f"Plonter parse called with status {response.status}")
        
        # Force correct encoding for the feed
        response = response.replace(encoding="windows-1255")
        
        pre_blocks = response.css("pre::text").getall()
        if len(pre_blocks) < 2:
            self.logger.warning("alon.tmpl returned no data rows or a challenge page.")
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
            
            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=sku,
                title_raw=row.get("title"),
                url=PRODUCT_URL_TEMPLATE.format(sku=quote(sku)),
                price_ils=row.get("price_total"),
                in_stock=True,  # Explicitly set to True
                category_guess=row.get("engdivision"),  # Clean English category
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
        self.logger.error(f"Plonter request failed: {failure.value}")