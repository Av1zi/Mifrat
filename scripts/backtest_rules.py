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

Every (rule, field) pair gets overlaps / agree / disagree, and --check decides
whether a pair is a REGRESSION using a statistical test, not a point threshold
(see `is_regression`): d disagreements out of n overlaps only count against a
rule when they are too many to be chance at that rule's acceptable precision
(MIN_PRECISION for a brand-new pair, or the pair's own recorded rate minus
SLACK for one pinned in scripts/backtest_baseline.json).

Why a test instead of "precision >= 99%": the catalog is rebuilt from fresh
scrapes every day, so the *population* each rule is measured against shifts
continuously. A fixed point threshold trips on pure sampling noise — a 4-overlap
pair where one odd product flips it 25 points, or a 400-overlap pair drifting
99.3% -> 98.7% because two new listings arrived. Both kept failing the daily
build while nothing was actually wrong. A binomial test scales the bar to the
sample: a handful of overlaps needs overwhelming evidence to fail, a large pair
needs the drop to be statistically real. The baseline is still a ratchet (a
pinned pair is judged only against its own history), but a rule can no longer
stop the build for being within noise of where it has always been.

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
from math import exp, lgamma, log
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

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

# Significance level for the regression test. A pair fails --check only when the
# chance of seeing this many disagreements at its acceptable precision is below
# ALPHA. Kept strict (1 in 10,000) because ~150 pairs are evaluated every day
# against a shifting catalog — at this level a purely-noise trip is rare, while
# a rule that genuinely dropped precision (say 85% on 50 overlaps) is many
# orders of magnitude past it and still fails loudly.
ALPHA = 1e-4

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
        category = str(product.get("category") or "")
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
        category = str(product.get("category") or "")
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


def _log_binom_pmf(k: int, n: int, q: float) -> float:
    """log P(X == k) for X ~ Binomial(n, q), via log-gamma for large-n exactness."""
    return (lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
            + k * log(q) + (n - k) * log(1 - q))


def binom_pge(d: int, n: int, q: float) -> float:
    """P(X >= d) for X ~ Binomial(n, q): the chance of seeing at least d
    disagreements when the true disagreement rate is q.

    Computed in log-space (log-sum-exp) so it stays exact for the large overlap
    counts the real catalog produces (hundreds of listings), where a naive
    C(n,k) overflows float.
    """
    if d <= 0:
        return 1.0
    if d > n:
        return 0.0
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    logs = [_log_binom_pmf(k, n, q) for k in range(d, n + 1)]
    top = max(logs)
    return min(exp(top) * sum(exp(x - top) for x in logs), 1.0)


def below_bar(slot: dict, key: str = "") -> bool:
    """True when a pair has not reached the ideal bar (no disagreement, or a
    clean MIN_OVERLAP-sample at >= MIN_PRECISION).

    Used for the display marker and --write-baseline: any pair still below the
    ideal gets pinned so future runs are judged against its own rate rather
    than against 99%. This was the old `verdict` — unchanged semantics.
    """
    field = key.rsplit(" -> ", 1)[-1]
    if tuple(field.split(".", 1)) in PARTNER_VARIES:
        return False
    if not slot["disagree"]:
        return False
    precision = slot["agree"] * 100 / slot["overlap"]
    return not (slot["overlap"] >= MIN_OVERLAP and precision >= MIN_PRECISION)


def is_regression(slot: dict, key: str, pinned: float | None) -> bool:
    """True when a pair's disagreements are too many to be chance -- the gate.

    A pair is a regression only if observing this many disagreements is
    unlikely (p < ALPHA) if the rule were still at its acceptable precision.
    That bar is statistical, not a point threshold, so it scales with the
    sample: a 4-overlap pair needs overwhelming evidence to fail, a 400-overlap
    pair needs the drop to be statistically real. This is what stops daily
    catalog churn (a few new listings) from failing the build while a rule that
    genuinely went bad still fails loudly.

    Acceptable precision: a new (unpinned) pair must be at MIN_PRECISION; a
    pinned pair need only stay within SLACK points of its own recorded rate.
    """
    disagree, overlap = slot["disagree"], slot["overlap"]
    if not disagree:
        return False
    field = key.rsplit(" -> ", 1)[-1]
    if tuple(field.split(".", 1)) in PARTNER_VARIES:
        return False
    target = MIN_PRECISION if pinned is None else max(pinned - SLACK, 0.0)
    q = max(1.0 - target / 100.0, 0.0)  # tolerated disagreement rate
    if pinned is None and overlap < MIN_GATE_OVERLAP:
        # Preserve "one odd new listing cannot stop the daily build" for the
        # very smallest samples; the binomial test already protects everything
        # above this floor.
        return False
    return binom_pge(disagree, overlap, q) < ALPHA


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
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
        pinned = baseline.get(key)
        # below_bar drives the "pinned"/"FAIL" marker + --write-baseline;
        # is_regression is the --check gate (statistical, see its docstring).
        below = below_bar(slot, key)
        regressed = is_regression(slot, key, pinned)
        mark = "" if not below else ("  pinned" if pinned is not None else "  FAIL")
        print(f"{key:<62}{slot['overlap']:>8}{slot['agree']:>7}{slot['disagree']:>7}"
              f"{precision:>7.1f}{mark}")
        if below:
            failing.append(key)
        if regressed:
            regressions.append(key)
            for example in slot["examples"][:args.examples]:
                print(f"      {json.dumps(example, ensure_ascii=False)[:220]}")

    total = sum(s["overlap"] for s in pairs.values())
    bad = sum(s["disagree"] for s in pairs.values())
    print(f"[backtest] {len(pairs)} rule/field pairs, {total} overlaps, {bad} disagree; "
          f"{len(failing)} below the ideal bar, {len(regressions)} regression(s) "
          f"past p<{ALPHA:g}")

    if args.json:
        args.json.write_text(json.dumps(pairs, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write_baseline:
        pins = {k: round(slot["agree"] * 100 / slot["overlap"], 1)
                for k, slot in sorted(tally.pairs.items()) if below_bar(slot, k)}
        BASELINE.write_text(json.dumps(pins, indent=1) + "\n", encoding="utf-8")
        print(f"[backtest] pinned {len(pins)} below-bar pairs in {BASELINE}")
    if args.check and regressions:
        for key in regressions:
            slot = pairs[key]
            pinned = baseline.get(key)
            target = MIN_PRECISION if pinned is None else max(pinned - SLACK, 0.0)
            p = binom_pge(slot["disagree"], slot["overlap"],
                          max(1.0 - target / 100.0, 0.0))
            print(f"[backtest] FAIL {key}: {slot['agree'] * 100 / slot['overlap']:.1f}% "
                  f"precision on {slot['overlap']} overlaps "
                  f"({slot['disagree']} disagree, p={p:.2g} < {ALPHA:g}, "
                  f"acceptable {target:.1f}%, pinned {pinned})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
