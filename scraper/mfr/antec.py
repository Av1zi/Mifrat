"""
mfr/antec.py - antec.com product pages (feasibility: PASS).

Verdict (Oct 2026): robots.txt is "Disallow:" (allow everything); sitemap.xml
lists every product page (/product/<group>/<slug>); pages are static HTML with
a "SPECIFICATIONS" block of nested two-cell tables and a "UPC#" row, so
products join on UPC when the catalog carries it and otherwise on the longest
slug that prefixes the product's brand-stripped name (a colour suffix such as
"-white" shares the model's specs). Ambiguous names (two equally long slugs)
are skipped, never guessed.

Round 2 (Oct 2026): name matching alone left 167 of 301 Antec products without a
page (catalog names carry series words and colour suffixes the slug lacks). The
retail part number / UPC the catalog already holds is the exact join: every
in-scope page is fetched (`in_scope`/`classify`, ~300 pages) and recorded with
the page's own UPCs plus its slug as a part number (Antec model codes such as
"CX700-RGB-ELITE" ARE the slug), then `store.facts_for` joins on identifiers.
Case drive-bay counts are NOT read from the combined "3.5\" / 2.5\"" row: it
mixes combo and dedicated bays and the page does not say which (pages with
separate 3.5" and 2.5" rows only are read).

Round 3 (Oct 2026): every field the page prints. The spec table is a run of
headed blocks ("Fan Support", "Radiator Support", "Fan", "Pump", "Radiator")
that repeat the same labels (Front / Top / Rear, Dimensions, Connector), so
fields are read per block; a rowspan label ("Connector", "UPC#") covers the
list rows under it, so all of a page's UPCs join now, not only the first.
"""

from __future__ import annotations

import re

from .common import (efficiency_tier, fan_mounts, front_io_ports, html_rows,
                     html_section_rows, mb_form_factor_list, norm_name,
                     psu_connector_counts, psu_length, radiator_sizes, spec_range, typed)

BRAND = "Antec"
BASE_URL = "https://www.antec.com"
SITEMAP = BASE_URL + "/sitemap.xml"
CATEGORIES = ("case", "psu", "case_fan", "cooler_air", "aio", "cooling_other")

_URL_RE = re.compile(r"<loc>(https://www\.antec\.com/product/([^/<]+)/([^/<]+))</loc>")


_LISTINGS = ("case-", "power-series", "power-80plus", "casefan", "cooling-", "cooling-all", "air",
             "discontinued", "case-vx-vcx-smart", "psu-extension")
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
    # "ne850-platinum" next to "ne850-platinum-atx3-1": the retail code
    # NE850PLATINUM names both revisions, so the bare slug is no part number
    # (the page still joins on its own UPCs). Colour siblings ("-white")
    # share the specs and keep the key.
    slugs = [entry["slug"].lower() for entry in entries.values()]
    for entry in entries.values():
        slug = entry["slug"].lower()
        if any(other.startswith(slug + "-") and re.match(r"atx-?3", other[len(slug) + 1:])
               for other in slugs):
            entry["key_is_id"] = False
    return list(entries.values())


_GROUP_SCOPE = {"case", "cooling", "power", "psu"}


def in_scope(entry: dict) -> bool:
    return entry.get("group") in _GROUP_SCOPE


def classify(entry: dict, page: str) -> str | None:
    """Catalog category of a page (the join also requires the product to share it)."""
    group = entry.get("group")
    if group == "case":
        return "case"
    if group in ("power", "psu"):
        return "psu"
    if group == "cooling":
        text = page or ""
        if re.search(r"Water Pressure|Flow rate|Pump", text):
            return "aio"
        if re.search(r"Heat ?pipe|Heatsink|Socket Support|TDP", text, re.I):
            return "cooler_air"
        rows = _rows(text)
        if re.match(r"\s*\d{2,3}\s*[*x]\s*\d{2,3}\s*[*x]\s*\d{2}", rows.get("dimensions", "")):
            return "case_fan"
    return None


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


def _sections(page: str) -> dict[tuple[str, str], list[str]]:
    """(block, label) -> every value, in page order. Block names are reduced
    to their kind ("Fan Support" -> "fan", "Radiator Support" -> "radiator")
    so the coolers' "Fan" block and the cases' "Fan Support" block read alike;
    rows above the first heading have block ""."""
    out: dict[tuple[str, str], list[str]] = {}
    for section, label, value in html_section_rows(page):
        kind = next((k for k in ("radiator", "fan", "pump", "head", "tube") if k in section), "")
        key = (kind, re.sub(r"\s+", " ", label).strip().lower())
        out.setdefault(key, []).append(value)
    return out


def _get(sections, *keys) -> str | None:
    """First value of the first (block, label) key present."""
    for key in keys:
        if sections.get(key):
            return sections[key][0]
    return None


def parse(page: str, category: str) -> dict:
    rows = _rows(page)
    sections = _sections(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    # The UPC rows list every variant ("0-761345-40033-6 P12 PWM ARGB_3PK /
    # 0-761345-40043-5 ..." or "[NE650C V2 AU][0-761345-11195-9]", one per row
    # under a rowspan label): read each barcode on its own, never the digits
    # of the whole cell.
    upc_text = " ".join(value for (_, label), values in sections.items()
                        if label in ("upc#", "upc", "#upc") for value in values)
    # Antec prints UPC-A as 0-761345-11647-3 (1-6-5-1 digits).
    out["_ids"] = re.findall(r"\b\d-\d{5,6}-\d{5}-\d\b|\b\d{12,13}\b", upc_text)
    if category == "case":
        _case(rows, sections, put)
    elif category == "case_fan":
        _fan(sections, put)
    elif category == "aio":
        _aio(sections, put)
    elif category == "cooler_air":
        _cooler_air(sections, put)
    elif category == "psu":
        _psu(rows, sections, put)
    return {k: v for k, v in out.items() if v is not None}


def _mm(raw) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mm", str(raw or ""), re.I)
    return int(round(float(match.group(1)))) if match else None


def _case(rows, sections, put) -> None:
    put("max_gpu_length_mm", _mm(rows.get("max gpu length")))
    put("max_cooler_height_mm", _mm(rows.get("max cpu cooler height") or rows.get("max cpu height")))
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
    ports = front_io_ports(rows.get("front access & controls") or rows.get("top access & controls"))
    if ports:
        put("front_usb", ports)
    # "Fan Support" block: one row per position. The PSU shroud is the bottom
    # mount on cases that print no separate "Bottom" row.
    for field, labels in (("fan_front", ("front",)), ("fan_top", ("top",)), ("fan_rear", ("rear",)),
                          ("fan_side", ("side", "right hand side")),
                          ("fan_bottom", ("bottom", "power supply shroud", "power supply"))):
        raw = _get(sections, *(("fan", label) for label in labels))
        if raw:
            put(field, fan_mounts(raw))
    sizes: set[int] = set()
    for (kind, _label), values in sections.items():
        if kind == "radiator":
            for value in values:
                sizes |= radiator_sizes(value)
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
    if not any(re.search(r"3\.5.*2\.5", label) for _, label in sections):
        for field, label in (("drive_bays_35", '3.5"'), ("drive_bays_25", '2.5"')):
            count = re.fullmatch(r"\s*(\d{1,2})\s*", rows.get(label, ""))
            if count:
                put(field, int(count.group(1)))
    fans = rows.get("included fan(s)") or rows.get("pre-installed fans") or ""
    if re.search(r"\bA-?RGB\b", fans, re.I):
        put("lighting", "ARGB")
    elif re.search(r"\bRGB\b", fans, re.I):
        put("lighting", "RGB")


def _psu(rows, sections, put) -> None:
    watts = re.search(r"(\d{3,4})\s*W", rows.get("output capacity", ""), re.I)
    if watts:
        put("wattage_w", int(watts.group(1)))
    put("efficiency", efficiency_tier(rows.get("certifications")))
    modular = rows.get("modular", "").strip().lower()
    if modular.startswith("full"):
        put("modular", "full")
    elif modular.startswith("semi"):
        put("modular", "semi")
    elif modular.startswith("non"):
        put("modular", "no")
    version = re.search(r"ATX\s*12V\s*(?:v|ver\.?\s*)?([23]\.\d{1,2})", rows.get("type", ""), re.I)
    if version:
        put("atx_version", f"ATX {version.group(1)}")
    fan = re.search(r"(\d{2,3})\s*mm", rows.get("fan", ""), re.I)
    if fan:
        put("fan_size_mm", int(fan.group(1)))
    put("length_mm", psu_length(rows.get("dimension") or rows.get("dimension (w x l x h)")))
    put("model", rows.get("model") or rows.get("product name"))
    put("color", rows.get("color"))
    # "Connector" is a rowspan label over the full cable list (24-pin, EPS,
    # PCI-E, SATA, Molex, FDD), one connector kind per row.
    for field, count in psu_connector_counts(sections.get(("", "connector"), [])).items():
        put(field, count)


def _fan_size(raw) -> int | None:
    size = re.match(r"\s*(\d{2,3})\s*[*x]\s*\1\b", str(raw or ""), re.I)
    return int(size.group(1)) if size else None


def _speed(put, low_field: str, high_field: str, raw) -> None:
    span = spec_range(raw)
    if span:
        if span[0] != span[1] and span[0] >= 100:   # a PWM floor "0 - 2000" is not an rpm
            put(low_field, int(span[0]))
        put(high_field, int(span[1]))


def _top(raw) -> float | None:
    span = spec_range(raw)
    return span[1] if span else None


def _fan(sections, put) -> None:
    def fan(label):
        return _get(sections, ("fan", label), ("", label))

    put("size_mm", _fan_size(fan("dimensions")))
    _speed(put, "rpm_min", "rpm_max", fan("fan speed"))
    put("airflow_cfm", _top(fan("airflow")))
    put("static_pressure_mmh2o", _top(fan("air pressure")))
    put("noise_db", _top(fan("fan noise level")))
    connector = re.search(r"(\d)-?pin", fan("connector") or "", re.I)
    if connector:
        put("connector", f"{connector.group(1)}-pin")
    kind = fan("fan type") or ""
    if re.search(r"\bPWM\b", kind):
        put("pwm", True)
    elif re.search(r"\bDC\b", kind):
        put("pwm", False)
    # "C120 ARGB White_3PK" - only when the page sells that one pack size.
    pack = re.fullmatch(r"[^/]*_(\d)PKS?", (fan("model name") or "").strip(), re.I)
    if pack:
        put("quantity", int(pack.group(1)))


def _aio_connectors(sections) -> list[str]:
    """'Fan: 4-Pin | ARGB: 3-Pin' / 'Pump: 3-pin | LED: 3-pin' / 'SATA power'
    -> the catalog's connector tokens. Proprietary plugs ("PH2.0 7pin") are
    not translated."""
    out: list[str] = []
    for kind in ("fan", "pump", "head", ""):
        for value in sections.get((kind, "connector"), []):
            for part in re.split(r"[|,;/]", value):
                pins = re.search(r"(\d)\s*-?\s*pin", part, re.I)
                if re.search(r"sata", part, re.I):
                    token = "SATA"
                elif re.search(r"usb", part, re.I):
                    token = "USB 2.0" if re.search(r"2\.0", part) else None
                elif not pins or re.search(r"PH\d|\b[5-9]\s*-?\s*pin", part, re.I):
                    token = None
                elif re.search(r"argb|led|rgb", part, re.I):
                    token = f"{pins.group(1)}-pin ARGB"
                elif pins.group(1) == "4" or re.search(r"pwm", part, re.I):
                    token = f"{pins.group(1)}-pin PWM"
                else:
                    token = f"{pins.group(1)}-pin"
                if token and token not in out:
                    out.append(token)
    return out


def _aio(sections, put) -> None:
    def fan(label):
        return _get(sections, ("fan", label), ("", label))

    _speed(put, "fan_rpm_min", "fan_rpm_max", fan("fan speed") or fan("speed"))
    put("airflow_cfm", _top(fan("airflow")))
    put("noise_db", _top(fan("fan noise level") or fan("noise")))
    radiator = re.match(r"\s*(\d{2,3})\s*[x*]\s*\d{2,3}\s*[x*]\s*(\d{2})\b",
                        _get(sections, ("radiator", "dimensions")) or "")
    if radiator:
        put("radiator_length_mm", int(radiator.group(1)))
        put("radiator_thickness_mm", int(radiator.group(2)))
    connectors = _aio_connectors(sections)
    if connectors:
        put("connectors", connectors)


def _cooler_air(sections, put) -> None:
    def fan(label):
        return _get(sections, ("fan", label), ("", label))

    _speed(put, "fan_rpm_min", "fan_rpm_max", fan("speed"))
    put("airflow_cfm", _top(fan("airflow")))
    put("noise_db", _top(fan("noise") or fan("noise level")))
    put("fan_size_mm", _fan_size(fan("dimensions")))
    tdp = re.search(r"(\d{2,3})\s*W\b", fan("tdp") or fan("tdp number") or "", re.I)
    if tdp:
        put("tdp_w", int(tdp.group(1)))
    size = fan("product dimension") or fan("product dimensions") or ""
    height = re.search(r"\d+\s*x\s*\d+\s*x\s*(\d{2,3})\s*mm\s*\(\s*(?:DWH|D\s*x\s*W\s*x\s*H)", size, re.I)
    if height:
        put("height_mm", int(height.group(1)))
    kind = fan("type") or ""
    if re.search(r"\bA-?RGB\b", kind, re.I):
        put("lighting", "ARGB")
    elif re.search(r"\bRGB\b", kind, re.I):
        put("lighting", "RGB")
