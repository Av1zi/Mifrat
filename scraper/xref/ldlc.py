"""
xref/ldlc.py - ldlc.com (French retailer) product pages, English site.

Reachable from the Nano's home IP by an honestly identified client, refused
from datacenter addresses (Oct 2026), so this site runs on the Nano
(nano/run_xref.sh). Search (/en/search/<MPN>/) lists product tiles linking to
/en/product/PB<digits>.html. A product page prints the barcode in
`<div id="productphoto" data-ean="...">` and a spec table
`<table id="product-parameters">` whose rows are a group `<h2>`, a label `<h3>`
and a value cell. The brand's model code is the "Model" row ("NOCTUA NH-U12A").

Joined on the EAN or on the "Model" code once the brand word is dropped, both
compared with our own part numbers (runner), never on the product name.

Only coolers, fans and memory are mapped: they are what the saved pages
(scraper/fixtures/ldlc) show. Other categories need their pages saved first.
The search is lenient (a 1x16GB code can list the 2x8GB kit); the exact-key join
in the runner is what rejects those.
"Processor support" prints ONE socket for a cooler that fits many, so sockets
are not read.
"""

from __future__ import annotations

import html
import re
import urllib.parse

from ..mfr.common import norm_mpn, norm_upc, typed

SITE = "ldlc"
BASE_URL = "https://www.ldlc.com"
CATEGORIES = ("cooler_air", "case_fan", "memory")
IDENTIFY = True                     # MifratSpecBot, never a borrowed browser name
M3H_TO_CFM = 0.588578

_TABLE = re.compile(r'<table id="product-parameters">(.*?)</table>', re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_LABEL = re.compile(r'<td class="label"[^>]*><h3>(.*?)</h3>', re.S)
_VALUE = re.compile(r'<td class="(?:no-)?checkbox"[^>]*>(.*?)</td>', re.S)
_EAN = re.compile(r'id="productphoto"[^>]*data-ean="(\d{8,14})"')
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_PRODUCT_LINK = re.compile(r'href="(/en/product/PB[0-9A-Za-z]+\.html)(?:#[^"]*)?"')


def search_url(code: str) -> str:
    return f"{BASE_URL}/en/search/{urllib.parse.quote(code)}/"


def tile_urls(page: str, limit: int = 2) -> list[str]:
    return [BASE_URL + path for path in list(dict.fromkeys(_PRODUCT_LINK.findall(page)))[:limit]]


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_page(page: str) -> dict:
    rows: dict[str, str] = {}
    table = _TABLE.search(page or "")
    for row in _ROW.findall(table.group(1) if table else ""):
        label, value = _LABEL.search(row), _VALUE.search(row)
        if label and value:
            name, text = _clean(label.group(1)), _clean(value.group(1))
            if name and text:
                rows.setdefault(name, text)         # "Height" vs "Height (fan included)": first wins
    ean = _EAN.search(page or "")
    title = _TITLE.search(page or "")
    # "NOCTUA NH-U12A": the code is the model minus a leading brand word.
    code = rows.get("Model", "")
    for word in dict.fromkeys(rows.get("Brand", "").split()):
        if code.lower().startswith(word.lower() + " "):
            code = code[len(word):].strip()
    return {"rows": rows, "ean": ean.group(1) if ean else None, "mpn": code or None,
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


def _airflow_cfm(value) -> float | None:
    number = _num(value)
    if number is None:
        return None
    if re.search(r"m³/h|m3/h", str(value), re.I):
        return round(number * M3H_TO_CFM, 1)
    return number if re.search(r"cfm", str(value), re.I) else None


def specs_for(category: str, rows: dict) -> dict:
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    if category not in CATEGORIES:
        return out
    if category == "memory":
        return _memory(rows, put, out)
    put("color", rows.get("Color"))
    lit = _yes(rows.get("Luminous"))
    if lit is False:
        put("lighting", "No")
    rpm_low, rpm_high = _num(rows.get("Minimum rotation speed")), _num(rows.get("Maximum rotation speed"))
    noise = _num(rows.get("Max sound level")) if re.search(r"dB", rows.get("Max sound level", "")) else None
    flow = _airflow_cfm(rows.get("Max airflow"))
    size = _num(rows.get("Fan diameter")) if re.search(r"mm", rows.get("Fan diameter", "")) else None
    if category == "cooler_air":
        put("fan_size_mm", size)
        put("fan_rpm_min", rpm_low)
        put("fan_rpm_max", rpm_high)
        put("noise_db", noise)
        put("airflow_cfm", flow)
        height = rows.get("Height (fan included)")
        if height and re.search(r"mm", height):
            put("height_mm", _num(height))
        kind = rows.get("Cooling type", "").lower()
        put("fanless", True if "passive" in kind and "active" not in kind
            else False if "active" in kind else None)
    else:  # case_fan
        put("size_mm", size)
        put("rpm_min", rpm_low)
        put("rpm_max", rpm_high)
        put("noise_db", noise)
        put("airflow_cfm", flow)
        pwm = _yes(rows.get("PWM"))
        if pwm is not None:
            put("pwm", pwm)
    return out


def _memory(rows: dict, put, out: dict) -> dict:
    kind = re.search(r"DDR\d", rows.get("Memory type", ""))
    rate = re.search(r"(DDR\d)\s*(\d{3,5})\s*MHz", rows.get("Memory Frequency(ies)", ""), re.I)
    if kind:
        put("memory_type", kind.group(0))
    if rate:
        put("speed_mhz", int(rate.group(2)))
        put("speed", f"{rate.group(1).upper()}-{rate.group(2)}")
    form = rows.get("Memory format", "")
    put("form_factor", "SO-DIMM" if re.search(r"SO-?DIMM", form, re.I)
        else "DIMM" if re.search(r"\bDIMM\b", form, re.I) else None)
    modules, each, total = (_num(rows.get(k)) for k in
                            ("Number of modules", "Capacity per module", "Capacity"))
    if modules and each and re.search(r"GB", rows.get("Capacity per module", "")):
        put("module_count", int(modules))
        put("module_size_gb", int(each))
        if total and re.search(r"GB", rows.get("Capacity", "")) and abs(modules * each - total) < 0.5:
            put("total_gb", int(total))
    put("cas_latency", _num(rows.get("CAS Latency")))
    volts = rows.get("Voltage", "")
    if re.search(r"volt", volts, re.I):
        put("voltage_v", _num(volts))
    sink = _yes(rows.get("Radiator"))
    if sink is not None:
        put("heat_spreader", sink)
    if _yes(rows.get("LED")) is False and _yes(rows.get("LED RGB")) is not True:
        put("lighting", "No")               # "Yes" alone does not say RGB or ARGB
    spec = rows.get("Memory specification", "").lower()
    if "unbuffered" in spec:
        put("registered", False)
    return out
