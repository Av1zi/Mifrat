"""
icecat/mapping.py - Icecat feature names -> schema fields, per category.

Icecat feature names are stable English ("Number of fans", "Maximum CPU cooler
height") and its raw `Value` is in the feature's base unit (mm, g, MHz, GB,
W), so most rows are a straight read. Every value still goes through
mfr.common.typed(), which drops anything the schema would reject.
"""

from __future__ import annotations

import re

from ..mfr.common import mb_form_factor_list, psu_length, typed

# Fields whose Icecat values disagreed with sourced (vendor / maker /
# reference) values more than TRUST_MAX_DISAGREE on the catalog
# (`python -m scraper.icecat --trust`). They are parsed but never merged.
TRUST_MAX_DISAGREE = 0.03
DISABLED: dict[str, frozenset] = {
    # The 990 PRO's sheet says MLC; Samsung's datasheet says TLC.
    "storage": frozenset({"nand"}),
    # Sheets count every physical x16-length slot (an ASUS B860M MAX GAMING
    # "has" four) and print "ECC & non-ECC" for consumer Intel boards whose
    # chipset has no ECC.
    "motherboard": frozenset({"pcie_x16_slots", "ecc_support",
                              # 'Brown' on black boards; BIOS-dependent memory
                              # ceilings (256 vs 192GB); x1 counts off by one.
                              "color", "memory_max_gb", "pcie_x1_slots"}),
    # Length is sometimes the card's height (a 3090 'length' of 126 mm); the
    # memory data rate and the minimum PSU differ from the chip and partner
    # figures retailers print.
    "gpu": frozenset({"length_mm", "memory_speed_gbps", "recommended_psu_w"}),
}

# Measured over the limit on the full Oct 2026 run (787 sheets, `--trust` on a
# catalog built without Icecat): disabled mechanically rather than reviewed one
# by one. Many are definitional (a case's box vs product dimensions, OC vs
# gaming-mode boost clocks, 77 vs 56 CFM for the same fan); a field is
# re-enabled by moving it to REVIEWED_OVER with the evidence.
_MEASURED_OVER: dict[str, frozenset] = {
    "aio": frozenset({'airflow_cfm', 'lighting', 'sockets'}),
    "case": frozenset({'dimensions_mm', 'drive_bays_25', 'drive_bays_35', 'expansion_slots', 'fan_front', 'fan_rear', 'fan_side', 'fan_top', 'max_gpu_length_mm', 'radiator_support', 'type', 'weight_kg'}),
    "case_fan": frozenset({'airflow_cfm', 'connector', 'noise_db', 'quantity', 'rpm_max'}),
    "cooler_air": frozenset({'fan_rpm_max', 'height_mm', 'sockets'}),
    "gpu": frozenset({'boost_clock_mhz', 'max_resolution'}),
    "memory": frozenset({'cas_latency', 'color', 'voltage_v'}),
    "motherboard": frozenset({'m2_slots', 'memory_speeds'}),
    "psu": frozenset({'molex4_connectors', 'sata_connectors'}),
    "storage": frozenset({'capacity_gb', 'form_factor', 'interface', 'pcie_gen', 'read_speed_mbs', 'write_speed_mbs'}),
}
# Found by the inference-rule backtest once Icecat values counted as sourced
# (a sheet shared between sibling SKUs): the title says Black / White / 8G and
# the sheet says Bronze / 16 GB; ASUS non-WiFi boards get a WiFi sheet's
# Bluetooth; DDR5 on-die ECC reads as ECC.
_MEASURED_OVER["gpu"] = _MEASURED_OVER["gpu"] | {"color", "memory_gb"}
_MEASURED_OVER["motherboard"] = _MEASURED_OVER["motherboard"] | {"bluetooth"}
_MEASURED_OVER["memory"] = _MEASURED_OVER.get("memory", frozenset()) | {"ecc"}
_MEASURED_OVER["cooling_other"] = _MEASURED_OVER.get("cooling_other", frozenset()) | {"color"}
for _category, _fields in _MEASURED_OVER.items():
    DISABLED[_category] = DISABLED.get(_category, frozenset()) | _fields

# Fields over the limit where the review found the SOURCED side wrong, so they
# stay enabled (and outrank the retailer). Re-check after a vendor parser fix.
REVIEWED_OVER: dict[str, frozenset] = {
    # Retailer cells list port kinds ("HDMI | DisplayPort"), and the old parser
    # read them as one of each; the partner sheets give real counts
    # (RTX 3070 Ti GAMING OC: 2 HDMI + 2 DP).
    # (gpu colour was reviewed here once; the backtest showed the sheet is the
    # wrong side - it is DISABLED above.)
    "gpu": frozenset({"dp_outputs", "hdmi_outputs"}),
    # Retailers print "Wi-Fi 6" for Gigabyte's AX boards that ship Wi-Fi 6E
    # (B650 AORUS PRO AX, B760M AORUS ELITE AX: RZ616 / AX211 modules).
    "motherboard": frozenset({"wireless"}),
}


def _yes(value) -> bool | None:
    text = str(value or "").strip().upper()
    if text in ("Y", "YES"):
        return True
    if text in ("N", "NO"):
        return False
    return None


def _num(value) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", "."))
    return float(match.group(0)) if match else None


def _int(value) -> int | None:
    number = _num(value)
    return int(round(number)) if number is not None else None


def _fan_mount(count, sizes) -> str | None:
    """'3' + '120,140' -> '3 x 120 mm, 3 x 140 mm' (the catalog's fan-mount
    spelling): the max count is stated once for every listed size."""
    n = _int(count)
    if n is None:
        return None
    if n == 0:
        return "No"
    diameters = [int(s) for s in re.findall(r"\d{2,3}", str(sizes or ""))]
    if not diameters:
        return None
    return ", ".join(f"{n} x {d} mm" for d in diameters)


def _radiators(*values) -> dict | None:
    sizes: set[int] = set()
    for value in values:
        sizes.update(int(s) for s in re.findall(r"\d{3}", str(value or "")))
    return {f"{s} mm": 1 for s in sorted(sizes)} or None


def _pcie_interface(value) -> str | None:
    match = re.search(r"(\d)\.0", str(value or ""))
    return f"PCIe {match.group(1)}.0 x16" if match else None


def _memory_type(value) -> str | None:
    match = re.search(r"\b(DDR\dX?|GDDR\dX?|HBM\d?)", str(value or ""), re.I)
    return match.group(1).upper() if match else None


def _ddr(value) -> str | None:
    match = re.search(r"\bDDR(\d)", str(value or ""), re.I)
    return f"DDR{match.group(1)}" if match else None


def _layout(value) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*x\s*(\d+)", str(value or ""))
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)


def _modular(value) -> str | None:
    text = str(value or "").lower()
    if "semi" in text:
        return "semi"
    if "non" in text:
        return "no"
    if "full" in text:
        return "full"
    return None


def _dims_case(f) -> str | None:
    w, h, d = (_int(f.get("Width")), _int(f.get("Height")), _int(f.get("Depth")))
    return f"W={w} H={h} D={d}mm" if w and h and d else None


def _dims_drive(f) -> str | None:
    values = [f.get(k) for k in ("Width", "Depth", "Height")]
    if not all(values):
        return None
    return " x ".join(f"{_num(v):g}" for v in values) + " mm"


def _color(value) -> str | None:
    text = str(value or "").replace(",", " / ")
    return text or None


def _wifi(value) -> str | None:
    match = re.search(r"Wi-?Fi\s?(\d[E]?)", str(value or ""), re.I)
    return f"Wi-Fi {match.group(1).upper()}" if match else None


def _bluetooth(value) -> str | None:
    number = _num(value)
    return f"Bluetooth {number:g}" if number else None


def _ethernet(value) -> str | None:
    text = str(value or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*Gigabit", text, re.I)
    if match:
        return f"LAN {float(match.group(1)):g} Gb/s"
    if re.search(r"\bGigabit\b", text, re.I):
        return "LAN 1 Gb/s"
    return None


def _lighting(f) -> str | None:
    lit = _yes(f.get("Illumination")) if "Illumination" in f else _yes(f.get("Illumination LED"))
    if lit is False:
        return "No"
    colour = str(f.get("Illumination colour") or f.get("Backlight colour") or "")
    if lit and re.search(r"multi|rgb", colour, re.I):
        return "RGB"
    return None


def specs_for(category: str, features: dict) -> dict:
    """{field: typed value} from one product's Icecat features ({name: Value})."""
    f = features
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None or field in out:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    put("color", _color(f.get("Product colour")))
    if category == "gpu":
        put("fan_count", _int(f.get("Number of fans")))
        put("memory_gb", _int(f.get("Discrete graphics card memory")))
        put("memory_type", _memory_type(f.get("Graphics card memory type")))
        put("memory_bus_bit", _int(f.get("Memory bus")))
        clock = _int(f.get("Memory clock speed"))
        if clock and clock >= 10000:
            put("memory_speed_gbps", round(clock / 1000))
        put("interface", _pcie_interface(f.get("Interface type")))
        put("hdmi_outputs", {"HDMI": _int(f.get("HDMI ports quantity"))}
            if _int(f.get("HDMI ports quantity")) is not None else None)
        put("dp_outputs", {"DisplayPort": _int(f.get("DisplayPorts quantity"))}
            if _int(f.get("DisplayPorts quantity")) is not None else None)
        put("max_resolution", f.get("Maximum resolution"))
        put("max_displays", _int(f.get("Maximum displays per videocard")))
        put("recommended_psu_w", _int(f.get("Minimum system power supply")))
        power = f.get("Supplementary power connectors")
        if power:
            plugs = [p.strip() for p in re.split(r",|\+| and ", str(power)) if p.strip()]
            put("external_power", ["no"] if re.search(r"^none$|^no$", str(power), re.I) else plugs)
        put("length_mm", _int(f.get("Length")))
        put("boost_clock_mhz", _int(f.get("Processor boost clock speed")))
        put("core_clock_mhz", _int(f.get("Processor frequency"))
            if f.get("Processor boost clock speed") else None)
        if f.get("Processor frequency") and not f.get("Processor boost clock speed"):
            # Partner sheets print the boost clock as "Processor frequency"
            # (GV-N5070WF3OC: 2542 MHz is its boost).
            put("boost_clock_mhz", _int(f.get("Processor frequency")))
        if str(f.get("Cooling type") or "").lower() == "passive":
            put("cooling", "Passive")
        put("lighting", _lighting(f))
    elif category == "motherboard":
        put("socket", f.get("Processor socket"))
        put("chipset", f.get("Motherboard chipset"))
        put("form_factor", f.get("Motherboard form factor"))
        put("memory_type", _ddr(f.get("Supported memory types")))
        put("memory_slots", _int(f.get("Number of memory slots")))
        put("memory_max_gb", _int(f.get("Maximum internal memory")))
        speeds = f.get("Supported memory clock speeds")
        if speeds:
            put("memory_speeds", sorted({s for s in re.findall(r"\d{4}", str(speeds))},
                                        key=int, reverse=True))
        elif f.get("Supported memory clock speed (max)"):
            put("memory_speeds", [str(_int(f.get("Supported memory clock speed (max)")))])
        put("sata_ports", _int(f.get("Number of SATA III connectors")))
        put("m2_slots", [str(_int(f.get("Number of M.2 (M) slots")))]
            if _int(f.get("Number of M.2 (M) slots")) is not None else None)
        x16 = [_int(v) for k, v in f.items() if re.match(r"PCI Express x16 \(Gen \d\.x\) slots", k)]
        if x16 and all(n is not None for n in x16):
            put("pcie_x16_slots", sum(n for n in x16 if n is not None))
        x1 = [_int(v) for k, v in f.items() if re.match(r"PCI Express x1 \(Gen \d\.x\) slots", k)]
        if x1 and all(n is not None for n in x1):
            put("pcie_x1_slots", sum(n for n in x1 if n is not None))
        put("ethernet", _ethernet(f.get("Ethernet interface type")))
        if "Wi-Fi" in f:
            put("wireless", _wifi(f.get("Top Wi-Fi standard")) if _yes(f.get("Wi-Fi")) else "No")
        if "Bluetooth" in f:
            put("bluetooth", _bluetooth(f.get("Bluetooth version")) if _yes(f.get("Bluetooth")) else "No")
        put("raid_support", _yes(f.get("RAID support")))
        ecc = f.get("ECC сompatibility") or f.get("ECC compatibility")
        if ecc:
            put("ecc_support", not str(ecc).lower().startswith("non"))
        put("audio", f.get("Audio chip"))
        put("bios", f.get("BIOS type"))
        put("lighting", _lighting(f))
    elif category == "memory":
        put("total_gb", _int(f.get("Internal memory")))
        count, size = _layout(f.get("Memory layout (modules x size)"))
        put("module_count", count)
        put("module_size_gb", size)
        put("memory_type", _ddr(f.get("Internal memory type")))
        speed = _int(f.get("Memory data transfer rate")) or _int(f.get("Memory clock speed"))
        put("speed_mhz", speed)
        put("cas_latency", _int(f.get("CAS latency")))
        put("voltage_v", _num(f.get("Memory voltage")))
        form = str(f.get("Memory form factor") or "")
        put("form_factor", "SO-DIMM" if "SO" in form.upper() else ("DIMM" if "DIMM" in form.upper() else None))
        if "ECC" in f:
            put("ecc", _yes(f.get("ECC")))
        buffered = str(f.get("Buffered memory type") or "").lower()
        if buffered:
            put("registered", not buffered.startswith("unregistered"))
        put("lighting", _lighting(f))
    elif category == "storage":
        put("capacity_gb", _int(f.get("SSD capacity") or f.get("HDD capacity")))
        if f.get("SSD capacity"):
            put("type", "SSD")
        elif f.get("HDD capacity"):
            put("type", "HDD")
        size = f.get("HDD size")
        put("form_factor", f'{_num(size):g}"' if size and _num(size) else f.get("SSD form factor"))
        interface = str(f.get("Interface") or "")
        if "PCI Express" in interface:
            gen = re.search(r"(\d)\.0", interface)
            put("interface", f"M.2 PCIe {gen.group(1)}.0 x4" if gen else "PCIe")
            put("pcie_gen", int(gen.group(1)) if gen else None)
        elif "Serial ATA" in interface:
            put("interface", "SATA 6.0 Gb/s")
        if "NVMe" in f:
            put("nvme", _yes(f.get("NVMe")))
        put("read_speed_mbs", _int(f.get("Read speed")))
        put("write_speed_mbs", _int(f.get("Write speed")))
        put("nand", f.get("Memory type"))
        put("cache_mb", _int(f.get("Storage drive buffer size")))
        put("rpm", _int(f.get("HDD speed") or f.get("Rotational speed")))
        put("mtbf_hours", _int(f.get("Mean time between failures (MTBF)")))
        put("warranty_years", _int(f.get("Warranty period")))
        put("weight_g", _int(f.get("Weight")))
        # M.2 sheets swap the axes (a 990 EVO Plus "80.15 x 2.38 x 80.15");
        # only a disk's box dimensions are read.
        if f.get("HDD capacity"):
            put("dimensions_mm", _dims_drive(f))
    elif category == "psu":
        put("wattage_w", _int(f.get("Total power")))
        cert = f.get("80 PLUS certification")
        if cert and re.search(r"80\s*PLUS", str(cert), re.I):
            put("efficiency", str(cert).replace("80 PLUS", "80+").strip())
        put("type", f.get("Power supply unit (PSU) form factor"))
        put("modular", _modular(f.get("Cabling type")))
        put("fan_size_mm", _int(f.get("Fan diameter")))
        put("pcie16_connectors", _int(f.get("PCI Express power connectors (16-pin)")))
        put("pcie62_connectors", _int(f.get("PCI Express power connectors (6+2 pin)")))
        put("pcie8_connectors", _int(f.get("PCI Express power connectors (8-pin)")))
        put("pcie6_connectors", _int(f.get("PCI Express power connectors (6-pin)")))
        put("sata_connectors", _int(f.get("Number of SATA power connectors")))
        put("molex4_connectors", _int(f.get("Peripheral (Molex) power connectors (4-pin)")))
        put("eps8_connectors", _int(f.get("Number of EPS power connectors (8-pin)")))
        if _yes(f.get("ATX power connector (20+4 pin)")):
            put("atx4_connectors", 1)
        # Icecat's three box dimensions are not labelled consistently for a
        # PSU (UD1000GM: W 150, D 86, H 140); with the standard faces present
        # the remaining figure is the length.
        dims = [f.get(k) for k in ("Width", "Depth", "Height")]
        if all(dims):
            put("length_mm", psu_length(" x ".join(str(d) for d in dims)))
    elif category == "case":
        form = f.get("Form factor")
        put("type", form)
        put("mb_form_factors", mb_form_factor_list(
            str(f.get("Supported motherboard form factors") or "")))
        put("max_gpu_length_mm", _int(f.get("Maximum graphics card length")))
        put("max_cooler_height_mm", _int(f.get("Maximum CPU cooler height")))
        put("drive_bays_35", _int(f.get('Number of 3.5" bays')))
        put("drive_bays_25", _int(f.get('Number of 2.5" bays')))
        slots = _int(f.get("Number of expansion slots"))
        put("expansion_slots", str(slots) if slots is not None else None)
        window = _yes(f.get("Side window"))
        put("side_panel", "Windowed" if window else ("No Window" if window is False else None))
        included = _yes(f.get("Power supply included"))
        put("psu_included", "Included" if included else ("Not included" if included is False else None))
        for position, field in (("Front", "fan_front"), ("Top", "fan_top"), ("Side", "fan_side"),
                                ("Rear", "fan_rear"), ("Bottom", "fan_bottom")):
            put(field, _fan_mount(f.get(f"Number of {position.lower()} fans supported (max)"),
                                  f.get(f"{position} fans diameters supported")))
        put("radiator_support", _radiators(*(f.get(f"{p} radiator sizes supported")
                                             for p in ("Front", "Top", "Side", "Rear", "Bottom"))))
        weight = _num(f.get("Weight"))
        put("weight_kg", round(weight / 1000, 1) if weight else None)
        put("dimensions_mm", _dims_case(f))
        put("lighting", _lighting(f))
    elif category == "case_fan":
        put("size_mm", _int(f.get("Fan diameter")))
        put("quantity", _int(f.get("Quantity per pack")))
        put("rpm_max", _int(f.get("Rotational speed (max)")))
        put("rpm_min", _int(f.get("Rotational speed (min)")))
        put("airflow_cfm", _num(f.get("Maximum airflow")))
        put("noise_db", _num(f.get("Noise level (high speed)")))
        put("static_pressure_mmh2o", _num(f.get("Maximum air pressure")))
        put("pwm", _yes(f.get("Pulse-width modulation (PWM) support")))
        put("connector", f.get("Fan connector"))
        put("led", _lighting(f))
    elif category in ("cooler_air", "aio", "cooling_other"):
        put("fan_size_mm", _int(f.get("Fan diameter")))
        put("fan_count", _int(f.get("Number of fans")))
        put("fan_rpm_max", _int(f.get("Rotational speed (max)")))
        put("fan_rpm_min", _int(f.get("Rotational speed (min)")))
        put("airflow_cfm", _num(f.get("Maximum airflow")))
        put("noise_db", _num(f.get("Noise level (high speed)")))
        put("tdp_w", _int(f.get("Thermal Design Power (TDP)")))
        sockets = f.get("Supported processor sockets")
        if sockets:
            put("sockets", [s.strip() for s in str(sockets).split(",") if s.strip()])
        if category == "cooler_air":
            put("height_mm", _int(f.get("Height")))
        if category == "aio":
            put("radiator_length_mm", _int(f.get("Radiator height") or f.get("Radiator length")))
            put("radiator_thickness_mm", _int(f.get("Radiator depth")))
        put("lighting", _lighting(f))
    for field in DISABLED.get(category, ()):
        out.pop(field, None)
    return out


def features_of(data: dict) -> dict:
    """{feature name: raw Value} from an Icecat `data` object."""
    out: dict = {}
    for group in data.get("FeaturesGroups") or []:
        for feature in group.get("Features") or []:
            name = (((feature.get("Feature") or {}).get("Name") or {}).get("Value"))
            if name and name not in out:
                out[name] = feature.get("Value")
    return out
