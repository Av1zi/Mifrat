"""
mfr/coolermaster.py - coolermaster.com product pages (feasibility: PASS, narrow).

Verdict (Oct 2026): robots.txt only lists a sitemap; the en-global product
sitemap lists ~190 current product slugs; pages are server-rendered with a
"Specifications" list of label/value <span> pairs (no JS). Scope is limited on
purpose:
- PSU pages are SERIES pages (one page, 750/850/1000W values side by side), so
  PSUs are skipped - a wrong-wattage row would outrank the retailer's right one;
- legacy products (HAF, MasterBox MB5xx...) are not in the current sitemap, so
  only products whose brand-stripped name is prefixed by a current slug match.
"""

from __future__ import annotations

import html as html_lib
import re

from .common import front_io_ports, mb_form_factor_list, norm_name, number_range, typed

BRAND = "Cooler Master"
BASE_URL = "https://www.coolermaster.com"
SITEMAP = BASE_URL + "/en-global/sitemap_0-product.xml"
CATEGORIES = ("cooler_air", "aio", "case")

_URL_RE = re.compile(r"<loc>(https://www\.coolermaster\.com/en-global/products/([^/<]+)\.html)</loc>")
_PAIR_RE = re.compile(
    r'repeater-item__label">(.*?)</span>\s*<span class="repeater-item__value">(.*?)</span>', re.S)


def index(client) -> list[dict]:
    page = client.get(SITEMAP)
    return [{"url": url, "slug": slug, "key": norm_name(slug)}
            for url, slug in _URL_RE.findall(page or "")]


def in_scope(entry: dict) -> bool:
    return True


def classify(entry: dict, page: str) -> str | None:
    """Category from the page's own labels (the join also needs the product to
    share it). PSU / fan / accessory pages return None: no parser reads them."""
    labels = {key for key, _ in _pairs(page)}
    if "radiator size" in labels:
        return "aio"
    if "cpu socket" in labels and "heat sink material" in labels:
        return "cooler_air"
    if "motherboard support" in labels and "expansion slots" in labels:
        return "case"
    return None


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    """Longest slug that prefixes the brand-stripped name; ties are skipped."""
    name = norm_name(product.get("canonical_name"), "cooler master")
    name = re.sub(r"^coolermaster", "", name)
    best, tie = None, False
    for key, entry in entries_by_key.items():
        if key and name.startswith(key):
            if best is None or len(key) > len(best[0]):
                best, tie = (key, entry), False
            elif len(key) == len(best[0]) and entry is not best[1]:
                tie = True
    return None if best is None or tie else best[1]


def _pairs(page: str) -> list[tuple[str, str]]:
    out = []
    for label, value in _PAIR_RE.findall(page):
        label = html_lib.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        value = html_lib.unescape(re.sub(r"<[^>]+>", " ", value))
        out.append((label.lower(), re.sub(r"\s+", " ", value).strip()))
    return out


def _first(pairs, label: str) -> str | None:
    for key, value in pairs:
        if key == label:
            return value
    return None


def _all(pairs, label: str) -> list[str]:
    return [value for key, value in pairs if key == label]


def _mm(raw) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(raw or ""), re.I)
    return int(round(float(match.group(1)))) if match else None


def _dims(raw) -> tuple[float, float, float] | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", str(raw or ""))
    return tuple(float(g) for g in match.groups()) if match else None


def _sockets(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        for family, pattern in (("LGA", r"LGA\s*([\d\s/]+)"), ("AM", r"\b(AM\d)\b")):
            if family == "LGA":
                match = re.search(pattern, value)
                if match:
                    for number in re.findall(r"\d{3,4}", match.group(1)):
                        token = f"LGA{number}"
                        if token not in out:
                            out.append(token)
            else:
                for token in re.findall(pattern, value):
                    if token not in out:
                        out.append(token)
    return out


def parse(page: str, category: str) -> dict:
    pairs = _pairs(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    out["_mpn"] = _first(pairs, "product number") or _first(pairs, "model number")
    put("color", _first(pairs, "exterior color"))
    if category in ("cooler_air", "aio"):
        _cooler(pairs, put, category)
    elif category == "case":
        _case(pairs, put)
    return {k: v for k, v in out.items() if v is not None}


def _cooler(pairs, put, category) -> None:
    sockets = _sockets(_all(pairs, "cpu socket"))
    if sockets:
        put("sockets", sockets)
    quantity = number_range(_first(pairs, "fan quantity"))
    if quantity:
        put("fan_count", int(quantity[1]))
    speed = number_range((_first(pairs, "fan speed") or "").split("±")[0])
    if speed:
        if speed[0] != speed[1]:
            put("fan_rpm_min", int(speed[0]))
        put("fan_rpm_max", int(speed[1]))
    airflow = number_range(_first(pairs, "fan airflow"))
    if airflow:
        put("airflow_cfm", airflow[1])
    noise = number_range(_first(pairs, "fan noise level"))
    if noise:
        put("noise_db", noise[1])
    dims = [_dims(v) for v in _all(pairs, "dimensions (l x w x h)")]
    if category == "aio":
        radiator = re.search(r"\d{3}", _first(pairs, "radiator size") or "")
        if radiator:
            put("radiator_size_mm", int(radiator.group(0)))
        rad = _dims(_first(pairs, "radiator dimensions"))
        if rad:
            put("radiator_length_mm", int(round(rad[0])))
            put("radiator_thickness_mm", int(round(rad[2])))
        if dims and dims[0]:
            put("fan_size_mm", int(round(dims[0][0])))
    else:
        if dims and dims[0]:
            put("height_mm", int(round(dims[0][2])))
        if len(dims) > 1 and dims[1]:
            put("fan_size_mm", int(round(dims[1][0])))


def _case(pairs, put) -> None:
    put("type", _first(pairs, "size"))
    forms = mb_form_factor_list(re.sub(r"\*[^,]*", "", _first(pairs, "motherboard support") or ""))
    if forms:
        put("mb_form_factors", forms)
    put("max_gpu_length_mm", _mm(_first(pairs, "clearance - gfx")))
    put("max_cooler_height_mm", _mm(_first(pairs, "clearance - cpu cooler")))
    panel = _first(pairs, "materials - left side panel") or ""
    if re.search(r"glass|acrylic|window", panel, re.I):
        put("side_panel", "Windowed")
    slots = re.fullmatch(r"\s*(\d{1,2})\s*", _first(pairs, "expansion slots") or "")
    if slots:
        put("expansion_slots", slots.group(1))
    front = []
    for key, value in pairs:
        if key.startswith("i/o") and "usb" in key and re.search(r"\d", value):
            label = key.split("/")[-1].strip() if " / " in key else ""
            front.append(f"{label} {value}".strip())
    ports = front_io_ports(", ".join(front))
    if ports:
        put("front_usb", ports)
    bays = re.fullmatch(r"\s*(\d{1,2})\s*", _first(pairs, '2.5" drive bays') or "")
    if bays:
        put("drive_bays_25", int(bays.group(1)))
    dims = None
    for value in _all(pairs, "dimensions (l x w x h)"):
        if re.search(r"excl", value, re.I):
            excl = re.search(r"(\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?)\s*mm\s*\(excl", value)
            dims = _dims(excl.group(1)) if excl else None
        elif dims is None:
            dims = _dims(value)
    if dims:
        put("dimensions_mm", f"W={int(round(dims[1]))} H={int(round(dims[2]))} D={int(round(dims[0]))}mm")
    sizes: set[int] = set()
    for key, value in pairs:
        if key.startswith("radiator support"):
            sizes.update(int(n) for n in re.findall(r"\b(1[24]0|2[48]0|3[68]0|420)\b", value))
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
