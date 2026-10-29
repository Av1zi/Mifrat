"""
specs/golden/check_golden.py — assert the pipeline's output matches hand-verified
specs (plan Phase 5).

The repo has no test framework by design (see PROJECT_OVERVIEW §11), so this is a
plain script:

    python -m scraper.specs.golden.check_golden            # after a normalize run
    python -m scraper.specs.golden.check_golden --catalog path/to/catalog.json

It reads data/catalog.json, resolves each fixture to a product and compares:

- `expect`           — always asserted (title/vendor-sourced facts).
- `expect_reference` — asserted only when the optional pcpartdb index exists,
                       because Tier 0 is off by design without it.
- `expect_null`      — the field MUST be unknown (null or absent). This pins a
                       wrong value as a regression: an air cooler must never
                       claim `water_cooled` / `radiator_size_mm`, a 2 TB drive
                       must never claim `capacity_gb: 2`.

Resolution — a fixture's `product_id` is derived from whichever vendor listings
exist on the day, so it churns. A case therefore carries optional `anchors`
(the listing keys, part numbers and model it was verified against). The lookup
is:

1. the fixture's own `product_id`, if it is in the catalog — and then ONLY it,
   because a live product whose values changed is a regression, not churn;
2. otherwise `anchors.ids`;
3. otherwise products owning an `anchors.listing_keys` entry;
4. otherwise products whose `specs.part_numbers` match an anchor / an
   `expect.part_numbers` entry (same category);
5. otherwise products matching `anchors.manufacturer` + `anchors.models`
   (same category).

`expect.part_numbers` is a CONTAINMENT assertion, never equality: a product may
gain a manufacturer model code (`specs.build.with_model_code`), and an extra
alias is not a regression.

Exit codes
----------
0  every case resolved by its own product id and every assertion held.
2  no wrong value anywhere, but identity churn was visible: a case resolved
   through an anchor, or a case has no product at all (within the missing
   budget). The catalog still publishes; the workflow turns this into a
   warning annotation.
1  a resolved case has a wrong value, missing cases exceed the budget, a
   category lost every fixture, or the catalog population collapsed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .. import schema

ROOT = Path(__file__).resolve().parent.parent.parent.parent
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures.json"
DEFAULT_CATALOG = ROOT / "data" / "catalog.json"
INDEX_PATH = ROOT / "data" / "pcpartdb" / "index.json"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CHURN = 2

# A vanished product is churn; a vanished quarter of the fixtures is a matching
# collapse. max(2, 25%) means three of the current 13 cases can go missing
# before the gate goes red — the old behaviour (fail on the first one) is what
# blocked deploys; the old "delete the case" behaviour is what silently
# unpinned the socket-list rule. Both are worse than a bounded budget.
MISSING_BUDGET_RATIO = 0.25
MISSING_BUDGET_FLOOR = 2
# Population guard (only with --baseline). Matched against the previously
# committed catalog, so no extra state is needed. vendor stale-forwarding keeps
# a normal day well inside these numbers.
POPULATION_CATEGORY_DROP = 0.15
POPULATION_TOTAL_DROP = 0.10
POPULATION_MIN_CATEGORY = 10
POPULATION_MIN_TOTAL = 100


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


def _fold(value: object) -> str:
    """Unicode NFKD, ASCII-fold, lowercase, collapse punctuation to spaces."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def part_key(value: object) -> str:
    """Same key shape as matching.mpn_part_key (compact + Gigabyte GV strip).

    Duplicated rather than imported so the gate keeps its light dependency set
    (`..schema` only); scripts/check_golden_resolution.py asserts parity against
    the real function.
    """
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if len(key) > 5 and key.startswith("gv"):
        rest = key[2:]
        if len(rest) >= 3 and re.search(r"\d", rest):
            return rest
    return key


def _case_label(case: dict) -> str:
    return str(case.get("product_id") or case.get("name") or "<unnamed case>")


# --------------------------------------------------------------------------
# Indexes and resolution
# --------------------------------------------------------------------------


@dataclass
class Indexes:
    by_id: dict[str, dict] = field(default_factory=dict)
    by_listing: dict[str, list[dict]] = field(default_factory=dict)
    by_part: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    by_model: dict[tuple[str, str, str], list[dict]] = field(default_factory=dict)


def build_indexes(catalog: dict) -> Indexes:
    indexes = Indexes()
    for product in catalog.get("products") or []:
        product_id = str(product.get("product_id") or "")
        if not product_id:
            continue
        indexes.by_id[product_id] = product
        category = str(product.get("category") or "")
        specs = product.get("specs") or {}

        for offer in product.get("offers") or []:
            key = offer.get("listing_key")
            if key:
                indexes.by_listing.setdefault(str(key), []).append(product)

        for value in specs.get("part_numbers") or []:
            key = part_key(value)
            if key:
                indexes.by_part.setdefault((category, key), []).append(product)

        model = specs.get("model") or product.get("model")
        manufacturer = specs.get("manufacturer")
        if model and manufacturer:
            indexes.by_model.setdefault(
                (category, part_key(manufacturer), part_key(model)), []
            ).append(product)
    return indexes


def _dedupe(products: list[dict]) -> list[dict]:
    seen: set[str] = set()
    ordered: list[dict] = []
    for product in products:
        key = str(product.get("product_id"))
        if key and key not in seen:
            seen.add(key)
            ordered.append(product)
    return ordered


def resolve_case(case: dict, indexes: Indexes) -> tuple[list[dict], str]:
    """Return (candidates, mode) where mode is "primary" or "anchors"."""
    primary = indexes.by_id.get(str(case.get("product_id") or ""))
    if primary is not None:
        return [primary], "primary"

    anchors = case.get("anchors") or {}
    category = str(case.get("category") or "")
    found: list[dict] = []

    for anchor_id in anchors.get("ids") or []:
        product = indexes.by_id.get(str(anchor_id))
        if product is not None:
            found.append(product)

    for listing_key in anchors.get("listing_keys") or []:
        found.extend(indexes.by_listing.get(str(listing_key), []))

    part_anchors = list(anchors.get("part_numbers") or [])
    part_anchors += list((case.get("expect") or {}).get("part_numbers") or [])
    for value in part_anchors:
        key = part_key(value)
        if key:
            found.extend(indexes.by_part.get((category, key), []))

    manufacturer = anchors.get("manufacturer")
    if manufacturer:
        for model in anchors.get("models") or []:
            found.extend(
                indexes.by_model.get(
                    (category, part_key(manufacturer), part_key(model)), []
                )
            )

    return _dedupe(found), "anchors"


# --------------------------------------------------------------------------
# Assertions
# --------------------------------------------------------------------------


def _field_problems(label: str, product: dict, field_name: str, expected) -> list[str]:
    specs = product.get("specs") or {}
    actual = specs.get(field_name)

    if field_name == "part_numbers" and isinstance(expected, list):
        present = part_key_set(actual)
        missing = [value for value in expected if part_key(value) not in present]
        if missing:
            return [
                f"{label}: part_numbers missing {missing!r}, got {actual!r}"
            ]
        return []

    if actual != expected:
        return [f"{label}: {field_name} = {actual!r}, expected {expected!r}"]
    return []


def part_key_set(values) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {part_key(value) for value in values if part_key(value)}


def evaluate(case: dict, product: dict, have_reference: bool) -> list[str]:
    label = _case_label(case)
    problems: list[str] = []

    if case.get("category") and product.get("category") != case["category"]:
        problems.append(
            f"{label}: category {product.get('category')!r} != {case['category']!r}"
        )

    for field_name, expected in (case.get("expect") or {}).items():
        problems.extend(_field_problems(label, product, field_name, expected))

    if have_reference:
        for field_name, expected in (case.get("expect_reference") or {}).items():
            problems.extend(_field_problems(label, product, field_name, expected))

    specs = product.get("specs") or {}
    for field_name in case.get("expect_null") or []:
        actual = specs.get(field_name)
        if actual is not None:
            problems.append(
                f"{label}: {field_name} should be unknown, got {actual!r}"
            )

    return problems


def count_assertions(case: dict, have_reference: bool) -> int:
    total = len(case.get("expect") or {})
    if have_reference:
        total += len(case.get("expect_reference") or {})
    total += len(case.get("expect_null") or [])
    return total


# --------------------------------------------------------------------------
# Population guard
# --------------------------------------------------------------------------


def moved_products(catalog: dict, baseline: dict) -> list[str]:
    """Products whose id changed but whose listing is the same as before."""
    fresh_by_listing: dict[str, dict] = {}
    for product in catalog.get("products") or []:
        for offer in product.get("offers") or []:
            key = offer.get("listing_key")
            if key:
                fresh_by_listing[str(key)] = product

    moved: list[str] = []
    for product in baseline.get("products") or []:
        old = str(product.get("product_id") or "")
        for offer in product.get("offers") or []:
            key = offer.get("listing_key")
            if not key:
                continue
            match = fresh_by_listing.get(str(key))
            if match is None:
                continue
            new = str(match.get("product_id") or "")
            if new and new != old:
                moved.append(f"{old} -> {new}")
            break
    return moved


def population_problems(catalog: dict, baseline: dict) -> list[str]:
    problems: list[str] = []
    fresh_counts = Counter(
        str(p.get("category") or "") for p in catalog.get("products") or []
    )
    base_counts = Counter(
        str(p.get("category") or "") for p in baseline.get("products") or []
    )

    for category, before in base_counts.items():
        after = fresh_counts.get(category, 0)
        if before < POPULATION_MIN_CATEGORY:
            continue
        if after < before * (1 - POPULATION_CATEGORY_DROP):
            problems.append(
                f"category {category!r}: {before} -> {after} products "
                f"(drop > {POPULATION_CATEGORY_DROP:.0%}; matching collapse?)"
            )

    before_total = sum(base_counts.values())
    after_total = sum(fresh_counts.values())
    if before_total >= POPULATION_MIN_TOTAL and after_total < (
        before_total * (1 - POPULATION_TOTAL_DROP)
    ):
        problems.append(
            f"catalog: {before_total} -> {after_total} products "
            f"(drop > {POPULATION_TOTAL_DROP:.0%}; matching collapse?)"
        )
    return problems


# --------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------


@dataclass
class Result:
    total: int = 0
    checked: int = 0
    resolved: int = 0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    churned: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    budget: int = 0

    @property
    def exit_code(self) -> int:
        if self.failures:
            return EXIT_FAIL
        if self.missing or self.churned:
            return EXIT_CHURN
        return EXIT_OK


def missing_budget(total_cases: int) -> int:
    return max(MISSING_BUDGET_FLOOR, round(total_cases * MISSING_BUDGET_RATIO))


def check(
    catalog: dict,
    fixtures: dict,
    have_reference: bool,
    *,
    strict: bool = False,
    baseline: dict | None = None,
) -> Result:
    result = Result()
    cases = list(fixtures.get("cases") or [])
    result.total = len(cases)
    result.budget = missing_budget(result.total)
    indexes = build_indexes(catalog)

    missing_cases: list[dict] = []
    for case in cases:
        label = _case_label(case)
        candidates, mode = resolve_case(case, indexes)

        if not candidates:
            missing_cases.append(case)
            result.missing.append(f"{label} ({case.get('name')})")
            continue

        result.checked += count_assertions(case, have_reference)

        if mode == "primary":
            problems = evaluate(case, candidates[0], have_reference)
            if problems:
                result.failures.extend(problems)
            else:
                result.resolved += 1
            continue

        evaluated = [
            (product, evaluate(case, product, have_reference))
            for product in candidates
        ]
        winner = next(
            (product for product, problems in evaluated if not problems), None
        )
        if winner is not None:
            result.resolved += 1
            result.churned.append(label)
            result.warnings.append(
                f"{label} ({case.get('name')}): its product id is gone; an anchor "
                f"still resolves it to {winner.get('product_id')}"
            )
            continue

        best, best_problems = min(evaluated, key=lambda item: len(item[1]))
        others = [
            str(product.get("product_id"))
            for product in candidates
            if product is not best
        ]
        result.failures.extend(best_problems)
        context = f" (other candidates: {', '.join(others)})" if others else ""
        result.failures.append(
            f"{label}: {len(candidates)} candidate(s), none matched{context}"
        )

    if strict and missing_cases:
        result.failures.append(
            f"strict: {len(missing_cases)} case(s) have no product in the catalog"
        )
    elif len(missing_cases) > result.budget:
        result.failures.append(
            f"{len(missing_cases)} case(s) no longer resolvable, "
            f"budget is {result.budget}"
        )

    missing_ids = {id(case) for case in missing_cases}
    by_category: dict[str, list[dict]] = {}
    for case in cases:
        by_category.setdefault(str(case.get("category") or ""), []).append(case)
    for category, group in by_category.items():
        if len(group) >= 2 and all(id(case) in missing_ids for case in group):
            result.failures.append(
                f"category {category!r}: all {len(group)} fixture(s) are missing "
                "(matching collapse?)"
            )

    if baseline is not None:
        result.failures.extend(population_problems(catalog, baseline))
        result.moved = moved_products(catalog, baseline)

    return result


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def report(result: Result, have_reference: bool) -> None:
    for warning in result.warnings:
        print(f"[golden] warn: {warning}")

    if result.moved:
        print(
            f"[golden] note: {len(result.moved)} product(s) were re-keyed "
            "since the previous catalog"
        )
        for line in result.moved[:5]:
            print(f"  - {line}")
        if len(result.moved) > 5:
            print(f"  - ... and {len(result.moved) - 5} more")

    if result.missing:
        print(
            f"[golden] {len(result.missing)} of {result.total} case(s) have no "
            f"product in the catalog (budget {result.budget}):"
        )
        for item in result.missing:
            print(f"  - {item}")
        print(
            "[golden] action: run `python -m scraper.specs.golden.check_golden "
            "--update-anchors` to refresh anchors, or retire the case with a "
            "`_pins` note if the product left the catalog."
        )

    if result.failures:
        print(
            f"[golden] FAIL — {len(result.failures)} mismatch(es) over "
            f"{result.total} cases:"
        )
        for failure in result.failures:
            print(f"  - {failure}")
        return

    tier_note = "" if have_reference else " (Tier-0 checks skipped)"
    skipped = f", {len(result.missing)} skipped" if result.missing else ""
    print(
        f"[golden] pass — {result.checked} assertions over {result.resolved} "
        f"product(s){skipped}{tier_note}"
    )
    if result.churned:
        print(
            f"[golden] {len(result.churned)} case(s) resolved through an anchor "
            "(identity churn, not a failure)"
        )


def annotate(result: Result) -> None:
    """GitHub Actions annotations, so skips are visible in the run summary."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for warning in result.warnings:
        print(f"::warning::{warning}")
    for item in result.missing:
        print(f"::warning::golden fixture no longer resolvable: {item}")
    for failure in result.failures:
        print(f"::error::{failure}")


# --------------------------------------------------------------------------
# Anchor maintenance
# --------------------------------------------------------------------------


def _anchor_payload(case: dict, product: dict) -> dict:
    """Anchors are append-only evidence: never drop a stale key or id."""
    specs = product.get("specs") or {}
    current = str(product.get("product_id") or "")
    old = case.get("anchors") or {}

    ids = [current]
    seen_ids = {current}
    for value in old.get("ids") or []:
        text = str(value)
        if text not in seen_ids:
            seen_ids.add(text)
            ids.append(text)

    listing_keys = {
        str(value) for value in old.get("listing_keys") or [] if value
    }
    listing_keys.update(
        str(offer.get("listing_key"))
        for offer in product.get("offers") or []
        if offer.get("listing_key")
    )

    part_numbers: list[str] = []
    seen_parts: set[str] = set()
    for value in list(old.get("part_numbers") or []) + list(
        specs.get("part_numbers") or []
    ):
        key = part_key(value)
        if key and key not in seen_parts:
            seen_parts.add(key)
            part_numbers.append(str(value))

    payload: dict = {
        "ids": ids,
        "listing_keys": sorted(listing_keys),
        "part_numbers": part_numbers,
    }

    manufacturer = specs.get("manufacturer")
    model = specs.get("model") or product.get("model")
    if manufacturer and model:
        payload["manufacturer"] = str(manufacturer)
        models = [str(model)]
        models.extend(
            str(value)
            for value in old.get("models") or []
            if part_key(value) != part_key(model)
        )
        payload["models"] = models
    return payload


def update_anchors(
    catalog: dict,
    fixtures: dict,
    fixtures_path: Path,
    have_reference: bool,
    apply: bool,
) -> int:
    indexes = build_indexes(catalog)
    changed = 0
    untouched = 0

    for case in fixtures.get("cases") or []:
        label = _case_label(case)
        candidates, _mode = resolve_case(case, indexes)
        if len(candidates) != 1:
            print(
                f"[golden] {label}: left untouched "
                f"({len(candidates)} candidate(s) in this catalog)"
            )
            untouched += 1
            continue

        product = candidates[0]
        problems = evaluate(case, product, have_reference)
        if problems:
            print(
                f"[golden] {label}: left untouched — the case fails its own "
                f"expectations ({problems[0]})"
            )
            untouched += 1
            continue

        before = json.dumps(
            {"product_id": case.get("product_id"), "anchors": case.get("anchors")},
            sort_keys=True,
        )
        case["product_id"] = str(product.get("product_id") or "")
        case["anchors"] = _anchor_payload(case, product)
        after = json.dumps(
            {"product_id": case.get("product_id"), "anchors": case.get("anchors")},
            sort_keys=True,
        )
        if before == after:
            print(f"[golden] {label}: unchanged")
            continue

        changed += 1
        anchors = case["anchors"]
        print(
            f"[golden] {label}: -> {case['product_id']} "
            f"({len(anchors['ids'])} id(s), "
            f"{len(anchors['listing_keys'])} listing key(s), "
            f"{len(anchors['part_numbers'])} part number(s))"
        )
        vendor_count = product.get("vendor_count")
        if isinstance(vendor_count, int) and vendor_count < 2:
            print(
                f"[golden]   note: {case['product_id']} has {vendor_count} "
                "vendor(s) — single-vendor pins are the fragile kind"
            )

    if not changed:
        print(f"[golden] anchors already current ({untouched} case(s) left untouched)")
        return EXIT_OK
    if not apply:
        print(
            f"[golden] {changed} case(s) would change — re-run with --apply to "
            f"write {fixtures_path}"
        )
        return EXIT_OK

    fixtures_path.write_text(
        json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[golden] wrote {fixtures_path}")
    return EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1, never 2 — 2 means "identity churn" to the workflow."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_FAIL)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        description="Assert the pipeline's spec output against hand-verified fixtures."
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES_PATH)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="previously committed catalog; enables the population guard",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="any missing case is a failure (local audits)",
    )
    parser.add_argument(
        "--update-anchors",
        action="store_true",
        help="refresh fixture anchors from --catalog (dry run unless --apply)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="with --update-anchors: write the fixtures file",
    )
    args = parser.parse_args(argv)

    if args.apply and not args.update_anchors:
        parser.error("--apply only makes sense with --update-anchors")

    if not args.catalog.exists():
        print(f"[golden] catalog not found: {args.catalog} (run normalize first)")
        return EXIT_FAIL
    fixtures = load_json(args.fixtures)
    if int(fixtures.get("schema_version", 0)) != schema.SCHEMA_VERSION:
        print(
            f"[golden] FAIL: fixtures target schema v{fixtures.get('schema_version')} "
            f"but the schema is v{schema.SCHEMA_VERSION} — regenerate fixtures"
        )
        return EXIT_FAIL

    catalog = load_json(args.catalog)
    have_reference = INDEX_PATH.exists()

    if args.update_anchors:
        return update_anchors(
            catalog, fixtures, args.fixtures, have_reference, args.apply
        )

    if not have_reference:
        print(
            "[golden] no pcpartdb index — Tier-0 assertions are skipped "
            "(run: python -m scraper.pcpartdb refresh)"
        )

    baseline = None
    if args.baseline is not None:
        if args.baseline.exists():
            baseline = load_json(args.baseline)
        else:
            print(f"[golden] baseline not found: {args.baseline} — guard skipped")

    result = check(
        catalog,
        fixtures,
        have_reference,
        strict=args.strict,
        baseline=baseline,
    )
    report(result, have_reference)
    annotate(result)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
