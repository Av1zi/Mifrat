"""
Ivory (ivory.co.il) spider.

Recon so far: broad electronics retailer (computers, mobile, home appliances —
not PC-parts-only like TMS/1PC/Plonter), so category scoping matters more
here — don't crawl the whole catalog, only PC-hardware-relevant sections.

- robots.txt CONFIRMED (Aug 2026): remarkably permissive, only two rules for
  User-agent: * — Disallow: /files/banners/ and Disallow: /catalog_compare.php.
  Category/product crawling is wide open as far as robots.txt is concerned.
- Manual Network-tab check done: Google Analytics `mp/collect` pings, plus
  a JSON response that DOES exist but reads as unstructured/minified
  gibberish rather than clean product data (unlike TMS's configurator JSON
  or 1PC's category-tile HTML) — not usable as-is. Not pursuing this further
  for now; flag if a clearer look at it later reveals it's decodable.
- **view-source confirmed (Aug 2026): product tiles ARE present in the raw
  HTML** (checked via View Source, not DevTools Elements, so this reflects
  the actual server response, not post-JS DOM). This settles the
  playwright question: plain scrapy.Request + Selector is enough for
  Ivory, same as TMS/Plonter. scrapy-playwright NOT needed.

TODO before first real run (§7):
1. Still need: ToS skim (linked from ivory.co.il footer).
2. Confirm the site's category URL structure for PC components
   (processors, motherboards, GPUs, PSUs, cases) — not yet verified.
3. Watch for Windows-1255 encoding (§7 step 3) — check response headers.
"""
import scrapy
from datetime import datetime, timezone
from scraper.items import ListingItem

VENDOR_ID = "ivory"


class IvorySpider(scrapy.Spider):
    name = "ivory"
    allowed_domains = ["ivory.co.il"]
    # TODO: replace with real PC-hardware category URLs once confirmed
    start_urls = [
        "https://www.ivory.co.il/",
    ]

    def parse(self, response):
        raise NotImplementedError(
            "Ivory spider not yet built — do the Phase 0 recon in the "
            "module docstring first (JSON API check is the priority here)."
        )
