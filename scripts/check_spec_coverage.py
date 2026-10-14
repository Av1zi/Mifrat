"""
check_spec_coverage.py — spec-coverage regression gate (Oct 2026 coverage pass).

The repo has no test framework by design (see PROJECT_OVERVIEW §11), so this
is a plain script:

    python scripts/check_spec_coverage.py        # after a normalize run

It reads data/site/spec_report.json (written by the normalizer) and fails
when spec health regresses beyond daily-churn noise:

1. label-gap rows exceed the budget — the `label_gaps` frequency table is
   how the vocabulary in scraper/specs/labels.py grows from real vendor
   pages, so a sudden jump means a vendor renamed labels or a mapping broke;
2. a category's fill drops below its floor — floors come from the post-fix
   baseline of the Oct 2026 coverage pass (measured 2026-10-03), minus 2pp
   of tolerance for daily vendor churn;
3. a core compat field (socket, chipset, memory_type, wattage_w,
   form_factor) drops below its floor for the same reason.

Floors are deliberately conservative: this gate catches regressions, not
daily wobble. If a floor trips because the catalog genuinely changed shape
(e.g. a vendor left and took its facts with it), update the floors here in
the same commit and say why — never just delete the check.

Exit 0 = within budget; exit 1 = regression (each trip printed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "data" / "site" / "spec_report.json"

# Total label-gap rows in spec_report.json on 2026-10-03 (3,475) + ~30%
# headroom for vendor-label churn. A vendor renaming a table or a broken
# mapping shows up here first, long before category fill moves.
# 2026-10-14: 4500 -> 6200. Yahav onboarded (1,079 rows, fifth Hebrew
# vocabulary) carrying ~1,300 gap rows that are deliberate gap evidence,
# not breakage: motherboard ממשק אחסון (M.2 per-slot interface, no field),
# gpu מהירות זכרון/DirectX/OpenGL/רוחב פס זכרון (deferred-schema backlog),
# psu קבוצת הספק (wattage already comes from the title). Same rule as the
# baseline: new measured total (4,797) + ~30% headroom.
LABEL_GAP_BUDGET = 6200

# Mean field-fill % per category on 2026-10-03, minus 2pp tolerance.
CATEGORY_FLOORS = {
    "accessories": 31,
    "aio": 51,
    "case": 42,
    # 2026-10-14: 60 -> 55. Yahav onboarded: 201 of 471 case_fan products
    # are Yahav's, averaging 8.0 filled fields/product vs 9.0 for the rest
    # (its tables are ~5 rows), so mean fill went to 57.7% on composition
    # alone — measured, not a mapping regression (pair cases still pass).
    "case_fan": 55,
    "cooler_air": 41,
    "cooling_other": 28,
    "cpu": 70,
    "gpu": 52,
    "memory": 59,
    # 2026-10-14: 51 -> 46. Same Yahav onboarding: 148 of 710 boards are
    # Yahav's at 10.1 filled fields/product vs 16.9 for the rest (its
    # boards carry ~5 Hebrew rows where 1PC/TMS carry full tables),
    # dragging mean fill to 48.5% on composition alone.
    "motherboard": 46,
    "psu": 46,
    # 2026-10-13: 58 -> 55. 1PC returned to the catalog (Oct 2026
    # storefront rebuild) bringing 66 HDD listings whose vendor tables
    # are 5 thin rows (model/capacity/type/warranty, no form-factor or
    # interface evidence to map); storage went 60.5% (n=249) -> 57.1%
    # (n=316) on composition alone. Recalibrated per the rule above
    # (new baseline minus tolerance), not deleted.
    "storage": 55,
}

# Core compat fields, same basis (2026-10-03: socket 99, chipset 96,
# memory_type 97, wattage_w 96, form_factor 74).
CORE_FLOORS = {
    "socket": 97,
    "chipset": 94,
    "memory_type": 95,
    "wattage_w": 94,
    # 2026-10-13: 72 -> 69. Same 1PC return: memory went 350 -> 368
    # products while memory form_factor was already 81% empty before it
    # (desktop DIMM is the unrecorded default, a schema question outside
    # this change), and the thin-spec HDDs carry no form factor either;
    # product-weighted fill went 73.7% -> 71.4% on composition alone.
    "form_factor": 69,
}


def category_fill(bucket: dict) -> float:
    fields = bucket.get("fields") or {}
    if not fields:
        return 0.0
    return sum(f.get("filled", 0) for f in fields.values()) / len(fields)


def core_fill(report: dict, field: str) -> float | None:
    """Product-weighted fill across categories carrying the field.

    Same formula as SpecReport.core_coverage (the site JSON stores field
    fill as percentages, so counts are reconstructed per category).
    """
    total = filled = 0
    for bucket in (report.get("categories") or {}).values():
        slot = (bucket.get("fields") or {}).get(field)
        if slot is None:
            continue
        n = bucket.get("products") or 0
        total += n
        filled += slot.get("filled", 0) * n / 100
    if not total:
        return None
    return filled * 100 / total


def main() -> int:
    if not REPORT.exists():
        print(f"[spec-coverage] report not found: {REPORT} (run normalize first)")
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    failures: list[str] = []

    gaps = report.get("label_gaps") or []
    gap_rows = sum(g.get("count", 0) for g in gaps)
    if gap_rows > LABEL_GAP_BUDGET:
        failures.append(
            f"label-gap rows {gap_rows} exceed budget {LABEL_GAP_BUDGET} "
            f"({len(gaps)} labels) — a vendor renamed labels or a mapping broke; "
            "see scripts/diagnose_spec_coverage.py --suggest")

    for category, floor in sorted(CATEGORY_FLOORS.items()):
        bucket = (report.get("categories") or {}).get(category)
        if bucket is None:
            failures.append(f"category {category!r} missing from the report")
            continue
        fill = category_fill(bucket)
        if fill < floor:
            failures.append(
                f"{category}: fill {fill:.1f}% below floor {floor}% "
                f"(n={bucket.get('products')})")

    for field, floor in sorted(CORE_FLOORS.items()):
        fill = core_fill(report, field)
        if fill is None:
            failures.append(f"core field {field!r} matches no category")
        elif fill < floor:
            failures.append(f"core field {field}: {fill:.1f}% below floor {floor}%")

    if failures:
        print(f"[spec-coverage] FAIL — {len(failures)} trip(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[spec-coverage] pass — gap rows {gap_rows}/{LABEL_GAP_BUDGET}, "
          f"{len(CATEGORY_FLOORS)} category floors + {len(CORE_FLOORS)} core floors held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
