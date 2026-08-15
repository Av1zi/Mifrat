"""
1PC (1pc.co.il) spider.

Recon so far (Aug 2026):
- Site is genuinely bilingual at the URL level: /he/... and /en/... paths
  both exist (e.g. https://1pc.co.il/en/pc-hardware), which is convenient
  since the site itself is going to be bilingual (Hebrew + English) per the
  project's language decision — scraping the /en/ path may give cleaner
  English product names for free instead of needing translation later.
  Worth comparing /he/ vs /en/ output for the same product to see if pricing
  or stock differs before picking one as canonical.
- Category example: https://1pc.co.il/en/pc-hardware
- No JSON API observed yet — needs the same Network-tab check as the others.

TODO before first real run (§7):
1. Check https://1pc.co.il/robots.txt and https://1pc.co.il/he/תקנון-האתר
   (terms of service — note the ToS page itself is at a Hebrew-slug URL).
2. Decide: scrape /he/ or /en/ paths (or both, and cross-check)?
3. Confirm pagination + full category list for PC-hardware-relevant sections.
"""
import scrapy
from datetime import datetime, timezone
from scraper.items import ListingItem

VENDOR_ID = "1pc"

START_CATEGORIES = [
    "https://1pc.co.il/en/pc-hardware",
]


class OnePcSpider(scrapy.Spider):
    name = "onepc"
    allowed_domains = ["1pc.co.il"]
    start_urls = START_CATEGORIES

    def parse(self, response):
        raise NotImplementedError(
            "1PC spider not yet built — confirm selectors against the live "
            "category page DOM first."
        )
