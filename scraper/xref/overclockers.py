"""
xref/overclockers.py - overclockers.co.uk product pages.

Search (/search?sSearch=<part number>) answers with product tiles carrying
`data-pid`; each product page prints `EAN` and `MPN` attribute spans and a
spec table of `<tr class="spec-lvl-1">` rows (label / value). Units are
explicit in the values ("355 mm", "60 m³/h", "22.6 dB(A)").
"""

from __future__ import annotations

import html
import re
import urllib.parse

from ..mfr.common import mb_form_factor_list, norm_mpn, norm_upc, typed

SITE = "overclockers"
BASE_URL = "https://www.overclockers.co.uk"
CATEGORIES = ("case", "case_fan", "cooler_air", "aio", "cooling_other")

_ROW = re.compile(r'<tr class="spec-lvl-1">\s*<td>\s*<div class="small">(.*?)</div>\s*</td>'
                  r'\s*<td>\s*<div class="small">(.*?)</div>', re.S)
_ATTR = re.compile(r'product-attributes-label[^>]*>\s*(EAN|MPN)\s*</span>\s*'
                   r'<span class="product-attributes-value[^"]*">\s*([^<]+?)\s*</span>', re.S)
_TITLE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)
M3H_TO_CFM = 0.588578


def search_url(code: str) -> str:
    return f"{BASE_URL}/search?sSearch={urllib.parse.quote(code)}"


def tile_urls(page: str, limit: int = 2) -> list[str]:
    urls: list[str] = []
    for pid in dict.fromkeys(re.findall(r'data-pid="([^"]+)"', page)):
        match = re.search(r'href="(/[a-z0-9-]+/' + re.escape(pid) + r'\.html)"', page)
        if match:
            urls.append(BASE_URL + match.group(1))
        if len(urls) >= limit:
            break
    return urls


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_page(page: str) -> dict:
    rows: dict[str, str] = {}
    for label, value in _ROW.findall(page):
        label, value = _clean(label), _clean(value)
        if label and value:
            rows.setdefault(label, value)
    ids = {kind: value.strip() for kind, value in _ATTR.findall(page)}
    title = _TITLE.search(page)
    return {"rows": rows, "mpn": ids.get("MPN"), "ean": ids.get("EAN"),
            "title": _clean(title.group(1)) if title else None}


def page_keys(parsed: dict) -> set[str]:
    keys = {norm_mpn(parsed.get("mpn")), norm_upc(parsed.get("ean"))}
    return {k for k in keys if k}


def _num(value) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
    return float(match.group(0).replace(",", ".")) if match else None


def _yes(value) -> bool | None:
    text = str(value or "").strip().lower()
    return True if text == "yes" else False if text == "no" else None


def _fan_mounts(value) -> str | None:
    """'120mm Fan (3x), 140mm Fan (2x)' -> '3 x 120 mm, 2 x 140 mm'; 'None' -> 'No'."""
    text = str(value or "")
    if re.fullmatch(r"\s*(?:none|no|-)\s*", text, re.I):
        return "No"
    parts = [f"{count} x {size} mm"
             for size, count in re.findall(r"(\d{2,3})\s*mm\s*Fan\s*\((\d+)x\)", text, re.I)]
    return ", ".join(parts) or None


def _radiators(rows: dict) -> dict | None:
    sizes: set[int] = set()
    for label, value in rows.items():
        if label.startswith("Radiator/AIO Support"):
            sizes.update(int(s) for s in re.findall(r"(\d{3})\s*mm\s*Radiator", value, re.I))
    return {f"{s} mm": 1 for s in sorted(sizes)} or None


def _airflow_cfm(value) -> float | None:
    number = _num(value)
    if number is None:
        return None
    if re.search(r"m³/h|m3/h", str(value), re.I):
        return round(number * M3H_TO_CFM, 1)
    return number if re.search(r"cfm", str(value), re.I) else None


def _included_fans(value) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*x\s*(\d{2,3})\s*mm", str(value or ""), re.I)
    if match:
        return int(match.group(1)), int(match.group(2))
    count = re.fullmatch(r"\s*(\d+)\s*", str(value or ""))
    return (int(count.group(1)), None) if count else (None, None)


def _sockets(value) -> list[str] | None:
    out = []
    for token in re.split(r"\s*,\s*", str(value or "")):
        token = token.strip()
        if re.fullmatch(r"\d{3,4}", token):
            token = f"LGA{token}"
        if token:
            out.append(token)
    return out or None


def _lighting(rows: dict) -> str | None:
    lit = _yes(rows.get("Lighting / RGB"))
    if lit is False:
        return "No"
    colour = str(rows.get("Lighting Colour") or "")
    if lit and re.search(r"argb|addressable", colour, re.I):
        return "ARGB"
    if lit and re.search(r"rgb", colour, re.I):
        return "RGB"
    return None


def specs_for(category: str, rows: dict) -> dict:
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None or field in out:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    colours = [rows.get("Primary Colour"), rows.get("Secondary Colour")]
    colours = [c for c in dict.fromkeys(colours) if c]
    put("color", " / ".join(colours) if colours else None)
    if category == "case":
        put("type", rows.get("Case Type"))
        put("mb_form_factors", mb_form_factor_list(rows.get("Compatible Motherboard Formats")))
        put("max_cooler_height_mm", _num(rows.get("Max. CPU Cooler Height")))
        put("max_gpu_length_mm", _num(rows.get("Max. GPU Length")))
        included = _yes(rows.get("PSU included"))
        put("psu_included", "Included" if included else "Not included" if included is False else None)
        for position, field in (("Front", "fan_front"), ("Top", "fan_top"), ("Side", "fan_side"),
                                ("Rear", "fan_rear"), ("Bottom", "fan_bottom")):
            put(field, _fan_mounts(rows.get(f"Case Fan Support ({position})")))
        put("radiator_support", _radiators(rows))
        put("drive_bays_35", _num(rows.get("Max. 3.5 Inch Drives")))
        put("drive_bays_25", _num(rows.get("Max. 2.5 Inch Drives")))
        slots = _num(rows.get("Expansion slots / PCI slots"))
        put("expansion_slots", str(int(slots)) if slots is not None else None)
        side = str(rows.get("Side panel") or "").lower()
        put("side_panel", "Windowed" if "with window" in side
            else "No Window" if "without window" in side else None)
        weight = rows.get("Weight")
        if weight and re.search(r"\bkg\b", weight):
            put("weight_kg", _num(weight))
        length, width, height = (_num(rows.get(k)) for k in ("Length / Depth", "Width", "Height"))
        if length and width and height:
            put("dimensions_mm", f"W={int(width)} H={int(height)} D={int(length)}mm")
        put("lighting", _lighting(rows))
    elif category == "case_fan":
        put("size_mm", _num(rows.get("Fan Size")))
        put("rpm_min", _num(rows.get("Min. Fan RPM")))
        put("rpm_max", _num(rows.get("Max. Fan RPM")))
        put("airflow_cfm", _airflow_cfm(rows.get("Max. Single Fan Airflow")))
        put("noise_db", _num(rows.get("Max. Single Fan Noise")))
        pressure = rows.get("Max. Static Pressure")
        if pressure and re.search(r"mmH2O", pressure, re.I):
            put("static_pressure_mmh2o", _num(pressure))
        connector = str(rows.get("Fan connectors") or "")
        if re.search(r"\b4\s*Pin\b", connector, re.I):
            put("connector", "4-pin")
        elif re.search(r"\b3\s*Pin\b", connector, re.I):
            put("connector", "3-pin")
        if connector:
            put("pwm", bool(re.search(r"PWM", connector, re.I)))
        put("led", _lighting(rows))
    else:  # cooler_air / aio / cooling_other
        count, size = _included_fans(rows.get("Included fans"))
        put("fan_count", count)
        put("fan_size_mm", size or _num(rows.get("Fan Size")))
        put("fan_rpm_min", _num(rows.get("Min. Fan RPM")))
        put("fan_rpm_max", _num(rows.get("Max. Fan RPM")))
        put("airflow_cfm", _airflow_cfm(rows.get("Max. Single Fan Airflow")))
        put("noise_db", _num(rows.get("Max. Single Fan Noise")))
        put("sockets", _sockets(rows.get("CPU Socket")))
        if category == "cooler_air":
            put("height_mm", _num(rows.get("Height")))
            vent = str(rows.get("Ventilation type") or "").lower()
            put("fanless", True if vent == "passive" else False if vent == "active" else None)
        if category == "aio":
            put("radiator_size_mm", _num(rows.get("Radiator Size")))
            put("radiator_thickness_mm", _num(rows.get("Radiator Height")))
        put("lighting", _lighting(rows))
    return out
