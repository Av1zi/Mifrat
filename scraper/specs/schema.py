"""
specs/schema.py — the canonical, typed spec schema for every category.

This module is the SINGLE SOURCE OF TRUTH for spec field names. Nothing
downstream may invent a key: resolvers emit schema fields, the merge engine
merges schema fields, validators validate schema fields, the site renders
schema fields, and `python -m scraper.specs.export_site` generates the
frontend's types/labels/filter metadata from the same definition
(scripts/check_spec_sync.py fails CI on drift).

Design rules (see decisions.md "spec system overhaul"):
- Units live in the field name (`_ghz`, `_mhz`, `_mm`, `_w`, `_gb`, `_mb`,
  `_rpm`, `_db`, `_ns`, `_v`, `_cfm`, `_l`). Values are always BARE numbers
  in that unit — no "155 mm" strings anywhere past the resolver boundary.
- One product always carries the SAME key set for its category, with
  `null` for anything unknown. The frontend never discovers keys.
- `aliases` are legacy/vendor spellings of the SAME fact. They exist for two
  reasons: (1) mapping vendor detail keys onto schema fields, and (2)
  deriving the transitional `attributes` blob the filters/compat engine
  still read (scraper/specs/legacy.py). They are never promoted back into
  the product's `specs`.
- `filterable` + `group` drive the frontend filter rail and the PDP display
  order. No hand-maintained list in site/src/specs.ts anymore.
"""

from __future__ import annotations

from dataclasses import dataclass

# Value types a field may have. Keep this list in sync with
# values.py::coerce_value and the TS type mapping in export_site.py.
TYPES = ("int", "float", "bool", "str", "enum", "list_str", "dict_int")

# Display groups, in PDP render order.
GROUPS = (
    "identity",   # manufacturer/model/part numbers/type
    "core",       # cores, clocks, caches, chipsets, speeds
    "memory",     # capacity, memory type/slots/speed
    "storage",    # capacity/interface/pcie gen/rpm
    "power",      # wattage, efficiency, connectors, TDP
    "physical",   # dimensions, colors, materials, cooling
    "io",         # ports, headers, connectivity, wireless, outputs
    "other",      # everything else
)


@dataclass(frozen=True)
class FieldSpec:
    """One spec field. Frozen: the schema is data, never mutated at runtime."""

    name: str
    type: str
    unit: str | None = None
    enum: tuple[str, ...] = ()
    lo: float | None = None
    hi: float | None = None
    filterable: bool = False
    group: str = "other"
    aliases: tuple[str, ...] = ()
    label_he: str = ""
    label_en: str = ""

    def label(self, lang: str) -> str:
        return self.label_he if lang == "he" else self.label_en


def _f(
    name: str,
    type: str,
    *,
    unit: str | None = None,
    enum: tuple[str, ...] = (),
    lo: float | None = None,
    hi: float | None = None,
    filterable: bool = False,
    group: str = "other",
    aliases: tuple[str, ...] = (),
    he: str = "",
    en: str = "",
) -> FieldSpec:
    """Compact field constructor (keeps the tables below readable)."""
    assert type in TYPES, f"bad type {type!r} for {name}"
    assert group in GROUPS, f"bad group {group!r} for {name}"
    if type == "enum":
        assert enum, f"enum field {name} needs allowed values"
    return FieldSpec(
        name=name,
        type=type,
        unit=unit,
        enum=tuple(enum),
        lo=lo,
        hi=hi,
        filterable=filterable,
        group=group,
        aliases=tuple(aliases),
        label_he=he or name,
        label_en=en or name,
    )


# --------------------------------------------------------------------------
# Knowledge maps the schema owns (moved out of extractors.py)
# --------------------------------------------------------------------------

# chipset -> (socket, memory type). None = board-dependent: look at the title.
CHIPSET_INFO: dict[str, tuple[str | None, str | None]] = {
    # AMD AM4 / DDR4
    "A320": ("AM4", "DDR4"), "B350": ("AM4", "DDR4"), "X370": ("AM4", "DDR4"),
    "A520": ("AM4", "DDR4"), "B450": ("AM4", "DDR4"), "X470": ("AM4", "DDR4"),
    "B550": ("AM4", "DDR4"), "X570": ("AM4", "DDR4"), "X570S": ("AM4", "DDR4"),
    # AMD AM5 / DDR5
    "A620": ("AM5", "DDR5"), "B650": ("AM5", "DDR5"), "B650E": ("AM5", "DDR5"),
    "X670": ("AM5", "DDR5"), "X670E": ("AM5", "DDR5"), "X870": ("AM5", "DDR5"),
    "X870E": ("AM5", "DDR5"), "B840": ("AM5", "DDR5"), "B850": ("AM5", "DDR5"),
    # AMD sTR5 / WRX90
    "TRX50": ("sTR5", "DDR5"), "WRX90": ("sWRX8", "DDR5"),
    # Intel LGA1151 / DDR4
    "H110": ("LGA1151", "DDR4"), "B150": ("LGA1151", "DDR4"),
    "H170": ("LGA1151", "DDR4"), "Z170": ("LGA1151", "DDR4"),
    "B250": ("LGA1151", "DDR4"), "H270": ("LGA1151", "DDR4"),
    "Z270": ("LGA1151", "DDR4"), "H310": ("LGA1151", "DDR4"),
    "B360": ("LGA1151", "DDR4"), "H370": ("LGA1151", "DDR4"),
    "Z370": ("LGA1151", "DDR4"), "B365": ("LGA1151", "DDR4"),
    "Z390": ("LGA1151", "DDR4"),
    # Intel LGA1200 / DDR4
    "H410": ("LGA1200", "DDR4"), "B460": ("LGA1200", "DDR4"),
    "H470": ("LGA1200", "DDR4"), "Z490": ("LGA1200", "DDR4"),
    "W480": ("LGA1200", "DDR4"), "H510": ("LGA1200", "DDR4"),
    "B560": ("LGA1200", "DDR4"), "H570": ("LGA1200", "DDR4"),
    "Z590": ("LGA1200", "DDR4"),
    # Intel LGA1700 (DDR4 or DDR5 depending on the board)
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "H670": ("LGA1700", None),
    "Z690": ("LGA1700", None), "B760": ("LGA1700", None), "H770": ("LGA1700", None),
    "Z790": ("LGA1700", None), "W680": ("LGA1700", None),
    # Intel LGA1851 (DDR5 only)
    "H810": ("LGA1851", "DDR5"), "B860": ("LGA1851", "DDR5"),
    "Z890": ("LGA1851", "DDR5"),
    # HEDT / legacy
    "X99": ("LGA2011-v3", "DDR4"), "X299": ("LGA2066", "DDR4"),
    "X399": ("TR4", "DDR4"), "TRX40": ("sTRX4", "DDR4"),
    "C422": ("LGA2066", "DDR4"), "C621": ("LGA3647", "DDR4"),
    "W790": ("LGA4677", "DDR5"),
}

# Socket -> memory generation. Used by validate.py's cross-field checks and by
# the reference resolver's anchor cross-check (not as a spec source itself).
SOCKET_MEMORY: dict[str, str] = {
    "AM4": "DDR4", "AM5": "DDR5", "sTR5": "DDR5", "sWRX8": "DDR5",
    "TR4": "DDR4", "sTRX4": "DDR4",
    "LGA1151": "DDR4", "LGA1200": "DDR4", "LGA2066": "DDR4",
    "LGA2011": "DDR4", "LGA2011-v3": "DDR4", "LGA3647": "DDR4",
    "LGA1700": "DDR4",  # both flavours exist; a hint only
    "LGA1851": "DDR5", "LGA4677": "DDR5",
}

# Our category id -> PCPartPicker/dataset category slug(s) for Tier-0
# reference lookups. Categories missing here have no reference source.
CATEGORY_TO_PCPP: dict[str, tuple[str, ...]] = {
    "cpu": ("cpu",),
    "motherboard": ("motherboard",),
    "memory": ("memory",),
    "storage": ("internal-hard-drive",),
    "gpu": ("video-card",),
    "case": ("case",),
    "psu": ("power-supply",),
    "case_fan": ("case-fan",),
    "aio": ("cpu-cooler",),
    "cooler_air": ("cpu-cooler",),
}


# Shared alias groups (legacy/vendor spellings seen in the wild).
_BRAND = ("brand", "manufacturer", "maker", "vendor_brand")
_MODEL = ("model", "model_name")
_SOCKETS = ("socket", "cpu_socket", "sockets", "socket_compat", "socket_type",
            "hardware_socket", "processor_socket", "socket_support")

# --------------------------------------------------------------------------
# cpu
# --------------------------------------------------------------------------

CPU = (
    _f("manufacturer", "str", filterable=True, group="identity",
       aliases=_BRAND, he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn", "upc"),
       he="מק״טים", en="Part Numbers"),
    _f("series", "str", filterable=True, group="core",
       aliases=("series", "family"), he="סדרה", en="Series"),
    _f("microarchitecture", "str", filterable=True, group="core",
       aliases=("microarchitecture", "architecture"), he="ארכיטקטורה", en="Microarchitecture"),
    _f("core_family", "str", group="core", aliases=("core_family", "codename"),
       he="משפחת ליבות", en="Core Family"),
    _f("socket", "str", filterable=True, group="core", aliases=_SOCKETS,
       he="סוקט", en="Socket"),
    _f("core_count", "int", lo=1, hi=256, filterable=True, group="core",
       aliases=("cores", "core_count", "number_of_cores"), he="ליבות", en="Core Count"),
    _f("thread_count", "int", lo=1, hi=512, filterable=True, group="core",
       aliases=("threads", "thread_count"), he="נימים", en="Thread Count"),
    _f("base_clock_ghz", "float", lo=0.3, hi=8.0, group="core",
       aliases=("base_clock_ghz", "core_clock"), he="תדר בסיס (GHz)", en="Base Clock (GHz)"),
    _f("boost_clock_ghz", "float", lo=0.3, hi=8.0, group="core",
       aliases=("boost_clock_ghz", "boost_clock", "turbo_clock_ghz"),
       he="תדר מוגבר (GHz)", en="Boost Clock (GHz)"),
    _f("l2_cache_mb", "int", lo=1, hi=512, group="core", aliases=("l2_cache_mb", "l2_cache"),
       he="מטמון L2 (MB)", en="L2 Cache (MB)"),
    _f("l3_cache_mb", "int", lo=1, hi=2048, group="core", aliases=("l3_cache_mb", "l3_cache"),
       he="מטמון L3 (MB)", en="L3 Cache (MB)"),
    _f("tdp_w", "int", lo=3, hi=500, filterable=True, group="power",
       aliases=("tdp", "tdp_w", "power_consumption", "max_power", "rated_power",
                "total_power", "watt"),
       he="הספק (W)", en="TDP (W)"),
    _f("integrated_graphics", "str", filterable=True, group="other",
       aliases=("integrated_graphics", "graphics"), he="גרפיקה משולבת", en="Integrated Graphics"),
    _f("max_memory_gb", "int", lo=4, hi=8192, group="memory",
       aliases=("max_memory_gb", "max_memory", "maximum_memory"),
       he="זיכרון מקסימלי (GB)", en="Max Memory (GB)"),
    _f("ecc_support", "bool", filterable=True, group="memory",
       aliases=("ecc_support", "ecc"), he="תמיכת ECC", en="ECC Support"),
    _f("includes_cooler", "bool", filterable=True, group="physical",
       aliases=("cooler_included", "includes_cooler", "cooler"),
       he="כולל קירור", en="Includes Cooler"),
    _f("packaging", "enum", enum=("boxed", "tray", "bulk", "oem"), filterable=True,
       group="identity", aliases=("packaging", "box_type", "pack"), he="אריזה", en="Packaging"),
    _f("lithography_nm", "int", lo=2, hi=250, group="core",
       aliases=("lithography_nm", "manufacturing_process", "process_nm"),
       he="ליתוגרפיה (nm)", en="Lithography (nm)"),
    _f("smt", "bool", filterable=True, group="core", aliases=("smt", "hyperthreading"),
       he="SMT", en="SMT"),
    _f("unlocked", "bool", group="other", aliases=("unlocked", "overclock_support"),
       he="לא נעול", en="Unlocked"),
)

# --------------------------------------------------------------------------
# cpu_cooler — one schema for aio + cooler_air + cooling_other
# --------------------------------------------------------------------------

CPU_COOLER = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("water_cooled", "bool", filterable=True, group="physical",
       aliases=("water_cooled", "aio"), he="קירור נוזלי", en="Water Cooled"),
    _f("radiator_size_mm", "int", lo=60, hi=560, filterable=True, group="physical",
       aliases=("radiator_size_mm", "supported_radiator_mm", "radiator_mm", "size"),
       he="גודל רדיאטור (mm)", en="Radiator Size (mm)"),
    _f("fan_size_mm", "int", lo=40, hi=200, filterable=True, group="physical",
       aliases=("fan_size_mm", "fan_size"), he="גודל מאוורר (mm)", en="Fan Size (mm)"),
    _f("fan_count", "int", lo=0, hi=6, group="physical", aliases=("fan_count", "fans"),
       he="מספר מאווררים", en="Fan Count"),
    _f("fan_rpm_min", "int", lo=0, hi=6000, group="physical",
       aliases=("fan_rpm_min", "rpm_min", "fan_speed_min"), he="סל״ד מינימלי", en="Fan RPM Min"),
    _f("fan_rpm_max", "int", lo=0, hi=8000, group="physical",
       aliases=("fan_rpm_max", "rpm_max", "rpm", "fan_speed"), he="סל״ד מקסימלי", en="Fan RPM Max"),
    _f("noise_db", "float", lo=0, hi=80, group="physical",
       aliases=("noise_db", "noise_level"), he="רעש (dB)", en="Noise (dB)"),
    _f("airflow_cfm", "float", lo=0, hi=800, group="physical",
       aliases=("airflow_cfm", "airflow", "air_flow"), he="ספיקת אוויר (CFM)", en="Airflow (CFM)"),
    _f("height_mm", "int", lo=5, hi=300, group="physical",
       aliases=("height_mm", "cooler_height_mm"), he="גובה (mm)", en="Height (mm)"),
    _f("sockets", "list_str", filterable=True, group="io",
       aliases=("sockets", "socket_compat", "socket"), he="סוקטים נתמכים", en="Sockets"),
    _f("tdp_w", "int", lo=10, hi=1000, group="power",
       aliases=("tdp_w", "tdp", "cooling_capacity_w"), he="פיזור חום (W)", en="Cooling Capacity (W)"),
    _f("fanless", "bool", filterable=True, group="physical", aliases=("fanless",),
       he="ללא מאוורר", en="Fanless"),
    _f("lighting", "str", filterable=True, group="physical",
       aliases=("lighting", "led"), he="תאורה", en="Lighting"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# motherboard
# --------------------------------------------------------------------------

MOTHERBOARD = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("socket", "str", filterable=True, group="core", aliases=_SOCKETS,
       he="סוקט", en="Socket"),
    _f("chipset", "str", filterable=True, group="core",
       aliases=("chipset", "cpu_model", "northbridge"), he="ערכת שבבים", en="Chipset"),
    _f("form_factor", "enum", enum=("ATX", "EATX", "Micro-ATX", "Mini-ITX", "XL-ATX",
                                    "Mini-DTX", "Thin Mini-ITX", "SSI-EEB"),
       filterable=True, group="physical",
       aliases=("form_factor", "motherboard_form_factor", "board_form_factor",
                "spec_form_factor", "motherboard_size", "board_size", "format"),
       he="פורמט", en="Form Factor"),
    _f("memory_type", "enum", enum=("DDR3", "DDR4", "DDR5"), filterable=True, group="memory",
       aliases=("memory_type", "memory_support", "ram_type"), he="סוג זיכרון", en="Memory Type"),
    _f("memory_slots", "int", lo=1, hi=32, filterable=True, group="memory",
       aliases=("memory_slots", "slots", "dimm_slots"), he="חריצי זיכרון", en="Memory Slots"),
    _f("memory_max_gb", "int", lo=4, hi=8192, group="memory",
       aliases=("memory_max_gb", "memory_max", "max_memory", "internal_memory_capacity"),
       he="זיכרון מקסימלי (GB)", en="Max Memory (GB)"),
    _f("memory_speeds", "list_str", group="memory",
       aliases=("memory_speeds", "memory_speed_oc", "memory_speed", "supported_memory_speed"),
       he="מהירויות זיכרון", en="Memory Speeds"),
    _f("pcie_x16_slots", "int", lo=0, hi=8, group="io", aliases=("pcie_x16_slots",),
       he="חריצי PCIe x16", en="PCIe x16 Slots"),
    _f("pcie_x1_slots", "int", lo=0, hi=8, group="io", aliases=("pcie_x1_slots",),
       he="חריצי PCIe x1", en="PCIe x1 Slots"),
    _f("m2_slots", "list_str", group="io",
       aliases=("m2_slots", "m_2_slots", "m2_slot_details", "m_2_slot_details"),
       he="חריצי M.2", en="M.2 Slots"),
    _f("sata_ports", "int", lo=0, hi=24, group="io", aliases=("sata_ports", "sata_connections"),
       he="יציאות SATA", en="SATA Ports"),
    _f("ethernet", "str", filterable=True, group="io",
       aliases=("lan", "ethernet", "network", "spec_network_card"),
       he="רשת", en="Ethernet"),
    _f("onboard_video", "str", group="io",
       aliases=("onboard_video", "video_outputs", "display_outputs", "graphics_output"),
       he="יציאות תצוגה", en="Onboard Video"),
    _f("wireless", "str", filterable=True, group="io",
       aliases=("wifi", "wifi_standard", "wireless", "wireless_std", "spec_wireless"),
       he="אלחוטי", en="Wireless"),
    _f("ecc_support", "bool", filterable=True, group="memory",
       aliases=("ecc_support", "ecc"), he="תמיכת ECC", en="ECC Support"),
    _f("raid_support", "bool", group="storage", aliases=("raid_support", "raid_level", "raid"),
       he="תמיכת RAID", en="RAID Support"),
    _f("back_connect", "bool", group="io", aliases=("back_connect",),
       he="Back-Connect", en="Back-Connect"),
    _f("usb2_headers", "int", lo=0, hi=6, group="io", aliases=("usb2_headers", "usb_headers"),
       he="מחברי USB 2.0", en="USB 2.0 Headers"),
    _f("usb32_gen1_headers", "int", lo=0, hi=6, group="io", aliases=("usb32_gen1_headers",),
       he="מחברי USB 3.2 Gen1", en="USB 3.2 Gen1 Headers"),
    _f("usb32_gen2_headers", "int", lo=0, hi=6, group="io", aliases=("usb32_gen2_headers",),
       he="מחברי USB 3.2 Gen2", en="USB 3.2 Gen2 Headers"),
    _f("usb_ports", "str", group="io", aliases=("usb_ports", "usb_a_ports", "usb_c_ports"),
       he="יציאות USB", en="Rear USB Ports"),
    _f("fan_headers", "int", lo=0, hi=16, group="io", aliases=("fan_headers",),
       he="מחברי מאווררים", en="Fan Headers"),
    _f("audio", "str", group="io", aliases=("audio", "audio_chip"), he="שמע", en="Audio"),
    _f("expansion_slots", "str", group="io", aliases=("expansion_slots",),
       he="חריצי הרחבה", en="Expansion Slots"),
    _f("vrm_phases", "str", group="other", aliases=("vrm_phases",),
       he="שלבֵי VRM", en="VRM Phases"),
    _f("bios", "str", group="other", aliases=("bios",), he="BIOS", en="BIOS"),
    _f("power_connections", "str", group="power", aliases=("power_connections",),
       he="חיבורי חשמל", en="Power Connections"),
    _f("max_cooler_height_mm", "int", lo=10, hi=300, group="physical",
       aliases=("max_cooler_height_mm",), he="גובה קירור מקסימלי (mm)", en="Max Cooler Height (mm)"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------

MEMORY = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("memory_type", "enum", enum=("DDR3", "DDR4", "DDR5"), filterable=True, group="core",
       aliases=("memory_type", "ram_type", "memory_support"), he="סוג זיכרון", en="Memory Type"),
    _f("speed", "str", group="core", aliases=("speed", "memory_speed"),
       he="מהירות", en="Speed"),
    _f("speed_mhz", "int", lo=800, hi=12000, filterable=True, group="core",
       aliases=("speed_mhz", "speed_rating_mhz", "speed_rating", "memory_speed_mhz"),
       he="מהירות (MHz)", en="Speed (MHz)"),
    _f("form_factor", "str", filterable=True, group="physical",
       aliases=("form_factor", "dimm_type", "memory_form_factor"),
       he="פורמט", en="Form Factor"),
    _f("module_count", "int", lo=1, hi=16, filterable=True, group="memory",
       aliases=("module_count", "modules", "modules_count", "number_of_modules"),
       he="מספר מודולים", en="Module Count"),
    _f("module_size_gb", "int", lo=1, hi=256, group="memory",
       aliases=("module_size_gb", "module_capacity_gb"), he="גודל מודול (GB)", en="Module Size (GB)"),
    _f("total_gb", "int", lo=1, hi=2048, filterable=True, group="memory",
       aliases=("total_gb", "capacity_gb", "capacity", "kit"), he="נפח כולל (GB)", en="Total (GB)"),
    _f("first_word_latency_ns", "float", lo=1, hi=60, group="core",
       aliases=("first_word_latency_ns", "first_word_latency"), he="השהיה (ns)", en="Latency (ns)"),
    _f("cas_latency", "int", lo=5, hi=60, filterable=True, group="core",
       aliases=("cas_latency", "cas", "cl"), he="CAS Latency", en="CAS Latency"),
    _f("timing", "str", group="core", aliases=("timing", "timings", "memory_timings"),
       he="תזמונים", en="Timings"),
    _f("voltage_v", "float", lo=0.8, hi=2.5, group="power",
       aliases=("voltage_v", "voltage", "memory_voltage"), he="מתח (V)", en="Voltage (V)"),
    _f("ecc", "bool", filterable=True, group="memory", aliases=("ecc", "ecc_support"),
       he="ECC", en="ECC"),
    _f("registered", "bool", group="memory", aliases=("registered", "ecc_registered", "buffered"),
       he="Registered", en="Registered"),
    _f("heat_spreader", "bool", group="physical", aliases=("heat_spreader", "heatsink"),
       he="גוף קירור", en="Heat Spreader"),
    _f("lighting", "str", filterable=True, group="physical", aliases=("lighting", "rgb_lighting"),
       he="תאורה", en="Lighting"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

STORAGE = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("capacity_gb", "int", lo=1, hi=30000, filterable=True, group="storage",
       aliases=("capacity_gb", "capacity", "drive_capacity", "total_capacity_gb"),
       he="נפח (GB)", en="Capacity (GB)"),
    _f("type", "enum", enum=("SSD", "HDD", "Hybrid"), filterable=True, group="storage",
       aliases=("type", "drive_type"), he="סוג כונן", en="Type"),
    _f("form_factor", "str", filterable=True, group="storage",
       aliases=("form_factor", "drive_form_factor", "storage_form_factor"),
       he="פורמט", en="Form Factor"),
    _f("interface", "str", filterable=True, group="storage",
       aliases=("interface", "connection_interface"), he="ממשק", en="Interface"),
    _f("nvme", "bool", filterable=True, group="storage", aliases=("nvme", "nvme_flag"),
       he="NVMe", en="NVMe"),
    _f("pcie_gen", "int", lo=1, hi=6, filterable=True, group="storage",
       aliases=("pcie_gen",), he="דור PCIe", en="PCIe Gen"),
    _f("cache_mb", "int", lo=0, hi=16384, group="storage", aliases=("cache_mb", "cache", "dram_cache"),
       he="מטמון (MB)", en="Cache (MB)"),
    _f("rpm", "int", lo=0, hi=20000, filterable=True, group="storage",
       aliases=("rpm", "spindle_speed"), he="סל״ד", en="RPM"),
    _f("nand", "str", group="storage", aliases=("nand", "nand_type"), he="סוג NAND", en="NAND"),
    _f("controller", "str", group="storage", aliases=("controller",), he="בקר", en="Controller"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# gpu
# --------------------------------------------------------------------------

GPU = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("chipset", "str", filterable=True, group="core",
       aliases=("chipset", "gpu_chip", "gpu_chipset", "graphics_processor"),
       he="שבב גרפי", en="Chipset"),
    _f("memory_gb", "int", lo=1, hi=128, filterable=True, group="memory",
       aliases=("memory_gb", "vram_gb", "memory", "video_memory"), he="זיכרון (GB)", en="Memory (GB)"),
    _f("memory_type", "str", group="memory", aliases=("memory_type", "vram_type", "gddr"),
       he="סוג זיכרון", en="Memory Type"),
    _f("core_clock_mhz", "int", lo=100, hi=4000, group="core",
       aliases=("core_clock_mhz", "core_clock", "base_clock_mhz"),
       he="תדר ליבה (MHz)", en="Core Clock (MHz)"),
    _f("boost_clock_mhz", "int", lo=100, hi=6000, group="core",
       aliases=("boost_clock_mhz", "boost_clock"), he="תדר מוגבר (MHz)", en="Boost Clock (MHz)"),
    _f("interface", "str", filterable=True, group="core",
       aliases=("interface", "bus_interface"), he="ממשק", en="Interface"),
    _f("length_mm", "int", lo=50, hi=500, group="physical",
       aliases=("length_mm", "gpu_length_mm", "card_length_mm"), he="אורך (mm)", en="Length (mm)"),
    _f("slot_width", "float", lo=0.5, hi=6.0, group="physical", aliases=("slot_width",),
       he="רוחב חריצים", en="Slot Width"),
    _f("tdp_w", "int", lo=10, hi=1000, group="power", aliases=("tdp_w", "tdp", "power_consumption"),
       he="הספק (W)", en="TDP (W)"),
    _f("cooling", "str", filterable=True, group="physical",
       aliases=("cooling", "cooler_type"), he="קירור", en="Cooling"),
    _f("fan_count", "int", lo=0, hi=6, group="physical", aliases=("fan_count", "fans"),
       he="מספר מאווררים", en="Fan Count"),
    _f("external_power", "list_str", group="power",
       aliases=("external_power", "power_connections", "power_connectors"),
       he="חיבורי חשמל", en="External Power"),
    _f("dp_outputs", "dict_int", group="io", aliases=("dp_outputs", "displayport_ports", "dp_ports"),
       he="יציאות DisplayPort", en="DisplayPort Outputs"),
    _f("hdmi_outputs", "dict_int", group="io", aliases=("hdmi_outputs", "hdmi_ports"),
       he="יציאות HDMI", en="HDMI Outputs"),
    _f("dvi_outputs", "dict_int", group="io", aliases=("dvi_outputs", "dvi_ports"),
       he="יציאות DVI", en="DVI Outputs"),
    _f("frame_sync", "str", group="core", aliases=("frame_sync", "g_sync", "freesync"),
       he="סנכרון פריימים", en="Frame Sync"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# case_fan
# --------------------------------------------------------------------------

CASE_FAN = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("size_mm", "int", lo=40, hi=250, filterable=True, group="physical",
       aliases=("size_mm", "fan_size_mm", "size"), he="גודל (mm)", en="Size (mm)"),
    _f("quantity", "int", lo=1, hi=10, group="physical", aliases=("quantity", "fans_per_pack", "pack"),
       he="כמות בחבילה", en="Quantity"),
    _f("flow_direction", "enum", enum=("standard", "reverse"), group="physical",
       aliases=("flow_direction", "airflow_direction"), he="כיוון זרימה", en="Flow Direction"),
    _f("rpm_min", "int", lo=0, hi=6000, group="core", aliases=("rpm_min",), he="סל״ד מינימלי",
       en="RPM Min"),
    _f("rpm_max", "int", lo=0, hi=8000, group="core", aliases=("rpm_max", "rpm"),
       he="סל״ד מקסימלי", en="RPM Max"),
    _f("airflow_cfm", "float", lo=0, hi=800, group="core", aliases=("airflow_cfm", "airflow"),
       he="ספיקת אוויר (CFM)", en="Airflow (CFM)"),
    _f("noise_db", "float", lo=0, hi=80, group="core", aliases=("noise_db", "noise_level"),
       he="רעש (dB)", en="Noise (dB)"),
    _f("static_pressure_mmh2o", "float", lo=0, hi=20, group="core",
       aliases=("static_pressure_mmh2o", "static_pressure"), he="לחץ סטטי (mmH2O)",
       en="Static Pressure (mmH2O)"),
    _f("pwm", "bool", filterable=True, group="core", aliases=("pwm",), he="PWM", en="PWM"),
    _f("connector", "str", group="io", aliases=("connector", "power_connector"),
       he="מחבר", en="Connector"),
    _f("led", "str", filterable=True, group="physical", aliases=("led", "lighting"),
       he="תאורה", en="LED"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# case
# --------------------------------------------------------------------------

CASE = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("type", "str", filterable=True, group="identity",
       aliases=("type", "form_factor", "case_type"), he="סוג", en="Type"),
    _f("side_panel", "str", filterable=True, group="physical", aliases=("side_panel",),
       he="פאנל צד", en="Side Panel"),
    _f("psu_included", "str", group="power", aliases=("psu_included", "power_supply", "psu"),
       he="ספק כוח כלול", en="PSU Included"),
    _f("psu_shroud", "bool", group="power", aliases=("psu_shroud", "power_supply_shroud"),
       he="כיסוי ספק כוח", en="PSU Shroud"),
    _f("mb_form_factors", "list_str", group="physical",
       aliases=("mb_form_factors", "supported_mb_form_factors", "motherboard_support"),
       he="פורמטים נתמכים", en="Motherboard Form Factors"),
    _f("max_gpu_length_mm", "int", lo=50, hi=600, filterable=True, group="physical",
       aliases=("max_gpu_length_mm", "maximum_video_card_length", "gpu_max_length_mm"),
       he="אורך GPU מקסימלי (mm)", en="Max GPU Length (mm)"),
    _f("max_cooler_height_mm", "int", lo=10, hi=300, group="physical",
       aliases=("max_cooler_height_mm", "cooler_max_height_mm"),
       he="גובה קירור מקסימלי (mm)", en="Max Cooler Height (mm)"),
    _f("drive_bays_35", "int", lo=0, hi=20, group="storage",
       aliases=("drive_bays_35", "internal_35_bays"), he="תאי 3.5 אינץ'", en="3.5\" Bays"),
    _f("drive_bays_25", "int", lo=0, hi=20, group="storage",
       aliases=("drive_bays_25", "internal_25_bays"), he="תאי 2.5 אינץ'", en="2.5\" Bays"),
    _f("expansion_slots", "str", group="io", aliases=("expansion_slots",),
       he="חריצי הרחבה", en="Expansion Slots"),
    _f("front_usb", "list_str", group="io", aliases=("front_usb", "front_io", "front_panel_usb"),
       he="USB קדמי", en="Front USB"),
    _f("fan_support", "dict_int", group="physical", aliases=("fan_support",),
       he="תמיכת מאווררים", en="Fan Support"),
    _f("radiator_support", "dict_int", group="physical",
       aliases=("radiator_support", "supported_radiator_mm"), he="תמיכת רדיאטורים",
       en="Radiator Support"),
    _f("dimensions_mm", "str", group="physical", aliases=("dimensions_mm", "dimensions"),
       he="ממדים (HxWxD)", en="Dimensions (HxWxD)"),
    _f("volume_l", "float", lo=1, hi=300, group="physical",
       aliases=("volume_l", "external_volume_l", "external_volume"), he="נפח (L)", en="Volume (L)"),
    _f("weight_kg", "float", lo=0.2, hi=60, group="physical", aliases=("weight_kg", "weight"),
       he="משקל (kg)", en="Weight (kg)"),
    _f("fan_front", "str", group="physical", aliases=("fan_front",), he="מאווררים קדמיים", en="Front Fans"),
    _f("fan_top", "str", group="physical", aliases=("fan_top",), he="מאווררים עליונים", en="Top Fans"),
    _f("fan_rear", "str", group="physical", aliases=("fan_rear",), he="מאוורר אחורי", en="Rear Fan"),
    _f("fan_bottom", "str", group="physical", aliases=("fan_bottom",), he="מאווררים תחתונים", en="Bottom Fans"),
    _f("lighting", "str", filterable=True, group="physical", aliases=("lighting", "rgb_lighting"),
       he="תאורה", en="Lighting"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# psu
# --------------------------------------------------------------------------

_PSU_TYPES = ("ATX", "SFX", "SFX-L", "TFX", "Flex ATX", "Micro ATX", "Mini ITX", "1U")
_PSU_EFFICIENCY = ("80+ White", "80+ Bronze", "80+ Silver", "80+ Gold",
                   "80+ Platinum", "80+ Titanium")

PSU = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("type", "enum", enum=_PSU_TYPES, filterable=True, group="identity",
       aliases=("type", "form_factor"), he="סוג", en="Type"),
    _f("wattage_w", "int", lo=100, hi=3000, filterable=True, group="power",
       aliases=("wattage_w", "wattage", "power_consumption"), he="הספק (W)", en="Wattage (W)"),
    _f("efficiency", "enum", enum=_PSU_EFFICIENCY, filterable=True, group="power",
       aliases=("efficiency", "efficiency_rating", "80plus"), he="יעילות", en="Efficiency"),
    _f("modular", "enum", enum=("no", "semi", "full"), filterable=True, group="power",
       aliases=("modular", "modularity"), he="מודולרי", en="Modular"),
    _f("length_mm", "int", lo=100, hi=250, filterable=True, group="physical",
       aliases=("length_mm", "psu_length_mm", "depth_mm"), he="אורך (mm)", en="Length (mm)"),
    _f("fanless", "bool", filterable=True, group="physical", aliases=("fanless",),
       he="ללא מאוורר", en="Fanless"),
    _f("atx_version", "str", group="power", aliases=("atx_version", "atx_standard"),
       he="תקן ATX", en="ATX Version"),
    _f("atx4_connectors", "int", lo=0, hi=4, group="power", aliases=("atx4_connectors", "atx_24pin"),
       he="מחברי ATX 24-pin", en="ATX 24-pin Connectors"),
    _f("eps8_connectors", "int", lo=0, hi=6, group="power", aliases=("eps8_connectors", "cpu_power_connectors"),
       he="מחברי EPS 8-pin", en="EPS 8-pin Connectors"),
    _f("pcie16_connectors", "int", lo=0, hi=4, group="power",
       aliases=("pcie16_connectors", "pcie16pin", "12v_2x6"), he="מחברי PCIe 16-pin",
       en="PCIe 16-pin Connectors"),
    _f("pcie12_connectors", "int", lo=0, hi=4, group="power",
       aliases=("pcie12_connectors", "12vhpwr"), he="מחברי PCIe 12-pin", en="PCIe 12-pin Connectors"),
    _f("pcie8_connectors", "int", lo=0, hi=12, group="power", aliases=("pcie8_connectors",),
       he="מחברי PCIe 8-pin", en="PCIe 8-pin Connectors"),
    _f("pcie62_connectors", "int", lo=0, hi=12, group="power", aliases=("pcie62_connectors",),
       he="מחברי PCIe 6+2-pin", en="PCIe 6+2-pin Connectors"),
    _f("pcie6_connectors", "int", lo=0, hi=12, group="power", aliases=("pcie6_connectors",),
       he="מחברי PCIe 6-pin", en="PCIe 6-pin Connectors"),
    _f("sata_connectors", "int", lo=0, hi=24, filterable=True, group="power",
       aliases=("sata_connectors", "sata_power_connectors"), he="מחברי SATA", en="SATA Connectors"),
    _f("molex4_connectors", "int", lo=0, hi=12, group="power", aliases=("molex4_connectors", "molex"),
       he="מחברי Molex", en="Molex Connectors"),
    _f("pcie_power_connectors", "str", group="power", aliases=("pcie_power_connectors",),
       he="חיבורי PCIe", en="PCIe Power Connectors"),
    _f("lighting", "str", filterable=True, group="physical", aliases=("lighting", "rgb_lighting"),
       he="תאורה", en="Lighting"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

# --------------------------------------------------------------------------
# Minimal schema — accessories / cooling_other / other / unmapped categories
# --------------------------------------------------------------------------

MINIMAL = (
    _f("manufacturer", "str", filterable=True, group="identity", aliases=_BRAND,
       he="יצרן", en="Manufacturer"),
    _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model"),
    _f("part_numbers", "list_str", group="identity",
       aliases=("part_numbers", "part_number", "mpn"), he="מק״טים", en="Part Numbers"),
    _f("accessory_type", "str", filterable=True, group="identity",
       aliases=("accessory_type", "product_type"), he="סוג אביזר", en="Accessory Type"),
    _f("quantity", "int", lo=1, hi=50, group="physical", aliases=("quantity", "amount", "pack"),
       he="כמות", en="Quantity"),
    _f("connector", "str", group="io", aliases=("connector",), he="מחבר", en="Connector"),
    _f("length_mm", "int", lo=5, hi=2000, group="physical", aliases=("length_mm", "cable_length_mm"),
       he="אורך (mm)", en="Length (mm)"),
    _f("lighting", "str", filterable=True, group="physical", aliases=("lighting", "led", "rgb"),
       he="תאורה", en="Lighting"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)


# --------------------------------------------------------------------------
# Category -> schema
#
# Category ids are the pipeline's `category_normalized` values, unchanged by
# this overhaul (spiders, matching and site routing keep working). aio and
# cooler_air intentionally share one schema: they are the same physical
# product class (PCPP calls both "CPU Cooler").
# --------------------------------------------------------------------------

SCHEMA_VERSION = 1

SCHEMA: dict[str, tuple[FieldSpec, ...]] = {
    "cpu": CPU,
    "motherboard": MOTHERBOARD,
    "memory": MEMORY,
    "storage": STORAGE,
    "gpu": GPU,
    "case": CASE,
    "psu": PSU,
    "case_fan": CASE_FAN,
    "aio": CPU_COOLER,
    "cooler_air": CPU_COOLER,
    "cooling_other": CPU_COOLER,
    "accessories": MINIMAL,
    "other": MINIMAL,
}

DEFAULT_SCHEMA = MINIMAL


def _norm_key(key: str) -> str:
    """Normalize a vendor/detail key for alias lookup ('Board Form Factor' ->
    'board_form_factor'). Mirrors extractors._norm_key_name, kept here so the
    schema owns its own key normalization."""
    out = []
    prev_us = False
    for ch in str(key).strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")


def fields_for(category: str | None) -> tuple[FieldSpec, ...]:
    """Ordered field list for a category (falls back to the minimal schema)."""
    return SCHEMA.get(category or "", DEFAULT_SCHEMA)


def field_names(category: str | None) -> tuple[str, ...]:
    return tuple(f.name for f in fields_for(category))


def field_map(category: str | None) -> dict[str, FieldSpec]:
    return {f.name: f for f in fields_for(category)}


def filterable_fields(category: str | None) -> tuple[str, ...]:
    """Fields the frontend may offer as checkbox filters (schema order)."""
    return tuple(f.name for f in fields_for(category) if f.filterable)


_ALIAS_CACHE: dict[str, dict[str, str]] = {}

# Vendor detail-table key prefixes that carry no meaning of their own
# ("Hardware Socket", "Spec Motherboard Form Factor", "M.2 Slots" style
# rows are all seen in the wild). Stripped once before retrying the lookup.
_VENDOR_KEY_PREFIXES = (
    "hardware_mother_board_", "hardware_", "spec_interface_", "spec_",
    "mainboard_", "motherboard_", "board_", "ram_", "cpu_",
)


def alias_map(category: str | None) -> dict[str, str]:
    """Normalized alias -> field name, including field names themselves.

    Vendor detail keys are looked up through this map; anything absent is not
    a spec (and is dropped, per the fixed-schema rule).
    """
    key = category or ""
    cached = _ALIAS_CACHE.get(key)
    if cached is None:
        mapping: dict[str, str] = {}
        for field in fields_for(category):
            for alias in (field.name, *field.aliases):
                mapping.setdefault(_norm_key(alias), field.name)
        cached = mapping
        _ALIAS_CACHE[key] = cached
    return cached


def field_for_key(category: str | None, key: str) -> FieldSpec | None:
    """Resolve a raw (vendor/detail/legacy) key to a schema field.

    Vendor detail tables spell the same field many ways ("Hardware Socket",
    "Spec Motherboard Form Factor", "M.2 Slots"). After the exact alias lookup
    fails, known vendor key prefixes are stripped and the lookup is retried,
    then a unique suffix match is accepted. Ambiguous keys resolve to None —
    a wrong mapping is worse than a dropped row.
    """
    fields = field_map(category)
    aliases = alias_map(category)
    normalized = _norm_key(key)
    if normalized in aliases:
        return fields[aliases[normalized]]

    candidate = normalized
    for prefix in _VENDOR_KEY_PREFIXES:
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
            if candidate in aliases:
                return fields[aliases[candidate]]
            break

    if len(normalized) >= 4:
        matches = {name for alias, name in aliases.items()
                   if alias.endswith(f"_{normalized}") or normalized.endswith(f"_{alias}")}
        if len(matches) == 1:
            return fields[matches.pop()]
    return None


def empty_specs(category: str | None) -> dict[str, None]:
    """The full fixed key set with every value null — the shape every
    product must ship, whether or not any source supplied a value."""
    return {f.name: None for f in fields_for(category)}


def covered_specs(category: str | None, specs: dict) -> dict:
    """Only the non-null fields (used by golden checks and the coverage
    report; the shipped `specs` keeps nulls)."""
    return {k: v for k, v in specs.items() if v is not None}


def normalize_key(key: str) -> str:
    """Public alias for the vendor/detail key normalizer."""
    return _norm_key(key)


def json_schema() -> dict:
    """Machine-readable schema for tests/tooling (one definition, many uses)."""
    return {
        "version": SCHEMA_VERSION,
        "categories": {
            cat: {
                "fields": [
                    {
                        "name": f.name,
                        "type": f.type,
                        "unit": f.unit,
                        "enum": list(f.enum),
                        "min": f.lo,
                        "max": f.hi,
                        "filterable": f.filterable,
                        "group": f.group,
                        "aliases": list(f.aliases),
                    }
                    for f in fields
                ]
            }
            for cat, fields in SCHEMA.items()
        },
    }


def schema_field_names() -> frozenset[str]:
    """Every field name across every category (for the legacy projection's
    'is this key schema-owned?' check)."""
    names: set[str] = set()
    for fields in SCHEMA.values():
        names.update(f.name for f in fields)
    return frozenset(names)


def schema_key_names() -> frozenset[str]:
    """Every field name AND alias across every category (normalized). This is
    what stops non-schema junk from re-entering the derived attributes blob."""
    keys: set[str] = set()
    for category in SCHEMA:
        keys.update(alias_map(category))
    return frozenset(keys)
