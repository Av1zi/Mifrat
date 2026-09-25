"""
specs/validate.py — per-field validators + cross-field consistency.

Two layers:

1. `validate_fact(category, field, value)` — per-value sanity: type, enum,
   range (already applied during coercion) PLUS the semantic guards that used
   to be scattered through extractors.py (socket shapes, planar core counts,
   plausible memory speeds, board memory-max whitelist, Hebrew/promo junk).
   Returns a reason string when the value must be dropped, else None.

2. `cross_check(category, specs, sources)` — post-merge contradiction rules
   from the plan §6: chipset <-> socket <-> memory type, memory module math,
   CPU tray-without-cooler, and warn-only notes (GPU external power).
   The higher-tier field wins; the loser is nulled and every change is logged
   for the QA report. Nothing is silently flipped.
"""

from __future__ import annotations

import re

from . import schema
from .derive import expected_microarchitecture, zen_generation
from .schema import FieldSpec

# Tier preference for cross-field fights (lower number = stronger source).
_TIER_ORDER = {"override": 0, "reference": 1, "vendor": 2, "title": 3, "weak": 4}

_SOCKET_SHAPE = re.compile(
    r"^(?:\d x )?(AM\d\+?|FM\d\+?|LGA\d{3,4}(?:-[0-9v]\d?)?|BGA\d+|sTR\d+|sTRX\d+|sWRX\d+"
    r"|TRX?\d{1,2}|SP\d+|G\d{1,2}|PGA\d+|Socket\s?[A-Z0-9]+)$",
    re.I,
)
_CHIPSET_SHAPE = re.compile(r"^[A-Za-z]{1,4}\d{2,4}[A-Za-z]{0,2}$")
# A GPU chip is a marketing name ("GeForce RTX 5070 Ti"), not a board chipset
# code, so it is checked as a name: a model number, no listing dump.
_GPU_CHIPSET_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+\-]{1,31}$")

# Planar CPU core counts (a "7-core" CPU is always a parse error).
_PLANAR_CORES = frozenset({
    1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 44, 48,
    56, 60, 64, 72, 84, 96, 112, 128, 144, 192, 256,
})

# Board memory-maximum sizes worth accepting (GB). Anything else is a
# misparsed title ("2000", "1", "2"), not a memory limit.
_BOARD_MAX_MEM_GB = frozenset({
    16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048,
    3072, 4096, 6144, 8192,
})

# Plausible memory clock steps (JEDEC + XMP/EXPO common values).
_MEMORY_SPEEDS = frozenset({
    1066, 1333, 1600, 1866, 2133, 2400, 2666, 2800, 2933, 3000, 3200, 3333,
    3466, 3600, 3733, 3800, 4000, 4133, 4200, 4266, 4400, 4600, 4800, 5000,
    5200, 5400, 5600, 5800, 6000, 6200, 6400, 6600, 6800, 7000, 7200, 7400,
    7600, 7800, 8000, 8200, 8400, 8600, 8800, 9000, 9200, 9400, 9600, 9800,
    10000,
})

_HEBREW_OR_MOJIBAKE = re.compile(r"[\u0590-\u05FF\ufffd\u05f3]")
_PROMO_TEXT = re.compile(r"לחץ/י|לרכישה|מומלץ|לקרר")

# Standard fan sizes a mis-keyed "radiator" value is allowed to be read as.
_FAN_SIZES = frozenset({80, 92, 120, 135, 140, 150, 170, 200, 230})

# An Ethernet column holding a wireless marketing paragraph is a mis-mapping;
# a Bluetooth radio is never Ethernet.
_NOT_ETHERNET = re.compile(r"bluetooth", re.I)

# The reference dataset occasionally leaks a GPU architecture into a CPU's
# microarchitecture ("RDNA 2, Codename", "Xe-LPG / Gen 12.7").
_GPU_ARCH = re.compile(r"\bRDNA\b|\bVega\b|\bNavi\b|\bXe-?LPG\b|\bGen\s?12\.?\d*\b", re.I)


def _looks_like_junk(text: str) -> bool:
    """Hebrew prose, mojibake, or Ivory promo copy that leaked into a spec."""
    if _HEBREW_OR_MOJIBAKE.search(text):
        return True
    return bool(_PROMO_TEXT.search(text))


def validate_fact(category: str | None, field: FieldSpec, value) -> str | None:
    """Return a drop-reason for `value`, or None when it is acceptable."""
    if value is None:
        return "null value"

    if field.type in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected a number, got {type(value).__name__}"
        if field.lo is not None and value < field.lo:
            return f"{value} below minimum {field.lo}"
        if field.hi is not None and value > field.hi:
            return f"{value} above maximum {field.hi}"
    elif field.type == "bool":
        if not isinstance(value, bool):
            return f"expected a boolean, got {type(value).__name__}"
    else:
        if not isinstance(value, (str, list, dict)):
            return f"expected text, got {type(value).__name__}"
        for token in ([value] if isinstance(value, str)
                      else value if isinstance(value, list) else list(value)):
            if isinstance(token, str) and _looks_like_junk(token):
                return "content looks like Hebrew prose / mojibake / promo copy"

    if field.type == "enum" and field.enum and value not in field.enum:
        return f"{value!r} not in {field.enum}"

    # ---- semantic guards (the good parts of the old extractors heuristics) --
    if field.name == "socket" and isinstance(value, str):
        if not _SOCKET_SHAPE.match(value.strip()):
            return f"socket {value!r} has an implausible shape"
    if field.name == "chipset" and isinstance(value, str):
        # Board chipsets are short codes ("B850"); GPU chips are chip names
        # ("GeForce RTX 5070"). Applying the board rule to both silently threw
        # away every multi-word GPU chipset — 87% of the GPU catalogue.
        if category == "motherboard":
            if not _CHIPSET_SHAPE.match(value.strip()):
                return f"chipset {value!r} has an implausible shape"
        elif category == "gpu":
            if not _GPU_CHIPSET_SHAPE.match(value.strip()):
                return f"GPU chipset {value!r} is not a chip name"
    if field.name == "core_count" and isinstance(value, int):
        if value not in _PLANAR_CORES:
            return f"core count {value} is not a planar CPU layout"
    if field.name == "thread_count" and isinstance(value, int):
        if value > 512:
            return f"thread count {value} is implausible"
    if field.name == "memory_max_gb" and isinstance(value, int):
        if category == "motherboard" and value not in _BOARD_MAX_MEM_GB:
            return f"board memory maximum {value}GB is not a real board limit"
    if field.name == "speed_mhz" and isinstance(value, int):
        if value not in _MEMORY_SPEEDS:
            return f"memory speed {value}MHz is not a JEDEC/XMP/EXPO rating"
    if field.name == "wattage_w" and isinstance(value, int):
        if value % 10:
            return f"wattage {value}W is not a standard PSU rating"
    if field.name == "manufacturer" and isinstance(value, str):
        # Brand names are short; a marketing/rating blurb that leaked into the
        # brand slot ("80 PLUS Gold (according to manufacturer, 115V)") is not.
        if len(value) > 32 or "(" in value or "," in value or "according to" in value.lower():
            return f"manufacturer {value!r} is not a brand name"
    if field.name == "capacity_gb" and category == "storage" and isinstance(value, int):
        # No internal consumer drive ships under 16GB; a smaller number is a
        # unit/parse error ("2 TB" extracted as 2).
        if value < 16:
            return f"storage capacity {value}GB is implausibly small"
    if field.name == "ethernet" and isinstance(value, str):
        if _NOT_ETHERNET.search(value):
            return "ethernet value carries Bluetooth, so it is a wireless row"
    if field.name == "microarchitecture" and category == "cpu" and isinstance(value, str):
        if _GPU_ARCH.search(value):
            return f"microarchitecture {value!r} is a GPU architecture"
    return None


# --------------------------------------------------------------------------
# Cross-field consistency (post-merge)
# --------------------------------------------------------------------------


def _tier_rank(sources: dict, field: str) -> int:
    return _TIER_ORDER.get(sources.get(field, ""), 99)


def cross_check(category: str | None, specs: dict, sources: dict) -> list[dict]:
    """Mutates `specs`/`sources` in place; returns the list of QA issues.

    Each issue: {"kind": "spec_conflict"|"spec_note", "field": ..., "detail":
    ..., "kept": ..., "dropped": ...}. Conflicts drop a value; notes are
    informational only (never change data).
    """
    issues: list[dict] = []

    def drop(field: str, reason: str, kept_field: str) -> None:
        issues.append({
            "kind": "spec_conflict",
            "field": field,
            "kept": kept_field,
            "detail": reason,
            "dropped": specs.get(field),
        })
        specs[field] = None
        sources.pop(field, None)

    if category == "motherboard":
        chipset = specs.get("chipset")
        info = schema.CHIPSET_INFO.get(str(chipset or "").upper())
        if info:
            known_socket, known_memory = info
            socket = specs.get("socket")
            if known_socket and socket and socket != known_socket:
                if _tier_rank(sources, "socket") <= _tier_rank(sources, "chipset"):
                    drop("chipset", f"chipset {chipset} implies socket {known_socket}", "socket")
                else:
                    drop("socket", f"socket {socket} contradicts chipset {chipset}", "chipset")
            memory = specs.get("memory_type")
            if known_memory and memory and memory != known_memory:
                if _tier_rank(sources, "memory_type") <= _tier_rank(sources, "chipset"):
                    drop("chipset", f"chipset {chipset} implies {known_memory}", "memory_type")
                else:
                    drop("memory_type", f"{memory} contradicts chipset {chipset}", "chipset")

    if category == "memory":
        count, size, total = (specs.get("module_count"), specs.get("module_size_gb"),
                              specs.get("total_gb"))
        if count and size:
            computed = count * size
            if total is None:
                specs["total_gb"] = computed
                sources["total_gb"] = sources.get("module_count", "vendor")
            elif total != computed:
                modules_rank = max(_tier_rank(sources, "module_count"),
                                   _tier_rank(sources, "module_size_gb"))
                if modules_rank <= _tier_rank(sources, "total_gb"):
                    issues.append({
                        "kind": "spec_conflict", "field": "total_gb",
                        "kept": "module_count x module_size_gb",
                        "detail": f"{count}x{size}GB = {computed}GB, not {total}GB",
                        "dropped": total,
                    })
                    specs["total_gb"] = computed
                    sources["total_gb"] = sources.get("module_count", "vendor")
                else:
                    drop("total_gb", f"{count}x{size}GB != {total}GB", "module_count")

    if category == "cpu" and specs.get("packaging") == "tray" and specs.get("includes_cooler"):
        drop("includes_cooler", "tray CPUs never include a cooler", "packaging")

    if category == "cpu" and specs.get("microarchitecture"):
        # Note only: the lineup rule is strong enough to contradict a source
        # (the reference dataset lists a Threadripper 7960X as Zen 2), but a
        # wrong reference value is a data question, not something to silently
        # overwrite here.
        expected = expected_microarchitecture(specs.get("model"))
        admitted, implied = zen_generation(specs["microarchitecture"]), zen_generation(expected)
        if admitted and implied and admitted != implied:
            issues.append({
                "kind": "spec_note", "field": "microarchitecture",
                "detail": f"{specs['microarchitecture']} contradicts "
                          f"{specs.get('model')} ({expected})",
            })

    if category == "gpu":
        tdp = specs.get("tdp_w")
        if isinstance(tdp, int) and tdp > 75 and not specs.get("external_power"):
            issues.append({
                "kind": "spec_note", "field": "external_power",
                "detail": f"{tdp}W card with no external power info",
            })

    if category in ("cooler_air", "cooling_other"):
        # An air cooler is never water-cooled and has no radiator. Vendor
        # detail rows keyed "aio"/"size" used to flip these (Sep 2026: a
        # Thermalright Peerless Assassin shipped as water_cooled=true with a
        # "120mm radiator").
        if specs.get("water_cooled"):
            drop("water_cooled", "an air cooler is not water-cooled", "category")
        radiator = specs.get("radiator_size_mm")
        if radiator is not None:
            if specs.get("fan_size_mm") is None and int(radiator) in _FAN_SIZES:
                specs["fan_size_mm"] = int(radiator)
                sources["fan_size_mm"] = sources.get("radiator_size_mm", "vendor")
            drop("radiator_size_mm", "an air cooler has no radiator", "category")

    if category == "aio" and specs.get("water_cooled") is False:
        drop("water_cooled", "an AIO is water-cooled by definition", "category")

    if category == "psu":
        watts, connectors = specs.get("wattage_w"), specs.get("pcie8_connectors")
        if isinstance(watts, int) and isinstance(connectors, int) and connectors > watts // 150:
            issues.append({
                "kind": "spec_note", "field": "pcie8_connectors",
                "detail": f"{connectors} PCIe 8-pin connectors for a {watts}W unit",
            })

    return issues


def fill_derived(category: str | None, specs: dict, sources: dict) -> None:
    """Fill fields that follow logically from higher-priority ones.

    Only unambiguous inferences (the socket/memory map excludes LGA1700,
    which really does ship in both DDR4 and DDR5 flavors). Marked with the
    `vendor` tier and a `derived:` source so provenance stays honest.
    """
    if category != "motherboard":
        return
    if not specs.get("memory_type") and specs.get("socket"):
        memory = schema.SOCKET_MEMORY.get(str(specs["socket"]).upper())
        if memory and str(specs["socket"]).upper() != "LGA1700":
            specs["memory_type"] = memory
            sources["memory_type"] = "vendor"
