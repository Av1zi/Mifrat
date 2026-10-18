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

# Oct 2026 coverage pass: cells that carry a fact the vocabulary could not
# reach before. Each one is a *shape* problem, not a new fact — the schema
# field already exists, the vendor just prints it inside a prose cell
# ("4 חיבורי PCIe 6+2-pin", "גובה: 40 ס\"מ", "מאוורר אחד").
SOCKETS_CELL = "__sockets_cell__"          # cooler socket rows, unioned
FAN_SIZE = "__fan_size__"                  # "12 ס\"מ" / "120" -> fan_size_mm
AIO_RADIATOR_COUNT = "__aio_radiator_count__"  # "3" -> fan_count (+ aio size)
COOLING_MEDIUM = "__cooling_medium__"      # "קירור מים" -> water_cooled
FAN_RPM_CELL = "__fan_rpm_cell__"          # "400RPM ~ 1850RPM ±10%" / "עד 1500RPM"
DIMS_CELL = "__dims_cell__"                # case HxWxD / cooler "גובה: 155 מ\"מ"
LENGTH_MM_PREFIX = "__length_mm__:"        # + field: "31 ס\"מ" -> int mm
RADIATOR_SUPPORT = "__radiator_support__"  # "עליון: 120 / 240 מ\"מ" -> dict_int
DRIVE_BAYS = "__drive_bays__"              # "כונן אחד HDD (3.5\")" -> 35/25 counts
FRONT_IO = "__front_io__"                  # case front-panel port list -> front_usb
SIDE_WINDOW = "__side_window__"            # "כולל" -> side_panel
PSU_INCLUDED_CELL = "__psu_included__"     # case "ספק כח" cell -> psu_included
MB_FORM_FACTORS = "__mb_form_factors__"    # "Mini ITX Micro ATX" -> list
GPU_VRAM = "__gpu_vram__"                  # "12GB GDDR7" -> memory_gb + type
GPU_COOLING = "__gpu_cooling__"            # "צלעות קירור בלבד" -> cooling
MEMORY_SUPPORT = "__memory_support__"      # Ivory RAM cell -> 4 fields
CPU_SUPPORT = "__cpu_support__"            # Ivory CPU-family prose -> compact str
CPU_MEMORY_SUPPORT = "__cpu_memory_support__"  # CPU "expansion" cell -> max_memory_gb
STORAGE_SUPPORT = "__storage_support__"    # Ivory storage cell -> m2/sata/raid
USB_SUMMARY = "__usb_summary__"            # rear USB list -> usb_ports string
REAR_OUTPUTS = "__rear_outputs__"           # rear video ports -> onboard_video
INTERNAL_HEADERS = "__internal_headers__"  # internal header cell -> fan/usb headers
QUANTITY_WORDS = "__quantity_words__"      # "מאוורר אחד" / "3-Pack" -> quantity
THERMAL_DESIGN = "__thermal_design__"    # case "Front Fans 2x80x25mm" -> mounts
MEMORY_SPEEDS = "__memory_speeds__"      # support lists -> ["4800", "8200"]
EXPANSION_SLOTS = "__expansion_slots__"  # "8 … אופקיים…" -> 8 (Hebrew prose)
FAN_CONNECTOR = "__fan_connector__"        # "4pin PWM" -> connector
NAND_CELL = "__nand__"                     # "TLC | 3D/V NAND" -> nand
STORAGE_FORM_FACTOR = "__storage_form_factor__"  # "M.2 2280" only, never dims
INTERFACE_CONNECTIVITY = "__interface_connectivity__"  # 1PC grouped cell
NETWORK_CARD = "__network_card__"  # 1PC "Spec / Network Card" -> wifi vs LAN
PSU_CONN_STRING = "__psu_conn_string__"  # "350W with Power Connector 3x8-pin"
CONNECTOR_COUNT_PREFIX = "__connector_count__:"  # + PSU connector field name
SLOT_COUNT_PREFIX = "__slot_count__:"      # __slot_count__:x16 / :x1 (summed)
FAN_MOUNT_PREFIX = "__fan_mount_cell__:"   # + case fan field name

# Oct 2026 completeness pass: cells the vocabulary now reaches.
MEMORY_SPEED_GBPS = "__memory_speed_gbps__"   # "28Gbps" (bandwidth is GB/s)
MEMORY_BUS_BIT = "__memory_bus_bit__"         # "128bit" / "256bits"
RADIATOR_DIMS = "__radiator_dims__"           # "אורך: 403 מ\"מ רוחב: … עובי: 27"
PUMP_DIMS = "__pump_dims__"                   # "אורך: 69 … גובה: 76" / "124x120x28"
SPEED_MBS_PREFIX = "__speed_mbs__:"           # + read_speed_mbs / write_speed_mbs
CONNECTORS_CELL = "__connectors_cell__"       # cooler "חיבורים" prose -> list
PACKAGING_CELL = "__packaging_cell__"         # "Retail - קופסה" -> boxed
DISPLAY_COUNT = "__display_count__"           # "עד 4 מסכים" -> max_displays 4
GENERATION_CELL = "__generation__"            # "דור 14" / "Series 2" -> Gen N
WEIGHT_G = "__weight_g__"                    # mass cell -> grams ("32.7 גרם")
STORAGE_TYPE_CELL = "__storage_type_cell__"   # 1PC "Storage / Storage Type", per category

SPECIAL_TOKENS = frozenset({
    CLOCK_RANGE, CACHE_TIER, MEMORY_KIT, RPM_RANGE, GPU_DIMENSIONS,
    GPU_OUTPUTS, RAID, CONNECTIVITY_SPLIT,
    SOCKETS_CELL, FAN_SIZE, AIO_RADIATOR_COUNT, COOLING_MEDIUM, FAN_RPM_CELL,
    DIMS_CELL,
    RADIATOR_SUPPORT, DRIVE_BAYS, FRONT_IO,
    SIDE_WINDOW, PSU_INCLUDED_CELL, MB_FORM_FACTORS, GPU_VRAM, GPU_COOLING,
    MEMORY_SUPPORT, STORAGE_SUPPORT, USB_SUMMARY, REAR_OUTPUTS,
    CPU_SUPPORT, CPU_MEMORY_SUPPORT,
    INTERNAL_HEADERS, QUANTITY_WORDS, FAN_CONNECTOR, NAND_CELL,
    STORAGE_FORM_FACTOR, INTERFACE_CONNECTIVITY, NETWORK_CARD,
    PSU_CONN_STRING, THERMAL_DESIGN, MEMORY_SPEEDS, EXPANSION_SLOTS,
    MEMORY_SPEED_GBPS, MEMORY_BUS_BIT, RADIATOR_DIMS, PUMP_DIMS,
    CONNECTORS_CELL, PACKAGING_CELL, DISPLAY_COUNT,
    GENERATION_CELL, WEIGHT_G, STORAGE_TYPE_CELL,
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
    # English
    "brand": "manufacturer",
    "manufacturer": "manufacturer",
    "maker": "manufacturer",
    # 1PC's flattened brand row ("GPU / Graphics Card Model Brand:
    # ARKTEK"). Exact-matches before the relaxed subset rule can claim it
    # for the chip field via the shorter "Graphics Card Model" entry.
    "gpu / graphics card model brand": "manufacturer",
    "model": "model",
    "model name": "model",
    "memory type": "memory_type",
    "modular": "modular",
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
        # "אריזת Box ללא מאוורר למעבד" / "גרסת OEM Tray …" — the English word
        # is the fact; the surrounding Hebrew is the vendor's description.
        "אריזה": PACKAGING_CELL,
        "סדרת מעבד": "series",
        "סדרת המעבד": "series",
        "משפחת מעבדים": "series",
        # YahavPC prints the family as "processor type" — values are the
        # vendor's own family names ("Threadripper", "Ryzen 9", "Ultra 9"),
        # never a model, so this is the same fact as the rows above.
        "סוג מעבד": "series",
        # TMS/1PC print the lineup generation as its own row ("דור 14",
        # "Series 2", 69 rows). Hebrew value: the token reads the RAW cell and
        # canon_generation folds every spelling into "Gen N".
        "דור המעבד": GENERATION_CELL,
        # Oct 2026 completeness pass (Ivory, 113 rows): the chipsets this CPU
        # drops into — the actual "does it fit my board" answer.
        "תאימות ערכת שבבים": "chipset_support",
        "ארכיטקטורה": "microarchitecture",
        # "• תומך עד 192GB זכרון DDR5 • תומך PCI Express דור 5.0 • …" — the
        # only schema fact inside this cell is the supported memory capacity
        # (17 rows); the PCIe lanes it also names have no field.
        "אפשרויות הרחבה וקישוריות": CPU_MEMORY_SUPPORT,
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
        # 1PC's flattened twin of the row above ("GPU / Graphics Card
        # Model: Intel UHD Graphics 770"). Without this the schema-alias
        # suffix rule files it as `model` (it ends in "Model"), pooling
        # every chip that shares an iGPU under one junk pid.
        "gpu / graphics card model": "integrated_graphics",
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
        "ל2 cache": "l2_cache_mb",
        "l3 cache": "l3_cache_mb",
        # 1PC's redesigned storefront groups the chipsets this CPU runs
        # with under "hardware / Chipset" ("AMD B550", "Intel Z890", 13
        # rows) — the same fact Ivory's "תאימות ערכת שבבים" carries.
        "hardware / chipset": "chipset_support",
        # "Number of threads" spelled with the vendor's geresh-less plural.
        "מספר תהליכונים": "thread_count",
    },
    "gpu": {
        "אריזה": PACKAGING_CELL,
        "סוג קירור": GPU_COOLING,
        "נפח זכרון": GPU_VRAM,
        # 1PC grouped rows: Size/Capacity carry "8GB"/"16GB" (VRAM size),
        # type/Storage-Type carry "GDDR7" (VRAM type) or "512-bit" (bus
        # width). The bus width has a schema column since the Oct 2026
        # completeness pass, so the label goes through the cell router, which
        # keeps GPU_VRAM for the VRAM shapes and reads the bus for the third.
        "ram / ram size": GPU_VRAM,
        "ram / ram capacity": GPU_VRAM,
        "ram / ram type": GPU_VRAM,
        "storage / storage type": STORAGE_TYPE_CELL,
        "מהירות ליבה מקסימלית": "boost_clock_mhz",
        "יציאות תצוגה בכרטיס המסך": GPU_OUTPUTS,
        "מידות כרטיס מסך כ-": GPU_DIMENSIONS,
        "חיבורי ספק כח": "external_power",
        "spec / interface connectivity": INTERFACE_CONNECTIVITY,
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
        # YahavPC (Oct 2026) spells the card's outputs "display connections"
        # ("3X Display Port, HDMI", "4X Mini Display Port") — same fact as the
        # rows above.
        "חיבורי תצוגה": GPU_OUTPUTS,
        # ...and names the chip "graphics core" ("GeForce RTX 5090").
        "ליבה גראפית": "chipset",
        # Oct 2026 completeness pass. Two different facts sit under
        # near-identical labels (מהירות זכרון = the GDDR data rate,
        # רוחב פס זכרון = the bus width), so each gets its own cell parser:
        # the sibling rows also carry "224GB/s" and ancient "3200" clocks,
        # which a bare int mapping would have shipped as a data rate.
        "מהירות זכרון": MEMORY_SPEED_GBPS,
        "רוחב פס זכרון": MEMORY_BUS_BIT,
        "רוחב פס": MEMORY_BUS_BIT,
        "רוחב אפיק זכרון": MEMORY_BUS_BIT,
        # Ivory prints "עד 4 מסכים" (up to four screens) and TMS a bare
        # count; the cell reads the number in both.
        "כמות מסכים מקסימלית": DISPLAY_COUNT,
        "תמיכה מרבית במסכים": DISPLAY_COUNT,
        "גרסת directx": "directx",
        "גרסת opengl": "opengl",
        "רזולוציה מקסימלית": "max_resolution",
        "הספק מינימלי": "recommended_psu_w",
        "יצרן ליבה גראפית": "chip_manufacturer",
        "מספר מאווררים": "fan_count",
        "קירור": "cooling",
        # WINDFORCE marketing rows land here, not under סוג קירור.
        "עיצוב תרמי": GPU_COOLING,
        "חיבורי חשמל": "external_power",
        # Board spec sheets bury the connector in the PSU recommendation
        # ("350W with Power Connector 3x8-pin", "...Cable 12VHPWR").
        # The wattage half is a PSU recommendation, never chip power —
        # only the connector mentions are read (see PSU_CONN_STRING).
        "recommended psu": PSU_CONN_STRING,
        # Yahav/TMS spell the same recommendation in Hebrew
        # ("750W עם מחברי חשמל 1x16-פינים"); 1PC spells the neighbours in
        # English ("Bus Standard", "Memory Speed", "Maximum Display Support").
        "ספק כוח מומלץ": PSU_CONN_STRING,
        "bus standard": "interface",
        "hardware / socket": "interface",
        "memory speed": MEMORY_SPEED_GBPS,
        "maximum display support": DISPLAY_COUNT,
        "graphic engine": "chipset",
    },
    "motherboard": {
        "ערכת שבבים": "chipset",
        "שבב": "chipset",
        "צ'יפסט": "chipset",
        # 216 rows of Hebrew CPU-family prose -> cpu_support parser.
        "תמיכה במעבדים (CPU)": CPU_SUPPORT,
        # Ivory's generic "ממשק" row on a board names the drive interfaces
        # it exposes ("SATA III 6Gbps", "PCIe Gen 4.0"), not a graphics
        # interface — COMMON_LABELS sends it to `interface`, which no
        # motherboard schema owns, so it landed in label_gaps (16 rows).
        "ממשק": "storage_interface",
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
        "סלוטים ddr3": "memory_slots",
        "חריצי זיכרון": "memory_slots",
        "מספר חריצי זיכרון": "memory_slots",
        "pci-e x16": SLOT_COUNT_PREFIX + "x16",
        "pcie x16": SLOT_COUNT_PREFIX + "x16",
        "pci-e x16 (x4) slot": SLOT_COUNT_PREFIX + "x16",
        "pci-e x16 (x8) slot": SLOT_COUNT_PREFIX + "x16",
        "pci-e x16 slot": SLOT_COUNT_PREFIX + "x16",
        "חריצי pcie x16": SLOT_COUNT_PREFIX + "x16",
        "pci-e x1": SLOT_COUNT_PREFIX + "x1",
        "pcie x1": SLOT_COUNT_PREFIX + "x1",
        "חיבורי m.2 pcie": "m2_slots",
        "חריצי m.2": "m2_slots",
        "m.2": "m2_slots",
        "חיבורי sata3": "sata_ports",
        "חיבורי sata2": "sata_ports",
        "יציאות sata": "sata_ports",
        "sata": "sata_ports",
        "חיבור usb": "usb_ports",
        "יציאות usb": "usb_ports",
        "חיבורי usb": USB_SUMMARY,
        "חיבורים פנימיים בלוח האם": INTERNAL_HEADERS,
        "חיבורים בלוח האם (בגב המחשב)": REAR_OUTPUTS,
        "קישוריות wi-fi": "wireless",
        "כרטיס רשת קווי (lan)": "ethernet",
        "כרטיס קול": "audio",
        "גודל לוח": "form_factor",
        "תמיכה בזכרון (ram)": MEMORY_SUPPORT,
        "תמיכה באחסון": STORAGE_SUPPORT,
        "ram / ram capacity": "memory_max_gb",
        "spec / interface connectivity": INTERFACE_CONNECTIVITY,
        "spec / network card": NETWORK_CARD,
        "usb type-c": USB_COUNT_PREFIX + "USB-C",
        "usb type c": USB_COUNT_PREFIX + "USB-C",
        "usb 3.2": USB_COUNT_PREFIX + "USB 3.2",
        "usb 3.1": USB_COUNT_PREFIX + "USB 3.1",
        "usb 3.0": USB_COUNT_PREFIX + "USB 3.0",
        "usb 2.0": USB_COUNT_PREFIX + "USB 2.0",
        "מחברי usb 2.0": "usb2_headers",
        "מחברי usb 3.2 gen1": "usb32_gen1_headers",
        "מחברי usb 3.2 gen2": "usb32_gen2_headers",
        "מחברי מאווררים": "fan_headers",
        "חריצי הרחבה": "expansion_slots",
        "חיבור גרפי": "onboard_video",
        # TMS prints the board's graphics device here ("ASPEED AST2600 BMC",
        # "AMD Radeon Graphics") — that is the onboard video.
        "כרטיס מסך": "onboard_video",
        "יציאות תצוגה": "onboard_video",
        "אלחוטי": "wireless",
        "כרטיס רשת אלחוטי": "wireless",
        # Oct 2026 completeness pass (455 + 148 + 55 rows).
        "ממשק אחסון": "storage_interface",
        # 1PC's English twin of the row above ("M.2, SATA III", 79 rows). The
        # same English label prints a GPU's memory type ("GDDR6") on GPU
        # pages, so it goes through the per-category cell router instead of a
        # plain mapping.
        "storage / storage type": STORAGE_TYPE_CELL,
        # "Retail - קופסה" is one cell whose Hebrew gloss used to make
        # clean_detail_value drop the whole row (see PACKAGING_CELL).
        "אריזה": PACKAGING_CELL,
        "קישוריות bluetooth": "bluetooth",
        # The slot-count token carries the SLOT KIND (the emitter sums rows
        # per kind and the closing block emits the field), not a field name.
        "pci-e x4": SLOT_COUNT_PREFIX + "x4",
        # 1PC's "network card" cell is a radio, not a LAN: NETWORK_CARD routes
        # Wi-Fi to `wireless` and LAN to `ethernet`.
        "כרטיס רשת": NETWORK_CARD,
        "תמיכת ecc": "ecc_support",
        "bios": "bios",
        "זיכרון מקסימלי": "memory_max_gb",
        "מהירות זכרון": "memory_speeds",
        "מהירויות זכרון": "memory_speeds",
        # Long-tail support-list spellings ("1866,2133,…,4133",
        # "Dual Channel DDR5-7000MHz OC"). Bare 4-digit numbers are only
        # read inside these explicitly speeds-labeled cells — never prose.
        # NOTE: "תמיכה בזכרון (RAM)" is deliberately NOT here — it resolves
        # to MEMORY_SUPPORT (slots+type+max+speeds) via the relaxed path,
        # and an exact entry would shadow that richer parse.
        "מהירויות שעון זיכרון נתמכות": MEMORY_SPEEDS,
        "תמיכה בזיכרון": MEMORY_SPEEDS,
        "סלוטים ddr5": "memory_slots",
        "זיכרון (ram)": MEMORY_SPEEDS,
        # 1PC's redesigned storefront (Oct 2026) spells the same board rows
        # out in full ("תושבת המעבד" vs TMS's "תושבת מעבד", "ערכת שבבים של
        # לוח האם" vs "ערכת שבבים"). Values verified against the live pages.
        "תושבת המעבד": "socket",
        "ערכת שבבים של לוח האם": "chipset",
        "סוגי זיכרון נתמכים": "memory_type",
        "מספר חריצי m.2 (m)": "m2_slots",
        "מספר מחברי sata iii": "sata_ports",
        "סוג ממשק ethernet": "ethernet",
        # YahavPC (Oct 2026) prints the board's networking as one cell that
        # mixes radios ("Wi-Fi, Wired LAN, Bluetooth"), so it takes the same
        # per-radio router 1PC's "Spec / Network Card" uses rather than
        # landing whole in `ethernet` — a value carrying Bluetooth is a
        # wireless row and the validator rejects it as ethernet.
        "קישוריות": NETWORK_CARD,
        # ...and its display row as "display connections", which mixes real
        # video ports with USB-C/Thunderbolt ("2X USB Type C", "HDMI, 2x USB
        # 4.0"). REAR_OUTPUTS keeps only the video ports and drops the rest,
        # the same way the other vendors' rear-I/O cells are read.
        "חיבורי תצוגה": REAR_OUTPUTS,
        # ----- Fix-round P6 (Oct 2026): labels counted in the gap report
        # with real values behind them, verified against the raw pages. -----
        "תצורת לוח האם": "form_factor",
        "סוג bios": "bios",
        "שבב שמע": "audio",
        "בקר lan": "ethernet",
        "תמיכה ב-raid": RAID,
        "תמיכה ב raid": RAID,
        "רמות raid": RAID,
        "מצבי raid": RAID,
        "מחברי usb 3.2 gen 1": "usb32_gen1_headers",
        "מחברי usb 3.2 gen 2": "usb32_gen2_headers",
        "ממשקי כונני אחסון נתמכים": "storage_interface",
        "ממשקי כוננים נתמכים": "storage_interface",
        "מקסימום זכרון": "memory_max_gb",
        "זכרון מרבי נתמך": "memory_max_gb",
        "תאימות ecc": "ecc_support",
        # Values are the vendor's plain answer ("Yes"/"No") — honest either
        # way; "the board has no Wi-Fi" is a compatibility fact.
        "wi-fi": "wireless",
        "top wi-fi standard": "wireless",
        "תקן wi-fi מרבי": "wireless",
        "גרפיקה משולבת": "onboard_video",
        "יציאות וידאו": REAR_OUTPUTS,
        "חריצי ddr5": "memory_slots",
        "חריצי ddr4": "memory_slots",
        "חריצי ddr3": "memory_slots",
    },
    "memory": {
        # "Retail - קופסה" (52 rows) reaches canon_packaging only through the
        # cell parser — as a plain value it is dropped as Hebrew prose.
        "אריזה": PACKAGING_CELL,
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
        "תאימות ecc": "ecc",
        "באפר": "registered",
        "גוף קירור": "heat_spreader",
        "פורמט": "form_factor",
        "סוג תאורה": "lighting",
        "נפח": "total_gb",
        "סוג": "memory_type",
        "ram / ram size": MEMORY_KIT,
        "ram / ram capacity": "total_gb",
        "frequency": "speed_mhz",
        "memory frequency": "speed_mhz",
        # 1PC's redesigned storefront (Oct 2026): plain Hebrew spellings of
        # rows TMS already prints under other names ("מהירות זכרון (max)",
        # "זמן איחזור", "ערכת זיכרון"). Each maps to the same field.
        "נפח זיכרון": "total_gb",
        "תזמון cas": "cas_latency",
        "תצורת ערכה": MEMORY_KIT,
        "קצב העברת נתונים בזיכרון": "speed_mhz",
        "קצב נתונים מרבי": "speed_mhz",
        "מהירות זיכרון מרבית": "speed_mhz",
        # YahavPC (Oct 2026) prints a bare "memory" row holding the kit
        # capacity ("128GB"/"64GB"/"32GB") — the same fact as the rows above.
        "זיכרון": "total_gb",
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
        # Drive mass ("32.7 גרם", "98 grams", "כ-2.49 ק\"ג", 43 rows):
        # canon_weight_g reads the vendor's unit, grams or kilograms.
        "משקל": WEIGHT_G,
        "משקל המוצר": WEIGHT_G,
        "דור pcie": "pcie_gen",
        "pcie generation": "pcie_gen",
        "nvme": "nvme",
        "ממשק אחסון": "interface",
        # Oct 2026 completeness pass: sequential throughput + random IOPS, the
        # two rows every drive page prints (83 / 81 / 43 / 40 / 19 / 19 rows).
        "מהירות קריאה": SPEED_MBS_PREFIX + "read_speed_mbs",
        "מהירות קריאה מקסימלית": SPEED_MBS_PREFIX + "read_speed_mbs",
        "מהירות כתיבה": SPEED_MBS_PREFIX + "write_speed_mbs",
        "מהירות כתיבה מקסימלית": SPEED_MBS_PREFIX + "write_speed_mbs",
        "אריזה": PACKAGING_CELL,
        "storage memory": NAND_CELL,
        "זכרון מטמון": "cache_mb",
        "גודל פיזי": STORAGE_FORM_FACTOR,
        # YahavPC (Oct 2026) prints the drive's shape as a bare "size"
        # ("3.5\"", "2.5\"", "Form Factor 2280").
        "גודל": STORAGE_FORM_FACTOR,
        "spec / interface connectivity": INTERFACE_CONNECTIVITY,
        # 1PC's redesigned storefront (Oct 2026) prints its own storage rows;
        # values are already in schema units ("480GB", "SSD", "M.2 2280"),
        # which is why the capacity/type/form-factor trio is what these three
        # labels fill. The read/write-speed rows stay gaps: no schema field.
        "נפח אחסון": "capacity_gb",
        "גודל האחסון": "capacity_gb",
        "סוג האחסון": "type",
        "סוג אחסון": "type",
        "פקטור צורה": STORAGE_FORM_FACTOR,
        "גודל הפיזי של הכונן": STORAGE_FORM_FACTOR,
    },
    "psu": {
        "הספק": "wattage_w",
        "הספק (w)": "wattage_w",
        "יעילות": "efficiency",
        "נצילות": "efficiency",
        "מודולרי": "modular",
        "תצורת ספק": "type",
        # 'קבוצת הספק' is the *series* family range the page prints next to the
        # real row ("650W - 1100W" on a 700W unit), not this product's rated
        # wattage. It used to map to wattage_w: because the series row comes
        # first in the vendor table, its low bound won the merge and 143
        # products shipped the family minimum (a 750W Antec displayed as 650W).
        # Oct 2026 completeness pass: the schema now HAS a column for it, so
        # the row is read there — never into `wattage_w` (194 rows).
        "קבוצת הספק": "series_wattage_range",
        "אורך": "length_mm",
        "ללא מאוורר": "fanless",
        "תקן atx": "atx_version",
        "חיבורי pcie": "pcie_power_connectors",
        "אריזה": PACKAGING_CELL,
        # Oct 2026 completeness pass: Yahav's watt row is this unit's real
        # rating (its case pages share the label but mean the included PSU,
        # which is where the case table maps it).
        "וואט / watt / אמפר": "wattage_w",
        "דרגת נצילות": "efficiency",
        "גודל מאוורר": FAN_SIZE,
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
        "חיבורי sata": "sata_connectors",
        "חיבור לכונן (sata)": CONNECTOR_COUNT_PREFIX + "sata_connectors",
        "חיבור לכונן (molex)": CONNECTOR_COUNT_PREFIX + "molex4_connectors",
        "eps 12v 8 pin": "eps8_connectors",
        "pci-e connectors 8 pin": "pcie8_connectors",
        "pci-e connectors 6 pin": "pcie6_connectors",
        "pci-e connectors 6+2 pin": "pcie62_connectors",
        "pci-e connectors 16 pin": "pcie16_connectors",
        "molex 4 pin": "molex4_connectors",
        "חיבורי 12vhpwr": "pcie12_connectors",
        "חיבור לכרטיס מסך (12vhpwr)": CONNECTOR_COUNT_PREFIX + "pcie12_connectors",
        "חיבור לכרטיס מסך (pcie)": CONNECTOR_COUNT_PREFIX + "pcie62_connectors",
        "חיבור למעבד (cpu)": CONNECTOR_COUNT_PREFIX + "eps8_connectors",
        "חיבור ללוח אם (atx)": CONNECTOR_COUNT_PREFIX + "atx4_connectors",
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
        # 1PC's combined label ("מודולרי / Modular", 76 rows in the gap
        # report) — the same fact as the bare "מודולרי" above, same canon.
        "מודולרי / modular": "modular",
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
        "תאימות קירור נוזלי (רדיאטור)": RADIATOR_SUPPORT,
        "תאימות לוח": MB_FORM_FACTORS,
        "תאימות ללוח": MB_FORM_FACTORS,
        "מספר חריצי הרחבה": EXPANSION_SLOTS,
        "גודל כרטיס מסך מקסימלי": LENGTH_MM_PREFIX + "max_gpu_length_mm",
        "מקסימום אורך כרטיס גרפי": LENGTH_MM_PREFIX + "max_gpu_length_mm",
        "גובה קירור למעבד מקסימלי": LENGTH_MM_PREFIX + "max_cooler_height_mm",
        "מידות כ-": DIMS_CELL,
        "מקום לכוננים": DRIVE_BAYS,
        # Oct 2026 completeness pass (case).
        "bays 5.25": "drive_bays_525",
        "rackmount": "rackmount",
        "מאוורר צד": FAN_MOUNT_PREFIX + "fan_side",
        "תמיכה בגודל רדיאטור ב mm": RADIATOR_SUPPORT,
        # 1PC grouped row ("2x 3.5\" + 1x 2.5\"") — same shape DRIVE_BAYS reads.
        "storage / storage capacity": DRIVE_BAYS,
        "חיבורים בקדמת המארז": FRONT_IO,
        "חלון צד": SIDE_WINDOW,
        "ספק כח": PSU_INCLUDED_CELL,
        # YahavPC (Oct 2026): the case's PSU slot as "watt / amp", printed
        # "ללא" when the case ships without a unit.
        "וואט / watt / אמפר": PSU_INCLUDED_CELL,
        # ...and the size class as "case size" ("Full Tower", "Mid Tower") —
        # the same value `סוג מארז` already puts in `type`.
        "גודל מארז": "type",
        # 1PC grouped front-panel USB ("USB 3.2, USB-C") -> front_usb.
        "spec / interface connectivity": INTERFACE_CONNECTIVITY,
        "מאוורר קידמי": FAN_MOUNT_PREFIX + "fan_front",
        "מאווררים קדמיים": FAN_MOUNT_PREFIX + "fan_front",
        "מאוורר עליון": FAN_MOUNT_PREFIX + "fan_top",
        "מאווררים עליונים": FAN_MOUNT_PREFIX + "fan_top",
        "מאוורר אחורי": FAN_MOUNT_PREFIX + "fan_rear",
        "מאוורר תחתון": FAN_MOUNT_PREFIX + "fan_bottom",
        "מאווררים תחתונים": FAN_MOUNT_PREFIX + "fan_bottom",
        # Thermal-design prose names positions in English ("Front Fans
        # 2x80x25mm", "Rear: 1x120") while the rows above carry the Hebrew
        # mount labels. Segments without a position word (dimensions,
        # "Fans Included", cooler brand lines) are skipped, never guessed.
        "עיצוב תרמי": THERMAL_DESIGN,
        "סוג תאורה": "lighting",
        "ממדים": "dimensions_mm",
        "מימדים": "dimensions_mm",
        "מידות": "dimensions_mm",
        "נפח": "volume_l",
        "משקל": "weight_kg",
        # 1PC's redesigned storefront (Oct 2026) prints the clearance rows as
        # "תמיכה ב... mm" with a bare millimetre number ("280", "155").
        "תמיכה בכרטיס מסך mm": "max_gpu_length_mm",
        "תמיכה בקירור למעבד mm": "max_cooler_height_mm",
        # ----- Fix-round P6 (Oct 2026): the new storefront's remaining
        # spellings, verified against the raw values ("Micro-ATX, Mini-ITX",
        # "3", "280x195x380", "עליון: 240/280 מ״מ"). -----
        "תמיכה בלוח אם": "mb_form_factors",
        "תמיכה בלוחות אם": "mb_form_factors",
        "משקל בקג": "weight_kg",
        "מידות ב mm": "dimensions_mm",
        "תמיכה ברדיאטור": RADIATOR_SUPPORT,
        "תמיכה ברדיאטורים": RADIATOR_SUPPORT,
    },
    "cooler_air": {
        "גודל מאוורר": "fan_size_mm",
        "גודל מאוורר כ-": FAN_SIZE,
        # YahavPC prints the cooler's fan as a bare "size" ("120MM").
        "גודל": "fan_size_mm",
        "גודל רדיאטור": "radiator_size_mm",
        # Oct 2026 completeness pass: Ivory's cooler cells.
        "חיבורים": CONNECTORS_CELL,
        "מידות משאבה": PUMP_DIMS,
        "מידות רדיאטור": RADIATOR_DIMS,
        "מספר מאווררים": "fan_count",
        "מאוורר מובנה (ממ)": FAN_SIZE,
        # Ivory prints Intel and AMD compatibility as two rows; the union is
        # the product's real socket list, so the rows are accumulated and
        # emitted once (a plain mapping would race them in the merge).
        "תושבת מעבד": SOCKETS_CELL,
        "תאימות תושבת intel": SOCKETS_CELL,
        "תאימות תושבת amd": SOCKETS_CELL,
        "תאימות תושבות intel": SOCKETS_CELL,
        "תאימות תושבות amd": SOCKETS_CELL,
        "סוקטים": SOCKETS_CELL,
        "הספק תרמי מירבי": "tdp_w",
        # 1PC's grouped cooler cell ("4PIN PWM", "iCUE LINK", "USB") is the
        # same wiring list the Hebrew "חיבורים" row feeds.
        "spec / interface connectivity": INTERFACE_CONNECTIVITY,
        "המלצה מקסימלית לקירור (tdp)": "tdp_w",
        "סוג תאורה": "lighting",
        "סוג קירור": COOLING_MEDIUM,
        "מהירות מקסימלית עד": FAN_RPM_CELL,
        "מידות כ-": DIMS_CELL,
        "סל\u05f4ד": RPM_RANGE,
        "מהירות מאוורר": RPM_RANGE,
        "רעש": "noise_db",
        "ספיקת אוויר": "airflow_cfm",
        # YahavPC prints the cooler's fan as a bare "size": "120MM".
        "גודל": "fan_size_mm",
        "גובה": "height_mm",
        "תושבת": SOCKETS_CELL,
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
        # 1PC names the fan's link/lighting in its grouped cell ("iCUE LINK",
        # "ARGB") — the router reads only those two facts.
        "spec / interface connectivity": INTERFACE_CONNECTIVITY,
        "סוג תאורה": "led",
        "גודל כ-": FAN_SIZE,
        "מהירות סיבוב": FAN_RPM_CELL,
        "מספר מאווררים": QUANTITY_WORDS,
        "סוג חיבור": FAN_CONNECTOR,
        "תאורה": "led",
        # The same cell the case table maps ("מאוורר מובנה (ממ)" = built-in
        # fan, mm), reached through case_fan's own table so a fan product's
        # detail page fills size_mm instead of landing in label_gaps.
        "מאוורר מובנה (ממ)": FAN_SIZE,
    },
}

# Coolers used to share one schema across aio / cooler_air / cooling_other;
# since the 2026-10-17 split each category drops the labels whose field it no
# longer has (check_tms_detail fails on a label that maps to a missing field):
# an air cooler has no radiator / water flag, an AIO no height / fanless flag,
# and the grab-bag category neither fanless nor pump/radiator dimensions.
_AIR_ONLY_DROP = ("גודל רדיאטור", "קירור נוזלי")
_AIO_DROP = ("גובה", "ללא מאוורר", "קירור נוזלי")
_OTHER_DROP = ("ללא מאוורר",)

_COOLER_AIR_FULL = _CATEGORY_RAW["cooler_air"]
_CATEGORY_RAW["cooler_air"] = {k: v for k, v in _COOLER_AIR_FULL.items()
                               if k not in _AIR_ONLY_DROP}
_CATEGORY_RAW["aio"] = {
    **{k: v for k, v in _COOLER_AIR_FULL.items() if k not in _AIO_DROP},
    "גודל רדיאטור": "radiator_size_mm",
    "רדיאטורים": AIO_RADIATOR_COUNT,
    "סוג קירור": COOLING_MEDIUM,
}
_CATEGORY_RAW["cooling_other"] = {k: v for k, v in _COOLER_AIR_FULL.items()
                                  if k not in _OTHER_DROP}

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
    "מאוורר", "משקל", "סלד", "סל״ד", "נימה", "מחברים", "נימים", "מהירות", "מאווררים", "דיסק",
    "ממ", "סמ", "מילימטר", "סנטימטר",
    "ליבות", "ליבה", "נימים", "נימה", "מאווררים", "מאוורר", "ערוצים", "ערוץ",
    "פינים", "פין", "תדר", "תדרים", "מהירות", "נפח", "קיבולת", "זיכרון",
    "זכרון", "כונן", "דיסק", "סל\u05f4ד", "סל\"ד", "שבבים", "חריצים", "יציאות",
    "מחברים", "חיבורים", "יחידות", "ליטר", "משקל", "גובה", "אורך", "רוחב",
})

# Hebrew words that mean "no X" / "yes". Mapped to the canonical English
# spelling the rest of the pipeline already uses ("no" on a CPU's
# integrated_graphics, "yes"/"no" on a boolean field).
_HE_VALUE_WORDS = {
    # "כולל" (included) is the Hebrew yes across the lighting / side-window /
    # PSU-included rows (506 lighting values alone). Without it every one of
    # those rows was dropped as Hebrew prose, because nothing else in the
    # value survived to make it a spec.
    "כולל": "yes",
    "ללא": "no",
    "אין": "no",
    "לא": "no",
    "כן": "yes",
    "יש": "yes",
    "רגיל": "standard",
    "הפוך": "reverse",
}
# False-by-prefix value openers ("ללא X" / "אין X" are never specs).
# English "without" joins them: the only values it opens anywhere on disk
# are five graphics-absence rows, mirroring the Hebrew twin exactly.
_FALSE_PREFIXES = ("ללא", "אין", "without")
_GERESH_STRIP = str.maketrans({"׳": "", "״": "", "'": "", '"': ""})

# Vendor SKU / part-number rows on a *detail* page are the shop's own catalogue
# number, which is not the manufacturer part number (the listing spider and the
# reference index own that fact). Warranty rows are shop bookkeeping too (the
# importer's warranty, not a product spec). Ignoring them keeps them out of
# `specs` AND out of the label-gap report, where they drowned real evidence.
#
# The Oct 2026 pass added the second block: pure housekeeping (`הערות` notes,
# `שונות` misc, box contents, 1PC's screen rows on a GPU) and container rows
# (`Spec / Specifications` is a section header, never a fact). Facts with no
# schema field stay OUT of this list on purpose — they are the evidence for
# the deferred schema candidates.
_IGNORED_LABELS = frozenset({
    normalize_label(label) for label in (
        "sku", "mpn", "part number", "part number (mpn)", "upc", "ean",
        "מק\u05f4ט", "מק\u05f4טים", "מקט", "מק\u05f4ט ספק", "ברקוד",
        "warranty", "warranty / importer", "warranty / warranty type",
        "אחריות", "תקופת אחריות", "אחריות יבואן",
        # housekeeping
        "הערות", "שונות", "תכולת האריזה", "נלווים באריזה", "מאפיינים",
        "באריזה", "אריזת",
        # no schema field, pure shop/vendor bookkeeping (never a spec fact):
        # PSU power-factor correction, case-fan bearing type, memory
        # XMP/EXPO profile. Row counts stay visible in git history; these
        # are recorded as deferred schema candidates in spec-coverage-plan.
        # ("עיצוב תרמי" left this list: case/gpu rows map to mount/cooling
        # tokens; other categories report it as a gap.)
        "pfc", "pfc פעיל", "active pfc",
        "מסב מאוורר",
        "פרופיל זיכרון",
        "דרישות ותאימות", "תוכנות ואפליקציות", "עמידות",
        "תצוגה ותאורה", "פאנל תצוגה (מסך)", "חיבור סיריאלי com",
        "spec / specifications", "spec / operating system",
        "spec / built-in speakers", "spec / designed for gaming",
        "screen / resolution", "screen / screen size", "screen / screen type",
        "screen / screen refresh rate", "product type",
        # ----- 1PC's redesigned storefront (Oct 2026) -----
        # Same categories as the block above, in the Hebrew spellings the new
        # pages use. The warranty pair is the importer's policy row ("יבואן
        # רשמי" / "CD-LOG" / "שלוש שנים"), the rest is shop bookkeeping. The
        # screen/OS/camera rows are the non-part facts the English ignores
        # already cover: 1PC files some complete systems under its storage
        # slot, and those pages print laptop facts no parts schema can hold
        # (they stay visible in git history as evidence of the miscategorised
        # listings — see decisions.md 2026-10-13).
        "נותן האחריות", "תקופת ותנאי האחריות", "סוג האחריות", "ספק יבואן",
        "סוג מוצר", "מוצרים נלווים", "כבלים כלולים", "מיועד לגיימינג",
        "product name", "intel xmp", "גרסת intel xmp",
        "מערכת הפעלה", "מסך", "גודל מסך באינצ'ים", "מצלמה", "מצלמת אינטרנט",
        # ----- YahavPC (Oct 2026) -----
        # "Warranty duration" — the same importer-policy row the other
        # vendors spell "תקופת אחריות"/"נותן האחריות". Values are plain
        # durations ("36 חודשים"), and no schema field carries one.
        "משך אחריות",
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

    # "ללא מעבד גרפי" / "ללא מאוורר" / "Without a graphics processor." -> "no"
    for prefix in _FALSE_PREFIXES:
        if text.lower().startswith(prefix):
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


# Token prefixes carry a parameter after the colon (the field they fill), so
# they are tested by prefix; plain tokens by membership.
_TOKEN_PREFIXES = (USB_COUNT_PREFIX, CONNECTOR_COUNT_PREFIX, SLOT_COUNT_PREFIX,
                   FAN_MOUNT_PREFIX, LENGTH_MM_PREFIX, SPEED_MBS_PREFIX)


def _is_token(value: str) -> bool:
    """True when a table value is an action token, not a field name."""
    return value in SPECIAL_TOKENS or value.startswith(_TOKEN_PREFIXES)


# Filler words an English vendor label may carry without changing its meaning.
# Stripping them lets the relaxed lookup see "PCI-E Connectors 8 pin" as the
# curated key "8-pin pcie".
_RELAXED_FILLER = frozenset({
    "connector", "connectors", "pin", "pins", "port", "ports", "count",
    "size", "version", "support", "supported", "max", "maximum",
    "external", "internal", "integrated", "type",
})
_RELAXED_ALIASES = (("pci-e", "pcie"), ("pci express", "pcie"), ("pci e", "pcie"),
                    ("wi-fi", "wifi"), ("wi fi", "wifi"))
_RELAXED_INDEX_CACHE: dict[tuple[str, frozenset], str] | None = None


def _relaxed_tokens(label) -> frozenset:
    text = normalize_label(label)
    for needle, replacement in _RELAXED_ALIASES:
        text = text.replace(needle, replacement)
    text = re.sub(r"(?<=\d)\s*-?\s*pin\b", "", text)
    text = re.sub(r"[^0-9a-z\u0590-\u05FF+]+", " ", text)
    return frozenset(t for t in text.split() if t not in _RELAXED_FILLER)


def _relaxed_index() -> dict[tuple[str, frozenset], str]:
    """(category, token set) -> field, built once from the curated tables."""
    global _RELAXED_INDEX_CACHE
    if _RELAXED_INDEX_CACHE is None:
        index: dict[tuple[str, frozenset], str] = {}
        for category, table in CATEGORY_LABELS.items():
            for key, value in table.items():
                if _is_token(value):
                    continue
                index.setdefault((category, _relaxed_tokens(key)), value)
        for key, value in COMMON_LABELS.items():
            index.setdefault(("*", _relaxed_tokens(key)), value)
        _RELAXED_INDEX_CACHE = index
    return _RELAXED_INDEX_CACHE


def _relaxed_lookup(category: str, label: str) -> str | None:
    """Token-subset match against the curated vocabulary (English only).

    Two guards keep this from inventing mappings: a curated key must be fully
    contained in the label's tokens and carry at least two tokens, and a tie
    between two different keys is refused — ambiguity means no mapping.

    A label containing a colon is a flattened "Label: value" pair (1PC's
    `Spec / Specifications` groups arrive as `key: "Disk type: M.2 2280
    (unpaired)"` with an empty value), not a label at all — matching the
    label half against the vocabulary would silently swallow the row (no
    fact AND no gap). Those stay gaps until the pair is split upstream.
    """
    if ":" in str(label or ""):
        return None
    tokens = _relaxed_tokens(label)
    if not tokens:
        return None
    index = _relaxed_index()
    exact = index.get((category, tokens)) or index.get(("*", tokens))
    if exact:
        return _resolve_field(category, exact)
    best_tokens = None
    best_field = None
    for (index_cat, key_tokens), field in index.items():
        if index_cat not in (category, "*") or not key_tokens:
            continue
        if not key_tokens <= tokens or len(key_tokens) < 2:
            continue
        if best_tokens is None or len(key_tokens) > len(best_tokens):
            best_tokens, best_field = key_tokens, field
        elif len(key_tokens) == len(best_tokens) and field != best_field:
            return None
    return _resolve_field(category, best_field) if best_field else None


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
            if _is_token(mapped):
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
    # English labels get one relaxed attempt: token-aware matching catches
    # vendor spellings the curated tables never saw ("PCI-E Connectors 8 pin"
    # for the key "8-pin pcie"), without guessing at Hebrew, which must be
    # curated explicitly.
    relaxed = _relaxed_lookup(cat, raw)
    if relaxed:
        return relaxed
    return raw or None
