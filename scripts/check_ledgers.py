"""Ledgers point at live data (audit 2026-11-10 L).

Every hand-kept ledger entry should point at something that exists now and
changes the output. A ledger is human-edited and a listing absent for 14
days can come back, so nothing here prunes; it reports, and it fails only
where a dead entry is certainly dead:

    hard    a spec override that no product reaches (exact pid, a pid alias,
            or the `mpn:`/`sku:` part-number fallback of
            `specs.resolvers.reference.overrides_for`)
    warn    an override reached only through an alias or that fallback (it
            applies; rekey it to the live pid when convenient)
    budget  curated manual products none of whose listings is in the
            catalog, blocked pairs naming a key no snapshot carries,
            `qa_dismissed` keys whose case is gone, image blocklist entries
            that match no listing image, cover files no listing uses

    python scripts/check_ledgers.py [--catalog data/catalog.json] [--verbose]

Exit 0 = no hard failure and every budget holds; exit 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.site_data import _image_vendor_key, _safe_image_stem  # noqa: E402
from scraper.specs.resolvers import reference  # noqa: E402

MATCHING = ROOT / "data" / "matching"
IMAGES = ROOT / "data" / "images"

# Counts at the 2026-11-11 baseline plus headroom; raise them only with a
# decisions.md line saying why the entries are kept.
BUDGETS = {
    "manual products with no live listing": 6,
    "blocked pairs naming a gone key": 3,
    "qa_dismissed keys with no case": 4,
    "image blocklist entries matching nothing": 3,
    "cover files no listing uses": 900,
}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def check_overrides(catalog: dict) -> tuple[list[str], list[str]]:
    overrides = reference.load_overrides()
    live = {str(p.get("product_id")): p for p in catalog.get("products") or []}
    aliases = catalog.get("pid_aliases") or {}
    reached: dict[str, str] = {}
    for pid, product in live.items():
        if pid in overrides:
            reached[pid] = "exact"
    for old_pid, target in aliases.items():
        if old_pid in overrides and target in live:
            reached.setdefault(old_pid, f"alias -> {target}")
    # The part-number fallback: which entry each product without an exact
    # entry would pick (same lookup as `overrides_for`).
    by_entry = {id(entry): key for key, entry in overrides.items()}
    for pid, product in live.items():
        if pid in overrides:
            continue
        entry = _entry_of(product)
        key = by_entry.get(id(entry)) if entry is not None else None
        if key and key not in reached:
            reached[key] = f"part number -> {pid}"
    hard = [f"override {key} reaches no product" for key in overrides if key not in reached]
    warn = [f"override {key} applies via {how}" for key, how in sorted(reached.items())
            if how != "exact"]
    return hard, warn


def _entry_of(product: dict):
    """The override entry `overrides_for` would pick for a product (same lookup)."""
    import re

    overrides = reference.load_overrides()
    category = product.get("category")
    for offer in product.get("offers") or []:
        raws = [offer.get("mpn"), offer.get("vendor_sku")]
        attrs = offer.get("attributes") or {}
        for name in ("part_numbers", "part_number", "mpn"):
            value = attrs.get(name)
            raws += list(value) if isinstance(value, (list, tuple, set)) else [value]
        for raw in raws:
            key = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())
            if len(key) > 5 and key.startswith("gv"):
                rest = key[2:]
                if len(rest) >= 3 and re.search(r"\d", rest):
                    key = rest
            if not key:
                continue
            for prefix in ("mpn", "sku"):
                found = overrides.get(f"{prefix}:{category}:{key}")
                if isinstance(found, dict):
                    return found
    return None


def check_budgets(catalog: dict) -> dict[str, list[str]]:
    listing_keys = {str(e.get("listing_key")) for e in catalog.get("listings") or []}
    manual = _read(MATCHING / "manual_products.json", {})
    out: dict[str, list[str]] = {}

    out["manual products with no live listing"] = [
        str(p.get("product_id")) for p in manual.get("products") or []
        if not any(k in listing_keys for k in p.get("listing_keys") or [])
    ]
    out["blocked pairs naming a gone key"] = [
        " / ".join(pair) for pair in manual.get("blocked_pairs") or []
        if any(k not in listing_keys for k in pair)
    ]

    qa = _read(ROOT / "data" / "site" / "qa.json", {})
    case_ids = {
        f"{c.get('kind')}|{c.get('product_id')}|{c.get('field') or c.get('vendor') or ''}"
        for c in qa.get("cases") or []
    }
    out["qa_dismissed keys with no case"] = [
        key for key, value in (_read(MATCHING / "qa_dismissed.json", {}) or {}).items()
        if value and not key.startswith("fuzzy|") and key not in case_ids
    ]

    images = [(_image_vendor_key(e.get("vendor_id")), str(e.get("image_url") or ""))
              for e in catalog.get("listings") or []]
    out["image blocklist entries matching nothing"] = [
        item for item in (_read(MATCHING / "image_blocklist.json", {}).get("blocked") or [])
        if isinstance(item, str) and "/" in item
        and not any(vendor == item.split("/", 1)[0] and item.split("/", 1)[1] in url
                    for vendor, url in images)
    ]

    used = {
        f"{_image_vendor_key(e.get('vendor_id'))}/{_safe_image_stem(str(e['vendor_sku']))}.webp"
        for e in catalog.get("listings") or [] if e.get("vendor_sku")
    }
    out["cover files no listing uses"] = sorted(
        f"{path.parent.name}/{path.name}"
        for path in IMAGES.glob("*/*.webp")
        if f"{path.parent.name}/{path.name}" not in used
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    path = Path(args.catalog)
    if not path.exists():
        print("[check-ledgers] %s not found, run the normalizer first" % path,
              file=sys.stderr)
        return 1
    catalog = json.loads(path.read_text(encoding="utf-8"))

    hard, warn = check_overrides(catalog)
    for line in warn:
        print("  [warn] " + line)
    failed = list(hard)
    for label, items in check_budgets(catalog).items():
        budget = BUDGETS[label]
        print("  %-42s %4d (budget %d)" % (label, len(items), budget))
        if args.verbose or len(items) > budget:
            for item in items[:40]:
                print("      " + item)
        if len(items) > budget:
            failed.append(f"{label}: {len(items)} > budget {budget}")
    if failed:
        for line in failed:
            print("  [fail] " + line)
        print("[check-ledgers] %d failure(s)" % len(failed))
        return 1
    print("[check-ledgers] every ledger points at live data (or is within budget)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
