"""
mfr/amd.py - amd.com processor pages (feasibility: PASS).

Verdict (Oct 2026): robots.txt only disallows /onboarding/, maintenance and
search paths; the English sitemap lists every processor page; each page is
server-rendered with a flat <dt>/<dd> specification list (cores, threads,
clocks, caches, TDP, socket, architecture, memory, ECC, iGPU, product ids) - no
JavaScript needed.

Join: the page slug ends in the model number ("amd-ryzen-7-9800x3d",
"amd-ryzen-5-pro-5650g"), the catalog's CPU `model` carries the same number, so
products join on (model number, PRO flag) when exactly one page claims it; the
boxed/tray product ids the page prints (100-100001084WOF) are stored as extra
identity keys.  Intel is NOT here: ark.intel.com and www.intel.com answer HTTP
403 on robots.txt (see README verdicts).
"""

from __future__ import annotations

import html as html_lib
import re

from ..specs import derive
from .common import clean, typed

BRAND = "AMD"
BASE_URL = "https://www.amd.com"
SITEMAP = BASE_URL + "/en.sitemap.xml"
CATEGORIES = ("cpu",)

_URL_RE = re.compile(
    r"<loc>(https://www\.amd\.com/en/products/processors/"
    r"(?:desktops|workstations|server)/[^<]*?/(amd-[^/<]+)\.html)</loc>")
_PAIR_RE = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.S)


def _slug_key(slug: str) -> tuple[str, bool] | None:
    parts = slug.lower().split("-")
    token = parts[-1]
    if not re.fullmatch(r"\d{4}[a-z0-9]*|\d{3}[a-z0-9]{0,3}", token):
        return None
    return token.upper(), "pro" in parts[:-1]


def index(client) -> list[dict]:
    page = client.get(SITEMAP) or ""
    counts: dict[tuple, int] = {}
    found: dict[tuple, dict] = {}
    for url, slug in _URL_RE.findall(page):
        key = _slug_key(slug)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        found[key] = {"url": url, "key": f"{key[0]}{'-PRO' if key[1] else ''}"}
    # A model number claimed by two pages is ambiguous: never joined.
    return [entry for key, entry in found.items() if counts[key] == 1]


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    specs = product.get("specs") or {}
    model = re.sub(r"[™®]", "", str(specs.get("model") or ""))
    epyc = re.search(r"\bEPYC\s+(\d{4}[A-Z]{0,2})\b", model, re.I)
    if epyc:
        token = epyc.group(1).upper()
    else:
        table_key = derive.cpu_table_key({**specs, "model": model})
        if not table_key or not table_key.startswith("amd:"):
            return None
        token = table_key.split(":", 1)[1]
    is_pro = bool(re.search(r"\bPRO\b", model, re.I))
    return entries_by_key.get(f"{token}{'-PRO' if is_pro else ''}")


def _pairs(page: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, value in _PAIR_RE.findall(page):
        # Tooltips live inside the <dt>: keep only the text before them.
        label = re.sub(r"<i\b.*", "", label, flags=re.S)
        label = clean(re.sub(r"<[^>]+>", " ", label))
        value = clean(html_lib.unescape(re.sub(r"<[^>]+>", " ", value)))
        if label and value:
            out.setdefault(label.lower(), value)
    return out


def _ghz(raw) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*GHz", str(raw or ""), re.I)
    return float(match.group(1)) if match else None


def _mb(raw) -> float | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(MB|KB|GB)\s*", str(raw or ""), re.I)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).upper()
    return value / 1024 if unit == "KB" else value * 1024 if unit == "GB" else value


def parse(page: str, category: str) -> dict:
    rows = _pairs(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed("cpu", field, raw)
        if value is not None:
            out[field] = value

    def number(label: str) -> int | None:
        match = re.fullmatch(r"\s*(\d+)\s*", rows.get(label, ""))
        return int(match.group(1)) if match else None

    put("core_count", number("# of cpu cores"))
    put("thread_count", number("# of threads"))
    smt = rows.get("multithreading (smt)", "").strip().lower()
    if smt in ("yes", "no"):
        put("smt", smt == "yes")
    put("base_clock_ghz", _ghz(rows.get("base clock")))
    put("boost_clock_ghz", _ghz(rows.get("max. boost clock")))
    put("l2_cache_mb", _mb(rows.get("l2 cache")))
    put("l3_cache_mb", _mb(rows.get("l3 cache")))
    tdp = re.search(r"(\d{2,3})\s*W", rows.get("default tdp", ""), re.I)
    if tdp:
        put("tdp_w", int(tdp.group(1)))
    socket = rows.get("cpu socket", "").strip()
    if socket and "," not in socket:
        put("socket", socket)
    architecture = rows.get("processor architecture", "")
    if re.fullmatch(r"Zen\s?\d\+?(?:\s?[a-z]+)?", architecture, re.I):
        put("microarchitecture", architecture)
    node = re.search(r"(\d{1,2})\s*nm", rows.get("processor technology for cpu cores", ""), re.I)
    if node:
        put("lithography_nm", int(node.group(1)))
    memory = re.fullmatch(r"\s*(\d{2,5})\s*GB\s*", rows.get("max. memory", ""), re.I)
    if memory:
        put("max_memory_gb", int(memory.group(1)))
    ecc = rows.get("ecc support", "").strip().lower()
    if ecc:
        put("ecc_support", ecc.startswith("yes"))
    unlocked = rows.get("unlocked for overclocking", "").strip().lower()
    if unlocked in ("yes", "no"):
        put("unlocked", unlocked == "yes")
    graphics = rows.get("graphics model", "").strip()
    if graphics:
        if re.search(r"radeon|graphics", graphics, re.I) and not re.search(r"discrete|n/?a|not", graphics, re.I):
            put("integrated_graphics", re.sub(r"[™®]", "", graphics))
        else:
            put("integrated_graphics", "No")
    ids = []
    for label in ("product id boxed", "product id tray"):
        value = rows.get(label, "")
        ids += [part for part in re.split(r"[,/\s]+", value) if re.search(r"\d{4,}", part)]
    return {**out, "_ids": ids}
