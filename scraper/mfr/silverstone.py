"""
mfr/silverstone.py - silverstonetek.com product pages (draft).
"""

from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

from .common import (efficiency_tier, fan_mounts, front_io_ports, mb_form_factor_list,
                     psu_connector_counts, radiator_sizes, spec_range, typed)

BRAND = "SilverStone"
BASE_URL = "https://www.silverstonetek.com"
SITEMAP = BASE_URL + "/sitemap.xml"
CATEGORIES = ("case", "psu", "case_fan", "cooler_air", "aio", "cooling_other")

# /en/product/info/<group>/<slug>/ - the English block of the sitemap.
_LOC_RE = re.compile(r"<loc>(https://www\.silverstonetek\.com/en/product/info/"
                     r"([A-Za-z-]+)/([^/<]+)/)</loc>")
_GROUPS = {"computer-chassis", "server-nas", "power-supplies", "coolers", "fans"}
# SilverStone cable / adapter part codes (PP05, PP06BE-..., PP12-EPS) share the
# power-supplies group; they are no PSU, so their pages are not fetched.
_CABLE_SLUG = re.compile(r"^PP\d", re.I)


def index(client) -> list[dict]:
    """Every English product page of the in-scope groups, from the sitemap.

    The sitemap is ~10 MB (ten languages interleaved, English first); the
    client reads 8 MB, which holds the whole English block (1,248 product
    pages, checked 2026-10-22) - only later languages are cut off."""
    page = client.get(SITEMAP) or ""
    entries: dict[str, dict] = {}
    for url, group, slug in _LOC_RE.findall(page):
        entries.setdefault(url, {"url": url, "group": group, "slug": slug, "key": ""})
    return list(entries.values())


def in_scope(entry: dict) -> bool:
    return entry.get("group") in _GROUPS and not _CABLE_SLUG.match(entry.get("slug", ""))


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    """No name / slug join: slugs are marketing names (FARA_313, SUGO14,
    HELA2050Platinum). Every in-scope page is fetched and joins at merge time
    on the SST- codes it prints (`_ids`)."""
    return None


class _SpecParser(HTMLParser):
    """The "Product Specifications" block: `div.item > div.title + div.cont`.

    A cont either holds text (lines split on <br>/<li>) or a `sub-spec-on`
    list of `div.sub-title` + `div.sub-cont` pairs (Front / Rear, Internal /
    External). Each item becomes {"label", "lines", "subs": [(sub, lines)]}.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._depth = 0
        self._spec_depth = 0             # depth of the open spec-on-list div
        self._open: list[tuple[str, int]] = []   # (role, depth) of capture divs
        self._buf: list[str] = []
        self._skip = 0
        self._item: dict | None = None
        self._sub: str | None = None
        self._done = False

    def _role(self) -> str | None:
        return self._open[-1][0] if self._open else None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag in ("br", "li", "tr", "p") and self._open:
            self._buf.append("\n")
        if tag in ("td", "th") and self._open:
            self._buf.append(" ; ")
        if tag != "div":
            return
        self._depth += 1
        classes = (dict(attrs).get("class") or "").split()
        if "spec-on-list" in classes and not self._spec_depth and not self._done:
            self._spec_depth = self._depth
            return
        if not self._spec_depth:
            return
        for role in ("title", "cont", "sub-title", "sub-cont"):
            if role in classes:
                if role == "sub-title" or role == "sub-cont":
                    self._flush()
                self._open.append((role, self._depth))
                self._buf = []
                break

    def _lines(self) -> list[str]:
        text = "".join(self._buf)
        return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")
                if re.sub(r"\s+", " ", line).strip()]

    def _flush(self) -> None:
        """Text collected in a cont before its sub-spec list starts."""
        if self._role() == "cont" and self._item is not None:
            self._item["lines"] += self._lines()
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag != "div":
            return
        if self._open and self._open[-1][1] == self._depth:
            role, _ = self._open.pop()
            lines = self._lines()
            if role == "title":
                self._item = {"label": " ".join(lines), "lines": [], "subs": []}
                self.items.append(self._item)
            elif role == "cont" and self._item is not None:
                self._item["lines"] += lines
            elif role == "sub-title":
                self._sub = " ".join(lines)
            elif role == "sub-cont" and self._item is not None:
                self._item["subs"].append((self._sub or "", lines))
                self._sub = None
            self._buf = []
        if self._spec_depth and self._depth == self._spec_depth:
            self._spec_depth, self._done = 0, True     # one spec block per page
        self._depth -= 1

    def handle_data(self, data):
        if self._open and not self._skip:
            self._buf.append(data)


def spec_items(page: str) -> list[dict]:
    parser = _SpecParser()
    parser.feed(page or "")
    return parser.items


# -- page pieces --------------------------------------------------------------

def _text(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html_lib.unescape(fragment)).strip()


def _intro(page: str) -> dict:
    """The product header: name ("Triton 850Rz"), headline ("Cybenetics Gold
    850W ATX 3.1 & PCIe 5 Fully Modular ATX Power Supply"), the feature
    bullets under it and the SST- codes of the VERSION swatches."""
    page = page or ""
    start = page.find('class="prointro-info"')
    block = page[start:start + 20000] if start >= 0 else ""
    name = re.search(r'class="main-txt">(.*?)</div>', block, re.S)
    head = re.search(r'class="sub-txt">(.*?)</div>', block, re.S)
    bullets = re.search(r'class="editor">\s*<ul>(.*?)</ul>', block, re.S)
    return {
        "name": _text(name.group(1)) if name else "",
        "headline": _text(head.group(1)) if head else "",
        "features": [_text(li) for li in re.findall(r"<li>(.*?)</li>", bullets.group(1), re.S)]
        if bullets else [],
        "versions": [_code(t) for t in re.findall(r'<label for="buy_kind[^"]*"[^>]*title="([^"]+)"', block)
                     if _code(t)],
    }


_CODE_RE = re.compile(r"SST-\s*([A-Z0-9][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)(\s+V\d\b)?")


def _code(text: str) -> str:
    """'SST- FM620B-ARGB' -> 'SST-FM620B-ARGB'; 'SST-GM1000-2UG V2' ->
    'SST-GM1000-2UG-V2' (the retail spelling of the revision)."""
    match = _CODE_RE.search(str(text or ""))
    if not match:
        return ""
    code = "SST-" + match.group(1).upper()
    if match.group(2):
        code += "-" + match.group(2).strip().upper()
    return code


def _variants(items: dict, intro: dict) -> list[tuple[str, str]]:
    """(code, note) per model the page sells: 'SST-SG13B-C (black, mesh front
    panel, Type-C port)' -> ('SST-SG13B-C', 'black, mesh front panel, Type-C
    port'). Lines without a code ('Type-C version') are group headings."""
    item = items.get("model no.") or items.get("product no.") or {}
    out: list[tuple[str, str]] = []
    for line in item.get("lines", []):
        for match in re.finditer(r"SST-\s*[A-Za-z0-9][A-Za-z0-9-]*(?:\s+V\d\b)?\s*(?:[(（]([^)）]*)[)）])?",
                                 line):
            code = _code(match.group(0))
            if code and code not in [c for c, _ in out]:
                out.append((code, (match.group(1) or "").strip()))
    for code in intro.get("versions", []):
        if code not in [c for c, _ in out]:
            out.append((code, ""))
    return out


def _items(page: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in spec_items(page):
        out.setdefault(re.sub(r"\s+", " ", item["label"]).strip().lower(), item)
    return out


def _lines(items: dict, *labels: str) -> list[str]:
    for label in labels:
        item = items.get(label)
        if item:
            return item["lines"] + [line for _, lines in item["subs"] for line in lines]
    return []


def _subs(items: dict, *labels: str) -> list[tuple[str, list[str]]]:
    for label in labels:
        item = items.get(label)
        if item:
            return item["subs"]
    return []


# -- category -----------------------------------------------------------------

_SOCKET_RE = re.compile(r"\b(?:LGA|AM\d|SP\d|sTR\d|sWRX\d|TR4|FM\d)", re.I)


def classify(entry: dict, page: str) -> str | None:
    items = _items(page)
    group = entry.get("group")
    if not _variants(items, {}):
        return None                      # no SST- code: nothing joins
    if group in ("computer-chassis", "server-nas"):
        return "case" if "motherboard" in items else None
    if group == "power-supplies":
        return "psu" if "max. dc output" in items else None
    if group == "fans":
        if "speed" in items and "airflow" in items and "dimension" in items:
            return "case_fan"
        return None
    if group == "coolers":
        if "radiator" in items and "pump" in items:
            return "aio"
        application = " ".join(_lines(items, "application"))
        if "fan" in items and "dimension" in items and _SOCKET_RE.search(application):
            return "cooler_air"
    return None


# -- parse --------------------------------------------------------------------

def parse(page: str, category: str) -> dict:
    """One spec dict per page, or one block per variant when the page sells
    several SST- codes (colour / Type-C versions differ in colour and front
    I/O, everything else is shared)."""
    items = _items(page)
    intro = _intro(page)
    variants = _variants(items, intro)
    shared: dict = {}

    def put(field: str, raw, out: dict = shared) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    reader = {"case": _case, "psu": _psu, "case_fan": _fan, "cooler_air": _cooler_air,
              "aio": _aio}.get(category)
    if reader is None or not variants:
        return {}
    reader(items, intro, put)
    per_variant = _per_variant(category, items, intro, variants)
    if len(variants) == 1:
        code, _ = variants[0]
        out = dict(shared)
        for field, raw in per_variant.get(code, {}).items():
            put(field, raw, out)
        out["_ids"] = [code]
        return out
    blocks = []
    for code, _note in variants:
        out = dict(shared)
        for field, raw in per_variant.get(code, {}).items():
            put(field, raw, out)
        out["_ids"] = [code]
        out["_category"] = category
        blocks.append(out)
    return {"_blocks": blocks}


_COLOURS = {"black": "Black", "white": "White", "pink": "Pink", "silver": "Silver",
            "gray": "Gray", "grey": "Gray", "red": "Red", "blue": "Blue", "green": "Green",
            "gold": "Gold", "titanium": "Titanium"}


def _colour(text: str) -> str | None:
    """'black, mesh front panel' -> 'Black'; 'black&white' -> 'Black / White';
    'Black (lead-free paint)' -> 'Black'. Anything else -> None."""
    first = re.sub(r"\([^)]*\)", " ", str(text or "")).split(",")[0].strip().lower()
    parts = [p.strip() for p in re.split(r"\s*(?:&|/|\band\b)\s*", first) if p.strip()]
    if parts and all(p in _COLOURS for p in parts):
        return " / ".join(_COLOURS[p] for p in parts)
    return None


def _per_variant(category: str, items: dict, intro: dict,
                 variants: list[tuple[str, str]]) -> dict[str, dict]:
    """Fields that differ between the codes of one page: colour (from the
    code's own note, or the page's single Color row when only one code is
    sold), ARGB in the code / note, and - for cases - the front I/O when the
    page lists it per code ('SST-FA313-B-C: USB Type-C x 1 ...')."""
    out: dict[str, dict] = {code: {} for code, _ in variants}
    colour_row = _lines(items, "color")
    for code, note in variants:
        colour = _colour(note)
        if colour is None and len(variants) == 1 and len(colour_row) == 1:
            colour = _colour(colour_row[0])
        if colour:
            out[code]["color"] = colour
        argb = re.search(r"\bA-?RGB\b", code + " " + note, re.I)
        if argb:
            out[code]["lighting" if category in ("case", "cooler_air", "aio") else "led"] = "ARGB"
    if category == "case":
        for code, ports in _front_io(items, [c for c, _ in variants]).items():
            out[code]["front_usb"] = ports
    return out


def _front_io(items: dict, codes: list[str]) -> dict[str, list[str]]:
    lines = _lines(items, "front i/o port", "front i/o ports", "i/o port", "front i/o")
    if not lines:
        return {}
    sections: dict[str, list[str]] = {}
    current = None
    headed = False
    for line in lines:
        heading = re.fullmatch(r"\s*(.+?)\s*[:：]\s*", line)
        if heading:
            headed = True
            current = _code(heading.group(1)) or None
            if current is not None:
                sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
        elif not headed:
            sections.setdefault("", []).append(line)
    out: dict[str, list[str]] = {}
    for code in codes:
        # A list split by headings that are not this page's codes ("Type-C
        # version:") cannot be attributed: nothing is read.
        body = sections.get(code) if headed else sections.get("")
        if not body:
            continue
        text = ", ".join(re.sub(r"\([^)]*\)", " ", line) for line in body)
        ports = front_io_ports(text)
        if ports:
            out[code] = ports
    return out


# -- shared number readers ------------------------------------------------------

def _mm_values(text: str) -> list[float]:
    return [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", str(text or ""), re.I)]


def _whd(lines: list[str]) -> dict[str, float] | None:
    """'181mm (W), x 360mm (H), x 410mm (D), 26.72 liters' -> {W, H, D}; only
    the first metric line (the page repeats it in inches)."""
    for line in lines:
        found = dict((axis.upper(), float(value)) for value, axis in
                     re.findall(r"(\d+(?:\.\d+)?)\s*mm\s*\(\s*([WHD])\s*\)", line, re.I))
        if len(found) == 3:
            return found
    return None


def _number(text: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(text or "")))
    return float(match.group(0)) if match else None


def _top(lines: list[str]) -> float | None:
    span = spec_range(" ".join(lines)) if lines else None
    return span[1] if span else None


def _speed(put, low_field: str, high_field: str, lines: list[str]) -> None:
    span = spec_range(" ".join(lines)) if lines else None
    if span:
        if span[0] != span[1] and span[0] >= 100:   # "0 ~ 1200 RPM": a fan-stop floor
            put(low_field, int(span[0]))
        put(high_field, int(span[1]))


def _square_fan(lines: list[str]) -> int | None:
    """'120mm (W) x 25mm (H) x 120 mm (D)' -> 120 (the two equal sides)."""
    for line in lines:
        values = [round(v) for v in _mm_values(line)][:3]
        if len(values) == 3:
            for value in values:
                if values.count(value) >= 2:
                    return value
            return None
    return None


def _sockets(lines: list[str]) -> list[str]:
    """'Intel LGA 115X/1200/1700/1851' + 'AMD Socket AM3/AM4/AM5' ->
    LGA115X, LGA1200, ..., AM3, AM4, AM5 (the catalog's tokens)."""
    out: list[str] = []
    for line in lines:
        line = re.sub(r"\([^)]*\)", " ", line)
        lga = re.search(r"LGA\s*([0-9X/\s]+)", line, re.I)
        if lga:
            for number in re.findall(r"\d{3,4}X?", lga.group(1).upper()):
                token = f"LGA{number}"
                if token not in out:
                    out.append(token)
        amd = re.search(r"Socket\s+(.+)$", line, re.I) if re.search(r"\bAMD\b", line, re.I) else None
        if amd:
            for token in re.split(r"\s*/\s*|,\s*", amd.group(1)):
                token = token.strip()
                if re.fullmatch(r"AM\d\+?|SP\d|sTR\d|sWRX\d|TR4|FM\d\+?", token, re.I):
                    token = token if token[0] == "s" else token.upper()
                    if token not in out:
                        out.append(token)
    return out


# -- case -----------------------------------------------------------------------

_POSITIONS = (("fan_front", ("front",)), ("fan_top", ("top",)), ("fan_rear", ("rear",)),
              ("fan_side", ("side",)), ("fan_bottom", ("bottom",)))
_BAY = r"[\"”″'′’]"


def _case(items, intro, put) -> None:
    support = " ".join(_lines(items, "motherboard"))
    support = re.sub(r"\bExtended\s*-?\s*ATX\b", "E-ATX", support, flags=re.I)
    support = re.sub(r"Specialized form factor|SSI-?\s*[EC]EB", " ", support, flags=re.I)
    forms = mb_form_factor_list(support)
    if forms:
        put("mb_form_factors", forms)
    # "Length : 354mm (incl. front 25mm thickness fan installed)" / "Compatible
    # up to 13" (330mm) long": the longest card the case states it takes.
    lengths = []
    for line in _lines(items, "limitation of expansion card", "limitation of graphics card",
                       "limitation of vga card"):
        if re.search(r"\blength\b", line, re.I):
            value = re.search(r"length[^:：0-9]*[:：]?\s*(\d{2,3})\s*mm", line, re.I)
            if value:
                lengths.append(int(value.group(1)))
        else:
            value = re.search(r"\((\d{2,3})\s*mm\)\s*long|(\d{2,3})\s*mm\s*long", line, re.I)
            if value:
                lengths.append(int(value.group(1) or value.group(2)))
    if lengths:
        put("max_gpu_length_mm", max(lengths))
    heights = [v for line in _lines(items, "limitation of cpu cooler") for v in _mm_values(line)
               if v >= 30]
    if heights:
        put("max_cooler_height_mm", int(round(max(heights))))
    slots = []
    for line in _lines(items, "expansion slot", "expansion slots"):
        value = re.match(r"\s*(\d{1,2})\b", line)
        if not value or "+" in line:
            slots = []
            break
        slots.append(int(value.group(1)))
    if slots:
        put("expansion_slots", str(max(slots)))
    dims = _whd(_lines(items, "dimension", "dimensions"))
    if dims:
        put("dimensions_mm", f"W={round(dims['W'])} H={round(dims['H'])} D={round(dims['D'])}mm")
    volume = re.search(r"(\d+(?:\.\d+)?)\s*liters?\b", " ".join(_lines(items, "dimension")), re.I)
    if volume:
        put("volume_l", float(volume.group(1)))
    weight = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", " ".join(_lines(items, "net weight", "weight")), re.I)
    if weight:
        put("weight_kg", float(weight.group(1)))
    material = " ".join(_lines(items, "material"))
    if re.search(r"tempered glass|acrylic|window", material, re.I):
        put("side_panel", "Windowed")
    form = " ".join(_lines(items, "chassis form factor"))
    rack = re.fullmatch(r"\s*([1-9])\s*U\s*", form, re.I)
    if rack:
        put("type", f"{rack.group(1)}U")
        put("rackmount", True)
    for field, keys in _POSITIONS:
        for sub, lines in _subs(items, "cooling system"):
            if any(re.search(rf"\b{key}\b", sub, re.I) for key in keys):
                text = " / ".join(re.sub(r"\[\d\]|\*", "", line) for line in lines)
                text = re.sub(r"\b(?:left|right)(?:\s*side)?\s*[:：]", " ", text, flags=re.I)
                put(field, fan_mounts(text))
                break
    sizes: set[int] = set()
    for _sub, lines in _subs(items, "radiator support"):
        for line in lines:
            sizes |= radiator_sizes(line)
    if sizes:
        put("radiator_support", {f"{n} mm": 1 for n in sorted(sizes)})
    _drive_bays(items, put)


def _drive_bays(items, put) -> None:
    """Internal 3.5" / 2.5" bays, only when every line names one size: a combo
    line ('3.5"/ 2.5" x 1', '2.5" x 1 or 3.5" x 1') does not say which count
    it adds to. Notes in brackets ('(compatible with 2.5" x 3)') are dropped;
    external bays that take 3.5" / 2.5" drives make the total unknown."""
    subs = _subs(items, "drive bay", "drive bays", "drive support")
    if not subs:
        return
    counts = {"3.5": 0, "2.5": 0}
    for sub, lines in subs:
        internal = re.search(r"internal", sub, re.I)
        for line in lines:
            line = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", line).replace(",", ".")
            sizes = set(re.findall(rf"([23]\.5)\s*{_BAY}", line))
            if not internal:
                if sizes:
                    return
                continue
            if len(sizes) != 1:
                return
            size = sizes.pop()
            count = re.search(rf"{re.escape(size)}\s*{_BAY}\s*(?:HDD|SSD|drive)?\s*[x×]\s*(\d{{1,2}})", line, re.I)
            if not count:
                return
            counts[size] += int(count.group(1))
    if any(re.search("internal", sub, re.I) for sub, _ in subs):
        put("drive_bays_35", counts["3.5"])
        put("drive_bays_25", counts["2.5"])


# -- psu -----------------------------------------------------------------------

def _psu_lines(lines: list[str]) -> list[str]:
    """SilverStone's connector spellings -> the shared counter's:
    '8 / 6-Pin PCIe' is a 6+2, '8 / 4-Pin EPS' a 4+4, '24 / 20-Pin' the
    24-pin; a lone '4-Pin EPS / ATX 12V' is no 8-pin EPS and is left out."""
    out = []
    for line in lines:
        line = re.sub(r"\b8\s*/\s*6\s*-?\s*Pin", "6+2-Pin", line, flags=re.I)
        line = re.sub(r"\b8\s*/\s*4\s*-?\s*Pin", "4+4-Pin", line, flags=re.I)
        line = re.sub(r"\b24\s*/\s*20\s*-?\s*Pin", "24-Pin", line, flags=re.I)
        if re.search(r"\bx\s*4\s*-?\s*Pin\s+(?:EPS|ATX\s*12V|CPU)", line, re.I):
            continue
        out.append(line)
    return out


def _psu(items, intro, put) -> None:
    watts = _number(" ".join(_lines(items, "max. dc output", "max dc output")))
    if watts:
        put("wattage_w", int(watts))
    put("efficiency", efficiency_tier(" ".join(_lines(items, "certification", "80 plus"))))
    claims = " ".join([intro["headline"], *intro["features"]])
    if re.search(r"\bsemi[\s-]*modular\b", claims, re.I):
        put("modular", "semi")
    elif re.search(r"\b(?:fully|full|100%)\s*modular\b", claims, re.I):
        put("modular", "full")
    elif re.search(r"\bnon[\s-]*modular\b|\bfixed[\s-]*cables?\b", claims, re.I):
        put("modular", "no")
    versions = {f"ATX {v}" for v in re.findall(r"\bATX\s*(3\.[01])\b", claims, re.I)}
    if len(versions) == 1:
        put("atx_version", versions.pop())
    form = " ".join(_lines(items, "form factor"))
    if not re.search(r"redundant", form, re.I):
        for pattern, value in ((r"\bSFX[\s-]*L\b", "SFX-L"), (r"\bSFX\b", "SFX"), (r"\bTFX\b", "TFX"),
                               (r"\bFlex\s*-?\s*ATX\b", "Flex ATX"), (r"\bATX\b|\bPS\s*/?\s*2\b", "ATX")):
            if re.search(pattern, form, re.I):
                put("type", value)
                break
    # One housing only: redundant units print bracket / housing / module sizes.
    metric = [line for line in _lines(items, "dimension") if re.search(r"mm\s*\(\s*D\s*\)", line, re.I)]
    if len(metric) == 1:
        dims = _whd(metric)
        if dims:
            put("length_mm", int(round(dims["D"])))
    cooling = " ".join(_lines(items, "cooling system"))
    fan = re.search(r"(\d{2,3})\s*mm", cooling, re.I)
    if fan:
        put("fan_size_mm", int(fan.group(1)))
        put("fanless", False)
    elif re.search(r"\bfanless\b|\bpassive\b", cooling, re.I):
        put("fanless", True)
    for field, count in psu_connector_counts(_psu_lines(_lines(items, "connectors", "connector"))).items():
        put(field, count)


# -- fans / coolers -------------------------------------------------------------

def _fan_connector(text: str, put, *, pwm_field: str | None = "pwm",
                   connector_field: str = "connector") -> None:
    pins = re.search(r"(\d)\s*-?\s*pin", text, re.I)
    if pins:
        put(connector_field, f"{pins.group(1)}-pin")
        if pwm_field:
            if re.search(r"\bPWM\b", text):
                put(pwm_field, True)
            elif pins.group(1) == "3":
                put(pwm_field, False)


def _fan(items, intro, put) -> None:
    put("size_mm", _square_fan(_lines(items, "dimension")))
    _speed(put, "rpm_min", "rpm_max", _lines(items, "speed"))
    put("airflow_cfm", _top(_lines(items, "airflow")))
    put("static_pressure_mmh2o", _top(_lines(items, "static pressure")))
    put("noise_db", _top(_lines(items, "noise level")))
    connectors = " ".join(_lines(items, "connectors", "connector"))
    _fan_connector(connectors, put)
    if re.search(r"\bA-?RGB\b", connectors, re.I):
        put("led", "ARGB")
    codes = _variants(items, intro)
    pack_matches = [re.search(r"-(\d)PK$", code) for code, _ in codes]
    pack_sizes = [match.group(1) for match in pack_matches if match is not None]
    if pack_matches and len(pack_sizes) == len(pack_matches) and len(set(pack_sizes)) == 1:
        put("quantity", int(pack_sizes[0]))


def _fan_block(items) -> dict[str, list[str]]:
    return {re.sub(r"\s+", " ", sub).strip().lower(): lines for sub, lines in _subs(items, "fan")}


def _cooler_air(items, intro, put) -> None:
    fan = _fan_block(items)
    put("fan_size_mm", _square_fan(fan.get("dimension", [])))
    _speed(put, "fan_rpm_min", "fan_rpm_max", fan.get("speed", []))
    put("noise_db", _top(fan.get("noise level", [])))
    put("airflow_cfm", _top(fan.get("max airflow", []) or fan.get("airflow", [])))
    dims = _whd(_lines(items, "dimension"))
    if dims:
        put("height_mm", int(round(dims["H"])))
    sockets = _sockets(_lines(items, "application"))
    if sockets:
        put("sockets", sockets)
    tdp = re.search(r"(\d{2,4})\s*W\b", " ".join(_lines(items, "cpu tdp", "tdp")), re.I)
    if tdp:
        put("tdp_w", int(tdp.group(1)))
    if re.search(r"\bA-?RGB\b", " ".join(fan.get("connector", [])), re.I):
        put("lighting", "ARGB")


def _aio(items, intro, put) -> None:
    fan = _fan_block(items)
    put("fan_size_mm", _square_fan(fan.get("dimension", [])))
    _speed(put, "fan_rpm_min", "fan_rpm_max", fan.get("speed", []))
    put("noise_db", _top(fan.get("noise level", [])))
    put("airflow_cfm", _top(fan.get("max airflow", []) or fan.get("airflow", [])))
    radiator = {re.sub(r"\s+", " ", sub).strip().lower(): lines for sub, lines in _subs(items, "radiator")}
    dims = _whd(radiator.get("dimension", []))
    if dims:
        put("radiator_length_mm", int(round(max(dims["W"], dims["D"]))))
        put("radiator_thickness_mm", int(round(dims["H"])))
        # The size class the model name states ("XE360PD"), only when the
        # radiator's own length is that class (360 -> 380-420 mm).
        size = re.search(r"(?<!\d)(120|240|280|360|420)(?!\d)", intro["name"] + " " + intro["headline"])
        length = max(dims["W"], dims["D"])
        if size and int(size.group(1)) <= length <= int(size.group(1)) * 1.2:
            put("radiator_size_mm", int(size.group(1)))
    sockets = _sockets(_lines(items, "application"))
    if sockets:
        put("sockets", sockets)
    connectors: list[str] = []
    pump = {re.sub(r"\s+", " ", sub).strip().lower(): lines for sub, lines in _subs(items, "pump")}
    for text in (" ".join(pump.get("connectors", []) + pump.get("connector", [])),
                 " ".join(fan.get("connector", []) + fan.get("connectors", []))):
        for part in re.split(r"[&,;/]|\band\b", text):
            pins = re.search(r"(\d)\s*-?\s*pin", part, re.I)
            if not pins:
                continue
            if re.search(r"A-?RGB|LED", part, re.I):
                token = f"{pins.group(1)}-pin ARGB"
            elif re.search(r"PWM", part, re.I):
                token = f"{pins.group(1)}-pin PWM"
            else:
                token = f"{pins.group(1)}-pin"
            if token not in connectors:
                connectors.append(token)
    if connectors:
        put("connectors", connectors)
