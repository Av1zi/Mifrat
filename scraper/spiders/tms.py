"""
TMS (tms.co.il) spider.

## robots.txt: NOT observed for this project (see pc-parts-il-plan.md §17
decision log, Aug 2026). This spider deliberately hits a path that TMS's
robots.txt disallows (`Disallow: /*configurator`) — that's an intentional,
documented decision, not an oversight. See settings.py (ROBOTSTXT_OBEY =
False) and the plan's decision log for the reasoning/caveats.

## The data source: product/configurator/getProductByCategory

TMS's PC configurator (https://tms.co.il/index.php?route=product/configurator)
calls, per category:

  GET https://tms.co.il/index.php?route=product/configurator/getProductByCategory
      &category_id=10001&attribute_value_id=0&sort_type=1
      &heightForCoolerCase=0&memory_type_value_id=0

...and gets back a clean JSON payload, one object per product:

  {
    "products": [
      {
        "product_id": "105950",
        "category_id": 10001,
        "socket": "1200",
        "manufacturer": "Intel",
        "name": "Intel Core i3 10105F / 1200 Box ",
        "stock": false,
        "model": "C10105FB",
        "price": 188,
        "href": "https://tms.co.il/intel-core-i3-10105f-1200-box",
        ...
      },
      ...
    ]
  }

This is by far the best raw data of the four vendors: real in-stock boolean,
manufacturer, socket, model/SKU, price, and canonical product URL, no HTML
parsing needed at all.

Confirmed category_ids (Aug 2026, captured directly from TMS's PC
configurator Network tab): CPU (10001), CPU cooler (10073), motherboard
(10000), RAM (10020), case (10002), case fans (10074), PSU (10050), GPU
(10033), SSD (10028), hard drive (10024). All 10 categories the
compatibility engine needs are now covered — see the CATEGORIES dict below.

`attribute_value_id`, `heightForCoolerCase`, and `memory_type_value_id` look
like compatibility filters (matching a previously-selected socket/cooler
clearance/RAM type) — using 0 for all of them, as in the CPU capture, seems
to return the full unfiltered category list, but this hasn't been
independently confirmed for other categories yet.

## TODO before first real run
1. ToS skim — noted for completeness; per the project owner's Aug 2026
   decision (see pc-parts-il-plan.md §17), scraping is proceeding regardless
   with a take-down-on-request posture, so this is no longer a blocking step.
2. Confirm `stock` (bool) maps cleanly to the shared ListingItem.in_stock
   field, and whether `stock_status` carries anything extra worth keeping
   (currently dropped).
3. Confirm pagination — the captured responses weren't confirmed to be a
   complete category or just a first page; check for a total-count field or
   whether category size ever exceeds what one call returns.
"""
import json
import scrapy
from datetime import datetime, timezone
from scraper.items import ListingItem

VENDOR_ID = "tms"

CONFIGURATOR_URL = "https://tms.co.il/index.php"

# category_id -> human label. Only CPU confirmed so far; fill in the rest
# per TODO #2 above.
CATEGORIES = {
    10001: "cpu",
    10073: "cpu_cooler",
    10000: "motherboard",
    10020: "ram",
    10002: "case",
    10074: "case_fans",
    10050: "psu",
    10033: "gpu",
    10028: "ssd",
    10024: "harddrive",
}


class TmsSpider(scrapy.Spider):
    name = "tms"
    allowed_domains = ["tms.co.il"]

    def start_requests(self):
        for category_id, label in CATEGORIES.items():
            url = (
                f"{CONFIGURATOR_URL}?route=product/configurator/getProductByCategory"
                f"&category_id={category_id}&attribute_value_id=0&sort_type=1"
                f"&heightForCoolerCase=0&memory_type_value_id=0"
            )
            yield scrapy.Request(
                url=url,
                callback=self.parse_category,
                meta={"category_label": label},
            )

    def parse_category(self, response):
        category_label = response.meta["category_label"]
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning(f"Non-JSON response for category '{category_label}': {response.url}")
            return

        for product in data.get("products", []):
            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=product.get("model") or product.get("product_id"),
                title_raw=(product.get("name") or "").strip(),
                url=product.get("href"),
                price_ils=product.get("price"),
                in_stock=product.get("stock"),  # already a bool in this API
                category_guess=category_label,
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )
