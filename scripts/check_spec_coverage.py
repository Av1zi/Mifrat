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
#
# 2026-10-15: 6200 -> 2100. The completeness pass gave those backlog labels
# their schema homes (GPU memory speed / bus width / API + display rows,
# board storage interface + Bluetooth + Thunderbolt + x4 slots, cooler
# dimensions and wiring, drive throughput, packaging) and gap rows fell
# 4,655 -> 1,651. The old budget would have left ~4,500 rows of headroom,
# i.e. it could no longer see a real rename. Same rule: measured total
# (1,651) + ~30% headroom.
#
# 2026-10-16: 2100 -> 1600. Batch 3 gave columns to the last big deferred
# labels (cpu generation, psu series wattage range, drive weight) and read
# 1PC's grouped cells per category (Storage / Storage Type, Interface
# Connectivity), so gap rows fell 1,651 -> 1,237. What remains is genuinely
# unreadable or has no schema home: Hebrew CPU-support prose (106), Yahav's
# ambiguous modularity badge (76 — it sits on semi-modular units too), spec
# blocks leaked onto accessory pages (~100), flattened "מפרט" cells (26).
# Same rule: measured total (1,237) + ~30% headroom.
LABEL_GAP_BUDGET = 1600

# Mean field-fill % per category, minus 2pp tolerance.
#
# 2026-10-15: every floor recalibrated by the same completeness pass. This
# metric is a RATE (filled values / schema fields), so adding real but sparse
# fields moves it down while the catalog knows MORE: 21 new fields landed and
# total filled facts went 43,905 -> 46,832 (+2,927), yet each category's rate
# fell (storage 57.2 -> 46.7 with read/write/IOPS/packaging added, gpu
# 56.3 -> 52.6 while gaining 1,056 real facts over 9 more fields). Floors are
# the new baselines minus the same 2pp tolerance, so a genuine mapping break
# still trips — every new parser is pinned by pair cases in
# scripts/check_tms_detail.py.
CATEGORY_FLOORS = {
    "accessories": 43,
    "aio": 43,
    "case": 41,
    # 2026-10-14: 60 -> 55. Yahav onboarded: 201 of 471 case_fan products
    # are Yahav's, averaging 8.0 filled fields/product vs 9.0 for the rest
    # (its tables are ~5 rows), so mean fill went to 57.7% on composition
    # alone — measured, not a mapping regression (pair cases still pass).
    # 2026-10-14 (same day): 55 -> 54. The lone-RPM bugfix (a lone
    # "2200 RPM" filed as min==max) removed false rpm_min fills; the 55
    # floor had been set on the inflated count.
    # 2026-10-15: 54 -> 53 on the recalibration above (case_fan 55.1%).
    "case_fan": 53,
    "cooler_air": 35,
    "cooling_other": 23,
    "cpu": 78,
    "gpu": 50,
    "memory": 57,
    # 2026-10-14: 51 -> 46. Same Yahav onboarding: 148 of 710 boards are
    # Yahav's at 10.1 filled fields/product vs 16.9 for the rest (its
    # boards carry ~5 Hebrew rows where 1PC/TMS carry full tables),
    # dragging mean fill to 48.5% on composition alone.
    # 2026-10-15: 46 -> 43. Board fill is 45.3% now: storage_interface (62%)
    # and Bluetooth/Thunderbolt/x4/lighting/packaging (5-21%) added six
    # fields — 11,118 -> 11,947 real board facts.
    "motherboard": 43,
    "psu": 43,
    # 2026-10-13: 58 -> 55. 1PC returned to the catalog (Oct 2026
    # storefront rebuild) bringing 66 HDD listings whose vendor tables
    # are 5 thin rows (model/capacity/type/warranty, no form-factor or
    # interface evidence to map); storage went 60.5% (n=249) -> 57.1%
    # (n=316) on composition alone. Recalibrated per the rule above
    # (new baseline minus tolerance), not deleted.
    # 2026-10-15: 55 -> 44. Same rule again, larger effect: 14 -> 19 fields
    # (sequential read/write, random IOPS, packaging). Storage facts went
    # 2,570 -> 2,844 while the rate fell to 46.7%.
    "storage": 44,
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
