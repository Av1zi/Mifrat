"""
Phase 2B: "Compatibility & features" attribute extraction.

Builds a structured `attributes` blob per listing, per category.
The blob is deliberately loose (plan §7): categories share almost no fields.

Priority of evidence:
1. `vendor_meta` — structured specs harvested straight from vendor payloads
   (Ivory's builder API carries per-product compatibility/features data).
2. Plonter-style dash-separated spec fragments
   ("LGA1700 socket - B760 chipset - DDR5 - WIFI - mATX").
3. Free-text regex over the cleaned match text.
4. Knowledge maps (chipset -> socket / memory generation).
"""

from __future__ import annotations

import html as _html
import json
import re
import unicodedata
from pathlib import Path

HEBREW = re.compile(r"[\u0590-\u05FF]+")


def clean_text(value) -> str:
    if value is None:
        return ""
    s = _html.unescape(str(value))
    s = unicodedata.normalize("NFKC", s)
    s = HEBREW.sub(" ", s)
    s = re.sub(r"[^A-Za-z0-9#+/.&()-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# Knowledge maps
# --------------------------------------------------------------------------

# chipset -> (socket, memory type). None = board-dependent, look at the title.
CHIPSET_INFO = {
    # AMD AM4 / DDR4
    "A320": ("AM4", "DDR4"), "B450": ("AM4", "DDR4"), "X470": ("AM4", "DDR4"),
    "A520": ("AM4", "DDR4"), "B550": ("AM4", "DDR4"), "X570": ("AM4", "DDR4"),
    # AMD AM5 / DDR5
    "A620": ("AM5", "DDR5"), "B650": ("AM5", "DDR5"), "X670": ("AM5", "DDR5"),
    "X670E": ("AM5", "DDR5"), "X870": ("AM5", "DDR5"), "X870E": ("AM5", "DDR5"),
    "B840": ("AM5", "DDR5"), "B850": ("AM5", "DDR5"),
    # Intel LGA1700 (DDR4 or DDR5 depending on board)
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "H670": ("LGA1700", None),
    "Z690": ("LGA1700", None), "B760": ("LGA1700", None), "H770": ("LGA1700", None),
    "Z790": ("LGA1700", None),
    # Intel LGA1851 (DDR5 only)
    "H810": ("LGA1851", "DDR5"), "B860": ("LGA1851", "DDR5"), "Z890": ("LGA1851", "DDR5"),
    # HEDT / legacy
    "X299": ("LGA2066", "DDR4"), "Z390": ("LGA1151", "DDR4"),
}

CHIPSET_RE = re.compile(
    r"\b(X670E|X870E|X870|X670|X570|X470|X299|"
    r"B850|B840|B860|B760|B660|B650|B550|B450|"
    r"A620|A520|A320|"
    r"Z890|Z790|Z690|Z390|"
    r"H810|H770|H670|H610|H310)([A-Z]?)\b",
    re.I,
)

SOCKET_RE = re.compile(r"\b(LGA\s?\d{3,4}|sWRX8|SP3|TR4|AM[45])\b", re.I)

NUMERIC_SOCKET = {
    "1700": "LGA1700", "1851": "LGA1851", "1200": "LGA1200",
    "1151": "LGA1151", "1150": "LGA1150", "1155": "LGA1155",
    "1366": "LGA1366", "2066": "LGA2066",
}

DDR_RE = re.compile(r"\bDDR\s?([345])\b", re.I)
WIFI_STD_RE = re.compile(r"\bWIFI\s?([67])\s?(E)?\b", re.I)
WIFI_RE = re.compile(r"\bWIFI\b|\bWI-?FI\b|\bWIRELESS\b", re.I)

FORM_FACTOR_PATTERNS = [
    (re.compile(r"\bMINI\s?[- ]?ITX\b|\bITX\b", re.I), "Mini-ITX"),
    (re.compile(r"\bMICRO\s?[- ]?ATX\b|\bM\s?[- ]?ATX\b|\bMATX\b", re.I), "mATX"),
    (re.compile(r"\bE\s?[- ]?ATX\b|\bEEB\b", re.I), "EATX"),
    (re.compile(r"\bATX\b", re.I), "ATX"),
]

LAN_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?G\s?LAN\b", re.I)
SLOTS_RE = re.compile(r"\b(\d)\s?X\s?DDR[345]\b", re.I)

AMD_CPU_RE = re.compile(r"\bRYZEN\s?(\d)\s?(\d{4}[A-Z0-9]*)", re.I)
INTEL_CPU_RE = re.compile(
    r"\bCORE\s?(ULTRA\s?\d|I\d)[\s-]?(\d{3,4}[A-Z]{0,4}(?:\s?PLUS)?)", re.I
)
XEON_RE = re.compile(r"\bXEON\s?([A-Z]{1,3}\s?\d{4}[A-Z]?)", re.I)

GPU_CHIP_RE = re.compile(
    r"\b(GEFORCE\s?RTX\s?\d{4}(?:\s?TI)?|RTX\s?PRO\s?\d{4}[A-Z]?|RTX\s?\d{4}(?:\s?TI)?|"
    r"RX\s?\d{4}(?:\s?XT|\s?GRE)?|QUADRO\s?[A-Z0-9]+|FIREPRO\s?[A-Z0-9]+|"
    r"ARC\s?PRO\s?[A-Z]\d+|ARC\s?[A-Z]\d{2,3})\b",
    re.I,
)
VRAM_RE = re.compile(r"\b(\d{1,2})\s?GB\b")
GMEM_RE = re.compile(r"\bGDDR([67])\b", re.I)

WATT_RE = re.compile(r"\b(\d{3,4})\s?W\b")
EFF_RE = re.compile(
    r"80\s?PLUS\s?(TITANIUM|PLATINUM|GOLD|SILVER|BRONZE|WHITE)", re.I
)
MOD_RE = re.compile(r"\b(FULL\s?MODULAR|SEMI\s?MODULAR|NON\s?MODULAR|MODULAR)\b", re.I)

KIT_RE = re.compile(r"\((\d)\s?X\s?(\d{1,3})\s?(?:GB)?\)", re.I)
SPEED_RE = re.compile(r"\b(\d{4})\s?MHZ\b", re.I)
CL_RE = re.compile(r"\bCL\s?(\d{2})\b", re.I)

SIZE_MM_RE = re.compile(r"\b(80|92|120|140|170|200|240|280|360|420)\s?MM\b", re.I)

COLOR_WORDS = [
    "black", "white", "silver", "gray", "grey", "charcoal",
    "blue", "midnight", "red", "pink", "purple", "brown",
]

# Hebrew spec prose (Ivory descriptions)
HE_CORES_RE = re.compile(r"(\d+)\s*ליבות")
HE_THREADS_RE = re.compile(r"(\d+)\s*תהליכונים")
HE_CLOCK_RE = re.compile(r"([\d.]+)\s*GHz\s*-\s*([\d.]+)\s*GHz")
HE_COOLER_RE = re.compile(r"כולל\s*מאוורר")
HE_NO_COOLER_RE = re.compile(r"ללא\s*מאוורר|בלי\s*מאוורר")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _socket_from_text(text: str) -> str | None:
    m = SOCKET_RE.search(text)
    if m:
        return m.group(1).upper().replace(" ", "")
    m = re.search(r"\b(1700|1851|1200|1151|1150|1155|1366|2066)\b", text)
    if m:
        return NUMERIC_SOCKET[m.group(1)]
    return None


def _form_factor(text: str) -> str | None:
    for rx, label in FORM_FACTOR_PATTERNS:
        if rx.search(text):
            return label
    return None


def _wifi(text: str) -> tuple[bool | None, str | None]:
    m = WIFI_STD_RE.search(text)
    if m:
        return True, ("WIFI" + m.group(1) + (m.group(2) or "")).upper()
    if WIFI_RE.search(text):
        return True, None
    return None, None


def _ddr(text: str) -> str | None:
    m = DDR_RE.search(text)
    return f"DDR{m.group(1)}" if m else None


def _revision(text: str) -> str | None:
    m = re.search(r"\b[Vv](\d+)\b", text)
    if m:
        return f"V{m.group(1)}"
    m = re.search(r"\b[Rr](\d+)\b", text)
    if m:
        return f"R{m.group(1)}"
    m = re.search(r"\bREV\.?\s?(\d+(?:\.\d+)?)\b", text, re.I)
    if m:
        return f"REV{m.group(1)}"
    if re.search(r"\bIII\b", text):
        return "V3"
    if re.search(r"\bII\b", text):
        return "V2"
    return None


def _norm_key_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


# --------------------------------------------------------------------------
# vendor_meta harvesting (Ivory builder payload etc.)
# --------------------------------------------------------------------------

_META_SCALAR_KEYS = {
    "socket", "chipset", "form_factor", "memory_type", "wifi", "wattage_w",
    "efficiency", "vram_gb", "platform", "co_dependant",
    "build_computer_global_categories_id",
}


def _from_vendor_meta(meta) -> dict:
    """
    Defensive harvester for structured vendor specs.

    Accepts either flat keys (socket=..., chipset=...) or nested
    name/value spec blocks (specs / features / compatibility / data).
    """
    out: dict = {}
    if not isinstance(meta, dict):
        return out

    for k, v in meta.items():
        if k in _META_SCALAR_KEYS and v not in (None, "", [], {}):
            out[k] = v

    for key in ("specs", "spec", "features", "compatibility", "data", "details"):
        block = meta.get(key)
        if isinstance(block, dict):
            for k, v in block.items():
                if v not in (None, "", [], {}):
                    out.setdefault(_norm_key_name(k), v)
        elif isinstance(block, list):
            for item in block:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    out.setdefault(_norm_key_name(item["name"]), item["value"])

    return out


_LABELS_CACHE = None


def _load_cut_labels() -> dict:
    """
    Labels for Ivory's opaque builder IDs, learned by
    scraper/learn_ivory_labels.py from correlation with title-derived
    attributes. Empty until you run the learner once.
    """
    global _LABELS_CACHE
    if _LABELS_CACHE is None:
        path = Path(__file__).resolve().parent.parent / "data" / "ivory_cut_labels.json"
        try:
            _LABELS_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _LABELS_CACHE = {}
    return _LABELS_CACHE


def _parse_hebrew_description(desc: str) -> dict:
    a: dict = {}

    m = HE_CORES_RE.search(desc)
    if m:
        a["cores"] = int(m.group(1))

    m = HE_THREADS_RE.search(desc)
    if m:
        a["threads"] = int(m.group(1))

    m = HE_CLOCK_RE.search(desc)
    if m:
        a["base_clock_ghz"] = float(m.group(1))
        a["boost_clock_ghz"] = float(m.group(2))

    if HE_COOLER_RE.search(desc):
        a["cooler_included"] = True
    elif HE_NO_COOLER_RE.search(desc):
        a["cooler_included"] = False

    return a


# --------------------------------------------------------------------------
# Per-category parsers (title/SKU based)
# --------------------------------------------------------------------------

def _parse_motherboard(text: str, meta) -> dict:
    a: dict = {}

    chipset_m = CHIPSET_RE.search(text)
    chipset = chipset_m.group(1).upper() if chipset_m else None
    if chipset:
        a["chipset"] = chipset

    info = CHIPSET_INFO.get(chipset or "", (None, None))

    socket = _socket_from_text(text) or info[0]
    if socket:
        a["socket"] = socket

    ddr = _ddr(text) or info[1]
    if ddr:
        a["memory_type"] = ddr

    ff = _form_factor(text)
    if ff:
        a["form_factor"] = ff

    wifi, std = _wifi(text)
    if wifi is not None:
        a["wifi"] = wifi
        if std:
            a["wifi_standard"] = std

    lan = LAN_RE.search(text)
    if lan:
        a["lan"] = f"{lan.group(1)}G"

    slots = SLOTS_RE.search(text)
    if slots:
        a["memory_slots"] = int(slots.group(1))

    rev = _revision(text)
    if rev:
        a["revision"] = rev

    return a


def _parse_cpu(text: str, meta) -> dict:
    a: dict = {}

    socket = _socket_from_text(text)
    if socket:
        a["socket"] = socket

    if re.search(r"\bTRAY\b", text, re.I):
        a["packaging"] = "Tray"
    elif re.search(r"\bBOX\b|\bWOF\b", text, re.I):
        a["packaging"] = "Box"

    m = AMD_CPU_RE.search(text)
    if m:
        a["brand"] = "AMD"
        a["model"] = f"Ryzen {m.group(1)} {m.group(2).upper()}"
    else:
        m = INTEL_CPU_RE.search(text)
        if m:
            a["brand"] = "Intel"
            fam = re.sub(r"\s+", " ", m.group(1).upper())
            a["model"] = f"Core {fam} {m.group(2).upper().strip()}"
        else:
            m = XEON_RE.search(text)
            if m:
                a["brand"] = "Intel"
                a["model"] = f"Xeon {m.group(1).replace(' ', '')}"

    return a


def _parse_gpu(text: str, meta) -> dict:
    a: dict = {}

    m = GPU_CHIP_RE.search(text)
    if m:
        a["gpu_chip"] = re.sub(r"\s+", " ", m.group(1).upper().strip())

    v = VRAM_RE.search(text)
    if v:
        a["vram_gb"] = int(v.group(1))

    g = GMEM_RE.search(text)
    if g:
        a["memory_type"] = f"GDDR{g.group(1)}"

    return a


def _parse_psu(text: str, meta) -> dict:
    a: dict = {}

    w = WATT_RE.search(text)
    if w:
        a["wattage_w"] = int(w.group(1))

    e = EFF_RE.search(text)
    if e:
        a["efficiency"] = e.group(1).upper()

    m = MOD_RE.search(text)
    if m:
        a["modular"] = re.sub(r"\s+", " ", m.group(1).upper())

    return a


def _parse_memory(text: str, meta) -> dict:
    a: dict = {}

    ddr = _ddr(text)
    if ddr:
        a["memory_type"] = ddr

    t = re.sub(r"\s+", "", text.lower())
    m = re.search(r"(\d+)gb", t)
    if m:
        a["total_gb"] = int(m.group(1))

    k = KIT_RE.search(text)
    if k:
        a["kit"] = f"{k.group(1)}x{k.group(2)}GB"

    s = SPEED_RE.search(text)
    if s:
        a["speed_mhz"] = int(s.group(1))

    c = CL_RE.search(text)
    if c:
        a["cas_latency"] = int(c.group(1))

    return a


def _parse_case(text: str, meta) -> dict:
    a: dict = {}

    ff = _form_factor(text)
    if ff:
        a["form_factor"] = ff

    for color in COLOR_WORDS:
        if re.search(rf"\b{color}\b", text, re.I):
            a["color"] = color.title()
            break

    return a


def _parse_fan_or_aio(text: str, meta) -> dict:
    a: dict = {}

    s = SIZE_MM_RE.search(text)
    if s:
        a["size_mm"] = int(s.group(1))

    if re.search(r"\bARGB\b", text, re.I):
        a["argb"] = True
    elif re.search(r"\bRGB\b", text, re.I):
        a["rgb"] = True

    if re.search(r"\bPWM\b", text, re.I):
        a["pwm"] = True

    return a


_PARSERS = {
    "motherboard": _parse_motherboard,
    "cpu": _parse_cpu,
    "gpu": _parse_gpu,
    "psu": _parse_psu,
    "memory": _parse_memory,
    "case": _parse_case,
    "case_fan": _parse_fan_or_aio,
    "aio": _parse_fan_or_aio,
    "cooler_air": _parse_fan_or_aio,
}


# --------------------------------------------------------------------------
# Plonter-style dash-separated spec fragments
# --------------------------------------------------------------------------

def _parse_fragments(title_raw) -> dict:
    """
    Plonter titles are spec lines:
    "LGA1700 socket - B760 chipset - DDR5 - WIFI - mATX"
    """
    a: dict = {}
    parts = [p.strip() for p in str(title_raw or "").split("-")]
    if len(parts) < 3:
        return a

    for part in parts:
        pc = clean_text(part)
        if not pc:
            continue

        s = _socket_from_text(pc)
        if s and "socket" not in a:
            a["socket"] = s

        c = CHIPSET_RE.search(pc)
        if c and "chipset" not in a:
            a["chipset"] = c.group(1).upper()

        d = _ddr(pc)
        if d and "memory_type" not in a:
            a["memory_type"] = d

        f = _form_factor(pc)
        if f and "form_factor" not in a:
            a["form_factor"] = f

        w, std = _wifi(pc)
        if w is not None and "wifi" not in a:
            a["wifi"] = w
            if std:
                a["wifi_standard"] = std

        l = LAN_RE.search(pc)
        if l and "lan" not in a:
            a["lan"] = f"{l.group(1)}G"

    return a


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def extract_attributes(listing: dict) -> dict:
    """
    Build the structured attributes blob for one enriched listing.
    """
    category = listing.get("category_normalized") or ""
    meta = listing.get("vendor_meta") or {}

    text = listing.get("match_text") or clean_text(
        f"{listing.get('vendor_sku', '')} {listing.get('title_raw', '')}"
    )

    # Ivory builder payload: description/title carry Latin spec tokens
    # (GHz ranges, DDR5, WiFi...) that the scraped title sometimes omits.
    extra = " ".join(
        str(meta[k]) for k in ("title", "description") if isinstance(meta.get(k), str)
    )
    if extra:
        text = f"{text} {clean_text(extra)}"

    attrs = _from_vendor_meta(meta)

    parser = _PARSERS.get(category)
    if parser:
        for k, v in parser(text, meta).items():
            attrs.setdefault(k, v)

    for k, v in _parse_fragments(listing.get("title_raw")).items():
        attrs.setdefault(k, v)

    # Hebrew description facts (mostly CPUs).
    raw_desc = meta.get("description")
    if isinstance(raw_desc, str) and raw_desc:
        for k, v in _parse_hebrew_description(raw_desc).items():
            attrs.setdefault(k, v)

    # Structural builder data.
    cuts = meta.get("cuts")
    if isinstance(cuts, list) and cuts:
        attrs["ivory_cuts"] = sorted(int(c) for c in cuts if str(c).isdigit())

    parent = meta.get("parent")
    if parent not in (None, "", 0):
        attrs["ivory_parent"] = parent

    # Apply learned labels for opaque Ivory IDs (second pass onwards).
    labels = _load_cut_labels()
    if labels:
        for cut in attrs.get("ivory_cuts", []):
            for k, v in (labels.get("cuts", {}).get(str(cut)) or {}).items():
                attrs.setdefault(k, v)

        parent_label = (
            labels.get("parents", {}).get(str(attrs.get("ivory_parent")), {})
        ).get("category")
        if parent_label:
            attrs.setdefault("ivory_category", parent_label)

    return attrs