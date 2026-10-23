"""
mfr/fractal.py - fractal-design.com product pages.

Policy: robots.txt allows `*` everywhere except /studio/ and /api/, and
disallows named AI crawlers (ClaudeBot, anthropic-ai, GPTBot, CCBot,
Google-Extended ...) from the whole site. The owner decided (2026-10-22) to
read the product pages anyway; client.ROBOTS_OVERRIDES records that decision
for /products/ only. /api/ is never touched, and a 403 / 429 / challenge page
still stops the run (no retries).

Delivery: the site is a Next.js app; every variant page embeds its PIM record
(`"_type":"pimProductVariant"`) in the server-rendered RSC flight payload
(`self.__next_f.push([1,"..."])`): typed attributes such as
`cases_gpuMaxLength: 355`, `cases_radiatorFront: ["120","240",...]`,
`waterCooling_fanRotationalSpeed: {"min":500,"max":2000}`, plus the article
number (`sku` FD-C-NOR1C-01), EAN and UPC. No /api/ request is needed.

Index: the three category listings (/products/cases/, /water-cooling/,
/fans/) embed every current product with its variants' `sku` and `slug`, so
`sku -> /products/<category>/<line>/<product>/<variant>/` is known before any
product page is fetched, and catalog products join EXACTLY on the article
number they carry. Only matched pages are fetched. Legacy cases keep their
old article number (FD-CA-NODE-304-BL), which Israeli retailers list without
the "FD-CA-" brand prefix (NODE-304-BL): that stripped form is the same
identifier, so it is a second exact key. Discontinued models (Torrent
Compact / Nano, Celsius+, Define S2 Vision, ERA ITX, Prisma fans) are not in
the listings and stay unmatched; their URLs are not guessed.
"""

from __future__ import annotations

import json
import re

from .common import (clean, fan_mounts, front_io_ports, mb_form_factor_list, norm_mpn,
                     radiator_sizes, typed)

BRAND = "Fractal Design"
BASE_URL = "https://www.fractal-design.com"
CATEGORIES = ("case", "aio", "cooling_other", "case_fan")
LISTINGS = ("cases", "water-cooling", "fans")

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_PRODUCT_RE = re.compile(r'\{"_id":"[^"]+","categorySlug":')
_PIM_RE = re.compile(r'\{"_id":"([^"]+)","_type":"pimProductVariant"')
_WEB_RE = re.compile(r'"_type":"webProductVariant"')
_DECODER = json.JSONDecoder()


def _payload(page: str) -> str:
    """The concatenated RSC flight text of a Next.js page."""
    parts = []
    for chunk in _PUSH_RE.findall(page or ""):
        try:
            parts.append(json.loads('"' + chunk + '"'))
        except ValueError:
            continue
    return "".join(parts)


def _objects(text: str, pattern: re.Pattern) -> list[dict]:
    out = []
    for match in pattern.finditer(text):
        try:
            obj, _ = _DECODER.raw_decode(text, match.start())
        except ValueError:
            continue
        out.append(obj)
    return out


def _legacy_key(sku: str) -> str:
    """FD-CA-NODE-304-BL -> NODE-304-BL (the form retailers list), else ""."""
    match = re.fullmatch(r"FD-CA-([A-Z0-9]+(?:-[A-Z0-9]+)+)", sku.strip().upper())
    return match.group(1) if match else ""


def index(client) -> list[dict]:
    entries: dict[str, dict] = {}
    for listing in LISTINGS:
        text = _payload(client.get(f"{BASE_URL}/products/{listing}/") or "")
        for product in _objects(text, _PRODUCT_RE):
            category = product.get("categorySlug")
            line, slug = product.get("lineSlug"), product.get("slug")
            if category not in LISTINGS or not line or not slug:
                continue
            for variant in product.get("variants") or []:
                sku, vslug = str(variant.get("sku") or "").strip(), variant.get("slug")
                if not sku or not vslug:
                    continue
                url = f"{BASE_URL}/products/{category}/{line}/{slug}/{vslug}/"
                for key in (norm_mpn(sku), norm_mpn(_legacy_key(sku))):
                    if key:
                        entries.setdefault(key, {"url": url, "key": key, "sku": sku,
                                                 "listing": category})
    return list(entries.values())


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    for value in (product.get("specs") or {}).get("part_numbers") or []:
        entry = entries_by_key.get(norm_mpn(value))
        if entry is not None:
            return entry
    return None


def _records(page: str) -> tuple[dict, dict]:
    """(web variant, PIM record) of the page's own product, or ({}, {}).

    A page also embeds the PIM records of sibling and "compatible" products,
    so the record is chosen by id: the webProductVariant whose slug is the
    canonical URL's last segment names its record by `pimDocumentId`."""
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page or "")
    own_slug = canonical.group(1).rstrip("/").rsplit("/", 1)[-1] if canonical else None
    text = _payload(page)
    pims = {obj.get("_id"): obj for obj in _objects(text, _PIM_RE)}
    for match in _WEB_RE.finditer(text):
        start = text.rfind('{"_id":"', 0, match.start())
        try:
            web, _ = _DECODER.raw_decode(text, start)
        except ValueError:
            continue
        if web.get("_type") != "webProductVariant" or web.get("slug") != own_slug:
            continue
        pim = pims.get(web.get("pimDocumentId"))
        return (web, pim) if pim else ({}, {})
    return {}, {}


def _variant(page: str) -> dict:
    return _records(page)[1]


def _value(raw):
    """A PIM scalar, or None for the payload's empty markers."""
    if raw in (None, "", "$undefined", [], {}):
        return None
    return raw


def _num(raw) -> float | None:
    """12 / "12" / "<10–33.2" / {"min": 13, "max": 56} -> the (maximum) number."""
    raw = _value(raw)
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        return _num(raw.get("max")) if _value(raw.get("max")) is not None else _num(raw.get("min"))
    numbers = re.findall(r"\d+(?:\.\d+)?", str(raw).replace(",", ""))
    return max(float(n) for n in numbers) if numbers else None


def _min(raw) -> float | None:
    raw = _value(raw)
    if isinstance(raw, dict):
        return _num(raw.get("min"))
    return None


def _int(raw) -> int | None:
    value = _num(raw)
    return int(round(value)) if value is not None else None


def _notes(attrs: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for note in attrs.get("notes") or []:
        if isinstance(note, dict) and note.get("attribute") and note.get("note"):
            out[note["attribute"]] = clean(str(note["note"]))
    return out


def _color(attrs: dict) -> str | None:
    primary = _value(attrs.get("color"))
    if not isinstance(primary, str):
        return None
    secondary = _value(attrs.get("secondaryColor"))
    text = primary.title()
    if isinstance(secondary, str) and secondary.lower() != primary.lower():
        text += " / " + secondary.title()
    return text


def _says_argb(attrs: dict) -> bool:
    blob = json.dumps({k: v for k, v in attrs.items() if k not in ("productImages", "posterImages")},
                      ensure_ascii=False)
    return bool(re.search(r"\bARGB\b|\baddressable\b|\b5\s*V\b[^\"]{0,20}\b(?:RGB|header)", blob, re.I))


def _lighting(attrs: dict, flag) -> str | None:
    """`rgb: false` -> "No"; `rgb: true` -> "ARGB" only when the record itself
    says addressable / ARGB (Fractal labels its ARGB parts "RGB", so a bare
    "RGB" would downgrade a retailer's correct ARGB); otherwise unknown."""
    if flag is False:
        return "No"
    if flag is True and _says_argb(attrs):
        return "ARGB"
    return None


def _sockets(attrs: dict, prefix: str) -> list[str]:
    out: list[str] = []
    intel = str(_value(attrs.get(prefix + "supportedSocketsIntel")) or "")
    for number in re.findall(r"(?<!\d)(\d{3,4}(?:-3|-v3)?)(?![\d.])", intel):
        token = "LGA" + number.replace("-v3", "-3")
        if token not in out:
            out.append(token)
    amd = str(_value(attrs.get(prefix + "supportedSocketsAmd")) or "")
    for token in re.findall(r"\b(?:AM\d\+?|FM\d\+?|TR\d|sTRX\d|SP\d)\b", amd, re.I):
        token = token.upper().replace("STRX", "sTRX")
        if token not in out:
            out.append(token)
    return out


def parse(page: str, category: str) -> dict:
    web, attrs = _records(page)
    if not attrs:
        return {}
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    model = ((web.get("parentProduct") or {}) if isinstance(web.get("parentProduct"), dict) else {}).get("title")
    if category == "case":
        _case(attrs, put)
        put("model", model)
    elif category in ("aio", "cooling_other"):
        _cooler(attrs, put, category)
        if category == "aio":
            put("model", model)
    elif category == "case_fan":
        _fan(attrs, put)
        put("model", model)
    put("color", _color(attrs))
    sku = str(attrs.get("sku") or "")
    ids = [sku, attrs.get("ean"), attrs.get("upc"), _legacy_key(sku)]
    return {**out, "_ids": [str(i) for i in ids if _value(i)]}


# -- cases ---------------------------------------------------------------

_FAN_POSITIONS = (("fan_front", "cases_frontFanMounts"), ("fan_top", "cases_topFanMounts"),
                  ("fan_rear", "cases_rearFanMounts"), ("fan_bottom", "cases_bottomFanMounts"),
                  ("fan_side", "cases_sideFanMounts"))
_RADIATORS = ("cases_radiatorFront", "cases_radiatorTop", "cases_radiatorRear",
              "cases_radiatorBottom", "cases_radiatorSide")
_SIDE_PANEL = (("tempered glass", "Windowed"), ("glass", "Windowed"), ("mesh", "Mesh"),
               ("steel", "No Window"), ("alumin", "No Window"))


def _case(attrs: dict, put) -> None:
    notes = _notes(attrs)
    forms = _value(attrs.get("cases_mbCompatibility"))
    if isinstance(forms, list):
        put("mb_form_factors", mb_form_factor_list(", ".join(map(str, forms))) or None)
    put("max_gpu_length_mm", _int(attrs.get("cases_gpuMaxLength")))
    # "145 mm with Fan Bracket (Mesh version only) / 170 mm without": the
    # value is sometimes the with-bracket figure (North) and sometimes the
    # without one (North XL); the maximum is the larger of the two.
    cooler = _int(attrs.get("cases_cpuCoolerMaxHeight"))
    without = re.findall(r"(\d{2,3})\s*mm\s*without\b", notes.get("cases_cpuCoolerMaxHeight", ""), re.I)
    if cooler is not None and without:
        cooler = max([cooler, *map(int, without)])
    put("max_cooler_height_mm", cooler)
    slots = _int(attrs.get("cases_expansionSlots"))
    if slots:
        put("expansion_slots", str(slots))
    _bays(attrs, notes, put)
    ports = []
    for key, name in (("cases_usbTypeA20", "USB 2.0"), ("cases_usbTypeA5gbps", "USB 3.0"),
                      ("cases_usbTypeA10gbps", "USB 3.2"), ("cases_usbTypeC5gbps", "USB Type-C"),
                      ("cases_usbTypeC10gbps", "USB Type-C"), ("cases_usbTypeC20gbps", "USB Type-C")):
        if (_int(attrs.get(key)) or 0) > 0:
            ports.append(name)
    if any((_int(attrs.get(key)) or 0) > 0 for key in
           ("cases_headsetComboJack35mm", "cases_audioJack35mm", "cases_micJack35mm")):
        ports.append("Headset")
    if ports:
        put("front_usb", front_io_ports(", ".join(ports)))
    panel = str(_value(attrs.get("cases_leftSidePanel")) or "").lower()
    put("side_panel", next((label for word, label in _SIDE_PANEL if word in panel), None))
    width, height, depth = (_int(attrs.get(k)) for k in ("width", "height", "length"))
    if width and height and depth:
        put("dimensions_mm", f"W={width} H={height} D={depth}mm")
    weight = _num(attrs.get("netWeight"))
    if weight:
        put("weight_kg", round(weight / 1000, 2))
    put("volume_l", _num(attrs.get("cases_volumeL")))
    for field, key in _FAN_POSITIONS:
        raw = _value(attrs.get(key))
        if raw is None:
            continue
        raw = str(raw).strip()
        put(field, "No" if re.fullmatch(r"0+", raw) else fan_mounts(raw))
    sizes: set[int] = set()
    for key in _RADIATORS:
        for item in _value(attrs.get(key)) or []:
            item = str(item)
            # "2x 120/140 mm" (a fan-row spelling) is a 240 / 280 radiator.
            multi = re.fullmatch(r"\s*(\d)\s*x\s*(\d{3}(?:\s*/\s*\d{3})*)\s*(?:mm)?\s*", item, re.I)
            if multi:
                sizes |= {int(multi.group(1)) * int(n) for n in re.findall(r"\d{3}", multi.group(2))}
            else:
                sizes |= radiator_sizes(item)
    sizes &= {120, 140, 240, 280, 360, 420, 480}
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
    put("lighting", _lighting(attrs, _value(attrs.get("cases_rgb"))))


def _bays(attrs: dict, notes: dict[str, str], put) -> None:
    """3.5" bays = dedicated HDD + combined; 2.5" = dedicated SSD + combined.

    A combined bay note that splits the count ("Combined bay: 2x 3.5\\" or
    4x 2.5\\" (shared)") is read per size. Nothing is written when the record
    names no drive mount at all (null is unknown, not zero)."""
    hdd = _int(attrs.get("cases_dedicatedHddMounts"))
    ssd = _int(attrs.get("cases_dedicatedSsdMounts"))
    combined = _int(attrs.get("cases_combinedDriveMounts"))
    note = notes.get("cases_combinedDriveMounts", "")
    as35 = re.search(r"(\d{1,2})\s*x\s*3\.5", note)
    as25 = re.search(r"(\d{1,2})\s*x\s*2\.5", note)
    c35 = int(as35.group(1)) if as35 else combined
    c25 = int(as25.group(1)) if as25 else combined
    if hdd is not None or combined is not None:
        put("drive_bays_35", (hdd or 0) + (c35 or 0))
    if ssd is not None or combined is not None:
        put("drive_bays_25", (ssd or 0) + (c25 or 0))


# -- coolers / fans --------------------------------------------------------

def _fan_size(models) -> int | None:
    """[{"refDoc": {"title": "Aspect 12"}}] -> 120 (Fractal fan names end in
    the size in cm: Aspect 12 / Momentum 14 / Prisma AL-18)."""
    sizes = set()
    for model in models or []:
        title = str(((model or {}).get("refDoc") or {}).get("title") or "")
        found = re.search(r"\b(?:AL-|GP-|SL-)?(12|14|18|20)\b", title)
        if found:
            sizes.add(int(found.group(1)) * 10)
    return sizes.pop() if len(sizes) == 1 else None


def _cooler(attrs: dict, put, category: str) -> None:
    prefix = "waterCooling_"
    get = lambda key: _value(attrs.get(prefix + key))
    models = get("fanModelsIncluded") or []
    width = _int(get("radiatorWidth"))
    fan_size = _fan_size(models) or (width if width in (120, 140) else None)
    put("fan_size_mm", fan_size)
    sockets = _sockets(attrs, prefix)
    if sockets:
        put("sockets", sockets)
    put("fan_rpm_max", _int(get("fanRotationalSpeed")))
    put("noise_db", _num(get("fanAcousticalNoise")))
    put("lighting", _lighting(attrs, get("rgb")))
    if category == "cooling_other":
        put("water_cooled", True if get("pumpColdPlateMaterial") or get("size") else None)
        return
    put("radiator_size_mm", _int(get("size")))
    put("radiator_length_mm", _int(get("radiatorLength")))
    put("radiator_thickness_mm", _int(get("radiatorHeight")))
    count = sum(int(m.get("amount") or 0) for m in models if isinstance(m, dict))
    if count:
        put("fan_count", count)
    low = _min(get("fanRotationalSpeed"))
    if low and low >= 100:
        put("fan_rpm_min", int(low))
    put("airflow_cfm", _num(get("maxAirflowCfm")))
    connectors = []
    if re.search(r"\bPWM\b", str(get("fanControl") or ""), re.I):
        connectors.append("4-pin PWM")
    if re.search(r"\b5\s*V\s*ARGB\b|\bARGB cable\b",
                 str(_value(attrs.get("bomPackageContent")) or ""), re.I):
        connectors.append("3-pin ARGB")
    if connectors:
        put("connectors", connectors)


def _fan(attrs: dict, put) -> None:
    get = lambda key: _value(attrs.get("fans_" + key))
    put("size_mm", _int(get("size")))
    speed = get("rotationalSpeed")
    low = _min(speed)
    if low and low >= 100:
        put("rpm_min", int(low))
    put("rpm_max", _int(speed))
    put("airflow_cfm", _num(get("airflowCfm")))
    put("noise_db", _num(get("noiseLevel")))
    put("static_pressure_mmh2o", _num(get("staticPressure")))
    pwm = get("pwm")
    if isinstance(pwm, bool):
        put("pwm", pwm)
    pins = re.search(r"(\d)\s*-?\s*pin", str(get("connector") or ""), re.I)
    if pins:
        put("connector", f"{pins.group(1)}-pin")
    led = _lighting(attrs, get("rgb"))
    put("led", led)
