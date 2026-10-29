"""Offline regression for the golden-fixture resolver (Oct 2026).

`scraper/specs/golden/check_golden.py` decides whether a hand-verified spec
fixture is *wrong* or merely *re-keyed*: product ids are rebuilt from whichever
vendor listings exist on the day, so a delist/merge/split moves them. That
decision is the difference between a red deploy and a warning, so it gets its
own synthetic-catalog test — the repo has no test framework by design (see
PROJECT_OVERVIEW §11), so this is a plain script:

    python scripts/check_golden_resolution.py

It covers the resolution ladder (id, alias, listing key, part number, model),
the strict-on-a-live-primary rule, part-number containment, the missing budget,
the category-collapse guard, the population guard and `part_key` parity with
`matching.mpn_part_key`.

Exit 0 = every case behaved; exit 1 = at least one did not (each printed).
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.matching import mpn_part_key  # noqa: E402
from scraper.specs.golden.check_golden import (  # noqa: E402
    EXIT_CHURN,
    EXIT_FAIL,
    EXIT_OK,
    check,
    moved_products,
    part_key,
    report,
    write_step_summary,
)

CHECKS = 0
FAILURES: list[str] = []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def product(
    product_id: str,
    category: str,
    specs: dict,
    listing_keys: tuple[str, ...] = (),
    vendor_count: int | None = None,
):
    return {
        "product_id": product_id,
        "category": category,
        "canonical_name": specs.get("name") or product_id,
        "model": specs.get("model"),
        "specs": specs,
        "offers": [{"listing_key": key} for key in listing_keys],
        "vendor_count": vendor_count,
    }


BOARD_SPECS = {
    "manufacturer": "MSI",
    "chipset": "B850",
    "memory_type": "DDR5",
    "part_numbers": ["AAA-1", "B850 BOARD"],
    "model": "B850 Board",
}


def board_case(product_id: str = "mpn:motherboard:missing", **overrides):
    case = {
        "product_id": product_id,
        "category": "motherboard",
        "name": "Test board",
        "expect": {"manufacturer": "MSI", "chipset": "B850"},
    }
    case.update(overrides)
    return case


def run(
    cases: list[dict],
    products: list[dict],
    *,
    reference: bool = False,
    strict: bool = False,
    baseline: dict | None = None,
):
    fixtures = {"schema_version": 3, "cases": cases}
    return check(
        {"products": products}, fixtures, reference, strict=strict, baseline=baseline
    )


def expect(name: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def expect_in(name: str, haystack: list[str], needle: str) -> None:
    global CHECKS
    CHECKS += 1
    joined = " | ".join(haystack)
    if needle not in joined:
        FAILURES.append(f"{name}: no {needle!r} in {joined!r}")


def expect_not_in(name: str, haystack: list[str], needle: str) -> None:
    global CHECKS
    CHECKS += 1
    joined = " | ".join(haystack)
    if needle in joined:
        FAILURES.append(f"{name}: unexpected {needle!r} in {joined!r}")


def captured_report(result, have_reference: bool = False) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        report(result, have_reference)
    return buffer.getvalue()


def filler(category: str, count: int, prefix: str) -> list[dict]:
    return [
        product(f"sku:{category}:{prefix}{index}", category, {"manufacturer": "X"})
        for index in range(count)
    ]


# --------------------------------------------------------------------------
# Resolution ladder
# --------------------------------------------------------------------------


def main() -> int:
    board = product(
        "mpn:motherboard:aaa1", "motherboard", BOARD_SPECS, ("1pc:1", "yahav:2"), 2
    )

    result = run([board_case("mpn:motherboard:aaa1")], [board])
    expect("id hit: exit", result.exit_code, EXIT_OK)
    expect("id hit: resolved", result.resolved, 1)

    result = run(
        [board_case("mpn:motherboard:aaa1", expect={"chipset": "X870"})], [board]
    )
    expect("id hit, wrong value: exit", result.exit_code, EXIT_FAIL)
    expect_in("id hit, wrong value: message", result.failures, "chipset")

    result = run([board_case("mpn:motherboard:gone")], [board])
    expect("no candidates: exit", result.exit_code, EXIT_CHURN)
    expect("no candidates: missing", len(result.missing), 1)

    result = run(
        [board_case("mpn:motherboard:gone", anchors={"ids": ["mpn:motherboard:aaa1"]})],
        [board],
    )
    expect("alias hit: exit", result.exit_code, EXIT_CHURN)
    expect("alias hit: resolved", result.resolved, 1)
    expect("alias hit: churn recorded", len(result.churned), 1)

    result = run(
        [board_case("mpn:motherboard:gone", anchors={"listing_keys": ["yahav:2"]})],
        [board],
    )
    expect("listing hit: exit", result.exit_code, EXIT_CHURN)
    expect("listing hit: resolved", result.resolved, 1)

    result = run(
        [board_case("mpn:motherboard:gone", anchors={"part_numbers": ["aaa1"]})],
        [board],
    )
    expect("part hit: exit", result.exit_code, EXIT_CHURN)
    expect("part hit: resolved", result.resolved, 1)

    result = run(
        [
            board_case(
                "mpn:motherboard:gone",
                anchors={"manufacturer": "MSI", "models": ["B850 Board"]},
            )
        ],
        [board],
    )
    expect("model hit: exit", result.exit_code, EXIT_CHURN)
    expect("model hit: resolved", result.resolved, 1)

    # A live primary whose values changed is a regression, never churn: an
    # anchor that happens to point at a sibling must not rescue it.
    stale_primary = product(
        "mpn:motherboard:aaa1",
        "motherboard",
        {**BOARD_SPECS, "chipset": "X870"},
        ("1pc:1",),
    )
    sibling = product(
        "mpn:motherboard:bbb2", "motherboard", BOARD_SPECS, ("1pc:9",)
    )
    result = run(
        [
            board_case(
                "mpn:motherboard:aaa1",
                anchors={"ids": ["mpn:motherboard:bbb2"]},
            )
        ],
        [stale_primary, sibling],
    )
    expect("live primary wins over sibling: exit", result.exit_code, EXIT_FAIL)
    expect_in("live primary wins over sibling: message", result.failures, "chipset")

    # Two anchor candidates, neither carries the expected values.
    other_one = product(
        "mpn:motherboard:ccc3", "motherboard", {"chipset": "X870"}, ("1pc:3",)
    )
    other_two = product(
        "mpn:motherboard:ddd4", "motherboard", {"chipset": "Z890"}, ("1pc:4",)
    )
    result = run(
        [
            board_case(
                "mpn:motherboard:gone",
                anchors={"listing_keys": ["1pc:3", "1pc:4"]},
            )
        ],
        [other_one, other_two],
    )
    expect("ambiguous failure: exit", result.exit_code, EXIT_FAIL)
    expect_in("ambiguous failure: message", result.failures, "none matched")
    expect_in("ambiguous failure: context", result.failures, "other candidates")

    # ----------------------------------------------------------------------
    # Assertion semantics
    # ----------------------------------------------------------------------

    generous = product(
        "mpn:storage:eee5",
        "storage",
        {"part_numbers": ["MZ-V9P2T0BW", "EXTRA-CODE"]},
        ("tms:1",),
    )
    result = run(
        [
            {
                "product_id": "mpn:storage:eee5",
                "category": "storage",
                "expect": {"part_numbers": ["mzv9p2t0bw"]},
            }
        ],
        [generous],
    )
    expect("part_numbers containment: superset passes", result.exit_code, EXIT_OK)

    result = run(
        [
            {
                "product_id": "mpn:storage:eee5",
                "category": "storage",
                "expect": {"part_numbers": ["MZ-V9P2T0BW", "NOPE-9"]},
            }
        ],
        [generous],
    )
    expect("part_numbers containment: missing entry fails", result.exit_code, EXIT_FAIL)
    expect_in(
        "part_numbers containment: message", result.failures, "part_numbers missing"
    )

    cooler = product(
        "sku:cooler_air:fff6", "cooler_air", {"water_cooled": True, "fan_rpm_max": 1800}
    )
    result = run(
        [
            {
                "product_id": "sku:cooler_air:fff6",
                "category": "cooler_air",
                "expect_null": ["water_cooled", "radiator_size_mm"],
            }
        ],
        [cooler],
    )
    expect("expect_null: exit", result.exit_code, EXIT_FAIL)
    expect_in("expect_null: message", result.failures, "should be unknown")

    tier0_case = {
        "product_id": "mpn:motherboard:aaa1",
        "category": "motherboard",
        "name": "Test board",
        "expect": {"chipset": "B850"},
        "expect_reference": {"socket": "AM5"},
    }
    expect(
        "expect_reference skipped without the index",
        run([tier0_case], [board]).exit_code,
        EXIT_OK,
    )
    expect(
        "expect_reference enforced with the index",
        run([tier0_case], [board], reference=True).exit_code,
        EXIT_FAIL,
    )

    # ----------------------------------------------------------------------
    # Reporting
    # ----------------------------------------------------------------------

    churn_result = run(
        [board_case("mpn:motherboard:gone", anchors={"ids": ["mpn:motherboard:aaa1"]})],
        [board],
    )
    text = captured_report(churn_result)
    expect_in("report: churn verdict", [text], "pass (identity churn)")
    expect_in("report: churn count", [text], "resolved through an anchor")

    missing_result = run([board_case("mpn:motherboard:gone")], [board])
    text = captured_report(missing_result)
    expect_in("report: repair hint is runnable", [text], "--update-anchors --apply")

    fail_text = captured_report(
        run([board_case("mpn:motherboard:aaa1", expect={"chipset": "X870"})], [board])
    )
    expect_in("report: failure verdict", [fail_text], "FAIL")

    summary_path = Path(tempfile.mkdtemp()) / "summary.md"
    os.environ["GITHUB_STEP_SUMMARY"] = str(summary_path)
    try:
        write_step_summary(missing_result)
    finally:
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
    summary = summary_path.read_text(encoding="utf-8")
    expect_in("summary: verdict", [summary], "pass (identity churn)")
    expect_in("summary: missing section", [summary], "**Missing cases**")
    expect_in("summary: repair hint", [summary], "--update-anchors --apply")

    # ----------------------------------------------------------------------
    # Missing budget and collapse guards
    # ----------------------------------------------------------------------

    categories = ["cpu", "gpu", "case", "psu"]
    absent = [
        {"product_id": f"mpn:{name}:gone", "category": name} for name in categories
    ]
    result = run(absent, [])
    expect("budget: 4 missing of 4", result.exit_code, EXIT_FAIL)
    expect("budget: value", result.budget, 2)

    thirteen_missing = [
        {"product_id": f"mpn:cat{index}:gone", "category": f"cat{index}"}
        for index in range(13)
    ]
    expect("budget: 13 cases -> 3", run(thirteen_missing, []).budget, 3)
    expect(
        "budget: exactly 3 missing of 13 passes",
        run(
            thirteen_missing[:3] + [board_case("mpn:motherboard:aaa1")] * 10, [board]
        ).exit_code,
        EXIT_CHURN,
    )
    expect(
        "budget: 4 missing of 13 fails",
        run(
            thirteen_missing[:4] + [board_case("mpn:motherboard:aaa1")] * 9, [board]
        ).exit_code,
        EXIT_FAIL,
    )

    two_live = run(
        absent[:2] + [board_case("mpn:motherboard:aaa1")] * 2,
        [board],
    )
    expect("budget: 2 missing of 4", two_live.exit_code, EXIT_CHURN)
    expect("budget: 2 missing counted", len(two_live.missing), 2)

    strict_run = run(absent[:1], [], strict=True)
    expect("strict: one missing", strict_run.exit_code, EXIT_FAIL)
    expect_in("strict: message", strict_run.failures, "strict:")

    collapse = run(
        [
            {"product_id": "mpn:gpu:gone1", "category": "gpu"},
            {"product_id": "mpn:gpu:gone2", "category": "gpu"},
            board_case("mpn:motherboard:aaa1"),
            board_case("mpn:motherboard:aaa1"),
        ],
        [board],
    )
    expect("category collapse: exit", collapse.exit_code, EXIT_FAIL)
    expect_in("category collapse: message", collapse.failures, "matching collapse")

    # ----------------------------------------------------------------------
    # Population guard
    # ----------------------------------------------------------------------

    baseline = {"products": filler("gpu", 20, "b") + filler("cpu", 20, "b")}
    cases = [board_case("mpn:motherboard:aaa1")]

    mild = filler("gpu", 18, "f") + filler("cpu", 20, "f")
    expect(
        "population: 10% category drop tolerated",
        run(cases, [board] + mild, baseline=baseline).exit_code,
        EXIT_OK,
    )

    crushed = filler("gpu", 10, "f") + filler("cpu", 20, "f")
    result = run(cases, [board] + crushed, baseline=baseline)
    expect("population: 50% category drop fails", result.exit_code, EXIT_FAIL)
    expect_in("population: message", result.failures, "category 'gpu'")

    big_baseline = {"products": filler("gpu", 60, "b") + filler("cpu", 60, "b")}
    shrunk = filler("gpu", 52, "f") + filler("cpu", 52, "f")
    result = run(cases, [board] + shrunk, baseline=big_baseline)
    expect("population: total drop fails", result.exit_code, EXIT_FAIL)
    expect_in("population: total message", result.failures, "catalog:")
    expect_not_in(
        "population: no category false positive", result.failures, "category '"
    )

    moved_baseline = {
        "products": [product("mpn:motherboard:old", "motherboard", {}, ("1pc:7",))]
    }
    moved_fresh = {
        "products": [product("mpn:motherboard:new", "motherboard", {}, ("1pc:7",))]
    }
    moved = moved_products(moved_fresh, moved_baseline)
    expect("moved products: detected", len(moved), 1)
    expect_in("moved products: line", moved, "mpn:motherboard:old -> mpn:motherboard:new")

    # ----------------------------------------------------------------------
    # Key parity with the matcher
    # ----------------------------------------------------------------------

    samples = [
        "MZ-V9P2T0BW",
        "mzv9p2t0bw",
        "GV-N5070AERO OC-12GD",
        "N5070AEROOC12GD",
        "4711377290623",
        "B850 AORUS ELITE WIFI7",
        "",
        None,
    ]
    for sample in samples:
        expect(
            f"part_key parity: {sample!r}",
            part_key(sample),
            mpn_part_key(sample),
        )

    # ----------------------------------------------------------------------

    if FAILURES:
        print(f"[golden-resolver] FAIL - {len(FAILURES)} of {CHECKS}")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"[golden-resolver] pass - {CHECKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
