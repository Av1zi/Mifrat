"""
TMS (tms.co.il) spider.
robots.txt: NOT observed for this project (see pc-parts-il-plan.md §17
decision log, Aug 2026). This spider deliberately hits a path that TMS's
robots.txt disallows (`Disallow: /*configurator`) — that's an intentional,
documented decision, not an oversight. See settings.py (ROBOTSTXT_OBEY =
False) and the plan's decision log for the reasoning/caveats.

The data source: product/configurator/getProductByCategory
TMS's PC configurator (https://tms.co.il/index.php?route=product/configurator)
calls, per category:
GET https://tms.co.il/index.php?route=product/configurator/getProductByCategory
&category_id=10001&attribute_value_id=0&sort_type=1
&heightForCoolerCase=0&memory_type_value_id=0
...and gets back a clean JSON payload, one object per product:
{
 "products ": [
{
 "product_id ":  "105950 ",
 "category_id ": 10001,
 "socket ":  "1200 ",
 "manufacturer ":  "Intel ",
 "name ":  "Intel Core i3 10105F / 1200 Box  ",
 "stock ": false,
 "model ":  "C10105FB ",
 "price ": 188,
 "href ":  "https://tms.co.il/intel-core-i3-10105f-1200-box ",
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

Gotcha hit during first test run (Aug 2026): Scrapy start() entrypoint
Scrapy >=2.13 moved to an `async def start(self)` entrypoint
(`StartSpiderMiddleware` handles it) and by 2.17 the old-style
`start_requests()` override wasn't being called at all — spider opened,
found nothing to crawl, closed instantly with 0 requests/0 items, no error.
Fixed by defining both `start()` (new entrypoint) and `start_requests()`
(fallback for <2.13), sharing the same request-building logic, per Scrapy's
own migration guidance. If you see a spider open-and-immediately-close with
zero requests again, this is the first thing to check.

Gotcha hit during first real test run (Aug 2026): `stock` field is unreliable
The  `stock`  boolean came back  `false`  for every product in a real test run,
including items confirmed purchasable on the live site — so this field
does NOT reliably indicate purchasability from this endpoint (possibly  it
reflects literal physical-warehouse stock only, distinct from
 "orderable, " or is simply not populated by this particular endpoint; the
separate per-branch  `claris/availability`  endpoint noted above might be
the real signal, but that's a per-product/per-branch call, not a
category-level one). Rather than confidently report a value we know is
sometimes wro ng,  `in_stock`  is set to  `None`  (unknown) here instead of
passing  `stock`  through — a wrong  "definitely out of stock " is worse than
an honest  "unknown, " especially for a price-comparison site where a false
out-of-stock reading actively steers someone away from a real option.
 `stock_status`  is captured in the raw JSON but not yet mapped to anything;
worth a look if a real in_stock signal is needed later.

TODO before first real run
ToS skim — noted for completeness; per the project owner's Aug 2026
decision (see pc-parts-il-plan.md §17), scraping is proceeding regardless
with a take-down-on-request posture, so this is no longer a blocking step.
Find a reliable in_stock signal — `stock` is confirmed unreliable (see
above). Candidates: the product detail page itself, or the per-branch
`claris/availability` endpoint (would need one call per product/SKU,
not per category — a real cost tradeoff to weigh before adopting it).
Confirm pagination — the captured responses weren't confirmed to be a
complete category or just a first page; check for a total-count field or
whether category size ever exceeds what one call returns.
"""
import json
import scrapy
from datetime import datetime, timezone
from scraper.items import ListingItem

VENDOR_ID = "tms"
CONFIGURATOR_URL = "https://tms.co.il/index.php?route=product/configurator"

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

    async def start(self):
        # Scrapy >=2.13 entrypoint (StartSpiderMiddleware calls this, not
        # start_requests() anymore — see the note at the top of this file).
        for request in self._build_requests():
            yield request

    def start_requests(self):
        # Fallback for Scrapy <2.13, which doesn't call start() at all.
        # Shares the same request-building logic as start() above so the
        # two can't drift out of sync.
        yield from self._build_requests()

    def _build_requests(self):
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
        # --- NEW: Catch 403 Forbidden errors explicitly ---
        if response.status == 403:
            self.logger.error(
                f"Blocked by WAF/Server! Status: {response.status}, URL: {response.url}"
            )
            # Optional: uncomment the next line to see the HTML error page in logs
            # self.logger.debug(f"Response text: {response.text[:500]}")
            return

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
                in_stock=None,  # `stock` field confirmed unreliable — see docstring gotcha
                category_guess=category_label,
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )
