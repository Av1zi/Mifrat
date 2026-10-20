"""
mfr/lianli.py - lian-li.com product pages (feasibility: PASS, re-checked Oct 2026).

The Phase-1 verdict ("spec tab rendered client-side") was wrong for the pages
that matter: robots.txt only blocks WooCommerce cart/log paths, the AIOSEO
product sitemap (product-sitemap.xml, ~135 URLs) lists every product, and the
product pages carry the specification as plain server-rendered <th>/<td> rows
("MODEL NO.", "FAN SPEED", "GPU LENGTH CLEARANCE", "MAX. DC OUTPUT" ...). One
page covers a whole family, so the rows form repeated blocks (one per model,
each opening with PRODUCT NAME / MODEL NAME); every block becomes its own
manufacturer entry keyed on the MODEL NO. it prints, which is the part number
the retailers carry (12TLLCD3B, O11VMX, SX1000P-B ...). The first table of a
family page (MODEL | AIRFLOW) is a summary and is ignored.
"""

from __future__ import annotations

import re

from .common import (efficiency_tier, fan_mounts, front_io_ports, html_rows, mb_form_factor_list,
                     psu_connector_counts, psu_length, radiator_sizes,
                     typed)

BRAND = "Lian Li"
BASE_URL = "https://lian-li.com"
SITEMAP = BASE_URL + "/product-sitemap.xml"
CATEGORIES = ("case", "case_fan", "psu")

_LOC_RE = re.compile(r"<loc>(?:<!\[CDATA\[)?(https://lian-li\.com/product/[^<\]]+?)(?:\]\]>)?</loc>")
_START_LABELS = {"product name", "model name", "product"}
_COLOURS = {"BLACK", "WHITE", "SILVER", "GREY", "GRAY", "BLUE", "RED", "PINK", "GREEN", "SNOW",
            "BK", "WH"}


def index(client) -> list[dict]:
    page = client.get(SITEMAP) or ""
    seen: dict[str, dict] = {}
    for url in _LOC_RE.findall(page):
        seen.setdefault(url, {"url": url, "key": ""})
    return list(seen.values())


def in_scope(entry: dict) -> bool:
    return True


def classify(entry: dict, page: str) -> str | None:
    return "multi"                   # per-block categories decided in parse()


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    return None                      # joins on the MODEL NO. printed in each block


def _blocks(page: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for label, value in html_rows(page):
        key = re.sub(r"\s+", " ", label).strip().lower()
        if key in _START_LABELS:
            current = {}
            blocks.append(current)
        if current is None:
            continue
        current.setdefault(key, value)
    return blocks


def _category(block: dict[str, str]) -> str | None:
    if "motherboard support" in block or "gpu length clearance" in block:
        return "case"
    if "max. dc output" in block or "power supply design" in block:
        return "psu"
    if "fan speed" in block and "max. airflow" in block and "pump" not in " ".join(block):
        return "case_fan"
    return None


def _model_ids(block: dict[str, str]) -> list[str]:
    raw = block.get("model no.") or block.get("model") or ""
    ids: list[str] = []
    for part in re.split(r"\s*/\s*|,", raw):
        tokens = part.split()
        if not tokens:
            continue
        ids.append(tokens[0])
        stripped = [t for t in tokens if t.upper() not in _COLOURS]
        if stripped and "".join(stripped) != tokens[0]:
            ids.append("".join(stripped))
    return ids


def _colour_variants(ids: list[str], letters: str) -> list[str]:
    """Lian Li marks the colour with the last letter of the model number (O11VMX
    = black, O11VMW = white; fans 12TLLCD3B / 12TLLCD3W) and the retailers append
    the word as well (O11VMX-BLACK). A colour variant is the same hardware, so a
    page printing one colour also answers for its sibling spellings."""
    out: list[str] = []
    for model in ids:
        base = re.sub(r"[^A-Za-z0-9]", "", model).upper()
        base = re.sub(r"(BLACK|WHITE)$", "", base)
        if base not in out:
            out.append(base)
        if len(base) > 3 and base[-1] in letters:
            for letter in letters:
                for suffix in ("", "BLACK", "WHITE"):
                    alias = base[:-1] + letter + suffix
                    if alias not in out:
                        out.append(alias)
    return out


def parse(page: str, category: str) -> dict:
    out_blocks = []
    for block in _blocks(page):
        kind = _category(block)
        ids = _model_ids(block)
        if kind is None or not ids:
            continue
        out: dict = {}

        def put(field: str, raw, kind=kind, out=out) -> None:
            if raw is None:
                return
            value = typed(kind, field, raw)
            if value is not None:
                out[field] = value

        if kind == "case":
            _case(block, put)
        elif kind == "case_fan":
            _fan(block, put)
        else:
            _psu(block, put)
        out["_category"] = kind
        out["_ids"] = _colour_variants(ids, "XW" if kind == "case" else "BW") if kind != "psu" else ids
        out_blocks.append(out)
    return {"_blocks": out_blocks}


def _mm(raw) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(raw or ""), re.I)
    return int(round(float(match.group(1)))) if match else None


def _pick(block, *labels) -> str:
    for label in labels:
        if block.get(label):
            return block[label]
    return ""


_POSITION = re.compile(r"\b(top|front|side|rear|bottom)\b[^:：/]{0,30}[:：]", re.I)


def _by_position(text: str) -> dict[str, str]:
    """'Top: 3 x 120mm / Side: 3 x 120mm or 2 x 140mm / Rear: 1 x 120mm' ->
    {'top': '3 x 120mm', ...}; the first statement of a position wins
    ("Side (With SFX PSU): ... / Side (With ATX PSU): ...")."""
    out: dict[str, str] = {}
    # Rows run together where the page had line breaks ("120/140mmFront:2 x").
    text = re.sub(r"(?<=[a-z0-9])(?=(?:Top|Front|Side|Rear|Bottom)\s*[:：(])", " / ", text)
    marks = list(_POSITION.finditer(text))
    for n, mark in enumerate(marks):
        end = marks[n + 1].start() if n + 1 < len(marks) else len(text)
        value = text[mark.end():end]
        # Stop at a footnote ("/ *Total max thickness: ...") or another
        # labelled spot ("/ On Drive Cage: 60mm x 1").
        value = re.split(r"/\s*\*|/\s*[A-Za-z][A-Za-z ()]*[:：]", value)[0]
        out.setdefault(mark.group(1).lower(), value.strip(" /"))
    return out


def _case(block, put) -> None:
    support = _pick(block, "motherboard support", "motherboard")
    forms = mb_form_factor_list(re.sub(r"back-?connect.*", "", support, flags=re.I))
    if forms:
        put("mb_form_factors", forms)
    put("max_gpu_length_mm", _mm(_pick(block, "gpu length clearance", "max gpu length",
                                       "maximum gpu length", "vga length")))
    put("max_cooler_height_mm", _mm(_pick(block, "cpu cooler height clearance", "cpu height clearance",
                                          "maximum cpu cooler height", "max cpu cooler height",
                                          "cpu cooler / height clearance", "cpu cooler clearance")))
    if re.search(r"tempered glass|acrylic|window", _pick(block, "materials", "material"), re.I):
        put("side_panel", "Windowed")
    fans = _by_position(block.get("fan support", ""))
    for position in ("front", "top", "side", "rear", "bottom"):
        if position in fans:
            put(f"fan_{position}", fan_mounts(fans[position]))
    volume = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*L\s*", block.get("capacity", ""), re.I)
    if volume:
        put("volume_l", float(volume.group(1)))
    weight = re.search(r"(\d+(?:\.\d+)?)\s*kg", block.get("net weight", ""), re.I)
    if weight:
        put("weight_kg", float(weight.group(1)))
    included = _pick(block, "included fans", "included fan")
    if re.search(r"\bA-?RGB\b", included, re.I):
        put("lighting", "ARGB")
    put("model", _pick(block, "model name", "product name") or None)
    dims = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*x\s*(\d+(?:\.\d+)?)\s*mm\s*x\s*(\d+(?:\.\d+)?)\s*mm\s*\(\s*DxWxH",
                     block.get("dimensions", ""), re.I)
    if dims:
        put("dimensions_mm", f"W={round(float(dims.group(2)))} H={round(float(dims.group(3)))} "
                             f"D={round(float(dims.group(1)))}mm")
    slots = re.match(r"\s*(\d{1,2})\b", _pick(block, "expansion slot", "expansion slots",
                                               "pcie expansion slots"))
    if slots:
        put("expansion_slots", slots.group(1))
    storage = _pick(block, "storage", "drive support", "drive", "drives", "storage support")
    # Several mounting spots ("Bottom: 2.5" x 4 or 3.5" x 2 / Side: ... / Drive
    # Cage: ...") share mounts between sizes, so no per-size total is stated:
    # only a single-spot description is read.
    if len(re.findall(r"[A-Za-z][^:：/]{0,30}[:：]", storage)) > 1:
        storage = ""
    for size, field in (("3.5", "drive_bays_35"), ("2.5", "drive_bays_25")):
        size_first = re.escape(size) + r"\s*[”″\"'′’]*\s*(?:HDD|SSD)?\s*[x×]\s*(\d+)"
        counts = [int(n) for n in re.findall(size_first, storage, re.I)]
        counts += [int(n) for n in re.findall(r"(\d+)\s*[x×]\s*" + re.escape(size), storage, re.I)]
        if counts:
            put(field, max(counts))
    ports = front_io_ports(_pick(block, "i/o ports", "io ports", "front i/o"))
    if ports:
        put("front_usb", ports)
    # "Top: 1 x 360/240mm" - every size of a slash list counts; the thickness
    # footnotes ("*Outer scenario ... 120mm(120mm fan on top)") do not.
    sizes: set[int] = set()
    for segment in re.split(r"\s/\s|/(?=\s*\*)", block.get("radiator support", "")):
        if not re.match(r"\s*(?:\*|\d+(?:\.\d+)?\s*mm\s*\()", segment):
            sizes |= radiator_sizes(segment)
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})


def _fan(block, put) -> None:
    size = re.match(r"\s*(\d{2,3})\s*x\s*(\d{2,3})\s*x\s*\d{2}", block.get("fan dimension", ""))
    if size:
        put("size_mm", min(int(size.group(1)), int(size.group(2))))
    count = re.fullmatch(r"\s*(\d{1,2})\s*", block.get("number of fans", ""))
    if count:
        put("quantity", int(count.group(1)))
    speeds = [int(n) for n in re.findall(r"\d{3,4}", block.get("fan speed", ""))]
    if speeds:
        if len(speeds) > 1:
            put("rpm_min", min(speeds))
        put("rpm_max", max(speeds))
    for label, field, unit in (("max. airflow", "airflow_cfm", "CFM"),
                               ("max. air pressure", "static_pressure_mmh2o", "mm"),
                               ("acoustic noise", "noise_db", "dB")):
        match = re.match(r"\s*(\d+(?:\.\d+)?)\s*" + unit, block.get(label, ""), re.I)
        if match:
            put(field, float(match.group(1)))
    connector = block.get("connector type", "") + " " + block.get("fan speed", "")
    pins = re.search(r"\b(\d)\s*-?\s*pin\b", connector, re.I)
    if pins and re.search(r"pwm", connector, re.I):
        put("connector", f"{pins.group(1)}-pin")
        put("pwm", True)


def _psu(block, put) -> None:
    watts = re.search(r"(\d{3,4})\s*W", block.get("max. dc output", ""), re.I)
    if watts:
        put("wattage_w", int(watts.group(1)))
    put("efficiency", efficiency_tier(block.get("certification")))
    design = block.get("power supply design", "").lower()
    if design.startswith("full"):
        put("modular", "full")
    elif design.startswith("semi"):
        put("modular", "semi")
    elif design.startswith("non"):
        put("modular", "no")
    form = block.get("form factor", "")
    version = re.search(r"\bATX\s*(3\.[01])\b", form, re.I)
    if version:
        put("atx_version", f"ATX {version.group(1)}")
    if re.match(r"\s*SFX-?L", form, re.I):
        put("type", "SFX-L")
    elif re.match(r"\s*SFX", form, re.I):
        put("type", "SFX")
    elif re.match(r"\s*(?:ATX|EPS)", form, re.I):
        put("type", "ATX")
    fan = re.search(r"(\d{2,3})\s*mm", _pick(block, "fan type", "fan spec", "fan spc"), re.I)
    if fan:
        put("fan_size_mm", int(fan.group(1)))
    put("length_mm", psu_length(block.get("dimensions")))
    # "Model No." can list every colour ("SP750 BLACK / SP750 WHITE").
    put("model", _pick(block, "model name", "product name", "model no.", "model") or None)
    version = re.search(r"\bATX\s*(3\.[01])\b", block.get("atx12v version", ""), re.I)
    if version:
        put("atx_version", f"ATX {version.group(1)}")
    # "1 x 8/6+2 Pin PCIe connector (550mm) x3pcs / ... 12VHPWR connector
    # (400mm) × 1pcs": connectors per cable x cables.
    lines = []
    for chunk in re.split(r"pcs\b\s*/?", block.get("connectors", ""), flags=re.I):
        item = re.match(r"\s*(?:(\d{1,2})\s*[x×]\s*)?(.*?connector).*?[x×]\s*(\d{1,2})\s*$", chunk, re.I)
        if item:
            lines.append(f"{int(item.group(1) or 1) * int(item.group(3))} x {item.group(2)}")
    for field, count in psu_connector_counts(lines).items():
        put(field, count)
