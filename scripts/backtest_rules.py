#!/usr/bin/env python
"""
backtest_rules.py - shadow-run every inference rule against what sources say.

A rule that fills a null (derive.infer_specs, validate.fill_derived) or a
title regex (resolvers/title_parse) only earns its place when it agrees with
the products where a real source already states that field. This script
measures exactly that, offline, from data/catalog.json:

  derived rules  For every product and every SOURCED field (vendor, maker page,
                 reference, override; not title, not derived), null that one
                 field, rebuild the evidence context from the product's own
                 listings, run fill_derived + infer_specs, and compare what the
                 rule writes with the sourced value. One field at a time,
                 because rules chain (fan size -> fanless).
  title rules    Run the title parser on every listing and compare each value
                 with the product's sourced value for that field.
  tables         The curated-table check from fill_report.py --check-tables
                 (printed, not gated: its mismatches are often vendor typos).

Every (rule, field) pair gets overlaps / agree / disagree. A pair passes when
it has no disagreement, or at least MIN_OVERLAP overlaps at >= MIN_PRECISION.
Pairs that fail today are pinned with their precision in
scripts/backtest_baseline.json. --check fails when an unpinned pair fails (with
at least MIN_GATE_OVERLAP overlaps, so one odd new listing cannot stop the daily
build) or a pinned pair's precision drops more than SLACK points below its pin.
That makes the baseline a ratchet: existing rules may only get better, and a
new rule must be clean before it ships.

Usage (repo root, after a normalize run):
    python scripts/backtest_rules.py                 # summary of every pair
    python scripts/backtest_rules.py --examples 5    # + sample disagreements
    python scripts/backtest_rules.py --rule psu      # pairs whose rule/field matches
    python scripts/backtest_rules.py --check         # CI gate (ratchet)
    python scripts/backtest_rules.py --write-baseline
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scraper.specs import schema  # noqa: E402
from scraper.specs.build import _evidence_context, listing_text  # noqa: E402
from scraper.specs.derive import infer_specs  # noqa: E402
from scraper.specs.merge import same_value  # noqa: E402
from scraper.specs.resolvers import title_parse  # noqa: E402
from scraper.specs.validate import fill_derived  # noqa: E402

CATALOG = ROOT / "data" / "catalog.json"
BASELINE = ROOT / "scripts" / "backtest_baseline.json"

MIN_OVERLAP = 20
MIN_PRECISION = 99.0
MIN_GATE_OVERLAP = 5
SLACK = 2.0

# Sources a rule is judged against. Title and derived values are themselves
# rules; the fuzzy reference tier shares the public name "reference".
_TRUSTED = ("vendor", "manufacturer", "reference", "override", "catalog")


def trusted(source: str | None) -> bool:
    label = str(source or "")
    return label.split(":", 1)[0] in _TRUSTED


# Fields where a board partner legitimately publishes a different figure from
# the chip designer's reference (same set as fill_report.PARTNER_VARIES): a
# disagreement there is informational, not evidence the rule is wrong.
PARTNER_VARIES = {("gpu", "tdp_w"), ("gpu", "recommended_psu_w"),
                  ("gpu", "memory_speed_gbps")}

# Lighting words, least to most specific: a title "RGB" on an addressable kit
# is less precise than the page's "ARGB", not a contradiction of it.
_LIGHT_FAMILY = {"rgb", "argb", "led"}


def _gen(value) -> str | None:
    match = re.search(r"(?:gen\s*|pci[- ]?e(?:xpress)?\s*)(\d)(?:\.0)?", str(value), re.I)
    return match.group(1) if match else None


def _words(value) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value).lower()))


def agrees(category: str, field: str, predicted, actual) -> bool:
    """True unless the two values make claims that cannot both hold.

    Spelling and specificity are not contradictions: "M.2" vs "M.2-2280",
    "PCIe 5.0 x16" vs "PCI Express 5.0", "Ultra 5" vs "Core Ultra 5",
    "Tempered Glass" vs "Windowed". Only a different claim counts.
    """
    if same_value(predicted, actual):
        return True
    if isinstance(predicted, list) and isinstance(actual, list):
        left = {str(v).lower() for v in predicted}
        right = {str(v).lower() for v in actual}
        if left <= right or right <= left:
            return True
    if isinstance(predicted, dict) or isinstance(actual, dict):
        return False
    if isinstance(predicted, (bool, int, float)) or isinstance(actual, (bool, int, float)):
        return False
    if isinstance(predicted, list) or isinstance(actual, list):
        # ["2"] vs ["2 (support SATA and PCIe)"]: the leading count is the claim.
        first = [str((v if isinstance(v, list) else [v])[0]) if (v if isinstance(v, list) else [v])
                 else "" for v in (predicted, actual)]
        # "2 + 1 (SATA and PCIe SSD support)" is three slots.
        counts = [sum(int(n) for n in re.findall(r"(?:^|\+)\s*(\d+)", x)) if
                  re.match(r"\s*\d", x) else None for x in first]
        if None not in counts:
            return counts[0] == counts[1]
        return False
    a, b = str(predicted).lower(), str(actual).lower()
    if field in ("ethernet", "wireless", "bluetooth", "audio"):
        # A generic value ("Ethernet", "Yes", "Realtek HD Audio") names the
        # feature without its grade: it cannot contradict a specific one.
        grade = {"ethernet": r"(\d+(?:\.\d+)?)\s*g", "wireless": r"wi-?fi\s?(\d+e?)",
                 "bluetooth": r"(\d\.\d)", "audio": r"(alc\s?\d{3,4}|s\d{4})"}[field]
        ga, gb = re.search(grade, a), re.search(grade, b)
        if ga and gb:
            return re.sub(r"\s", "", ga.group(1)) == re.sub(r"\s", "", gb.group(1))
        return "no" not in (a, b) or a == b
    if field == "interface" or field == "pcie_gen":
        return _gen(a) == _gen(b) or None in (_gen(a), _gen(b))
    if field == "integrated_graphics":
        return (a == "no") == (b == "no")
    if field in ("lighting", "led"):
        if a in _LIGHT_FAMILY and b in _LIGHT_FAMILY:
            return "no" not in (a, b)
    if field == "side_panel":
        glass = {"tempered glass", "windowed", "glass", "acrylic"}
        return (a in glass) == (b in glass) or a.startswith(b) or b.startswith(a)
    # One spelling contains the other's every word ("M.2" in "M.2-2280",
    # "Threadripper" in "Ryzen Threadripper").
    wa, wb = _words(a), _words(b)
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa)


class Tally:
    def __init__(self) -> None:
        self.pairs: dict[str, dict] = {}

    def add(self, key: str, ok: bool, example: dict) -> None:
        slot = self.pairs.setdefault(key, {"overlap": 0, "agree": 0, "disagree": 0,
                                           "examples": []})
        slot["overlap"] += 1
        if ok:
            slot["agree"] += 1
        else:
            slot["disagree"] += 1
            if len(slot["examples"]) < 25:
                slot["examples"].append(example)


def backtest_derived(products: list[dict], by_product: dict, tally: Tally) -> None:
    for product in products:
        category = product.get("category")
        specs = product.get("specs") or {}
        sources = product.get("spec_sources") or {}
        context = _evidence_context(by_product.get(str(product.get("product_id")), []))
        for field, actual in specs.items():
            if actual is None or not trusted(sources.get(field)):
                continue
            shadow_specs = copy.deepcopy(specs)
            shadow_sources = dict(sources)
            shadow_specs[field] = None
            shadow_sources.pop(field, None)
            fill_derived(category, shadow_specs, shadow_sources)
            infer_specs(category, shadow_specs, shadow_sources, context=context)
            label = str(shadow_sources.get(field) or "")
            predicted = shadow_specs.get(field)
            if predicted is None or not label.startswith("derived"):
                continue
            tally.add(f"{label} -> {category}.{field}",
                      agrees(category, field, predicted, actual),
                      {"product_id": product.get("product_id"),
                       "name": product.get("canonical_name"),
                       "rule": predicted, "sourced": actual,
                       "source": sources.get(field)})


def backtest_title(products: list[dict], by_product: dict, tally: Tally) -> None:
    for product in products:
        category = product.get("category")
        specs = product.get("specs") or {}
        sources = product.get("spec_sources") or {}
        for listing in by_product.get(str(product.get("product_id")), []):
            facts = title_parse.parse_title(category, listing_text(listing))
            for field, fact_list in facts.items():
                actual = specs.get(field)
                if actual is None or not trusted(sources.get(field)):
                    continue
                for fact in fact_list:
                    tally.add(f"title -> {category}.{field}",
                              agrees(category, field, fact.value, actual),
                              {"product_id": product.get("product_id"),
                               "title": listing.get("title_raw"),
                               "rule": fact.value, "sourced": actual,
                               "source": sources.get(field)})


def verdict(slot: dict, key: str = "") -> bool:
    field = key.rsplit(" -> ", 1)[-1]
    if tuple(field.split(".", 1)) in PARTNER_VARIES:
        return True
    if not slot["disagree"]:
        return True
    precision = slot["agree"] * 100 / slot["overlap"]
    return slot["overlap"] >= MIN_OVERLAP and precision >= MIN_PRECISION


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalog", type=Path, default=CATALOG)
    ap.add_argument("--rule", help="only pairs whose key contains this text")
    ap.add_argument("--examples", type=int, default=0,
                    help="print this many disagreements per failing pair")
    ap.add_argument("--no-title", action="store_true", help="skip the title-rule pass")
    ap.add_argument("--json", type=Path, help="write the full tally as JSON")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on a new failing pair or a pinned pair that got worse")
    ap.add_argument("--write-baseline", action="store_true",
                    help=f"pin today's failing pairs in {BASELINE.name}")
    args = ap.parse_args()

    if not args.catalog.exists():
        print(f"[backtest] {args.catalog} missing - run the normalizer first")
        return 1
    data = json.loads(args.catalog.read_text(encoding="utf-8"))
    products = data["products"]
    by_product: dict[str, list[dict]] = {}
    for listing in data.get("listings") or []:
        if listing.get("product_id"):
            by_product.setdefault(str(listing["product_id"]), []).append(listing)

    tally = Tally()
    backtest_derived(products, by_product, tally)
    if not args.no_title:
        backtest_title(products, by_product, tally)

    import fill_report  # noqa: E402  (scripts/)
    # Informational: a table disagreement is as often a vendor typo (a 14900KF
    # "with UHD 770") as a wrong row, so it is read by a person, not gated.
    print("[backtest] curated tables:")
    fill_report.check_tables(products)

    pairs = {k: v for k, v in sorted(tally.pairs.items())
             if not args.rule or args.rule in k}
    baseline = (json.loads(BASELINE.read_text(encoding="utf-8"))
                if BASELINE.exists() else {})
    failing, regressions = [], []
    print(f"{'rule -> field':<62}{'overlap':>8}{'agree':>7}{'disagr':>7}{'prec%':>7}")
    for key, slot in pairs.items():
        precision = slot["agree"] * 100 / slot["overlap"]
        ok = verdict(slot, key)
        pinned = baseline.get(key)
        mark = "" if ok else ("  pinned" if pinned is not None else "  FAIL")
        print(f"{key:<62}{slot['overlap']:>8}{slot['agree']:>7}{slot['disagree']:>7}"
              f"{precision:>7.1f}{mark}")
        if not ok:
            failing.append(key)
            if (pinned is None and slot["overlap"] >= MIN_GATE_OVERLAP) or (
                    pinned is not None and precision < pinned - SLACK):
                regressions.append(key)
            for example in slot["examples"][:args.examples]:
                print(f"      {json.dumps(example, ensure_ascii=False)[:220]}")

    total = sum(s["overlap"] for s in pairs.values())
    bad = sum(s["disagree"] for s in pairs.values())
    print(f"[backtest] {len(pairs)} rule/field pairs, {total} overlaps, {bad} disagree; "
          f"{len(failing)} pairs below {MIN_PRECISION:.0f}% "
          f"({len(regressions)} new or worse than baseline)")

    if args.json:
        args.json.write_text(json.dumps(pairs, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write_baseline:
        pins = {k: round(slot["agree"] * 100 / slot["overlap"], 1)
                for k, slot in sorted(tally.pairs.items()) if not verdict(slot, k)}
        BASELINE.write_text(json.dumps(pins, indent=1) + "\n", encoding="utf-8")
        print(f"[backtest] pinned {len(failing)} failing pairs in {BASELINE}")
    if args.check and regressions:
        for key in regressions:
            slot = pairs[key]
            print(f"[backtest] FAIL {key}: {slot['agree'] * 100 / slot['overlap']:.1f}% "
                  f"precision on {slot['overlap']} overlaps (pinned {baseline.get(key)})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
