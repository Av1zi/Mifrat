"""
Plonter spider.

Note: two domains showed up in recon — plonter.co.il and plonter.com/main.tmpl.
Confirm which is the live/canonical storefront before building against either
(the .com/main.tmpl path suggests an older or alternate template system, worth
checking they're not two different sites/platforms).

TODO before first real run (§7):
1. Check robots.txt + ToS for whichever domain turns out to be canonical.
2. Confirm category URL structure for PC-hardware-relevant sections.
3. Network-tab check for a JSON API vs. server-rendered HTML.
4. Watch for Windows-1255 encoding.
"""
import scrapy
from scraper.items import ListingItem

VENDOR_ID = "plonter"


class PlonterSpider(scrapy.Spider):
    name = "plonter"
    allowed_domains = ["plonter.co.il", "plonter.com"]
    start_urls = [
        "https://www.plonter.co.il/",  # TODO: confirm canonical domain first
    ]

    def parse(self, response):
        raise NotImplementedError(
            "Plonter spider not yet built — resolve the .co.il vs .com "
            "canonical-domain question first, then do the standard §7 recon."
        )
