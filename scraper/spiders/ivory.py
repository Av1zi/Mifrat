"""
Ivory (ivory.co.il) spider.

## robots.txt CONFIRMED: remarkably permissive — only two rules for
User-agent: * — Disallow: /files/banners/ and Disallow: /catalog_compare.php.
Nothing this spider hits is disallowed; the project's robots.txt-disregard
decision isn't even needed here.

## The API (Aug 2026, see IvoryFindings.md + owner confirmation)

Ivory's PC-builder tool exposes an internal JSON API, same pattern as
TMS's configurator and 1PC's CategoryViewData — CONFIRMED as a plain GET
with query params (not POST form data as originally assumed):

  GET https://www.ivory.co.il/computer/{platform}/ws/get
      ?source_parent={id}&selectedProds=%5B%5D

  platform: "intel" or "amd" — BOTH confirmed directly (Intel from the
  original recon, AMD confirmed by owner: source_parent=2675 works at
  computer/amd/ws/get exactly like the Intel endpoint).

`selectedProds=[]` CONFIRMED (owner tested) to return the full unfiltered
category on both Ivory and 1PC — not a narrowed default view. No more
guessing on that front.

Response is JSON: `Build.categories[]`, each category has a `products`
dict keyed `"itm-<id>"`, e.g.:

  {
    "id": 43970, "title": "מעבד Intel® Core™ i3-12100...",
    "barcode": "I3-12100", "parent": 2674, "price": 499,
    "picture": "files/catalog/reg/....webp", "cuts": [...], ...
  }

`barcode` CONFIRMED to just be the vendor SKU (owner checked — not some
separate internal code). `id` is the numeric product id, and CONFIRMED
(owner checked view-source) to be exactly what resolves the product page:

  https://www.ivory.co.il/catalog.php?id={id}

## Shared categories — only request once, not per platform

Cooling, RAM, storage, GPU, PSU, case, and case fans use the SAME
source_parent regardless of platform and CONFIRMED (owner checked) to
return the identical full set either way — no need to hit them under both
intel and amd. Only CPU and motherboard are genuinely platform-specific
(different socket, different source_parent). CATEGORIES below reflects
this: shared categories appear once, arbitrarily under the "intel" URL
since that's just where they happen to live, not because they're
Intel-specific data.

## Stock status

The API payload does not contain an explicit stock field. However,
products that appear in the response are available for purchase.
Therefore we set `in_stock = True` for every yielded item.
"""
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

import scrapy

from scraper.items import ListingItem

VENDOR_ID = "ivory"

WS_GET_URL = "https://www.ivory.co.il/computer/{platform}/ws/get"
PRODUCT_URL_TEMPLATE = "https://www.ivory.co.il/catalog.php?id={id}"

# (category_guess, platform, source_parent)
# CPU/motherboard are genuinely platform-specific (different socket).
# Everything else is shared across platforms — requested once, not twice.
CATEGORIES = [
    ("cpu", "intel", 2674),
    ("cpu", "amd", 2675),
    ("motherboard", "intel", 2653),
    ("motherboard", "amd", 2676),
    ("cpu_cooler_air", "intel", 6083),
    ("cpu_cooler_aio", "intel", 11656),
    ("ram", "intel", 2649),
    ("ssd", "intel", 2672),
    ("hdd", "intel", 2720),
    ("gpu", "intel", 2652),
    ("psu", "intel", 5347),
    ("case", "intel", 2628),
    ("case_fans", "intel", 6084),
]


class IvorySpider(scrapy.Spider):
    name = "ivory"
    allowed_domains = ["ivory.co.il"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_ids = set()  # defensive — categories shouldn't overlap now, but cheap to keep
        self._requests = len(CATEGORIES)
        self._failed_403 = 0

    async def start(self):
        for request in self._build_requests():
            yield request

    def start_requests(self):
        # Fallback for Scrapy <2.13 — see onepc.py/tms.py for why both
        # entrypoints are defined; the async start() one is what actually
        # runs on 2.17.
        yield from self._build_requests()

    def _build_requests(self):
        for category_guess, platform, source_parent in CATEGORIES:
            qs = urlencode({"source_parent": source_parent, "selectedProds": "[]"})
            url = f"{WS_GET_URL.format(platform=platform)}?{qs}"
            yield scrapy.Request(
                url,
                callback=self.parse,
                cb_kwargs={"category_guess": category_guess, "platform": platform},
                errback=self._request_failed,
            )

    def parse(self, response, category_guess, platform):
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning(
                "[ivory] non-JSON response for %s/%s (status %s) — skipping",
                platform, category_guess, response.status,
            )
            return

        categories = (data.get("Build") or {}).get("categories") or []
        for cat in categories:
            products = cat.get("products") or {}
            for prod in products.values():
                pid = prod.get("id")
                if pid is None or pid in self._seen_ids:
                    continue
                self._seen_ids.add(pid)

                # The builder API returns a per-product `picture` path
                # (e.g. "files/catalog/reg/....webp") — free photo coverage
                # for every listing without opening the detail page. Detail
                # og:image still wins when present (see _merge_detail_specs).
                picture = prod.get("picture")
                image_url = (
                    response.urljoin(picture)
                    if picture
                    else None
                )

                yield ListingItem(
                    vendor_id=VENDOR_ID,
                    vendor_sku=prod.get("barcode"),
                    title_raw=prod.get("title"),
                    url=PRODUCT_URL_TEMPLATE.format(id=pid),
                    price_ils=prod.get("price"),
                    # All products returned are available for sale
                    in_stock=True,
                    category_guess=category_guess,
                    image_url=image_url,
                    vendor_meta={
                        "description": prod.get("description"),
                        "parent": prod.get("parent"),
                        # Builder's per-product compatibility/feature tags —
                        # decoded downstream via data/ivory_cut_labels.json
                        # (see IvoryFindings.md, scraper/build_ivory_cut_labels.py).
                        "cuts": prod.get("cuts"),
                    },
                    scraped_at=datetime.now(timezone.utc).isoformat(),
                )

    def _request_failed(self, failure):
        status = getattr(getattr(failure.value, "response", None), "status", None)
        if status == 403:
            self._failed_403 += 1
        self.logger.warning(
            "[ivory] request failed: %s — that category's items are "
            "skipped, nothing else is affected", failure.value,
        )

    def closed(self, reason):
        # Uniform 403 = datacenter-IP block, not flaky categories. Say so
        # explicitly: the per-category warnings above bury this, and the
        # run_spider zero-items error that follows doesn't name the cause.
        # Policy (same class as TMS §7 / KSP WAF): do NOT retry against it,
        # do not add proxies — stale-forward covers 14 days, just wait.
        if self._requests and self._failed_403 >= self._requests:
            self.logger.error(
                "[ivory] ALL %d requests got 403 — Ivory is blocking this "
                "IP (datacenter ban). Nothing is broken on our side; the "
                "catalog stale-forwards Ivory for up to 14 days. "
                "Do not retry/proxy — check back in a few days.",
                self._requests,
            )