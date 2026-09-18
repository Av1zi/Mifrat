"""Promote local review-queue decisions into the manual merge ledger.

Reads the decisions recorded by the local review tool
(`python -m scraper.review_queue`, stored in
`data/matching/review_decisions.json`):

- `match` verdicts become entries in `data/matching/manual_products.json`
  `products[]` (schema: product_id/category/brand/model/attributes/
  listing_keys), so the next normalize run merges those listings.
- `not_match` verdicts become `blocked_pairs` entries, which the matcher
  enforces as a hard veto (those two listings never share a product).

Idempotent: decisions already reflected in the ledger are skipped, so
re-running after each review session only appends what's new.

Usage (from the repo root):
    python -m scraper.promote_decisions [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL_PATH = ROOT / "data" / "matching" / "manual_products.json"
DECISIONS_PATH = ROOT / "data" / "matching" / "review_decisions.json"
CATALOG_PATH = ROOT / "data" / "catalog.json"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _manual_product_id(category: str, keys: list[str]) -> str:
    stem = _slug("-".join(sorted(keys)))[:60].strip("-")
    return f"manual:{_slug(category) or 'other'}:{stem or 'pair'}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would change without writing manual_products.json",
    )
    args = parser.parse_args()

    if not DECISIONS_PATH.exists():
        print("no decisions file (run the review tool first), nothing to do")
        return 0
    decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    if not decisions:
        print("no decisions recorded, nothing to do")
        return 0

    manual = (
        json.loads(MANUAL_PATH.read_text(encoding="utf-8"))
        if MANUAL_PATH.exists()
        else {}
    )
    manual.setdefault("products", [])
    manual.setdefault("blocked_pairs", [])

    listings: dict[str, dict] = {}
    if CATALOG_PATH.exists():
        try:
            catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            listings = {
                item["listing_key"]: item
                for item in catalog.get("listings", [])
                if item.get("listing_key")
            }
        except (ValueError, OSError) as exc:
            print(f"warning: cannot read catalog ({exc}); "
                  f"metadata will be sparse")

    key_to_pid: dict[str, str] = {}
    for product in manual["products"]:
        for lk in product.get("listing_keys", []):
            key_to_pid.setdefault(lk, product.get("product_id", ""))

    blocked: set[frozenset] = set()
    for pair in manual["blocked_pairs"]:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            blocked.add(frozenset(pair))

    added_products = 0
    added_blocks = 0
    skipped = 0
    for index in sorted(decisions, key=lambda k: int(k) if str(k).isdigit() else str(k)):
        verdict = decisions[index] or {}
        decision = verdict.get("decision")
        key_a = verdict.get("listing_a")
        key_b = verdict.get("listing_b")
        if decision not in ("match", "not_match") or not key_a or not key_b:
            skipped += 1
            continue
        if decision == "not_match":
            if frozenset((key_a, key_b)) in blocked:
                skipped += 1
                continue
            blocked.add(frozenset((key_a, key_b)))
            manual["blocked_pairs"].append(
                sorted((str(key_a), str(key_b))))
            added_blocks += 1
            continue
        # match verdict
        pid_a = key_to_pid.get(key_a)
        pid_b = key_to_pid.get(key_b)
        if pid_a and pid_a == pid_b:
            skipped += 1
            continue
        if pid_a or pid_b:
            print(f"warning: #{index} {key_a} + {key_b} touches an "
                  f"existing manual product; merge it by hand")
            skipped += 1
            continue
        info_a = listings.get(key_a, {})
        info_b = listings.get(key_b, {})
        category = (
            info_a.get("category_normalized")
            or info_b.get("category_normalized")
            or "other"
        )
        brand_a, brand_b = info_a.get("brand"), info_b.get("brand")
        brand = brand_a if brand_a and brand_a == brand_b else (brand_a or brand_b)
        model = (
            (info_a.get("attributes") or {}).get("model")
            or (info_b.get("attributes") or {}).get("model")
            or info_a.get("model")
            or info_b.get("model")
        )
        product_id = _manual_product_id(category, [str(key_a), str(key_b)])
        manual["products"].append(
            {
                "product_id": product_id,
                "category": category,
                "brand": brand,
                "model": model,
                "attributes": {},
                "listing_keys": sorted((str(key_a), str(key_b))),
            }
        )
        key_to_pid[key_a] = product_id
        key_to_pid[key_b] = product_id
        added_products += 1

    # Deterministic ordering for clean diffs.
    seen_pairs: set[tuple] = set()
    ordered_pairs: list[list[str]] = []
    for pair in manual["blocked_pairs"]:
        tup = tuple(sorted(pair)) if isinstance(pair, list) else tuple(pair)
        if len(tup) == 2 and tup not in seen_pairs:
            seen_pairs.add(tup)
            ordered_pairs.append(list(tup))
    manual["blocked_pairs"] = sorted(ordered_pairs)
    manual["products"] = sorted(
        manual["products"], key=lambda p: str(p.get("product_id", "")))

    print(f"decisions: {len(decisions)}, new manual products: "
          f"{added_products}, new blocked pairs: {added_blocks}, "
          f"skipped: {skipped}")
    if args.dry_run:
        print("dry run: manual_products.json not written")
        return 0
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_PATH.write_text(
        json.dumps(manual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {MANUAL_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
