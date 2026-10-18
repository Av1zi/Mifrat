"""
mfr/antec.py - antec.com product pages (feasibility: PASS).

Verdict (Oct 2026): robots.txt is "Disallow:" (allow everything); sitemap.xml
lists every product page (/product/<group>/<slug>); pages are static HTML with
a "SPECIFICATIONS" block of nested two-cell tables and a "UPC#" row, so
products join on UPC when the catalog carries it and otherwise on the longest
slug that prefixes the product's brand-stripped name (a colour suffix such as
"-white" shares the model's specs). Ambiguous names (two equally long slugs)
are skipped, never guessed.
"""

from __future__ import annotations

import re

from .common import html_rows, mb_form_factor_list, norm_name, number_range, typed

BRAND = "Antec"
BASE_URL = "https://www.antec.com"
SITEMAP = BASE_URL + "/sitemap.xml"
CATEGORIES = ("case", "psu", "case_fan", "cooler_air", "aio", "cooling_other")

_URL_RE = re.compile(r"<loc>(https://www\.antec\.com/product/([^/<]+)/([^/<]+))</loc>")


_LISTINGS = ("case-", "power-series", "power-80plus", "casefan", "cooling-", "cooling-all", "air")
_LINK_RE = re.compile(r'href="([a-z]+)/([A-Za-z0-9_.-]+?)\.php"')


def index(client) -> list[dict]:
    """Listing pages first (the sitemap is stale: dated 2021, ~140 pages),
    then whatever the sitemap adds. Listing links are `<group>/<slug>.php`."""
    entries: dict[str, dict] = {}
    for listing in _LISTINGS:
        page = client.get(f"{BASE_URL}/product/{listing}")
        for group, slug in _LINK_RE.findall(page or ""):
            url = f"{BASE_URL}/product/{group}/{slug}.php"
            entries.setdefault(norm_name(slug), {"url": url, "group": group,
                                                 "slug": slug, "key": norm_name(slug)})
    page = client.get(SITEMAP)
    for url, group, slug in _URL_RE.findall(page or ""):
        entries.setdefault(norm_name(slug), {"url": url, "group": group,
                                             "slug": slug, "key": norm_name(slug)})
    return list(entries.values())


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    """Longest slug that is a prefix of the brand-stripped product name."""
    name = norm_name(product.get("canonical_name"), "antec")
    best, tie = None, False
    for key, entry in entries_by_key.items():
        if key and name.startswith(key):
            if best is None or len(key) > len(best[0]):
                best, tie = (key, entry), False
            elif len(key) == len(best[0]) and entry is not best[1]:
                tie = True
    return None if best is None or tie else best[1]


def _rows(page: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, value in html_rows(page):
        out.setdefault(re.sub(r"\s+", " ", label).strip().lower(), value)
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

    out["_upc"] = rows.get("upc#")
    if category == "case":
        _case(rows, put)
    elif category == "case_fan":
        _fan(rows, put)
    elif category == "aio":
        _aio(rows, put)
    return {k: v for k, v in out.items() if v is not None}


def _mm(raw) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(raw or ""), re.I)
    return int(round(float(match.group(1)))) if match else None


def _case(rows, put) -> None:
    put("max_gpu_length_mm", _mm(rows.get("max gpu length")))
    put("max_cooler_height_mm", _mm(rows.get("max cpu cooler height")))
    put("type", rows.get("form factor"))
    forms = mb_form_factor_list(rows.get("mainboard support", ""))
    if forms:
        put("mb_form_factors", forms)
    panel = rows.get("side panel", "")
    if re.search(r"glass|acrylic|window", panel, re.I):
        put("side_panel", "Windowed")
    dims = re.search(r"(\d{2,3})\s*x\s*(\d{2,3})\s*x\s*(\d{2,3})\s*mm\s*\(\s*DWH", rows.get("dimensions", ""), re.I)
    if dims:
        put("dimensions_mm", f"W={dims.group(2)} H={dims.group(3)} D={dims.group(1)}mm")
    weight = re.search(r"(\d+(?:\.\d+)?)\s*kg", rows.get("net weight", ""), re.I)
    if weight:
        put("weight_kg", float(weight.group(1)))
    slots = re.fullmatch(r"\s*(\d{1,2})\s*", rows.get("expansion slots", ""))
    if slots:
        put("expansion_slots", slots.group(1))
    bays = re.fullmatch(r"\s*(\d{1,2})\s*", rows.get('5.25"', ""))
    if bays:
        put("drive_bays_525", int(bays.group(1)))


def _range_max(raw) -> float | None:
    span = number_range(re.sub(r"[±].*", "", str(raw or "")))
    return span[1] if span else None


def _speed(rows, put, low_field: str, high_field: str, label: str) -> None:
    span = number_range(re.sub(r"[±].*", "", rows.get(label, "")))
    if span:
        if span[0] != span[1] and span[0] >= 100:
            put(low_field, int(span[0]))
        put(high_field, int(span[1]))


def _fan(rows, put) -> None:
    size = re.match(r"\s*(\d{2,3})\s*[*x]\s*\1\b", rows.get("dimensions", ""))
    if size:
        put("size_mm", int(size.group(1)))
    _speed(rows, put, "rpm_min", "rpm_max", "fan speed")
    put("airflow_cfm", _range_max(rows.get("airflow")))
    put("static_pressure_mmh2o", _range_max(rows.get("air pressure")))
    put("noise_db", _range_max(rows.get("fan noise level")))
    connector = re.search(r"(\d)-?pin", rows.get("connector", ""), re.I)
    if connector:
        put("connector", f"{connector.group(1)}-pin")


def _aio(rows, put) -> None:
    _speed(rows, put, "fan_rpm_min", "fan_rpm_max", "speed")
    put("airflow_cfm", _range_max(rows.get("airflow")))
    put("noise_db", _range_max(rows.get("noise")))
