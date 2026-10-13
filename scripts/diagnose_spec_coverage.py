"""
diagnose_spec_coverage.py — offline view of which vendor facts the spec
pipeline currently drops, and what a mapping would recover.

Run this yourself, locally, against your own data/raw/ — it never touches the
network and never writes the catalog:

    python scripts/diagnose_spec_coverage.py              # per-vendor summary
    python scripts/diagnose_spec_coverage.py --labels psu  # top gap labels
    python scripts/diagnose_spec_coverage.py --labels psu --suggest
    python scripts/diagnose_spec_coverage.py --fields

What it does: replays every row of data/raw/detail/<vendor>.jsonl through the
same entry point the normalizer uses (`vendor_struct.parse_detail_specs` with
the listing's normalized category from data/catalog.json), and reports

  - how many detail rows / labels exist per vendor and category,
  - how many labels mapped to NO schema field (the `label_gaps` the coverage
    report already tracks, but attributed per vendor and per category),
  - how many facts each category's pages actually supply today (--fields),
  - what the gap labels look like under a relaxed, token-aware matcher
    (--suggest) — dry-run evidence for specs/labels.py, never used by the
    pipeline itself.

Fast loop for vocabulary work: the full normalizer takes minutes, this takes
seconds, and both read the same raw files.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.specs import labels  # noqa: E402
from scraper.specs.resolvers import vendor_struct  # noqa: E402

CATALOG = ROOT / "data" / "catalog.json"
DETAIL_DIR = ROOT / "data" / "raw" / "detail"
REPORT = ROOT / "data" / "site" / "spec_report.json"

# vendor_id as written in the raw detail files -> the catalog's spelling.
VENDOR_KEY = {"onepc": "1pc", "1pc": "1pc", "tms": "tms", "ivory": "ivory",
              "plonter": "plonter"}

# Filler tokens a vendor label may carry that the curated tables do not.
# Stripping them shows what a token-aware vocabulary would match; this is
# evidence for labels.py, not a mapping the pipeline uses.
_FILLER = frozenset({
    "connectors", "connector", "pin", "pins", "port", "ports", "count",
    "type", "size", "version", "support", "supported", "max", "maximum",
    "external", "internal", "integrated",
    "גודל", "חיבורי", "חיבורים", "מחברים", "מחבר", "כמות", "סוג", "מספר",
    "תמיכה", "מובנה", "מקסימלי", "מקסימלית", "פנימיים", "בלוח", "בגב",
    "המחשב", "מאוורר",
})

_TOKEN_ALIASES = (("pci-e", "pcie"), ("pci express", "pcie"), ("pci e", "pcie"),
                  ("wi-fi", "wifi"), ("wi fi", "wifi"))


def _tokens(label: str) -> frozenset[str]:
    """Token set for the relaxed matcher (see module docstring)."""
    text = labels.normalize_label(label)
    for needle, replacement in _TOKEN_ALIASES:
        text = text.replace(needle, replacement)
    text = re.sub(r"[^\w\u0590-\u05FF+]+", " ", text)
    return frozenset(token for token in text.split() if token not in _FILLER)


def _relaxed_index() -> dict[tuple[str, frozenset], str]:
    index: dict[tuple[str, frozenset], str] = {}
    for category, table in labels.CATEGORY_LABELS.items():
        for key, value in table.items():
            index.setdefault((category, _tokens(key)), value)
    for key, value in labels.COMMON_LABELS.items():
        index.setdefault(("*", _tokens(key)), value)
    return index


def _relaxed(label: str, category: str | None,
             index: dict[tuple[str, frozenset], str]) -> str | None:
    tokens = _tokens(label)
    for candidate in (tokens, tokens - {"pin"}):
        value = (index.get((category or "", candidate))
                 or index.get(("*", candidate)))
        if value:
            return value
    best = None
    for (index_cat, key_tokens), value in index.items():
        if index_cat != category or not key_tokens or not key_tokens <= tokens:
            continue
        if best is None or len(key_tokens) > len(best[0]):
            best = (key_tokens, value)
    return best[1] if best else None


def _load_catalog() -> tuple[dict[tuple[str, str], str], dict[str, int], set[str]]:
    """(vendor, sku)->category, per-category product counts, live vendors."""
    if not CATALOG.exists():
        print(f"[warn] {CATALOG} not found — run the normalizer first",
              file=sys.stderr)
        return {}, {}, set()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_sku: dict[tuple[str, str], str] = {}
    vendors: set[str] = set()
    for listing in catalog.get("listings", []):
        vendor = str(listing.get("vendor_id") or "")
        sku = str(listing.get("vendor_sku") or "").strip()
        category = listing.get("category_normalized")
        if vendor:
            vendors.add(vendor)
        if vendor and sku and category:
            by_sku[(vendor, sku)] = category
    products: dict[str, int] = collections.Counter()
    if REPORT.exists():
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        for category, bucket in (report.get("categories") or {}).items():
            products[category] = bucket.get("products") or 0
    return by_sku, products, vendors


def _row_category(row: dict, by_sku: dict[tuple[str, str], str]) -> str | None:
    vendor = VENDOR_KEY.get(str(row.get("vendor_id") or ""),
                            str(row.get("vendor_id") or ""))
    sku = str(row.get("vendor_sku") or "").strip()
    if (vendor, sku) in by_sku:
        return by_sku[(vendor, sku)]
    # 1PC detail rows are keyed by the vendor's numeric id; the catalog holds
    # the real MPN after the merge. The detail row's extra carries the bridge.
    extra = row.get("extra") or {}
    for key in ("real_sku", "mpn"):
        real = str(extra.get(key) or "").strip()
        if real and (vendor, real) in by_sku:
            return by_sku[(vendor, real)]
    return None


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Offline spec-coverage diagnostic (no network).")
    parser.add_argument("--labels", metavar="CATEGORY",
                        help="print the unmapped labels for one category")
    parser.add_argument("--suggest", action="store_true",
                        help="dry-run relaxed mapping for every gap label")
    parser.add_argument("--fields", action="store_true",
                        help="print fact coverage per category/field")
    args = parser.parse_args()

    by_sku, products_by_category, live_vendors = _load_catalog()
    index = _relaxed_index() if args.suggest else {}

    rows_per_vendor: collections.Counter = collections.Counter()
    gaps_per_vendor: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    gaps_per_category: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    facts_per_category: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    unresolved_per_vendor: collections.Counter = collections.Counter()

    for path in sorted(DETAIL_DIR.glob("*.jsonl")):
        vendor = path.stem
        # A vendor the catalog no longer carries (Plonter, dropped Sep 2026)
        # has no listings to resolve categories from; its rows would all read
        # as gaps and drown the signal. Skip it.
        key = VENDOR_KEY.get(vendor, vendor)
        if live_vendors and key not in live_vendors:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            specs = row.get("specs")
            if not specs:
                continue
            rows_per_vendor[vendor] += 1
            category = _row_category(row, by_sku)
            if category is None:
                unresolved_per_vendor[vendor] += 1
            row_gaps: dict[str, int] = {}
            out = vendor_struct.parse_detail_specs(category, specs,
                                                   gaps=row_gaps)
            for field, values in out.items():
                facts_per_category[category or "?"][field] += len(values)
            for label, count in row_gaps.items():
                gaps_per_category[category or "?"][label] += count
                gaps_per_vendor[vendor][label] += count

    print("detail rows replayed per vendor (rows with specs):")
    for vendor, count in rows_per_vendor.most_common():
        unresolved = unresolved_per_vendor[vendor]
        gap_rows = sum(gaps_per_vendor[vendor].values())
        print(f"  {vendor:8} rows={count:6}  unmapped-label rows={gap_rows:6}  "
              f"no-category rows={unresolved:5}")

    if args.labels:
        bucket = gaps_per_category.get(args.labels) or collections.Counter()
        print(f"\nunmapped labels in {args.labels} (top 40):")
        if not bucket:
            print("  (none)")
        for label, count in bucket.most_common(40):
            hint = ""
            if args.suggest:
                suggestion = _relaxed(label, args.labels, index)
                hint = f"  -> {suggestion}" if suggestion else "  -> (no field)"
            print(f"  {count:5}  {label}{hint}")
        return 0

    if args.suggest:
        print("\ndry-run relaxed mappings for the top gap labels "
              "(suggestion only — the pipeline does not use these yet):")
        total = 0
        for category in sorted(gaps_per_category,
                               key=lambda c: -sum(gaps_per_category[c].values())):
            for label, count in gaps_per_category[category].most_common(25):
                suggestion = _relaxed(label, category, index)
                if suggestion:
                    print(f"  {count:5}  {category:14} {label}  -> {suggestion}")
                    total += 1
        print(f"  ({total} labelled suggestions)")
        return 0

    if args.fields:
        print("\nvendor detail facts per category (what pages actually "
              "supply today):")
        for category in sorted(facts_per_category,
                               key=lambda c: -sum(facts_per_category[c].values())):
            facts = facts_per_category[category]
            products = products_by_category.get(category, 0)
            head = ", ".join(f"{name}={count}"
                             for name, count in facts.most_common(8))
            print(f"  {category:14} products={products:4} "
                  f"facts={sum(facts.values()):6}  {head}")
        return 0

    print("\nunmapped-label rows per category:")
    for category, bucket in sorted(gaps_per_category.items(),
                                   key=lambda kv: -sum(kv[1].values())):
        print(f"  {category:14} {sum(bucket.values()):6} rows  "
              f"{len(bucket):3} distinct labels")
    print("\nnext: --labels <category> [--suggest] to see the labels, "
          "or --fields for per-field fact coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
