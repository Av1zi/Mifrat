"""
specs/labels.py — the vendor label vocabulary.

Vendor product pages label the same fact in their own language ("תושבת מעבד",
"Socket", "Hardware Socket"). The schema owns field *semantics*; this module owns
the *vocabulary* that maps those labels onto it, so `schema.py` stays the single
source of truth for field names while the translation table grows from real
pages instead of from broad regexes.

Two public entry points:

- `translate_vendor_label(label, category)` -> schema field name, a special
  action token (see below), or None when the label is not a spec.
- `clean_detail_value(value)` -> the machine-readable form of a vendor value
  (Hebrew unit words removed, Hebrew color/boolean words translated), or None
  when the value is prose/mojibake and must be dropped.

Special action tokens are returned by `translate_vendor_label` when one vendor
row expands into several schema fields (a clock range, a memory kit, a rear-USB
breakdown). `resolvers/vendor_struct.py` implements them; keeping them out of
the field namespace means the schema never gains a field called
"__memory_kit__".

Category awareness is mandatory, not cosmetic: "מעבד גרפי" is the integrated
graphics of a CPU but the chip *name* of a GPU, and "חיבור גרפי" is a
motherboard's onboard video but a graphics card's display outputs. A
category-blind table silently wrote one into the other.

Evidence-driven growth: every label a detail page carries that maps to nothing
is collected into the coverage report (`label_gaps`) with its frequency, so the
next mapping decision is made from real vendor vocabulary rather than guesses.
"""

from __future__ import annotations

import re

from . import schema
from .canon import HE_COLOR_WORDS

# --------------------------------------------------------------------------
# Special action tokens (implemented in resolvers/vendor_struct.py)
# --------------------------------------------------------------------------

CLOCK_RANGE = "__clock_range__"        # "Base 2.7GHz | Max. 4.1GHz"
CACHE_TIER = "__cache_tier__"          # "L3 512MB" -> l2_cache_mb/l3_cache_mb
MEMORY_KIT = "__memory_kit__"          # "2x16GB" -> count/size/total
RPM_RANGE = "__rpm_range__"            # "600-1500 RPM" -> rpm min/max
GPU_DIMENSIONS = "__gpu_dimensions__"  # "L=170mm W=69mm" -> length_mm
GPU_OUTPUTS = "__gpu_outputs__"        # "VGA | DVI | DMS-59" -> dvi/dp/hdmi maps
RAID = "__raid__"                      # "0,1,10" -> raid_support True
# TMS packs the whole networking block into one cell
# ("Bluetooth 5.4 | Wi-Fi 7 (802.11be) | LAN 5 Gb/s"); emitting it into
# `ethernet` whole is a mis-mapping the validator then has to reject. The
# splitter in vendor_struct routes each radio to its own field.
CONNECTIVITY_SPLIT = "__connectivity_split__"
USB_COUNT_PREFIX = "__usb_count__:"    # "__usb_count__:USB-C" + "3"

SPECIAL_TOKENS = frozenset({
    CLOCK_RANGE, CACHE_TIER, MEMORY_KIT, RPM_RANGE, GPU_DIMENSIONS,
    GPU_OUTPUTS, RAID, CONNECTIVITY_SPLIT,
})

# --------------------------------------------------------------------------
# Label normalization
# --------------------------------------------------------------------------

# Vendor labels decorate the same word with geresh/gershayim and RTL marks; one
# spelling per label keeps the table free of near-duplicate rows.
_GERESH = str.maketrans({"׳": "", "״": "", "'": "", '"': "", "’": "", "“": "",
                         "”": "", "\u200e": "", "\u200f": ""})
_PAREN = re.compile(r"\(([^)]*)\)")


def normalize_label(label) -> str:
    """One spelling per label: geresh-free, whitespace-collapsed, lowercased.

    Hebrew memory words are folded to the defective spelling (זיכרון ->
    זכרון): vendors mix the full and defective ktiv freely (TMS prints
    גודל זיכרון, Ivory prints גודל זכרון) and the word is unambiguous, so
    one canonical form keeps the table free of near-duplicate rows.
    """
    text = str(label or "").translate(_GERESH)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.lower()
    text = text.replace("זיכרון", "זכרון")
    return text


def _variants(label) -> list[str]:
    """Candidate keys for one vendor label, most specific first.

    Parentheticals are both dropped ("מהירות זכרון (Max)") and offered on
    their own ("ליבות (Cores)" -> "cores"), which is how Ivory and TMS annotate
    Hebrew labels with an English hint.
    """
    full = normalize_label(label)
    if not full:
        return []
    out = [full]
    stripped = re.sub(r"\s+", " ", _PAREN.sub(" ", full)).strip()
    if stripped and stripped not in out:
        out.append(stripped)
    for hint in _PAREN.findall(full):
        hint = hint.strip()
        if hint and hint not in out:
            out.append(hint)
    return out


# --------------------------------------------------------------------------
# The vocabulary (raw tables; keys are normalized once, at the bottom)
# --------------------------------------------------------------------------

# Vendor-agnostic labels. Kept small: a label belongs here only when it means
# the same thing in every category.
_COMMON_RAW: dict[str, str] = {
    # Hebrew
    "דגם": "model",
    "דגם מוצר": "model",
    "מותג": "manufacturer",
    "יצרן": "manufacturer",
    "מק\u05f4ט": "part_numbers",
    "מק\u05f4טים": "part_numbers",
    "אריזה": "packaging",
    "צבע": "color",
    "צבעים": "color",
    "תאורה": "lighting",
    "סדרה": "series",
    "סוג": "type",
    # English
    "brand": "manufacturer",
    "manufacturer": "manufacturer",
    "maker": "manufacturer",
    "model": "model",
    "model name": "model",
    "sku": "part_numbers",
    "mpn": "part_numbers",
    "part number": "part_numbers",
    "color": "color",
    "colour": "color",
    "lighting": "lighting",
    "series": "series",
    "type": "type",
}

# Labels whose meaning depends on the category. Order inside a table does not
# matter (lookup is exact); the tables are grouped by product page for review.
_CATEGORY_RAW: dict[str, dict[str, str]] = {
    "cpu": {
        "סדרת מעבד": "series",
        "סדרת המעבד": "series",
        "משפחת מעבדים": "series",
        "ארכיטקטורה": "microarchitecture",
        "משפחת ליבות": "core_family",
        "שם קוד": "core_family",
        "תושבת מעבד": "socket",
        "תושבת": "socket",
        "סוקט": "socket",
        "כמות ליבות מעבד": "core_count",
        "כמות ליבות": "core_count",
        "ליבות": "core_count",
        "מספר ליבות": "core_count",
        "נימים": "thread_count",
        "מספר נימים": "thread_count",
        "threads": "thread_count",
        "threads #": "thread_count",
        "מעבד גרפי": "integrated_graphics",
        "גרפיקה משולבת": "integrated_graphics",
        "מהירות מעבד": CLOCK_RANGE,
        "מהירות שעון": CLOCK_RANGE,
        "תדר": CLOCK_RANGE,
        "זכרון מטמון במעבד": CACHE_TIER,
        "זיכרון מטמון במעבד": CACHE_TIER,
        "זכרון מטמון": CACHE_TIER,
        "זיכרון מטמון": CACHE_TIER,
        "מטמון": CACHE_TIER,
        "צריכת חשמל - מעבד": "tdp_w",
        "צריכת חשמל מעבד": "tdp_w",
        "צריכת חשמל": "tdp_w",
        "הספק": "tdp_w",
        "ליתוגרפיה": "lithography_nm",
        "תהליך ייצור": "lithography_nm",
        "זיכרון מקסימלי": "max_memory_gb",
        "מקסימום זיכרון": "max_memory_gb",
        "תמיכת ecc": "ecc_support",
        "smt": "smt",
        "hyper threading": "smt",
        "hyper-threading": "smt",
        "כולל קירור": "includes_cooler",
        "קירור כלול": "includes_cooler",
        "לא נעול": "unlocked",
        "ללא נעול": "unlocked",
        "מכפיל פתוח": "unlocked",
        "מטמון l2": "l2_cache_mb",
        "מטמון l3": "l3_cache_mb",
        "l2 cache": "l2_cache_mb",
        "l3 cache": "l3_cache_mb",
    },
    "gpu": {
        "מעבד גרפי": "chipset",
        "שבב גרפי": "chipset",
        "גרפיקה": "chipset",
        "גודל זכרון כרטיס מסך": "memory_gb",
        "זיכרון גרפי": "memory_gb",
        "גודל זכרון": "memory_gb",
        "זיכרון": "memory_gb",
        "סוג זכרון גרפי": "memory_type",
        "סוג זכרון": "memory_type",
        "מהירות ליבה": "core_clock_mhz",
        "תדר ליבה": "core_clock_mhz",
        "מהירות מוגברת": "boost_clock_mhz",
        "מימדים": GPU_DIMENSIONS,
        "מידות": GPU_DIMENSIONS,
        "ממדים": GPU_DIMENSIONS,
        "ממשק כרטיס מסך": "interface",
        "ממשק": "interface",
        "חיבור למחשב": "interface",
        "חיבור גרפי": GPU_OUTPUTS,
        "יציאות": GPU_OUTPUTS,
        "מספר מאווררים": "fan_count",
        "קירור": "cooling",
        "חיבורי חשמל": "external_power",
        "תמיכת סנכרון": "frame_sync",
        "סנכרון פריימים": "frame_sync",
    },
    "motherboard": {
        "ערכת שבבים": "chipset",
        "שבב": "chipset",
        "צ'יפסט": "chipset",
        "תושבת מעבד": "socket",
        "תושבת": "socket",
        "סוקט": "socket",
        "סוג זכרון": "memory_type",
        "תמיכת זיכרון": "memory_type",
        "תצורת לוח": "form_factor",
        "פורמט": "form_factor",
        # One cell holding Bluetooth + Wi-Fi + LAN must not land in `ethernet`
        # whole (935 facts/run were rejected that way in Sep 2026).
        "חיבורי תקשורת": CONNECTIVITY_SPLIT,
        "רשת": "ethernet",
        "כרטיס קול משולב": "audio",
        "שמע": "audio",
        "raid": RAID,
        "תמיכת raid": RAID,
        "סלוטים ddr5": "memory_slots",
        "סלוטים ddr4": "memory_slots",
        "חריצי זיכרון": "memory_slots",
        "מספר חריצי זיכרון": "memory_slots",
        "pci-e x16": "pcie_x16_slots",
        "pcie x16": "pcie_x16_slots",
        "חריצי pcie x16": "pcie_x16_slots",
        "pci-e x1": "pcie_x1_slots",
        "pcie x1": "pcie_x1_slots",
        "חיבורי m.2 pcie": "m2_slots",
        "חריצי m.2": "m2_slots",
        "m.2": "m2_slots",
        "חיבורי sata3": "sata_ports",
        "יציאות sata": "sata_ports",
        "sata": "sata_ports",
        "חיבור usb": "usb_ports",
        "יציאות usb": "usb_ports",
        "usb type-c": USB_COUNT_PREFIX + "USB-C",
        "usb type c": USB_COUNT_PREFIX + "USB-C",
        "usb 3.2": USB_COUNT_PREFIX + "USB 3.2",
        "usb 3.0": USB_COUNT_PREFIX + "USB 3.0",
        "usb 2.0": USB_COUNT_PREFIX + "USB 2.0",
        "מחברי usb 2.0": "usb2_headers",
        "מחברי usb 3.2 gen1": "usb32_gen1_headers",
        "מחברי usb 3.2 gen2": "usb32_gen2_headers",
        "מחברי מאווררים": "fan_headers",
        "חריצי הרחבה": "expansion_slots",
        "חיבור גרפי": "onboard_video",
        "יציאות תצוגה": "onboard_video",
        "אלחוטי": "wireless",
        "כרטיס רשת אלחוטי": "wireless",
        "חיבורי חשמל": "power_connections",
        "גובה קירור מקסימלי": "max_cooler_height_mm",
        "תמיכת ecc": "ecc_support",
        "שלבי vrm": "vrm_phases",
        "bios": "bios",
        "זיכרון מקסימלי": "memory_max_gb",
        "מהירות זכרון": "memory_speeds",
        "מהירויות זכרון": "memory_speeds",
    },
    "memory": {
        "סוג זכרון": "memory_type",
        "גודל זכרון (ram)": "total_gb",
        "גודל זכרון": "total_gb",
        "נפח כולל": "total_gb",
        "קיבולת": "total_gb",
        "ערכת זיכרון": MEMORY_KIT,
        "ערכת זכרון": MEMORY_KIT,
        "ערכה": MEMORY_KIT,
        "מהירות זכרון (max)": "speed_mhz",
        "מהירות זכרון": "speed_mhz",
        "מהירות (mhz)": "speed_mhz",
        "מהירות": "speed_mhz",
        "זמן איחזור": "cas_latency",
        "cas latency": "cas_latency",
        "תזמונים": "timing",
        "מתח זכרון": "voltage_v",
        "מתח": "voltage_v",
        "ecc": "ecc",
        "registered": "registered",
        "באפר": "registered",
        "גוף קירור": "heat_spreader",
        "פורמט": "form_factor",
        "סוג תאורה": "lighting",
    },
    "storage": {
        "נפח דיסק": "capacity_gb",
        "נפח": "capacity_gb",
        "קיבולת": "capacity_gb",
        "סוג דיסק": "form_factor",
        "פורמט": "form_factor",
        "סוג כונן": "type",
        "מהירות דיסק": "rpm",
        "סל\u05f4ד": "rpm",
        "באפר": "cache_mb",
        "מטמון": "cache_mb",
        "סוג חיבור - ממשק": "interface",
        "סוג חיבור": "interface",
        "ממשק": "interface",
        "סדרת hdd": "model",
        "סוג nand": "nand",
        "nand": "nand",
        "בקר": "controller",
        "דור pcie": "pcie_gen",
        "nvme": "nvme",
    },
    "psu": {
        "הספק": "wattage_w",
        "הספק (w)": "wattage_w",
        "יעילות": "efficiency",
        "נצילות": "efficiency",
        "מודולרי": "modular",
        "תצורת ספק": "type",
        "קבוצת הספק": "wattage_w",
        "אורך": "length_mm",
        "ללא מאוורר": "fanless",
        "תקן atx": "atx_version",
        "חיבורי pcie": "pcie_power_connectors",
        # Plonter PSU labels (English, hyphenated exactly as printed). The
        # certificate rows carry the 80 PLUS tier inside a parenthetical blob;
        # canon_efficiency extracts the tier.
        "certificates": "efficiency",
        "certification": "efficiency",
        "certifications": "efficiency",
        "80 plus certification": "efficiency",
        "certificates-according to manufacturer": "efficiency",
        "certificates-loud 80 plus": "efficiency",
        "cable-management": "modular",
        "shape-factor": "type",
        "sata": "sata_connectors",
        "ide": "molex4_connectors",
        "molex": "molex4_connectors",
        "20/24-pin": "atx4_connectors",
        "24-pin": "atx4_connectors",
        "4/8-pin atx12v": "eps8_connectors",
        "eps": "eps8_connectors",
        "eps12v": "eps8_connectors",
        "cpu power": "eps8_connectors",
        "6/8-pin pcie": "pcie62_connectors",
        "8-pin pcie": "pcie8_connectors",
        "pcie 8-pin": "pcie8_connectors",
        "6-pin pcie": "pcie6_connectors",
        "pcie 6-pin": "pcie6_connectors",
        "12vhpwr": "pcie12_connectors",
        "12v-2x6": "pcie16_connectors",
        "16-pin": "pcie16_connectors",
    },
    "case": {
        "סוג": "type",
        "תצורה": "type",
        "סוג מארז": "type",
        "פאנל צד": "side_panel",
        "ספק כוח כלול": "psu_included",
        "כיסוי ספק כוח": "psu_shroud",
        "תמיכת לוחות אם": "mb_form_factors",
        "תאימות ללוח אם": "mb_form_factors",
        "פורמטים נתמכים": "mb_form_factors",
        "אורך gpu מקסימלי": "max_gpu_length_mm",
        "גובה קירור מקסימלי": "max_cooler_height_mm",
        "גובה מקסימלי קירור למעבד": "max_cooler_height_mm",
        "תאי 3.5": "drive_bays_35",
        "תאי 2.5": "drive_bays_25",
        "hard drive 3.5": "drive_bays_35",
        "hard drive 2.5": "drive_bays_25",
        "יציאות קדמיות": "front_usb",
        "חריצי הרחבה": "expansion_slots",
        "usb קדמי": "front_usb",
        "תמיכת מאווררים": "fan_support",
        "תמיכת רדיאטורים": "radiator_support",
        "ממדים": "dimensions_mm",
        "מימדים": "dimensions_mm",
        "מידות": "dimensions_mm",
        "נפח": "volume_l",
        "משקל": "weight_kg",
        "מאווררים קדמיים": "fan_front",
        "מאווררים עליונים": "fan_top",
        "מאוורר אחורי": "fan_rear",
        "מאווררים תחתונים": "fan_bottom",
    },
    "cooler_air": {
        "גודל מאוורר": "fan_size_mm",
        "גודל רדיאטור": "radiator_size_mm",
        "מספר מאווררים": "fan_count",
        "סל\u05f4ד": RPM_RANGE,
        "מהירות מאוורר": RPM_RANGE,
        "רעש": "noise_db",
        "ספיקת אוויר": "airflow_cfm",
        "גובה": "height_mm",
        "סוקטים": "sockets",
        "תושבת": "sockets",
        "פיזור חום": "tdp_w",
        "קירור נוזלי": "water_cooled",
        "ללא מאוורר": "fanless",
    },
    "case_fan": {
        "גודל": "size_mm",
        "גודל מאוורר": "size_mm",
        "כמות בחבילה": "quantity",
        "כיוון זרימה": "flow_direction",
        "סל\u05f4ד": RPM_RANGE,
        "מהירות מאוורר": RPM_RANGE,
        "ספיקת אוויר": "airflow_cfm",
        "רעש": "noise_db",
        "לחץ סטטי": "static_pressure_mmh2o",
        "pwm": "pwm",
        "מחבר": "connector",
        "סוג תאורה": "led",
        "תאורה": "led",
    },
}

# Coolers share one schema across aio / cooler_air / cooling_other.
_CATEGORY_RAW["aio"] = {
    **_CATEGORY_RAW["cooler_air"],
    "גודל רדיאטור": "radiator_size_mm",
    "סוג קירור": "water_cooled",
}
_CATEGORY_RAW["cooling_other"] = dict(_CATEGORY_RAW["cooler_air"])

# English hints vendors append in parentheses to a Hebrew label ("ליבות
# (Cores)"), carried over from the pre-overhaul table so Ivory keeps working.
_HINT_RAW = {
    "cores": "core_count",
    "threads": "thread_count",
    "clock": CLOCK_RANGE,
    "cache": CACHE_TIER,
    "socket": "socket",
    "brand": "manufacturer",
    "model": "model",
    "packing": "packaging",
    "packaging": "packaging",
    "chipset": "chipset",
    "memory": "memory_gb",
    "speed": "speed_mhz",
}

# A resolved field that this category does not have falls back to a broader
# field when one carries the same fact (only `series` -> `model` today: a memory
# kit's "סדרה" is its model, and memory has no `series` field).
_FIELD_FALLBACKS = {"series": "model"}

COMMON_LABELS: dict[str, str] = {normalize_label(k): v for k, v in _COMMON_RAW.items()}
CATEGORY_LABELS: dict[str, dict[str, str]] = {
    cat: {normalize_label(k): v for k, v in table.items()}
    for cat, table in _CATEGORY_RAW.items()
}
HINT_ALIASES: dict[str, str] = {normalize_label(k): v for k, v in _HINT_RAW.items()}

# --------------------------------------------------------------------------
# Hebrew values
# --------------------------------------------------------------------------

_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_MOJIBAKE_RE = re.compile(r"[\ufffd\u05f3]")
# Ivory promo copy / Plonter nav junk — never a spec value (pre-existing guard).
_PROMO_RE = re.compile(r"לחץ/י|לרכישה|מומלץ|לקרר|מבצע|₪")
_ANY_ALNUM_RE = re.compile(r"[0-9A-Za-z]")

# Hebrew words that carry the unit or the noun the field name already declares
# ("128 ליבות" -> 128 cores). Removing them is not interpretation: the field
# declares the unit, so the word is noise.
_UNIT_WORDS = frozenset({
    "ליבות", "ליבה", "נימים", "נימה", "מאווררים", "מאוורר", "ערוצים", "ערוץ",
    "פינים", "פין", "תדר", "תדרים", "מהירות", "נפח", "קיבולת", "זיכרון",
    "זכרון", "כונן", "דיסק", "סל\u05f4ד", "סל\"ד", "שבבים", "חריצים", "יציאות",
    "מחברים", "חיבורים", "יחידות", "ליטר", "משקל", "גובה", "אורך", "רוחב",
})

# Hebrew words that mean "no X" / "yes". Mapped to the canonical English
# spelling the rest of the pipeline already uses ("no" on a CPU's
# integrated_graphics, "yes"/"no" on a boolean field).
_HE_VALUE_WORDS = {
    "ללא": "no",
    "אין": "no",
    "לא": "no",
    "כן": "yes",
    "יש": "yes",
    "רגיל": "standard",
    "הפוך": "reverse",
}
_FALSE_PREFIXES = ("ללא", "אין")
_GERESH_STRIP = str.maketrans({"׳": "", "״": "", "'": "", '"': ""})

# Vendor SKU / part-number rows on a *detail* page are the shop's own catalogue
# number, which is not the manufacturer part number (the listing spider and the
# reference index own that fact). Warranty rows are shop bookkeeping too (the
# importer's warranty, not a product spec). Ignoring them keeps them out of
# `specs` AND out of the label-gap report, where they drowned real evidence.
_IGNORED_LABELS = frozenset({
    normalize_label(label) for label in (
        "sku", "mpn", "part number", "part number (mpn)", "upc", "ean",
        "מק\u05f4ט", "מק\u05f4טים", "מקט", "מק\u05f4ט ספק", "ברקוד",
        "warranty", "warranty / importer", "warranty / warranty type",
        "אחריות", "תקופת אחריות", "אחריות יבואן",
    )
})


def is_ignored_label(label) -> bool:
    """True for detail rows that are shop bookkeeping, never a product spec."""
    variants = _variants(label)
    return bool(variants) and variants[0] in _IGNORED_LABELS


def clean_detail_value(value) -> str | None:
    """Machine-readable form of one vendor detail value, or None to drop it.

    - Hebrew color/boolean words are translated (`canon.HE_COLOR_WORDS` is the
      shared table; canon then canonicalizes the English form).
    - Hebrew unit/noun words are removed ("128 ליבות" -> "128").
    - Anything still carrying Hebrew afterwards returns None: a phrase like
      "לא תואם AM5" would invert its meaning if we kept the token, so the whole
      value is dropped instead of half-read. Mojibake and promo copy likewise.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    if _MOJIBAKE_RE.search(text) or _PROMO_RE.search(text):
        return None

    # "ללא מעבד גרפי" / "ללא מאוורר" -> "no"
    for prefix in _FALSE_PREFIXES:
        if text.startswith(prefix):
            return "no"

    out: list[str] = []
    for word in text.split(" "):
        bare = word.translate(_GERESH_STRIP)
        low = bare.lower()
        color = HE_COLOR_WORDS.get(bare)
        if color:
            out.append(color)
            continue
        if low in _HE_VALUE_WORDS:
            out.append(_HE_VALUE_WORDS[low])
            continue
        if bare in _UNIT_WORDS or low in _UNIT_WORDS:
            continue
        out.append(word)

    cleaned = re.sub(r"\s+", " ", " ".join(out)).strip(" ,;|")
    if not cleaned or _HEBREW_RE.search(cleaned):
        return None
    if not _ANY_ALNUM_RE.search(cleaned):
        return None
    return cleaned


# --------------------------------------------------------------------------
# Label lookup
# --------------------------------------------------------------------------

_SCHEMA_LABEL_INDEX_CACHE: dict[str, dict[str, str]] = {}


def _schema_label_index(category: str) -> dict[str, str]:
    """field.label_he / label_en -> field name, for one category."""
    cached = _SCHEMA_LABEL_INDEX_CACHE.get(category)
    if cached is None:
        index: dict[str, str] = {}
        for field in schema.fields_for(category):
            for label in (field.label_he, field.label_en):
                if label:
                    index.setdefault(normalize_label(label), field.name)
        cached = index
        _SCHEMA_LABEL_INDEX_CACHE[category] = cached
    return cached


def _resolve_field(category: str, name: str) -> str | None:
    """Keep only field names the category actually has (series -> model)."""
    fields = schema.field_map(category)
    if name in fields:
        return name
    fallback = _FIELD_FALLBACKS.get(name)
    if fallback and fallback in fields:
        return fallback
    return None


def translate_vendor_label(label, category: str | None = None) -> str | None:
    """Vendor detail label -> schema field name / action token / None.

    Resolution order, most specific first:
    1. curated category table (the vocabulary verified against real pages);
    2. curated common table;
    3. English parenthetical hint ("ליבות (Cores)" -> core_count);
    4. schema `label_he` / `label_en` exact match;
    5. nothing — a Hebrew label we cannot map is dropped (and reported as a
       coverage gap) rather than guessed at. Non-Hebrew labels pass through
       unchanged so vendor key spellings keep reaching schema alias lookup.
    """
    cat = category or ""
    for candidate in _variants(label):
        for table in (CATEGORY_LABELS.get(cat, {}), COMMON_LABELS, HINT_ALIASES):
            mapped = table.get(candidate)
            if mapped is None:
                continue
            if mapped in SPECIAL_TOKENS or mapped.startswith(USB_COUNT_PREFIX):
                return mapped
            resolved = _resolve_field(cat, mapped)
            if resolved:
                return resolved
        resolved = _schema_label_index(cat).get(candidate)
        if resolved:
            return resolved

    raw = str(label or "")
    if _HEBREW_RE.search(raw):
        return None
    return raw or None
