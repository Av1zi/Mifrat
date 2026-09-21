"""Presentation layer: turn the raw merged attribute blob into a small,
curated, uniformly-formatted spec list for the site.

Why this exists (Sep 2026)
--------------------------
``extractors.py`` is deliberately *additive* (decisions.md): every vendor
signal (title parses, Plonter's German-ish hardwareversand detail tables,
Ivory cut labels, 1PC overview prose) may add facts, and deep trivia like
``mosfets_vcore`` or ``asus_gen2`` accumulates next to ``socket``. The
result is ~800 distinct keys, many carrying useless ``"1"`` count values,
half-decomposed German row labels (``"USB 3.0)"`` -> ``usb_3_0``) and
board-partner USB headers (``asus_gen2``) that mean nothing to shoppers.

Rendering that blob directly produced unreadable spec cards and polluted
filter rails / similar-product scoring. Fixing it inside extractors.py was
rejected: filtering needs the deep keys, and the additive-only rule there
is load-bearing. Instead this module is a pure *view*: it reads the merged
``product.attributes``, distills the raw detail rows into genuinely useful
aggregates (rear I/O ports, USB header counts, VRM phases, expansion slot
list, cooler clearance, PSU connectors), drops trivia, formats values
consistently, and caps the list at a readable size. Extractors and
matching stay untouched - catalog.json keeps the full blob for internal
use; only ``data/site/*.json`` gets the curated view.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Small parsing helpers
# --------------------------------------------------------------------------

_INT_RE = re.compile(r"^\s*(\d+)\s*$")


def _count(value) -> int | None:
    """Parse a detail-row connector count ("2", "1") -> int, else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = _INT_RE.match(str(value))
    return int(m.group(1)) if m else None


def _int_attr(attrs: dict, key: str) -> int | None:
    """Best-effort int for an attribute ("4", 4, "256GB" -> 256)."""
    v = attrs.get(key)
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"^\s*(\d+)", str(v))
    return int(m.group(1)) if m else None


def _collect_counts(attrs: dict, prefixes: tuple[str, ...]) -> dict[str, int]:
    """Collect {key: count} for raw connector rows under `prefixes`."""
    out: dict[str, int] = {}
    for key, value in attrs.items():
        if any(key.startswith(p) for p in prefixes):
            n = _count(value)
            if n:
                out[key] = n
    return out


def _format_ports(counts: dict[str, int], labels: dict[str, str],
                  order: list[str]) -> str | None:
    """"2x HDMI 2.1, 1x DisplayPort 1.4" from {hdmi_2_1: 2, ...}."""
    parts = []
    for key in order:
        n = counts.get(key)
        if n and key in labels:
            parts.append(f"{n}x {labels[key]}")
    return ", ".join(parts) if parts else None


def _text_attr(attrs: dict, keys: tuple[str, ...], cap: int = 80) -> str | None:
    """First short single-line string among `keys` (long prose -> None)."""
    for key in keys:
        v = attrs.get(key)
        if isinstance(v, str):
            s = re.sub(r"\s+", " ", v).strip()
            if s and len(s) <= cap:
                return s
    return None


# --------------------------------------------------------------------------
# Motherboard distillation (Plonter detail rows are the main raw material)
# --------------------------------------------------------------------------

_MOBO_DISPLAY_LABELS = {
    "hdmi_2_1": "HDMI 2.1", "hdmi_2_1b": "HDMI 2.1", "hdmi_2_0": "HDMI 2.0",
    "hdmi_1_4": "HDMI 1.4", "hdmi_2_1_tmds": "HDMI 2.1",
    "displayport_2_1": "DisplayPort 2.1", "displayport_1_4": "DisplayPort 1.4",
    "displayport_1_4a": "DisplayPort 1.4", "displayport_1_2": "DisplayPort 1.2",
    "displayport_2_1b_uhbr20": "DisplayPort 2.1",
    "dvi_d": "DVI-D", "vga": "VGA",
}
_MOBO_DISPLAY_ORDER = list(_MOBO_DISPLAY_LABELS)

# Rear USB-C ports that also carry Thunderbolt/USB4/DP alt-mode.
_MOBO_USBC_LABELS = {
    "thunderbolt_5_usb4_with_displayport_2_1": "Thunderbolt 5 (USB-C)",
    "thunderbolt_4_usb4_with_displayport_2_1": "Thunderbolt 4 (USB-C)",
    "thunderbolt_4_usb4_with_displayport_2_1_uhbr20": "Thunderbolt 4 (USB-C)",
    "thunderbolt_4_usb4_with_displayport_1_4": "Thunderbolt 4 (USB-C)",
    "usb4_with_displayport_2_1": "USB4 (USB-C)",
    "usb4_with_displayport_1_4": "USB4 (USB-C)",
    "usb4_with_displayport_1_4a": "USB4 (USB-C)",
    "usb4_with_displayport": "USB4 (USB-C)",
    "usb_c_3_2_with_displayport_1_4": "USB-C 3.2 (DP)",
    "usb_c_3_2_with_displayport_1_4a": "USB-C 3.2 (DP)",
    "usb_c_3_1_with_displayport_1_4": "USB-C 3.1 (DP)",
    "usb_c_3_1_with_displayport_1_4a": "USB-C 3.1 (DP)",
    "usb_c_3_1": "USB-C 3.1",
    "usb_c_3_0": "USB-C 3.0",
    "usb_c": "USB-C",
}

# Internal USB headers: normalized row prefix -> human label.
_MOBO_USB_HEADER_LABELS = {
    "usb_2_0_header": "USB 2.0",
    "usb_3_0_header": "USB 3.0",
    "usb_3_1_header": "USB 3.1",
    "usb_3_2_header": "USB 3.2",
    "usb_c_3_0_key_a_header": "USB-C (Key-A)",
    "usb_c_3_1_key_a_header": "USB-C (Key-A)",
    "usb_3_0_header_key_a": "USB-C (Key-A)",
    "usb_3_1_header_key_a": "USB-C (Key-A)",
    "usb_3_2_header_key_a": "USB-C (Key-A)",
}

# RGB headers (vendor-branded row names fold into the generic label).
_MOBO_RGB_LABELS = {
    "3_pin_argb": "3-pin ARGB", "jargbv2": "3-pin ARGB",
    "msi_jargbv2": "3-pin ARGB", "jrainbow": "3-pin ARGB",
    "4_pin_rgb": "4-pin RGB", "jrgb": "4-pin RGB", "msi_jrgb": "4-pin RGB",
}
_MOBO_FAN_PREFIXES = ("cpu_fan", "fan_4_pin", "fan_3_pin", "fan_6_pin")
_MOBO_PUMP_PREFIXES = ("fan_pump", "aio_pump", "cpu_fan_pump")

_M2_PLAUSIBLE = {1, 2, 3, 4, 5, 6, 7, 8}


def _mobo_vrm_phases(attrs: dict) -> str | None:
    """"12x 60A" from the mosfets_vcore family of raw rows."""
    for key in ("mosfets_vcore", "mosfets_cpu_vcore", "mosfets_cpu"):
        v = attrs.get(key)
        if not isinstance(v, str):
            continue
        m = re.match(r"^\s*(\d+)\s?x\b", v)
        if not m:
            continue
        amp = re.search(r"(\d+)\s?A\b", v)
        return f"{m.group(1)}x {amp.group(1)}A" if amp else f"{m.group(1)}x"
    return None


def _mobo_wireless(attrs: dict) -> str | None:
    std = attrs.get("wifi_standard")
    if isinstance(std, str) and std.strip():
        m = re.match(r"(?i)wi-?fi\s?(\d)\s?(e)?$", std.strip())
        if m:
            return f"Wi-Fi {m.group(1)}{'E' if m.group(2) else ''}"
        return std.strip()
    if str(attrs.get("wifi", "")).lower() in ("yes", "true"):
        return "Yes"
    return None


def _mobo_lan_chip(attrs: dict) -> str | None:
    for key in ("network", "network_card"):
        v = attrs.get(key)
        if not isinstance(v, str) or not v.strip():
            continue
        s = re.sub(r"\s+", " ", v).strip()
        # Skip pure speed rows - `lan` already carries that.
        if re.fullmatch(r"(?i)(wi-?fi.*|\d+(\.\d+)?g(\s?lan)?.*)", s):
            continue
        return s
    return None



def _distill_motherboard(attrs: dict, out: dict) -> None:
    m2 = _int_attr(attrs, "m2_slots")
    if m2 in _M2_PLAUSIBLE:
        out["m2_slots"] = m2

    sata = _int_attr(attrs, "sata_ports")
    if sata is None:
        # "Misc Interfaces: 4x SATA 6Gb/s (Z890)" rows carry the count.
        misc = attrs.get("miscellaneous_interfaces")
        if isinstance(misc, str):
            m = re.search(r"(\d+)\s?x\s?SATA", misc, re.I)
            if m:
                sata = int(m.group(1))
    if sata is not None and 0 < sata <= 16:
        out["sata_ports"] = sata

    usb_a = (_count(attrs.get("usb_a_3_0")) or 0) + (_count(attrs.get("usb_a")) or 0)
    if usb_a:
        out["usb_a_ports"] = usb_a

    usbc = _format_ports(_collect_counts(attrs, tuple(_MOBO_USBC_LABELS)),
                         _MOBO_USBC_LABELS, list(_MOBO_USBC_LABELS))
    if usbc:
        out["usb_c_ports"] = usbc

    disp = _format_ports(_collect_counts(attrs, tuple(_MOBO_DISPLAY_LABELS)),
                         _MOBO_DISPLAY_LABELS, _MOBO_DISPLAY_ORDER)
    if not disp:
        disp = _text_attr(attrs, ("display_outputs",))
    if disp:
        out["video_outputs"] = disp

    fan_n = sum(_collect_counts(attrs, _MOBO_FAN_PREFIXES).values())
    if fan_n:
        out["fan_headers"] = fan_n
    pump_n = sum(_collect_counts(attrs, _MOBO_PUMP_PREFIXES).values())
    if pump_n:
        out["pump_headers"] = pump_n

    rgb_parts, seen = [], set()
    rgb_counts = _collect_counts(attrs, tuple(_MOBO_RGB_LABELS))
    for key, label in _MOBO_RGB_LABELS.items():
        n = rgb_counts.get(key)
        if n and label not in seen:
            rgb_parts.append(f"{n}x {label}")
            seen.add(label)
    if rgb_parts:
        out["rgb_headers"] = ", ".join(rgb_parts)

    headers = []
    header_counts = _collect_counts(attrs, tuple(_MOBO_USB_HEADER_LABELS))
    for prefix, label in _MOBO_USB_HEADER_LABELS.items():
        n = sum(v for k, v in header_counts.items() if k.startswith(prefix))
        if n and f"{n}x {label}" not in headers:
            headers.append(f"{n}x {label}")
    if headers:
        out["usb_headers"] = ", ".join(headers)

    vrm = _mobo_vrm_phases(attrs)
    if vrm:
        out["vrm_phases"] = vrm

    slots = _text_attr(attrs, ("pcie_slots",), cap=120)
    if slots:
        out["expansion_slots"] = slots
    else:
        x16 = _int_attr(attrs, "pcie_x16_slots")
        if x16:
            out["expansion_slots"] = f"{x16}x PCIe x16"

    wireless = _mobo_wireless(attrs)
    if wireless:
        out["wireless"] = wireless
    lan_chip = _mobo_lan_chip(attrs)
    if lan_chip:
        out["lan_chip"] = lan_chip
    audio = _text_attr(attrs, ("audio",))
    if audio:
        out["audio"] = audio

    cpu_support = attrs.get("cpu_compatibility") or attrs.get("cpu_support")
    if isinstance(cpu_support, str):
        s = re.sub(r"(?i),?\s*cpu[- ]compatibility list", "", cpu_support)
        s = re.sub(r"\s+", " ", s).strip(" ,")
        if s and len(s) <= 80:
            out["cpu_support"] = s

    for key in ("ram_operating_frequency_oc", "ram_data_installment_oc"):
        v = attrs.get(key)
        if isinstance(v, str):
            m = re.search(r"(?i)(ddr\d)[- ](\d+)", v)
            if m:
                out["memory_speed_oc"] = f"{m.group(1).upper()}-{m.group(2)} (OC)"
                break



# --------------------------------------------------------------------------
# PSU / case distillation
# --------------------------------------------------------------------------


def _distill_psu(attrs: dict, out: dict) -> None:
    sata = _count(attrs.get("sata_connectors")) or _count(attrs.get("sata"))
    if sata:
        out["sata_connectors"] = sata
    pcie = (_count(attrs.get("pcie_power_connectors"))
            or _count(attrs.get("6_8_pin_pcie"))
            or _count(attrs.get("pcie_8pin_connectors")))
    hp = (_count(attrs.get("16_pin_pcie_5_0"))
          or _count(attrs.get("16_pin_pcie_5_0_12vhpwr"))
          or _count(attrs.get("pcie_16pin_connectors"))
          or _count(attrs.get("pcie_12vhpwr_connectors")))
    if pcie and hp:
        out["pcie_connectors"] = f"{pcie}x 6+2-pin, {hp}x 16-pin"
    elif pcie:
        out["pcie_connectors"] = f"{pcie}x 6+2-pin"
    elif hp:
        out["pcie_connectors"] = f"{hp}x 16-pin"
    eps = (_count(attrs.get("cpu_power_connectors"))
           or _count(attrs.get("4_8_pin_atx12v"))
           or _count(attrs.get("8_pin_eps12v"))
           or _count(attrs.get("eps_connectors")))
    if eps:
        out["eps_connectors"] = f"{eps}x 8-pin"


def _distill_case(attrs: dict, out: dict) -> None:
    cooler = attrs.get("cpu_coolers")
    if isinstance(cooler, str):
        m = re.search(r"max\.?\s*(\d+)\s?mm", cooler, re.I)
        if m:
            out["max_cooler_height_mm"] = int(m.group(1))
    for slot, key in (("front", "fan_s_front"), ("top", "fan_s_top"),
                      ("rear", "fan_s_rear"), ("bottom", "fan_s_bottom")):
        v = attrs.get(key)
        if isinstance(v, str) and v.strip():
            out[f"fan_{slot}"] = re.sub(r"\s+", " ", v).strip()



# --------------------------------------------------------------------------
# Formatting of kept raw values
# --------------------------------------------------------------------------

_NUMERIC_SUFFIX = {
    "speed_mhz": " MT/s", "boost_clock_ghz": " GHz", "base_clock_ghz": " GHz",
    "wattage_w": " W", "capacity_gb": " GB", "vram_gb": " GB",
    "length_mm": " mm", "max_gpu_length_mm": " mm", "cooler_height_mm": " mm",
    "max_cooler_height_mm": " mm", "radiator_size_mm": " mm",
    "supported_radiator_mm": " mm", "fan_size_mm": " mm",
    "first_word_latency_ns": " ns", "cache_mb": " MB",
    "core_clock_mhz": " MHz", "memory_clock_mhz": " MHz",
    "external_volume_l": " L",
}


def _format_value(key: str, value, category: str) -> str | None:
    """One canonical display string per (key, value). None = drop the row."""
    if isinstance(value, bool):
        return "Yes" if value else None
    if isinstance(value, (int, float)):
        if key == "cas_latency":
            return f"CL{value}"
        suffix = _NUMERIC_SUFFIX.get(key)
        return f"{value}{suffix}" if suffix is not None else str(value)

    s = re.sub(r"\s+", " ", str(value)).strip()
    if not s:
        return None

    if key in ("wifi_standard", "wireless"):
        m = re.match(r"(?i)^wi-?fi\s?(\d)(e)?$", s)
        if m:
            return f"Wi-Fi {m.group(1)}{'E' if m.group(2) else ''}"
    if key == "modules" and category == "memory":
        m = re.match(r"^(\d+)\s?x\s?(\d+)\s?GB$", s, re.I)
        if m:
            return f"{m.group(1)} x {m.group(2)}GB"
    if key == "cas_latency":
        m = re.match(r"^CL?\s?(\d+)$", s, re.I)
        if m:
            return f"CL{m.group(1)}"
    if key in _NUMERIC_SUFFIX:
        m = re.match(r"^([\d.]+)", s)
        if m:
            return f"{m.group(1)}{_NUMERIC_SUFFIX[key]}"
    if key == "lan":
        m = re.match(r"^([\d.]+)G$", s, re.I)
        if m:
            return f"{m.group(1)}GbE"
    if key == "memory_max":
        m = re.match(r"^(\d+)\s?GB", s, re.I)
        if m:
            return f"{m.group(1)} GB"
    return s



# --------------------------------------------------------------------------
# Per-category curated key order. Anything not listed is dropped from the
# display spec sheet (it still lives in catalog.json for filters/matching).
# --------------------------------------------------------------------------

_CATEGORY_ORDER: dict[str, list[str]] = {
    "cpu": [
        "cores", "threads", "base_clock_ghz", "boost_clock_ghz",
        "l2_cache", "l3_cache", "tdp", "socket", "generation", "tier",
        "microarchitecture", "integrated_graphics", "smt", "ecc_support",
        "cooler_included", "packaging", "memory_max", "codename",
        "manufacturing_process", "launch",
    ],
    "motherboard": [
        "socket", "chipset", "form_factor", "memory_type", "memory_slots",
        "memory_max", "memory_speed_oc", "cpu_support", "expansion_slots",
        "m2_slots", "sata_ports", "usb_a_ports", "usb_c_ports", "usb_ports",
        "video_outputs", "wireless", "lan", "lan_chip", "audio",
        "vrm_phases", "fan_headers", "pump_headers", "rgb_headers",
        "usb_headers", "raid_level", "ecc_support", "power_connections",
        "bios", "buttons_switches", "color",
    ],
    "memory": [
        "memory_type", "capacity_gb", "modules", "module_count",
        "speed_mhz", "cas_latency", "timings", "first_word_latency_ns",
        "voltage", "form_factor", "ecc_support", "heat_spreader",
        "lighting", "color", "modules_height",
    ],
    "gpu": [
        "gpu_chip", "vram_gb", "memory_type", "boost_clock_ghz",
        "core_clock_mhz", "memory_clock_mhz", "interface", "length_mm",
        "tdp", "slot_width", "power_connections", "cooling", "fan_count",
        "hdmi_ports", "displayport_ports", "dvi_ports", "lighting", "color",
    ],
    "storage": [
        "capacity_gb", "drive_type", "drive_form_factor", "interface",
        "nvme", "pcie_gen", "rpm", "read", "write", "cache_mb", "tbw",
        "nand", "controller",
    ],
    "psu": [
        "wattage_w", "efficiency", "modular", "form_factor", "length_mm",
        "atx_version", "fanless", "sata_connectors", "pcie_connectors",
        "eps_connectors", "lighting", "color",
    ],
    "case": [
        "form_factor", "side_panel", "color", "lighting", "power_supply",
        "max_gpu_length_mm", "max_cooler_height_mm", "supported_radiator_mm",
        "fan_front", "fan_top", "fan_rear", "fan_bottom",
        "internal_25_bays", "internal_35_bays", "front_io",
        "expansion_slots", "external_volume_l", "dimensions", "weight",
    ],
    "case_fan": [
        "fan_size_mm", "rpm", "airflow", "noise_level", "pwm", "lighting",
        "color", "fans_per_pack",
    ],
    "aio": [
        "radiator_size_mm", "socket_compat", "fan_size_mm", "rpm",
        "noise_level", "lighting", "color", "cooler_display",
    ],
    "cooler_air": [
        "socket_compat", "cooler_height_mm", "tdp", "fan_size_mm", "rpm",
        "airflow", "noise_level", "lighting", "color",
    ],
    "accessories": ["accessory_type", "color", "lighting", "socket_compat"],
    "cooling_other": ["accessory_type", "color", "lighting", "socket_compat"],
    "other": ["form_factor", "color"],
}

# Hard cap so one over-detailed product can never render an endless card.
_MAX_DISPLAY_SPECS = 28


def build_display_specs(category: str, attributes: dict) -> dict[str, str]:
    """Curated, formatted, ordered spec rows for the product page.

    Pure function over the merged attribute blob: nothing here mutates or
    feeds back into matching/filtering. Keys are emitted in the category's
    curated order so the frontend can render them as-is.
    """
    if not isinstance(attributes, dict) or not attributes:
        return {}

    order = _CATEGORY_ORDER.get(
        category, ["socket", "form_factor", "color", "lighting"])

    distilled: dict = {}
    if category == "motherboard":
        _distill_motherboard(attributes, distilled)
    elif category == "psu":
        _distill_psu(attributes, distilled)
    elif category == "case":
        _distill_case(attributes, distilled)

    out: dict[str, str] = {}
    for key in order:
        raw = distilled.get(key)
        if raw is None:
            raw = attributes.get(key)
        if raw in (None, "", [], {}):
            continue
        formatted = _format_value(key, raw, category)
        if formatted:
            out[key] = formatted
        if len(out) >= _MAX_DISPLAY_SPECS:
            break

    # De-duplicate rows that say the same thing twice: the kit layout row
    # ("2 x 16GB") already implies the stick count, and the rear-USB
    # breakdown (usb_a/usb_c rows) is the useful form of the lumped
    # "USB Ports: 16" total.
    if "modules" in out:
        out.pop("module_count", None)
    if "usb_a_ports" in out or "usb_c_ports" in out:
        out.pop("usb_ports", None)
    return out

