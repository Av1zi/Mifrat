"""Offline regression for the spec MERGE layer (Sep 2026).

The typed spec system already has two gates: scripts/check_spec_sync.py
(schema <-> generated TypeScript drift) and the golden fixtures
(hand-verified values for 13 real products, run after a normalize). Neither
pins the merge RULES themselves, which is how this regression reached data:
Ivory's product pages keep the manufacturer part number in their "דגם"
(model) row, that vendor-tier fact outranked the title-derived lineup name,
a product shipped `model: 100-1000001084WOF`, and its identity key flipped
from `model:cpu:ryzen79800x3d-tray` to `sku:cpu:100000001084-tray` — only the
golden fixture noticed, and only because it pins that id.

So this script asserts the layer directly, with no catalog, no network and
no fixtures: tier order, the model-is-a-name rule, validation drops, unknown
keys, conflict recording, and the list/value equality helpers the rest of the
pipeline leans on.

Run: python scripts/check_spec_merge.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs.merge import (  # noqa: E402
    TIER_OVERRIDE,
    TIER_REFERENCE,
    TIER_TITLE,
    TIER_VENDOR,
    Fact,
    merge_facts,
    same_value,
)
from scraper.specs.values import looks_like_part_number  # noqa: E402

PART_NUMBERS = [
    "100-1000001084WOF",
    "100-000001084",
    "ACFRE00161A",
    "MZ-V9P2T0BW",
    "GB550XEAGLEWF6E",
]
MODEL_NAMES = [
    "Ryzen 7 9800X3D",
    "9800X3D",
    "B650M-A",
    "B650M-A WIFI",
    "RTX 4070",
    "O11DMIV2W",
    "970 EVO Plus",
    "RM850x",
    "KFGX",
]


class Checks:
    def __init__(self) -> None:
        self.count = 0
        self.failures: list[str] = []

    def ok(self, condition: bool, label: str, detail: str = "") -> None:
        self.count += 1
        if not condition:
            self.failures.append(f"{label}{(' — ' + detail) if detail else ''}")

    def eq(self, actual, expected, label: str) -> None:
        self.ok(actual == expected, label, f"got {actual!r}, want {expected!r}")


def check_part_number_shape(c: Checks) -> None:
    for value in PART_NUMBERS:
        c.ok(looks_like_part_number(value), f"{value!r} is a part number")
    for value in MODEL_NAMES:
        c.ok(not looks_like_part_number(value), f"{value!r} is a model name")
    c.ok(not looks_like_part_number(None), "None is not a part number")
    c.ok(not looks_like_part_number(""), "an empty string is not a part number")


def check_model_prefers_a_name(c: Checks) -> None:
    # The audited case: a higher tier carries the code, a lower tier the name.
    facts = {
        "model": [
            Fact(value="100-1000001084WOF", tier=TIER_VENDOR, source="vendor:detail"),
            Fact(value="Ryzen 7 9800X3D", tier=TIER_TITLE, source="title"),
        ]
    }
    merged = merge_facts("cpu", facts)
    c.eq(merged.specs.get("model"), "Ryzen 7 9800X3D",
         "a title-derived name beats a vendor part number for `model`")
    c.ok(any(conflict.field == "model" for conflict in merged.conflicts),
         "the displaced part number is still recorded as a conflict")

    # 88 products in the real catalog legitimately carry a code as their only
    # model value (an accessory, a bare MPN-only listing): keep it.
    only_code = merge_facts("cpu", {
        "model": [Fact(value="ACFRE00161A", tier=TIER_VENDOR, source="vendor:detail")],
    })
    c.eq(only_code.specs.get("model"), "ACFRE00161A",
         "a lone part-number model is kept, not nulled")

    # Two names: tier order still decides.
    two_names = merge_facts("cpu", {
        "model": [
            Fact(value="Ryzen 7 9800X3D", tier=TIER_TITLE, source="title"),
            Fact(value="Ryzen 7 9800X3D series", tier=TIER_REFERENCE, source="reference"),
        ]
    })
    c.eq(two_names.specs.get("model"), "Ryzen 7 9800X3D series",
         "among names the better tier still wins")


def check_tier_order(c: Checks) -> None:
    merged = merge_facts("cpu", {
        "socket": [
            Fact(value="AM5", tier=TIER_VENDOR, source="vendor:detail"),
            Fact(value="AM4", tier=TIER_TITLE, source="title"),
        ]
    })
    c.eq(merged.specs.get("socket"), "AM5", "vendor tier beats title tier")
    c.ok(any(conflict.field == "socket" for conflict in merged.conflicts),
         "the losing socket is recorded as a conflict")

    overridden = merge_facts("cpu", {
        "socket": [
            Fact(value="AM5", tier=TIER_REFERENCE, source="reference"),
            Fact(value="AM4", tier=TIER_OVERRIDE, source="override"),
        ]
    })
    c.eq(overridden.specs.get("socket"), "AM4", "an override beats every other tier")


def check_validation_and_unknowns(c: Checks) -> None:
    junk = merge_facts("cpu", {
        "model": [Fact(value="\u05dc\u05d7\u05e5/\u05d9 \u05dc\u05e8\u05db\u05d9\u05e9\u05d4",
                       tier=TIER_VENDOR, source="vendor:detail")],
    })
    c.eq(junk.specs.get("model"), None, "Hebrew prose never becomes a model value")
    c.ok(any("Hebrew" in item.reason or "promo" in item.reason
             for item in junk.invalid),
         "the dropped prose is recorded as invalid")

    unknown = merge_facts("cpu", {
        "definitely_not_a_field": [
            Fact(value="x", tier=TIER_VENDOR, source="vendor:detail")],
    })
    c.ok(all(item.field == "definitely_not_a_field" for item in unknown.invalid),
         "an unknown field key is recorded as invalid")
    c.eq(unknown.specs.get("definitely_not_a_field"), None,
         "an unknown field key never enters the sheet")

    out_of_range = merge_facts("psu", {
        "wattage_w": [Fact(value=99999, tier=TIER_TITLE, source="title")],
    })
    c.eq(out_of_range.specs.get("wattage_w"), None,
         "a value outside the field's range is dropped")

    c.ok(schema_keys_are_fixed(), "every category ships its full fixed key set")


def schema_keys_are_fixed() -> bool:
    """A field no tier supplies must still exist as null (null-first schema)."""
    from scraper.specs import schema

    empty = schema.empty_specs("cpu")
    populated = merge_facts("cpu", {}).specs
    required = schema.field_map("cpu").keys()
    return all(key in empty and key in populated for key in required)


def check_equality_helpers(c: Checks) -> None:
    c.ok(same_value("65W", "65 w"), "unit-case noise does not create a conflict")
    c.ok(same_value(["A", "B"], ["B", "A"]),
         "list order does not create a conflict")
    c.ok(not same_value("AM4", "AM5"), "different values are different")
    c.ok(same_value(1000, 1000.0), "int/float spelling compares equal")


def main() -> int:
    checks = Checks()
    for group in (check_part_number_shape, check_model_prefers_a_name,
                  check_tier_order, check_validation_and_unknowns,
                  check_equality_helpers):
        group(checks)

    if checks.failures:
        print(f"[spec-merge] FAIL — {len(checks.failures)} of {checks.count} "
              f"assertions failed")
        for failure in checks.failures:
            print(f"  - {failure}")
        return 1
    print(f"[spec-merge] pass — {checks.count} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
