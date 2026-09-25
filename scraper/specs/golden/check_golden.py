"""
specs/golden/check_golden.py — assert the pipeline's output matches hand-verified
specs (plan Phase 5).

The repo has no test framework by design (see PROJECT_OVERVIEW §11), so this is a
plain script:

    python -m scraper.specs.golden.check_golden            # after a normalize run
    python -m scraper.specs.golden.check_golden --catalog path/to/catalog.json

It reads data/catalog.json, looks up each fixture's product, and compares:

- `expect`           — always asserted (title/vendor-sourced facts).
- `expect_reference` — asserted only when the optional pcpartdb index exists,
                       because Tier 0 is off by design without it.
- `expect_null`      — the field MUST be unknown (null or absent). This pins a
                       wrong value as a regression: an air cooler must never
                       claim `water_cooled` / `radiator_size_mm`, a 2 TB drive
                       must never claim `capacity_gb: 2`.

Exit 0 = every assertion held; exit 1 = at least one mismatch (each printed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import schema

ROOT = Path(__file__).resolve().parent.parent.parent.parent
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures.json"
DEFAULT_CATALOG = ROOT / "data" / "catalog.json"
INDEX_PATH = ROOT / "data" / "pcpartdb" / "index.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES_PATH)
    args = parser.parse_args()

    if not args.catalog.exists():
        print(f"[golden] catalog not found: {args.catalog} (run normalize first)")
        return 1
    fixtures = load_json(args.fixtures)
    if int(fixtures.get("schema_version", 0)) != schema.SCHEMA_VERSION:
        print(f"[golden] FAIL: fixtures target schema v{fixtures.get('schema_version')} "
              f"but the schema is v{schema.SCHEMA_VERSION} — regenerate fixtures")
        return 1

    have_reference = INDEX_PATH.exists()
    if not have_reference:
        print("[golden] no pcpartdb index — Tier-0 assertions are skipped "
              "(run: python -m scraper.pcpartdb refresh)")

    catalog = load_json(args.catalog)
    by_id = {str(p.get("product_id")): p for p in catalog.get("products", [])}

    failures: list[str] = []
    checked = 0
    for case in fixtures.get("cases", []):
        product_id = case["product_id"]
        product = by_id.get(product_id)
        if product is None:
            failures.append(f"{product_id}: product not found in catalog")
            continue
        if case.get("category") and product.get("category") != case["category"]:
            failures.append(
                f"{product_id}: category {product.get('category')!r} != "
                f"{case['category']!r}")
        specs = product.get("specs") or {}

        for field, expected in (case.get("expect") or {}).items():
            actual = specs.get(field)
            checked += 1
            if actual != expected:
                failures.append(
                    f"{product_id}: {field} = {actual!r}, expected {expected!r}")

        if have_reference:
            for field, expected in (case.get("expect_reference") or {}).items():
                actual = specs.get(field)
                checked += 1
                if actual != expected:
                    failures.append(
                        f"{product_id}: {field} = {actual!r}, expected {expected!r}")

        for field in case.get("expect_null") or []:
            actual = specs.get(field)
            checked += 1
            if actual is not None:
                failures.append(
                    f"{product_id}: {field} should be unknown, got {actual!r}")

    total_cases = len(fixtures.get("cases", []))
    if failures:
        print(f"[golden] FAIL — {len(failures)} mismatch(es) over "
              f"{total_cases} products:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[golden] pass — {checked} assertions over {total_cases} products"
          + ("" if have_reference else " (Tier-0 checks skipped)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
