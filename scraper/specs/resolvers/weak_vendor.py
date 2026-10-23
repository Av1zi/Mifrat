"""
specs/resolvers/weak_vendor.py — Tier 3: fill-only prose/vendor-fragment data.

This is the LOWEST tier: whatever it produces only fills fields that Tier 0-2
left null, and every value still has to pass validation. It exists because
some vendors publish real facts in shapes we cannot type from a title:

- Plonter titles are dash-separated spec lines
  ("LGA1700 socket - B760 chipset - DDR5 - WIFI - mATX");
- Plonter listings carry a `tree` field of internal filter tokens
  ("ACAM5 BAM5BOARD"), decoded by the table below — vendor-specific by design,
  which is exactly why it lives in its own quarantined module;
- 1PC publishes marketing prose with a few numeric facts in it;
- Ivory's Hebrew descriptions sometimes state cores/threads/clocks.

Nothing here can overwrite a better source: see merge.py rule 3.
"""

from __future__ import annotations

import re

from .. import schema, text
from ..merge import TIER_WEAK, Fact, add_fact
from ..values import InvalidValue, coerce

SOURCE_FRAGMENTS = "weak:plonter-fragments"
SOURCE_TREE = "weak:plonter-tree"
SOURCE_HE = "weak:hebrew-prose"

# Plonter's opaque filter-token table (ported verbatim from extractors.py).
# Keys are legacy/vendor names on purpose: schema.field_for_key() maps them
# onto schema fields, so the table stays a data blob with no logic in it.
PLONTER_TREE_TOKENS: dict[str, dict] = {
    # CPU sockets
    "ACAM4": {"socket": "AM4", "brand": "AMD"},
    "ACAM5": {"socket": "AM5", "brand": "AMD"},
    "AC1700": {"socket": "LGA1700", "brand": "Intel"},
    "AC1851": {"socket": "LGA1851", "brand": "Intel"},
    "ACsTR5": {"socket": "sTR5", "brand": "AMD"},
    "AC4677": {"socket": "LGA4677", "brand": "Intel"},
    "AC3647": {"socket": "LGA3647", "brand": "Intel"},
    "ACSP3": {"socket": "SP3", "brand": "AMD"},
    "ACSP5": {"socket": "SP5", "brand": "AMD"},
    # Motherboards
    "BAM4BOARD": {"socket": "AM4", "brand": "AMD"},
    "BAM5BOARD": {"socket": "AM5", "brand": "AMD"},
    "B1700D5ATX": {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "ATX"},
    "B1700D4ATX": {"socket": "LGA1700", "memory_type": "DDR4", "form_factor": "ATX"},
    "B1700D5ITX": {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "Mini-ITX"},
    "B1700D4ITX": {"socket": "LGA1700", "memory_type": "DDR4", "form_factor": "Mini-ITX"},
    "B1851ATX": {"socket": "LGA1851", "form_factor": "ATX"},
    "B1851MATX": {"socket": "LGA1851", "form_factor": "Micro-ATX"},
    "B1851ITX": {"socket": "LGA1851", "form_factor": "Mini-ITX"},
    "BsTR5BOARD": {"socket": "sTR5", "brand": "AMD"},
    "B4677ATX": {"socket": "LGA4677", "form_factor": "ATX"},
    "BSP3BOARD": {"socket": "SP3", "brand": "AMD"},
    "BSP5BOARD": {"socket": "SP5", "brand": "AMD"},
    "B1151v2ATX": {"socket": "LGA1151", "form_factor": "ATX"},
    "B11514ATX": {"socket": "LGA1151", "form_factor": "ATX"},
    "B1200ATX": {"socket": "LGA1200", "form_factor": "ATX"},
    "B20113ATX": {"socket": "LGA2011-v3", "form_factor": "ATX"},
    # Memory
    "CDDR5D": {"memory_type": "DDR5"},
    "CDDR5DRDECC": {"memory_type": "DDR5", "ecc": True, "registered": True},
    "DDR5SODIM": {"memory_type": "DDR5", "form_factor": "SODIMM"},
    "CDDR4D": {"memory_type": "DDR4"},
    "CDDR4LRDIMM": {"memory_type": "DDR4", "ecc": True, "registered": True},
    "DDR4SODIM": {"memory_type": "DDR4", "form_factor": "SODIMM"},
    "CDDR3D": {"memory_type": "DDR3"},
    "CDDR3LD": {"memory_type": "DDR3L"},
    "3DDR3L": {"memory_type": "DDR3L", "form_factor": "SODIMM"},
    # Storage
    "CHDD35": {"drive_form_factor": "3.5-inch"},
    "CHDD25": {"drive_form_factor": "2.5-inch"},
    "SATA": {"interface": "SATA"},
    "SAS": {"interface": "SAS"},
    "DSSDM2NVMe": {"drive_form_factor": "M.2", "interface": "NVMe"},
    "DSSDM2SATA": {"drive_form_factor": "M.2", "interface": "SATA"},
    "DSSD25": {"drive_form_factor": "2.5-inch", "interface": "SATA"},
    # Cooling — socket support + radiator size
    "ZFANAM4": {"socket_compat": "AM4"},
    "ZFAN1700": {"socket_compat": "LGA1700"},
    "ZFANTR4": {"socket_compat": "TR4"},
    "ZFANS4677": {"socket_compat": "LGA4677"},
    "ZFANSP3": {"socket_compat": "SP3"},
    "120mm": {"radiator_size_mm": 120},
    "240mm": {"radiator_size_mm": 240},
    "280mm": {"radiator_size_mm": 280},
    "360mm": {"radiator_size_mm": 360},
    "420mm": {"radiator_size_mm": 420},
    # Power supply / case
    "EATXPSU": {"form_factor": "ATX"},
    "ESFXPSU": {"form_factor": "SFX"},
    "EATXC": {"form_factor": "ATX"},
    "EITXC": {"form_factor": "Mini-ITX"},
    "EHTPC": {"form_factor": "HTPC"},
    "MINISTX": {"form_factor": "Mini-STX"},
}

# Multi-word tree values need a substring pass (they do not survive a split).
PLONTER_TREE_SUBSTRINGS: dict[str, dict] = {
    "AMD Radeon": {"gpu_vendor": "AMD Radeon"},
    "NVIDIA GeForce": {"gpu_vendor": "NVIDIA GeForce"},
    "Intel ARC": {"gpu_vendor": "Intel ARC"},
    "Tesla": {"gpu_vendor": "NVIDIA Tesla"},
}


def _emit_legacy_keys(facts: dict, category: str, source: str, legacy: dict,
                      confidence: float = 0.6) -> None:
    """Emit `{legacy_key: raw_value}` pairs through the schema alias map."""
    for key, value in legacy.items():
        field = schema.field_for_key(category, key)
        if field is None or value is None:
            continue
        try:
            typed = coerce(field, value, category)
        except InvalidValue:
            continue
        add_fact(facts, field.name,
                 Fact(value=typed, tier=TIER_WEAK, source=source, confidence=confidence))


def parse_plonter_tree(category: str | None, tree_raw) -> dict[str, list[Fact]]:
    """Decode Plonter's internal filter tokens ('ACAM5 BAM5BOARD')."""
    facts: dict[str, list[Fact]] = {}
    if not isinstance(tree_raw, str) or not tree_raw.strip():
        return facts

    for token in tree_raw.split():
        mapping = PLONTER_TREE_TOKENS.get(token)
        if mapping:
            _emit_legacy_keys(facts, category or "", SOURCE_TREE, mapping)

    for marker, mapping in PLONTER_TREE_SUBSTRINGS.items():
        if marker in tree_raw:
            _emit_legacy_keys(facts, category or "", SOURCE_TREE, mapping)
    return facts


def parse_fragments(category: str | None, title_raw) -> dict[str, list[Fact]]:
    """Plonter-style dash-separated spec lines.

    'LGA1700 socket - B760 chipset - DDR5 - WIFI - mATX'
    """
    facts: dict[str, list[Fact]] = {}
    text_value = str(title_raw or "")
    parts = [part.strip() for part in text_value.split("-")]
    if len(parts) < 3:
        return facts

    collected: dict[str, object] = {}
    for part in parts:
        cleaned = text.clean_text(part)
        if not cleaned:
            continue
        socket = text.socket_from_text(cleaned)
        if socket:
            collected.setdefault("socket", socket)
        chipset = text.CHIPSET_RE.search(cleaned)
        if chipset:
            collected.setdefault("chipset", chipset.group(1).upper())
        memory = text.ddr(cleaned)
        if memory:
            collected.setdefault("memory_type", memory)
        form = text.form_factor(cleaned)
        if form:
            collected.setdefault("form_factor", form)
        wifi_on, wifi_std = text.wifi(cleaned)
        if wifi_on is not None:
            collected.setdefault("wireless", wifi_std or "Yes")
        lan = text.LAN_RE.search(cleaned)
        if lan:
            collected.setdefault("ethernet", f"{lan.group(1)}G LAN")

    _emit_legacy_keys(facts, category or "", SOURCE_FRAGMENTS, collected)
    return facts


def parse_hebrew_prose(category: str | None, description) -> dict[str, list[Fact]]:
    """Numeric facts from Ivory's Hebrew product prose.

    Only counts and clocks are read; no Hebrew text ever becomes a spec value
    (validate.py rejects Hebrew strings as a second net).
    """
    facts: dict[str, list[Fact]] = {}
    if not isinstance(description, str) or not text.HEBREW.search(description):
        return facts

    legacy: dict[str, object] = {}
    cores = text.HE_CORES_RE.search(description)
    if cores:
        legacy["cores"] = int(cores.group(1))
    threads = text.HE_THREADS_RE.search(description)
    if threads:
        legacy["threads"] = int(threads.group(1))
    clocks = text.HE_CLOCK_RE.search(description)
    if clocks:
        legacy["base_clock_ghz"] = float(clocks.group(1))
        legacy["boost_clock_ghz"] = float(clocks.group(2))
    if text.HE_COOLER_RE.search(description):
        legacy["cooler_included"] = True
    elif text.HE_NO_COOLER_RE.search(description):
        legacy["cooler_included"] = False

    if legacy:
        _emit_legacy_keys(facts, category or "", SOURCE_HE, legacy)
    return facts


SOURCE_OVERVIEW = "weak:1pc-overview"

# 1PC pages that carry no spec table at all keep one machine-written blurb:
# "Manufacturer: X, Product Type: Fan, Height: 163mm, Number of fans: 1, ...".
# ~480 listings, and `vendor_struct` skips the blob as prose. Only labels that
# name one schema fact AND print a unit-bearing value are read; everything else
# in the blob is marketing ("Additional Features", "Connectivity: Compatible
# with all motherboards") or boilerplate ("Not relevant").
_OVERVIEW_SPLIT_RE = re.compile(r",\s+(?=[A-Z][A-Za-z0-9 /&()+\-]{1,45}:\s)")

# label (lowercase) -> {category: legacy key}. Legacy keys resolve through the
# schema alias map, so a category without that field drops the fact.
_OVERVIEW_LABELS: dict[str, dict[str, str]] = {
    "number of processor cores": {"cpu": "cores"},
    "power": {"psu": "wattage_w"},
    "modular type": {"psu": "modular"},
    "modular": {"psu": "modular"},
    "efficiency": {"psu": "efficiency"},
    "rating": {"psu": "efficiency"},
    "height": {"cooler_air": "height_mm", "cooling_other": "height_mm"},
    "number of fans": {"cooler_air": "fan_count", "aio": "fan_count",
                       "cooling_other": "fan_count"},
    "fan diameter": {"cooler_air": "fan_size_mm", "aio": "fan_size_mm",
                     "cooling_other": "fan_size_mm"},
    "fan size": {"cooler_air": "fan_size_mm", "aio": "fan_size_mm",
                 "cooling_other": "fan_size_mm"},
    "radiator size": {"aio": "radiator_size_mm", "cooling_other": "radiator_size_mm"},
    "rotation speed": {"cooler_air": "rpm_max", "aio": "rpm_max",
                       "cooling_other": "rpm_max", "case_fan": "rpm_max"},
    "rotational speed": {"case_fan": "rpm_max", "cooler_air": "rpm_max"},
    "noise level": {"cooler_air": "noise_db", "aio": "noise_db",
                    "cooling_other": "noise_db", "case_fan": "noise_db"},
    "diameter": {"case_fan": "size_mm"},
    "size": {"case_fan": "size_mm"},
    "color": {"*": "color"},
    "memory type": {"memory": "memory_type", "gpu": "memory_type"},
    "frequency": {"memory": "speed_mhz"},
    "memory frequency": {"memory": "speed_mhz"},
    "voltage": {"memory": "voltage_v"},
    "bandwidth": {"gpu": "memory_bus_bit"},
    "read speed": {"storage": "read_speed_mbs"},
    "write speed": {"storage": "write_speed_mbs"},
}
_NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)")

# GPU overview rows that print the card's VRAM ("Internal Memory Size: 16GB
# GDDR6", "Memory: 8GB GDDR7"). Size and type share one cell, so they are
# split here instead of through _OVERVIEW_LABELS (one key per label).
_OVERVIEW_GPU_VRAM_LABELS = frozenset({
    "memory", "internal memory size", "video memory", "memory size",
    "graphics card memory size", "graphics card memory",
})
_VRAM_GB_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*GB\b", re.I)
_VRAM_TYPE_RE = re.compile(r"\b(GDDR\d+X?|HBM\d?)\b", re.I)


def _overview_value(label: str, value: str):
    """Reduce an overview value to the bare token coerce() understands."""
    value = value.strip().rstrip(".").strip()
    if not value or re.search(r"not (?:applicable|relevant|specified|available)",
                              value, re.I):
        return None
    if label in ("color", "modular type", "modular", "efficiency", "rating",
                 "memory type"):
        return value
    if label in ("noise level", "rotation speed", "rotational speed"):
        # "up to 24.4 dB(A)" / "up to 1600 RPM": the number is the maximum.
        match = _NUMBER_RE.search(value)
        return match.group(1).replace(",", ".") if match else None
    match = _NUMBER_RE.search(value)
    return match.group(1).replace(",", ".") if match else None


def parse_overview(category: str | None, meta) -> dict[str, list[Fact]]:
    """Facts from a 1PC `overview_text_raw` blob (detail pages with no table)."""
    facts: dict[str, list[Fact]] = {}
    if not isinstance(meta, dict):
        return facts
    detail = meta.get("detail_specs")
    blob = detail.get("overview_text_raw") if isinstance(detail, dict) else None
    if not isinstance(blob, str) or not blob.strip():
        return facts
    cat = category or ""
    legacy: dict[str, object] = {}
    for part in _OVERVIEW_SPLIT_RE.split(blob):
        if ":" not in part:
            continue
        label, _, value = part.partition(":")
        name = label.strip().lower()
        if cat == "gpu" and name in _OVERVIEW_GPU_VRAM_LABELS:
            size = _VRAM_GB_RE.search(value)
            if size:
                legacy.setdefault("memory_gb", size.group(1).replace(",", "."))
            kind = _VRAM_TYPE_RE.search(value)
            if kind:
                legacy.setdefault("memory_type", kind.group(1).upper())
            continue
        mapping = _OVERVIEW_LABELS.get(name)
        if not mapping:
            continue
        key = mapping.get(cat) or mapping.get("*")
        if key is None:
            continue
        cleaned = _overview_value(label.strip().lower(), value)
        if cleaned is not None:
            legacy.setdefault(key, cleaned)
    # The product-type line is a closed vocabulary on these pages.
    kind = re.search(r"Product Type:\s*([^,]+)", blob, re.I)
    if kind:
        product_type = kind.group(1).strip().lower()
        if cat == "memory" and "laptop" in product_type:
            legacy.setdefault("form_factor", "SO-DIMM")
        elif cat == "storage" and product_type.startswith("ssd"):
            legacy.setdefault("type", "SSD")
    if legacy:
        _emit_legacy_keys(facts, cat, SOURCE_OVERVIEW, legacy, confidence=0.55)
    return facts


def parse_weak(category: str | None, listing: dict) -> dict[str, list[Fact]]:
    """All Tier-3 facts for one listing."""
    facts = parse_fragments(category, listing.get("title_raw"))
    meta = listing.get("vendor_meta") or {}
    for key, value in parse_overview(category, meta).items():
        facts.setdefault(key, []).extend(value)
    for key, value in parse_plonter_tree(category, meta.get("tree")).items():
        facts.setdefault(key, []).extend(value)
    description = meta.get("description")
    for key, value in parse_hebrew_prose(category, description).items():
        facts.setdefault(key, []).extend(value)
    return facts
