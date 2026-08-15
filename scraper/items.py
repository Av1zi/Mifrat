"""
Shared Item schema across all vendor spiders.

Every spider (tms.py, ivory.py, onepc.py, plonter.py, and eventually ksp.py)
yields ListingItem instances. Keep this schema stable — the normalizer/matcher
(normalize_and_match.py) and everything downstream depends on it, and per the
plan (§7) adding/removing a vendor should never require touching this file.
"""
import scrapy


class ListingItem(scrapy.Item):
    # Identity of this raw listing
    vendor_id = scrapy.Field()       # e.g. "tms", "ivory", "1pc", "plonter"
    vendor_sku = scrapy.Field()      # vendor's own SKU/model code if exposed (prefer over title matching)
    url = scrapy.Field()

    # Raw signal — do NOT try to clean/parse this in the spider.
    # Title parsing belongs in normalize_and_match.py (§8), not here, so all
    # vendors feed the matcher identical raw material.
    title_raw = scrapy.Field()

    # Pricing / availability
    price_ils = scrapy.Field()
    in_stock = scrapy.Field()

    # Best-effort category guess from the vendor's own site structure
    # (breadcrumb / URL path). The canonical `category` lives in products.json
    # after matching — this is just a hint for the matcher.
    category_guess = scrapy.Field()

    # Bookkeeping
    scraped_at = scrapy.Field()      # ISO 8601 UTC timestamp, set by the spider/pipeline
