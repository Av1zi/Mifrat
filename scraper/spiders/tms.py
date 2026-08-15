"""
TMS (tms.co.il) spider.

Recon so far (Aug 2026, via search/fetch — verify against live robots.txt/ToS
yourself before running, see README "Phase 0 checklist"):
- Platform: OpenCart. Category URLs are clean and server-rendered, e.g.
  https://tms.co.il/computer-hardware-components/video-cards
  https://tms.co.il/computer-hardware-components/processor/amd-cpu
- No JSON/XHR API observed in the page source fetched — looks like classic
  OpenCart server-rendered HTML, not a JS/React frontend. Plain
  scrapy.Request + Selector should be enough; scrapy-playwright likely NOT
  needed for this vendor. Re-verify with the Network tab per §7 step 2
  before committing to that assumption.
- Product tiles include SKU (e.g. "N5080AORUSM16GD"), price in ₪, and a
  manufacturer logo/name — good structured signals for the matcher (§8).
- Site is Hebrew (RTL) only, per <meta og:locale> = he-IL.
- Sale/clearance prices ("קניה מהירה" tiles) sit alongside catalog pages —
  make sure the category-page parser doesn't only rely on scraping the
  homepage promo carousels, which aren't representative of the full catalog.

TODO before first real run:
1. Check https://tms.co.il/robots.txt and https://tms.co.il/terms_conditions.
2. Confirm category page pagination pattern (URL param, infinite scroll, etc).
3. Get one product's full field set from its detail page (spec table) to see
   what structured attributes (socket, wattage, etc.) TMS exposes directly.
"""
import scrapy
from datetime import datetime, timezone
from scraper.items import ListingItem

VENDOR_ID = "tms"

# Start with a couple of the categories the compatibility engine cares about
# most (CPU, GPU, motherboard, PSU) rather than the whole site on day one.
START_CATEGORIES = [
    "https://tms.co.il/computer-hardware-components/processor",
    "https://tms.co.il/computer-hardware-components/video-cards",
    "https://tms.co.il/computer-hardware-components/motherboards",
    "https://tms.co.il/computer-hardware-components/power-supplies",
]


class TmsSpider(scrapy.Spider):
    name = "tms"
    allowed_domains = ["tms.co.il"]
    start_urls = START_CATEGORIES

    def parse(self, response):
        # TODO: replace selectors with real ones once you've inspected the
        # live category page DOM — these are placeholders based on the tile
        # structure implied by the homepage fetch (product link + SKU + price).
        for product in response.css("div.product-thumb"):  # placeholder selector
            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=product.css("::attr(data-sku)").get(),
                title_raw=product.css("a.product-title::text").get(),
                url=response.urljoin(product.css("a::attr(href)").get()),
                price_ils=product.css("span.price::text").get(),
                in_stock=None,  # TODO: find stock indicator on the page
                category_guess=response.url.rsplit("/", 1)[-1],
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

        next_page = response.css("a.next::attr(href)").get()  # placeholder
        if next_page:
            yield response.follow(next_page, callback=self.parse)
