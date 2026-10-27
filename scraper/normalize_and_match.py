"""
Normalizer + matcher: reads today's + recent raw per-vendor snapshots from
data/raw/YYYY-MM-DD/<vendor>.jsonl and builds data/catalog.json.

Phase 2:
- enriches listings with stable listing keys
- normalizes prices/categories
- builds canonical products
- writes optional fuzzy review queue to data/review_queue.json

Stale-forward rule:
If a vendor's raw snapshot is missing today, use the most recent snapshot
within the lookback window and mark those listings stale.

Usage (from the repo root):
python -m scraper.normalize_and_match
"""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

# Script-path invocation (`python scraper/normalize_and_match.py`, used by
# normalize-and-deploy.yml) puts scraper/ — not the repo root — on sys.path,
# so `from scraper...` fails and the fallback below loads site_data as a
# top-level module. Insert the repo root so the absolute imports work from
# both entrypoints (`python scraper/...` and `python -m scraper....`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scraper.matching import (
        dedupe_enriched_listings,
        enrich_listing,
        find_duplicate_vendor_cases,
        find_naming_conflict_cases,
        match_listings,
        match_text,
        mpn_affix_related,
        name_from_attributes,
        prefer_longer_mpn,
        suggest_fuzzy_matches,
    )
    from scraper.specs import build_product_specs, extract_attributes
    from scraper.site_data import write_site_data
    from scraper.build_price_history import build_price_history
    from scraper.image_urls import best_of, candidate_urls
except ImportError:
    from matching import (
        dedupe_enriched_listings,
        enrich_listing,
        find_duplicate_vendor_cases,
        find_naming_conflict_cases,
        match_listings,
        match_text,
        mpn_affix_related,
        name_from_attributes,
        prefer_longer_mpn,
        suggest_fuzzy_matches,
    )
    from specs import build_product_specs, extract_attributes
    from site_data import write_site_data
    from image_urls import best_of, candidate_urls  # type: ignore[no-redef]
    from build_price_history import build_price_history


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_PATH = DATA_DIR / "catalog.json"
REVIEW_PATH = DATA_DIR / "review_queue.json"
MANUAL_PATH = DATA_DIR / "matching" / "manual_products.json"
SITE_DIR = DATA_DIR / "site"

# Ivory is now included. If its raw file is missing, it is skipped gracefully.
# Plonter dropped 2026-09-29 (datacenter IP-class Incapsula block, two
# consecutive CI failures; owner decision — see decisions.md). Its spider +
# support code stay for a possible future re-scrape, but its listings no
# longer enter the catalog. Raw/detail history under data/ is kept as-is.
VENDOR_SPIDER_NAMES = ["tms", "onepc", "ivory", "yahav"]

# Vendors whose listing feed exposes only an internal numeric product id
# instead of a part number, and whose product pages therefore have to hand
# the real SKU over through detail `extra` (see _merge_detail_specs).
# 1PC: /web/builder/candidates ids. YahavPC: /api/BuildSearch ids.
NUMERIC_ID_VENDORS = {"onepc", "yahav"}

# Supports either onepc.jsonl or 1pc.jsonl.
VENDOR_FILE_ALIASES = {
    "onepc": ["onepc", "1pc"],
    "1pc": ["1pc", "onepc"],
}

STALE_LOOKBACK_DAYS = 14


def _date_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def find_latest_snapshot(vendor_spider_name: str, today: datetime):
    """
    Return (path, date_str) for the most recent available raw file for
    this vendor within the lookback window, or None if there isn't one.
    """
    base_names = VENDOR_FILE_ALIASES.get(vendor_spider_name, [vendor_spider_name])

    for offset in range(STALE_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=offset)
        day_str = _date_str(day)

        for name in base_names:
            candidate = RAW_DIR / day_str / f"{name}.jsonl"
            if candidate.exists():
                return candidate, day_str

    return None


def load_listings(path: Path) -> list[dict]:
    """
    Load JSONL listings.

    This also tries to recover from concatenated JSON objects on one line,
    which can happen when copy/pasting raw output.
    """
    listings = []
    decoder = json.JSONDecoder()

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                listings.append(json.loads(line))
                continue
            except json.JSONDecodeError:
                idx = 0

                while idx < len(line):
                    while idx < len(line) and line[idx] not in "{[":
                        idx += 1

                    if idx >= len(line):
                        break

                    try:
                        obj, end = decoder.raw_decode(line[idx:])
                        listings.append(obj)
                        idx += end
                    except json.JSONDecodeError:
                        break

    return listings


def _has_image_basename(url: str) -> bool:
    """True when a (possibly relative) image URL points at an actual file,
    not a bare directory. Shared guard with the detail spiders' _og_image
    and the image downloader — keep the three in sync."""
    try:
        if not url:
            return False
        return bool(urlparse(str(url)).path.rsplit("/", 1)[-1])
    except Exception:
        return False


def _reextract_attributes(e: dict) -> None:
    """Re-run attribute extraction, preserving enrich-time accessory_type.

    extract_attributes() knows nothing about the umbrella `accessories`
    category, so a plain re-extract would drop the subtype enrich_listing()
    assigned — carry it across instead.
    """
    kept = (e.get("attributes") or {}).get("accessory_type")
    e["attributes"] = extract_attributes(e)
    if kept:
        e["attributes"].setdefault("accessory_type", kept)


def _collapse_doubled(value: str) -> str:
    """Collapse page-side doubled text nodes ("Acer Acer", "10GB 10GB").

    1PC detail pages render the spec table twice (mobile + desktop layout)
    and the scraper concatenates both copies into one cell — 59 values
    across the Sep 2026 snapshot ("Black. Black.", "AN B570 10G OC AN B570
    10G OC"). Only exactly equal halves are collapsed; anything else is
    returned untouched.
    """
    text = value.strip()
    tokens = text.split()
    if len(tokens) >= 2 and len(tokens) % 2 == 0:
        half = len(tokens) // 2
        if tokens[:half] == tokens[half:]:
            return " ".join(tokens[:half])
    if " " not in text and len(text) >= 4 and len(text) % 2 == 0:
        half = len(text) // 2
        if text[:half] == text[half:]:
            return text[:half]
    return value


def _recompute_canonical_names(products: list[dict], enriched: list[dict]) -> None:
    """Rebuild generated canonical names from the VALIDATED spec attributes.

    Names are built inside match_listings from raw merged attributes; the
    spec build (build_product_specs) then re-derives `attributes` from the
    validated sheet and may have corrected or dropped wrong values — e.g. a
    title-bled "H610" chipset once baked "ARKTEK H610 H81M EL VS" for an
    H81 board. Recompute so what the user reads matches what the spec sheet
    proves. Manual canonical names always win; builders return None when
    their inputs are missing, which keeps the old name.
    """
    groups: dict[str, list[dict]] = {}
    for e in enriched:
        pid = e.get("product_id")
        if pid:
            groups.setdefault(pid, []).append(e)
    updated = 0
    for product in products:
        # CPU names are fully derived from model + packaging, and the
        # manual entries carry stale generated names ("... series Ryzen 5
        # Tray"), so only the other categories keep manual names.
        if product.get("matched_by") == "manual" and product.get("category") not in (
                "cpu", "gpu"):
            continue
        pid = str(product.get("product_id") or "")
        group = groups.get(pid, [])
        if not group:
            continue
        # GPU names must carry the board partner, not the chip vendor: a
        # vendor row said "NVIDIA" for an ASUS card and the rebuilt name
        # read "NVIDIA GeForce RTX 5060 …". Overlay the product brand ONLY
        # when it actually corrects that case — the attrs brand is a chip
        # vendor (NVIDIA/AMD/Intel) while the merged listing brand is not.
        # A blanket overlay is wrong in BOTH directions: it turned
        # "Lian Li Lancool 216" into "LanCool 216" and "PNY GeForce RTX
        # 5060" into "NVIDIA GeForce RTX 5060" (product["brand"] picked the
        # chip vendor from "PNY NVIDIA …" titles).
        attrs = dict(product.get("attributes") or {})
        brand = str(product.get("brand") or "").strip()
        chip_vendors = {"nvidia", "amd", "intel", "ati"}
        if (
            brand
            and product.get("category") == "gpu"
            and str(attrs.get("brand") or "").strip().lower() in chip_vendors
            and brand.lower() not in chip_vendors
        ):
            attrs["brand"] = brand
            attrs["manufacturer"] = brand
        # Same confusion one level up: a GPU whose spec `manufacturer` is a
        # copyable of `chip_manufacturer` ("NVIDIA" for an ASUS card) also
        # pollutes the spec sheet and the manufacturer facet. When the
        # listing-derived brand disagrees, it IS the board partner — correct
        # specs, source and attribute view together.
        specs = product.get("specs") or {}
        specs_mfr = str(specs.get("manufacturer") or "").strip()
        chip_mfr = str(specs.get("chip_manufacturer") or "").strip()
        if (
            brand
            and specs_mfr
            and chip_mfr
            and specs_mfr.lower() == chip_mfr.lower()
            and brand.lower() != specs_mfr.lower()
        ):
            specs["manufacturer"] = brand
            sources = product.get("spec_sources")
            if isinstance(sources, dict):
                sources["manufacturer"] = "derived:gpu.board_partner_from_brand"
            product_attrs = product.get("attributes")
            if isinstance(product_attrs, dict):
                product_attrs["manufacturer"] = brand
        rebuilt = name_from_attributes(
            product.get("category", ""),
            attrs,
            group,
        )
        if rebuilt and rebuilt != product.get("canonical_name"):
            product["canonical_name"] = rebuilt
            updated += 1
    if updated:
        print(f"  recomputed {updated} canonical names from validated specs")


def _disambiguate_duplicate_names(products: list[dict]) -> None:
    """Two different products must never read the same: append the part
    number to every product that shares a name with another one in its
    category ("Gigabyte GeForce RTX 5060 8GB" x3 -> "... (GV-N5060GAMING OC-8GD)").
    Products with no part number keep their name."""
    by_name: dict[tuple, list[dict]] = {}
    for product in products:
        name = str(product.get("canonical_name") or "").strip().lower()
        if name:
            by_name.setdefault((product.get("category"), name), []).append(product)
    changed = 0
    for group in by_name.values():
        if len(group) < 2:
            continue
        for product in group:
            parts = (product.get("specs") or {}).get("part_numbers") or []
            part = next((str(p) for p in parts if p), "")
            if not part:
                pid = str(product.get("product_id") or "")
                if pid.startswith("mpn:"):
                    part = pid.rsplit(":", 1)[-1].upper()
            name = str(product["canonical_name"])
            if part and part.lower() not in name.lower():
                product["canonical_name"] = f"{name} ({part})"
                changed += 1
    if changed:
        print(f"  disambiguated {changed} duplicate canonical names")


def _merge_detail_specs(enriched: list[dict]) -> list[dict]:
    """Load detail-scraped specs from data/raw/detail/<vendor>.jsonl and
    merge into each enriched listing's vendor_meta under a 'detail_specs'
    key.  The extractors consume this via _from_vendor_meta() so the
    structured specs from vendor product pages feed into the attributes
    blob alongside title-parsed and vendor_meta-parsed attributes.

    Also merges:
    - `extra` (real MPN/brand surfaced by the 1PC detail spider — the
      listing spider only knows 1PC's internal numeric id, so without
      this offers display meaningless ids like "126902"),
    - `image_url`, where the full-resolution detail og:image wins but a
      listing-level thumbnail (captured by every listing spider) is kept
      as fallback so photo coverage doesn't depend on the detail scrape.
    """
    vendors = set(str(e.get("vendor_id") or "") for e in enriched)
    # SKUs are vendor-scoped.  The same manufacturer SKU can legitimately
    # occur on multiple sites; indexing by SKU alone lets whichever detail
    # file is read last overwrite another vendor's specs/image/extra.
    detail_index: dict[tuple[str, str], dict] = {}
    # Values are best-first candidate URL lists (a detail page yields several:
    # og:image, the gallery, and the unsuffixed original derived from a cached
    # render). The old shape was a single URL, which forced "og:image wins"
    # even when it was a 74x74 gallery thumb.
    image_index: dict[tuple[str, str], list[str]] = {}
    extra_index: dict[tuple[str, str], dict] = {}
    for vendor in vendors:
        norm = "onepc" if vendor in ("1pc", "onepc") else vendor
        vendor_key = norm
        path = RAW_DIR / "detail" / f"{norm}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                sku = str(item.get("vendor_sku") or "").strip()
                specs = item.get("specs")
                image_url = item.get("image_url")
                extra = item.get("extra")
                if sku and specs:
                    detail_index[(vendor_key, sku)] = {
                        key: _collapse_doubled(value)
                        if isinstance(value, str) else value
                        for key, value in specs.items()
                    }
                # Basename-less image URLs (a bare ".../full/" directory —
                # Plonter emits these for imageless products) must never
                # reach the index: the listing-level thumbnail would be
                # overwritten with an unfetchable directory URL (Sep 2026:
                # 116 products showed broken images this way).
                candidates: list[str] = []
                for url in [*(item.get("image_urls") or []), image_url]:
                    if not url or not _has_image_basename(str(url)):
                        continue
                    for expanded in candidate_urls(str(url)) or [str(url)]:
                        if expanded not in candidates:
                            candidates.append(expanded)
                if sku and candidates:
                    image_index[(vendor_key, sku)] = candidates
                if sku and isinstance(extra, dict) and extra:
                    extra_index[(vendor_key, sku)] = extra

    merged_specs = 0
    merged_images = 0
    merged_extra = 0
    for e in enriched:
        # NOTE: listing-level image_url thumbnails (captured by every
        # listing spider) already ride along on the enriched dict — the
        # detail image below overwrites them only when present.
        sku = str(e.get("vendor_sku") or "").strip()
        if not sku:
            continue
        vendor_id = e.get("vendor_id")
        vendor_key = "onepc" if vendor_id in ("1pc", "onepc") else str(vendor_id or "")
        key = (vendor_key, sku)
        detail_extra = extra_index.get(key)
        if vendor_key in NUMERIC_ID_VENDORS and isinstance(detail_extra, dict):
            real_sku = str(
                detail_extra.get("real_sku") or detail_extra.get("mpn") or ""
            ).strip()
            # 1PC and YahavPC listing IDs are numeric database keys. Replace
            # them with the manufacturer SKU found on the product page before
            # matching so exact SKU/MPN matching can join the same item
            # across vendors.
            if real_sku and not real_sku.isdigit() and real_sku != sku:
                e["vendor_sku"] = real_sku
                cur_mpn = e.get("mpn")
                if not cur_mpn or not mpn_affix_related(cur_mpn, real_sku):
                    # Nothing to reconcile, or the two are different parts:
                    # the vendor's own product page is authoritative.
                    e["mpn"] = real_sku
                else:
                    # Same part at different truncation levels — page code
                    # truncated ("R9070XTGAMINGOC16") vs the full pattern MPN
                    # from the title ("GV-R9070XTGAMING-OC-16GD"): keep the
                    # longer full part number so the cross-vendor match lands,
                    # and the printed spelling when the two agree on the code
                    # (prefer_longer_mpn).
                    e["mpn"] = prefer_longer_mpn(cur_mpn, real_sku)
                sku = real_sku
                # The pre-detail match_text was built from the numeric id
                # ("189654 Intel…") so packaging codes in the real SKU
                # (C225FT=Tray) were invisible to the parsers. Rebuild the
                # match text and re-extract so _packaging_from_codes sees it.
                try:
                    e["match_text"] = match_text(e)
                    _reextract_attributes(e)
                except Exception:
                    pass
        if key in detail_index:
            meta = e.setdefault("vendor_meta", {})
            meta["detail_specs"] = detail_index[key]
            # Re-extract attributes so the newly-merged detail specs feed
            # into the attributes blob (enrich_listing already ran before
            # this point, so without this the detail specs would never make
            # it out of vendor_meta into parsed attributes).
            _reextract_attributes(e)
            merged_specs += 1
        if detail_extra:
            extra = detail_extra
            meta = e.setdefault("vendor_meta", {})
            real_mpn = extra.get("mpn") or extra.get("real_sku")
            if real_mpn and (vendor_key not in NUMERIC_ID_VENDORS or not e.get("mpn")):
                # Reconcile, don't blindly overwrite: detail rows sometimes
                # carry only the tail ("KFGX" for "WD161KFGX") while enrich
                # holds the full code — keep the longer on affix relations.
                # On true conflicts the detail value wins (status quo: the
                # vendor's own product page is authoritative).
                cur_mpn = e.get("mpn")
                new_mpn = str(real_mpn).strip()
                if not cur_mpn or not mpn_affix_related(cur_mpn, new_mpn):
                    # Nothing to reconcile, or a true conflict (status quo:
                    # the vendor's own product page is authoritative).
                    if new_mpn != cur_mpn:
                        e["mpn"] = new_mpn
                        merged_extra += 1
                else:
                    # Affix relation (detail rows sometimes carry only the
                    # tail, "KFGX" for "WD161KFGX") or the same code spelled
                    # differently — prefer_longer_mpn keeps the fuller code
                    # and the printed spelling.
                    reconciled = prefer_longer_mpn(cur_mpn, new_mpn)
                    if reconciled != cur_mpn:
                        e["mpn"] = reconciled
                        merged_extra += 1
            if extra.get("brand") and not e.get("brand"):
                e["brand"] = str(extra["brand"]).strip()
        if key in image_index:
            # Detail candidates + the listing tile compete on URL shape: the
            # vendor's original (TMS /image/catalog/products/<sku>/<hash>.jpg)
            # beats a cached render (-1000x1000) which beats the 228px listing
            # tile, whichever order they arrived in. The listing tile stays in
            # the list as the last resort so photo coverage never drops.
            merged: list[str] = []
            for url in [*(e.get("image_url") and [e["image_url"]] or []),
                        *image_index[key]]:
                if url and str(url) not in merged:
                    merged.append(str(url))
            e["image_url"] = best_of(merged)
            merged_images += 1

    if merged_specs:
        print(f"  merged detail specs for {merged_specs} listings")
    if merged_images:
        print(f"  merged detail images for {merged_images} listings")
    if merged_extra:
        print(f"  merged real MPNs for {merged_extra} listings")
    return enriched


def _drop_included_builder_options(listings: list[dict]) -> list[dict]:
    """Drop YahavPC's "included in ..." builder slots.

    BuildSearch returns the PC-builder's zero-price options as if they were
    products: BIC-GPU ("integrated graphics in the CPU"), BIC-CPU ("boxed
    cooler"), BIC-CASE-YPC ("case + cooler bundle") and WITHPSU ("included
    PSU"). They have no real price, no vendor page worth linking and a
    generic stamp image, yet they used to surface as products in gpu,
    cooler_air, case_fan and psu. The spider now filters them at the source;
    this also scrubs snapshots taken before that fix (and any stale-forwarded
    copies of them).

    Deliberately scoped to yahav: TMS legitimately lists "price on request"
    parts without a price, and dropping those would lose real products.
    """
    kept = []
    dropped = 0
    for listing in listings:
        if listing.get("vendor_id") == "yahav" and listing.get("price_ils") == 0:
            dropped += 1
            continue
        kept.append(listing)
    if dropped:
        print(f"  dropped {dropped} YahavPC included-in-... builder options")
    return kept


def build_catalog(today: datetime):
    today_str = _date_str(today)

    all_listings = []
    skipped_vendors = []

    for vendor_spider_name in VENDOR_SPIDER_NAMES:
        found = find_latest_snapshot(vendor_spider_name, today)

        if found is None:
            skipped_vendors.append(vendor_spider_name)
            print(
                f"[info] {vendor_spider_name}: no snapshot in the last "
                f"{STALE_LOOKBACK_DAYS} days — not onboarded yet or down "
                "for longer than the lookback window",
                file=sys.stderr,
            )
            continue

        path, snapshot_date = found
        is_stale = snapshot_date != today_str

        listings = load_listings(path)
        listings = _drop_included_builder_options(listings)

        for listing in listings:
            listing["last_seen"] = snapshot_date
            listing["stale"] = is_stale

            if not listing.get("vendor_id"):
                listing["vendor_id"] = (
                    "1pc" if vendor_spider_name == "onepc" else vendor_spider_name
                )

        level = "warn" if is_stale else "ok"
        print(
            f"[{level}] {vendor_spider_name}: {len(listings)} listings from {snapshot_date}"
            + (" (stale)" if is_stale else "")
        )

        all_listings.extend(listings)

    enriched = [enrich_listing(listing) for listing in all_listings]
    enriched = dedupe_enriched_listings(enriched)
    enriched = _merge_detail_specs(enriched)

    # Stable output ordering.
    enriched.sort(key=lambda e: (e.get("vendor_id", ""), e.get("listing_key", "")))

    match_result = match_listings(enriched, manual_path=MANUAL_PATH)

    assignments = match_result["assignments"]
    product_sizes = match_result["product_sizes"]

    for e in enriched:
        e["product_id"] = assignments.get(e["listing_key"])

    # Specs: merge every offer's typed facts with the Tier-0 reference data,
    # manual overrides and cross-field validation, then re-derive the legacy
    # `attributes` view from the merged sheet (scraper/specs/). Products end
    # up with `specs` (fixed key set, nulls included) + `spec_sources`.
    spec_report = build_product_specs(match_result["products"], enriched)
    _recompute_canonical_names(match_result["products"], enriched)
    _disambiguate_duplicate_names(match_result["products"])

    exclude_multi_keys = {
        listing_key_value
        for listing_key_value, pid in assignments.items()
        if product_sizes.get(pid, 0) > 1
    }

    review_queue = suggest_fuzzy_matches(
        enriched,
        manual_path=MANUAL_PATH,
        threshold=88,
        exclude_multi_keys=exclude_multi_keys,
        assignments=assignments,
    )
    # Public duplicate-vendor QA cases ride along in the same queue file
    # (local review tool) and are also emitted as data/site/qa.json for the
    # public #/qa page (see site_data.write_site_data). Naming-conflict
    # cases (tier-4c flags) ride along the same way.
    try:
        review_queue = list(review_queue) + find_duplicate_vendor_cases(
            match_result["products"]
        ) + find_naming_conflict_cases(match_result["products"])
    except Exception:
        pass

    catalog = {
        "generated_at": today.isoformat(),
        "listings": enriched,
        "products": match_result["products"],
        "review_queue_count": len(review_queue),
        "skipped_vendors": skipped_vendors,
    }

    return catalog, review_queue, spec_report


def main():
    # The coverage summary prints vendor labels, which are Hebrew on local
    # (non-UTF-8) consoles — and a UnicodeEncodeError there would abort the
    # build right before the outputs are written. Degrade to replacement
    # characters instead; CI (utf-8) is unaffected.
    try:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    today = datetime.now(timezone.utc)

    catalog, review_queue, spec_report = build_catalog(today)

    DATA_DIR.mkdir(exist_ok=True)
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(review_queue, f, ensure_ascii=False, indent=2)

    # Visible evidence queue for scraper/specs/labels.py: every vendor detail
    # label that mapped to no schema field, grouped by category with a count
    # and sample product ids. Read by `python -m scraper.specs.report_gaps`.
    with open(DATA_DIR / "spec_gaps.json", "w", encoding="utf-8") as f:
        gaps = (spec_report or {}).get("label_gaps") or []
        json.dump(
            {
                "generated_at": today.isoformat(),
                "gaps": [
                    {
                        "category": gap.get("category"),
                        "label": gap.get("label"),
                        "count": gap.get("count"),
                        "products": (gap.get("products") or [])[:3],
                    }
                    for gap in gaps
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # Count-check: zero listings across every vendor means the whole
    # pipeline is broken, so fail loudly rather than commit an empty catalog.
    if not catalog["listings"]:
        print("[error] zero listings across all vendors — failing the job", file=sys.stderr)
        sys.exit(1)

    print(
        f"[ok] wrote {len(catalog['listings'])} listings, "
        f"{len(catalog['products'])} products, "
        f"{len(review_queue)} review candidates "
        f"to {OUTPUT_PATH}"
    )

    # Sharded, client-optimized data for the static site (data/site/*.json)
    # — see scraper/site_data.py for why this is separate from catalog.json.
    site_meta = write_site_data(catalog, SITE_DIR, spec_report=spec_report)
    print(
        f"[ok] wrote site data: {len(site_meta['categories'])} category files "
        f"to {SITE_DIR}"
    )

    # Per-category price history for the product pages' charts
    # (data/site/history/*.json) — see scraper/build_price_history.py.
    build_price_history(catalog)


if __name__ == "__main__":
    main()