"""
Plonter spider.

## robots.txt: NOT observed for this project (see pc-parts-il-plan.md §17
decision log, Aug 2026). This spider deliberately hits a path
(`/pnp/alon.tmpl`) that Plonter's robots.txt disallows (`Disallow: /pnp/`)
— that's an intentional, documented decision, not an oversight. See
settings.py (ROBOTSTXT_OBEY = False) and the plan's decision log for the
reasoning/caveats.

## Canonical domain: plonter.co.il only

plonter.com/main.tmpl was also checked (Aug 2026) and appears to serve the
same content without redirecting — looks like a genuinely separate,
independently-served site rather than a mirror. We have only characterized
plonter.co.il (robots.txt, this feed). Do not point this spider at
plonter.com without separately re-verifying it there — don't assume
findings carry over between what look like duplicate domains.

## The data source: /pnp/alon.tmpl — full catalog feed

Plonter's own PC-builder tool (buildyourownpc-v2.tmpl) loads its entire
product list in one request:

  GET https://www.plonter.co.il/pnp/alon.tmpl

Response is windows-1255-encoded HTML containing one `<pre>` tag per row
(the first `<pre>` is the tab-separated header), e.g.:

  <pre>sku	title	description	category	division	shelf	price_total	tree	image_file	amount	engdivision</pre>
  <pre>DRW-08D6MT	DVD-RW drive...	ASUS	חלקי מחשב	DVD צורבים...	139	ZOPTICAL	DRW-08D6MT.jpg		CD DVD and Writers</pre>
  ...

This is the ENTIRE catalog in one response — no pagination, no per-category
requests needed. Columns observed: sku, title, description, category,
division, shelf, price_total, tree, image_file, amount, engdivision.

Known gaps:
- **No direct product URL in the feed.** Only sku/title/description/price/
  image — no slug or product-page link. TODO: either construct a guessed
  URL (unclear if there's a stable sku->URL pattern; not yet confirmed) or
  cross-reference against sitemap.xml to resolve sku -> real product URL
  before this can populate ListingItem.url properly. Leaving url=None for
  now rather than guessing wrong.
- `amount` is blank in several sampled rows — unclear yet whether blank
  means "in stock, quantity not tracked" or "out of stock, 0 suppressed."
  Treating blank as unknown (in_stock=None) rather than assuming either way.
- The `category`/`division`/`tree`/`engdivision` columns overlap in
  purpose — `category` is broad ("חלקי מחשב" = "computer parts") and same
  for every sampled row, `division`/`engdivision` look like the more useful
  fine-grained category signal. Using `division` for category_guess;
  revisit once more of the catalog has been eyeballed.
- Content spans well beyond PC-hardware-relevant components (storage
  controllers, USB devices, etc. showed up in the sample) despite the
  earlier assumption that Plonter is PC-parts-only like TMS/1PC — no
  filtering is applied here yet, so downstream normalize_and_match.py
  should expect some out-of-scope rows and filter by category/division
  rather than assuming everything from this feed is a PC-builder-relevant
  part.

## TODO before first real run
1. Resolve the product-URL gap (see above) — this is now the main blocker.
2. Confirm windows-1255 decoding is correct across the full response (the
   sample decoded fine but hasn't been checked against the full catalog for
   mojibake in less-common characters).
3. Decide whether to filter this spider's output to PC-hardware-relevant
   categories at scrape time, or let normalize_and_match.py do that
   filtering downstream (§8) — currently deferring to the latter.
"""
import scrapy
from datetime import datetime, timezone
from scraper.items import ListingItem

VENDOR_ID = "plonter"

ALON_FEED_URL = "https://www.plonter.co.il/pnp/alon.tmpl"

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

        # First <pre> is the header; skip it (COLUMNS above is the trusted
        # source of truth, but this is a cheap sanity check point if the
        # feed's column order ever changes).
        for raw_row in pre_blocks[1:]:
            fields = raw_row.strip("\r\n").split("\t")
            row = dict(zip(COLUMNS, fields))
            if not row.get("sku"):
                continue

            amount_raw = (row.get("amount") or "").strip()
            in_stock = None
            if amount_raw.isdigit():
                in_stock = int(amount_raw) > 0

            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=row.get("sku"),
                title_raw=row.get("title"),
                url=None,  # TODO: not present in this feed — see docstring
                price_ils=row.get("price_total"),
                in_stock=in_stock,
                category_guess=row.get("division") or row.get("category"),
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )
