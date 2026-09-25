"""
check_tms_detail.py — offline regression for the TMS detail pipeline.

The repo has no test framework by design (see PROJECT_OVERVIEW §11), so this is
a plain script:

    python scripts/check_tms_detail.py

It never touches the network. It exercises two halves of the pipeline against
verifiable data:

1. the spider (`scraper/spiders/detail_pages.py::TmsDetailSpider`) against
   trimmed captures of REAL TMS product pages in
   `scraper/specs/golden/tms_pages/`. This is the regression that matters most:
   the previous selector set matched nothing on any TMS page, so all 1,051
   detail rows ever scraped came back with `specs = {}` while the vendor page
   displayed the spec table. A fixture that stops parsing fails here instead of
   silently emptying the catalog again.
2. the resolver + canonicalization + inference-free mapping
   (`scraper/specs/resolvers/vendor_struct.py::parse_detail_specs`) against the
   label/value pairs those pages really use, per category — including the
   negative cases that must NOT produce a fact ("לא תואם AM5", promo copy,
   mojibake, a CPU label on a GPU).

Exit 0 = every assertion held; exit 1 = at least one mismatch (each printed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapy.http import HtmlResponse, Request  # noqa: E402

from scraper.specs import labels, schema  # noqa: E402
from scraper.specs.resolvers import vendor_struct  # noqa: E402
from scraper.spiders.detail_pages import TmsDetailSpider  # noqa: E402

PAGES_DIR = ROOT / "scraper" / "specs" / "golden" / "tms_pages"

# A definition-list template from an older TMS theme: the fallback path must
# keep working even though the current pages use product-attribute-item rows.
DL_PAGE = (
    "<html><body><div class='product-specification'><dl>"
    "<dt>Socket</dt><dd>AM5</dd><dt>Cores</dt><dd>8</dd>"
    "</dl></div></body></html>"
)

# An "empty" page: no spec block at all (challenge page / template change).
EMPTY_PAGE = (
    "<html><head><title>Access</title></head><body>"
    "<div class='nav'><table><tr><th>a</th><td>b</td></tr></table></div>"
    "<p>Please verify you are human.</p></body></html>"
)

SPIDER_CASES = [
    {
        "fixture": "cpu.html",
        "category": "cpu",
        "selector": "attribute-item",
        "rows": 8,
        "expect_specs": {
            "series": "EPYC",
            "socket": "SP5",
            "core_count": 128,
            "integrated_graphics": "no",
            "thread_count": 256,
            "base_clock_ghz": 2.7,
            "boost_clock_ghz": 4.1,
            "l3_cache_mb": 512,
            "tdp_w": 500,
        },
        "expect_gaps": (),
    },
    {
        "fixture": "gpu.html",
        "category": "gpu",
        "selector": "attribute-item",
        "rows": 12,
        "expect_specs": {
            "chipset": "AMD FirePro",
            "core_clock_mhz": 600,
            "memory_gb": 1,
            "memory_type": "GDDR3",
            "length_mm": 170,
            "dvi_outputs": {"DVI": 1},
            "interface": "PCIe 2.0 x16",
        },
        # Fields TMS prints that the schema deliberately has no home for yet —
        # they must show up as evidence, not as invented facts.
        "expect_gaps": ("מהירות זכרון", "רוחב פס זכרון", "גרסת DirectX",
                        "גרסת OpenGL", "Recommended PSU"),
    },
]

# Label/value pairs exactly as the vendor pages print them, per category.
PAIR_CASES = [
    {
        "name": "motherboard (ASRock WRX90 WS EVO page)",
        "category": "motherboard",
        "rows": {
            "ערכת שבבים": "AMD WRX90",
            "תושבת מעבד": "sTR5",
            "סוג זכרון": "DDR5 ECC REG | DDR5 ECC REG 3DS",
            "תצורת לוח": "EEB",
            "חיבורי תקשורת": "LAN 10 Gb/s",
            "חיבור גרפי": "DisplayPort",
            "חיבור USB": "USB Type-C | USB 3.2 | USB 2.0",
            "כרטיס קול משולב": "2 port + S/PDIF",
            "RAID": "0,1,10",
            "סלוטים DDR5": "8",
            "PCI-E x16": "7",
            "USB Type-C": "3",
            "USB 3.2": "8",
            "USB 2.0": "4",
            "חריצי הרחבה": "PCIe 5.0 x16 slot",
            "חיבורי M.2 PCIe": "1",
            "חיבורי SATA3": "4",
        },
        "expect_specs": {
            "chipset": "WRX90",
            "socket": "sTR5",
            "memory_type": "DDR5",
            "form_factor": "SSI-EEB",
            "ethernet": "LAN 10 Gb/s",
            "onboard_video": "DisplayPort",
            "usb_ports": "USB Type-C | USB 3.2 | USB 2.0",
            "audio": "2 port + S/PDIF",
            "raid_support": True,
            "memory_slots": 8,
            "pcie_x16_slots": 7,
            "expansion_slots": "PCIe 5.0 x16 slot",
            "m2_slots": ["1"],
            "sata_ports": 4,
        },
        "expect_gaps": ("ממשק אחסון",),
    },
    {
        "name": "motherboard rear USB counts without a type row",
        "category": "motherboard",
        "rows": {"USB Type-C": "3", "USB 3.2": "8"},
        "expect_specs": {"usb_ports": "USB-C x3, USB 3.2 x8"},
        "expect_gaps": (),
    },
    {
        "name": "storage (WD Ultrastar 8TB page)",
        "category": "storage",
        "rows": {
            "סוג דיסק": '3.5"',
            "נפח דיסק": "8TB",
            "מהירות דיסק": "7200 RPM",
            "באפר": "256MB",
            "סוג חיבור - ממשק": "SATA3",
            "סדרת HDD": "Ultrastar",
        },
        "expect_specs": {
            "form_factor": '3.5"',
            "capacity_gb": 8000,
            "rpm": 7200,
            "cache_mb": 256,
            "interface": "SATA 6.0 Gb/s",
            "model": "Ultrastar",
        },
        "expect_gaps": (),
    },
    {
        "name": "memory (G.Skill 2x16GB page)",
        "category": "memory",
        "rows": {
            "סוג זכרון": "DDR5",
            "גודל זיכרון (RAM)": "32GB",
            "סוג תאורה": "ARGB",
            "ערכת זיכרון": "2x16GB",
            "מהירות זכרון (Max)": "5200",
            "זמן איחזור": "CL40",
            "מתח זכרון": "1.1V",
            "צבע": "שחור | כסוף",
            "סדרה": "Trident Z5 RGB",
        },
        "expect_specs": {
            "memory_type": "DDR5",
            "total_gb": 32,
            "lighting": "ARGB",
            "module_count": 2,
            "module_size_gb": 16,
            "speed_mhz": 5200,
            "cas_latency": 40,
            "voltage_v": 1.1,
            "color": "Black / Silver",
            "model": "Trident Z5 RGB",
        },
        "expect_gaps": (),
    },
    {
        "name": "psu",
        "category": "psu",
        "rows": {
            "הספק": "750W",
            "יעילות": "80+ Gold",
            "מודולרי": "Full Modular",
            "אורך": "160mm",
            "מחברי SATA": "6",
            "ללא מאוורר": "לא",
        },
        "expect_specs": {
            "wattage_w": 750,
            "efficiency": "80+ Gold",
            "modular": "full",
            "length_mm": 160,
            "sata_connectors": 6,
            "fanless": False,
        },
        "expect_gaps": (),
    },
    {
        "name": "psu (Plonter detail rows: certificates + connectors)",
        "category": "psu",
        "rows": {
            "certificates-according to manufacturer":
                "80 PLUS Gold (according to manufacturer, 115V)",
            "certificates-loud 80 PLUS":
                "80 PLUS titanium (115V, loud 80 PLUS certificate)",
            "cable-management": "Full Modular",
            "shape-factor": "ATX12V",
            "SATA": "8",
            "IDE": "4",
            "20/24-Pin": "1",
            "4/8-Pin ATX12V": "2",
            "6/8-Pin PCIe": "4",
            "Certificates": "80 PLUS Platinum (according to manufacturer, voltage unknown)",
        },
        "expect_specs": {
            "efficiency": "80+ Gold",
            "modular": "full",
            "type": "ATX",
            "sata_connectors": 8,
            "molex4_connectors": 4,
            "atx4_connectors": 1,
            "eps8_connectors": 2,
            "pcie62_connectors": 4,
        },
        # The 80-PLUS blob must never reach the brand field again
        # (schema.py suffix-matched 'certificates_according_to_manufacturer'
        # onto the `manufacturer` alias until Sep 2026).
        "expect_absent": ("manufacturer",),
        "expect_gaps": (),
    },
    {
        "name": "motherboard combined connectivity cell splits per radio",
        "category": "motherboard",
        "rows": {
            "חיבורי תקשורת": "Bluetooth 5.3 | LAN 2.5 Gb/s | Wi-Fi 6/6E (802.11ax)",
        },
        "expect_specs": {
            "ethernet": "LAN 2.5 Gb/s",
            "wireless": "Wi-Fi 6",
        },
        "expect_gaps": (),
    },
    {
        "name": "motherboard LAN-only connectivity cell",
        "category": "motherboard",
        "rows": {"חיבורי תקשורת": "LAN 10 Gb/s"},
        "expect_specs": {"ethernet": "LAN 10 Gb/s"},
        "expect_gaps": (),
    },
    {
        "name": "case fan",
        "category": "case_fan",
        "rows": {
            "גודל": "120mm",
            "סל\u05f4ד": "500-1500 RPM",
            "רעש": "25.6 dB",
            "pwm": "כן",
            "כיוון זרימה": "הפוך",
        },
        "expect_specs": {
            "size_mm": 120,
            "rpm_min": 500,
            "rpm_max": 1500,
            "noise_db": 25.6,
            "pwm": True,
            "flow_direction": "reverse",
        },
        "expect_gaps": (),
    },
    {
        "name": "cpu cooler",
        "category": "cooler_air",
        "rows": {
            "סל\u05f4ד": "600-1500 RPM",
            "רעש": "23 dB",
            "גובה": "155mm",
            "פיזור חום": "220W",
            "קירור נוזלי": "לא",
        },
        "expect_specs": {
            "fan_rpm_min": 600,
            "fan_rpm_max": 1500,
            "noise_db": 23.0,
            "height_mm": 155,
            "tdp_w": 220,
            "water_cooled": False,
        },
        "expect_gaps": (),
    },
]

NEGATIVE_CASES = [
    {
        "name": "Plonter promo copy is not a spec",
        "category": "memory",
        "rows": {"מפרט זיכרון": "לחץ/י לרכישה עכשיו"},
        "expect_no_facts": True,
    },
    {
        "name": "mojibake is not a spec",
        "category": "memory",
        "rows": {"דגם": "׳™׳¦׳¨׳�"},
        "expect_no_facts": True,
    },
    {
        "name": "a negated Hebrew sentence is dropped, never half-read",
        "category": "motherboard",
        "rows": {"תושבת": "לא תואם AM5"},
        "expect_absent": ("socket",),
    },
    {
        "name": "vendor SKU rows never become part_numbers",
        "category": "storage",
        "rows": {"מק\u05f4ט": "100-000001443", "sku": "ABC-1"},
        "expect_absent": ("part_numbers",),
    },
    {
        "name": "an unknown Hebrew label is reported, not guessed",
        "category": "cpu",
        "rows": {"יכולת מיוחדת": "טכנולוגיה"},
        "expect_absent": ("socket", "core_count"),
        "expect_gap": "יכולת מיוחדת",
    },
    {
        "name": "warranty rows are bookkeeping, not specs and not gaps",
        "category": "motherboard",
        "rows": {"Warranty / Importer": "3 שנים", "אחריות": "36 חודשים"},
        "expect_no_facts": True,
        "expect_no_gap": ("Warranty / Importer", "אחריות"),
    },
]


def load_page(path: Path, url: str, sku: str = "TEST-1") -> HtmlResponse:
    request = Request(url=url, meta={"vendor_sku": sku})
    return HtmlResponse(url=url, body=path.read_bytes(), encoding="utf-8",
                        request=request)


def check_spider_cases(failures: list[str]) -> int:
    checked = 0
    spider = TmsDetailSpider()
    for case in SPIDER_CASES:
        path = PAGES_DIR / case["fixture"]
        if not path.exists():
            failures.append(f"{case['fixture']}: fixture missing ({path})")
            continue
        response = load_page(path, f"https://tms.co.il/x/{case['fixture']}")
        items = list(spider.parse_detail(response))
        if not items:
            failures.append(f"{case['fixture']}: spider yielded no item")
            continue
        item = items[0]
        extra = item.get("extra") or {}
        checked += 1
        if extra.get("spec_selector") != case["selector"]:
            failures.append(
                f"{case['fixture']}: selector {extra.get('spec_selector')!r} != "
                f"{case['selector']!r}")
        checked += 1
        if extra.get("spec_rows") != case["rows"]:
            failures.append(
                f"{case['fixture']}: spec_rows {extra.get('spec_rows')!r} != "
                f"{case['rows']!r}")
        checked += 1
        if not item.get("specs"):
            failures.append(f"{case['fixture']}: specs empty — regression")

        gaps: dict[str, int] = {}
        specs = vendor_struct.parse_detail_specs(case["category"],
                                                 item.get("specs"), gaps=gaps)
        for field, expected in case["expect_specs"].items():
            actual = specs.get(field, [None])[0]
            value = actual.value if actual is not None else None
            checked += 1
            if value != expected:
                failures.append(
                    f"{case['fixture']}: {field} = {value!r}, expected {expected!r}")
        for label in case["expect_gaps"]:
            checked += 1
            if label not in gaps:
                failures.append(
                    f"{case['fixture']}: label {label!r} should be reported as a "
                    "coverage gap")
    return checked


def check_pair_cases(failures: list[str]) -> int:
    checked = 0
    for case in PAIR_CASES + NEGATIVE_CASES:
        name = case["name"]
        gaps: dict[str, int] = {}
        facts = vendor_struct.parse_detail_specs(case["category"], case["rows"],
                                                 gaps=gaps)
        values = {field: entries[0].value for field, entries in facts.items()}
        if case.get("expect_no_facts"):
            checked += 1
            if values:
                failures.append(f"{name}: expected no facts, got {values!r}")
            continue
        for field, expected in (case.get("expect_specs") or {}).items():
            checked += 1
            if values.get(field) != expected:
                failures.append(
                    f"{name}: {field} = {values.get(field)!r}, expected {expected!r}")
        for field in case.get("expect_absent") or ():
            checked += 1
            if field in values:
                failures.append(
                    f"{name}: {field} should be absent, got {values[field]!r}")
        if case.get("expect_gap"):
            checked += 1
            if case["expect_gap"] not in gaps:
                failures.append(
                    f"{name}: label {case['expect_gap']!r} should be reported as a "
                    "coverage gap")
        for label in case.get("expect_no_gap") or ():
            checked += 1
            if label in gaps:
                failures.append(
                    f"{name}: label {label!r} is bookkeeping and must not be "
                    "reported as a coverage gap")
    return checked


def check_chipset_and_efficiency(failures: list[str]) -> int:
    """Concatenated vendor chipset cells and certificate blobs (Sep 2026)."""
    from scraper.specs.canon import canon_chipset, canon_efficiency
    checked = 0
    for raw, expected in (
        ("AMDB850AMDX670", "B850"),
        ("AMDX870EAMDX870AMDX670", "X870E"),
        ("INTELH810INTELH610", "H810"),
        ("Z890INTELZ890", "Z890"),
        ("INTELB860INTELB760", "B860"),
        ("AMDB840INTELB760", "B840"),
        ("AMDA620AMDX670", "A620"),
        ("AMDB650AMDB550", "B650"),
        ("B760EXPRESS", "B760"),
        ("AMDWRX80", "WRX80"),
        ("C612PCH", "C612"),
        ("AMD B850", "B850"),
        ("B650", "B650"),
        ("X570S", "X570S"),
        ("B760M", "B760"),
    ):
        checked += 1
        actual = canon_chipset(raw)
        if actual != expected:
            failures.append(f"canon_chipset({raw!r}) = {actual!r}, expected {expected!r}")
    for raw, expected in (
        ("80 PLUS Gold (according to manufacturer, 115V)", "80+ Gold"),
        ("80 PLUS Gold (115V, loud 80 PLUS certificate)", "80+ Gold"),
        ("80 PLUS titanium (according to manufacturer, voltage unknown)",
         "80+ Titanium"),
        ("80+ Gold", "80+ Gold"),
        ("Gold", "80+ Gold"),
        ("80 PLUS Bronze", "80+ Bronze"),
    ):
        checked += 1
        actual = canon_efficiency(raw)
        if actual != expected:
            failures.append(
                f"canon_efficiency({raw!r}) = {actual!r}, expected {expected!r}")
    return checked


def check_template_fallbacks(failures: list[str]) -> int:
    checked = 0
    spider = TmsDetailSpider()
    for name, body, selector, expected in (
        ("definition-list page", DL_PAGE, "definition-list",
         {"Socket": "AM5", "Cores": "8"}),
        ("empty page", EMPTY_PAGE, "none", {}),
    ):
        response = HtmlResponse(url="https://tms.co.il/x", body=body.encode("utf-8"),
                                encoding="utf-8")
        specs, matched, _rows = spider._parse_specs(response)
        checked += 2
        if matched != selector:
            failures.append(f"{name}: selector {matched!r} != {selector!r}")
        if specs != expected:
            failures.append(f"{name}: specs {specs!r} != {expected!r}")
    return checked


def check_category_awareness(failures: list[str]) -> int:
    """The same Hebrew label means different fields per category."""
    checked = 0
    for category, label, expected in (
        ("cpu", "מעבד גרפי", "integrated_graphics"),
        ("gpu", "מעבד גרפי", "chipset"),
        ("gpu", "חיבור גרפי", labels.GPU_OUTPUTS),
        ("motherboard", "חיבור גרפי", "onboard_video"),
        ("memory", "סדרה", "model"),          # memory has no `series`
        ("cpu", "סדרה", "series"),
    ):
        actual = labels.translate_vendor_label(label, category)
        checked += 1
        if actual != expected:
            failures.append(
                f"{category}: {label!r} -> {actual!r}, expected {expected!r}")
    checked += 1
    if not labels.is_ignored_label("מק\u05f4ט"):
        failures.append("the Hebrew SKU label should be ignored")
    return checked


def check_mapped_fields_exist(failures: list[str]) -> int:
    """Every label in the vocabulary must point at a real field."""
    checked = 0
    for category, table in labels.CATEGORY_LABELS.items():
        fields = schema.field_map(category)
        for label, target in table.items():
            if target in labels.SPECIAL_TOKENS or target.startswith(labels.USB_COUNT_PREFIX):
                continue
            if target not in fields and target not in labels._FIELD_FALLBACKS:
                failures.append(
                    f"{category}: label {label!r} maps to unknown field {target!r}")
            checked += 1
    return checked


def main() -> int:
    failures: list[str] = []
    checked = 0
    checked += check_spider_cases(failures)
    checked += check_pair_cases(failures)
    checked += check_template_fallbacks(failures)
    checked += check_category_awareness(failures)
    checked += check_mapped_fields_exist(failures)
    checked += check_chipset_and_efficiency(failures)

    if failures:
        print(f"[tms-detail] FAIL — {len(failures)} mismatch(es):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[tms-detail] pass — {checked} assertions")
    print(json.dumps({"assertions": checked, "fixtures": len(SPIDER_CASES),
                      "pair_cases": len(PAIR_CASES) + len(NEGATIVE_CASES)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
