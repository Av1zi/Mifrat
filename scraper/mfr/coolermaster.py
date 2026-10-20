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

from .common import (fan_mounts, front_io_ports, mb_form_factor_list, norm_name, number_range,
                     radiator_sizes, spec_range, typed)

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


_CODE_RE = re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){2,}\b")
_SIZE_PREFIX = re.compile(r"^\s*(?:\((\d{3})\)|(\d{3})\s*:)\s*(.*)$", re.S)


def _codes(text) -> list[str]:
    """'Black: NR100-KNNN-S00, White: NR100-WNNN-S00' -> both part numbers."""
    return _CODE_RE.findall(str(text or "").replace("​", ""))


def _by_size(pairs) -> tuple[list, dict[int, list], dict[int, list[str]]]:
    """Split a series page ("360: 394 x 119.6 x 27.2 mm", "(240) 350 mm",
    "360 Black: ELW-D36M-A21DA-R1") into the rows every size shares, the rows
    of each radiator size, and each size's part numbers."""
    common: list = []
    sized: dict[int, list] = {}
    codes: dict[int, list[str]] = {}
    for key, value in pairs:
        if key in ("product number", "model number"):
            # "360 Black: ELW-D36M-A21DA-R1, 240 LCD White: MLX-D24M-A25SZ-LW",
            # "(240 LCD Black) MLX-D24M-A25SZ-L1" (comma- or line-separated).
            for size, code in re.findall(r"\b(\d{3})\b[^:,|()]{0,30}[:)]\s*([A-Z0-9][A-Z0-9-]+)",
                                         value.replace("​", "")):
                codes.setdefault(int(size), []).extend(_codes(code))
            continue
        parts = [p for p in re.split(r"\s+\|\s+", value) if p.strip()]
        prefixed = [_SIZE_PREFIX.match(p) for p in parts]
        if parts and all(prefixed):
            for match in prefixed:
                size = int(match.group(1) or match.group(2))
                sized.setdefault(size, []).append((key, match.group(3).strip()))
        else:
            common.append((key, value))
    return common, sized, codes


def parse(page: str, category: str) -> dict:
    pairs = _pairs(page)
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    ids = []
    for label in ("product number", "model number", "upc code", "ean code"):
        for value in _all(pairs, label):
            # Hyphenated part numbers, a bare one-token number ("RC340"), the
            # UPC / EAN as printed.
            single = re.fullmatch(r"\s*([A-Z0-9][A-Z0-9-]{3,})\s*", value)
            ids += _codes(value) or ([single.group(1)] if single else [])
    out["_ids"] = ids
    put("color", _first(pairs, "exterior color"))
    if category == "aio":
        common, sized, codes = _by_size(pairs)
        if len(set(sized) | set(codes)) > 1:
            # A series page (Elite Liquid 240 / 360 side by side): one block per
            # radiator size, joined only on that size's printed part numbers.
            blocks = []
            for size in sorted(set(sized) | set(codes)):
                block: dict = {}

                def put_block(field, raw, block=block):
                    value = typed("aio", field, raw) if raw is not None else None
                    if value is not None:
                        block[field] = value

                rows = common + sized.get(size, [])
                rows = [(k, v) for k, v in rows if k != "radiator size"]
                _cooler(rows, put_block, "aio")
                put_block("radiator_size_mm", size)
                put_block("color", _first(pairs, "exterior color"))
                block["_ids"] = codes.get(size, [])
                block["_category"] = "aio" if block["_ids"] else None
                blocks.append(block)
            return {"_blocks": blocks}
        _cooler(pairs, put, category)
    elif category == "cooler_air":
        _cooler(pairs, put, category)
    elif category == "case":
        _case(pairs, put)
    return {k: v for k, v in out.items() if v is not None}


def _radiator(pairs) -> int | None:
    size = re.search(r"\d{3}", _first(pairs, "radiator size") or "")
    return int(size.group(0)) if size else None


def _cfm(raw) -> float | None:
    """'142.8 m³/h(84.2 CFM) (Max)' -> 84.2: the CFM figure, never the m³/h one."""
    text = str(raw or "")
    cfm = re.search(r"(\d+(?:\.\d+)?)\s*CFM", text, re.I)
    if cfm:
        return float(cfm.group(1))
    if re.search(r"m³|m3", text):
        return None
    span = spec_range(text)
    return span[1] if span else None


def _connectors(pairs) -> list[str]:
    """'3-Pin ARGB + 4-Pin PWM' / '7-Pin PWM + ARGB' / '4-Pin (PWM)' -> the
    catalog's connector tokens; combined proprietary plugs are not split."""
    out: list[str] = []
    for label in ("pump connector", "fan connector", "fan power connector"):
        for value in _all(pairs, label):
            for part in re.split(r"\+|,|/", value):
                pins = re.search(r"(\d)\s*-?\s*pin", part, re.I)
                if not pins or pins.group(1) not in "34":
                    continue
                if re.search(r"argb|rgb|led", part, re.I):
                    token = f"{pins.group(1)}-pin ARGB"
                elif pins.group(1) == "4" or re.search(r"pwm", part, re.I):
                    token = f"{pins.group(1)}-pin PWM"
                else:
                    token = f"{pins.group(1)}-pin"
                if token not in out:
                    out.append(token)
    return out


def _cooler(pairs, put, category) -> None:
    sockets = _sockets(_all(pairs, "cpu socket"))
    if sockets:
        put("sockets", sockets)
    quantity = number_range(_first(pairs, "fan quantity") or _first(pairs, "fan quantity (pcs)"))
    if quantity and category == "aio":
        put("fan_count", int(quantity[1]))
    speed = spec_range(_first(pairs, "fan speed"))
    if speed:
        if speed[0] != speed[1]:      # "0-2050 RPM": the fan stops (semi-passive)
            put("fan_rpm_min", int(speed[0]))
        put("fan_rpm_max", int(speed[1]))
    put("airflow_cfm", _cfm(_first(pairs, "fan airflow") or _first(pairs, "fan air flow (max)")))
    noise = spec_range(_first(pairs, "fan noise level") or _first(pairs, "fan noise level (max)"))
    if noise:
        put("noise_db", noise[1])
    profile = " ".join(v for k, v in pairs if k in ("fan profiles", "fan led type", "fan led",
                                                    "profile", "led lighting"))
    if re.search(r"addressable|argb", profile, re.I):
        put("lighting", "ARGB")
    elif re.search(r"\bnon-led\b|^\s*none\s*$", profile, re.I):
        put("lighting", "No")
    dims = [_dims(v) for v in _all(pairs, "dimensions (l x w x h)") + _all(pairs, "dimensions")]
    fan_dims = _dims(_first(pairs, "fan dimensions (l x w x h)") or _first(pairs, "fan dimensions (l x h x w)"))
    if category == "aio":
        radiator = _radiator(pairs)
        if radiator:
            put("radiator_size_mm", radiator)
        rad = _dims(_first(pairs, "radiator dimensions"))
        if rad:
            put("radiator_length_mm", int(round(rad[0])))
            put("radiator_thickness_mm", int(round(rad[2])))
        if fan_dims and fan_dims[0] < 200:
            put("fan_size_mm", int(round(fan_dims[0])))
        elif dims and dims[0]:
            put("fan_size_mm", int(round(dims[0][0])))
        connectors = _connectors(pairs)
        if connectors:
            put("connectors", connectors)
    else:
        if dims and dims[0]:
            put("height_mm", int(round(dims[0][2])))
        if fan_dims:
            put("fan_size_mm", int(round(fan_dims[0])))
        elif len(dims) > 1 and dims[1]:
            put("fan_size_mm", int(round(dims[1][0])))


def _lead_int(raw) -> int | None:
    """'2 (exposed)' / '1 (Max. 2)' / '3' -> the count the case ships with."""
    match = re.match(r"\s*(\d{1,2})\b(?!\s*[+x/])", str(raw or ""))
    return int(match.group(1)) if match else None


def _case(pairs, put) -> None:
    put("type", _first(pairs, "size"))
    forms = mb_form_factor_list(re.sub(r"\*[^,]*", "", _first(pairs, "motherboard support") or ""))
    if forms:
        put("mb_form_factors", forms)
    gpu = _first(pairs, "clearance - gfx")
    if gpu is None:
        length = re.search(r"\bL:\s*(\d{3})\s*mm", _first(pairs, "clearances - graphics card") or "")
        gpu = f"{length.group(1)}mm" if length else None
    put("max_gpu_length_mm", _mm(gpu))
    put("max_cooler_height_mm", _mm(_first(pairs, "clearance - cpu cooler")
                                    or _first(pairs, "clearances - cpu cooler")))
    panel = _first(pairs, "materials - left side panel") or _first(pairs, "materials - side panel") or ""
    if re.search(r"glass|acrylic|window|\bTG\b", panel, re.I):
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
    put("drive_bays_25", _lead_int(_first(pairs, '2.5" drive bays') or _first(pairs, 'drive bays - 2.5" ssd')))
    put("drive_bays_35", _lead_int(_first(pairs, '3.5" drive bays')))
    dims = None
    for value in _all(pairs, "dimensions (l x w x h)"):
        if re.search(r"excl", value, re.I):
            excl = re.search(r"(\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?)\s*mm\s*\(?excl", value)
            dims = _dims(excl.group(1)) if excl else None
        elif dims is None:
            dims = _dims(value)
    if dims:
        put("dimensions_mm", f"W={int(round(dims[1]))} H={int(round(dims[2]))} D={int(round(dims[0]))}mm")
    sizes: set[int] = set()
    for key, value in pairs:
        if key.startswith("radiator support"):
            sizes |= radiator_sizes(value)
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
    for position in ("front", "top", "rear", "side", "bottom"):
        value = _first(pairs, f"fan support - {position}")
        if value:
            put(f"fan_{position}", fan_mounts(value))
    volume = re.search(r"(\d+(?:\.\d+)?)\s*L\b", _first(pairs, "volume") or "")
    if volume:
        put("volume_l", float(volume.group(1)))
    weight = re.search(r"(\d+(?:\.\d+)?)\s*kg", _first(pairs, "weight") or "", re.I)
    if weight:
        put("weight_kg", float(weight.group(1)))
    fans = " ".join(v for k, v in pairs if k.startswith("pre-installed fans"))
    if re.search(r"\bA-?RGB\b|addressable", fans, re.I):
        put("lighting", "ARGB")
    elif re.search(r"\bRGB\b", fans, re.I):
        put("lighting", "RGB")
