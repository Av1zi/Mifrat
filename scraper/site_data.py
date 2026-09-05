"""
Builds the static site's data layer from the catalog the normalizer just
produced: one small JSON file per category (data/site/<category>.json) plus
an index (data/site/meta.json), instead of shipping the single ~20MB
data/catalog.json to browsers.

data/catalog.json stays exactly as-is (full listings + products, indent=2,
kept for debugging/history/tooling). These are a derived, client-optimized
view of catalog["products"] only — trimmed fields, one file per category,
minified (no indent: these are fetched over the network on every page
view, so transfer size matters more than git-diff readability here; see
decisions.md).

Usage: called from normalize_and_match.py's main() right after catalog.json
is built, so it never has to re-parse the 20MB file.
"""

import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

SITE_DIR = Path(__file__).resolve().parent.parent / "data" / "site"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "data" / "images"


def _image_vendor_key(vendor_id: str | None) -> str:
    """Same normalization as the image downloader's folders on disk."""
    return "onepc" if vendor_id in ("1pc", "onepc") else (vendor_id or "")


def _local_image_path(vendor_id: str | None, vendor_sku: str | None) -> str | None:
    """Same-origin /images/... URL when the scraped file exists on disk."""
    if not vendor_sku:
        return None
    filename = f"{vendor_sku}.jpg"
    if (IMAGES_DIR / _image_vendor_key(vendor_id) / filename).is_file():
        return f"/images/{_image_vendor_key(vendor_id)}/{quote(filename)}"
    return None


def _resolve_image(product: dict, offers: list[dict]) -> str | None:
    """
    Prefer our own hosted copy (data/images/<vendor>/<sku>.jpg, served from
    /images/...) so vendor hosts can't break our photos by moving theirs.
    The offer that supplied the current image_url wins; otherwise the first
    offer with a downloaded file; otherwise the remote URL as fallback.
    """
    current = product.get("image_url")
    raw_offers = product.get("offers", [])

    if current:
        for offer in raw_offers:
            if offer.get("image_url") == current:
                local = _local_image_path(
                    offer.get("vendor_id"), str(offer.get("vendor_sku") or "")
                )
                if local:
                    return local

    for offer in raw_offers:
        local = _local_image_path(
            offer.get("vendor_id"), str(offer.get("vendor_sku") or "")
        )
        if local:
            return local

    return current


def _write_json_atomic(path: Path, value: object) -> None:
    """Replace derived output atomically so transient file locks do not truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        for attempt in range(3):
            try:
                os.replace(temp_path, path)
                return
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        temp_path.unlink(missing_ok=True)


def _trim_offer(offer: dict) -> dict:
    return {
        "vendor": offer.get("vendor_id"),
        "url": offer.get("url"),
        "price": offer.get("price_ils"),
        "in_stock": bool(offer.get("in_stock")),
        "last_seen": offer.get("last_seen"),
        "stale": bool(offer.get("stale")),
    }


def _trim_product(product: dict) -> dict:
    offers = [_trim_offer(o) for o in product.get("offers", [])]
    offers.sort(key=lambda o: (o["price"] is None, o["price"]))

    in_stock_prices = [o["price"] for o in offers if o["in_stock"] and o["price"] is not None]
    any_prices = [o["price"] for o in offers if o["price"] is not None]
    min_price = min(in_stock_prices) if in_stock_prices else (min(any_prices) if any_prices else None)

    trimmed = {
        "id": product["product_id"],
        "name": product.get("canonical_name"),
        "category": product["category"],
        "brand": product.get("brand"),
        "model": product.get("model"),
        "image": _resolve_image(product, product.get("offers", [])),
        "attributes": product.get("attributes", {}),
        "vendor_count": product.get("vendor_count", len(offers)),
        "min_price": min_price,
        "in_stock": any(o["in_stock"] for o in offers),
        "offers": offers,
    }

    # Optional pcpartdb reference-spec block (scraper/matching.py's
    # enrich_products_with_pcpartdb, Aug 2026). Only present on products
    # that got a confident match, so most products don't carry this key at
    # all — cheap to include, and this is exactly the kind of field that's
    # easy to forget here since _trim_product() is an explicit whitelist,
    # not a passthrough.
    pcpartdb = product.get("pcpartdb")
    if pcpartdb:
        trimmed["pcpartdb"] = pcpartdb

    pckombo = product.get("pckombo")
    if pckombo:
        trimmed["pckombo"] = pckombo

    return trimmed


def write_site_data(catalog: dict, site_dir: Path = SITE_DIR) -> dict:
    """
    Writes data/site/<category>.json + data/site/meta.json from an
    already-built catalog dict (as returned by normalize_and_match.build_catalog).
    Returns the meta dict that was written, mainly so callers can log a
    summary without re-reading the file.
    """
    by_category: dict[str, list[dict]] = defaultdict(list)

    for product in catalog["products"]:
        by_category[product["category"]].append(_trim_product(product))

    site_dir.mkdir(parents=True, exist_ok=True)

    categories_meta = []

    for category, items in by_category.items():
        items.sort(key=lambda x: (x["min_price"] is None, x["min_price"]))

        out_path = site_dir / f"{category}.json"
        _write_json_atomic(out_path, items)

        prices = [x["min_price"] for x in items if x["min_price"] is not None]
        categories_meta.append(
            {
                "id": category,
                "count": len(items),
                "min_price": min(prices) if prices else None,
                "max_price": max(prices) if prices else None,
            }
        )

    categories_meta.sort(key=lambda c: c["id"])

    meta = {
        "generated_at": catalog["generated_at"],
        "skipped_vendors": catalog.get("skipped_vendors", []),
        "categories": categories_meta,
    }

    _write_json_atomic(site_dir / "meta.json", meta)

    # Categories that existed before this run but no longer do (e.g. a
    # category emptied out) would otherwise leave a stale, orphaned file
    # behind forever since we only ever write, never clean up.
    current_files = {f"{c['id']}.json" for c in categories_meta}
    for existing in site_dir.glob("*.json"):
        if existing.name != "meta.json" and existing.name not in current_files:
            existing.unlink()

    return meta
