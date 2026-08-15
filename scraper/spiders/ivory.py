"""
Ivory (ivory.co.il) spider.

Recon so far: broad electronics retailer (computers, mobile, home appliances —
not PC-parts-only like TMS/1PC/Plonter), so category scoping matters more
here — don't crawl the whole catalog, only PC-hardware-relevant sections.

TODO before first real run (§7):
1. Check https://www.ivory.co.il/robots.txt and site ToS.
2. Open Network tab on a category page — Ivory's homepage content (per the
   Aug 2026 search snapshot) reads like it could be a heavier, more dynamic
   storefront than TMS. Check for a JSON/XHR endpoint before assuming plain
   HTML scraping is enough; if the catalog is client-rendered you'll need
   scrapy-playwright for this one specifically.
3. Confirm the site's category URL structure for PC components
   (processors, motherboards, GPUs, PSUs, cases) — not yet verified.
4. Watch for Windows-1255 encoding (§7 step 3) — check response headers.
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
