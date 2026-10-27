"""
mfr/corsair.py - corsair.com product pages (feasibility: PASS).

Verdict (Oct 2026): robots.txt allows /us/en/p/ product pages; the product
sitemap (us-sitemap-products-1.xml) lists ~4,000 URLs that embed the
manufacturer part number (".../p/case-fans/co-9050111-ww/<slug>"), so catalog
products join EXACTLY on MPN (region suffix dropped: the importer sells -EU
codes, the US sitemap lists -NA / -WW); pages are server-rendered with a
"TechSpecItem" table (<th>label</th><td>value</td>), no JS needed.
Storage pages (MP600 SSDs) carry no such table and are skipped.
"""

from __future__ import annotations

import re

from .common import (base_mpn, clean, fan_mounts, front_io_ports, html_rows,
                     mb_form_factor_list, psu_connector_counts, psu_length,
                     radiator_sizes, spaced_mm, spec_range, typed)

BRAND = "Corsair"
BASE_URL = "https://www.corsair.com"
SITEMAP = BASE_URL + "/us-sitemap-products-1.xml"
CATEGORIES = ("case_fan", "aio", "cooler_air", "cooling_other", "case", "psu", "memory")

_URL_RE = re.compile(r"https://www\.corsair\.com/us/en/p/([^/]+)/([^/]+)/([^/<\s]+)")


def index(client) -> list[dict]:
    """[{url, key, path_category}] for every product URL in the sitemap."""
    page = client.get(SITEMAP)
    entries = []
    for match in _URL_RE.finditer(page or ""):
        path_category, mpn_part, _slug = match.groups()
        key = base_mpn(mpn_part)
        if key:
            entries.append({"url": match.group(0), "key": key,
                            "path_category": path_category})
    return entries


_PATH_CATEGORY = {"case": "pc-cases", "case_fan": "case-fans", "aio": "cpu-coolers",
                  "cooler_air": "cpu-coolers", "cooling_other": "cpu-coolers",
                  "psu": "power-supply-units"}
_COLOURS = {"black", "white", "gray", "grey", "silver", "red", "blue", "pink", "green",
            "yellow", "purple", "orange", "bamboo", "wood", "oak", "satin", "aluminum"}
# Words a product page title adds to (or a catalog title drops from) the model
# name without changing which product it is.
_GENERIC = {"corsair", "pc", "case", "mid", "tower", "full", "micro", "mini", "atx", "itx", "matx",
            "compact", "dual", "chamber", "liquid", "cpu", "cooler", "aio", "fan", "fans", "pwm",
            "cooling", "kit", "pack", "single", "triple", "expansion", "starter", "computer",
            "gaming", "tempered", "glass", "mesh", "steel", "panel", "with", "and", "for", "ww",
            "na", "eu", "icue", "link", "series", "water", "radiator", "pro", "edition"}
_NOISE_RE = re.compile(r"^\d+x\d+(mm)?$|^\d+mm$|^\d{1,2}x$")


def _tokens(text: str) -> tuple[frozenset, frozenset]:
    """(model tokens, colour tokens) of a title or URL slug."""
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    colours = frozenset(w for w in words if w in _COLOURS)
    model = frozenset(w for w in words
                      if w not in _COLOURS and w not in _GENERIC and not _NOISE_RE.match(w))
    return model, colours


_name_index: dict[int, list] = {}


def _slug_index(entries_by_key: dict) -> list:
    cached = _name_index.get(id(entries_by_key))
    if cached is None:
        cached = []
        for entry in entries_by_key.values():
            slug = entry["url"].rsplit("/", 1)[-1]
            slug = re.sub(r"[-]?[a-z]{2}-?\d{6,8}(-[a-z]{2})?$", "", slug, flags=re.I)
            slug = re.sub(r"-?(ww|na|eu)$", "", slug, flags=re.I)
            cached.append((entry, *_tokens(slug)))
        _name_index[id(entries_by_key)] = cached
    return cached


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    """Exact MPN join first (the part number is in the URL); products with no
    sitemap MPN fall back to a tight name join: the product's model tokens must
    EQUAL the page title's (colour and size words aside), the colour must agree,
    and exactly one page may qualify - anything looser would hand a wrong
    manufacturer row to a product."""
    for value in (product.get("specs") or {}).get("part_numbers") or []:
        entry = entries_by_key.get(base_mpn(value))
        if entry:
            return entry
    group = _PATH_CATEGORY.get(str(product.get("category") or ""))
    if group is None:
        return None
    model, colours = _tokens(re.sub(r"(\d+)\s*x\s*(\d+)", " ", str(product.get("canonical_name") or "")))
    if len(model) < 1 or not any(any(c.isdigit() for c in t) for t in model):
        return None
    found = []
    for entry, slug_model, slug_colours in _slug_index(entries_by_key):
        if entry.get("path_category") != group or slug_model != model:
            continue
        if colours and slug_colours and colours != slug_colours:
            continue
        found.append((entry, bool(colours and colours == slug_colours)))
    exact = [entry for entry, same in found if same]
    pool = exact or [entry for entry, _ in found]
    return pool[0] if len(pool) == 1 else None


# ---------------------------------------------------------------------------
# Spec table -> schema fields, per catalog category
# ---------------------------------------------------------------------------


def _rows(page: str) -> dict[str, str]:
    """label (lowercase) -> value, first occurrence wins."""
    out: dict[str, str] = {}
    for label, value in html_rows(page):
        out.setdefault(re.sub(r"\s+", " ", label).strip().lower(), value)
    return out


def _pick(rows: dict[str, str], *labels: str) -> str | None:
    for label in labels:
        if label in rows:
            return rows[label]
    return None


def _max(raw) -> float | None:
    span = spec_range(raw)
    return span[1] if span else None


def _yes(raw) -> bool | None:
    text = str(raw or "").strip().lower()
    if text in ("yes", "y", "true", "supported"):
        return True
    if text in ("no", "n", "false", "none", "n/a", "not supported"):
        return False
    return None


def _mm(raw) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(raw or ""), re.I)
    return int(round(float(match.group(1)))) if match else None


def _bare_mm(raw) -> int | None:
    match = re.fullmatch(r"\s*(\d{2,4})(?:\.\d+)?\s*", str(raw or ""))
    return int(match.group(1)) if match else None


def parse(page: str, category: str) -> dict:
    """Typed schema fields for one page. Only values that validate survive."""
    rows = _rows(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    if category == "case_fan":
        _fan(rows, put, page)
    elif category in ("aio", "cooler_air", "cooling_other"):
        _cooler(rows, put, category)
    elif category == "psu":
        _psu(rows, put, page)
    elif category == "case":
        _case(rows, put)
    elif category == "memory":
        _memory(rows, put)
    # The colour row is sometimes copied from the sibling SKU (the white
    # 2800X page says "BLACK"); a page whose title names a different colour
    # keeps no colour.
    title_colours = {c.replace("grey", "gray") for c in _tokens(_title(page))[1]}
    colour = str(out.get("color") or "").lower().replace("grey", "gray")
    if colour and title_colours and not title_colours & set(re.findall(r"[a-z]+", colour)):
        del out["color"]
    return out


def _speed(rows, put, low_field: str, high_field: str) -> None:
    raw = _pick(rows, "fan speed", "speed", "rpm")
    span = spec_range(raw) if raw else None
    if span:
        if span[0] != span[1] and span[0] >= 100:   # "10 - 2100" is the PWM floor, not rpm
            put(low_field, int(span[0]))
        put(high_field, int(span[1]))


def _title(page: str) -> str:
    match = re.search(r"<title>([^<]*)</title>", page)
    return clean(match.group(1)) if match else ""


_PACK_WORDS = {"single": 1, "dual": 2, "twin": 2, "triple": 3, "quad": 4}


def _fan(rows, put, page) -> None:
    put("size_mm", _mm(_pick(rows, "fan size", "fan dimensions")))
    put("airflow_cfm", _max(_pick(rows, "fan airflow", "airflow")))
    put("static_pressure_mmh2o",
        _max(_pick(rows, "fan static pressure", "static pressure")))
    _speed(rows, put, "rpm_min", "rpm_max")
    put("noise_db", _max(_pick(rows, "noise level", "sound level", "fan noise level")))
    put("pwm", _yes(_pick(rows, "pwm control", "pwm")))
    # `Package Quantity` counts packages on some kits ("1" on a dual-fan kit),
    # so it is read only when it says more than one; the page title's pack
    # word ("Triple Pack", "Dual Fan Kit") is the fan count itself.
    # ("Dual Light Loop" is a lighting feature, not a count.)
    pack = re.search(r"\b(single|dual|twin|triple|quad)\s+(?:fan\s+)?(?:pack|kit|starter|fan\b|expansion)",
                     _title(page), re.I)
    if pack:
        put("quantity", _PACK_WORDS[pack.group(1).lower()])
    else:
        count = re.fullmatch(r"\s*([2-9])\s*", _pick(rows, "package quantity") or "")
        if count:
            put("quantity", int(count.group(1)))
    # "LED Color: RGB" does not say addressable, so it is not read.


def _color(raw) -> str | None:
    """'BLACK' / 'OLIVE DRAB' -> 'Black' / 'Olive Drab' (catalog spelling)."""
    text = clean(raw)
    if not text or text.upper() in ("NA", "N/A", "NONE"):
        return None
    return text.title()


def _cooler(rows, put, category) -> None:
    sockets = _pick(rows, "cpu socket")
    if sockets:
        put("sockets", [part.strip() for part in sockets.split(",") if part.strip()])
    if category != "cooler_air":
        put("radiator_size_mm", _mm(_pick(rows, "radiator size")))
    _speed(rows, put, "fan_rpm_min", "fan_rpm_max")
    put("airflow_cfm", _max(_pick(rows, "fan airflow", "airflow")))
    put("noise_db", _max(_pick(rows, "noise level", "sound level")))
    put("color", _color(_pick(rows, "color")))
    if category == "cooler_air":
        height = _max(_pick(rows, "product height"))
        if height:
            put("height_mm", int(round(height)))
    elif category == "aio":
        # An AIO's product length is its radiator's (397 on a 360 mm
        # radiator); a figure that is not 1.0-1.25x the size class is some
        # other dimension and is not read.
        size = _mm(_pick(rows, "radiator size"))
        length = _max(_pick(rows, "product length"))
        if size and length and 1.0 <= length / size <= 1.25:
            put("radiator_length_mm", int(round(length)))


_EFFICIENCY = {"white", "bronze", "silver", "gold", "platinum", "titanium"}


def _cable_table(page: str) -> dict[str, int]:
    """Connector counts from the 'QTY | Cable | ... | Total connectors' table
    some PSU pages print (the full cable kit)."""
    from .common import _RowParser

    parser = _RowParser()
    parser.feed(page)
    lines: list[str] = []
    header = None
    for cells in parser.rows:
        if cells and cells[0].strip().upper() == "QTY" and len(cells) >= 4:
            header = [c.strip().lower() for c in cells]
            continue
        if header is None:
            continue
        if len(cells) != len(header) or not cells[0].strip().isdigit():
            if lines:
                break
            continue
        total = cells[3].strip()
        if total.isdigit():
            lines.append(f"{total} x {cells[1]}")
    return psu_connector_counts(lines)


def _psu(rows, put, page) -> None:
    watts = _max(_pick(rows, "continuous power w"))
    if watts:
        put("wattage_w", int(watts))
    tier = (_pick(rows, "80 plus efficiency", "cybenetics efficiency") or "").strip().lower()
    if tier in _EFFICIENCY:
        put("efficiency", f"80+ {tier.title()}")
    modular = (_pick(rows, "modular") or "").strip().lower()
    if modular.startswith("fully") or modular == "full":
        put("modular", "full")
    elif modular.startswith("semi") or modular == "partial":
        put("modular", "semi")
    elif modular in ("no", "non-modular", "none"):
        put("modular", "no")
    version = re.fullmatch(r"\s*v?([23]\.\d{1,2})\s*", _pick(rows, "atx12v version") or "", re.I)
    if version:
        put("atx_version", f"ATX {version.group(1)}")
    put("atx4_connectors", _max(_pick(rows, "atx connector")))
    put("sata_connectors", _max(_pick(rows, "sata connector")))
    put("molex4_connectors", _max(_pick(rows, "pata connector")))
    put("type", _pick(rows, "psu form factor"))
    put("fan_size_mm", _mm(_pick(rows, "fan size mm", "fan size")))
    put("length_mm", psu_length(_pick(rows, "dimensions")))
    for field, count in _cable_table(page).items():
        if field not in ("atx4_connectors", "sata_connectors", "molex4_connectors"):
            put(field, count)


def _case(rows, put) -> None:
    support = _pick(rows, "motherboard support", "case supported")
    forms = mb_form_factor_list(support or "")
    if forms:
        put("mb_form_factors", forms)
    size = _pick(rows, "case size")
    if size:
        put("type", re.sub(r"[-_]+", " ", size).strip())
    put("max_gpu_length_mm", _mm(_pick(rows, "maximum gpu length", "max gpu length")))
    put("max_cooler_height_mm",
        _mm(_pick(rows, "maximum cpu cooler height", "max cpu cooler height")))
    window = (_pick(rows, "case window", "left side panel", "side panel") or "").strip()
    if window:
        if re.search(r"glass|window|acrylic", window, re.I):
            put("side_panel", "Windowed")
        elif window.lower() in ("none", "no", "n/a", "solid"):
            put("side_panel", "No Window")
    height, length, width = (_mm(_pick(rows, label)) or _bare_mm(_pick(rows, label))
                             for label in ("case height", "case length", "case width"))
    if height and length and width:
        put("dimensions_mm", f"W={width} H={height} D={length}mm")
    weight = re.search(r"(\d+(?:\.\d+)?)\s*kg", _pick(rows, "weight") or "", re.I)
    if weight and float(weight.group(1)) > 0:
        put("weight_kg", float(weight.group(1)))
    sizes: set[int] = set()
    for label, value in rows.items():
        if label.startswith("radiator support"):
            sizes |= radiator_sizes(value)
    if not sizes:
        sizes = radiator_sizes(_pick(rows, "radiator compatibility"))
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
    for label, field in (("fan support - front", "fan_front"), ("fan support - top", "fan_top"),
                         ("fan support - rear", "fan_rear"), ("fan support - side", "fan_side"),
                         ("fan support - bottom", "fan_bottom")):
        value = rows.get(label)
        if value:
            put(field, fan_mounts(value) or spaced_mm(value))
    slots = re.match(r"\s*(\d{1,2})\b", _pick(rows, "case expansion slots") or "")
    if slots:
        put("expansion_slots", slots.group(1))
    ports = front_io_ports(_pick(rows, "case front io"))
    if ports:
        put("front_usb", ports)
    # "(x6) 3.5in (x4) 2.5in"; "(x2) 3.5in or (x2) 2.5in" is one shared cage
    # and is not split.
    bays = _pick(rows, "case drive bays") or ""
    if bays and not re.search(r"\bor\b", bays, re.I):
        for field, size in (("drive_bays_35", "3.5"), ("drive_bays_25", "2.5")):
            count = re.search(rf"\(x(\d{{1,2}})\)\s*{re.escape(size)}\s*in", bays, re.I)
            if count:
                put(field, int(count.group(1)))
    fans = _pick(rows, "included fans") or ""
    if re.search(r"\bA-?RGB\b", fans, re.I):
        put("lighting", "ARGB")
    elif re.search(r"\bRGB\b", fans, re.I):
        put("lighting", "RGB")
    put("color", _color(_pick(rows, "color")))


def _memory(rows, put) -> None:
    size = _pick(rows, "memory size") or ""
    kit = re.search(r"(\d+)\s*GB\s*\(\s*(\d+)\s*x\s*(\d+)\s*GB", size, re.I)
    single = re.fullmatch(r"\s*(\d+)\s*GB\s*", size, re.I)
    if kit:
        put("total_gb", int(kit.group(1)))
        put("module_count", int(kit.group(2)))
        put("module_size_gb", int(kit.group(3)))
    elif single:
        put("total_gb", int(single.group(1)))
        put("module_count", 1)
        put("module_size_gb", int(single.group(1)))
    put("cas_latency", _max(_pick(rows, "tested latency")))
    speed = _max(_pick(rows, "tested speed"))
    if speed:
        put("speed_mhz", int(speed))
    put("voltage_v", _max(_pick(rows, "tested voltage")))
    form = (_pick(rows, "package memory format") or "").upper()
    if form in ("UDIMM", "DIMM"):
        put("form_factor", "DIMM")
        put("registered", False)
    elif form in ("SODIMM", "SO-DIMM"):
        put("form_factor", "SO-DIMM")
    kind = (_pick(rows, "memory type") or "").strip().upper()
    if re.fullmatch(r"DDR[345]", kind):
        put("memory_type", kind)
    lighting = (_pick(rows, "lighting") or "").strip().upper()
    if lighting in ("RGB", "ARGB"):
        put("lighting", lighting)
    put("color", _color(_pick(rows, "memory color")))
    spreader = _pick(rows, "heat spreader")
    if spreader:
        put("heat_spreader", spreader.strip().lower() not in ("none", "no"))
