"""
Shared Item schema across all vendor spiders.

Every spider (tms.py, ivory.py, onepc.py, plonter.py, and eventually ksp.py)
yields ListingItem instances. Keep this schema stable — the normalizer/matcher
(normalize_and_match.py) and everything downstream depends on it, and per the
plan (§7) adding/removing a vendor should never require touching this file.
"""
import scrapy

class DetailItem(scrapy.Item):
    vendor_id = scrapy.Field()
    vendor_sku = scrapy.Field()
    url = scrapy.Field()
    specs = scrapy.Field()        # dict[str, str]
    image_url = scrapy.Field()    # source URL, downloaded separately
    scraped_at = scrapy.Field()
    extra = scrapy.Field()        # optional, vendor-specific bonus fields

class ListingItem(scrapy.Item):
    # Identity of this raw listing
    vendor_id = scrapy.Field()  # e.g. "tms", "ivory", "1pc", "plonter"
    vendor_sku = scrapy.Field()  # vendor's own SKU/model code if exposed (prefer over title matching)
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

    # Optional structured specs harvested from vendor payloads (Phase 2B).
    # Ivory's PC-builder API carries per-product compatibility/features data
    # (description, parent, qty, cuts, properCuts); spiders may attach the raw
    # subset here for the extractor to prefer over title parsing.
    # Additive + optional: the schema-stability rule stands.
    vendor_meta = scrapy.Field()

    # Optional listing-level cover image harvested without opening the
    # product page (1PC tile <img>, Ivory API `picture`, Plonter feed
    # `image_file`, TMS tile <img>). Detail-scraped og:image (see
    # _merge_detail_specs) wins when both exist — it is full-resolution
    # while listing thumbnails are small — but this fallback takes photo
    # coverage from ~10% (detail-only) to near-100% for free.
    image_url = scrapy.Field()

    # Bookkeeping
    scraped_at = scrapy.Field()  # ISO 8601 UTC timestamp, set by the spider/pipeline