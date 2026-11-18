"""
Ivory Eilat prices (scraper/eilat.py) from Ivory's catalog category pages.

Ivory's PC-builder API (spiders/ivory.py) carries only the regular price, but
its category pages print the Eilat price on every tile the Eilat stores sell
(verified 2026-11-16):

    <a data-product-id="45329" ...>
      <div class="pricing-details no-left is-eilat no-sale">
        ... <span class="price ">599</span> ...
        <span class="tag-area ... eilatprice">מחיר באילת:</span>
        <span class="price eilatprice">507</span>

A tile on sale says "מחיר מבצע באילת" and shows the Eilat sale price, which is
the Eilat price that applies today. A tile without `is-eilat` / an eilatprice
amount is not sold at the Eilat stores (no row). Pages are
catalog.php?act=cat&id=<source_parent>&pg=N (pg counts from 0, 60 tiles a
page), following the page's own "next" link.

Only the Eilat price is read here. The product identity is Ivory's numeric
id, the same `catalog.php?id=` the listing spider writes, so normalize joins
the row to the regular listing by listing key. Cloud vendor: Ivory's
robots.txt allows these pages and the project ignores robots for cloud runs.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import scrapy

from scraper.eilat import EILAT_CHANNEL
from scraper.items import ListingItem
from scraper.spiders.ivory import CATEGORIES, PRODUCT_URL_TEMPLATE, VENDOR_ID

CATEGORY_URL = "https://www.ivory.co.il/catalog.php?act=cat&id={id}"
# Every builder category has well under this many pages (largest: 2).
MAX_PAGES = 10

_AMOUNT_RE = re.compile(r"[\d,]+")


def _amount(text: str | None) -> int | None:
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return None
    value = int(m.group(0).replace(",", "") or 0)
    return value or None


def parse_tiles(response) -> list[dict]:
    """(product id, regular price, Eilat price) per Eilat-priced tile."""
    out: list[dict] = []
    seen: set[str] = set()
    for anchor in response.css("a.product-anchor[data-product-id]"):
        pid = (anchor.attrib.get("data-product-id") or "").strip()
        if not pid.isdigit() or pid in seen:
            continue
        details = anchor.css("div.pricing-details")
        if not details:
            continue
        eilat = _amount(details.css("span.price.eilatprice::text").get())
        if eilat is None:
            continue
        seen.add(pid)
        # First non-Eilat price span: the regular price everyone else pays.
        regular = next((_amount(t) for t in details.css("span.price:not(.eilatprice)::text").getall()
                        if _amount(t)), None)
        title = " ".join(anchor.css(".title_product_catalog::text").getall()).strip()
        out.append({"id": pid, "regular": regular, "eilat": eilat, "title": title or None})
    return out


class IvoryEilatSpider(scrapy.Spider):
    name = "ivory_eilat"
    allowed_domains = ["ivory.co.il"]
    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOADER_MIDDLEWARES": {
            "scraper.crawl_outcome.StopOnBlockMiddleware": 950,
        },
        "RETRY_HTTP_CODES": [408, 500, 502, 503, 504],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen: set[str] = set()
        self._scraped_at = datetime.now(timezone.utc).isoformat()

    async def start(self):
        for request in self._build_requests():
            yield request

    def start_requests(self):
        yield from self._build_requests()

    def _build_requests(self):
        for category_guess, _platform, source_parent in CATEGORIES:
            yield scrapy.Request(
                CATEGORY_URL.format(id=source_parent),
                callback=self.parse,
                cb_kwargs={"category_guess": category_guess, "page": 0},
            )

    def parse(self, response, category_guess, page):
        tiles = parse_tiles(response)
        if page == 0 and not response.css("a.product-anchor[data-product-id]"):
            self.logger.warning("[ivory_eilat] no product tiles on %s - markup changed?", response.url)
        for tile in tiles:
            if tile["id"] in self._seen:
                continue
            self._seen.add(tile["id"])
            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=None,
                url=PRODUCT_URL_TEMPLATE.format(id=tile["id"]),
                title_raw=tile["title"],
                price_ils=tile["eilat"],
                in_stock=None,
                category_guess=category_guess,
                channel=EILAT_CHANNEL,
                vendor_meta={"regular_price": tile["regular"]},
                scraped_at=self._scraped_at,
            )
        next_url = response.css('a.page[aria-label="לדף הבא"]::attr(href)').get()
        if next_url and page + 1 < MAX_PAGES:
            yield response.follow(next_url, callback=self.parse,
                                  cb_kwargs={"category_guess": category_guess, "page": page + 1})
