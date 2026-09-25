"""
specs/resolvers/title_parse.py — Tier 2: typed regex extraction.

The regexes are ported verbatim from the retired extractors.py (same
coverage, same intent) but every branch now emits a TYPED schema field
instead of a free-form attribute key. What changed vs the old code:

- values are coerced (int/float/bool/enum) at emit time, so "65W" becomes
  the int 65 with the unit living in the field name (`tdp_w`);
- no alias/dupe folding, no `setdefault` ordering tricks — the merge engine
  handles conflicts by tier and logs them;
- CPU `tier`/`generation` and other UI-only facets are NOT emitted here:
  they are derived once in specs/derive.py from the typed facts.

Nothing here reads vendor payload structure; that is Tier 1.
"""

from __future__ import annotations

import re

from .. import canon, schema, text
from ..merge import TIER_TITLE, Fact, add_fact
from ..values import InvalidValue, coerce

SOURCE = "title"


def _emit(facts: dict, category: str, name: str, value, confidence: float = 1.0) -> None:
    field = schema.field_map(category).get(name)
    if field is None or value is None:
        return
    try:
        typed = coerce(field, value, category)
    except InvalidValue:
        return
    add_fact(facts, name, Fact(value=typed, tier=TIER_TITLE, source=SOURCE,
                               confidence=confidence))


def _collect(category: str, pairs) -> dict[str, list[Fact]]:
    """pairs: iterable of (field_name, raw_value[, confidence])."""
    facts: dict[str, list[Fact]] = {}
    for pair in pairs:
        name, value = pair[0], pair[1]
        confidence = pair[2] if len(pair) > 2 else 1.0
        _emit(facts, category, name, value, confidence)
    return facts


# --------------------------------------------------------------------------
# motherboard
# --------------------------------------------------------------------------


def parse_motherboard(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    chipset = None
    match = text.CHIPSET_RE.search(text_value)
    if match:
        raw = match.group(0).upper().replace(" ", "")
        # Strip a form-factor suffix the vendor glued on ("B760M" -> B760),
        # but keep real chipset letters (X570S).
        if raw not in schema.CHIPSET_INFO and len(raw) > 4 and raw[-1] in "MI":
            raw = raw[:-1]
        chipset = raw
        pairs.append(("chipset", raw, 1.0))

    info = schema.CHIPSET_INFO.get(chipset or "", (None, None))
    socket = text.socket_from_text(text_value) or info[0]
    if socket:
        pairs.append(("socket", socket))
    memory = text.ddr(text_value) or info[1]
    if memory:
        pairs.append(("memory_type", memory))

    form = text.form_factor(text_value)
    if form:
        pairs.append(("form_factor", form))
    elif match and match.group(2) in ("M", "I"):
        # "B760M" / "Z790I" with no size words: M = micro-ATX, I = mini-ITX.
        # (E/S/A suffixes are chipset variants, not sizes.)
        pairs.append(("form_factor",
                      "Micro-ATX" if match.group(2) == "M" else "Mini-ITX", 0.9))

    wifi_on, wifi_std = text.wifi(text_value)
    if wifi_on is not None:
        pairs.append(("wireless", wifi_std or "Yes", 0.9))

    lan = text.LAN_RE.search(text_value) or text.LAN_BASE_T_RE.search(text_value)
    if lan:
        pairs.append(("ethernet", f"{lan.group(1)}G LAN", 0.9))

    slots = text.SLOTS_RE.search(text_value)
    if slots:
        pairs.append(("memory_slots", int(slots.group(1))))
    else:
        dimms = text.DIMMS_RE.search(text_value)
        if dimms and 1 <= int(dimms.group(1)) <= 32:
            pairs.append(("memory_slots", int(dimms.group(1)), 0.9))

    memory_max = text.MEMORY_MAX_RE.search(text_value)
    if memory_max:
        pairs.append(("memory_max_gb", int(memory_max.group(1)), 0.9))

    m2 = text.M2_SLOTS_RE.search(text_value)
    if m2:
        pairs.append(("m2_slots", [f"M.2 x{m2.group(1)}"], 0.8))

    sata = text.SATA_PORTS_RE.search(text_value)
    if sata:
        pairs.append(("sata_ports", int(sata.group(1))))

    pcie_x16 = text.PCIE_X16_RE.search(text_value)
    if pcie_x16 and 1 <= int(pcie_x16.group(1)) <= 8:
        pairs.append(("pcie_x16_slots", int(pcie_x16.group(1))))

    pcie_x1 = text.PCIE_X1_RE.search(text_value)
    if pcie_x1:
        pairs.append(("pcie_x1_slots", int(pcie_x1.group(1))))

    if text.ECC_RE.search(text_value):
        pairs.append(("ecc_support", True, 0.9))

    return pairs


# --------------------------------------------------------------------------
# cpu
# --------------------------------------------------------------------------


def cpu_model(text_value: str) -> tuple[str | None, str | None]:
    """(manufacturer, model) — the same chain, in the same order, as before."""
    match = text.AMD_RYZEN_RE.search(text_value)
    if match:
        pro = "PRO " if match.group(2) else ""
        return "AMD", f"Ryzen {match.group(1)} {pro}{match.group(3).upper()}".strip()
    match = text.AMD_THREADRIPPER_RE.search(text_value)
    if match:
        pro = "PRO " if match.group(1) else ""
        return "AMD", f"Threadripper {pro}{match.group(2).upper()}".strip()
    match = text.AMD_APU_RE.search(text_value)
    if match:
        return "AMD", f"A{match.group(1)}-{match.group(2).upper()}"
    match = text.AMD_FX_RE.search(text_value)
    if match:
        return "AMD", f"FX-{match.group(1).upper()}"
    match = text.AMD_ATHLON_RE.search(text_value)
    if match:
        variant = f"{match.group(1).upper()} " if match.group(1) else ""
        return "AMD", f"Athlon {variant}{match.group(2).upper()}".strip()
    match = text.AMD_EPYC_CODENAME_RE.search(text_value)
    if match:
        return "AMD", f"EPYC {match.group(2).upper()}"
    match = text.INTEL_CPU_RE.search(text_value)
    if match:
        family = re.sub(r"\s+", " ", match.group(1).strip())
        if family.upper().startswith("ULTRA"):
            family = family.title()
        elif family.upper() in ("I3", "I5", "I7", "I9"):
            family = "i" + family[-1]
        else:
            family = family.upper()
        return "Intel", f"Core {family} {match.group(2).upper().strip()}"
    match = text.XEON_RE.search(text_value)
    if match:
        tier = (match.group(1) or "").upper()
        number = match.group(2).upper()
        if tier in ("W", "E"):
            return "Intel", f"Xeon {tier}-{number}"
        if tier:
            return "Intel", f"Xeon {tier.title()} {number}"
        return "Intel", f"Xeon {number}"
    match = text.EPYC_RE.search(text_value)
    if match:
        return "AMD", f"EPYC {match.group(1).upper()}"
    match = text.INTEL_CELERON_RE.search(text_value)
    if match:
        return "Intel", f"Celeron {match.group(1).upper()}"
    match = text.INTEL_PENTIUM_RE.search(text_value)
    if match:
        return "Intel", f"Pentium {match.group(1).upper()}"
    return None, None


def parse_cpu(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    socket = text.socket_from_text(text_value)
    if socket:
        pairs.append(("socket", socket))

    if text.CPU_PACKAGING_TRAY_RE.search(text_value):
        pairs.append(("packaging", "tray", 0.9))
    elif text.CPU_PACKAGING_BOX_RE.search(text_value):
        pairs.append(("packaging", "boxed", 0.9))

    tdp = text.TDP_RE.search(text_value)
    if tdp and 10 <= int(tdp.group(1)) <= 300:
        pairs.append(("tdp_w", int(tdp.group(1)), 0.8))

    # "32/64 Cores" (server SKUs) or "8 cores / 16 threads".
    cores: int | None = None
    threads: int | None = None
    both = re.search(r"\b(\d{1,3})\s*/\s*(\d{1,3})\s*cores?\b", text_value, re.I)
    if both:
        cores, threads = int(both.group(1)), int(both.group(2))
    else:
        both = re.search(r"\b(\d{1,3})\s*cores?\s*/\s*(\d{1,3})\s*threads?\b",
                         text_value, re.I)
        if both:
            cores, threads = int(both.group(1)), int(both.group(2))
    if not cores:
        if re.search(r"\bdual[-\s]?core\b", text_value, re.I):
            cores = 2
        else:
            match = re.search(r"\b(\d{1,3})\s*-?\s*cores?\b|\b(\d{1,3})\s*C\b",
                              text_value, re.I)
            value = (match.group(1) or match.group(2)) if match else None
            if value and 2 <= int(value) <= 128:
                cores = int(value)
    if not threads:
        match = re.search(r"\b(\d{1,3})\s*threads?\b", text_value, re.I)
        if match and 2 <= int(match.group(1)) <= 512:
            threads = int(match.group(1))
    if cores:
        pairs.append(("core_count", cores, 0.9))
    if threads:
        pairs.append(("thread_count", threads, 0.9))

    manufacturer, model = cpu_model(text_value)
    if manufacturer:
        pairs.append(("manufacturer", manufacturer))
    if model:
        pairs.append(("model", model))

    uhd = re.search(r"\bUHD\s*7[37]0\b", text_value, re.I)
    if uhd:
        pairs.append(("integrated_graphics", uhd.group(0).upper(), 0.8))
    elif manufacturer == "AMD" and re.search(r"\bRADEON\b", text_value, re.I):
        pairs.append(("integrated_graphics", "Radeon", 0.7))
    elif re.search(r"\b(?:CPU ONLY|NO GRAPHICS|WITHOUT GRAPHICS)\b", text_value, re.I):
        pairs.append(("integrated_graphics", "None", 0.7))

    series = re.search(r"\(?\bseries\s?(\d{1,2})\)?\b", text_value, re.I)
    if series and manufacturer == "Intel" and 1 <= int(series.group(1)) <= 4:
        pairs.append(("series", series.group(1), 0.8))

    if text.CPU_COOLER_EXCLUDED_RE.search(text_value):
        pairs.append(("includes_cooler", False, 0.8))
    elif text.CPU_COOLER_INCLUDED_RE.search(text_value):
        pairs.append(("includes_cooler", True, 0.8))
    return pairs


# --------------------------------------------------------------------------
# gpu
# --------------------------------------------------------------------------

# Board partners only: a bare "AMD"/"Intel" in a GPU title is the chip maker,
# not the manufacturer (PCPP's field is the board partner).
_GPU_BRAND_TOKENS = tuple(
    sorted((token for token in canon.BRANDS if token not in ("amd", "intel", "nvidia")),
           key=len, reverse=True)
)


def parse_gpu(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    for token in _GPU_BRAND_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", text_value, re.I):
            pairs.append(("manufacturer", canon.BRANDS[token]))
            break

    chip = text.GPU_CHIP_RE.search(text_value)
    if chip:
        pairs.append(("chipset", re.sub(r"\s+", " ", chip.group(1).upper().strip())))

    vram = text.VRAM_RE.search(text_value)
    if vram and 1 <= int(vram.group(1)) <= 64:
        pairs.append(("memory_gb", int(vram.group(1)), 0.9))

    gmem = text.GMEM_RE.search(text_value)
    if gmem:
        if gmem.group(1):
            kind, generation = "S", gmem.group(1).upper()
        elif gmem.group(2):
            kind, generation = "GDDR", gmem.group(2).upper()
        else:
            kind, generation = "HBM", (gmem.group(3) or "2")
        pairs.append(("memory_type", f"{kind}{generation}", 0.9))

    clocks = [int(c) for c in text.CORE_CLOCK_RE.findall(text_value)
              if 500 <= int(c) <= 3500]
    if len(clocks) == 1:
        pairs.append(("boost_clock_mhz", clocks[0], 0.7))
    elif len(clocks) >= 2:
        pairs.append(("core_clock_mhz", min(clocks), 0.7))
        pairs.append(("boost_clock_mhz", max(clocks), 0.7))
    boost = text.BOOST_CLOCK_RE.search(text_value)
    if boost and 500 <= int(boost.group(1)) <= 3500:
        pairs.append(("boost_clock_mhz", int(boost.group(1)), 0.9))

    for tdp in re.finditer(r"\b(\d{2,3})\s?W\b", text_value, re.I):
        if 15 <= int(tdp.group(1)) <= 700:
            pairs.append(("tdp_w", int(tdp.group(1)), 0.7))
            break

    length = text.LENGTH_MM_RE.search(text_value)
    if length and 100 <= int(length.group(1)) <= 500:
        pairs.append(("length_mm", int(length.group(1)), 0.8))

    if text.PCIE_INTERFACE_RE.search(text_value):
        generation = re.search(r"PCI\s*E?\s*(\d)\.0", text_value, re.I)
        pairs.append(("interface", f"PCIe {generation.group(1)}.0 x16" if generation
                      else "PCIe x16", 0.8))

    slot = text.SLOT_WIDTH_RE.search(text_value)
    if slot:
        pairs.append(("slot_width", float(slot.group(1)), 0.8))

    if re.search(r"\bLIQUID\b|\bAIO\b", text_value, re.I):
        pairs.append(("cooling", "Liquid", 0.8))
    elif re.search(r"\bPASSIVE\b|\bFANLESS\b", text_value, re.I):
        pairs.append(("cooling", "Passive", 0.8))
    elif re.search(r"\bAIR\b|\bFAN\b", text_value, re.I):
        pairs.append(("cooling", "Air", 0.6))

    power = re.findall(r"(\d+)\s?X\s?(8[-\s]?PIN|6[-\s]?PIN|16[-\s]?PIN|12VHPWR|12V-2X6)",
                       text_value, re.I)
    if power:
        pairs.append(("external_power",
                      [f"{count}x {kind.upper().replace(' ', '-')}" for count, kind in power],
                      0.8))

    ports: dict[str, int] = {}
    for key, pattern in (("HDMI", r"(\d+)\s?X\s?HDMI"),
                         ("DisplayPort", r"(\d+)\s?X\s?DISPLAYPORT|(\d+)\s?X\s?DP\b"),
                         ("DVI", r"(\d+)\s?X\s?DVI")):
        match = re.search(pattern, text_value, re.I)
        if match:
            count = next((g for g in match.groups() if g), None)
            if count:
                ports[key] = int(count)
    if "HDMI" in ports:
        pairs.append(("hdmi_outputs", {"HDMI": ports["HDMI"]}, 0.7))
    if "DisplayPort" in ports:
        pairs.append(("dp_outputs", {"DisplayPort": ports["DisplayPort"]}, 0.7))
    if "DVI" in ports:
        pairs.append(("dvi_outputs", {"DVI": ports["DVI"]}, 0.7))

    fan = re.search(r"(\d)\s?X\s?FAN", text_value, re.I)
    if fan:
        pairs.append(("fan_count", int(fan.group(1)), 0.8))

    if re.search(r"\bG-?SYNC\b", text_value, re.I):
        pairs.append(("frame_sync", "G-Sync", 0.8))
    elif re.search(r"\bFREE-?SYNC\b", text_value, re.I):
        pairs.append(("frame_sync", "FreeSync", 0.8))
    return pairs


# --------------------------------------------------------------------------
# psu
# --------------------------------------------------------------------------


def parse_psu(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    watts = text.WATT_RE.search(text_value)
    if watts and 100 <= int(watts.group(1)) <= 3000:
        pairs.append(("wattage_w", int(watts.group(1)), 0.9))
    elif re.search(r"\b(PSU|POWER\s*SUPPLY)\b", text_value, re.I):
        # Models like "Ai1300P" carry the wattage without a W suffix.
        fallback = text.WATT_PSU_FALLBACK_RE.search(text_value)
        if fallback:
            value = int(fallback.group(1))
            if 100 <= value <= 3000 and value not in (100, 120):
                pairs.append(("wattage_w", value, 0.8))

    cert = text.EFF_RE.search(text_value)
    if cert:
        pairs.append(("efficiency", f"80+ {cert.group(1).title()}", 0.9))
    else:
        shorthand = re.search(r"\b80\s?\+?\s?(GOLD|SILVER|BRONZE|PLATINUM|TITANIUM)\b",
                              text_value, re.I)
        metal = shorthand or re.search(
            r"\b(GOLD|SILVER|BRONZE|PLATINUM|TITANIUM)\b", text_value, re.I)
        if metal:
            pairs.append(("efficiency", f"80+ {metal.group(1).title()}", 0.7))

    modular = text.MOD_RE.search(text_value)
    if modular:
        pairs.append(("modular", modular.group(1), 0.9))

    length = re.search(r"\b(\d{2,3})\s?MM\b", text_value, re.I)
    if length and 100 <= int(length.group(1)) <= 250:
        pairs.append(("length_mm", int(length.group(1)), 0.7))

    if text.FANLESS_RE.search(text_value):
        pairs.append(("fanless", True, 0.9))

    if re.search(r"\bSFX[-\s]?L\b", text_value, re.I):
        pairs.append(("type", "SFX-L", 0.9))
    elif re.search(r"\bSFX\b", text_value, re.I):
        pairs.append(("type", "SFX", 0.9))
    elif re.search(r"\bFLEX\s?ATX\b", text_value, re.I):
        pairs.append(("type", "Flex ATX", 0.9))
    elif re.search(r"\bTFX\b", text_value, re.I):
        pairs.append(("type", "TFX", 0.9))
    elif re.search(r"\bATX\b", text_value, re.I):
        pairs.append(("type", "ATX", 0.7))

    version = re.search(r"\bATX\s?(3\.\d|2\.\d)\b", text_value, re.I)
    if version:
        pairs.append(("atx_version", f"ATX {version.group(1)}", 0.8))

    # Color: blank certification phrases first — "80 PLUS Gold" is a cert, not
    # a paint job (this produced 189 bogus color=Gold PSUs before the fix).
    color_text = re.sub(
        r"\b80\s?PLUS\b(\s+[A-Za-z]+)?|\bCYBENETICS\b(\s+[A-Za-z]+)?", " ",
        text_value, flags=re.I)
    for color in canon.COLOR_WORDS:
        if color in ("gold", "silver", "bronze", "platinum", "titanium"):
            continue
        if re.search(rf"\b{color}\b", color_text, re.I):
            pairs.append(("color", color.title(), 0.7))
            break

    sata = re.search(r"(\d+)\s?X\s?SATA", text_value, re.I)
    if sata:
        pairs.append(("sata_connectors", int(sata.group(1)), 0.8))
    pcie = re.search(r"(\d+)\s?X\s?PCIE", text_value, re.I)
    if pcie:
        pairs.append(("pcie8_connectors", int(pcie.group(1)), 0.6))
    eps = re.search(r"(\d+)\s?X\s?(EPS|CPU|ATX\s*12V)", text_value, re.I)
    if eps:
        pairs.append(("eps8_connectors", int(eps.group(1)), 0.7))
    if re.search(r"12VHPWR|12V-2X6", text_value, re.I):
        pairs.append(("pcie16_connectors", 1, 0.8))

    if re.search(r"\bARGB\b", text_value, re.I):
        pairs.append(("lighting", "ARGB", 0.7))
    elif re.search(r"\bRGB\b", text_value, re.I):
        pairs.append(("lighting", "RGB", 0.7))
    return pairs


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------

# JEDEC/XMP/EXPO speed whitelist for bare 4-digit numbers in a title
# (years like 2024/2025 and MPN fragments must never match).
_BARE_SPEEDS = (
    "1600|1866|2133|2400|2666|2933|3200|3400|3600|4000|4133|4400|4800|5200|"
    "5400|5600|6000|6200|6400|6600|6800|7000|7200|7400|7600|7800|8000|8200|"
    "8400|8533|8800|9000"
)


def parse_memory(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    memory_type = text.ddr(text_value)
    if memory_type:
        pairs.append(("memory_type", memory_type))

    gb_values = [int(v) for v in re.findall(r"\b(\d{1,3})\s?GB\b", text_value, re.I)
                 if 2 <= int(v) <= 256]
    total = max(gb_values) if gb_values else None
    if total is None:
        match = re.search(r"\b(\d{1,3})\s?G\b", text_value, re.I)
        if (match and 2 <= int(match.group(1)) <= 256
                and re.search(r"\b(RAM|MEMORY|DDR)\b", text_value, re.I)):
            total = int(match.group(1))

    modules: int | None = None
    per_module: int | None = None
    kit = text.KIT_RE.search(text_value)
    if kit:
        modules, per_module = int(kit.group(1)), int(kit.group(2))
    else:
        alt = text.KIT_ALT_RE.search(text_value)
        if alt:
            modules, per_module = int(alt.group(1)), int(alt.group(2))
    if modules and not 1 <= modules <= 8:
        modules = None
    if per_module and not 1 <= per_module <= 64:
        per_module = None
    if modules:
        pairs.append(("module_count", modules, 0.9))
    if per_module:
        pairs.append(("module_size_gb", per_module, 0.9))
    if modules and per_module:
        # The kit parenthetical is the most reliable capacity statement.
        total = modules * per_module
    if total:
        pairs.append(("total_gb", total, 0.9))

    speed: int | None = None
    match = text.SPEED_RE.search(text_value) or text.SPEED_DDR_RE.search(text_value)
    if match:
        speed = int(match.group(1))
    if speed is None:
        match = re.search(r"GB\s+(\d{4})\b", text_value, re.I)
        if match and 1600 <= int(match.group(1)) <= 9000:
            speed = int(match.group(1))
    if speed is None:
        match = re.search(rf"\b({_BARE_SPEEDS})\b", text_value)
        if match:
            speed = int(match.group(1))
    if speed and 800 <= speed <= 12000:
        pairs.append(("speed_mhz", speed))
        label = canon.canon_speed_string(memory_type, speed) if memory_type else None
        pairs.append(("speed", label or str(speed)))

    cas = text.CL_RE.search(text_value)
    if cas:
        cas_value = int(cas.group(1))
        pairs.append(("cas_latency", cas_value, 0.9))
        if speed:
            pairs.append(("first_word_latency_ns", round(cas_value * 2000 / speed, 1), 0.8))

    voltage = text.VOLTAGE_RE.search(text_value)
    if voltage:
        pairs.append(("voltage_v", float(voltage.group(1)), 0.9))

    timing = text.TIMING_RE.search(text_value)
    if timing:
        pairs.append(("timing", timing.group(1), 0.9))

    if text.ECC_RE.search(text_value):
        pairs.append(("ecc", True, 0.9))
    if text.REGISTERED_RE.search(text_value):
        pairs.append(("registered", True, 0.8))
    if text.HEAT_SPREADER_RE.search(text_value):
        pairs.append(("heat_spreader", True, 0.7))
    if re.search(r"\bARGB\b", text_value, re.I):
        pairs.append(("lighting", "ARGB", 0.8))
    elif re.search(r"\bRGB\b", text_value, re.I):
        pairs.append(("lighting", "RGB", 0.8))

    if re.search(r"\bSO-?DIMM\b", text_value, re.I):
        pairs.append(("form_factor", "SO-DIMM", 0.9))
    elif re.search(r"\bDIMM\b", text_value, re.I):
        pairs.append(("form_factor", "DIMM", 0.8))
    return pairs


# --------------------------------------------------------------------------
# case
# --------------------------------------------------------------------------


def parse_case(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    case_type = text.case_form_factor(text_value)
    if case_type:
        pairs.append(("type", case_type, 0.9))

    if re.search(r"\bTEMPERED\s*GLASS\b", text_value, re.I):
        pairs.append(("side_panel", "Tinted Tempered Glass"
                      if re.search(r"\bTINTED\b", text_value, re.I)
                      else "Tempered Glass", 0.9))
    elif re.search(r"\bMESH\b", text_value, re.I):
        pairs.append(("side_panel", "Mesh", 0.6))
    elif re.search(r"\bACRYLIC\b", text_value, re.I):
        pairs.append(("side_panel", "Acrylic", 0.8))

    if re.search(r"\bNO\s+PSU\b|\bWITHOUT\s+PSU\b", text_value, re.I):
        pairs.append(("psu_included", "None", 0.9))
    elif re.search(r"\bWITH\s+PSU\b|\bPSU\s+INCLUDED\b|\b\d{3,4}W\s+PSU\b", text_value, re.I):
        included = re.search(r"\b(\d{3,4})W\s+PSU\b", text_value, re.I)
        pairs.append(("psu_included",
                      f"{included.group(1)}W" if included else "Included", 0.8))

    volume = re.search(r"\b(\d+(?:\.\d+)?)\s?L\b", text_value, re.I)
    if volume:
        pairs.append(("volume_l", float(volume.group(1)), 0.7))

    bays_35 = re.search(r"(\d+)\s?X\s?3\.5", text_value, re.I)
    if bays_35:
        pairs.append(("drive_bays_35", int(bays_35.group(1)), 0.8))
    bays_25 = re.search(r"(\d+)\s?X\s?2\.5", text_value, re.I)
    if bays_25:
        pairs.append(("drive_bays_25", int(bays_25.group(1)), 0.8))

    slots = re.search(r"(\d+)\s?X?\s?EXPANSION\s*SLOTS?", text_value, re.I)
    if slots:
        pairs.append(("expansion_slots", f"{slots.group(1)} full-height", 0.8))

    max_gpu = (re.search(r"(\d{2,3})\s?MM.*?(?:GPU|VGA|VIDEO)", text_value, re.I)
               or re.search(r"(?:GPU|VGA|VIDEO).*?(\d{2,3})\s?MM", text_value, re.I))
    if max_gpu and 150 <= int(max_gpu.group(1)) <= 600:
        pairs.append(("max_gpu_length_mm", int(max_gpu.group(1)), 0.7))

    max_cooler = re.search(r"(?:COOLER).*?(\d{2,3})\s?MM", text_value, re.I)
    if max_cooler and 100 <= int(max_cooler.group(1)) <= 300:
        pairs.append(("max_cooler_height_mm", int(max_cooler.group(1)), 0.7))

    radiator = text.FAN_SIZE_MM_RE.search(text_value)
    if radiator and int(radiator.group(1)) >= 120:
        pairs.append(("radiator_support", {f"{radiator.group(1)} mm": 1}, 0.6))

    if re.search(r"\bARGB\b", text_value, re.I):
        pairs.append(("lighting", "ARGB", 0.7))
    elif re.search(r"\bRGB\b", text_value, re.I):
        pairs.append(("lighting", "RGB", 0.7))
    return pairs


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------


def parse_storage(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    capacities = []
    for number, unit in text.CAPACITY_RE.findall(text_value):
        gb = int(float(number) * 1000) if unit.upper() == "TB" else int(float(number))
        if 80 <= gb <= 30000:
            capacities.append(gb)
    if capacities:
        pairs.append(("capacity_gb", max(capacities), 0.9))

    kind = text.STORAGE_TYPE_RE.search(text_value)
    if kind:
        pairs.append(("type", kind.group(1), 0.9))
    elif re.search(r"\bM\.2\b", text_value, re.I):
        pairs.append(("type", "SSD", 0.7))

    form = text.FORM_FACTOR_STORAGE_RE.search(text_value)
    if form:
        pairs.append(("form_factor", form.group(1), 0.9))

    nvme = bool(re.search(r"\bNVME\b|\bM\.2\b", text_value, re.I))
    if nvme:
        pairs.append(("nvme", True, 0.9))

    generation = text.PCIE_GEN_RE.search(text_value)
    if generation:
        pairs.append(("pcie_gen", int(generation.group(1)), 0.9))
        pairs.append(("interface", f"M.2 PCIe {generation.group(1)}.0 x4", 0.9))
    elif nvme:
        pairs.append(("interface", "M.2 PCIe NVMe" if re.search(r"\bM\.2\b", text_value, re.I)
                      else "NVMe", 0.8))
    elif re.search(r"\bSATA\b", text_value, re.I):
        pairs.append(("interface", "SATA 6.0 Gb/s", 0.8))
    elif re.search(r"\bSAS\b", text_value, re.I):
        pairs.append(("interface", "SAS", 0.9))
    elif re.search(r"\bPCI\s?E\b", text_value, re.I):
        pairs.append(("interface", "PCIe", 0.6))

    cache = text.CACHE_RE.search(text_value)
    if cache and 8 <= int(cache.group(1)) <= 8192:
        pairs.append(("cache_mb", int(cache.group(1)), 0.8))

    rpm = text.RPM_RE.search(text_value)
    if rpm and 3000 <= int(rpm.group(1)) <= 15000:
        pairs.append(("rpm", int(rpm.group(1)), 0.9))
    elif re.search(r"\bHDD\b", text_value, re.I):
        bare = re.search(r"\b(5400|7200|10000|15000)\b", text_value)
        if bare:
            pairs.append(("rpm", int(bare.group(1)), 0.7))
    return pairs


# --------------------------------------------------------------------------
# cpu coolers (aio + air + cooling_other)
# --------------------------------------------------------------------------

_RADIATOR_SIZES = {"120", "140", "240", "280", "360", "420", "480"}


def parse_cooler(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    water = bool(text.WATER_COOLED_RE.search(text_value))
    if water:
        pairs.append(("water_cooled", True, 0.9))

    size = text.FAN_SIZE_MM_RE.search(text_value)
    if not size:
        # Bare sizes in cooler titles ("MAG CORELIQUID E360", "Skeleton 360")
        # can only be fan/radiator sizes: RPM runs 4-digit+, model prefixes
        # like H100i never hit this set.
        size = re.search(r"(?:(?<=[A-Z])|(?<![\w]))(120|140|240|280|360|420)(?![\w])",
                         text_value)
    if size:
        value = int(size.group(1))
        if water or str(value) in _RADIATOR_SIZES and value >= 240:
            pairs.append(("radiator_size_mm", value, 0.8))
        else:
            pairs.append(("fan_size_mm", value, 0.8))

    fans = re.search(r"(\d)\s?X\s?(?:FAN|120|140)", text_value, re.I)
    if fans and 1 <= int(fans.group(1)) <= 6:
        pairs.append(("fan_count", int(fans.group(1)), 0.7))

    sockets = {re.sub(r"\s+", "", s).upper() for s in text.SOCKET_LIST_RE.findall(text_value)}
    if sockets:
        pairs.append(("sockets", sorted(sockets), 0.8))

    height = re.search(r"(?:HEIGHT|גובה)\D{0,12}?(\d{2,3})\s?MM", text_value, re.I)
    if height and 20 <= int(height.group(1)) <= 300:
        pairs.append(("height_mm", int(height.group(1)), 0.8))

    rpm = text.RPM_RE.search(text_value)
    if rpm:
        pairs.append(("fan_rpm_max", int(rpm.group(1)), 0.8))

    noise = text.NOISE_DB_RE.search(text_value)
    if noise:
        pairs.append(("noise_db", float(noise.group(1)), 0.8))

    airflow = text.AIRFLOW_RE.search(text_value)
    if airflow:
        pairs.append(("airflow_cfm", float(airflow.group(1)), 0.8))

    if re.search(r"\bFANLESS\b|\bPASSIVE\b", text_value, re.I):
        pairs.append(("fanless", True, 0.8))

    if re.search(r"\bARGB\b", text_value, re.I):
        pairs.append(("lighting", "ARGB", 0.8))
    elif re.search(r"\bRGB\b", text_value, re.I):
        pairs.append(("lighting", "RGB", 0.8))
    return pairs


# --------------------------------------------------------------------------
# case fans
# --------------------------------------------------------------------------


def parse_case_fan(text_input: str) -> list[tuple]:
    text_value = text.clean_text(text_input)
    pairs: list[tuple] = []

    size = text.FAN_SIZE_MM_RE.search(text_value)
    if not size:
        size = re.search(r"(?:(?<=[A-Z])|(?<![\w]))(80|92|120|140|170|200)(?![\w])",
                         text_value)
    if size:
        pairs.append(("size_mm", int(size.group(1)), 0.9))

    pack = re.search(r"\b(\d)\s?-?\s?(?:PACK|PCS|FANS?\b)", text_value, re.I)
    if pack and 2 <= int(pack.group(1)) <= 6:
        pairs.append(("quantity", int(pack.group(1)), 0.8))

    if re.search(r"\bPWM\b", text_value, re.I):
        pairs.append(("pwm", True, 0.9))
    if re.search(r"\bPST\b|\bPWM\b", text_value, re.I):
        pairs.append(("connector", "4-pin", 0.6))
    elif re.search(r"\b3[-\s]?PIN\b", text_value, re.I):
        pairs.append(("connector", "3-pin", 0.8))

    rpm = text.RPM_RE.search(text_value)
    if rpm:
        pairs.append(("rpm_max", int(rpm.group(1)), 0.8))

    noise = text.NOISE_DB_RE.search(text_value)
    if noise:
        pairs.append(("noise_db", float(noise.group(1)), 0.8))

    airflow = text.AIRFLOW_RE.search(text_value)
    if airflow:
        pairs.append(("airflow_cfm", float(airflow.group(1)), 0.8))

    if re.search(r"\bREVERSE\b", text_value, re.I):
        pairs.append(("flow_direction", "reverse", 0.9))

    if re.search(r"\bARGB\b|\bADDRESSABLE\b", text_value, re.I):
        pairs.append(("led", "ARGB", 0.8))
    elif re.search(r"\bRGB\b|\bLED\b", text_value, re.I):
        pairs.append(("led", "RGB", 0.7))

    for color in canon.COLOR_WORDS:
        if re.search(rf"\b{color}\b", text_value, re.I):
            pairs.append(("color", color.title(), 0.7))
            break
    return pairs


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

PARSERS = {
    "cpu": parse_cpu,
    "motherboard": parse_motherboard,
    "gpu": parse_gpu,
    "psu": parse_psu,
    "memory": parse_memory,
    "storage": parse_storage,
    "case": parse_case,
    "case_fan": parse_case_fan,
    "aio": parse_cooler,
    "cooler_air": parse_cooler,
    "cooling_other": parse_cooler,
}


def parse_title(category: str | None, text_input: str) -> dict[str, list[Fact]]:
    """Tier-2 facts for one listing's title/SKU text."""
    parser = PARSERS.get(category or "")
    if parser is None or not text_input:
        return {}
    return _collect(category or "", parser(text_input))
