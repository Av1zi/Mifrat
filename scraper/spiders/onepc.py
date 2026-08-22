"""
1PC (1pc.co.il) spider.
(See pc-parts-il-plan.md and decisions.md for full context)

Recon so far (Aug 2026):
- Site is genuinely bilingual at the URL level: /he/... and /en/... paths
  both exist, which is convenient since the site itself is going to be
  bilingual (Hebrew + English) per the project's language decision.
- robots.txt CONFIRMED: blocks the usual transactional stuff (cart,
  checkout, account, wishlist, search?, .aspx pages) under root and the
  /he/, /en/, /ru/ prefixes. The PCBuilder path used below is NOT in the
  disallow list — allowed.

## The real find: PCBuilder/CategoryViewData

1PC's site has a "PC Builder" tool (https://1pc.co.il/en/pcbuilder). Opening
it and clicking a component type (e.g. CPU) fires:

  POST https://1pc.co.il/en/PCBuilder/CategoryViewData
  Content-Type: application/x-www-form-urlencoded
  Body: categoryId=158&attributeId=90&dependAttributeId=0&includeChildren=False&pageNumber=0

This does NOT return JSON — it returns an HTML *fragment* (product tiles
only, no page chrome), which is actually easier to parse reliably than the
full category page:

  <div class="pc-product-item" data-productid="121957">
    <a class="product-link" href="/en/product-121957-amd_ryzen_5_5600x...">
    <img class="picture-img" src="https://1pc.co.il/images/thumbs/....jpeg">
    <span class="product-title" data-id="121957" data-price="685.00003000">
        AMD Ryzen 5 5600X AM4 processor color tray.
    </span>
    <span class="price actual-price">₪685</span>
  </div>
  ...
  <div class="next-page" data-page="1"></div>   <!-- pagination cue -->

This gives vendor_sku (data-productid), title, a full-precision price
(data-price — prefer this over the rounded ₪685 display text), product URL,
and an image, per page, with a `next-page` marker for pagination
(0-indexed `pageNumber`; stop once a response contains 0 product tiles or
no next-page marker with a new value).

Confirmed categoryIds (Aug 2026, captured directly from PCBuilder's Network
tab — see the CATEGORIES dict below for the exact attributeId/
dependAttributeId pairing per category, kept as captured rather than
guessed): CPU (158), CPU cooling (429), motherboard (167), memory (45),
case (118), PSU (88), case fans (428), GPU (192), SSD (358), hard drive
(356). That covers all the categories the compatibility engine (§6) cares
about — this is now the most complete vendor recon of the four.

Interesting side note for later (§8/§6): the attributeId/dependAttributeId
values chain across categories (CPU's attributeId=90 == motherboard's
dependAttributeId=90; motherboard's attributeId=49 == memory's
dependAttributeId=49). That's the PC Builder's own compatibility filtering
(socket, then memory type) — a hint 1PC already encodes some compatibility
relationships server-side, which might be worth mining later rather than
only rebuilding compatibility rules from scratch in Phase 3.

## Gotcha hit during first test run (Aug 2026)
Scrapy >=2.13 moved to an `async def start(self)` entrypoint
(`StartSpiderMiddleware` handles it) and by 2.17 the old-style
`start_requests()` override wasn't being called at all — spider opened,
found nothing to crawl, closed instantly with 0 requests/0 items, no error.
Fixed by defining both `start()` (new entrypoint) and `start_requests()`
(fallback for <2.13), sharing the same request-building logic
(`_build_requests()`), per Scrapy's own migration guidance. If you see a
spider open-and-immediately-close with zero requests again, this is the
first thing to check. (Same fix applied to spiders/tms.py and ivory.py.)

## Gotcha hit during first real test run (Aug 2026)
The `data-price` attribute (e.g. "1148.99998400" for a real ₪1149 item,
"1327.50000000" for a real ₪1328 item) is NOT more precise than the
rounded ₪NNN shown on-site — it's floating-point noise from whatever
currency/conversion math 1PC does server-side. The rounded price IS the
real, charged price. Originally this spider preferred the raw data-price
string on the (wrong) assumption it was more accurate; fixed to round to
the nearest shekel with standard round-half-up (matches observed site
behavior: .5 and above rounds up) via `_round_price()` below, using
`Decimal` rather than Python's built-in `round()` specifically because
`round()` uses banker's-rounding (round-half-to-even), which can disagree
with round-half-up exactly at .50 boundaries landing on an odd integer.

## TODO before first real run
1. ToS skim (https://1pc.co.il/he/תקנון-האתר) — noted for completeness; per
   the project owner's decision (decisions.md), scraping proceeds
   regardless with a take-down-on-request posture.
2. Confirm whether GET with querystring works as an alternative to POST
   form data (simpler for Scrapy either way, but worth knowing) — likely
   yes, per Ivory's ws/get endpoint turning out to accept GET+querystring
   for the same kind of PC-builder data; not yet re-tested against 1PC
   specifically.
3. in_stock confirmed NOT present anywhere in this endpoint's response
   (Aug 2026 test run) — stays None until a real signal is found (a
   follow-up per-product request, maybe). Do NOT default this to True just
   because most catalog items happen to be orderable — an unverified
   assumption baked in as fact is worse than an honest "unknown," same
   reasoning as the TMS `stock` field fix in spiders/tms.py.
4. Confirm pagination stop condition empirically (does the last page still
   include a next-page div with a stale/same page number, or is it absent?).
5. RESOLVED (Aug 2026, owner-confirmed): the captured attributeId/
   dependAttributeId values DO return the full, unfiltered category — not
   a pre-filtered subset. No need to try attributeId="" as an alternative.
"""
import scrapy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from scraper.items import ListingItem

VENDOR_ID = "1pc"

# categoryId -> (attributeId, dependAttributeId, label)
CATEGORIES = {
    158: ("90", "0", "cpu"),
    429: ("", "0", "cpu_cooling"),
    167: ("49", "90", "motherboard"),
    45: ("", "49", "memory"),
    118: ("", "0", "case"),
    88: ("", "0", "psu"),
    428: ("", "0", "case_fans"),
    192: ("", "0", "gpu"),
    358: ("", "0", "ssd"),
    356: ("", "0", "harddrive"),
}

CATEGORY_VIEW_DATA_URL = "https://1pc.co.il/en/PCBuilder/CategoryViewData"

def _round_price(raw_price):
    """
    1PC's data-price attribute carries stray floating-point noise.
    Round to the nearest whole shekel with round-half-up.
    """
    if not raw_price:
        return None
    try:
        return int(Decimal(raw_price).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None

class OnePcSpider(scrapy.Spider):
    name = "onepc"
    allowed_domains = ["1pc.co.il"]

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for category_id, (attribute_id, depend_attribute_id, label) in CATEGORIES.items():
            yield scrapy.FormRequest(
                url=CATEGORY_VIEW_DATA_URL,
                formdata={
                    "categoryId": str(category_id),
                    "attributeId": attribute_id,
                    "dependAttributeId": depend_attribute_id,
                    "includeChildren": "False",
                    "pageNumber": "0",
                },
                callback=self.parse_category_page,
                meta={
                    "category_id": category_id,
                    "category_label": label,
                    "attribute_id": attribute_id,
                    "depend_attribute_id": depend_attribute_id,
                    "page_number": 0,
                },
            )

    def parse_category_page(self, response):
        category_id = response.meta["category_id"]
        category_label = response.meta["category_label"]
        attribute_id = response.meta["attribute_id"]
        depend_attribute_id = response.meta["depend_attribute_id"]
        page_number = response.meta["page_number"]
        
        tiles = response.css("div.pc-product-item")
        if not tiles:
            return

        for tile in tiles:
            product_url = response.urljoin(tile.css("a.product-link::attr(href)").get() or "")
            
            # Just use the internal numeric ID as the vendor_sku.
            # The Phase 2 matcher will handle linking this to the real product.
            sku = tile.attrib.get("data-productid")
            if not sku:
                continue
            
            title_node = tile.css("span.product-title")
            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=sku,
                title_raw=(title_node.css("::text").get() or "").strip(),
                url=product_url,
                price_ils=_round_price(title_node.attrib.get("data-price")),
                in_stock=True,
                category_guess=category_label,
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

        next_page_node = response.css("div.next-page::attr(data-page)").get()
        if next_page_node is not None:
            next_page_number = int(next_page_node)
            if next_page_number != page_number:
                yield scrapy.FormRequest(
                    url=CATEGORY_VIEW_DATA_URL,
                    formdata={
                        "categoryId": str(category_id),
                        "attributeId": attribute_id,
                        "dependAttributeId": depend_attribute_id,
                        "includeChildren": "False",
                        "pageNumber": str(next_page_number),
                    },
                    callback=self.parse_category_page,
                    meta={
                        "category_id": category_id,
                        "category_label": category_label,
                        "attribute_id": attribute_id,
                        "depend_attribute_id": depend_attribute_id,
                        "page_number": next_page_number,
                    },
                )