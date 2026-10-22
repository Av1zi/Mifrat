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
# 2026-10-17: 1600 -> 1300. Phase 1 mapped the labels that had a schema home and
# the pruned fields' labels left the vocabulary; gap rows measure 978 now
# (+~30% headroom). What remains is laptop/server prose filed under PC categories.
#
# 2026-10-18: 1300 -> 1450. The second pruning pass removed 32 sparse field slots; the
# vendor labels that fed them are now unmapped gap evidence on purpose (rows
# 967 -> 1,131, +30% headroom would be 1,470; 1,450 keeps the same margin).
#
# 2026-10-21: 1450 -> 1950. 1PC added an English Icecat spec sheet to its
# ASUS GPU pages (~50 rows per card). The rows with a schema home are mapped
# and the box/manual rows ignored; what remains (HDCP, CUDA, slot width, VR
# ready, ...) has no column, so it is gap evidence, not breakage. Rows
# 1,436 -> 1,621; 1,950 keeps the same ~330-row margin as before.
LABEL_GAP_BUDGET = 1950

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
# 2026-10-17 (spec completeness, Phase 1): every floor recalibrated again, this
# time UPWARD - measured mean fill minus 2pp. The cooler schema split, pruned
# dead fields (vrm_phases, back_connect, power_connections, controller, IOPS,
# frame_sync), curated tables, explicit-negative rules and the manufacturer tier
# raised the rate: aio 48.3, case 53.3, case_fan 59.5, cooler_air 52.8,
# cooling_other 34.5, cpu 86.0, gpu 65.0, memory 74.8, motherboard 55.7,
# psu 51.3, storage 52.5, accessories 45.1 (baseline overall 48.8 -> 58.6).
# 2026-10-18 (Plan B, second pruning pass): recalibrated again, measured mean
# minus 2pp. The rates rose mostly because 32 sparse field slots left the schema (the
# denominator shrank), not because the catalog suddenly knows that much more:
# aio 56.0, case 61.1, case_fan 65.4, cooler_air 60.0, cooling_other 45.5,
# cpu 89.9, gpu 72.4, memory 81.7, motherboard 66.6, psu 55.2, storage 61.8,
# accessories 78.8.
# 2026-10-18 (S270 spec-fill round): storage 59 -> 46. The storage schema gained
# five real columns the MSI Spatium S270 page prints (series, dimensions_mm,
# mtbf_hours, warranty_years, weight_g). Only `series` is broadly populated
# (85%); the other four are sparse (1-2%) because few drive pages print them,
# so the RATE fell even though filled cells rose. This is the same
# denominator-dilution the 2026-10-15 note describes; the floor follows the
# measured value (48) minus 2pp.
CATEGORY_FLOORS = {
    "accessories": 76,
    "aio": 54,
    "case": 59,
    "case_fan": 63,
    "cooler_air": 58,
    "cooling_other": 43,
    "cpu": 87,
    "gpu": 70,
    "memory": 79,
    "motherboard": 64,
    "psu": 53,
    "storage": 46,
}

# Core compat fields, same basis (2026-10-03: socket 99, chipset 96,
# memory_type 97, wattage_w 96, form_factor 74).
CORE_FLOORS = {
    "socket": 97,
    "chipset": 96,
    "memory_type": 96,
    "wattage_w": 95,
    # 2026-10-17: 69 -> 94 (measured 96.0): memory form_factor is now derived
    # from "no laptop marker" and boards/cases gained manufacturer-page values.
    "form_factor": 94,
}


# Applicable CORE-field fill per category (scripts/fill_report.py CORE_FIELDS:
# the fields a buyer / the compat engine needs, "not applicable" cells excluded),
# measured 2026-10-17 after Phase 1 minus 2pp tolerance. The Phase-1 target is
# 95%; the gap to it is explained per brand by `fill_report.py --gaps`
# (Gigabyte/MSI block automated fetches, the long brand tail has no fetcher) and
# in decisions.md - the floors only stop it from sliding back.
# 2026-10-18 (Plan B): raised to the new measurement minus 2pp (aio 92.3,
# case 80.2, case_fan 69.1, cooler_air 83.9, cpu 93.9, motherboard 86.8 ...).
# 2026-10-19: case_fan 67 -> 64. The reference join stopped linking fans to
# sibling models (Corsair RX120 -> RS120, LX/QL120 -> LL120, Lian Li TL120 ->
# SL120; scripts/audit_reference_matches.py): measured 66.7% after removing
# those wrong rpm/airflow/noise values, minus the usual 2pp.
CORE_APPLICABLE_FLOORS = {
    "aio": 90,
    "case": 78,
    "case_fan": 64,
    "cooler_air": 82,
    "cooling_other": 70,
    "cpu": 91,
    "gpu": 81,
    "memory": 85,
    "motherboard": 84,
    "psu": 78,
    "storage": 76,
}

# Share of products at >= 90% APPLICABLE fill (fill_report.per_product: filled /
# (schema fields - fields that cannot exist for this product - fields a sibling
# answers)). Unlike CATEGORY_FLOORS this rate cannot be raised by pruning
# columns or lowered by a correct not-applicable gate: it moves only when
# products gain or lose real values. Measured __MEASURED__ after the sources
# pass (Icecat, foreign retailers, new makers), minus 3pp: a per-product share
# wobbles more than a mean when one vendor's offers come and go.
PRODUCT_TARGET_FLOORS: dict[str, float] = {}


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

    catalog = ROOT / "data" / "catalog.json"
    if catalog.exists():
        import fill_report

        analysed = fill_report.analyse(fill_report.load_products(catalog))
        for category, floor in sorted(CORE_APPLICABLE_FLOORS.items()):
            bucket = analysed.get(category)
            if bucket is None:
                failures.append(f"category {category!r} missing from the catalog")
                continue
            measured = bucket["core"]["applicable_fill_pct"]
            if measured < floor:
                failures.append(f"{category}: core applicable fill {measured:.1f}% "
                                f"below floor {floor}%")

        summary, _ = fill_report.per_product(fill_report.load_products(catalog))
        for category, floor in sorted(PRODUCT_TARGET_FLOORS.items()):
            measured = (summary.get(category) or {}).get("at_target_pct")
            if measured is None:
                failures.append(f"category {category!r} missing from the scoreboard")
            elif measured < floor:
                failures.append(f"{category}: {measured:.1f}% of products at >= "
                                f"{fill_report.PRODUCT_TARGET:.0f}% applicable fill, "
                                f"below floor {floor}%")

    if failures:
        print(f"[spec-coverage] FAIL — {len(failures)} trip(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[spec-coverage] pass — gap rows {gap_rows}/{LABEL_GAP_BUDGET}, "
          f"{len(CATEGORY_FLOORS)} category floors + {len(CORE_FLOORS)} core floors + "
          f"{len(CORE_APPLICABLE_FLOORS)} applicable-core floors + "
          f"{len(PRODUCT_TARGET_FLOORS)} per-product floors held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
