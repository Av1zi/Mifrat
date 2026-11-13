"""Offline regression for the KSP detail parser (spiders/ksp_detail.py).

The two payload shapes are real `result.specification.items` rows from the
Nano probes of 2026-11-13 (docs/ksp-detail-plan.md): an Intel CPU, whose
`דגם` row is only the model name, and a Kingston kit, whose `דגם` row IS the
maker part number. They pin the one rule that matters: a model name never
becomes a part number (it is adopted only when another vendor prints it).

Run: python scripts/check_ksp_detail.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.spiders.ksp_detail import (  # noqa: E402
    ksp_model_part_number,
    parse_specification,
    spec_text,
)

KINGSTON_193193 = {"result": {"specification": {"items": [
    {"head": "אחריות ", "body": "<div class=\"alignright\">אחריות לכל חיי המוצר, מימוש אחריות בסניפי KSP<div></div></div>"},
    {"head": "דגם", "body": "<div class=\"alignleft\">KF556C40BBK2-32</div>"},
    {"head": "יצרן", "body": "<div class=\"alignleft\">Kingston</div>"},
    {"head": "סוג", "body": "<div class=\"alignleft\">288-Pin DIMM</div>"},
    {"head": "קיבולת", "body": "<div class=\"alignleft\">32GB (2x 16GB)</div>"},
    {"head": "מהירות", "body": "<div class=\"alignleft\">DDR5 5600MHz</div>"},
    {"head": "Cas Latency", "body": "<div class=\"alignleft\">CL40</div>"},
]}}}

INTEL_280943 = {"result": {"specification": {"items": [
    {"head": "דגם", "body": "<div class=\"alignleft\">i5-14600K</div>"},
    {"head": "כללי", "body": "<div class=\"alignleft\"><b>Product Collection</b><br>Intel® Core™ i5 Processors (14th gen)<br><b>Processor Number</b><br>i5-14600K</div>"},
]}}}

PART_NUMBER_CASES = [
    # Part-number shaped: a candidate (adopted only if another vendor
    # prints it, see the normalizer case below).
    ("KF556C40BBK2-32", "KF556C40BBK2-32"),
    ("90MB1JG0-M0EAY0", "90MB1JG0-M0EAY0"),
    ("CT2K16G56C46U5", "CT2K16G56C46U5"),
    ("SA400S37/480G", "SA400S37/480G"),
    ("i5-14600K", "i5-14600K"),
    # Short codes, spaced names and bare numbers are never candidates.
    ("RM850e", None),
    ("FURY Beast", None),
    ("ROG STRIX B860-F GAMING WIFI", None),
    ("Ryzen 5 9600X", None),
    ("2024", None),
    ("", None),
]


def main() -> int:
    failures: list[str] = []

    def eq(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    kingston = parse_specification(KINGSTON_193193)
    eq("kingston model row", kingston.get("דגם"), "KF556C40BBK2-32")
    eq("kingston brand row", kingston.get("יצרן"), "Kingston")
    eq("kingston capacity row", kingston.get("קיבולת"), "32GB (2x 16GB)")
    eq("kingston head trimmed", "אחריות" in kingston, True)
    eq("kingston part number", ksp_model_part_number(kingston), "KF556C40BBK2-32")

    intel = parse_specification(INTEL_280943)
    eq("intel multi-line cell",
       intel.get("כללי"),
       "Product Collection | Intel® Core™ i5 Processors (14th gen) | Processor Number | i5-14600K")

    for value, want in PART_NUMBER_CASES:
        eq(f"part number {value!r}", ksp_model_part_number({"דגם": value}), want)

    eq("empty payload", parse_specification({}), {})
    eq("html entities", spec_text("<div>A&amp;B</div>"), "A&B")

    # The normalizer adopts a model row only when another vendor prints it.
    from scraper.normalize_and_match import _adopt_ksp_model_rows
    def listing(vendor, sku, category, mpn=None):
        return {"vendor_id": vendor, "vendor_sku": sku, "category_normalized": category, "mpn": mpn}
    ksp_ram = listing("ksp", "193193", "memory")
    ksp_cpu = listing("ksp", "280943", "cpu")
    ksp_lone = listing("ksp", "1", "memory")
    others = [listing("tms", "KF556C40BBK2-32", "memory", "KF556C40BBK2-32"),
              listing("tms", "X", "cpu", "BX8071514600K")]
    extra = {("ksp", "193193"): {"model_row": "KF556C40BBK2-32"},
             ("ksp", "280943"): {"model_row": "i5-14600K"},
             ("ksp", "1"): {"model_row": "KF999C99XXX-99"}}
    adopted = _adopt_ksp_model_rows([ksp_ram, ksp_cpu, ksp_lone, *others], extra)
    eq("adopted count", adopted, 1)
    eq("kingston adopted", ksp_ram.get("mpn"), "KF556C40BBK2-32")
    eq("cpu model name not adopted", ksp_cpu.get("mpn"), None)
    eq("uncorroborated code not adopted", ksp_lone.get("mpn"), None)

    if failures:
        for line in failures:
            print("  [fail]", line)
        print(f"[ksp-detail] FAIL - {len(failures)} case(s)")
        return 1
    print(f"[ksp-detail] pass - {12 + len(PART_NUMBER_CASES)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
