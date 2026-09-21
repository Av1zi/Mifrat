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

try:
    from scraper.display_specs import build_display_specs
except ImportError:
    from display_specs import build_display_specs

SITE_DIR = Path(__file__).resolve().parent.parent / "data" / "site"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "data" / "images"


def _image_vendor_key(vendor_id: str | None) -> str:
    """Same normalization as the image downloader's folders on disk."""
    return "onepc" if vendor_id in ("1pc", "onepc") else (vendor_id or "")


def _safe_image_stem(vendor_sku: str) -> str:
    """Filename stem for a vendor SKU with invisible/dangerous characters
    stripped. Scraped SKUs occasionally carry Unicode bidi marks or other
    format/control characters (Sep 2026: a TMS SKU starting with U+200E
    LEFT-TO-RIGHT MARK). Such names survive on one OS but become
    uncommittable/unfetchable elsewhere — git silently skipped the file
    entirely, so the product 404'd on every platform except the machine
    that downloaded it. Stripping Cf/Cc keeps the name byte-stable for
    every normal SKU (no churn) while making odd ones portable.

    MUST stay in sync with the downloader: both sides derive the on-disk
    path through this helper, never from the raw SKU.
    """
    import unicodedata

    return "".join(
        ch for ch in vendor_sku if unicodedata.category(ch) not in ("Cf", "Cc")
    )


def _local_image_path(vendor_id: str | None, vendor_sku: str | None,
                      thumb: bool = False) -> str | None:
    """Same-origin /images/... URL when the scraped file exists on disk.

    thumb=True addresses the 128px list-thumbnail derivative under
    data/images/<vendor>/thumbs/ (served from /images/<vendor>/thumbs/).
    """
    if not vendor_sku:
        return None
    filename = f"{_safe_image_stem(vendor_sku)}.jpg"
    vendor = _image_vendor_key(vendor_id)
    if thumb:
        if (IMAGES_DIR / vendor / "thumbs" / filename).is_file():
            return f"/images/{vendor}/thumbs/{quote(filename)}"
        return None
    if (IMAGES_DIR / vendor / filename).is_file():
        return f"/images/{vendor}/{quote(filename)}"
    return None


# Remotes dropped by _resolve_image during the current write_site_data()
# run — reported once per run so listing-thumbnail coverage gaps stay
# visible until backfilled (see download_images --from-catalog).
_DROPPED_REMOTES: list[str] = []


def _resolve_image(product: dict, offers: list[dict]) -> tuple[str | None, str | None]:
    """
    Local-only: return (image, thumb) — our own hosted cover
    (data/images/<vendor>/<sku>.jpg, served from /images/...) plus its
    128px list-thumbnail derivative (data/images/<vendor>/thumbs/,
    served from /images/<vendor>/thumbs/), or None for either.

    No remote-vendor fallback — hotlinking leaks visitor IPs to vendor
    hosts, breaks when vendors move their images, and defeats the
    frontend's same-origin image policy (see safeImageUrl). Products
    without a local photo fall back to the existing initials thumb in
    the UI (thumbHtml/thumbLabel), so None is a safe, renderable state.
    """
    current = product.get("image_url")
    raw_offers = product.get("offers", [])

    chosen: dict | None = None
    if current:
        for offer in raw_offers:
            if offer.get("image_url") == current:
                local = _local_image_path(
                    offer.get("vendor_id"), str(offer.get("vendor_sku") or "")
                )
                if local:
                    chosen = offer
                    break
    if chosen is None:
        for offer in raw_offers:
            local = _local_image_path(
                offer.get("vendor_id"), str(offer.get("vendor_sku") or "")
            )
            if local:
                chosen = offer
                break

    if chosen is not None:
        image = _local_image_path(
            chosen.get("vendor_id"), str(chosen.get("vendor_sku") or ""))
        thumb = _local_image_path(
            chosen.get("vendor_id"), str(chosen.get("vendor_sku") or ""),
            thumb=True)
        return image, thumb

    _dropped_remote = product.get("image_url")
    if _dropped_remote and isinstance(_dropped_remote, str) and _dropped_remote.startswith("http"):
        _DROPPED_REMOTES.append(str(_dropped_remote))
    return None, None


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


# Attribute keys the browser actually consumes: checkbox filters and table
# columns (site/src/specs.ts FILTER_ALLOWLIST/SPEC_PRIORITY), variant pills
# (views/product.ts VARIANT_KEY_PRIORITY + VARIANT_IDENTITY_KEYS) and the
# compatibility engine (site/src/build.ts). When a curated display_specs
# sheet exists (scraper/display_specs.py), the raw blob is trimmed to this
# set so data/site/*.json doesn't ship the same facts twice plus hundreds
# of deep-trivia keys (Sep 2026: motherboard.json blew past the 1MB size
# guard with both copies at full width). catalog.json always keeps the
# complete blob — this trim is site-JSON only.
_SITE_ATTR_KEYS = frozenset({
    # identity / QA
    "brand", "model", "mpn", "upc", "bundle_only",
    # cpu
    "cores", "threads", "base_clock_ghz", "boost_clock_ghz", "l2_cache",
    "l3_cache", "tdp", "tdp_w", "socket", "generation", "tier",
    "microarchitecture", "integrated_graphics", "smt", "ecc_support",
    "cooler_included", "packaging", "codename", "manufacturing_process",
    "launch", "series", "unlocked",
    # memory / shared
    "memory_type", "memory_slots", "memory_max", "capacity_gb", "total_gb",
    "modules", "module_count", "module_size_gb", "speed_mhz", "cas_latency",
    "timings", "first_word_latency_ns", "voltage", "heat_spreader",
    "modules_height", "registered", "memory",
    # motherboard
    "chipset", "wifi", "wifi_standard", "lan", "usb_ports", "m2_slots",
    "sata_ports", "pcie_x16_slots", "display_outputs", "fan_headers",
    "raid_level",
    # gpu
    "gpu_chip", "gpu_vendor", "vram_gb", "interface", "pcie_gen",
    "length_mm", "gpu_length_mm", "slot_width", "power_connections",
    "cooling", "fan_count", "hdmi_ports", "displayport_ports", "dvi_ports",
    "core_clock_mhz", "memory_clock_mhz", "boost_clock_mhz",
    # storage
    "drive_type", "drive_form_factor", "nvme", "rpm", "read", "write",
    "cache_mb", "tbw", "nand", "controller",
    # psu
    "wattage", "wattage_w", "efficiency", "modular", "atx_version",
    "fanless", "sata_connectors", "pcie_power_connectors",
    "cpu_power_connectors",
    # case / cooling
    "side_panel", "power_supply", "max_gpu_length_mm",
    "maximum_video_card_length", "supported_radiator_mm", "radiator_size_mm",
    "cooler_height_mm", "fan_size_mm", "airflow", "noise_level", "pwm",
    "fans_per_pack", "socket_compat", "internal_25_bays", "internal_35_bays",
    "front_io", "external_volume_l", "dimensions", "weight",
    # compat extras (build.ts reads these off attributes)
    "cpu_socket", "sockets", "power_consumption", "max_power",
    "rated_power", "total_power",
    # generic
    "accessory_type", "form_factor", "color", "lighting", "argb", "rgb",
})


def _trim_offer(offer: dict) -> dict:
    # min_price/sorting use the regular price only — promo_price is a
    # conditional side-column (whole-PC deal) and must never set the min.
    trimmed = {
        "vendor": offer.get("vendor_id"),
        "url": offer.get("url"),
        "price": offer.get("price_ils"),
        "in_stock": bool(offer.get("in_stock")),
        "last_seen": offer.get("last_seen"),
        "stale": bool(offer.get("stale")),
    }
    # Local first so the None-guard narrows the type for the checker
    # (a second offer.get() call cannot be narrowed).
    promo_raw = offer.get("price_promo_ils")
    if promo_raw is not None:
        try:
            trimmed["promo_price"] = int(
                float(str(promo_raw).replace(",", "").strip())
            )
        except (TypeError, ValueError):
            pass
    if offer.get("promo_kind"):
        trimmed["promo_kind"] = str(offer.get("promo_kind"))
    return trimmed


def _trim_product(product: dict) -> dict:
    offers = [_trim_offer(o) for o in product.get("offers", [])]
    offers.sort(key=lambda o: (o["price"] is None, o["price"]))

    in_stock_prices = [o["price"] for o in offers if o["in_stock"] and o["price"] is not None]
    any_prices = [o["price"] for o in offers if o["price"] is not None]
    min_price = min(in_stock_prices) if in_stock_prices else (min(any_prices) if any_prices else None)

    # 128px list-thumbnail derivative (local-only, like image above).
    # Omitted when the thumb file hasn't been generated yet — callers
    # fall back to image.
    _image, _thumb = _resolve_image(product, product.get("offers", []))

    # Curated spec sheet first: when present, the raw attribute blob is
    # trimmed to the keys the browser uses (filters/columns/variants/
    # compat) so the payload doesn't carry the full ~800-key blob plus a
    # formatted copy of it.
    display_specs = build_display_specs(
        product.get("category", ""), product.get("attributes", {}))
    attributes = product.get("attributes", {})
    if display_specs:
        attributes = {k: v for k, v in attributes.items()
                      if k in _SITE_ATTR_KEYS}

    trimmed = {
        "id": product["product_id"],
        "name": product.get("canonical_name"),
        "category": product["category"],
        "brand": product.get("brand"),
        "model": product.get("model"),
        "image": _image,
        "attributes": attributes,
        "vendor_count": product.get("vendor_count", len(offers)),
        "min_price": min_price,
        "in_stock": any(o["in_stock"] for o in offers),
        "offers": offers,
    }
    if _thumb:
        trimmed["thumb"] = _thumb

    # Optional pcpartdb reference-spec block (scraper/matching.py's
    # enrich_products_with_pcpartdb, Aug 2026). Only present on products
    # that got a confident match, so most products don't carry this key at
    # all — cheap to include, and this is exactly the kind of field that's
    # easy to forget here since _trim_product() is an explicit whitelist,
    # not a passthrough.
    # Vendor spec prose (matching.build_description — the long Plonter
    # dash-dump title the short canonical name was cut from). Only present
    # when it adds information beyond the name; the product page renders it
    # under the title.
    description = product.get("description")
    if isinstance(description, str) and description.strip():
        trimmed["description"] = description.strip()

    pcpartdb = product.get("pcpartdb")
    if pcpartdb:
        trimmed["pcpartdb"] = pcpartdb

    pckombo = product.get("pckombo")
    if pckombo:
        trimmed["pckombo"] = pckombo

    if product.get("duplicate_vendors"):
        trimmed["duplicate_vendors"] = sorted(product["duplicate_vendors"])

    # Curated spec sheet — computed at the top of this function so the raw
    # `attributes` blob could be trimmed against it; attached here so the
    # trimmed dict field order stays stable.
    if display_specs:
        trimmed["display_specs"] = display_specs

    return trimmed


def write_site_data(catalog: dict, site_dir: Path = SITE_DIR) -> dict:
    """
    Writes data/site/<category>.json + data/site/meta.json from an
    already-built catalog dict (as returned by normalize_and_match.build_catalog).
    Returns the meta dict that was written, mainly so callers can log a
    summary without re-reading the file.
    """
    _DROPPED_REMOTES.clear()
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

    # Lightweight global lookup (Phase 6): [id, category, min_price,
    # brand, name] per product (~500KB minified vs ~4.4MB of category
    # JSON). Powers instant global search (match on id/brand/category/
    # name without fetching any category file) and build-part resolution
    # (group wanted ids by category, fetch only those files). Built from
    # the trimmed rows so min_price matches the site exactly.
    index_rows: list[list] = []
    for category, items in by_category.items():
        for item in items:
            index_rows.append([
                item["id"],
                category,
                item["min_price"],
                item.get("brand"),
                item.get("name"),
            ])
    index_rows.sort(key=lambda row: str(row[0]))
    _write_json_atomic(site_dir / "index.json", index_rows)

    meta = {
        "generated_at": catalog["generated_at"],
        "skipped_vendors": catalog.get("skipped_vendors", []),
        "categories": categories_meta,
    }

    _write_json_atomic(site_dir / "meta.json", meta)

    # Public QA list for the #/qa page: duplicate same-vendor listings under
    # review. Built from the trimmed products (not review_queue.json, which
    # is never shipped to the site). copy-data.mjs copies the whole
    # directory, so no script change is needed.
    qa_cases: list[dict] = []
    for product in catalog["products"]:
        dup_vendors = product.get("duplicate_vendors") or []
        if not dup_vendors:
            continue
        by_vendor: dict[str, list[dict]] = {}
        for o in product.get("offers", []):
            by_vendor.setdefault(str(o.get("vendor_id") or ""), []).append(o)
        for vendor in sorted(dup_vendors):
            olist = by_vendor.get(vendor, [])
            qa_cases.append(
                {
                    "kind": "duplicate_vendor",
                    "product_id": product.get("product_id"),
                    "category": product.get("category"),
                    "vendor": vendor,
                    "offers": [
                        {
                            "listing_key": o.get("listing_key"),
                            "vendor_sku": o.get("vendor_sku"),
                            "title": o.get("title_raw"),
                            "price": o.get("price_ils"),
                        }
                        for o in olist
                    ],
                }
            )
    # Naming-conflict cases (tier-4c flags): same compact MPN, but the
    # offers' titles disagree on the model. Same offer shape plus the
    # conflicting titles, so #/qa renders both kinds uniformly.
    for product in catalog["products"]:
        if not product.get("naming_conflict"):
            continue
        qa_cases.append(
            {
                "kind": "naming_conflict",
                "product_id": product.get("product_id"),
                "category": product.get("category"),
                "vendor": "",
                "titles": list(
                    (product.get("attribute_conflicts") or {}).get(
                        "model_titles", [])
                ),
                "offers": [
                    {
                        "listing_key": o.get("listing_key"),
                        "vendor_sku": o.get("vendor_sku"),
                        "title": o.get("title_raw"),
                        "price": o.get("price_ils"),
                    }
                    for o in product.get("offers", [])
                ],
            }
        )
    qa_cases.sort(
        key=lambda c: (str(c.get("category") or ""), str(c.get("product_id") or ""))
    )
    _write_json_atomic(
        site_dir / "qa.json",
        {"generated_at": catalog["generated_at"], "cases": qa_cases},
    )

    # Categories that existed before this run but no longer do (e.g. a
    # category emptied out) would otherwise leave a stale, orphaned file
    # behind forever since we only ever write, never clean up.
    current_files = {f"{c['id']}.json" for c in categories_meta}
    for existing in site_dir.glob("*.json"):
        if existing.name in ("meta.json", "qa.json", "index.json"):
            continue
        if existing.name not in current_files:
            existing.unlink()

    # Local-only regression guard: no built site JSON may reference a
    # remote http(s) image. _resolve_image() already returns None instead
    # of a remote fallback, so any hit here means a new code path is
    # leaking vendor URLs — fail loudly rather than shipping hotlinks.
    remote_hits = _count_remote_images(site_dir)
    total_products = sum(len(v) for v in by_category.values())
    with_local = sum(
        1 for v in by_category.values() for p in v if p.get("image")
    )
    print(
        f"[images] local {with_local}/{total_products} products have a photo; "
        f"{len(_DROPPED_REMOTES)} remotes dropped (no local file yet — "
        f"backfill with: python -m scraper.download_images --from-catalog)"
    )
    if remote_hits:
        raise RuntimeError(
            f"[images] {remote_hits} remote \"image\":\"http\" references in "
            f"{site_dir} — local-only policy violated"
        )

    return meta


def _count_remote_images(site_dir: Path) -> int:
    """Post-write scan: count built files containing a remote image URL."""
    hits = 0
    for path in site_dir.glob("*.json"):
        if path.name == "meta.json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        hits += text.count('"image":"http')
        hits += text.count('"thumb":"http')
    history_dir = site_dir / "history"
    if history_dir.is_dir():
        for path in history_dir.glob("*.json"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            # History files carry no image fields today; guard anyway so a
            # future field can't reintroduce hotlinks silently.
            hits += text.count('"image":"http')
            hits += text.count('"thumb":"http')
    return hits
