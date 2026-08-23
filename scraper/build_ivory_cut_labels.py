"""
Build data/ivory_cut_labels.json directly from tmp/IvoryFindings.md.

Replaces the old learn_ivory_labels.py statistical-correlation approach.
We don't need to *guess* what cut 5838 means from title correlation —
IvoryFindings.md (owner-collected from the site's own filter UI) already
gives the ground truth: `data-id` -> Hebrew filter label, grouped by
builder category. This script transcribes that table into the same
{cuts: {...}, parents: {...}} shape extractors.py already expects.

IMPORTANT: tmp/ is gitignored (see decisions.md) — IvoryFindings.md never
reaches GitHub Actions. Run this ONCE locally whenever the findings doc
changes, and commit the resulting data/ivory_cut_labels.json — the
pipeline itself only ever reads that committed JSON, never the doc.

Usage:
    python -m scraper.build_ivory_cut_labels
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDINGS_PATH = ROOT / "tmp" / "IvoryFindings.md"
OUT_PATH = ROOT / "data" / "ivory_cut_labels.json"

# ### section header (Hebrew name before "(Category ID") -> ivory.py's
# own category_guess values, so this table lines up 1:1 with the spider.
CATEGORY_SLUGS = [
    ("מעבד INTEL", "cpu"),
    ("לוח אם", "motherboard"),
    ("מאוורר למעבד", "cpu_cooler_air"),
    ("קירור נוזלי למעבד", "cpu_cooler_aio"),
    ("זכרון (RAM)", "ram"),
    ("כונן SSD", "ssd"),
    ("דיסק קשיח", "hdd"),
    ("כרטיס מסך", "gpu"),
    ("ספק כח", "psu"),
    ("מארז", "case"),
    ("מאוורר נוסף למארז", "case_fans"),
]

# (category_slug, hebrew subheader) -> attribute key.
# Same Hebrew header can mean different things in different categories
# (e.g. "ערכת שבבים" = motherboard Chipset vs. GPU vendor) so this is
# keyed per-category, not globally.
HEADER_MAP = {
    "cpu": {
        "סוג המעבד": "cpu_tier",
        "מספר ליבות": "cores",
        "זכרון מטמון": "cache_mb",
        "דור המעבד אינטל": "cpu_generation",
        "מאיץ גרפי": "integrated_graphics",
    },
    "motherboard": {
        "מותג לוח אם": "brand",
        "גודל לוח אם": "form_factor",
        "זכרון נתמך": "memory_type",
        "חיבורי מסך": "display_outputs",
        "חיבורי USB בלוח אם": "usb_ports",
        "קישוריות רשת": "connectivity",
        "ערכת שבבים (Chipset)": "chipset",
        "צבע הרכיב": "color",
        "חיבורי שמע בלוח אם": "audio_connectors",
    },
    "cpu_cooler_air": {
        "מותג מאוורר למעבד": "brand",
        "סוג תאורה": "lighting",
        "תצוגה על הקירור": "cooler_display",
        "צבע הרכיב": "color",
        "גובה המאוורר למעבד": "cooler_height_mm",
    },
    "cpu_cooler_aio": {
        "מותג קירור נוזלי למעבד": "brand",
        "גודל מאוורר": "fan_size_mm",
        "גודל רדיאטור": "radiator_size_mm",
        "סוג תאורה": "lighting",
    },
    "ram": {
        "מותג זכרון RAM": "brand",
        "נפח זכרון RAM": "capacity_label",
        "דור זכרון RAM": "memory_type",
        "מהירות זכרון RAM": "speed_mhz",
        "סוג תאורה": "lighting",
        "צבע הרכיב": "color",
        "זמן אחזור (CAS Latency)": "cas_latency",
        "תאימות Overclock": "overclock_support",
    },
    "ssd": {
        "נפח כונן SSD": "capacity_gb",
        "מותג כונן SSD": "brand",
        "מבנה כונן SSD": "form_factor",
        "ממשק SSD": "interface",
        "גרסת ממשק PCIe": "pcie_gen",
    },
    "hdd": {
        "נפח דיסק קשיח": "capacity_gb",
        "מותג דיסק קשיח": "brand",
        "סל''ד - RPM": "rpm",
        "זכרון מטמון דיסק קשיח": "cache_mb",
        "תאימות כונן": "drive_use_case",
    },
    "gpu": {
        "ערכת שבבים": "gpu_vendor",
        "מותג כרטיס מסך": "brand",
        "נפח זכרון": "vram_gb",
        "מעבד גרפי": "gpu_chip",
        "גודל רדיאטור": "radiator_size_mm",
        "יציאות HDMI": "hdmi_ports",
        "יציאות DVI": "dvi_ports",
        "יציאות VGA": "vga_ports",
        "יציאות Mini DisplayPort": "mini_displayport_ports",
        "יציאות DisplayPort": "displayport_ports",
        "צבע הרכיב": "color",
        "תאורת כרטיס המסך": "lighting",
        "קירור כרטיס המסך": "cooling_type",
        "מספר מאווררים": "fan_count",
        "תכונות כרטיס נוספות": "gpu_features",
    },
    "psu": {
        "מותג ספקי כח": "brand",
        "ספק כח מודולרי": "modular",
        "נצילות ספק כח": "efficiency",
        "סוג תאורה": "lighting",
        "צבע הרכיב": "color",
        "הספק ספק כח": "wattage_w",
        "חיבורי SATA Power": "sata_connectors",
        "חיבורים לכרטיס מסך": "pcie_power_connectors",
        "חיבורי CPU ללוח אם": "cpu_power_connectors",
    },
    "case": {
        "מותג מארזים": "brand",
        "צבע מארז": "color",
        "מסך וחלון צד": "side_panel",
        "סוג תאורה": "lighting",
        "תמיכה בכונן אופטי": "optical_drive_support",
        "חיבורי מארז מחשב": "front_io",
    },
    "case_fans": {
        "גודל מאווררים למארז": "fan_size_mm",
        "מותג מאווררים": "brand",
        "צבע לד": "lighting",
        "צבע הרכיב": "color",
        "מספר מאווררים באריזה": "fans_per_pack",
        "מבנה להבים": "blade_design",
        "תכונות מאוורר נוספות": "fan_features",
    },
}

# Headers that mean the same thing in every category — fallback if a
# category-specific mapping above didn't match.
GLOBAL_HEADERS = {
    "מציאון": "clearance_item",
    "צבע הרכיב": "color",
    "סוג תאורה": "lighting",
}

# Exact-match Hebrew value -> English, for values that aren't already
# Latin/numeric in the source doc.
VALUE_TRANSLATE = {
    # Colors
    "לבן": "White", "שחור": "Black", "שחור כסוף": "Black/Silver",
    "שחור אדום": "Black/Red", "שחור זהב": "Black/Gold", "אפור": "Gray",
    "כחול": "Blue", "ירוק": "Green", "עץ": "Wood", "חום": "Brown",
    # Lighting
    "תאורת לד RGB": "RGB", "ללא תאורה": "None", "תאורת לד ARGB": "ARGB",
    "כולל תאורת RGB": "RGB",
    # Cooler display
    "מסך LCD": "LCD Display", "צג טמפרטורה": "Temperature Display",
    "מסך OLED": "OLED Display",
    # Integrated graphics
    "ללא מאיץ גרפי": "None",
    # RAM overclock
    "תומך Intel XMP": "Intel XMP", "תומך AMD EXPO": "AMD EXPO",
    "ללא Overclock (JEDEC בלבד)": "JEDEC only (no OC)",
    # HDD use case
    "כונן ל-NAS": "NAS", "כונן ל-DVR / NVR": "DVR/NVR",
    # PSU modular
    "מודולרי מלא": "Full Modular", "חצי מודולרי": "Semi Modular",
    # Case side panel
    "מארז כולל חלון": "Windowed", "מארז ללא חלון": "No Window",
    "מארז כולל מסך": "Includes Screen",
    # Case optical bay
    "כולל חריץ הרחבה לכונן אופטי": "Optical Bay Included",
    "ללא תמיכה בכונן אופטי": "None",
    # GPU cooling type
    "קירור פסיבי": "Passive", "קירור נוזלי": "Liquid", "קירור אוויר": "Air",
    # GPU features
    "פרופיל נמוך": "Low Profile",
    # Case fan blade design
    "להבים סטנדרטיים": "Standard", "להבים הפוכים": "Reverse",
    # Case fan extra features
    "כולל מסך מובנה": "Built-in Display",
    "תומך שרשור מאווררים": "Daisy-chainable",
    "תומך מצב 0 סל''ד": "Zero-RPM Mode",
    "כולל מראת אינפיניטי": "Infinity Mirror",
    # SSD form factor
    "2.5 אינץ'": "2.5-inch",
    # Motherboard network connectivity
    "בלוטוס - Bluetooth": "Bluetooth", "חיבור LAN קווי בלבד": "Wired LAN only",
    # Motherboard audio connectors
    "2 חיבורי אודיו 3.5mm": "2x 3.5mm Audio Jack",
    "3 חיבורי אודיו 3.5mm": "3x 3.5mm Audio Jack",
    "5 חיבורי אודיו 3.5mm": "5x 3.5mm Audio Jack",
    "6 חיבורי אודיו 3.5mm": "6x 3.5mm Audio Jack",
    "חיבור אודיו אופטי": "Optical Audio",
    # Case front IO
    "2 חיבורי USB 2.0": "2x USB 2.0", "חיבור USB 2.0": "1x USB 2.0",
    "2 חיבורי USB 3": "2x USB 3.0", "חיבור USB 3": "1x USB 3.0",
    "2 חיבורי USB-C": "2x USB-C", "חיבור USB-C": "1x USB-C",
    "3 חיבורי USB 3": "3x USB 3.0", "4 חיבורי USB 3": "4x USB 3.0",
    "3 חיבורי USB-C": "3x USB-C",
}

HE_FAN_COUNT_WORDS = {
    "מאוורר אחד": 1, "שני מאווררים": 2, "שלושה מאווררים": 3,
}

CM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ס[\"'׳]{1,2}מ")
MM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*מ[\"'׳]{1,2}מ")


def _num(pattern: str, s: str, flags=re.I):
    m = re.search(pattern, s, flags)
    return int(float(m.group(1))) if m else None


def _capacity_to_gb(s: str):
    m = re.search(r"(\d+(?:\.\d+)?)\s*TB", s, re.I)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", s, re.I)
    if m:
        return int(float(m.group(1)))
    return None


# attribute key -> parser(label) -> value, applied before the generic
# VALUE_TRANSLATE / passthrough fallback.
ATTR_PARSERS = {
    "cores": lambda s: _num(r"(\d+)\s*ליבות", s) or s,
    "cache_mb": lambda s: _num(r"(\d+)\s*MB", s) or s,
    "cooler_height_mm": lambda s: (lambda m: int(float(m.group(1)) * 10) if m else s)(CM_RE.search(s)),
    "fan_size_mm": lambda s: (lambda m: int(float(m.group(1)) * 10) if m else s)(CM_RE.search(s)),
    "radiator_size_mm": lambda s: (lambda m: int(float(m.group(1))) if m else s)(MM_RE.search(s)),
    "capacity_gb": lambda s: _capacity_to_gb(s) or s,
    "speed_mhz": lambda s: _num(r"(\d+)", s) or s,
    "cas_latency": lambda s: _num(r"CL\s?(\d+)", s) or s,
    "wattage_w": lambda s: _num(r"(\d+)\s*W\b", s) or s,
    "vram_gb": lambda s: _num(r"(\d+)\s*GB", s) or s,
    "sata_connectors": lambda s: _num(r"(\d+)\s*חיבורים", s) or s,
    "rpm": lambda s: _num(r"(\d+)\s*RPM", s) or s,
    "cpu_generation": lambda s: re.sub(r"^דור\s+", "Gen ", s),
    "fan_count": lambda s: HE_FAN_COUNT_WORDS.get(s, s),
    "fans_per_pack": lambda s: HE_FAN_COUNT_WORDS.get(s, s),
    "clearance_item": lambda s: True,
    "form_factor": lambda s: VALUE_TRANSLATE.get(s, s),  # e.g. SSD "2.5 אינץ'"
}


def normalize_value(attr: str, label: str):
    label = label.strip()
    parser = ATTR_PARSERS.get(attr)
    if parser:
        return parser(label)
    return VALUE_TRANSLATE.get(label, label)


ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*$")
SECTION_RE = re.compile(r"^###\s+(.+?)\s*\(Category ID")
SUBHEADER_RE = re.compile(r"^####\s+(.+?)\s*$")


def parse_findings(text: str) -> dict:
    slug_lookup = {name: slug for name, slug in CATEGORY_SLUGS}
    cuts: dict[str, dict] = {}
    current_slug = None
    current_header = None
    untranslated = 0

    for line in text.splitlines():
        sec = SECTION_RE.match(line)
        if sec:
            current_slug = slug_lookup.get(sec.group(1).strip())
            current_header = None
            continue

        sub = SUBHEADER_RE.match(line)
        if sub:
            current_header = sub.group(1).strip()
            continue

        row = ROW_RE.match(line)
        if not row or not current_header:
            continue
        cut_id, label = row.group(1), row.group(2)
        if cut_id == "data-id" or label == "Label":
            continue  # header row of the table itself

        attr = None
        if current_slug and current_slug in HEADER_MAP:
            attr = HEADER_MAP[current_slug].get(current_header)
        if attr is None:
            attr = GLOBAL_HEADERS.get(current_header)
        if attr is None:
            continue  # header not mapped (e.g. internal connector placement) — skip

        value = normalize_value(attr, label)
        if isinstance(value, str) and re.search(r"[\u0590-\u05FF]", value):
            untranslated += 1

        cuts.setdefault(cut_id, {})[attr] = value

    print(f"[build_ivory_cut_labels] {len(cuts)} cut ids labeled, "
          f"{untranslated} values left untranslated (Hebrew passthrough)")
    return {"cuts": cuts}


def main() -> None:
    if not FINDINGS_PATH.exists():
        raise SystemExit(
            f"{FINDINGS_PATH} not found — this script only runs locally, "
            "against your own copy of the findings doc (tmp/ is gitignored)."
        )
    result = parse_findings(FINDINGS_PATH.read_text(encoding="utf-8"))
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {OUT_PATH}")


if __name__ == "__main__":
    main()