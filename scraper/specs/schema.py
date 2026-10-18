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
    # Conditional applicability: ((gate_field, (allowed values...)), ...).
    # The field is meaningful only when EVERY gate field holds one of its
    # allowed values; a gate that is still null leaves the field applicable
    # (unknown is not "no"). See `applies()`. Python-side only: it is not
    # exported to the frontend (the site never needs to know why a cell is
    # absent, only that the schema says it is not expected).
    applies_to: tuple[tuple[str, tuple], ...] = ()

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
    when: tuple[tuple[str, tuple], ...] = (),
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
        applies_to=tuple((gate, tuple(allowed)) for gate, allowed in when),
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
    # AMD sTR5 / WRX90. WRX90 is Threadripper PRO 7000 (sTR5); sWRX8 is the
    # older WRX80 line. The Sep 2026 TMS detail audit caught the map claiming
    # sWRX8 for WRX90 boards while the vendor page showed תושבת מעבד = sTR5,
    # so the title parse was inheriting a wrong socket from this table.
    "TRX50": ("sTR5", "DDR5"), "WRX90": ("sTR5", "DDR5"),
    "WRX80": ("sWRX8", "DDR4"),
    # Intel LGA1151 / DDR4
    "H110": ("LGA1151", "DDR4"), "B150": ("LGA1151", "DDR4"),
    "H170": ("LGA1151", "DDR4"), "Z170": ("LGA1151", "DDR4"),
    "B250": ("LGA1151", "DDR4"), "H270": ("LGA1151", "DDR4"),
    "Z270": ("LGA1151", "DDR4"), "H310": ("LGA1151", "DDR4"),
    "B360": ("LGA1151", "DDR4"), "H370": ("LGA1151", "DDR4"),
    "Z370": ("LGA1151", "DDR4"), "B365": ("LGA1151", "DDR4"),
    "Z390": ("LGA1151", "DDR4"),
    "Q170": ("LGA1151", "DDR4"), "Q270": ("LGA1151", "DDR4"),
    "Q370": ("LGA1151", "DDR4"),
    # Intel LGA1200 / DDR4
    "H410": ("LGA1200", "DDR4"), "B460": ("LGA1200", "DDR4"),
    "H470": ("LGA1200", "DDR4"), "Z490": ("LGA1200", "DDR4"),
    "W480": ("LGA1200", "DDR4"), "H510": ("LGA1200", "DDR4"),
    "B560": ("LGA1200", "DDR4"), "H570": ("LGA1200", "DDR4"),
    "Z590": ("LGA1200", "DDR4"),
    "Q470": ("LGA1200", "DDR4"), "Q570": ("LGA1200", "DDR4"),
    # Intel LGA1700 (DDR4 or DDR5 depending on the board)
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "H670": ("LGA1700", None),
    "Z690": ("LGA1700", None), "B760": ("LGA1700", None), "H770": ("LGA1700", None),
    "Z790": ("LGA1700", None), "W680": ("LGA1700", None),
    "Q670": ("LGA1700", None),
    # Intel LGA1851 (DDR5 only)
    "H810": ("LGA1851", "DDR5"), "B860": ("LGA1851", "DDR5"),
    "Z890": ("LGA1851", "DDR5"), "W890": ("LGA1851", "DDR5"),
    # HEDT / legacy
    "X99": ("LGA2011-v3", "DDR4"), "X299": ("LGA2066", "DDR4"),
    "X399": ("TR4", "DDR4"), "TRX40": ("sTRX4", "DDR4"),
    "C422": ("LGA2066", "DDR4"), "C621": ("LGA3647", "DDR4"),
    "W790": ("LGA4677", "DDR5"),
    # Server chipsets (Sep 2026: seen on TMS server-board details;
    # canon_chipset recovers these from concatenated vendor cells).
    "C602": ("LGA2011", "DDR3"), "C612": ("LGA2011-v3", "DDR4"),
    # Sapphire Rapids (LGA4677, DDR5): Supermicro X13 boards print C741.
    "C741": ("LGA4677", "DDR5"),
}

# Socket -> memory generation. Used by validate.py's cross-field checks and by
# the reference resolver's anchor cross-check (not as a spec source itself).
SOCKET_MEMORY: dict[str, str] = {
    "AM4": "DDR4", "AM5": "DDR5", "sTR5": "DDR5", "sWRX8": "DDR4",
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

# Purchase form ("Retail - קופסה", "Bulk - בשקית", "Tray - מגש"). One shared
# field instance for every category whose vendors list it: the enum is the
# canonical set canon_packaging folds every spelling into, so a CPU box and a
# sealed motherboard read the same on the site. Order sets the filter order.
PACKAGING = _f("packaging", "enum", enum=("boxed", "tray", "bulk", "oem"),
               filterable=True, group="identity",
               aliases=("packaging", "box_type", "pack"), he="אריזה", en="Packaging")

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
    # TMS and 1PC print the lineup generation as its own row ("דור 14",
    # "Series 2") — 69 rows with no home until now. canon_generation folds
    # the three vendor spellings into one shape ("Gen N"); the generation
    # word is required, so a bare number is never read as one.
    _f("generation", "str", group="core",
       aliases=("generation", "cpu_generation", "processor_generation"),
       he="דור", en="Generation"),
    # Ivory lists every chipset the CPU drops into ("Intel Z690 | Intel
    # H610 | ..."), which is the real "is this CPU compatible with my
    # board" answer — 113 rows, unmapped until now.
    _f("chipset_support", "list_str", group="core",
       aliases=("chipset_support", "supported_chipsets", "compatible_chipsets"),
       he="תמיכת ערכות שבבים", en="Chipset Support"),
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
    # float: Intel hybrid parts print fractional L2 ("9.5MB" on a 14400), which
    # an int field rejected, so those caches shipped null.
    _f("l2_cache_mb", "float", lo=0.25, hi=512, group="core", aliases=("l2_cache_mb", "l2_cache"),
       he="מטמון L2 (MB)", en="L2 Cache (MB)"),
    _f("l3_cache_mb", "float", lo=0.5, hi=2048, group="core", aliases=("l3_cache_mb", "l3_cache"),
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
    PACKAGING,
    _f("lithography_nm", "int", lo=2, hi=250, group="core",
       aliases=("lithography_nm", "manufacturing_process", "process_nm"),
       he="ליתוגרפיה (nm)", en="Lithography (nm)"),
    _f("smt", "bool", filterable=True, group="core", aliases=("smt", "hyperthreading"),
       he="SMT", en="SMT"),
    _f("unlocked", "bool", group="other", aliases=("unlocked", "overclock_support"),
       he="לא נעול", en="Unlocked"),
)

# --------------------------------------------------------------------------
# coolers - aio / cooler_air / cooling_other
#
# Split 2026-10-17 (was one shared CPU_COOLER tuple): an air cooler can never
# carry a radiator or a pump, and a closed-loop AIO's "is it water cooled" is
# its category, so those cells sat permanently empty and dragged cooler fill to
# 26-45%. Shared field instances are defined once and composed per category.
# --------------------------------------------------------------------------

_C_MANUFACTURER = _f("manufacturer", "str", filterable=True, group="identity",
                     aliases=_BRAND, he="יצרן", en="Manufacturer")
_C_MODEL = _f("model", "str", group="identity", aliases=_MODEL, he="דגם", en="Model")
_C_PART_NUMBERS = _f("part_numbers", "list_str", group="identity",
                     aliases=("part_numbers", "part_number", "mpn"),
                     he="מק״טים", en="Part Numbers")
_C_WATER_COOLED = _f("water_cooled", "bool", filterable=True, group="physical",
                     aliases=("water_cooled", "aio"), he="קירור נוזלי", en="Water Cooled")
_C_RADIATOR_SIZE = _f("radiator_size_mm", "int", lo=60, hi=560, filterable=True,
                      group="physical",
                      aliases=("radiator_size_mm", "supported_radiator_mm", "radiator_mm", "size"),
                      he="גודל רדיאטור (mm)", en="Radiator Size (mm)")
# Ivory prints the radiator's real dimensions ("אורך: 403 מ\"מ רוחב: 120
# מ\"מ עובי: 27 מ\"מ"); the size class above already says 360, so these
# two are the extra facts that cell carries (fitment in tight cases).
_C_RADIATOR_LENGTH = _f("radiator_length_mm", "int", lo=60, hi=600, group="physical",
                        aliases=("radiator_length_mm",),
                        he="אורך רדיאטור (mm)", en="Radiator Length (mm)")
_C_RADIATOR_THICKNESS = _f("radiator_thickness_mm", "int", lo=10, hi=100,
                           group="physical", aliases=("radiator_thickness_mm",),
                           he="עובי רדיאטור (mm)", en="Radiator Thickness (mm)")
_C_FAN_SIZE = _f("fan_size_mm", "int", lo=40, hi=200, filterable=True, group="physical",
                 aliases=("fan_size_mm", "fan_size"), he="גודל מאוורר (mm)", en="Fan Size (mm)")
_C_FAN_COUNT = _f("fan_count", "int", lo=0, hi=6, group="physical",
                  aliases=("fan_count", "fans"), he="מספר מאווררים", en="Fan Count")
_C_FAN_RPM_MIN = _f("fan_rpm_min", "int", lo=0, hi=6000, group="physical",
                    aliases=("fan_rpm_min", "rpm_min", "fan_speed_min"),
                    he="סל״ד מינימלי", en="Fan RPM Min")
_C_FAN_RPM_MAX = _f("fan_rpm_max", "int", lo=0, hi=8000, group="physical",
                    aliases=("fan_rpm_max", "rpm_max", "rpm", "fan_speed"),
                    he="סל״ד מקסימלי", en="Fan RPM Max")
_C_NOISE = _f("noise_db", "float", lo=0, hi=80, group="physical",
              aliases=("noise_db", "noise_level"), he="רעש (dB)", en="Noise (dB)")
_C_AIRFLOW = _f("airflow_cfm", "float", lo=0, hi=800, group="physical",
                aliases=("airflow_cfm", "airflow", "air_flow"),
                he="ספיקת אוויר (CFM)", en="Airflow (CFM)")
_C_HEIGHT = _f("height_mm", "int", lo=5, hi=300, group="physical",
               aliases=("height_mm", "cooler_height_mm"), he="גובה (mm)", en="Height (mm)")
_C_SOCKETS = _f("sockets", "list_str", filterable=True, group="io",
                aliases=("sockets", "socket_compat", "socket"),
                he="סוקטים נתמכים", en="Sockets")
# Ivory's "חיבורים" cell lists the fan/pump wiring ("חיבור 4pin PWM ללוח
# אם", "חיבור 3pin ARGB", "USB2.0 פנימי"); the cell parser reduces it to
# the connector list instead of shipping the prose.
_C_CONNECTORS = _f("connectors", "list_str", group="io",
                   aliases=("connectors", "connection_types"),
                   he="חיבורים", en="Connectors")
# "אורך: 69 מ\"מ רוחב: 92 מ\"מ גובה: 76 מ\"מ" - the pump/block block
# size, kept as one normalized dimension string (case dimensions_mm has
# the same shape; nothing downstream sorts on it).
_C_PUMP_DIMS = _f("pump_dimensions_mm", "str", group="physical",
                  aliases=("pump_dimensions_mm", "pump_size_mm"),
                  he="מידות משאבה", en="Pump Dimensions (mm)")
_C_TDP = _f("tdp_w", "int", lo=10, hi=1000, group="power",
            aliases=("tdp_w", "tdp", "cooling_capacity_w"),
            he="פיזור חום (W)", en="Cooling Capacity (W)")
_C_FANLESS = _f("fanless", "bool", filterable=True, group="physical",
                aliases=("fanless",), he="ללא מאוורר", en="Fanless")
_C_LIGHTING = _f("lighting", "str", filterable=True, group="physical",
                 aliases=("lighting", "led"), he="תאורה", en="Lighting")
_C_COLOR = _f("color", "str", filterable=True, group="physical",
              aliases=("color", "colour"), he="צבע", en="Color")

# Closed-loop liquid coolers: radiator + pump, no fanless flag, no case-fit
# height (the radiator size is the fit fact), no water_cooled (the category).
AIO = (
    _C_MANUFACTURER, _C_MODEL, _C_PART_NUMBERS,
    _C_RADIATOR_SIZE, _C_RADIATOR_LENGTH, _C_RADIATOR_THICKNESS,
    _C_FAN_SIZE, _C_FAN_COUNT, _C_FAN_RPM_MIN, _C_FAN_RPM_MAX,
    _C_NOISE, _C_AIRFLOW, _C_SOCKETS, _C_CONNECTORS,
    _C_LIGHTING, _C_COLOR,
)

# Tower / downdraft air coolers: no radiator, no pump, no water_cooled.
COOLER_AIR = (
    _C_MANUFACTURER, _C_MODEL, _C_PART_NUMBERS,
    _C_FAN_SIZE, _C_FAN_RPM_MIN, _C_FAN_RPM_MAX,
    _C_NOISE, _C_AIRFLOW, _C_HEIGHT, _C_SOCKETS,
    _C_TDP, _C_FANLESS, _C_LIGHTING, _C_COLOR,
)

# The grab-bag the matcher could not place (coolers of either kind, paste,
# brackets): only the facts that make sense for all of them. water_cooled
# stays here because nothing else says which kind a row is.
# Pruned 2026-10-18 (second pass): `radiator_size_mm` and `fan_count` (0% of 51), `model`
# (3.9%), `airflow_cfm` (11.8%): thermal paste, pads and mounting kits carry none of them.
COOLING_OTHER = (
    _C_MANUFACTURER, _C_PART_NUMBERS, _C_WATER_COOLED,
    _C_FAN_SIZE, _C_FAN_RPM_MAX,
    _C_NOISE, _C_HEIGHT, _C_SOCKETS, _C_TDP,
    _C_LIGHTING, _C_COLOR,
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
    # Ivory's "תמיכה במעבדים (CPU)" row (216 rows, the largest unmapped
    # label in the catalog) names the CPU families the board takes. The raw
    # values are Hebrew prose ("מעבדי AMD: Ryzen 3 / … מסדרות … 9000 /
    # 8000"), which is why 2026-10-15 refused the field. 2026-10-17 reversal:
    # labels.CPU_SUPPORT routes the row through a parser that strips the
    # Hebrew connector words and keeps the Latin family tokens ("AMD Ryzen
    # 3 / Ryzen 5 / Ryzen 9000 / 8000"), so the sheet carries a readable
    # token string instead of untranslated prose. Deliberately NOT
    # filterable — the rail groups it would explode into dozens of
    # near-duplicate values.
    _f("cpu_support", "str", group="core",
       aliases=("cpu_support", "supported_cpus", "cpu_compatibility"),
       he="תמיכה במעבדים", en="CPU Support"),
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
    # "M.2 PCIe | SATA3" — the drive interfaces the board exposes, printed on
    # 455 of 711 board pages (the single largest unmapped label in the
    # catalog). A list, not a count: the vendor names the interfaces.
    _f("storage_interface", "list_str", group="storage",
       aliases=("storage_interface", "storage_interfaces", "drive_interfaces"),
       he="ממשקי אחסון", en="Storage Interfaces"),
    _f("ethernet", "str", filterable=True, group="io",
       aliases=("lan", "ethernet", "network", "spec_network_card"),
       he="רשת", en="Ethernet"),
    _f("onboard_video", "str", group="io",
       aliases=("onboard_video", "video_outputs", "display_outputs", "graphics_output"),
       he="יציאות תצוגה", en="Onboard Video"),
    _f("wireless", "str", filterable=True, group="io",
       aliases=("wifi", "wifi_standard", "wireless", "wireless_std", "spec_wireless"),
       he="אלחוטי", en="Wireless"),
    _f("bluetooth", "str", group="io", aliases=("bluetooth", "bluetooth_version"),
       he="Bluetooth", en="Bluetooth"),
    _f("thunderbolt_ports", "int", lo=0, hi=4, group="io",
       aliases=("thunderbolt_ports", "thunderbolt"),
       he="יציאות Thunderbolt", en="Thunderbolt Ports"),
    _f("ecc_support", "bool", filterable=True, group="memory",
       aliases=("ecc_support", "ecc"), he="תמיכת ECC", en="ECC Support"),
    _f("raid_support", "bool", group="storage", aliases=("raid_support", "raid_level", "raid"),
       he="תמיכת RAID", en="RAID Support"),
    _f("usb_ports", "str", group="io", aliases=("usb_ports", "usb_a_ports", "usb_c_ports"),
       he="יציאות USB", en="Rear USB Ports"),
    _f("audio", "str", group="io", aliases=("audio", "audio_chip"), he="שמע", en="Audio"),
    _f("expansion_slots", "str", group="io", aliases=("expansion_slots",),
       he="חריצי הרחבה", en="Expansion Slots"),
    _f("bios", "str", group="other", aliases=("bios",), he="BIOS", en="BIOS"),
    # Pruned 2026-10-17 (0% fill, no vendor or manufacturer page prints them):
    # `vrm_phases`, `back_connect`, `power_connections`.
    # Removed 2026-10-15: `max_cooler_height_mm` was a CASE fact (the tallest
    # air cooler the enclosure takes) that had been copied into the board
    # schema, where it is physically meaningless and had been null on all
    # 711 boards since the field was added.
    _f("lighting", "str", filterable=True, group="physical",
       aliases=("lighting", "rgb_lighting"), he="תאורה", en="Lighting"),
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
    # PCIe generation exists only on NVMe drives; a SATA SSD has none.
    _f("pcie_gen", "int", lo=1, hi=6, filterable=True, group="storage",
       aliases=("pcie_gen",), he="דור PCIe", en="PCIe Gen",
       when=(("nvme", (True,)),)),
    _f("cache_mb", "int", lo=0, hi=16384, group="storage", aliases=("cache_mb", "cache", "dram_cache"),
       he="מטמון (MB)", en="Cache (MB)"),
    # Spindle speed: a spinning disk fact (an SSD has no platters).
    _f("rpm", "int", lo=0, hi=20000, filterable=True, group="storage",
       aliases=("rpm", "spindle_speed"), he="סל״ד", en="RPM",
       when=(("type", ("HDD", "Hybrid")),)),
    # Sequential throughput and random IOPS: the two rows every vendor's
    # drive page carries ("7450MB/s", "220K IOPS") and the two numbers a
    # buyer compares. Cell-parsed, because thousand separators ("10,000MB
    # לשניה") and the K suffix ("1,850K IOPS") are not bare numbers.
    _f("read_speed_mbs", "int", lo=50, hi=30000, group="storage",
       aliases=("read_speed_mbs", "sequential_read_mbs", "max_read_mbs"),
       he="מהירות קריאה (MB/s)", en="Read Speed (MB/s)"),
    _f("write_speed_mbs", "int", lo=50, hi=30000, group="storage",
       aliases=("write_speed_mbs", "sequential_write_mbs", "max_write_mbs"),
       he="מהירות כתיבה (MB/s)", en="Write Speed (MB/s)"),
    # Pruned 2026-10-17: `random_read_iops` / `random_write_iops` (5% fill, only
    # Ivory's SSD tables print them) and `controller` (0%, no source prints it).
    _f("nand", "str", group="storage", aliases=("nand", "nand_type"), he="סוג NAND", en="NAND",
       when=(("type", ("SSD", "Hybrid")),)),
    # Oct 2026: rows 1PC/Yahav print that had no column before. `series` and
    # `dimensions_mm` reuse the CPU/case field names (one field, several
    # categories); `weight_g` is back for storage only (the prune dropped the
    # shared field at 13.7% fill, but the drive shape rows are the evidence).
    _f("series", "str", group="identity", aliases=("series", "family"),
       he="סדרה", en="Series"),
    _f("dimensions_mm", "str", group="physical",
       aliases=("dimensions_mm", "dimensions", "dimension"),
       he="מידות (מ״מ)", en="Dimensions (mm)"),
    _f("mtbf_hours", "int", lo=0, hi=10_000_000, group="other",
       aliases=("mtbf_hours", "mtbf"), he="MTBF (שעות)", en="MTBF (hours)"),
    _f("warranty_years", "int", lo=1, hi=20, group="other",
       aliases=("warranty_years",), he="אחריות (שנים)", en="Warranty (years)"),
    _f("weight_g", "int", lo=1, hi=5000, group="physical",
       aliases=("weight_g",), he="משקל (גרם)", en="Weight (g)"),
    # Pruned 2026-10-18: `color` (9.8%): drive pages rarely print it.
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
    # Who makes the SILICON (NVIDIA / AMD / Intel), as opposed to
    # `manufacturer` (the board partner that sells the card). Yahav prints it
    # as "יצרן ליבה גראפית" on 85 GPU pages.
    _f("chip_manufacturer", "str", filterable=True, group="identity",
       aliases=("chip_manufacturer", "gpu_chip_vendor", "chip_vendor"),
       he="יצרן השבב", en="Chip Manufacturer"),
    _f("memory_gb", "int", lo=1, hi=128, filterable=True, group="memory",
       aliases=("memory_gb", "vram_gb", "memory", "video_memory"), he="זיכרון (GB)", en="Memory (GB)"),
    _f("memory_type", "str", group="memory", aliases=("memory_type", "vram_type", "gddr"),
       he="סוג זיכרון", en="Memory Type"),
    # GDDR data rate ("20Gbps" on a 5060, "28Gbps" on a 5070 Ti) and the
    # memory bus width ("128bit" / "256bit"). Two different facts vendors
    # print under near-identical Hebrew labels (מהירות זכרון / רוחב פס זכרון),
    # so both carry dedicated cell parsers rather than a bare mapping.
    _f("memory_speed_gbps", "int", lo=1, hi=64, group="memory",
       aliases=("memory_speed_gbps", "vram_speed", "memory_data_rate"),
       he="מהירות זכרון (Gbps)", en="Memory Speed (Gbps)"),
    _f("memory_bus_bit", "int", lo=32, hi=8192, group="memory",
       aliases=("memory_bus_bit", "memory_bus_width", "vram_bus_width"),
       he="רוחב אפיק זיכרון (bit)", en="Memory Bus (bit)"),
    _f("core_clock_mhz", "int", lo=100, hi=4000, group="core",
       aliases=("core_clock_mhz", "core_clock", "base_clock_mhz"),
       he="תדר ליבה (MHz)", en="Core Clock (MHz)"),
    _f("boost_clock_mhz", "int", lo=100, hi=6000, group="core",
       aliases=("boost_clock_mhz", "boost_clock"), he="תדר מוגבר (MHz)", en="Boost Clock (MHz)"),
    _f("directx", "str", group="core", aliases=("directx", "directx_version"),
       he="DirectX", en="DirectX"),
    _f("opengl", "str", group="core", aliases=("opengl", "opengl_version"),
       he="OpenGL", en="OpenGL"),
    _f("interface", "str", filterable=True, group="core",
       aliases=("interface", "bus_interface"), he="ממשק", en="Interface"),
    _f("max_displays", "int", lo=1, hi=8, group="io",
       aliases=("max_displays", "maximum_displays", "multi_display"),
       he="מסכים מקסימלי", en="Max Displays"),
    _f("max_resolution", "str", group="io",
       aliases=("max_resolution", "maximum_resolution", "digital_max_resolution"),
       he="רזולוציה מרבית", en="Max Resolution"),
    _f("length_mm", "int", lo=50, hi=500, group="physical",
       aliases=("length_mm", "gpu_length_mm", "card_length_mm"), he="אורך (mm)", en="Length (mm)"),
    _f("tdp_w", "int", lo=10, hi=1000, group="power", aliases=("tdp_w", "tdp", "power_consumption"),
       he="הספק (W)", en="TDP (W)"),
    _f("recommended_psu_w", "int", lo=100, hi=2000, group="power",
       aliases=("recommended_psu_w", "minimum_psu_w", "psu_requirement_w"),
       he="ספק מומלץ (W)", en="Recommended PSU (W)"),
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
    # Pruned 2026-10-17: `frame_sync` (0.4% fill; no retailer or reference row prints it).
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
    _f("fan_side", "str", group="physical", aliases=("fan_side",), he="מאוורר צד", en="Side Fan"),
    _f("fan_bottom", "str", group="physical", aliases=("fan_bottom",), he="מאווררים תחתונים", en="Bottom Fans"),
    _f("lighting", "str", filterable=True, group="physical", aliases=("lighting", "rgb_lighting"),
       he="תאורה", en="Lighting"),
    _f("rackmount", "bool", filterable=True, group="identity", aliases=("rackmount",),
       he="מארז ראק", en="Rackmount"),
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)

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
    # TMS prints the SERIES' wattage span in its own row (194 rows,
    # "650W - 1100W"). It has to stay out of `wattage_w`: the family minimum
    # once beat the unit's own rating for 143 PSUs and steered their identity
    # slice into a wrong reference variant (decisions.md, 2026-10-13). As its
    # own read-only column the same number is honest and useful.
    _f("series_wattage_range", "str", group="power",
       aliases=("series_wattage_range", "wattage_range", "series_power_range"),
       he="טווח הספק בסדרה", en="Series Wattage Range"),
    _f("efficiency", "enum", enum=_PSU_EFFICIENCY, filterable=True, group="power",
       aliases=("efficiency", "efficiency_rating", "80plus"), he="יעילות", en="Efficiency"),
    _f("modular", "enum", enum=("no", "semi", "full"), filterable=True, group="power",
       aliases=("modular", "modularity"), he="מודולרי", en="Modular"),
    _f("length_mm", "int", lo=100, hi=250, filterable=True, group="physical",
       aliases=("length_mm", "psu_length_mm", "depth_mm"), he="אורך (mm)", en="Length (mm)"),
    # A fanless (passive) PSU has no fan to size.
    _f("fan_size_mm", "int", lo=40, hi=200, group="physical",
       aliases=("fan_size_mm", "fan_size"), he="גודל מאוורר (mm)", en="Fan Size (mm)",
       when=(("fanless", (False,)),)),
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
    _f("color", "str", filterable=True, group="physical", aliases=("color", "colour"),
       he="צבע", en="Color"),
)


# --------------------------------------------------------------------------
# Category -> schema
#
# Category ids are the pipeline's `category_normalized` values, unchanged by
# this overhaul (spiders, matching and site routing keep working). aio,
# cooler_air and cooling_other were one shared schema until 2026-10-17; the
# reference dataset still files both under PCPartPicker's "cpu-cooler".
# --------------------------------------------------------------------------

SCHEMA_VERSION = 2

SCHEMA: dict[str, tuple[FieldSpec, ...]] = {
    "cpu": CPU,
    "motherboard": MOTHERBOARD,
    "memory": MEMORY,
    "storage": STORAGE,
    "gpu": GPU,
    "case": CASE,
    "psu": PSU,
    "case_fan": CASE_FAN,
    "aio": AIO,
    "cooler_air": COOLER_AIR,
    "cooling_other": COOLING_OTHER,
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


def applies(category: str | None, field: str, specs: dict) -> bool:
    """False only when the field provably cannot exist for this product.

    Every `applies_to` gate must hold. A gate whose field is still null leaves
    the field applicable: unknown is not "no", and a wrongly-gated field would
    hide a real gap from the fill report.
    """
    spec = field_map(category).get(field)
    if spec is None:
        return False
    for gate, allowed in spec.applies_to:
        value = specs.get(gate)
        if value is not None and value not in allowed:
            return False
    return True


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


def normalize_key(key: str) -> str:
    """Public alias for the vendor/detail key normalizer."""
    return _norm_key(key)
