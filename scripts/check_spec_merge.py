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
    TIER_MANUFACTURER,
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

    # A numberless lineup name must not outrank a numbered precise name
    # on tier alone (audited case: vendor "AMD Ryzen 9 Processor" beat
    # title "Ryzen 9 9950X3D" and the product shipped a model with no
    # model in it).
    numbered = merge_facts("cpu", {
        "model": [
            Fact(value="AMD Ryzen 9 Processor", tier=TIER_VENDOR, source="vendor:detail"),
            Fact(value="Ryzen 9 9950X3D", tier=TIER_TITLE, source="title"),
        ]
    })
    c.eq(numbered.specs.get("model"), "Ryzen 9 9950X3D",
         "a numbered name beats a numberless lineup name for `model`")
    c.ok(any(conflict.field == "model" for conflict in numbered.conflicts),
         "the displaced lineup name is still recorded as a conflict")


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

    # Tier 0.5: the brand's own page outranks the retailer's payload, but never
    # the reference rows or a manual override.
    primary = merge_facts("case", {
        "max_gpu_length_mm": [
            Fact(value=330, tier=TIER_VENDOR, source="vendor:detail"),
            Fact(value=405, tier=TIER_MANUFACTURER, source="manufacturer:antec"),
        ],
        "max_cooler_height_mm": [
            Fact(value=170, tier=TIER_MANUFACTURER, source="manufacturer:antec"),
            Fact(value=165, tier=TIER_REFERENCE, source="reference"),
        ],
    })
    c.eq(primary.specs.get("max_gpu_length_mm"), 405, "manufacturer tier beats the vendor tier")
    c.eq(primary.sources.get("max_gpu_length_mm"), "manufacturer",
         "a manufacturer-sourced cell is labelled manufacturer")
    c.eq(primary.specs.get("max_cooler_height_mm"), 165, "reference tier still beats manufacturer")

    # Tier 0.75: an Open Icecat sheet sits between the brand's own page and
    # the retailer.
    from scraper.specs.merge import TIER_CATALOG
    catalog = merge_facts("gpu", {
        "fan_count": [Fact(value=2, tier=TIER_VENDOR, source="vendor:detail"),
                      Fact(value=3, tier=TIER_CATALOG, source="catalog:icecat:gigabyte")],
        "memory_gb": [Fact(value=16, tier=TIER_MANUFACTURER, source="manufacturer:asus"),
                      Fact(value=12, tier=TIER_CATALOG, source="catalog:icecat:asus")],
    })
    c.eq(catalog.specs.get("fan_count"), 3, "an Icecat sheet beats the retailer")
    c.eq(catalog.sources.get("fan_count"), "catalog", "an Icecat cell is labelled catalog")
    c.eq(catalog.specs.get("memory_gb"), 16, "the brand's own page beats its Icecat sheet")

    # cross_check ranks every label merge can write. A manufacturer socket must
    # beat a title chipset that implies another socket (it ranked 99 until Oct 2026).
    from scraper.specs.merge import TIER_NAMES
    from scraper.specs.validate import _TIER_ORDER, cross_check
    for name in set(TIER_NAMES.values()):
        c.ok(name in _TIER_ORDER, f"cross_check ranks the {name!r} tier")
    specs = {"socket": "AM5", "chipset": "B550", "memory_type": None}
    sources = {"socket": "manufacturer", "chipset": "title"}
    cross_check("motherboard", specs, sources)
    c.eq((specs["socket"], specs["chipset"]), ("AM5", None),
         "a manufacturer socket beats a contradicting title chipset")
    specs = {"socket": "AM4", "chipset": "B650", "memory_type": None}
    sources = {"socket": "derived:cpu.socket", "chipset": "vendor"}
    cross_check("motherboard", specs, sources)
    c.eq((specs["socket"], specs["chipset"]), (None, "B650"),
         "a vendor chipset beats a derived socket")


def check_applicability_gates(c: Checks) -> None:
    from scraper.specs.schema import applies
    c.ok(not applies("gpu", "fan_count", {"cooling": "Passive"}), "a passive GPU has no fan count")
    c.ok(applies("gpu", "fan_count", {"cooling": "Liquid"}), "a hybrid/liquid GPU keeps its fans")
    c.ok(applies("gpu", "fan_count", {"cooling": None}), "unknown cooling leaves fan_count applicable")
    c.ok(not applies("cooler_air", "noise_db", {"fanless": True}), "a fanless cooler has no noise figure")
    c.ok(applies("cooler_air", "noise_db", {"fanless": None}), "unknown fanless leaves noise applicable")
    c.ok(applies("aio", "fan_rpm_max", {}), "AIO has no fanless gate field: still applicable")
    c.ok(not applies("storage", "rpm", {"type": "SSD"}), "an SSD has no RPM")


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


def check_curated_tables(c: Checks) -> None:
    """Every curated-table cell must be a legal value for its schema field
    (scraper/specs/tables/*.json is data: a typo there ships as a derived cell)."""
    from scraper.specs import derive, schema
    from scraper.specs.tables import load
    from scraper.specs.validate import validate_fact

    for table, category in (("gpu_chipsets", "gpu"), ("cpu_models", "cpu")):
        fields = schema.field_map(category)
        rows = load(table)
        c.ok(bool(rows), f"{table} table loads")
        for key, row in rows.items():
            for field, value in row.items():
                if field.startswith("_"):
                    continue
                spec = fields.get(field)
                c.ok(spec is not None, f"{table}[{key}].{field} is a {category} schema field")
                if spec is not None:
                    reason = validate_fact(category, spec, value)
                    c.ok(reason is None, f"{table}[{key}].{field}={value!r} validates",
                         str(reason))
    import re as _re
    fan_spec = schema.field_map("gpu")["fan_count"]
    lines = load("gpu_board_lines")
    c.ok(bool(lines), "gpu_board_lines table loads")
    for key, row in lines.items():
        try:
            _re.compile(row["pattern"])
            compiles = True
        except (KeyError, _re.error):
            compiles = False
        c.ok(compiles, f"gpu_board_lines[{key}] pattern compiles")
        c.ok(validate_fact("gpu", fan_spec, row.get("fan_count")) is None,
             f"gpu_board_lines[{key}].fan_count validates")
        c.ok(bool(row.get("brands")), f"gpu_board_lines[{key}] names its brands")
    specs = {"manufacturer": "Sapphire", "chipset": "Radeon RX 9070 XT", "fan_count": None}
    derive.infer_specs("gpu", specs, {}, context={"title": "SAPPHIRE PULSE RX 9070 XT 16GB"})
    c.eq(specs["fan_count"], 3, "a chip-keyed board line uses the chip (PULSE 9070 XT)")
    specs = {"manufacturer": "Sapphire", "chipset": "Radeon RX 9070", "fan_count": None}
    derive.infer_specs("gpu", specs, {}, context={"title": "SAPPHIRE PULSE RX 9070 16GB"})
    c.eq(specs["fan_count"], 2, "... and the other chip of that line (PULSE 9070)")
    specs = {"manufacturer": "Gigabyte", "chipset": "GeForce RTX 5080", "fan_count": None}
    derive.infer_specs("gpu", specs, {}, context={"title": "AORUS RTX 5080 XTREME WATERFORCE"})
    c.eq(specs["fan_count"], None, "a liquid card takes no board-line fan count")
    c.eq(derive.cpu_table_key({"model": "Core i5 14400F", "manufacturer": "Intel"}),
         "intel:14400F", "intel model token")
    c.eq(derive.cpu_table_key({"model": "Core Ultra 7 265KF", "manufacturer": "Intel"}),
         "intel:265KF", "core ultra token")
    c.eq(derive.cpu_table_key({"model": "AMD Ryzen 5 5600 AMD Ryzen 5 Processor",
                               "manufacturer": "AMD"}), "amd:5600", "amd model token")
    c.eq(derive.cpu_table_key({"model": "Ryzen 5", "manufacturer": "AMD"}), None,
         "a lineup name with no model number has no table key")


def check_equality_helpers(c: Checks) -> None:
    c.ok(same_value("65W", "65 w"), "unit-case noise does not create a conflict")
    c.ok(same_value(["A", "B"], ["B", "A"]),
         "list order does not create a conflict")
    c.ok(not same_value("AM4", "AM5"), "different values are different")
    c.ok(same_value(1000, 1000.0), "int/float spelling compares equal")


def check_model_codes(c: Checks) -> None:
    """Gigabyte model codes: read verbatim, kept only when they spell the
    listing's own retailer code (matching.manufacturer_model_code), then
    appended to part_numbers (build.with_model_code)."""
    from scraper.matching import manufacturer_model_code
    from scraper.specs.build import with_model_code

    def board(mpn, title, detail=None):
        return {"brand": "Gigabyte", "category_normalized": "motherboard",
                "mpn": mpn, "title_raw": title,
                "vendor_meta": {"detail_specs": detail or {}}}

    c.eq(manufacturer_model_code(board("GA520AORUSE", "Gigabyte A520 AORUS ELITE")),
         "A520 AORUS ELITE", "TMS G-code abbreviates ELITE")
    c.eq(manufacturer_model_code(board(
        "GB760GAMINGXD4GEN5", "לוח אם Gigabyte B760 GAMING X DDR4 GEN5 צבע שחור")),
         "B760 GAMING X DDR4 GEN5", "DDR4 -> D4, Hebrew stripped")
    c.eq(manufacturer_model_code(board(
        "Z890-AORUS-ELITE-WIFI7",
        "לוח אם חברת Gigabyte דגם Z890 AORUS ELITE WIFI 7 LGA 1851 DDR5 DP ATX")),
         "Z890 AORUS ELITE WIFI 7", "Yahav title noise after the model is cut")
    c.eq(manufacturer_model_code(board(
        "B850AELITEWF7", "לוח אם Gigabyte B850 AORUS ELITE WIFI7 DDR5 ATX AMD",
        {"דגם": "B850 AORUS ELITE WIFI7"})),
         "B850 AORUS ELITE WIFI7", "Ivory דגם row spells its code")
    c.eq(manufacturer_model_code(board(
        "GB760MDS3HDDR4", "לוח אם Gigabyte B760M DS3H צבע שחור")),
         None, "a title missing a word of the code yields nothing")
    c.eq(manufacturer_model_code(board(
        "GX870AORUSELITEWIFI7", "Gigabyte X870 AORUS ELITE WIFI7 ICE")),
         None, "a title variant word past the code (ICE) is a disagreement")
    c.eq(manufacturer_model_code(board(
        "GX870E-AORUS-XTREME-AI-TOP",
        "לוח אם חברת Gigabyte דגם X870E Aorus Xtreme AI TOP WiFi 7 ATX DDR5")),
         "X870E AORUS XTREME AI TOP", "a spelled-out code ignores title marketing")
    c.eq(manufacturer_model_code(board(
        "GH610IDDR4", 'לוח אם Gigabyte H610I DDR4 מק"ט GH610IDDR4 בצבע שחור')),
         "H610I DDR4", "the vendor code printed after the model is not a variant")
    c.eq(manufacturer_model_code(board(
        "GB650MS2H", "Gigabyte B650 S2H")),
         None, "the chipset line must match verbatim (B650 is not B650M)")
    c.eq(manufacturer_model_code({
        "brand": "Gigabyte", "category_normalized": "gpu",
        "mpn": "N5060AEROOC8GD",
        "title_raw": "Gigabyte GeForce RTX 5060 AERO OC 8G GV-N5060AERO OC-8GD"}),
         "GV-N5060AERO OC-8GD", "GPU: the printed GV- part number")
    c.eq(manufacturer_model_code({**board("GA520AORUSE", "ASUS A520 AORUS ELITE"),
                                  "brand": "ASUS"}),
         None, "only Gigabyte")

    offers = [{"model_code": "Z890 AORUS ELITE WIFI 7"},
              {"model_code": "Z890 AORUS ELITE WIFI7"}, {}]
    c.eq(with_model_code(["GZ890AORUSELITEWIFI7"], offers),
         ["GZ890AORUSELITEWIFI7", "Z890 AORUS ELITE WIFI7"],
         "model code appended after the retailer code, fewest separators")
    c.eq(with_model_code(["Z890-AORUS-ELITE-WIFI7"], offers),
         ["Z890-AORUS-ELITE-WIFI7"], "no duplicate of an entry spelling it")
    c.eq(with_model_code(["X"], [{"model_code": "B760M DS3H"},
                                 {"model_code": "B760M DS3H DDR4"}]),
         ["X"], "offers disagreeing on the code add nothing")


def main() -> int:
    checks = Checks()
    for group in (check_part_number_shape, check_model_prefers_a_name,
                  check_tier_order, check_applicability_gates,
                  check_validation_and_unknowns,
                  check_curated_tables, check_equality_helpers,
                  check_model_codes):
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
