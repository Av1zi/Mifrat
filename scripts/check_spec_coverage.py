"""
check_spec_coverage.py — spec-coverage regression gate (Oct 2026 coverage pass).

The repo has no test framework by design (see PROJECT_OVERVIEW §11), so this
is a plain script:

    python scripts/check_spec_coverage.py             # after a normalize run
    python scripts/check_spec_coverage.py --self-test # the gate's own math

It reads the catalog the normalizer just wrote plus data/site/spec_report.json
and fails when spec health regresses beyond daily-churn noise:

1. label-gap rows exceed the budget — the `label_gaps` frequency table is
   how the vocabulary in scraper/specs/labels.py grows from real vendor
   pages, so a sudden jump means a vendor renamed labels or a mapping broke;
2. a category's fill drops below its floor — floors come from the post-fix
   baseline of the Oct 2026 coverage pass (measured 2026-10-03), minus 2pp
   of tolerance for daily vendor churn;
3. a core compat field (socket, chipset, memory_type, wattage_w,
   form_factor) drops below its floor for the same reason.

Every rate is now COUNTED from the catalog (filled products / products, via
fill_report.analyse), not rebuilt from the site report's percentages, which
are rounded to whole points. The old reconstruction multiplied a rounded
percentage by a product count and divided back (`95 * 307 / 100 * 100 / 307`
= 94.99999999999999), so a catalog exactly at its floor failed on binary
float representation alone — run #322 failed with "95.0% below floor 95%"
while the true rate was 95.11%. spec_report.json is still used for the
label-gap table, and its product count is checked against the catalog so a
stale report cannot validate the wrong run.

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
CATALOG = ROOT / "data" / "catalog.json"

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
#
# 2026-10-23: 1950 -> 2300. Rows 1,621 -> 1,963 after the case-fan / CPU-cooling
# split and the title/weak-vendor spec work; same ~330-row margin. Also dropped
# the removed `cooling_other` category from the floors and lowered accessories
# 76 -> 73 (measured 75.8 on n=19, so one product swings it).
# 2026-10-24: 2300 -> 4000. The branch merge of the category restructure
# (CPU Cooling, no cooling_other) and the 1PC re-scrape left main itself at
# 3,504 gap rows (it already failed this check) and this branch at 3,079 after
# Icecat / maker data; 4,000 is the measured total + ~30% headroom. The labels
# are cooler / board detail rows with no schema column, not a broken mapping.
LABEL_GAP_BUDGET = 4000

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
# 2026-10-29: measured exactly from the catalog (not from rounded report
# percentages) — the floors still hold with >= 5.8pp of headroom each:
# accessories 78.89, aio 68.49, case 72.30, case_fan 70.50, cooler_air 70.82,
# cpu 92.12, gpu 81.25, memory 86.70, motherboard 81.19, psu 69.54,
# storage 60.61. No floor needed to move.
CATEGORY_FLOORS = {
    "accessories": 73,
    "aio": 54,
    "case": 59,
    "case_fan": 63,
    "cooler_air": 58,
    "cpu": 87,
    "gpu": 70,
    "memory": 79,
    "motherboard": 64,
    "psu": 53,
    "storage": 46,
}

# Core compat fields, same basis. 2026-10-03 measurements: socket 99,
# chipset 96, memory_type 97, wattage_w 96, form_factor 74.
#
# 2026-10-29: recalibrated to the 2pp rule the section above states, measured
# exactly from today's catalog: socket 99.06 -> 97, chipset 97.62 -> 95,
# memory_type 97.78 -> 95, wattage_w 95.11 -> 93, form_factor 94.83 -> 92.
# The old values were measured-0..1 (chipset 96, memory_type 96, wattage_w 95,
# form_factor 94), which left wattage_w 0.11pp of headroom — one PSU listing
# either way is 0.33pp at n=307, so the gate was guaranteed to re-trip on
# ordinary churn, and did (run #322). A floor's job is to catch a break (a
# parser that stops reading a field drops it 5-40pp), not a one-listing swing.
# CATEGORY_FLOORS and CORE_APPLICABLE_FLOORS were re-measured the same run and
# already sit >= 2.7pp clear, so they did not move.
CORE_FLOORS = {
    "socket": 97,
    "chipset": 95,
    "memory_type": 95,
    "wattage_w": 93,
    "form_factor": 92,
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
# 2026-10-29: re-measured exactly (>= 1.5pp clear, psu the tightest): aio 94.2,
# case 83.2, case_fan 68.6, cooler_air 85.3, cpu 93.7, gpu 89.4, memory 89.8,
# motherboard 91.1, psu 79.5, storage 81.6.
CORE_APPLICABLE_FLOORS = {
    "aio": 90,
    "case": 78,
    "case_fan": 64,
    "cooler_air": 82,
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
# products gain or lose real values. Measured 2026-10-23 (30.6% of products overall) after the sources
# pass (Icecat, foreign retailers, new makers), minus 3pp: a per-product share
# wobbles more than a mean when one vendor's offers come and go.
# 2026-10-29: re-measured exactly (>= 2.0pp clear): accessories 11.1, aio 15.2,
# case 28.7, case_fan 24.2, cooler_air 17.9, cpu 78.9, gpu 39.0, memory 57.8,
# motherboard 30.4, psu 25.1, storage 2.0. No floor needed to move.
PRODUCT_TARGET_FLOORS: dict[str, float] = {
    "accessories": 7,
    "aio": 11,
    "case": 26,
    "case_fan": 22,
    "cooler_air": 12,
    "cpu": 76,
    "gpu": 36,
    "memory": 54,
    "motherboard": 27,
    "psu": 22,
    "storage": 0,
}

# Rates are counted exactly as filled * 100 / n over integers, so a true value
# of exactly 95.0 is the double 95.0, and the smallest real gap between two
# rates at these sample sizes is ~100/4000 = 0.025pp. The epsilon only absorbs
# binary-float representation of a mean; it cannot hide a real drop.
RATE_EPSILON = 1e-9


def _below(rate: float, floor: float) -> bool:
    """True when `rate` is genuinely under `floor` (floors are inclusive)."""
    return rate < floor - RATE_EPSILON


def category_fill(bucket: dict) -> float:
    """Mean per-field fill % for one category, from exact product counts."""
    n = int(bucket.get("n") or 0)
    fields = bucket.get("fields") or {}
    if not n or not fields:
        return 0.0
    return sum(int(s.get("filled") or 0) * 100 / n for s in fields.values()) / len(fields)


def core_fill(analysed: dict, field: str) -> tuple[float | None, int, int]:
    """Product-weighted fill for one core field: (rate %, filled, products).

    Mirrors CoverageReport.core_coverage (specs/report.py): the denominator is
    every product in a category whose schema carries the field, not just the
    products where it applies. Counts come from the catalog, so no rate is
    reconstructed from a percentage rounded to a whole point.
    """
    filled = total = 0
    for bucket in analysed.values():
        slot = (bucket.get("fields") or {}).get(field)
        if slot is None:
            continue
        filled += int(slot.get("filled") or 0)
        total += int(bucket.get("n") or 0)
    if not total:
        return None, 0, 0
    return filled * 100 / total, filled, total


def evaluate(report: dict, analysed: dict, summary: dict) -> tuple[list[str], dict]:
    """Run every floor against an already-analysed catalog. Pure, for tests."""
    failures: list[str] = []

    gaps = report.get("label_gaps") or []
    gap_rows = sum(int(g.get("count") or 0) for g in gaps)
    if gap_rows > LABEL_GAP_BUDGET:
        failures.append(
            f"label-gap rows {gap_rows} exceed budget {LABEL_GAP_BUDGET} "
            f"({len(gaps)} labels) — a vendor renamed labels or a mapping broke; "
            "see scripts/diagnose_spec_coverage.py --suggest")

    # A spec_report.json from another run would validate stale numbers while
    # the catalog moves on, so a mismatch is a failure, not a warning.
    declared = report.get("products")
    counted = sum(int(bucket.get("n") or 0) for bucket in analysed.values())
    if declared is not None and int(declared) != counted:
        failures.append(
            f"spec_report.json is stale: it describes {declared} products, the "
            f"catalog has {counted} — rerun normalize and check both were written")

    for category, floor in sorted(CATEGORY_FLOORS.items()):
        bucket = analysed.get(category)
        if bucket is None:
            failures.append(f"category {category!r} missing from the catalog")
            continue
        fill = category_fill(bucket)
        if _below(fill, floor):
            failures.append(
                f"{category}: fill {fill:.2f}% below floor {floor}% "
                f"(n={bucket.get('n')})")

    for field, floor in sorted(CORE_FLOORS.items()):
        fill, filled, total = core_fill(analysed, field)
        if fill is None:
            failures.append(f"core field {field!r} matches no category")
        elif _below(fill, floor):
            failures.append(
                f"core field {field}: {fill:.2f}% ({filled}/{total}) "
                f"below floor {floor}%")

    for category, floor in sorted(CORE_APPLICABLE_FLOORS.items()):
        bucket = analysed.get(category)
        if bucket is None:
            failures.append(f"category {category!r} missing from the catalog")
            continue
        measured = float((bucket.get("core") or {}).get("applicable_fill_pct") or 0.0)
        if _below(measured, floor):
            failures.append(f"{category}: core applicable fill {measured:.2f}% "
                            f"below floor {floor}%")

    for category, floor in sorted(PRODUCT_TARGET_FLOORS.items()):
        measured = (summary.get(category) or {}).get("at_target_pct")
        if measured is None:
            failures.append(f"category {category!r} missing from the scoreboard")
        elif _below(float(measured), floor):
            failures.append(f"{category}: {float(measured):.2f}% of products at >= "
                            f"90% applicable fill, below floor {floor}%")

    return failures, {"gap_rows": gap_rows, "products": counted}


def _passing_dataset(n: int = 100) -> tuple[dict, dict, dict]:
    """Synthetic report + analysed catalog + scoreboard that pass every floor."""
    analysed: dict = {}
    for category in sorted(CATEGORY_FLOORS):
        analysed[category] = {
            "n": n,
            "fields": {field: {"filled": n} for field in CORE_FLOORS},
            "core": {"applicable_fill_pct": 100.0},
        }
    summary = {category: {"at_target_pct": 100.0} for category in PRODUCT_TARGET_FLOORS}
    report = {"products": n * len(analysed), "label_gaps": []}
    return report, analysed, summary


def _one_field_dataset(field: str, n: int, filled: int) -> tuple[dict, dict, dict]:
    """`_passing_dataset` with `field` carried by psu alone, at filled/n."""
    report, analysed, summary = _passing_dataset()
    for bucket in analysed.values():
        fields = bucket["fields"]
        fields.pop(field, None)
    analysed["psu"]["fields"][field] = {"filled": filled}
    analysed["psu"]["n"] = n
    report["products"] = sum(int(b.get("n") or 0) for b in analysed.values())
    return report, analysed, summary


def self_test() -> int:
    """Pin the arithmetic that run #322 broke. No data files, no network."""
    problems: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            problems.append(f"{name}{(': ' + detail) if detail else ''}")

    report, analysed, summary = _passing_dataset()
    failures, _ = evaluate(report, analysed, summary)
    check("clean dataset passes", not failures, "; ".join(failures))

    # The exact rate the old rounded reconstruction could not represent:
    # 95% of 307 products -> 291.65 -> *100/307 = 94.99999999999999.
    report, analysed, _ = _one_field_dataset("wattage_w", n=307, filled=292)
    rate, filled, total = core_fill(analysed, "wattage_w")
    check("counts survive the analysis", (filled, total) == (292, 307), f"{filled}/{total}")
    check("292/307 is 95.11%", abs((rate or 0.0) - 95.114) < 0.001, repr(rate))
    check("292/307 clears floor 95", not _below(rate or 0.0, 95))
    legacy = 95 * 307 / 100 * 100 / 307
    check("legacy reconstruction is the bug", legacy < 95, repr(legacy))

    # Inclusive floors: exactly at the floor passes, one product under fails.
    report, analysed, summary = _one_field_dataset("socket", n=100, filled=97)
    failures, _ = evaluate(report, analysed, summary)
    check("exactly at the floor passes",
          not any("core field socket" in f for f in failures), "; ".join(failures))
    report, analysed, summary = _one_field_dataset("socket", n=100, filled=96)
    failures, _ = evaluate(report, analysed, summary)
    check("below the floor fails",
          any("core field socket" in f for f in failures), "; ".join(failures))

    # Category means: 73.0% is at the floor, not under it.
    bucket = {"n": 100, "fields": {"a": {"filled": 73}, "b": {"filled": 73}}}
    check("category mean counts exactly", abs(category_fill(bucket) - 73.0) < 1e-9,
          repr(category_fill(bucket)))
    check("73.0 is not below 73", not _below(73.0, 73))
    check("72.9 is below 73", _below(72.9, 73))

    # Label-gap budget is inclusive and only a real overage trips.
    report, analysed, summary = _passing_dataset()
    report["label_gaps"] = [{"count": LABEL_GAP_BUDGET}]
    failures, _ = evaluate(report, analysed, summary)
    check("gap budget is inclusive", not any("label-gap" in f for f in failures))
    report["label_gaps"] = [{"count": LABEL_GAP_BUDGET + 1}]
    failures, _ = evaluate(report, analysed, summary)
    check("gap overage fails", any("label-gap" in f for f in failures))

    # A stale site report must not validate a newer catalog.
    report, analysed, summary = _passing_dataset()
    report["products"] = int(report["products"]) - 1
    failures, _ = evaluate(report, analysed, summary)
    check("stale spec_report fails", any("stale" in f for f in failures), "; ".join(failures))

    # A core field nobody carries is a failure, not a silent pass.
    report, analysed, summary = _passing_dataset()
    for bucket in analysed.values():
        bucket["fields"].pop("wattage_w", None)
    failures, _ = evaluate(report, analysed, summary)
    check("unmatched core field fails", any("matches no category" in f for f in failures))

    total_checks = 15
    if problems:
        print(f"[spec-coverage] self-test FAILED — {len(problems)} of ~{total_checks} checks:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"[spec-coverage] self-test pass — {total_checks} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--self-test" in args:
        return self_test()
    if not REPORT.exists():
        print(f"[spec-coverage] report not found: {REPORT} (run normalize first)")
        return 1
    if not CATALOG.exists():
        print(f"[spec-coverage] catalog not found: {CATALOG} (run normalize first)")
        return 1
    try:
        import fill_report
    except ImportError:
        sys.path.insert(0, str(ROOT / "scripts"))
        import fill_report

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    products = fill_report.load_products(CATALOG)
    analysed = fill_report.analyse(products)
    summary, _ = fill_report.per_product(products)
    failures, stats = evaluate(report, analysed, summary)

    if failures:
        print(f"[spec-coverage] FAIL — {len(failures)} trip(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[spec-coverage] pass — gap rows {stats['gap_rows']}/{LABEL_GAP_BUDGET} over "
          f"{stats['products']} products, {len(CATEGORY_FLOORS)} category floors + "
          f"{len(CORE_FLOORS)} core floors + {len(CORE_APPLICABLE_FLOORS)} applicable-core "
          f"floors + {len(PRODUCT_TARGET_FLOORS)} per-product floors held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
