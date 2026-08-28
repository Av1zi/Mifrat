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

Goal: align with PCPartPicker filter parity (see screenshots):
- PSU: type, efficiency, wattage, length, modular, color, fanless, connector counts
- GPU: chipset, memory, memory type, core/boost clock, interface, color, length, TDP,
       ports (HDMI/DP/DVI), slot width, cooling, external power
- Storage: capacity, type, cache, form factor, interface/NVMe, PCIe gen, RPM
- Memory: form factor, type, speed, modules, color, voltage, timing, ECC, heat spreader,
          first-word latency
- Motherboard: socket, form factor, chipset, memory max/type/slots, color, PCIe/M.2/SATA
- Case: type, color, side panel, PSU, bays, radiator support, volume, max GPU length
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
    "A320": ("AM4", "DDR4"), "B350": ("AM4", "DDR4"), "X370": ("AM4", "DDR4"),
    "A520": ("AM4", "DDR4"), "B450": ("AM4", "DDR4"), "X470": ("AM4", "DDR4"),
    "B550": ("AM4", "DDR4"), "X570": ("AM4", "DDR4"), "X570S": ("AM4", "DDR4"),
    # AMD AM5 / DDR5
    "A620": ("AM5", "DDR5"), "B650": ("AM5", "DDR5"), "B650E": ("AM5", "DDR5"),
    "X670": ("AM5", "DDR5"), "X670E": ("AM5", "DDR5"), "X870": ("AM5", "DDR5"),
    "X870E": ("AM5", "DDR5"), "B840": ("AM5", "DDR5"), "B850": ("AM5", "DDR5"),
    # AMD sTR5 / WRX90 etc
    "TRX50": ("sTR5", "DDR5"), "WRX90": ("sWRX8", "DDR5"),
    # Intel LGA1151 / DDR4
    "H110": ("LGA1151", "DDR4"), "B150": ("LGA1151", "DDR4"), "H170": ("LGA1151", "DDR4"),
    "Z170": ("LGA1151", "DDR4"), "B250": ("LGA1151", "DDR4"), "H270": ("LGA1151", "DDR4"),
    "Z270": ("LGA1151", "DDR4"), "H310": ("LGA1151", "DDR4"), "B360": ("LGA1151", "DDR4"),
    "H370": ("LGA1151", "DDR4"), "Z370": ("LGA1151", "DDR4"), "B365": ("LGA1151", "DDR4"),
    "Z390": ("LGA1151", "DDR4"),
    # Intel LGA1200 / DDR4
    "H410": ("LGA1200", "DDR4"), "B460": ("LGA1200", "DDR4"), "H470": ("LGA1200", "DDR4"),
    "Z490": ("LGA1200", "DDR4"), "W480": ("LGA1200", "DDR4"), "H510": ("LGA1200", "DDR4"),
    "B560": ("LGA1200", "DDR4"), "H570": ("LGA1200", "DDR4"), "Z590": ("LGA1200", "DDR4"),
    # Intel LGA1700 (DDR4 or DDR5 depending on board)
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "H670": ("LGA1700", None),
    "Z690": ("LGA1700", None), "B760": ("LGA1700", None), "H770": ("LGA1700", None),
    "Z790": ("LGA1700", None), "W680": ("LGA1700", None),
    # Intel LGA1851 (DDR5 only)
    "H810": ("LGA1851", "DDR5"), "B860": ("LGA1851", "DDR5"), "Z890": ("LGA1851", "DDR5"),
    # HEDT / legacy
    "X99": ("LGA2011-v3", "DDR4"), "X299": ("LGA2066", "DDR4"),
    "X399": ("TR4", "DDR4"), "TRX40": ("sTRX4", "DDR4"),
    "C422": ("LGA2066", "DDR4"), "C621": ("LGA3647", "DDR4"),
}

CHIPSET_RE = re.compile(
    r"\b(X670E|X870E|X870|X670|X570S|X570|X470|X370|X399|X99|X299|"
    r"TRX50|WRX90|TRX40|"
    r"B850|B840|B860|B760|B660|B650E|B650|B560|B550|B460|B450|B360|B350|"
    r"A620|A520|A320|"
    r"Z890|Z790|Z690|Z590|Z490|Z390|Z370|Z270|Z170|"
    r"H810|H770|H670|H610|H570|H510|H470|H410|H370|H310|H270|H170|H110|"
    r"W680|W480|"
    r"B365|H310)([A-Z]?)\b",
    re.I,
)

SOCKET_RE = re.compile(r"\b(LGA\s?\d{3,4}|sTR5|sWRX8|TRX40|SP3|TR4|AM[45])\b", re.I)

NUMERIC_SOCKET = {
    "1700": "LGA1700", "1851": "LGA1851", "1200": "LGA1200",
    "1151": "LGA1151", "1150": "LGA1150", "1155": "LGA1155",
    "1366": "LGA1366", "2066": "LGA2066", "2011": "LGA2011",
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

CASE_FORM_FACTOR_PATTERNS = [
    (re.compile(r"\bATX\s+FULL\s+TOWER\b", re.I), "ATX Full Tower"),
    (re.compile(r"\bATX\s+MID\s+TOWER\b", re.I), "ATX Mid Tower"),
    (re.compile(r"\bMICRO\s?ATX\s+MINI\s+TOWER\b", re.I), "MicroATX Mini Tower"),
    (re.compile(r"\bMICRO\s?ATX\s+MID\s+TOWER\b", re.I), "MicroATX Mid Tower"),
    (re.compile(r"\bMINI\s?ITX\s+DESKTOP\b", re.I), "Mini ITX Desktop"),
    (re.compile(r"\bMINI\s?ITX\s+TOWER\b", re.I), "Mini ITX Tower"),
]

LAN_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?G\s?LAN\b", re.I)
SLOTS_RE = re.compile(r"\b(\d)\s?X\s?DDR[345]\b", re.I)
MEMORY_MAX_RE = re.compile(r"\b(\d+)\s?GB\s*(?:MAX|Maximum)\b", re.I)
M2_SLOTS_RE = re.compile(r"\b(\d+)\s?X\s?M\.?2\b", re.I)
SATA_PORTS_RE = re.compile(r"\b(\d+)\s?X\s?SATA\b", re.I)

AMD_CPU_RE = re.compile(r"\bRYZEN\s?(\d)\s?(\d{4}[A-Z0-9]*)", re.I)
INTEL_CPU_RE = re.compile(
    r"\bCORE\s?(ULTRA\s?\d|I\d)[\s-]?(\d{4,5}[A-Z]{0,4}(?:\s?PLUS)?)", re.I
)
XEON_RE = re.compile(r"\bXEON\s?([A-Z]{1,3}\s?\d{4}[A-Z]?)", re.I)

# Expanded GPU chip: covers GeForce RTX (incl. xx50 Ti, xx60 Ti), RTX PRO/A-series,
# Radeon RX (inc. GRE), Quadro, Tesla, ARC
GPU_CHIP_RE = re.compile(
    r"\b(GEFORCE\s?RTX\s?\d{3,4}(?:\s?(?:TI|SUPER))?|"
    r"RTX\s?PRO\s?\d{3,4}[A-Z]?|RTX\s*A\d{3,4}|RTX\s?\d{3,4}(?:\s?(?:TI|SUPER))?|"
    r"RX\s?\d{3,4}(?:\s?(?:XT|GRE|XTX))?|QUADRO\s?[A-Z0-9]+|TESLA\s?[A-Z0-9]+|FIREPRO\s?[A-Z0-9]+|"
    r"ARC\s?PRO\s?[A-Z]\d+|ARC\s?[A-Z]\d{2,3})\b",
    re.I,
)
VRAM_RE = re.compile(r"\b(\d{1,2})\s?GB\b")
GMEM_RE = re.compile(r"\bGDDR([567]X?)\b", re.I)

# GPU clocks / TDP / length
CORE_CLOCK_RE = re.compile(r"\b(\d{3,4})\s?MHZ\b", re.I)
BOOST_CLOCK_RE = re.compile(r"\bBOOST\s*[:\-]?\s*(\d{3,4})\s?MHZ\b", re.I)
TDP_RE = re.compile(r"\b(\d{2,4})\s?W\b")
GPU_LENGTH_RE = re.compile(r"\b(\d{2,3})\s?MM\b", re.I)
PCIE_INTERFACE_RE = re.compile(r"PCI\s*E?\s*([345]\.0)?\s*X\s*16", re.I)
SLOT_WIDTH_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*-?SLOT\b", re.I)

WATT_RE = re.compile(r"\b(\d{3,4})\s?W\b")
WATT_PSU_FALLBACK_RE = re.compile(r"\b(\d{3,4})P\b")  # e.g. Ai1300P without W
EFF_RE = re.compile(
    r"80\s?PLUS\s?(TITANIUM|PLATINUM|GOLD|SILVER|BRONZE|WHITE)", re.I
)
CYBENETICS_RE = re.compile(r"CYBENETICS\s*(TITANIUM|PLATINUM|GOLD|SILVER|BRONZE)", re.I)
MOD_RE = re.compile(r"\b(FULL\s?MODULAR|SEMI\s?MODULAR|NON\s?MODULAR|MODULAR)\b", re.I)
LENGTH_MM_RE = re.compile(r"\b(\d{2,3})\s?MM\b", re.I)
FANLESS_RE = re.compile(r"\bFANLESS\b", re.I)

KIT_RE = re.compile(r"\((\d)\s?X\s?(\d{1,3})\s?(?:GB)?\)", re.I)
SPEED_RE = re.compile(r"\b(\d{3,4})\s?MHZ\b", re.I)
SPEED_DDR_RE = re.compile(r"\bDDR[345][-\s]*(\d{3,4})\b", re.I)
CL_RE = re.compile(r"\bCL\s?(\d{1,2})\b", re.I)
VOLTAGE_RE = re.compile(r"\b(\d+\.\d+)\s?V\b", re.I)
TIMING_RE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{1,2}-\d{1,3})\b")
ECC_RE = re.compile(r"\bECC\b", re.I)
REGISTERED_RE = re.compile(r"\b(REG|REGISTERED)\b", re.I)
HEAT_SPREADER_RE = re.compile(r"\b(HEAT\s?SPREADER|HEATSINK)\b", re.I)

SIZE_MM_RE = re.compile(r"\b(80|92|120|140|170|200|240|280|360|420)\s?MM\b", re.I)

# Storage
CAPACITY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\b", re.I)
STORAGE_TYPE_RE = re.compile(r"\b(SSD|HDD|SSHD|NVME)\b", re.I)
FORM_FACTOR_STORAGE_RE = re.compile(r"\b(2\.5[\"'’]*|3\.5[\"'’]*|M\.2\s*22\d{2}|M\.2|U\.2)\b", re.I)
INTERFACE_RE = re.compile(r"\b(SATA|NVME|PCIE|SAS)\b", re.I)
PCIE_GEN_RE = re.compile(r"PCIE\s*GEN\s*([345])(?:\.0)?(?:\s*X\s*4)?", re.I)
CACHE_RE = re.compile(r"\b(\d+)\s?MB\s*(?:CACHE|DRAM)?\b", re.I)
RPM_RE = re.compile(r"\b(\d{3,4})\s?RPM\b", re.I)

COLOR_WORDS = [
    "black", "white", "silver", "gray", "grey", "charcoal",
    "blue", "midnight", "red", "pink", "purple", "brown",
    "gold", "titanium", "green", "yellow", "orange",
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
    m = re.search(r"\b(1700|1851|1200|1151|1150|1155|1366|2066|2011)\b", text)
    if m:
        return NUMERIC_SOCKET.get(m.group(1))
    return None


def _form_factor(text: str) -> str | None:
    for rx, label in FORM_FACTOR_PATTERNS:
        if rx.search(text):
            return label
    return None


def _case_form_factor(text: str) -> str | None:
    for rx, label in CASE_FORM_FACTOR_PATTERNS:
        if rx.search(text):
            return label
    return _form_factor(text)


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
    Labels for Ivory's opaque builder `cuts` IDs, transcribed directly
    from IvoryFindings.md (owner-collected from the site's own filter UI)
    by scraper/build_ivory_cut_labels.py — ground truth, not a statistical
    guess. IvoryFindings.md itself lives in tmp/ (gitignored) and never
    reaches GitHub Actions; only this committed JSON does. Regenerate it
    locally after updating the findings doc; nothing here re-parses it
    at pipeline runtime.
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
        # Normalize: strip trailing letters already captured? group1 is base, group2 optional letter already separated
        # For X570S, group1 captures X570S? Need handle X570S variant
        raw_chip = chipset_m.group(0).upper().replace(" ", "")
        # Clean to chipset base (e.g. B840M -> B840)
        # Remove trailing single letter if it's form-factor suffix (M/I/E)
        # But X570S is valid chipset ending with S, so keep S if chipset is X570S
        if raw_chip not in CHIPSET_INFO and len(raw_chip) > 4 and raw_chip[-1] in "MI":
            raw_chip = raw_chip[:-1]
        a["chipset"] = raw_chip

        # Correct socket/memory from knowledge map using cleaned chipset
        chipset = raw_chip

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
    # If no wifi keyword but chipset board often includes wifi in name, already handled

    lan = LAN_RE.search(text)
    if lan:
        a["lan"] = f"{lan.group(1)}G"

    slots = SLOTS_RE.search(text)
    if slots:
        a["memory_slots"] = int(slots.group(1))

    # Memory max (e.g. 128GB, 256GB)
    mm = MEMORY_MAX_RE.search(text)
    if mm:
        a["memory_max_gb"] = int(mm.group(1))

    m2 = M2_SLOTS_RE.search(text)
    if m2:
        a["m2_slots"] = int(m2.group(1))

    sata_p = SATA_PORTS_RE.search(text)
    if sata_p:
        a["sata_ports"] = int(sata_p.group(1))

    # PCIe x16 slots
    pcie_x16 = re.search(r"\b(\d)\s?X\s?PCIE\s?X?16\b", text, re.I)
    if pcie_x16:
        a["pcie_x16_slots"] = int(pcie_x16.group(1))

    pcie_x1 = re.search(r"\b(\d)\s?X\s?PCIE\s?X?1\b", text, re.I)
    if pcie_x1:
        a["pcie_x1_slots"] = int(pcie_x1.group(1))

    # ECC / Registered
    if ECC_RE.search(text):
        a["ecc_support"] = True

    # Color for motherboards (e.g. White, Black)
    for color in COLOR_WORDS:
        if re.search(rf"\b{color}\b", text, re.I):
            a["color"] = color.title()
            break

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

    # TDP from explicit W near CPU: e.g. 65W, 125W
    tdp = re.search(r"\b(\d{2,3})\s?W\b", text)
    # Heuristic: CPU TDP typical 35-250W; avoid false positives but keep if packaging context
    if tdp:
        val = int(tdp.group(1))
        if 10 <= val <= 300:
            a["tdp"] = f"{val}W"

    m = AMD_CPU_RE.search(text)
    if m:
        a["brand"] = "AMD"
        a["model"] = f"Ryzen {m.group(1)} {m.group(2).upper()}"
    else:
        m = INTEL_CPU_RE.search(text)
        if m:
            a["brand"] = "Intel"
            fam = re.sub(r"\s+", " ", m.group(1).upper())
            # Fix truncation: keep full number (4-5 digits + suffix)
            num = m.group(2).upper().strip()
            a["model"] = f"Core {fam} {num}"
        else:
            m = XEON_RE.search(text)
            if m:
                a["brand"] = "Intel"
                a["model"] = f"Xeon {m.group(1).replace(' ', '')}"

    # Generation + tier, so the UI can offer them as filters the way
    # PCPartPicker does. These are derived from the model number we just
    # extracted.
    brand = a.get("brand")
    model = a.get("model")

    if brand == "AMD":
        tier_m = re.search(r"\bRyzen\s?([3-9])\b", model or "", re.I)
        if tier_m:
            a["tier"] = f"Ryzen {tier_m.group(1)}"
        # AMD "series" = the thousands digit of the 4-digit model (5600X -> 5).
        series_m = re.search(r"\bRyzen\s?[3-9]\s?(\d)\d{3}", model or "", re.I)
        if series_m:
            a["generation"] = f"Ryzen {series_m.group(1)}000"
    elif brand == "Intel":
        if "Xeon" in (model or ""):
            xe_m = re.search(r"\bXeon\s?([A-Z]{1,3})\s?(\d{4})", model or "", re.I)
            if xe_m:
                a["tier"] = f"Xeon {xe_m.group(1).upper()}"
                a["generation"] = f"Xeon Gen {int(xe_m.group(2)[0])}"
        else:
            tier_m = re.search(r"\b(Ultra\s?\d|I[3579])\b", model or "", re.I)
            if tier_m:
                a["tier"] = re.sub(r"\s+", "", tier_m.group(1).upper())
            gen_m = re.search(r"\bI[3579]\s?(\d{4,5})", model or "", re.I)
            if gen_m:
                digits = re.sub(r"[^0-9]", "", gen_m.group(1))
                gen = int(digits[:2]) if len(digits) >= 5 else int(digits[0])
                a["generation"] = f"Gen {gen}"
            else:
                ultra_m = re.search(r"\bUltra\s?\d\s?(\d{3})", model or "", re.I)
                if ultra_m:
                    gen = int(ultra_m.group(1)[:2]) if len(ultra_m.group(1)) >= 3 else int(ultra_m.group(1))
                    a["generation"] = f"Gen {gen}"

    # Integrated graphics detection (Intel UHD / AMD Radeon)
    if re.search(r"\bUHD\s*7[37]0\b", text, re.I):
        m2 = re.search(r"UHD\s*7[37]0", text, re.I)
        if m2:
            a["integrated_graphics"] = m2.group(0).upper()
    elif re.search(r"\bRADEON\b", text, re.I) and "AMD" in a.get("brand", ""):
        a["integrated_graphics"] = "Radeon"

    return a


def _parse_gpu(text: str, meta) -> dict:
    a: dict = {}

    m = GPU_CHIP_RE.search(text)
    if m:
        a["gpu_chip"] = re.sub(r"\s+", " ", m.group(1).upper().strip())
        # Also expose as chipset for PCPP parity
        a["chipset"] = a["gpu_chip"]

    # VRAM: Prefer explicit GB before GDDR, but handle both
    v = VRAM_RE.search(text)
    if v:
        val = int(v.group(1))
        # Heuristic: GPU VRAM typical 2-48 GB, ignore false 100GB etc
        if 1 <= val <= 64:
            a["vram_gb"] = val
            a["memory"] = f"{val} GB"

    g = GMEM_RE.search(text)
    if g:
        a["memory_type"] = f"GDDR{g.group(1).upper()}"
        if "X" in g.group(1).upper():
            a["memory_type"] = a["memory_type"].replace("X", "X")

    # Core / Boost clock
    clocks = CORE_CLOCK_RE.findall(text)
    # Filter clocks typical GPU range 500-3000 MHz
    clocks = [int(c) for c in clocks if 500 <= int(c) <= 3500]
    if clocks:
        # If single, assume boost; if two, core then boost
        if len(clocks) == 1:
            a["boost_clock_mhz"] = clocks[0]
            a["boost_clock"] = f"{clocks[0]} MHz"
        elif len(clocks) >= 2:
            a["core_clock_mhz"] = min(clocks)
            a["boost_clock_mhz"] = max(clocks)
            a["core_clock"] = f"{min(clocks)} MHz"
            a["boost_clock"] = f"{max(clocks)} MHz"
            # PCPP wants core_clock and boost_clock

    # Explicit BOOST label
    bm = BOOST_CLOCK_RE.search(text)
    if bm:
        val = int(bm.group(1))
        if 500 <= val <= 3500:
            a["boost_clock_mhz"] = val
            a["boost_clock"] = f"{val} MHz"

    # TDP
    # Look for W near GPU with context
    tdp_matches = re.finditer(r"\b(\d{2,3})\s?W\b", text, re.I)
    for tm in tdp_matches:
        val = int(tm.group(1))
        # TDP typical 30-600W for GPUs, avoid PSU wattage confusion
        # Only set if not already have wattage_w from PSU context and text contains GPU
        if 15 <= val <= 700:
            # Prefer not to overwrite wattage_w which is PSU; use tdp
            if "tdp" not in a:
                a["tdp"] = f"{val}W"
            break

    # Length in mm (GPUs often 200-400mm)
    lm = GPU_LENGTH_RE.search(text)
    if lm:
        val = int(lm.group(1))
        if 100 <= val <= 500:
            a["length_mm"] = val
            a["length"] = f"{val} mm"

    # Interface
    if PCIE_INTERFACE_RE.search(text):
        a["interface"] = "PCIe x16"
        # Try to capture gen
        gen = re.search(r"PCI\s*E?\s*(\d)\.0", text, re.I)
        if gen:
            a["pcie_gen"] = f"PCIe {gen.group(1)}.0"

    # Slot width
    sw = SLOT_WIDTH_RE.search(text)
    if sw:
        try:
            a["slot_width"] = float(sw.group(1))
            a["total_slot_width"] = a["slot_width"]
        except ValueError:
            pass

    # Cooling type
    if re.search(r"\bLIQUID\b", text, re.I):
        a["cooling"] = "Liquid"
    elif re.search(r"\bPASSIVE\b", text, re.I):
        a["cooling"] = "Passive"
    elif re.search(r"\bAIR\b", text, re.I):
        a["cooling"] = "Air"

    # External power connectors
    power_matches = re.findall(r"(\d+)\s?X\s?(8[-\s]?PIN|6[-\s]?PIN|16[-\s]?PIN|12VHPWR|12V-2X6)", text, re.I)
    if power_matches:
        a["external_power"] = ", ".join(f"{c[0]}x {c[1].upper().replace(' ', '-')}" for c in power_matches)

    # Ports fallback from text
    for port_name, pat in [
        ("hdmi_ports", r"(\d+)\s?X\s?HDMI"),
        ("displayport_ports", r"(\d+)\s?X\s?DISPLAYPORT|(\d+)\s?X\s?DP\b"),
        ("dvi_ports", r"(\d+)\s?X\s?DVI"),
    ]:
        pm = re.search(pat, text, re.I)
        if pm:
            # Find first non-None group
            for g in pm.groups():
                if g:
                    a[port_name] = f"{g}x {port_name.split('_')[0].upper()}"
                    break

    # Fan count
    fan = re.search(r"(\d)\s?X\s?FAN", text, re.I)
    if fan:
        a["fan_count"] = int(fan.group(1))

    return a


def _parse_psu(text: str, meta) -> dict:
    a: dict = {}

    w = WATT_RE.search(text)
    if w:
        val = int(w.group(1))
        if 100 <= val <= 3000:
            a["wattage_w"] = val
            a["wattage"] = f"{val}W"
    else:
        # Fallback for models like Ai1300P without explicit W (common MSI/Asus naming)
        # Only trigger if PSU context present (PSU, Power Supply) to avoid false positives
        if re.search(r"\b(PSU|POWER\s*SUPPLY)\b", text, re.I):
            m = WATT_PSU_FALLBACK_RE.search(text)
            if m:
                val = int(m.group(1))
                if 100 <= val <= 3000:
                    # Check not part of larger model like 100120
                    if val not in (100, 120):
                        a["wattage_w"] = val
                        a["wattage"] = f"{val}W"

    e = EFF_RE.search(text)
    if e:
        a["efficiency"] = e.group(1).upper()
    else:
        cy = CYBENETICS_RE.search(text)
        if cy:
            a["efficiency"] = f"Cybenetics {cy.group(1).title()}"

    m = MOD_RE.search(text)
    if m:
        a["modular"] = re.sub(r"\s+", " ", m.group(1).upper())

    # Length
    # PSU length typical 100-220mm. Reuse generic mm but filter range
    len_match = re.search(r"\b(\d{2,3})\s?MM\b", text, re.I)
    if len_match:
        val = int(len_match.group(1))
        if 100 <= val <= 250:
            a["length_mm"] = val
            a["length"] = f"{val}mm"

    # Fanless
    if FANLESS_RE.search(text):
        a["fanless"] = True
    else:
        # Explicit fan present -> fanless=False could be inferred but keep only True for filter
        pass

    # Form factor / Type: ATX, SFX, SFX-L etc
    if re.search(r"\bSFX[-\s]?L\b", text, re.I):
        a["form_factor"] = "SFX-L"
        a["type"] = "SFX-L"
    elif re.search(r"\bSFX\b", text, re.I):
        a["form_factor"] = "SFX"
        a["type"] = "SFX"
    elif re.search(r"\bATX\b", text, re.I):
        # Could be ATX but not to override existing more specific; default ATX
        if "form_factor" not in a:
            a["form_factor"] = "ATX"
            a["type"] = "ATX"

    # Color
    for color in COLOR_WORDS:
        if re.search(rf"\b{color}\b", text, re.I):
            a["color"] = color.title()
            break

    # Connectors: try to extract SATAs, PCIe etc from title if present
    # Example: "4x SATA", "6x PCIe", "2x EPS"
    sata_m = re.search(r"(\d+)\s?X\s?SATA", text, re.I)
    if sata_m:
        a["sata_connectors"] = int(sata_m.group(1))
    pcie_m = re.search(r"(\d+)\s?X\s?PCIE", text, re.I)
    if pcie_m:
        a["pcie_connectors"] = int(pcie_m.group(1))
        a["pcie_8pin_connectors"] = int(pcie_m.group(1))

    # EPS/ATX 12V connectors
    eps_m = re.search(r"(\d+)\s?X\s?(EPS|CPU|ATX\s*12V)", text, re.I)
    if eps_m:
        a["eps_connectors"] = int(eps_m.group(1))

    # PCIe 12VHPWR / 12V-2x6
    if re.search(r"12VHPWR|12V-2X6", text, re.I):
        a["pcie_16pin_connectors"] = 1
        a["pcie_12vhpwr_connectors"] = 1

    return a


def _parse_memory(text: str, meta) -> dict:
    a: dict = {}

    ddr = _ddr(text)
    if ddr:
        a["memory_type"] = ddr
        a["type"] = ddr  # PCPP alias

    # FIX: use word-boundary search on cleaned text, not compact stripping
    # Avoid sku contamination (e.g. 104968 + 16GB -> 416GB)
    # Search for GB with word boundary
    gb_matches = re.findall(r"\b(\d{1,3})\s?GB\b", text, re.I)
    if gb_matches:
        # Filter to plausible memory sizes (2-256GB total)
        plausible = [int(v) for v in gb_matches if 2 <= int(v) <= 256]
        if plausible:
            # If kit present, total is max plausible or first before kit?
            # Prefer the largest plausible as total (e.g. 32GB (2x16GB) -> both 32 and 16 plausible, max is total)
            # But for "16GB (2x8GB)" both 16 and 8 -> max 16 correct.
            # For single module "8GB" only one.
            total = max(plausible) if len(plausible) > 1 else plausible[0]
            # Cross-check with kit later
            a["total_gb"] = total
            a["capacity_gb"] = total
            a["capacity"] = f"{total}GB"
            a["memory"] = f"{total}GB"

    # Also handle "64G" without B (e.g. Corsair DDR4 64G RAM (16Gx4))
    if "total_gb" not in a:
        g_match = re.search(r"\b(\d{1,3})\s?G\b", text, re.I)
        if g_match:
            val = int(g_match.group(1))
            if 2 <= val <= 256:
                # Check context contains RAM/Memory
                if re.search(r"\b(RAM|MEMORY|DDR)\b", text, re.I):
                    a["total_gb"] = val
                    a["capacity_gb"] = val

    k = KIT_RE.search(text)
    if k:
        try:
            modules = int(k.group(1))
            per = int(k.group(2))
            a["kit"] = f"{modules}x{per}GB"
            a["modules"] = f"{modules}x{per}GB"
            a["module_count"] = modules
            a["module_size_gb"] = per
            # Validate total_gb against kit
            calc_total = modules * per
            if "total_gb" in a and a["total_gb"] != calc_total:
                # Trust kit calculation for total if mismatch due to earlier sku bug (now fixed should be consistent)
                # For "32GB (2x16GB)" both 32, fine. For "16GB (2x8GB)" 16. If title is "64GB (2x32GB)" -> 64.
                # If mismatch, prefer calculated unless calculated is outlier
                if 2 <= calc_total <= 256:
                    a["total_gb"] = calc_total
                    a["capacity_gb"] = calc_total
            elif "total_gb" not in a:
                a["total_gb"] = calc_total
                a["capacity_gb"] = calc_total
        except ValueError:
            pass
    else:
        # Try to infer kit from "2x8GB" without parens or "4x8GB"
        alt_kit = re.search(r"\b(\d)\s?X\s?(\d{1,3})\s?GB\b", text, re.I)
        if alt_kit:
            modules = int(alt_kit.group(1))
            per = int(alt_kit.group(2))
            if 1 <= modules <= 8 and 1 <= per <= 64:
                a["kit"] = f"{modules}x{per}GB"
                a["modules"] = f"{modules}x{per}GB"
                a["module_count"] = modules

    s = SPEED_RE.search(text)
    if s:
        a["speed_mhz"] = int(s.group(1))
        a["speed"] = f"DDR{a.get('memory_type','')[-1] if a.get('memory_type') else ''}-{s.group(1)}" if a.get("memory_type") else f"{s.group(1)}"
    else:
        # Fallback DDR-XXXX without MHz
        sd = SPEED_DDR_RE.search(text)
        if sd:
            a["speed_mhz"] = int(sd.group(1))
            a["speed"] = f"DDR{a.get('memory_type','')[-1] if a.get('memory_type') else ''}-{sd.group(1)}"

    c = CL_RE.search(text)
    if c:
        a["cas_latency"] = int(c.group(1))
        a["cas"] = int(c.group(1))
        # First word latency calc if speed present
        if "speed_mhz" in a:
            try:
                fwl = round((int(c.group(1)) * 2000) / int(a["speed_mhz"]), 3)
                a["first_word_latency_ns"] = fwl
                a["first_word_latency"] = f"{fwl} ns"
            except ZeroDivisionError:
                pass

    # Voltage
    v = VOLTAGE_RE.search(text)
    if v:
        try:
            a["voltage_v"] = float(v.group(1))
            a["voltage"] = f"{v.group(1)}V"
        except ValueError:
            pass

    # Timing
    t = TIMING_RE.search(text)
    if t:
        a["timing"] = t.group(1)
        a["timings"] = t.group(1)

    # ECC / Registered
    if ECC_RE.search(text):
        a["ecc"] = True
        a["ecc_registered"] = "ECC"
    if REGISTERED_RE.search(text):
        a["registered"] = True

    # Heat spreader
    if HEAT_SPREADER_RE.search(text):
        a["heat_spreader"] = True
    elif re.search(r"\bRGB\b|\bARGB\b", text, re.I):
        # RGB often implies heat spreader but not explicit; check vendor_meta lighting?
        pass

    # Form factor for memory (DIMM vs SODIMM)
    if re.search(r"\bSODIMM\b", text, re.I):
        a["form_factor"] = "SODIMM"
    elif re.search(r"\bDIMM\b", text, re.I):
        a["form_factor"] = "DIMM"
        if "form_factor" not in a:
            a["form_factor"] = "DIMM"

    # Color for memory (often Black, White etc)
    for color in COLOR_WORDS:
        if re.search(rf"\b{color}\b", text, re.I):
            # Avoid picking up "Black" as part of model name? Keep first
            a["color"] = color.title()
            break

    return a


def _parse_case(text: str, meta) -> dict:
    a: dict = {}

    # Form factor / Type (ATX Mid Tower etc)
    cf = _case_form_factor(text)
    if cf:
        a["form_factor"] = cf
        a["type"] = cf
    else:
        # Fallback generic ATX etc
        ff = _form_factor(text)
        if ff:
            a["form_factor"] = ff
            a["type"] = ff

    for color in COLOR_WORDS:
        if re.search(rf"\b{color}\b", text, re.I):
            a["color"] = color.title()
            break

    # Side panel
    if re.search(r"TEMPERED\s*GLASS", text, re.I):
        if re.search(r"TINTED", text, re.I):
            a["side_panel"] = "Tinted Tempered Glass"
        else:
            a["side_panel"] = "Tempered Glass"
    elif re.search(r"\bMESH\b", text, re.I):
        a["side_panel"] = "Mesh"
    elif re.search(r"\bACRYLIC\b", text, re.I):
        a["side_panel"] = "Acrylic"

    # PSU included?
    if re.search(r"\bNO.*PSU\b|\bNONE\b.*PSU", text, re.I):
        a["power_supply"] = "None"
        a["psu_included"] = False
    elif re.search(r"\bWITH\s*PSU\b|\bPSU\s*INCLUDED\b", text, re.I):
        a["psu_included"] = True

    # Volume / dimensions
    vol = re.search(r"(\d+(?:\.\d+)?)\s?L\b", text, re.I)
    if vol:
        try:
            a["external_volume_l"] = float(vol.group(1))
            a["external_volume"] = f"{vol.group(1)}L"
        except ValueError:
            pass

    # Drive bays
    bays_35 = re.search(r"(\d+)\s?X\s?3\.5", text, re.I)
    if bays_35:
        a["internal_35_bays"] = int(bays_35.group(1))
    bays_25 = re.search(r"(\d+)\s?X\s?2\.5", text, re.I)
    if bays_25:
        a["internal_25_bays"] = int(bays_25.group(1))

    # Expansion slots
    slots = re.search(r"(\d+)\s?X?\s?EXPANSION\s*SLOT", text, re.I)
    if slots:
        a["full_height_expansion_slots"] = int(slots.group(1))

    # Max GPU length
    max_gpu = re.search(r"(\d{2,3})\s?MM.*GPU|GPU.*(\d{2,3})\s?MM", text, re.I)
    if max_gpu:
        # Find first group that is digits
        for g in max_gpu.groups():
            if g and g.isdigit():
                val = int(g)
                if 150 <= val <= 500:
                    a["max_gpu_length_mm"] = val
                    a["maximum_video_card_length"] = f"{val}mm"
                    break

    # Supported radiator sizes (for case)
    rad = SIZE_MM_RE.search(text)
    if rad:
        a["supported_radiator_mm"] = int(rad.group(1))

    return a


def _parse_storage(text: str, meta) -> dict:
    a: dict = {}

    # Capacity: handle TB and GB, pick largest plausible (storage up to 30TB)
    caps = CAPACITY_RE.findall(text)
    # CAPACITY_RE groups: [ (number, unit), ...]
    gb_vals = []
    for num_str, unit in caps:
        try:
            num = float(num_str)
            gb = int(num * 1000) if unit.upper() == "TB" else int(num)
            # Filter plausible storage capacities 100GB - 30000GB
            if 80 <= gb <= 30000:
                gb_vals.append(gb)
        except ValueError:
            continue
    if gb_vals:
        # Prefer maximum (e.g. "8TB (8000GB)" -> both 8000, ok)
        # But for titles with multiple capacities like specs listReads, nuance?
        # Use max as capacity
        cap = max(gb_vals)
        a["capacity_gb"] = cap
        a["capacity"] = f"{cap}GB" if cap < 1000 else f"{cap//1000}TB"
        # Also expose as total_gb for pcpp-like capacity filter
        a["total_gb"] = cap

    # Type: SSD vs HDD distinction
    if re.search(r"\bSSD\b", text, re.I):
        a["type"] = "SSD"
        a["drive_type"] = "SSD"
        # NVMe flag
        if re.search(r"\bNVME\b", text, re.I):
            a["nvme"] = True
            a["nvme_flag"] = "Yes"
        else:
            a["nvme"] = False
            a["nvme_flag"] = "No"
    elif re.search(r"\bHDD\b", text, re.I):
        a["type"] = "HDD"
        a["drive_type"] = "HDD"
        a["nvme"] = False
    elif re.search(r"\bSSHD\b", text, re.I):
        a["type"] = "SSHD"

    # Form factor
    ff = FORM_FACTOR_STORAGE_RE.search(text)
    if ff:
        raw = ff.group(1).upper().replace(" ", "")
        if "M.2" in raw or "M2" in raw:
            # Try to get size 2280 etc
            m2size = re.search(r"M\.?2\s*22\d{2}", text, re.I)
            if m2size:
                cleaned = re.sub(r"\s+", " ", m2size.group(0).upper().strip())
                a["form_factor"] = cleaned
                a["drive_form_factor"] = cleaned
            else:
                a["form_factor"] = "M.2"
                a["drive_form_factor"] = "M.2"
        elif "2.5" in raw:
            a["form_factor"] = "2.5\""
            a["drive_form_factor"] = "2.5-inch"
        elif "3.5" in raw:
            a["form_factor"] = "3.5\""
            a["drive_form_factor"] = "3.5-inch"

    # Interface
    # Distinguish NVMe vs SATA
    if re.search(r"\bNVME\b", text, re.I):
        a["interface"] = "M.2 PCIe NVMe" if "M.2" in text else "NVMe"
        # Heuristic for PCIe interface version
        pcie_gen = PCIE_GEN_RE.search(text)
        if pcie_gen:
            a["pcie_gen"] = f"PCIe Gen {pcie_gen.group(1)}.0"
            a["interface"] = f"M.2 PCIe {pcie_gen.group(1)}.0 X4"
    elif re.search(r"\bSATA\b", text, re.I):
        a["interface"] = "SATA 6.0 Gb/s" if "6" in text else "SATA"
    elif re.search(r"\bSAS\b", text, re.I):
        a["interface"] = "SAS"
    elif re.search(r"\bPCI\s*E\b", text, re.I):
        a["interface"] = "PCIe"

    # PCIe Gen explicit
    if "pcie_gen" not in a:
        pg = PCIE_GEN_RE.search(text)
        if pg:
            a["pcie_gen"] = f"PCIe Gen {pg.group(1)}.0"

    # Cache
    cache = CACHE_RE.search(text)
    if cache:
        try:
            val = int(cache.group(1))
            if 8 <= val <= 8192:
                a["cache_mb"] = val
                a["cache"] = f"{val}MB"
        except ValueError:
            pass

    # RPM for HDD
    rpm = RPM_RE.search(text)
    if rpm:
        try:
            val = int(rpm.group(1))
            if 3000 <= val <= 15000:
                a["rpm"] = val
                a["spindle_speed"] = f"{val} RPM"
        except ValueError:
            pass
    else:
        # Try bare 7200/5400 near HDD
        if re.search(r"\bHDD\b", text, re.I):
            bare = re.search(r"\b(5400|7200|10000|15000)\b", text)
            if bare:
                a["rpm"] = int(bare.group(1))

    # Price per GB will be computed downstream after price known, but prepare field
    # NVMe boolean already set

    return a


def _parse_fan_or_aio(text: str, meta) -> dict:
    a: dict = {}

    s = SIZE_MM_RE.search(text)
    if s:
        a["size_mm"] = int(s.group(1))
        a["fan_size_mm"] = int(s.group(1))
        a["radiator_size_mm"] = int(s.group(1))

    if re.search(r"\bARGB\b", text, re.I):
        a["argb"] = True
        a["lighting"] = "ARGB"
    elif re.search(r"\bRGB\b", text, re.I):
        a["rgb"] = True
        a["lighting"] = "RGB"

    if re.search(r"\bPWM\b", text, re.I):
        a["pwm"] = True

    # RPM for fans
    rpm = RPM_RE.search(text)
    if rpm:
        a["rpm"] = int(rpm.group(1))

    # Noise level
    noise = re.search(r"(\d+(?:\.\d+)?)\s?dB", text, re.I)
    if noise:
        a["noise_level"] = f"{noise.group(1)} dB"

    # Airflow
    airflow = re.search(r"(\d+(?:\.\d+)?)\s?CFM", text, re.I)
    if airflow:
        a["airflow"] = f"{airflow.group(1)} CFM"

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
    "storage": _parse_storage,
    "cooler": _parse_fan_or_aio,
    "cooling_other": _parse_fan_or_aio,
}


# --------------------------------------------------------------------------
# Plonter `tree` field — static ID->attribute table
# --------------------------------------------------------------------------
# Transcribed directly from PlonterFindings.md's "ID Prefixes and Meanings"
# tables. Unlike Ivory's opaque numeric `cuts`, Plonter's tree IDs are
# already human-readable prefixes, so no learning/bootstrapping step is
# needed — this table is the whole story. Only compatibility-relevant
# categories are covered (CPU/board/memory/storage/cooling/case/PSU/GPU);
# peripheral/networking/software IDs are skipped since ALLOWED_ENGDIVISIONS
# in plonter.py already filters those rows out before they reach here.
PLONTER_TREE_LABELS: dict[str, dict] = {
    # CPU sockets
    "ACAM4": {"socket": "AM4", "brand": "AMD"},
    "ACAM5": {"socket": "AM5", "brand": "AMD"},
    "AC1700": {"socket": "LGA1700", "brand": "Intel"},
    "AC1851": {"socket": "LGA1851", "brand": "Intel"},
    "ACsTR5": {"socket": "sTR5", "brand": "AMD"},
    "AC4677": {"socket": "LGA4677", "brand": "Intel"},
    "AC3647": {"socket": "LGA3647", "brand": "Intel"},
    "ACSP3": {"socket": "SP3", "brand": "AMD"},
    "ACSP5": {"socket": "SP5", "brand": "AMD"},
    # Motherboards
    "BAM4BOARD": {"socket": "AM4", "brand": "AMD"},
    "BAM5BOARD": {"socket": "AM5", "brand": "AMD"},
    "B1700D5ATX": {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "ATX"},
    "B1700D4ATX": {"socket": "LGA1700", "memory_type": "DDR4", "form_factor": "ATX"},
    "B1700D5ITX": {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "Mini-ITX"},
    "B1700D4ITX": {"socket": "LGA1700", "memory_type": "DDR4", "form_factor": "Mini-ITX"},
    "B1851ATX": {"socket": "LGA1851", "form_factor": "ATX"},
    "B1851MATX": {"socket": "LGA1851", "form_factor": "mATX"},
    "B1851ITX": {"socket": "LGA1851", "form_factor": "Mini-ITX"},
    "BsTR5BOARD": {"socket": "sTR5", "brand": "AMD"},
    "B4677ATX": {"socket": "LGA4677", "form_factor": "ATX"},
    "BSP3BOARD": {"socket": "SP3", "brand": "AMD"},
    "BSP5BOARD": {"socket": "SP5", "brand": "AMD"},
    "B1151v2ATX": {"socket": "LGA1151", "form_factor": "ATX"},
    "B11514ATX": {"socket": "LGA1151", "form_factor": "ATX"},
    "B1200ATX": {"socket": "LGA1200", "form_factor": "ATX"},
    "B20113ATX": {"socket": "LGA2011-v3", "form_factor": "ATX"},
    # Memory
    "CDDR5D": {"memory_type": "DDR5"},
    "CDDR5DRDECC": {"memory_type": "DDR5", "ecc": True, "registered": True},
    "DDR5SODIM": {"memory_type": "DDR5", "form_factor": "SODIMM"},
    "CDDR4D": {"memory_type": "DDR4"},
    "CDDR4LRDIMM": {"memory_type": "DDR4", "ecc": True, "registered": True},
    "DDR4SODIM": {"memory_type": "DDR4", "form_factor": "SODIMM"},
    "CDDR3D": {"memory_type": "DDR3"},
    "CDDR3LD": {"memory_type": "DDR3L"},
    "3DDR3L": {"memory_type": "DDR3L", "form_factor": "SODIMM"},
    # Storage
    "CHDD35": {"drive_form_factor": "3.5-inch"},
    "CHDD35NAS": {"drive_form_factor": "3.5-inch", "drive_use_case": "NAS"},
    "CHDD25": {"drive_form_factor": "2.5-inch"},
    "SATA": {"interface": "SATA"},
    "SAS": {"interface": "SAS"},
    "DSSDM2NVMe": {"drive_form_factor": "M.2", "interface": "NVMe"},
    "DSSDM2SATA": {"drive_form_factor": "M.2", "interface": "SATA"},
    "DSSD25": {"drive_form_factor": "2.5-inch", "interface": "SATA"},
    "DSSENTD25": {"drive_form_factor": "2.5-inch", "drive_use_case": "Enterprise"},
    # Cooling — socket compatibility + radiator size
    "ZFANAM4": {"socket_compat": "AM4"},
    "ZFAN1700": {"socket_compat": "LGA1700"},
    "ZFANTR4": {"socket_compat": "TR4"},
    "ZFANS4677": {"socket_compat": "LGA4677"},
    "ZFANSP3": {"socket_compat": "SP3"},
    "120mm": {"radiator_size_mm": 120},
    "240mm": {"radiator_size_mm": 240},
    "280mm": {"radiator_size_mm": 280},
    "360mm": {"radiator_size_mm": 360},
    "420mm": {"radiator_size_mm": 420},
    # Power supply
    "EATXPSU": {"form_factor": "ATX"},
    "ESFXPSU": {"form_factor": "SFX"},
    # Case
    "EATXC": {"form_factor": "ATX"},
    "EITXC": {"form_factor": "Mini-ITX"},
    "EHTPC": {"form_factor": "HTPC"},
    "MINISTX": {"form_factor": "Mini-STX"},
}

# A few documented tree values are multi-word ("AMD Radeon", "NVIDIA
# GeForce") and wouldn't survive a plain whitespace split reliably — matched
# separately as a substring pass over the raw tree string.
PLONTER_TREE_SUBSTRING_LABELS: dict[str, dict] = {
    "AMD Radeon": {"gpu_vendor": "AMD Radeon"},
    "NVIDIA GeForce": {"gpu_vendor": "NVIDIA GeForce"},
    "Intel ARC": {"gpu_vendor": "Intel ARC"},
    "Tesla": {"gpu_vendor": "NVIDIA Tesla"},
}


def _parse_plonter_tree(tree_raw) -> dict:
    a: dict = {}
    if not isinstance(tree_raw, str) or not tree_raw.strip():
        return a

    for token in tree_raw.split():
        for k, v in PLONTER_TREE_LABELS.get(token, {}).items():
            a.setdefault(k, v)

    for marker, attrs in PLONTER_TREE_SUBSTRING_LABELS.items():
        if marker in tree_raw:
            for k, v in attrs.items():
                a.setdefault(k, v)

    return a


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

    # Plonter's `tree` field, when present (static table, see above).
    for k, v in _parse_plonter_tree(meta.get("tree")).items():
        attrs.setdefault(k, v)

    # Hebrew description facts (mostly CPUs).
    raw_desc = meta.get("description")
    if isinstance(raw_desc, str) and raw_desc:
        for k, v in _parse_hebrew_description(raw_desc).items():
            attrs.setdefault(k, v)

    # Structural builder data is used only to decode Ivory's filter cuts.
    # Do not expose opaque IDs or internal parent IDs as product specs.
    cuts = meta.get("cuts")
    cut_ids = [int(c) for c in cuts if str(c).isdigit()] if isinstance(cuts, list) else []

    # Decode opaque Ivory `cuts` IDs via the static ground-truth table.
    # (No parent->category lookup needed: category_guess from the spider
    # already gives category_normalized deterministically — see ivory.py's
    # CATEGORIES table, one source_parent per category.)
    labels = _load_cut_labels()
    if labels:
        for cut in cut_ids:
            for k, v in (labels.get("cuts", {}).get(str(cut)) or {}).items():
                attrs.setdefault(k, v)

    # Post-process: ensure aliases for PCPP parity
    # Normalize wattage aliases
    if "wattage_w" in attrs and "wattage" not in attrs:
        attrs["wattage"] = f"{attrs['wattage_w']}W"
    if "capacity_gb" in attrs and "capacity" not in attrs:
        cap = attrs["capacity_gb"]
        attrs["capacity"] = f"{cap}GB" if cap < 1000 else f"{cap//1000}TB"

    # GPU memory alias
    if "vram_gb" in attrs and "memory" not in attrs:
        attrs["memory"] = f"{attrs['vram_gb']} GB"
    # Ensure chipset alias for GPU (gpu_chip -> chipset for filter parity)
    if "gpu_chip" in attrs and "chipset" not in attrs:
        attrs["chipset"] = attrs["gpu_chip"]

    # Price per GB for storage (if price available on listing, compute here? listing price may be missing at this stage)
    # Will be enriched later in matching if price present.

    return attrs
