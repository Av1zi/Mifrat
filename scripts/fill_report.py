#!/usr/bin/env python
"""
fill_report.py - spec completeness meter (plan Phase 0 / Phase 1).

Per category and per field: how many products carry a value, and for every
gap, *why* it is a gap. Each null cell is put in exactly one bucket:

  not-applicable  the field cannot exist for this product (a SATA SSD has no
                  RPM, a fanless PSU has no fan size). Gated by the schema's
                  own `applies_to` (schema.applies) so the pipeline and this
                  report cannot disagree.
  derivable       the product already carries the anchor a lookup table keys on
                  (GPU chipset, CPU model, board chipset ...), so a curated table
                  or rule COULD answer. A remaining derivable gap means the table
                  has no row for that anchor yet.
  unobtainable    no source we can legally/reliably reach publishes this (field
                  fill is below OBTAINABLE_FLOOR across the whole category and no
                  derivation rule exists). Candidates for schema pruning.
  fillable        everything else: a vendor page, title, manufacturer page or
                  reference row plausibly carries it, the parser/mapping just
                  does not read it yet.

The headline number is *core applicable fill*: filled / (n - not-applicable)
over each category's CORE_FIELDS - the fields a buyer or the compatibility
engine actually needs (an entry may be a tuple = "any of these", e.g. the PSU's
PCIe connector counts, which vendors spell three ways). The Phase-1 goal is
>= 95% there; `--gaps` explains every shortfall by brand and by what is (not)
reachable for that brand.

Usage (repo root, after a normalize run):
    python scripts/fill_report.py                 # category summary + baseline delta
    python scripts/fill_report.py --fields        # per-field table (all categories)
    python scripts/fill_report.py --gaps          # core gaps by brand + source verdict
    python scripts/fill_report.py --category gpu --fields
    python scripts/fill_report.py --check-tables  # curated tables vs sourced values
    python scripts/fill_report.py --json out.json # machine-readable dump
    python scripts/fill_report.py --check         # exit 1 if a category's core fill < target
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs import schema  # noqa: E402

CATALOG = ROOT / "data" / "catalog.json"

# Fill rate (%) below which a field with no derivation rule is treated as
# having no obtainable source.
OBTAINABLE_FLOOR = 15.0
CORE_TARGET = 95.0

# Baseline measured 2026-10-17 on the committed catalog, before Phase 1
# (cell-weighted: filled cells / schema cells; per category: the same).
BASELINE_OVERALL = 48.8
BASELINE = {
    "cpu": 80, "gpu": 55, "motherboard": 45, "case": 43, "aio": 45,
    "cooler_air": 37, "cooling_other": 26,
}

# The fields a buyer / the compat engine needs. Everything else is "extra".
# A tuple entry is an any-of group: the product counts as covered when ANY
# member holds a value.
_PCIE_POWER = ("pcie8_connectors", "pcie62_connectors", "pcie6_connectors",
               "pcie12_connectors", "pcie16_connectors")
CORE_FIELDS: dict[str, tuple] = {
    "cpu": ("manufacturer", "model", "socket", "core_count", "thread_count",
            "base_clock_ghz", "boost_clock_ghz", "l3_cache_mb", "tdp_w",
            "integrated_graphics", "microarchitecture", "max_memory_gb",
            "ecc_support"),
    "gpu": ("manufacturer", "chipset", "memory_gb", "memory_type",
            "memory_bus_bit", "interface", "length_mm", "tdp_w",
            "recommended_psu_w", "external_power", "cooling", "directx"),
    "motherboard": ("manufacturer", "socket", "chipset", "form_factor",
                    "memory_type", "memory_slots", "memory_max_gb",
                    "pcie_x16_slots", "m2_slots", "sata_ports", "ethernet",
                    "wireless"),
    "memory": ("manufacturer", "memory_type", "speed_mhz", "form_factor",
               "module_count", "module_size_gb", "total_gb", "cas_latency",
               "voltage_v"),
    "storage": ("manufacturer", "capacity_gb", "type", "form_factor",
                "interface", "read_speed_mbs", "write_speed_mbs"),
    "psu": ("manufacturer", "type", "wattage_w", "efficiency", "modular",
            "atx_version", "sata_connectors", "eps8_connectors", _PCIE_POWER),
    "case": ("manufacturer", "type", "mb_form_factors", "max_gpu_length_mm",
             "max_cooler_height_mm", "side_panel", "psu_included",
             "drive_bays_25", "drive_bays_35", "front_usb"),
    "case_fan": ("manufacturer", "size_mm", "quantity", "rpm_max",
                 "airflow_cfm", "noise_db", "pwm", "connector"),
    "aio": ("manufacturer", "radiator_size_mm", "fan_size_mm", "sockets",
            "lighting"),
    "cooler_air": ("manufacturer", "fan_size_mm", "sockets", "height_mm"),
    "cooling_other": ("manufacturer", "sockets"),
}

# What is (not) reachable per brand, for the --gaps explanation. Verdicts come
# from scraper/mfr/README.md (feasibility check, 2026-10-17).
MFR_FETCHERS = {"corsair": "built", "asus": "built (boards)",
                "cooler master": "built (coolers/AIO/cases; joined on product number)",
                "lian li": "built (cases, fans, PSU; one entry per model block)",
                "be quiet!": "built (all categories; joined on article number / EAN)",
                "antec": "built (cases, PSU, fans, AIO; joined on UPC / part number)",
                "amd": "built (CPUs; pages missing for older SKUs)",
                "nzxt": "built (cases, fans, AIO)",
                "thermalright": "built (narrow: ~15 products have a page)"}
MFR_VERDICT = {
    "gigabyte": "blocked: HTTP 403 on robots.txt (stop signal)",
    "msi": "blocked: HTTP 403 on robots.txt (stop signal)",
    "intel": "blocked: HTTP 403 on robots.txt of intel.com and ark.intel.com",
    "cougar": "blocked: connection closed without an HTTP answer (stop signal)",
    "fractal design": "skipped: robots.txt disallows AI crawlers by name",
    "noctua": "specs rendered client-side, /api/ disallowed",
    "gamdias": "skipped: pages exist for 5 of 43 products",
    "deepcool": "skipped: no sitemap / robots",
    "arctic": "skipped: no machine sitemap, pagination disallowed",
    "maxsun": "skipped: product pages are marketing prose, no spec table",
}


def _is(specs: dict, field: str, *values) -> bool:
    return specs.get(field) in values


# Rules for gaps that are not-applicable beyond the schema's own `applies_to`
# gates (schema.applies): (category, field) -> predicate(specs) -> True when
# the field cannot apply. Empty today - the gates live in schema.py.
NOT_APPLICABLE: dict = {}

# Fields a lookup table / rule can answer once the anchor field is known.
# (category, field) -> anchor fields that must ALL be non-null.
DERIVABLE = {
    ("gpu", f): ("chipset",) for f in (
        "directx", "opengl", "memory_type", "memory_bus_bit", "tdp_w",
        "recommended_psu_w", "interface", "chip_manufacturer",
        "memory_speed_gbps")
}
DERIVABLE.update({
    ("cpu", f): ("model",) for f in (
        "l2_cache_mb", "l3_cache_mb", "ecc_support", "integrated_graphics",
        "max_memory_gb", "lithography_nm", "smt", "microarchitecture",
        "core_family", "thread_count")
})
DERIVABLE.update({
    ("motherboard", f): ("chipset",) for f in ("memory_type", "ecc_support", "socket")
})
DERIVABLE.update({
    ("memory", "voltage_v"): ("memory_type",),
    ("memory", "total_gb"): ("module_size_gb",),
    ("memory", "module_count"): ("total_gb",),
    ("storage", "type"): ("interface",),
    ("storage", "nvme"): ("interface",),
    ("storage", "pcie_gen"): ("interface",),
})


def load_products(path: Path = CATALOG) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["products"]


def applicable(category: str, field: str, specs: dict) -> bool:
    if not schema.applies(category, field, specs):
        return False
    rule = NOT_APPLICABLE.get((category, field))
    return not (rule and rule(specs))


def analyse(products: list[dict]) -> dict:
    cats: dict[str, dict] = {}
    for product in products:
        category = product.get("category") or ""
        specs = product.get("specs") or {}
        sources = product.get("spec_sources") or {}
        bucket = cats.setdefault(category, {"n": 0, "fields": {}, "core": {
            "cells": 0, "filled": 0, "na": 0}})
        bucket["n"] += 1
        for fspec in schema.fields_for(category):
            name = fspec.name
            slot = bucket["fields"].setdefault(name, {
                "filled": 0, "na": 0, "derivable": 0, "gap": 0,
                "sources": {}})
            if specs.get(name) is not None:
                slot["filled"] += 1
                src = str(sources.get(name) or "?")
                src = "derived" if src.startswith("derived") else src
                slot["sources"][src] = slot["sources"].get(src, 0) + 1
            elif not applicable(category, name, specs):
                slot["na"] += 1
            else:
                anchors = DERIVABLE.get((category, name))
                if anchors and all(specs.get(a) is not None for a in anchors):
                    slot["derivable"] += 1
                else:
                    slot["gap"] += 1
        # Core coverage, per product, so any-of groups count once.
        for entry in CORE_FIELDS.get(category, ()):
            members = (entry,) if isinstance(entry, str) else entry
            bucket["core"]["cells"] += 1
            if any(specs.get(m) is not None for m in members):
                bucket["core"]["filled"] += 1
            elif all(not applicable(category, m, specs) for m in members):
                bucket["core"]["na"] += 1
    # Split the residual into fillable / unobtainable at field level.
    for category, bucket in cats.items():
        for name, slot in bucket["fields"].items():
            n = bucket["n"]
            fill = slot["filled"] * 100 / n if n else 0
            slot["fill_pct"] = round(fill, 1)
            applic = n - slot["na"]
            slot["applicable_fill_pct"] = round(
                slot["filled"] * 100 / applic, 1) if applic else None
            has_rule = (category, name) in DERIVABLE
            if slot["gap"] and fill < OBTAINABLE_FLOOR and not has_rule:
                slot["unobtainable"], slot["fillable"] = slot["gap"], 0
            else:
                slot["unobtainable"], slot["fillable"] = 0, slot["gap"]
        core = bucket["core"]
        applic = core["cells"] - core["na"]
        core["applicable_fill_pct"] = round(core["filled"] * 100 / applic, 1) if applic else 0.0
    return cats


def totals(bucket: dict) -> dict:
    cells = filled = na = der = fil = unob = 0
    for slot in bucket["fields"].values():
        cells += bucket["n"]
        filled += slot["filled"]
        na += slot["na"]
        der += slot["derivable"]
        fil += slot["fillable"]
        unob += slot["unobtainable"]
    return {"cells": cells, "filled": filled, "na": na, "derivable": der,
            "fillable": fil, "unobtainable": unob,
            "fill_pct": round(filled * 100 / cells, 1) if cells else 0.0,
            "applicable_fill_pct": round(
                filled * 100 / (cells - na), 1) if cells - na else 0.0}


def core_gaps_by_brand(products: list[dict], category: str) -> Counter:
    """brand -> number of (product, core field) gaps."""
    gaps: Counter = Counter()
    for product in products:
        if product.get("category") != category:
            continue
        specs = product.get("specs") or {}
        brand = str(specs.get("manufacturer") or product.get("brand") or "?")
        for entry in CORE_FIELDS.get(category, ()):
            members = (entry,) if isinstance(entry, str) else entry
            if all(specs.get(m) is None and applicable(category, m, specs) for m in members):
                gaps[brand] += 1
    return gaps


def print_gaps(products: list[dict], categories) -> None:
    for category in sorted(categories):
        gaps = core_gaps_by_brand(products, category)
        total = sum(gaps.values())
        if not total:
            continue
        print(f"\n== {category}: {total} core gaps ==")
        for brand, count in gaps.most_common(8):
            key = brand.lower()
            note = MFR_FETCHERS.get(key)
            verdict = (f"manufacturer fetcher {note}" if note
                       else MFR_VERDICT.get(key, "no manufacturer source built"))
            print(f"  {brand:<18}{count:>5}  {verdict}")


# Fields where a board partner legitimately publishes a different (usually
# higher, factory-overclocked) figure than the chip designer's reference.
PARTNER_VARIES = frozenset({"tdp_w", "recommended_psu_w", "memory_speed_gbps"})


def _pcie_gen(value) -> str | None:
    match = re.search(r"(\d)\.0", str(value))
    return match.group(1) if match else None


def check_tables(products: list[dict]) -> int:
    """Compare every curated table row to the SOURCED values in the catalog.

    A table row is a claim about every SKU sharing its anchor; any product whose
    vendor/reference-published value (not a derived one) disagrees is evidence
    the row is wrong or too coarse. Prints disagreements, exits 1 if any.
    """
    from scraper.specs import derive
    from scraper.specs.tables import load

    bad = checked = info = 0
    gpu_rows = {k.lower(): v for k, v in load("gpu_chipsets").items()}
    cpu_rows = load("cpu_models")
    for product in products:
        specs = product.get("specs") or {}
        sources = product.get("spec_sources") or {}
        category = product.get("category")
        if category == "gpu":
            key = str(specs.get("chipset") or "").lower()
            row, label = gpu_rows.get(key), key
        elif category == "cpu":
            label = derive.cpu_table_key(specs)
            row = cpu_rows.get(label) if label else None
        else:
            continue
        requires = (row or {}).get("_requires") or {}
        if any(specs.get(f) not in allowed for f, allowed in requires.items()):
            continue
        for field, expected in (row or {}).items():
            if field.startswith("_"):
                continue
            actual = specs.get(field)
            if actual is None or str(sources.get(field, "")).startswith("derived"):
                continue
            checked += 1
            if field == "integrated_graphics":
                # Vendors print the specific iGPU ("Radeon 780M"); the table
                # carries a family string, so only "has one / has none" is a claim.
                same = (str(expected).lower() == "no") == (str(actual).lower() == "no")
            elif field == "interface":
                same = _pcie_gen(expected) == _pcie_gen(actual) or _pcie_gen(actual) is None
            elif (isinstance(expected, (int, float)) and isinstance(actual, (int, float))
                  and not isinstance(expected, bool)):
                same = abs(float(actual) - float(expected)) < 1e-6
            else:
                same = str(actual).lower() == str(expected).lower()
            if same:
                continue
            if field in PARTNER_VARIES:
                info += 1
                continue
            bad += 1
            print(f"  MISMATCH {category} {label} {field}: table={expected!r} "
                  f"sourced={actual!r} ({product.get('canonical_name', '')[:50]})")
    print(f"[fill-report] tables: {checked} sourced cells compared, {bad} disagree "
          f"(+{info} partner-card figures above the chip designer's reference, informational)")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--category")
    ap.add_argument("--catalog", type=Path, default=CATALOG,
                    help="catalog json to read (default data/catalog.json)")
    ap.add_argument("--fields", action="store_true", help="per-field table")
    ap.add_argument("--gaps", action="store_true",
                    help="core gaps by brand + what is reachable for that brand")
    ap.add_argument("--check-tables", action="store_true",
                    help="compare curated tables to sourced catalog values")
    ap.add_argument("--json", metavar="PATH", help="write the full analysis as JSON")
    ap.add_argument("--check", action="store_true",
                    help=f"exit 1 when a category's core applicable fill < {CORE_TARGET:.0f}%%")
    args = ap.parse_args()

    if not args.catalog.exists():
        print(f"[fill-report] {args.catalog} missing - run the normalizer first")
        return 1
    products = load_products(args.catalog)
    if args.check_tables:
        return check_tables(products)
    cats = analyse(products)
    selected = {c: b for c, b in cats.items() if not args.category or c == args.category}

    all_cells = all_filled = 0
    for bucket in cats.values():
        t = totals(bucket)
        all_cells += t["cells"]
        all_filled += t["filled"]
    overall = all_filled * 100 / all_cells if all_cells else 0.0

    print(f"[fill-report] overall cell fill {overall:.1f}% "
          f"(baseline {BASELINE_OVERALL}%)  "
          f"{all_filled:,}/{all_cells:,} cells")
    print(f"{'category':<14}{'n':>5} {'fill%':>6} {'base':>5} {'applic%':>8} "
          f"{'core%':>7} {'n/a':>6} {'deriv':>6} {'fillbl':>7} {'unobt':>6}")
    failing = []
    for category in sorted(selected):
        bucket = selected[category]
        t = totals(bucket)
        core = bucket["core"]
        base = BASELINE.get(category)
        print(f"{category:<14}{bucket['n']:>5} {t['fill_pct']:>6.1f} "
              f"{(str(base) if base is not None else '-'):>5} "
              f"{t['applicable_fill_pct']:>8.1f} {core['applicable_fill_pct']:>7.1f} "
              f"{t['na']:>6} {t['derivable']:>6} {t['fillable']:>7} {t['unobtainable']:>6}")
        if (category in CORE_FIELDS and bucket["n"] >= 20
                and core["applicable_fill_pct"] < CORE_TARGET):
            failing.append((category, core["applicable_fill_pct"]))

    if args.fields:
        for category in sorted(selected):
            bucket = selected[category]
            core = {m for entry in CORE_FIELDS.get(category, ())
                    for m in ((entry,) if isinstance(entry, str) else entry)}
            print(f"\n== {category} (n={bucket['n']}) ==")
            print(f"{'field':<26}{'core':>5}{'fill%':>7}{'applic%':>8}"
                  f"{'n/a':>6}{'deriv':>6}{'fillbl':>7}{'unobt':>6}  sources")
            rows = sorted(bucket["fields"].items(), key=lambda kv: kv[1]["fill_pct"])
            for name, slot in rows:
                srcs = ",".join(f"{k}:{v}" for k, v in sorted(
                    slot["sources"].items(), key=lambda kv: -kv[1]))
                app = slot["applicable_fill_pct"]
                print(f"{name:<26}{'*' if name in core else '':>5}"
                      f"{slot['fill_pct']:>7.1f}"
                      f"{(f'{app:.1f}' if app is not None else '-'):>8}"
                      f"{slot['na']:>6}{slot['derivable']:>6}{slot['fillable']:>7}"
                      f"{slot['unobtainable']:>6}  {srcs}")

    if args.gaps:
        print_gaps(products, selected)

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"overall_fill_pct": round(overall, 2), "categories": cats},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[fill-report] wrote {args.json}")

    if failing:
        shown = ", ".join(f"{c} {v:.1f}%" for c, v in failing)
        print(f"[fill-report] core applicable fill below {CORE_TARGET:.0f}%: {shown}")
        if args.check:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
