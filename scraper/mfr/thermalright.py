"""
mfr/thermalright.py - thermalright.com product pages (feasibility: PASS).

Verdict (Oct 2026): robots.txt only blocks WooCommerce cart/admin paths;
wp-sitemap-posts-product-1.xml lists the product slugs; the "Specifications"
tab is server-rendered as <th>/<td> rows (no JS). Slugs are the retail model
names, so a product joins on its part number when that equals the slug
(`ROYAL-PRETOR-130-ULTRA-BLACK`), otherwise on the longest slug that prefixes
its brand-stripped name (`tl-s12-s` for "TL-S12-S Halo ... 120mm"); two equally
long candidates are skipped. Pages carry no SKU, UPC or socket list, so only
the numbers printed in the table are read (cooler height, fan size, rpm,
airflow, pressure, noise, connector).
"""

from __future__ import annotations

import re

from .common import html_rows, norm_name, number_range, typed

BRAND = "Thermalright"
BASE_URL = "https://www.thermalright.com"
SITEMAP = BASE_URL + "/wp-sitemap-posts-product-1.xml"
CATEGORIES = ("case_fan", "cooler_air", "aio", "cooling_other")

_LOC_RE = re.compile(r"<loc>(https://www\.thermalright\.com/product/([^/<]+)/?)</loc>")


def index(client) -> list[dict]:
    entries = []
    for url, slug in _LOC_RE.findall(client.get(SITEMAP) or ""):
        entries.append({"url": url, "slug": slug, "key": norm_name(slug)})
    return entries


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    for value in (product.get("specs") or {}).get("part_numbers") or []:
        entry = entries_by_key.get(norm_name(value))
        if entry:
            return entry
    # Whole-token prefix: "TL C12CG" must not match the slug "tl-c12c".
    words = re.findall(r"[a-z0-9]+", re.sub(r"(?i)thermalright", " ",
                                           str(product.get("canonical_name") or "")).lower())
    best, tie = None, False
    for entry in entries_by_key.values():
        tokens = entry["slug"].lower().split("-")
        if len(norm_name(entry["slug"])) >= 5 and words[:len(tokens)] == tokens:
            if best is None or len(tokens) > best[0]:
                best, tie = (len(tokens), entry), False
            elif len(tokens) == best[0] and entry is not best[1]:
                tie = True
    return None if best is None or tie else best[1]


def _blocks(page: str) -> list[tuple[str, str]]:
    return [(re.sub(r"\s+", " ", label).strip().lower(), value) for label, value in html_rows(page)]


def _dims(raw) -> tuple[int, int, int] | None:
    found = re.findall(r"[LWHD]\s*(\d+(?:\.\d+)?)\s*mm", str(raw or ""))
    if len(found) != 3:
        return None
    return (int(round(float(found[0]))), int(round(float(found[1]))),
            int(round(float(found[2]))))


def parse(page: str, category: str) -> dict:
    rows = _blocks(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    # First fan table = first "Dimension" row whose height is fan-thin (<= 40 mm).
    fan = None
    heatsink = None
    for index_, (label, value) in enumerate(rows):
        if label == "dimension":
            dims = _dims(value)
            if dims and dims[2] <= 40 and fan is None:
                fan = index_
            elif dims and dims[2] > 40 and heatsink is None:
                heatsink = dims
    fan_rows = dict(rows[fan:fan + 9]) if fan is not None else {}
    fan_dims = _dims(fan_rows.get("dimension"))
    if category in ("cooler_air", "cooling_other"):
        if heatsink:
            put("height_mm", heatsink[2])
        if fan_dims:
            put("fan_size_mm", min(fan_dims[0], fan_dims[1]))
    elif category == "aio":
        if fan_dims:
            put("fan_size_mm", min(fan_dims[0], fan_dims[1]))
    if category in ("case_fan", "cooler_air", "aio", "cooling_other"):
        speed = number_range(re.sub(r"[±].*", "", fan_rows.get("rated speed", "")))
        if speed:
            put("rpm_max" if category == "case_fan" else "fan_rpm_max", int(speed[1]))
        flow = re.match(r"\s*(\d+(?:\.\d+)?)\s*CFM", fan_rows.get("air flow", ""), re.I)
        if flow:
            put("airflow_cfm", float(flow.group(1)))
        noise = number_range(fan_rows.get("noise level"))
        if noise:
            put("noise_db", noise[1])
    if category == "aio":
        connectors = []
        first = dict(rows)
        if re.search(r"4\s*-?\s*pin\s*PWM", fan_rows.get("connector") or first.get("connector", ""), re.I):
            connectors.append("4-pin PWM")
        if re.search(r"3\s*-?\s*pin\s*5\s*V", first.get("argb connector", ""), re.I):
            connectors.append("3-pin ARGB")
        if connectors:
            put("connectors", connectors)
    if category == "case_fan":
        if fan_dims:
            put("size_mm", min(fan_dims[0], fan_dims[1]))
        pressure = re.match(r"\s*(\d+(?:\.\d+)?)\s*mm", fan_rows.get("air pressure", ""), re.I)
        if pressure:
            put("static_pressure_mmh2o", float(pressure.group(1)))
        connector = fan_rows.get("connector", "")
        pins = re.search(r"(\d)\s*-?\s*pin", connector, re.I)
        if pins:
            put("connector", f"{pins.group(1)}-pin")
            put("pwm", bool(re.search(r"pwm", connector, re.I)))
    return out
