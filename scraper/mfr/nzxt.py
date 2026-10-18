"""
mfr/nzxt.py - nzxt.com product pages (feasibility: PASS).

Verdict (Oct 2026): robots.txt allows product pages (Shopify storefront);
sitemap.xml -> sitemap_products_1.xml lists ~110 product handles; the page is
server-rendered with a `tech-specs__row` label/value table and a "Model
Number" row that names every colour variant's part number plus its UPC/EAN
("RF-D12SF-W1 (White) / RF-D12SF-B1 (Black)"), so catalog products join EXACTLY
on the part number or barcode they already carry. Every non-packaging product
page is fetched (~110) and categorised from its own rows.
"""

from __future__ import annotations

import html as html_lib
import re

from .common import (clean, front_io_ports, mb_form_factor_list, number_range, typed)

BRAND = "NZXT"
BASE_URL = "https://nzxt.com"
SITEMAP = BASE_URL + "/sitemap.xml"
CATEGORIES = ("case", "case_fan", "aio", "cooler_air")

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_ROW_RE = re.compile(
    r'tech-specs__cell--label">(.*?)</div>\s*<div class="tech-specs__cell tech-specs__cell--value">(.*?)</div>',
    re.S)
_SKIP_HANDLE = re.compile(r"packaging|gift|bundle|subscription|flex|pc-|prebuilt|rma", re.I)


def index(client) -> list[dict]:
    root = client.get(SITEMAP) or ""
    entries: dict[str, dict] = {}
    for sub in _LOC_RE.findall(root):
        sub = html_lib.unescape(sub)
        if not sub.startswith(BASE_URL + "/sitemap_products"):     # default locale only
            continue
        for url in _LOC_RE.findall(client.get(sub) or ""):
            if "/products/" not in url:
                continue
            handle = url.rstrip("/").rsplit("/", 1)[-1]
            if _SKIP_HANDLE.search(handle):
                continue
            entries.setdefault(url, {"url": url, "key": ""})
    return list(entries.values())


def in_scope(entry: dict) -> bool:
    return True


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    return None                          # joins on the part numbers the page prints


def _rows(page: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, value in _ROW_RE.findall(page):
        label = clean(re.sub(r"<[^>]+>", " ", label)).lower()
        value = clean(html_lib.unescape(re.sub(r"<[^>]+>", " ", value)))
        if label and value:
            out.setdefault(label, value)
    return out


def classify(entry: dict, page: str) -> str | None:
    rows = _rows(page)
    if "enclosure type" in rows or "motherboard support" in rows:
        return "case"
    if "cold plate material" in rows and "intel socket" in rows:
        return "aio"
    if "airflow" in rows and "static pressure" in rows:
        return "case_fan"
    return None


def _mm(raw) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(raw or ""), re.I)
    return int(round(float(match.group(1)))) if match else None


def parse(page: str, category: str) -> dict:
    rows = _rows(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    if category == "case":
        _case(rows, put)
    elif category == "case_fan":
        _fan(rows, put)
    elif category in ("aio", "cooler_air"):
        _cooler(rows, put, category)
    ids = []
    for label in ("model number", "upc", "ean"):
        ids += re.findall(r"[A-Z0-9]{2,3}-[A-Z0-9-]{3,}|\b\d{12,13}\b", rows.get(label, ""))
    return {**out, "_ids": ids}


def _case(rows, put) -> None:
    kind = rows.get("enclosure type", "")
    if kind:
        put("type", re.sub(r"[-_]+", " ", kind).strip())
    forms = mb_form_factor_list(rows.get("motherboard support", ""))
    if forms:
        put("mb_form_factors", forms)
    put("max_gpu_length_mm", _mm(rows.get("gpu length")))
    put("max_cooler_height_mm", _mm(rows.get("cpu cooler height")))
    for label, field in (('2.5" drive bays', "drive_bays_25"), ('3.5" drive bays', "drive_bays_35")):
        value = re.fullmatch(r"\s*(\d{1,2})\s*", rows.get(label, ""))
        if value:
            put(field, int(value.group(1)))
    slots = re.fullmatch(r"\s*(\d{1,2})\s*", rows.get("expansion slots", ""))
    if slots:
        put("expansion_slots", slots.group(1))
    ports = front_io_ports(", ".join(label for label in rows
                                     if re.match(r"usb|headset|audio", label)
                                     and re.fullmatch(r"\s*[1-9]\d?\s*", rows[label])))
    if ports:
        put("front_usb", ports)
    if re.search(r"tempered glass", rows.get("materials", ""), re.I):
        put("side_panel", "Windowed")
    dims = re.match(r"\s*(\d{2,3})\s*x\s*(\d{2,3})\s*x\s*(\d{2,3})", rows.get("dimensions (h x w x d)", ""))
    if dims:
        put("dimensions_mm", f"W={dims.group(2)} H={dims.group(1)} D={dims.group(3)}mm")
    weight = re.match(r"\s*(\d+(?:\.\d+)?)\s*kg", rows.get("weight", ""), re.I)
    if weight:
        put("weight_kg", float(weight.group(1)))


def _fan(rows, put) -> None:
    size = re.match(r"\s*(\d{2,3})\s*x\s*\d{2,3}\s*x\s*\d{2}\s*mm", rows.get("dimensions (l x w x h)", "")
                    or rows.get("dimensions", ""))
    if size:
        put("size_mm", int(size.group(1)))
    span = number_range(re.sub(r"[±].*", "", rows.get("speed", "")))
    if span:
        if span[0] != span[1] and span[0] >= 100:
            put("rpm_min", int(span[0]))
        put("rpm_max", int(span[1]))
    for label, field in (("airflow", "airflow_cfm"), ("static pressure", "static_pressure_mmh2o"),
                         ("noise level", "noise_db")):
        span = number_range(rows.get(label))
        if span:
            put(field, span[1])
    connector = rows.get("fan connector") or rows.get("power connector") or ""
    pins = re.search(r"(\d)-?pin", connector, re.I)
    if pins:
        put("connector", f"{pins.group(1)}-pin")
        put("pwm", bool(re.search(r"pwm", connector, re.I)))
    quantity = re.fullmatch(r"\s*(\d{1,2})\s*", rows.get("quantity", ""))
    if quantity:
        put("quantity", int(quantity.group(1)))


def _cooler(rows, put, category) -> None:
    sockets = []
    for label in ("intel socket", "amd socket"):
        text = rows.get(label, "")
        if label.startswith("intel"):
            for number in re.findall(r"\b(1[0-9]{3})\b", text):
                token = f"LGA{number}"
                if token not in sockets:
                    sockets.append(token)
        else:
            sockets += [t for t in re.findall(r"\bAM\d\b", text) if t not in sockets]
    if sockets:
        put("sockets", sockets)
    size = re.match(r"\s*(\d{2,3})\s*x\s*\d{2,3}\s*x\s*\d{2}\s*mm", rows.get("dimensions", ""))
    if size:
        put("fan_size_mm", int(size.group(1)))
