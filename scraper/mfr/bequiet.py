"""
mfr/bequiet.py - bequiet.com product pages (feasibility: PASS, re-checked Oct 2026).

The first verdict ("no sitemap, URLs not derivable") only looked at /sitemap.xml.
The category listings (/en/case, /en/casefans, /en/cpucooler, /en/watercooler,
/en/powersupply) link every product page as ./<category>/<numeric id>; robots.txt
allows everything; each page is server-rendered with a two-column technical-data
table that carries the "Article number" (BGW39, BK003 ...) and the "EAN code" the
catalog already holds as its part number, so products join EXACTLY on those two
identifiers (every listed page is fetched; the join happens at merge time).

Round 3 (Oct 2026): every field the table prints. Case pages repeat the
"Top / Front / Side / Rear / Bottom (mm)" labels: the first block is fan
mounts ("3x 120 / 3x 140"), the second radiator sizes ("120 / 240 / 360").
"""

from __future__ import annotations

import re

from .common import (efficiency_tier, fan_mounts, front_io_ports, html_rows, mb_form_factor_list,
                     number_range, radiator_sizes, typed)

BRAND = "be quiet!"
BASE_URL = "https://www.bequiet.com"
CATEGORIES = ("case", "case_fan", "cooler_air", "aio", "psu")

_GROUPS = {"case": "case", "casefans": "case_fan", "cpucooler": "cooler_air",
           "watercooler": "aio", "powersupply": "psu"}
_CHECK = "✓"


def index(client) -> list[dict]:
    entries = []
    for group in _GROUPS:
        page = client.get(f"{BASE_URL}/en/{group}") or ""
        for product_id in sorted(set(re.findall(r'href="\./' + group + r'/(\d+)"', page))):
            entries.append({"url": f"{BASE_URL}/en/{group}/{product_id}", "group": group,
                            "key": f"id{product_id}"})
    return entries


def in_scope(entry: dict) -> bool:
    return True


def classify(entry: dict, page: str) -> str | None:
    return _GROUPS.get(entry.get("group"))


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    return None                      # joins on the Article number / EAN printed on the page


def _rows(page: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, value in html_rows(page):
        out.setdefault(re.sub(r"\s+", " ", label).strip().lower(), value)
    return out


def _all_rows(page: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for label, value in html_rows(page):
        out.setdefault(re.sub(r"\s+", " ", label).strip().lower(), []).append(value)
    return out


def _flag(raw) -> bool | None:
    """'✓' / 'Yes' -> True, '-' -> False, anything else unknown."""
    text = str(raw or "").strip()
    if text in (_CHECK, "Yes", "yes"):
        return True
    if text == "-":
        return False
    return None


def _num(raw) -> float | None:
    match = re.match(r"\s*(\d+(?:\.\d+)?)", str(raw or "").replace(",", ""))
    return float(match.group(1)) if match else None


def _last_num(raw) -> float | None:
    span = number_range(raw)
    return span[1] if span else None


def _sockets(rows: dict[str, str]) -> list[str]:
    out: list[str] = []
    for token in re.findall(r"\b(1[0-9]{3}|775|2011|2066)\b", rows.get("socket compatibility intel", "")):
        value = f"LGA{token}"
        if value not in out:
            out.append(value)
    for token in re.findall(r"\bAM\d\b", rows.get("socket compatibility amd", ""), re.I):
        value = token.upper()
        if value not in out:
            out.append(value)
    return out


def parse(page: str, category: str) -> dict:
    rows = _rows(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    model = rows.get("model", "")
    if category in ("case_fan", "cooler_air", "aio", "case"):
        put("model", model or None)
        color = rows.get("color option", "").strip()
        put("color", color if color and color != "-" else None)
    ids = [rows.get("article number", ""), rows.get("ean code", "")]
    ids += re.findall(r"Article number:\s*([A-Z0-9]{4,8})", page)
    if category == "case":
        _case(rows, model, put)
        _case_more(rows, _all_rows(page), put)
    elif category == "case_fan":
        _fan(rows, put)
    elif category in ("cooler_air", "aio"):
        _cooler(rows, model, put, category)
    elif category == "psu":
        _psu(rows, model, put)
    return {**out, "_ids": [i for i in ids if i and i != "-"]}


def _case(rows, model, put) -> None:
    forms = mb_form_factor_list(rows.get("motherboard compatibility", ""))
    if forms:
        put("mb_form_factors", forms)
    put("max_cooler_height_mm", _num(rows.get("max.construction height of cpu cooler unit (mm)")))
    if re.search(r"\bwindow\b", model, re.I):
        put("side_panel", "Windowed")
    dims = re.match(r"\s*(\d{2,3})\s*x\s*(\d{2,3})\s*x\s*(\d{2,3})",
                    rows.get("case size excl. stands (l x w x h), (mm)", ""))
    if dims:
        put("dimensions_mm", f"W={dims.group(2)} H={dims.group(3)} D={dims.group(1)}mm")
    put("weight_kg", _num(rows.get("net weight (kg)")))
    put("volume_l", _num(rows.get("volume (l)")))
    ports = []
    for label in ("usb 3.2 gen. 2 type c", "usb 3.2 type a", "usb 3.2 gen. 2 type a", "usb 2.0",
                  "usb 3.0", "usb 3.2 gen. 1 type c"):
        if label in rows and re.match(r"\s*[1-9]", rows[label]):
            ports.append(label.replace("gen. ", "gen ") + " " + rows[label])
    if re.search(r"mic|audio", rows.get("hd audio i/o", ""), re.I):
        ports.append("microphone")
    found = front_io_ports(", ".join(ports))
    if found:
        put("front_usb", found)


def _fan(rows, put) -> None:
    size = _num(rows.get("dimensions (mm)"))
    if size:
        put("size_mm", int(size))
    put("rpm_max", _num(rows.get("fan speed at 100% pwm / 12v (rpm)")))
    put("noise_db", _last_num(rows.get("noise level at 100% pwm / 12v (db(a))")))
    put("airflow_cfm", _num(rows.get("airflow at 100% pwm / 12v (cfm / m3/h)")))
    put("static_pressure_mmh2o", _num(rows.get("air pressure at 100% pwm / 12v (mm h2o)")))
    lighting = rows.get("lighting", "").strip()
    if lighting == "-":
        put("led", "No")
    elif re.search(r"\bARGB\b", lighting, re.I):
        put("led", "ARGB")
    elif re.search(r"\bRGB\b", lighting, re.I):
        put("led", "RGB")
    connector = rows.get("connector", "")
    pins = re.search(r"(\d)\s*-?\s*pin", connector, re.I)
    if pins:
        put("connector", f"{pins.group(1)}-pin")
        put("pwm", bool(re.search(r"pwm", connector, re.I)))


def _cooler(rows, model, put, category) -> None:
    sockets = _sockets(rows)
    if sockets:
        put("sockets", sockets)
    fan = re.match(r"\s*(\d{2,3})\s*x\s*\d{2,3}\s*x\s*\d{2}", rows.get("fan dimensions (mm)", ""))
    if fan:
        put("fan_size_mm", int(fan.group(1)))
    fans = _num(rows.get("number of fans"))
    if category == "aio":
        radiator = re.search(r"\b(\d{3})\s*mm\b", model)
        if radiator:
            put("radiator_size_mm", int(radiator.group(1)))
        put("fan_rpm_max", _num(rows.get("speed at 100% pwm (rpm)")))
        put("airflow_cfm", _num(rows.get("airflow at 100% pwm / 12v (cfm / m3/h)")))
        put("noise_db", _last_num(rows.get("noise level (db(a)) at 50% / 75% /100% rpm", "")))
        if fans is not None:
            put("fan_count", int(fans))
        # The radiator alone ("277 x 120 x 27"); the row above it includes the fans.
        size = re.match(r"\s*(\d{2,3})\s*x\s*\d{2,3}\s*x\s*(\d{2})\b",
                        rows.get("dimensions (l x w x h), (mm)", ""))
        if size:
            put("radiator_length_mm", int(size.group(1)))
            put("radiator_thickness_mm", int(size.group(2)))
        connectors = []
        for label in ("pump connector", "connector"):
            pins = re.search(r"(\d)\s*-?\s*pin\s*PWM", rows.get(label, ""), re.I)
            if pins and f"{pins.group(1)}-pin PWM" not in connectors:
                connectors.append(f"{pins.group(1)}-pin PWM")
        if re.search(r"3\s*-?\s*pin.*(?:ARGB|addressable|adressable)", rows.get("lighting connector", ""), re.I):
            connectors.append("3-pin ARGB")
        if connectors:
            put("connectors", connectors)
    else:
        put("fan_rpm_max", _num(rows.get("speed @ 100% pwm (rpm)")))
        put("airflow_cfm", _num(rows.get("airflow at 100% pwm / 12v (cfm / m3/h)")))
        put("tdp_w", _num(rows.get("tdp (w)")))
        put("noise_db", _last_num(rows.get("overall noise level (db(a)) @ 50/75/100% (rpm)", "")))
        # Two dimension rows (overall / heatsink); which one includes the fan
        # differs by model (Pure Rock LP: 45 / 30, Shadow Rock TF 2: 87 / 112),
        # so the taller - the case-fit height - is read.
        heights = []
        for label, value in rows.items():
            if label.startswith(("overall dimensions", "dimensions (l x w x h)")):
                height = re.match(r"\s*\d{2,3}\s*x\s*\d{2,3}\s*x\s*(\d{2,3})\b", value)
                if height:
                    heights.append(int(height.group(1)))
        if heights:
            put("height_mm", max(heights))


def _psu(rows, model, put) -> None:
    put("wattage_w", _num(rows.get("continuous power (w)")))
    put("efficiency", efficiency_tier("80 plus " + rows.get("80 plus certification", "")))
    put("fan_size_mm", _num(rows.get("fan size (mm)")))
    form = rows.get("form factor", "") + " " + model
    if re.search(r"\bSFX[-\s]?L\b", form, re.I):
        put("type", "SFX-L")
    elif re.search(r"\bSFX\b", form, re.I):
        put("type", "SFX")
    elif re.search(r"\bTFX\b", form, re.I):
        put("type", "TFX")
    elif re.search(r"PS/2|ATX12V|\bATX\b", form, re.I):
        put("type", "ATX")
    version = re.search(r"\bATX\s*(3\.[01])\b", form + " " + model, re.I)
    if version:
        put("atx_version", f"ATX {version.group(1)}")
    cables = rows.get("modular cables", "").strip()
    if cables == "-":
        put("modular", "no")
    elif cables == _CHECK and not re.search(r"\bCM\b|cable management", model, re.I):
        put("modular", "full")

    def count(label: str) -> int | None:
        value = rows.get(label, "").strip()
        if value == "-":
            return 0
        return int(value) if value.isdigit() else None

    four_four, eight = count("p4+4 (cpu)"), count("p8 (cpu)")
    if four_four is not None and eight is not None:
        put("eps8_connectors", four_four + eight)
    put("pcie62_connectors", count("pci-e 6+2-pin (gpu)"))
    put("pcie6_connectors", count("pci-e 6-pin (gpu)"))
    put("pcie16_connectors", count("12v-2x6 cables"))
    put("sata_connectors", count("sata"))
    put("molex4_connectors", count("pata"))


def _count(raw) -> int | None:
    """'3' -> 3, '-' -> 0 (the table's "none"), anything else unknown."""
    text = str(raw or "").strip()
    if text == "-":
        return 0
    return int(text) if text.isdigit() else None


def _case_more(rows, every, put) -> None:
    """Fan mounts, radiator sizes, clearances, bays, lighting."""
    for position in ("front", "top", "side", "rear", "bottom"):
        values = every.get(f"{position} (mm)", [])
        mounts = values[0] if values else None
        shroud = rows.get("psu shroud", "-").strip()
        if position == "bottom" and (mounts or "-").strip() == "-" and shroud != "-":
            mounts = shroud                     # the PSU shroud is the bottom mount
        if mounts:
            put(f"fan_{position}", fan_mounts(mounts))
    sizes: set[int] = set()
    for position in ("front", "top", "side", "rear", "bottom"):
        for value in every.get(f"{position} (mm)", [])[1:2]:
            if not re.search(r"\dx", value.replace(" ", "")):
                sizes |= radiator_sizes(value)
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
    slots = re.match(r"\s*(\d{1,2})\b", rows.get("expansion slots", ""))
    if slots:
        put("expansion_slots", slots.group(1))
    # GPU length: the larger figure (HDD cage removed) is the case's maximum.
    lengths = [_num(rows.get(label)) for label in (
        "hdd cage (in height of graphics card) removed (mm)",
        "hdd cage (in height of graphics card) installed (mm)")]
    lengths = [n for n in lengths if n]
    if lengths:
        put("max_gpu_length_mm", int(max(lengths)))
    # Bays the case takes ("max."), not the trays in the box.
    put("drive_bays_35", _count(rows.get("3.5 slots (max.)")))
    put("drive_bays_25", _count(rows.get("2.5 slots (max.)")))
    led = _flag(rows.get("led illumination"))
    kind = rows.get("led type", "")
    # Only the positive: "LED illumination: -" is the case body, while the
    # catalog's case lighting also counts bundled ARGB fans (Pure Base 501 LX).
    if led and re.search(r"ARGB", kind, re.I):
        put("lighting", "ARGB")
    elif led and re.search(r"RGB", kind):
        put("lighting", "RGB")
