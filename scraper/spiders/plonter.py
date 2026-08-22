"""
Plonter spider.

## robots.txt: NOT observed for this project (see decisions.md). This
spider deliberately hits a path (`/pnp/alon.tmpl`) that Plonter's
robots.txt disallows (`Disallow: /pnp/`) — an intentional, documented
decision, not an oversight. See settings.py (ROBOTSTXT_OBEY = False).

## Canonical domain: plonter.co.il only

plonter.com/main.tmpl was also checked and appears to serve the same
content without redirecting — a genuinely separate, independently-served
site rather than a mirror. Only plonter.co.il has been characterized. Do
not point this spider at plonter.com without separately re-verifying it.

## The data source: /pnp/alon.tmpl — full catalog feed

  GET https://www.plonter.co.il/pnp/alon.tmpl

Response is windows-1255-encoded HTML containing one `<pre>` tag per row
(the first `<pre>` is the tab-separated header):

  sku  title  description  category  division  shelf  price_total  tree
  image_file  amount  engdivision

Entire catalog in one response — no pagination.

## Product URL (RESOLVED, Aug 2026 — see PlonterFindings.md)

  https://www.plonter.co.il/detail.tmpl?sku={sku}

Confirmed directly from Plonter's own recon doc, not guessed. Previously
this spider shipped with url=None; that gap is closed below.

## `tree` field (not yet used downstream, worth keeping)

Space-separated list of internal category IDs per listing (e.g. `ACAM4`
for AMD AM4 CPUs, `B1700D5ATX` for Intel LGA1700 DDR5 ATX boards) — a much
finer-grained taxonomy than `category`/`division`. PlonterFindings.md has
the full ID->meaning table. Not consumed by this spider yet; flagged here
so normalize_and_match.py (§8/matching) can use `tree` as a strong
category/attribute signal instead of re-deriving it from title text.

## Known gaps (still open)
- `amount` blank in several sampled rows — unclear whether blank means
  "in stock, quantity not tracked" or "out of stock, 0 suppressed."
  Treating blank as unknown (in_stock=None) rather than assuming.
- Content spans well beyond PC-hardware (storage controllers, USB devices,
  etc.) — no filtering applied here; normalize_and_match.py should expect
  out-of-scope rows and filter by category/division/tree downstream.
- windows-1255 decoding confirmed fine on sampled rows, not yet checked
  against the full catalog for mojibake in less-common characters.

## Also available, not yet wired in
`/pnp/alonDT.tmpl` returns the category tree as JSON
(`categories['systems']['Platform']['subsystems']['Form Factor'][]` etc.,
per PlonterFindings.md). Not necessary for the raw scrape — noted here in
case the matcher wants richer category structure later.
"""
import scrapy
from datetime import datetime, timezone
from urllib.parse import quote
from scraper.items import ListingItem

VENDOR_ID = "plonter"

ALON_FEED_URL = "https://www.plonter.co.il/pnp/alon.tmpl"
PRODUCT_URL_TEMPLATE = "https://www.plonter.co.il/detail.tmpl?sku={sku}"

# Column order per the confirmed header row.
COLUMNS = [
    "sku", "title", "description", "category", "division",
    "shelf", "price_total", "tree", "image_file", "amount", "engdivision",
]


class PlonterSpider(scrapy.Spider):
    name = "plonter"
    allowed_domains = ["plonter.co.il"]
    start_urls = [ALON_FEED_URL]

    def parse(self, response):
        response = response.replace(encoding="windows-1255")
        pre_blocks = response.css("pre::text").getall()
        if len(pre_blocks) < 2:
            self.logger.warning("alon.tmpl returned no data rows — check the feed is still live.")
            return

        # First <pre> is the header; skip it.
        for raw_row in pre_blocks[1:]:
            fields = raw_row.strip("\r\n").split("\t")
            row = dict(zip(COLUMNS, fields))
            sku = row.get("sku")
            if not sku:
                continue

            amount_raw = (row.get("amount") or "").strip()
            in_stock = None
            if amount_raw.isdigit():
                in_stock = int(amount_raw) > 0

            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=sku,
                title_raw=row.get("title"),
                url=PRODUCT_URL_TEMPLATE.format(sku=quote(sku)),
                price_ils=row.get("price_total"),
                in_stock=in_stock,
                category_guess=row.get("division") or row.get("category"),
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )