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
    # Same 1PC JSON-bleed guard as matching._clean (keep in sync).
    s = s.split('",')[0]
    # Trademark symbols MUST go before NFKC: NFKC folds ™->TM / ®->R,
    # gluing them onto the previous word ("Ryzen™" -> "RYZENTM") and
    # breaking every \b-anchored model regex after it.
    s = re.sub(r"[®™©℗]", " ", s)
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

DDR_RE = re.compile(r"\bDDR\s?([345]L?)\b", re.I)
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

AMD_RYZEN_RE = re.compile(r"\bRYZEN\s?(\d)\s?(?:(PRO)\s?)?(\d{4}[A-Z0-9]*)", re.I)
AMD_THREADRIPPER_RE = re.compile(r"\bTHREADRIPPER\s?(PRO\s?)?(\d{4}[A-Z0-9]*)", re.I)
# Pre-Ryzen AMD lines still show up in vendor feeds (A-series APUs, FX,
# Athlon). These never had brand/model extracted before, which is why
# cross-vendor listings of the same chip never reached the CPU model-merge
# tier in matching.py (Aug 2026 fix — see decisions.md).
AMD_APU_RE = re.compile(r"\bA(4|6|8|9|10|12)\s?-?\s?(\d{4}[A-Z]{0,2})\b", re.I)
AMD_FX_RE = re.compile(r"\bFX\s?-?\s?(\d{4}[A-Z]?)\b", re.I)
AMD_ATHLON_RE = re.compile(r"\bATHLON\s?(?:64\s?)?(X\d)?\s?-?\s?(\d{3,4}[A-Z]{0,2})\b", re.I)
# Budget Intel lines (Celeron G6900, Pentium Gold G7400) — no "Core" in the
# name, so INTEL_CPU_RE never fires and these fell back to raw titles.
# TMS writes the core-count infix ("Pentium Dual Core G4400").
INTEL_CELERON_RE = re.compile(r"\bCELERON\s?(?:DUAL\s?CORE\s?)?([A-Z]?\d{3,4}[A-Z]{0,2})\b", re.I)
INTEL_PENTIUM_RE = re.compile(r"\bPENTIUM\s?(?:GOLD\s?|SILVER\s?|DUAL\s?CORE\s?)?([A-Z]?\d{3,4}[A-Z]{0,2})\b", re.I)
INTEL_CPU_RE = re.compile(
    r"\b(?:CORE\s?)?(ULTRA\s?\d|I\d)[\s-]?(\d{3,5}[A-Z]{0,4}(?:\s?PLUS)?)", re.I
)
XEON_RE = re.compile(
    r"\bXEON\s?(?:(SILVER|BRONZE|GOLD|PLATINUM|W\d?|E\d?)\s?-?\s?)?(\d{3,5}[A-Z]{0,2})\b", re.I)
# First-gen EPYC naming ("Naples 7551P") — codename + number, no EPYC word.
AMD_EPYC_CODENAME_RE = re.compile(r"\b(NAPLES|ROME|MILAN|GENOA)\s?(\d{4}[A-Z]?)\b", re.I)
# Server AMD: "EPYC 7763", "EPYC 4th Gen 9454". The "Nth Gen" prefix is
# skipped here (parsed separately for the generation filter below).
# A trailing "Series" is also skipped ("EPYC 9004 Series" names the lineup,
# not the chip — matching it merged 18 different SKUs into one product).
# The Gen prefix tolerates a codename paren ("4th Gen (Zen4) 9354").
EPYC_RE = re.compile(
    r"\bEPYC\s?(?:\d+(?:TH|ST|ND|RD)\s?GEN\s?(?:\([^)]*\)\s?)?)?"
    r"(\d{3,4}[A-Z]{0,2})(?!\s*Series\b)", re.I)

# Expanded GPU chip: covers GeForce RTX (incl. xx50 Ti, xx60 Ti), RTX PRO/A-series,
# Radeon RX (inc. GRE), Quadro, Tesla, ARC — plus legacy GT/GTS/GTX and
# Radeon HD/R5/R7 lines still sold as budget cards (GT 710/610, HD 5450…).
# The legacy alternation requires a 3-4 digit number so plain words never match.
GPU_CHIP_RE = re.compile(
    r"\b(GEFORCE\s?RTX\s?\d{3,4}(?:\s?(?:TI|SUPER))?|"
    r"RTX\s?PRO\s?\d{3,4}[A-Z]?|RTX\s*A\d{3,4}|RTX\s?\d{3,4}(?:\s?(?:TI|SUPER))?|"
    r"RX\s?\d{3,4}(?:\s?(?:XT|GRE|XTX))?|QUADRO\s?[A-Z0-9]+|TESLA\s?[A-Z0-9]+|FIREPRO\s?[A-Z0-9]+|"
    r"ARC\s?PRO\s?[A-Z]\d+|ARC\s?[A-Z]\d{2,3}|"
    r"GEFORCE\s?GTX?\s?\d{3,4}(?:\s?TI)?|GTX?\s?\d{3,4}(?:\s?TI)?|GTS?\s?\d{3,4}|"
    r"RADEON\s?(?:HD\s?)?\d{3,4}|R[579]\s?\d{3})\b",
    re.I,
)
# GPU board partners, longest-first so "ZOTAC GAMING" hits before bare words.
GPU_BRANDS = {
    "asus": "ASUS", "gigabyte": "Gigabyte", "aorus": "Gigabyte",
    "msi": "MSI", "inno3d": "Inno3D", "inno3": "Inno3D",
    "arktek": "ARKTEK", "zotac": "ZOTAC", "pny": "PNY",
    "sapphire": "Sapphire", "xfx": "XFX", "asrock": "ASRock",
    "palit": "Palit", "gainward": "Gainward", "evga": "EVGA",
    "galax": "GALAX", "kfa2": "KFA2", "leadtek": "Leadtek",
    "maxsun": "Maxsun", "colorful": "Colorful",
    "powercolor": "PowerColor", "nvidia": "NVIDIA",
}

# Memory brands incl. sub-lines, for canonical memory names.
MEMORY_BRANDS = {
    "g.skill": "G.Skill", "gskill": "G.Skill", "ripjaws": "G.Skill",
    "trident": "G.Skill", "flare": "G.Skill",
    "corsair": "Corsair", "vengeance": "Corsair",
    "kingston": "Kingston", "fury": "Kingston", "beast": "Kingston",
    "hyperx": "Kingston",
    "samsung": "Samsung", "crucial": "Crucial", "ballistix": "Crucial",
    "micron": "Crucial", "adata": "ADATA", "xpg": "ADATA",
    "teamgroup": "TeamGroup", "t-force": "TeamGroup", "tforce": "TeamGroup",
    "delta": "TeamGroup",
    "silicon power": "Silicon Power", "siliconpower": "Silicon Power",
    "patriot": "Patriot", "viper": "Patriot",
    "sk hynix": "SK Hynix", "hynix": "SK Hynix",
    "klevv": "Klevv", "apacer": "Apacer", "transcend": "Transcend",
    "pny": "PNY", "oscoo": "OSCOO", "gloway": "Gloway",
    "thermaltake": "Thermaltake", "timetec": "Timetec",
    "lexar": "Lexar", "geil": "GeIL",
    "v-color": "V-Color", "vcolor": "V-Color",
}

VRAM_RE = re.compile(r"\b(\d{1,2})\s?G(?:B)?\b")
GMEM_RE = re.compile(r"\bS?DDR([345]X?)\b|\bGDDR([567]X?)\b|\bHBM(\d?)\b", re.I)

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
# Vendors write DDR5 speeds either way ("6000MHz", "6000MT/s").
# NOTE: no \b between the digits and the unit — "3200MT/s" has none
# (both word chars), so the unit alternation must abut the digits.
SPEED_RE = re.compile(r"\b(\d{3,4})\s?(?:MHZ|MT/S)\b", re.I)
SPEED_DDR_RE = re.compile(r"\bDDR[345]L?[-\s]*(\d{3,4})\b", re.I)
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
CACHE_RE = re.compile(r"\b(\d+)\s?MB\s*(?:CACHE|DRAM)?\b(?!/s)", re.I)
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
    return f"DDR{m.group(1).upper()}" if m else None


def _ddr_gen(memory_type) -> str:
    """Generation digit for DDR speed strings ('DDR3L' -> '3')."""
    m = re.search(r"[345]", str(memory_type or ""))
    return m.group(0) if m else ""


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
# Detail-spec sanitization — drops the garbage rows users kept seeing
# (mojibake Hebrew, empty keys, nav-breadcrumb junk) and aliases vendor
# spec keys to the canonical attribute names the filters/site expect.
#
# Background on each rule:
# - Mojibake (GERESH runs / U+FFFD): Plonter detail pages arrive via
#   Playwright as decoded Unicode; an old response.replace(encoding=
#   "windows-1255") re-interpreted the UTF-8 bytes and garbled every
#   Hebrew string ('יצרן' -> '׳™׳¦׳¨׳�'). Fixed at the spider, but the
#   already-scraped data/raw/detail/plonter.jsonl is still poisoned, so
#   tainted rows are dropped here — a catalog rebuild stays clean even
#   before a full re-scrape.
# - Empty normalized keys: Ivory's Hebrew labels ('מותג') and Plonter's
#   Hebrew header cells both normalize to '' and used to collapse into a
#   single garbage '' attribute. Ivory labels are translated first
#   (IVORY_HEBREW_LABELS); anything still empty is dropped.
# - Hebrew-only keys from non-Ivory vendors: Plonter's footer nav tables
#   ("... קונים בפלונטר") leaked keys like `amd_socket_am4` with Hebrew
#   values. Real Plonter spec keys are always English, so Hebrew keys
#   from other vendors are nav junk. (Fixed at the spider too via the
#   tr[onmouseover] selector; this is the backstop for old scrapes.)
# - Blacklisted keys: vendor boilerplate and server trivia nobody filters
#   on (segment, scalability, remote-management, NAME/SKU dupes of the
#   title and vendor_sku we already store).
# - Noise values: "not available" / "n/a" / "-" placeholder cells.
# --------------------------------------------------------------------------

_GERESH = "\u05f3"  # Hebrew punctuation geresh — mojibake hallmark
_REPLACEMENT_CHAR = "\ufffd"
_HEBREW_CHAR_RE = re.compile(r"[\u0590-\u05FF]")
_LATIN_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_PAREN_HINT_RE = re.compile(r"\(([^)]+)\)")
_NUMERIC_HEBREW_VALUE_RE = re.compile(r"^\s*([\d.,]+)\s*[\u0590-\u05FF\s]+$")

# Normalized detail keys that are never real specs.
DETAIL_KEY_BLACKLIST = frozenset({
    "name",               # 1PC packed-cell dupe of the product title
    "sku",                # dupe of vendor_sku (real MPN lives in `mpn`)
    "segment",            # "desktop (Mainstream)" — trivia, explicitly unwanted
    "scalability",        # "1 socket" — server trivia
    "remote_management",  # "no" on every desktop CPU — noise
    "remote_manageability",
    "type",               # redundant shadow of memory_type / form_factor /
                          # drive_type ("DDR5", "ATX", "SSD") under a
                          # meaningless key name
    "not_available",      # 1PC packed-cell artifact: bare label became a key
})
# NOTE: folded dupe keys (cas/colour/capacitygb/...) are NOT blacklisted —
# _sanitize_detail_pair lets them through and the post-process in
# extract_attributes folds them into their canonical target, so detail
# values like "CAS-Latency CL: 11" still land on cas_latency.

# Placeholder cell values — the vendor explicitly says "no data".
DETAIL_NOISE_VALUES = frozenset({
    "not available", "n/a", "na", "none", "-", "--", "—", "...",
    "no info", "no information", "unknown",
})

# Normalized Plonter/1PC detail key -> canonical attribute key.
# (Most vendor keys already normalize to the canonical name; only the
# mismatches live here.)
DETAIL_KEY_ALIASES = {
    "manufacturer": "brand",
    "product_type": "product_type",
    "model_number": "mpn",
    "memory_support": "memory_type",
    "format": "form_factor",
    "cpu_model": "chipset",
    "cpu_frequency": "boost_clock_ghz",
    "internal_memory_capacity": "max_memory",
    "usb_connections": "usb_ports",
    "sata_connections": "sata_ports",
    "connectivity": "connectivity",
    "graphics_cards": "expansion_slots",
    "base_clock": "base_clock_ghz",
    "turbo_clock": "boost_clock_ghz",
    "boost_clock": "boost_clock_ghz",
    "max_boost_clock": "boost_clock_ghz",
    "max_turbo_clock": "boost_clock_ghz",
    "architecture": "microarchitecture",
    "lithography": "manufacturing_process",
    "manufacturing_technology": "manufacturing_process",
    "process": "manufacturing_process",
}

# Yes/No canonicalization for boolean-ish spec keys. Vendors disagree on
# representation ('yes' vs True vs 'true'); without this the filter rail
# shows both "True" and "yes" as separate options for the same thing.
YES_NO_KEYS = frozenset({
    "smt", "ecc", "ecc_support", "unlocked", "cooler_included",
    "registered", "nvme", "nvme_flag", "heat_spreader",
    "integrated_graphics", "graphics",
    "rgb", "argb", "pwm", "wireless", "fanless",
})

_YES_VALUES = frozenset({"yes", "y", "true", "1", "included", "with", "ja"})
_NO_VALUES = frozenset({"no", "n", "false", "0", "not included", "without", "nein"})


def _is_mojibake_text(s) -> bool:
    t = str(s)
    return _GERESH in t or _REPLACEMENT_CHAR in t


def _has_hebrew(s) -> bool:
    return bool(_HEBREW_CHAR_RE.search(str(s)))


def _has_latin_alnum(s) -> bool:
    return bool(_LATIN_ALNUM_RE.search(str(s)))


# Ivory detail labels are Hebrew, usually with an English hint in parens
# ("Cores" etc.). The hint is the primary key source; the small map below
# covers the hint-less labels seen on real pages. Unknown Hebrew labels
# return None (dropped) -- an untranslated label would normalize to ''
# and collide with every other untranslated label in one garbage key.
# (Hebrew literals below are \u-escaped so no raw Hebrew lands in source.)
IVORY_HEBREW_LABELS = {
    "\u05de\u05d5\u05ea\u05d2": "brand",
    "\u05d3\u05d2\u05dd": "model",
    "\u05d0\u05e8\u05d9\u05d6\u05d4": "packaging",
}

# Normalized English paren-hint -> canonical key. "clock_range" is special:
# values like "3.6GHz - 4GHz" are split into base/boost clocks. None means
# "drop this row" (e.g. warranty -- not a spec anyone filters on).
IVORY_HINT_ALIASES = {
    "cores": "cores",
    "threads": "threads",
    "clock": "clock_range",
    "cache": "cache_mb",
    "socket": "socket",
    "brand": "brand",
    "model": "model",
    "packing": "packaging",
    "packaging": "packaging",
    "chipset": "chipset",
    "memory": "memory",
    "speed": "speed_mhz",
    "warranty": None,
}


def _ivory_label_to_key(label: str):
    """Translate one Ivory detail label to a canonical attribute key."""
    t = str(label).strip()
    hint_m = _PAREN_HINT_RE.search(t)
    if hint_m:
        hint = _norm_key_name(hint_m.group(1))
        if not hint:
            return None
        if hint in IVORY_HINT_ALIASES:
            return IVORY_HINT_ALIASES[hint]
        return hint
    base = re.sub(r"\s*\(.*?\)\s*", "", t).strip()
    if base in IVORY_HEBREW_LABELS:
        return IVORY_HEBREW_LABELS[base]
    return None


def _canonicalize_yes_no(key: str, value):
    """Map True/'true'/'yes' -> 'Yes', False/'false'/'no' -> 'No' for the
    boolean-ish keys in YES_NO_KEYS. Returns the (possibly unchanged) value."""
    if key not in YES_NO_KEYS:
        return value
    if isinstance(value, bool):
        return "Yes" if value else "No"
    low = str(value).strip().lower()
    # Detail rows qualify their answer ("yes (Intel Hyper-Threading)",
    # "No, not included") — decide on the leading word.
    m = re.match(r"^(yes|no|true|false)\b", low)
    if m:
        low = m.group(1)
    if low in _YES_VALUES:
        return "Yes"
    if low in _NO_VALUES:
        return "No"
    return value


def _clean_detail_value(value):
    """Strip Hebrew suffix words off numeric values ('4 XXXX' -> '4')."""
    if isinstance(value, bool):
        return value
    s = str(value).strip()
    m = _NUMERIC_HEBREW_VALUE_RE.match(s)
    if m:
        return m.group(1).replace(",", "")
    return s


def _parse_overview_fields(value: str) -> dict[str, str]:
    """Split 1PC's comma-packed English overview into label/value fields."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    parts = re.split(r",\s+(?=[A-Za-z][A-Za-z0-9 /()-]{1,48}:)", text)
    out = {}
    for part in parts:
        match = re.match(r"^\s*([^:]{2,48}):\s*(.+?)\s*$", part)
        if not match:
            continue
        label, field_value = match.groups()
        field_value = field_value.strip(" ,")
        if label.strip() and field_value:
            out[label.strip()] = field_value
    return out


def _sanitize_detail_pair(raw_key, raw_value, vendor=None):
    """Validate + canonicalize one detail-spec row.

    Returns (key, value) ready for the attributes blob, or None to drop
    the row. Ivory rows go through Hebrew-label translation; every other
    vendor's keys must already be usable English.
    """
    if raw_value in (None, "", [], {}):
        return None
    if isinstance(raw_value, str) and raw_value.strip().lower() in DETAIL_NOISE_VALUES:
        return None
    if _is_mojibake_text(raw_key) or _is_mojibake_text(raw_value):
        return None

    v = _clean_detail_value(raw_value)
    if isinstance(v, str) and not v.strip():
        return None

    norm_vendor = "onepc" if vendor in ("1pc", "onepc") else (vendor or "")

    if norm_vendor == "ivory":
        key = _ivory_label_to_key(raw_key)
        if not key:
            return None
    else:
        if _has_hebrew(raw_key):
            return None
        key = _norm_key_name(raw_key)
        if not key:
            return None
        if key in DETAIL_KEY_BLACKLIST:
            return None
        key = DETAIL_KEY_ALIASES.get(key, key)

    if isinstance(v, str):
        vs = v.strip()
        # Hebrew-only values are nav breadcrumbs, not specs.
        if _has_hebrew(vs) and not _has_latin_alnum(vs):
            return None
        if not vs or vs.lower() in DETAIL_NOISE_VALUES:
            return None
        v = vs

    # Socket values like "AMD AM4" collapse to the canonical "AM4" so they
    # merge with the tree/title-derived socket instead of conflicting.
    if key == "socket" and isinstance(v, str):
        short = _socket_from_text(v)
        if short:
            v = short

    # Pure-digit core/thread counts become ints for consistent merging.
    if key in ("cores", "threads") and isinstance(v, str) and v.isdigit():
        v = int(v)

    v = _canonicalize_yes_no(key, v)
    return key, v


def _split_clock_range(value: str):
    """'3.6GHz - 4GHz' -> (3.6, 4.0). Returns None when not a range."""
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*ghz\s*-\s*(\d+(?:\.\d+)?)\s*ghz?",
        str(value),
        re.I,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


# --------------------------------------------------------------------------
# vendor_meta harvesting (Ivory builder payload etc.)
# --------------------------------------------------------------------------

_META_SCALAR_KEYS = {
    "socket", "chipset", "form_factor", "memory_type", "wifi", "wattage_w",
    "efficiency", "vram_gb", "platform", "co_dependant",
    "build_computer_global_categories_id",
}


def _from_vendor_meta(meta, vendor=None) -> dict:
    """
    Defensive harvester for structured vendor specs.

    Accepts either flat keys (socket=..., chipset=...) or nested
    name/value spec blocks (specs / features / compatibility / data).
    Detail-page specs additionally pass through _sanitize_detail_pair,
    which drops mojibake/nav-junk rows and aliases vendor key names to
    the canonical attribute keys.
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

    # Detail-scraped specs from vendor product pages (vendor_sku-level).
    # These are the most authoritative source for structured specs —
    # scraped directly from the vendor's own spec table, not parsed
    # from a listing title.  Additive only: never override attributes
    # already set by scalar keys or the block harvest above.
    detail = meta.get("detail_specs")
    if isinstance(detail, dict):
        for k, v in detail.items():
            if v in (None, "", [], {}):
                continue
            if k == "overview_text_raw":
                overview = _parse_overview_fields(v)
                for overview_key, overview_value in overview.items():
                    clean = _sanitize_detail_pair(
                        overview_key, overview_value, vendor=vendor
                    )
                    if clean:
                        out.setdefault(*clean)
                continue
            clean = _sanitize_detail_pair(k, v, vendor=vendor)
            if not clean:
                continue
            ck, cv = clean
            if ck == "clock_range":
                # Ivory "3.6GHz - 4GHz" style range -> base + boost clocks.
                split = _split_clock_range(cv) if isinstance(cv, str) else None
                if split:
                    out.setdefault("base_clock_ghz", split[0])
                    out.setdefault("boost_clock_ghz", split[1])
                else:
                    out.setdefault("boost_clock_ghz", cv)
                continue
            out.setdefault(ck, cv)
            if ck == "scope_of_delivery" and isinstance(cv, str):
                # "with CPU cooler (AMD Wraith Stealth...)" -> cooler signal.
                low = cv.lower()
                if "cooler" in low or "fan included" in low:
                    out.setdefault("cooler_included", "Yes")
                elif "without" in low and "cooler" in low:
                    out.setdefault("cooler_included", "No")

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
    if chipset_m:
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

    # Core count from explicit text ("Dual Core", "10 cores"). Server
    # listings write "32/64 Cores" (cores/threads) — take both numbers.
    # Leftmost match wins otherwise — totals precede the P-core/E-core
    # breakdown in parens.
    ct = re.search(r"\b(\d{1,3})\s*/\s*(\d{1,3})\s*cores?\b", text, re.I)
    if ct and 2 <= int(ct.group(1)) <= 256 and 2 <= int(ct.group(2)) <= 512:
        a["cores"] = int(ct.group(1))
        a["threads"] = int(ct.group(2))
    else:
        ct2 = re.search(r"\b(\d{1,3})\s*cores?\s*/\s*(\d{1,3})\s*threads?\b", text, re.I)
        if ct2 and 2 <= int(ct2.group(1)) <= 256 and 2 <= int(ct2.group(2)) <= 512:
            a["cores"] = int(ct2.group(1))
            a["threads"] = int(ct2.group(2))
    if "cores" not in a:
        if re.search(r"\bdual[-\s]?core\b", text, re.I):
            a["cores"] = 2
        else:
            cm = re.search(r"\b(\d{1,3})\s*-?\s*cores?\b", text, re.I)
            if cm and 2 <= int(cm.group(1)) <= 128:
                # Guard: "P-cores"/"E-cores" fragments ("6 P-cores") must not
                # register as the total — require the word "core(s)" itself.
                a["cores"] = int(cm.group(1))
    if "threads" not in a:
        tm = re.search(r"\b(\d{1,3})\s*threads?\b", text, re.I)
        if tm and 2 <= int(tm.group(1)) <= 512:
            a["threads"] = int(tm.group(1))

    m = AMD_RYZEN_RE.search(text)
    if m:
        a["brand"] = "AMD"
        pro = "PRO " if m.group(2) else ""
        a["model"] = f"Ryzen {m.group(1)} {pro}{m.group(3).upper()}".strip()
    else:
        m = AMD_THREADRIPPER_RE.search(text)
        if m:
            a["brand"] = "AMD"
            pro = "PRO " if m.group(1) else ""
            a["model"] = f"Threadripper {pro}{m.group(2).upper()}".strip()
        else:
            m = AMD_APU_RE.search(text)
            if m:
                a["brand"] = "AMD"
                a["model"] = f"A{m.group(1)}-{m.group(2).upper()}"
            else:
                m = AMD_FX_RE.search(text)
                if m:
                    a["brand"] = "AMD"
                    a["model"] = f"FX-{m.group(1).upper()}"
                else:
                    m = AMD_ATHLON_RE.search(text)
                    if m:
                        a["brand"] = "AMD"
                        variant = f"{m.group(1).upper()} " if m.group(1) else ""
                        a["model"] = f"Athlon {variant}{m.group(2).upper()}".strip()
                    else:
                        m = AMD_EPYC_CODENAME_RE.search(text)
                        if m:
                            a["brand"] = "AMD"
                            a["model"] = f"EPYC {m.group(2).upper()}"
                        else:
                            m = INTEL_CPU_RE.search(text)
                            if m:
                                a["brand"] = "Intel"
                                raw_fam = re.sub(r"\s+", " ", m.group(1).strip())
                                # "ULTRA 5" -> "Ultra 5", "I7" -> "i7" (PCPP style).
                                if raw_fam.upper().startswith("ULTRA"):
                                    fam = raw_fam.title()
                                elif re.fullmatch(r"I[3579]", raw_fam.upper()):
                                    fam = "i" + raw_fam[-1]
                                else:
                                    fam = raw_fam.upper()
                                # Fix truncation: keep full number (3-5 digits + suffix)
                                num = m.group(2).upper().strip()
                                a["model"] = f"Core {fam} {num}"
                            else:
                                m = XEON_RE.search(text)
                                if m:
                                    a["brand"] = "Intel"
                                    tier, num = (m.group(1) or "").upper(), m.group(2).upper()
                                    if re.fullmatch(r"[WE]\d?", tier):
                                        a["model"] = f"Xeon {tier}-{num}"
                                    elif tier:
                                        a["model"] = f"Xeon {tier.title()} {num}"
                                    else:
                                        a["model"] = f"Xeon {num}"
                                else:
                                    m = EPYC_RE.search(text)
                                    if m:
                                        a["brand"] = "AMD"
                                        a["model"] = f"EPYC {m.group(1).upper()}"
                                    else:
                                        m = INTEL_CELERON_RE.search(text)
                                        if m:
                                            a["brand"] = "Intel"
                                            a["model"] = f"Celeron {m.group(1).upper()}"
                                        else:
                                            m = INTEL_PENTIUM_RE.search(text)
                                            if m:
                                                a["brand"] = "Intel"
                                                a["model"] = f"Pentium {m.group(1).upper()}"

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
        series_m = re.search(r"\bRyzen\s?[3-9]\s?(?:PRO\s?)?(\d)\d{3}", model or "", re.I)
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

    # Intel "series" tag — "(series 2)" / "Series 2" on Ultra parts.
    # Disambiguates same-numbered parts across series (225 vs 225 series 2)
    # and feeds the canonical CPU name ("... 225F series 2").
    sm = re.search(r"\(?\bseries\s?(\d{1,2})\)?\b", text, re.I)
    if sm and a.get("brand") == "Intel" and 1 <= int(sm.group(1)) <= 4:
        a["series"] = sm.group(1)

    return a


def _parse_gpu(text: str, meta) -> dict:
    a: dict = {}

    for token, canon in GPU_BRANDS.items():
        if re.search(rf"\b{re.escape(token)}\b", text, re.I):
            a["brand"] = canon
            break

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
        # Groups are (SDDRn / GDDRn / HBMn) — exactly one participates.
        kind, gen = None, ""
        if g.group(1):
            kind, gen = "SDDR", g.group(1).upper()
        elif g.group(2):
            kind, gen = "GDDR", g.group(2).upper()
        elif g.group(3) is not None:
            kind, gen = "HBM", (g.group(3) or "2")
        if kind:
            a["memory_type"] = f"{kind}{gen}"

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
        else:
            # "80+" shorthand ("850W Gold 80+") or a bare cert metal
            # ("NeoECO Gold"). In PSU titles a metal word is always the
            # efficiency tier, never the paint — real gold/silver PSUs
            # effectively don't exist. (WHITE excluded: white PSUs are
            # common, so bare "White" stays a color.)
            m80 = re.search(
                r"\b80\s?\+\s?(GOLD|SILVER|BRONZE|PLATINUM|TITANIUM)\b", text, re.I)
            if m80:
                a["efficiency"] = "80 PLUS " + m80.group(1).title()
            else:
                mb = re.search(r"\b(GOLD|SILVER|BRONZE|PLATINUM|TITANIUM)\b", text, re.I)
                if mb:
                    a["efficiency"] = "80 PLUS " + mb.group(1).title()

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

    # Form factor / Type: ATX, SFX, SFX-L etc.
    # (No separate `type` key — it only ever shadowed form_factor under a
    # meaningless name; filters use form_factor directly.)
    if re.search(r"\bSFX[-\s]?L\b", text, re.I):
        a["form_factor"] = "SFX-L"
    elif re.search(r"\bSFX\b", text, re.I):
        a["form_factor"] = "SFX"
    elif re.search(r"\bATX\b", text, re.I):
        # Could be ATX but not to override existing more specific; default ATX
        if "form_factor" not in a:
            a["form_factor"] = "ATX"

    # Color. Blank efficiency phrases first: "80 PLUS Gold" contains the
    # color word "Gold" but is a certification, not a paint job (this
    # produced 189 bogus color=Gold PSUs). Real metal-trim colors on other
    # categories (GPU "Black/Gold") are unaffected — this is PSU-only.
    # Additionally, bare cert metals never count as PSU colors at all (see
    # the efficiency fallback above: they always mean the tier).
    color_text = re.sub(
        r"\b80\s?PLUS\b(\s+[A-Za-z]+)?|\bCYBENETICS\b(\s+[A-Za-z]+)?",
        " ", text, flags=re.I)
    for color in COLOR_WORDS:
        if color in ("gold", "silver", "bronze", "platinum", "titanium"):
            continue
        if re.search(rf"\b{color}\b", color_text, re.I):
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
        a["speed"] = f"DDR{_ddr_gen(a.get('memory_type'))}-{s.group(1)}" if a.get("memory_type") else f"{s.group(1)}"
    else:
        # Fallback DDR-XXXX without MHz
        sd = SPEED_DDR_RE.search(text)
        if sd:
            a["speed_mhz"] = int(sd.group(1))
            a["speed"] = f"DDR{_ddr_gen(a.get('memory_type'))}-{sd.group(1)}"
        else:
            # Bare 4-digit speed after capacity ("Kingston DDR4 8GB 3200"):
            # in memory context a 1600-8533 number right after GB is MT/s.
            # (No leading \b: "8GB" has no boundary between 8 and G.)
            bs = re.search(r"GB\s+(\d{4})\b", text, re.I)
            if bs and 1600 <= int(bs.group(1)) <= 8533:
                a["speed_mhz"] = int(bs.group(1))
                a["speed"] = f"{bs.group(1)}"
            else:
                # Last resort: a bare JEDEC speed anywhere in the title
                # ("Corsair DDR4 16GB RAM (8GBx2) 3200"). Whitelist-only so
                # years (2024/2025) and MPN fragments never match; the \b
                # guards keep MPN-embedded runs ("AD4U320032G22") out.
                jb = re.search(
                    r"\b(1600|1866|2133|2400|2666|2933|3200|3400|3600|4000|"
                    r"4133|4400|4800|5200|5400|5600|6000|6200|6400|6600|"
                    r"6800|7200|7600|8000|8200|8400|8533)\b", text)
                if jb:
                    a["speed_mhz"] = int(jb.group(1))
                    a["speed"] = f"{jb.group(1)}"

    c = CL_RE.search(text)
    if c:
        a["cas_latency"] = int(c.group(1))
        a["cas"] = int(c.group(1))
        # First word latency calc if speed present
        if "speed_mhz" in a:
            try:
                fwl = round((int(c.group(1)) * 2000) / int(a["speed_mhz"]), 1)
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

    # Form factor / tower type (ATX Mid Tower etc). Stored as case_type —
    # PCPP's case TYPE filter — alongside form_factor, never as bare `type`.
    cf = _case_form_factor(text)
    if cf:
        a["form_factor"] = cf
        a["case_type"] = cf
    else:
        # Fallback generic ATX etc
        ff = _form_factor(text)
        if ff:
            a["form_factor"] = ff
            a["case_type"] = ff

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

    # Type: SSD vs HDD distinction (canonical key is drive_type; the old
    # bare `type` shadow is gone — see the PSU/case/memory notes).
    if re.search(r"\bSSD\b", text, re.I):
        a["drive_type"] = "SSD"
        # NVMe flag
        if re.search(r"\bNVME\b", text, re.I):
            a["nvme"] = True
            a["nvme_flag"] = "Yes"
        else:
            a["nvme"] = False
            a["nvme_flag"] = "No"
    elif re.search(r"\bHDD\b", text, re.I):
        a["drive_type"] = "HDD"
        a["nvme"] = False
    elif re.search(r"\bSSHD\b", text, re.I):
        a["drive_type"] = "SSHD"

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

    attrs = _from_vendor_meta(meta, vendor=listing.get("vendor_id"))

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

    # Boolean-ish specs to canonical Yes/No so the filter rail never shows
    # both "True" and "yes" for the same thing (detail values arrive as
    # 'yes'/'no', Hebrew-desc/tree values as True/False, pckombo rows as
    # JSON booleans). Single source of truth: YES_NO_KEYS.
    for yk in YES_NO_KEYS:
        if yk in attrs:
            attrs[yk] = _canonicalize_yes_no(yk, attrs[yk])

    # CPU-only dedupe: Plonter's detail "Graphics" row and the title parser's
    # "integrated_graphics" are the same signal ("no" iGPU vs "Radeon").
    # Keep integrated_graphics (nicer label, the one filters use).
    if category == "cpu" and "graphics" in attrs and "integrated_graphics" in attrs:
        del attrs["graphics"]

    # Cross-vendor dupe consolidation: different spiders/parsers produce
    # different keys for the same fact (British vs US spelling, unit-suffixed
    # vs bare, per-vendor variants). Fold them into one canonical key so the
    # site shows a single row / single filter instead of two or three.
    _DUPE_ALIASES = (
        ("colour", "color"),
        ("dimensions_wxhxd", "dimensions"),
        ("voltage_v", "voltage"),
        ("cas", "cas_latency"),
        ("cas_latency_cl", "cas_latency"),
        ("shape_factor", "drive_form_factor"),
        ("first_word_latency", "first_word_latency_ns"),
        ("nvme_flag", "nvme"),
        ("ecc", "ecc_support"),
        ("igpu", "integrated_graphics"),
        ("tdp_tgp", "tdp"),
    )
    for old_k, new_k in _DUPE_ALIASES:
        if old_k in attrs and new_k not in attrs:
            attrs[new_k] = attrs.pop(old_k)
        elif old_k in attrs:
            del attrs[old_k]

    # Vendor capacity variants: Plonter emits CapacityGB (already GB) and
    # CapacityTB alongside capacity_gb. Fold into capacity_gb as ints.
    if "capacity_gb" not in attrs:
        if "capacitygb" in attrs:
            try:
                attrs["capacity_gb"] = int(float(str(attrs.pop("capacitygb"))))
            except (ValueError, TypeError):
                pass
        elif "capacitytb" in attrs:
            try:
                attrs["capacity_gb"] = int(float(str(attrs.pop("capacitytb"))) * 1000)
            except (ValueError, TypeError):
                pass
    else:
        attrs.pop("capacitygb", None)
        attrs.pop("capacitytb", None)

    # Generic cache ("4MB", "16MB (1x 16MB)") -> cache_mb int when the
    # specific key is missing, so cache filters/columns have one source.
    if "cache_mb" not in attrs and "cache" in attrs:
        m = re.search(r"(\d+(?:\.\d+)?)\s*mb", str(attrs["cache"]), re.I)
        if m:
            try:
                attrs["cache_mb"] = int(float(m.group(1)))
            except (ValueError, TypeError):
                pass

    # GPU memory alias
    if "vram_gb" in attrs and "memory" not in attrs:
        attrs["memory"] = f"{attrs['vram_gb']} GB"
    # Ensure chipset alias for GPU (gpu_chip -> chipset for filter parity)
    if "gpu_chip" in attrs and "chipset" not in attrs:
        attrs["chipset"] = attrs["gpu_chip"]

    # Value canonicalization for filter parity (PCPP-style rails need a
    # small set of distinct values — "65W"/"65 W"/"65W (Base Power)" must
    # not become three filter options). All idempotent string->string/int
    # normalizations; safe to run on re-extracts.
    _canonicalize_filter_values(attrs, category)

    # Price per GB for storage (if price available on listing, compute here? listing price may be missing at this stage)
    # Will be enriched later in matching if price present.

    return attrs


# Motherboard memory-max sizes worth offering as a filter (GB). Anything
# outside this set came from a misparsed title ("2000", "1", "2") and is
# dropped instead of becoming a bogus filter option.
_MOBO_MAX_MEM_GB = {32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048}

# Brand spelling canonical map (lowercased input -> display). Detail-spec
# rows SHOUT ("CORSAIR", "THERMALRIGHT", "Team Group") while title parsing
# whispers canonical names — without this the brand rail shows both.
# Sub-lines fold into their parent ("Kingston Fury" -> "Kingston").
_BRAND_CANON = {
    "corsair": "Corsair", "thermalright": "Thermalright", "arctic": "Arctic",
    "hyte": "HYTE", "team group": "TeamGroup", "teamgroup": "TeamGroup",
    "be quiet": "be quiet!", "western digital wd": "Western Digital",
    "western digital": "Western Digital", "ivory": "Ivory",
    "maxsun": "MAXSUN", "kingston fury": "Kingston", "fury": "Kingston",
    "patriot viper": "Patriot", "viper": "Patriot",
    "sandisk": "SanDisk", "lexar": "Lexar", "adata": "ADATA", "xpg": "XPG",
    "geil": "GeIL", "v-color": "V-Color", "vcolor": "V-Color",
    "g.skill": "G.Skill", "gskill": "G.Skill", "ripjaws": "G.Skill",
    "trident": "G.Skill", "flare": "G.Skill", "beast": "Kingston",
    "klevv": "Klevv", "apacer": "Apacer", "transcend": "Transcend",
    "silicon power": "Silicon Power", "siliconpower": "Silicon Power",
    "sk hynix": "SK Hynix", "hynix": "SK Hynix", "samsung": "Samsung",
    "crucial": "Crucial", "ballistix": "Crucial", "micron": "Crucial",
    "kingston": "Kingston", "patriot": "Patriot", "pny": "PNY",
    "seasonic": "Seasonic", "fsp": "FSP", "antec": "Antec",
    "coolermaster": "Cooler Master", "cooler master": "Cooler Master",
    "fractal design": "Fractal Design", "fractal": "Fractal Design",
    "lian li": "Lian Li", "lian-li": "Lian Li", "nzxt": "NZXT",
    "thermaltake": "Thermaltake", "zalman": "Zalman", "cougar": "Cougar",
    "gamdias": "GAMDIAS", "supermicro": "Supermicro",
    "silverstone": "SilverStone", "noctua": "Noctua", "deepcool": "Deepcool",
    "asus": "ASUS", "gigabyte": "Gigabyte", "msi": "MSI", "asrock": "ASRock",
    "inno3d": "Inno3D", "powercolor": "PowerColor", "nvidia": "NVIDIA",
    "palit": "Palit", "xfx": "XFX", "sapphire": "Sapphire", "zotac": "ZOTAC",
    "toshiba": "Toshiba", "kioxia": "KIOXIA", "seagate": "Seagate",
    "1stplayer": "1stPlayer", "biostar": "Biostar",
    "afox": "AFOX", "evga": "EVGA", "arktek": "ARKTEK", "jonsbo": "Jonsbo",
}

# Legacy low-end cards are sold as "SDDR3" (vendor shorthand for the DDR3
# on sub-$50 cards like the GT 710) — fold into DDR3/4/5 for the filter.
_SDDR_RE = re.compile(r"(?i)\bSDDR([345])\b")


def _canonicalize_filter_values(attrs: dict, category: str) -> None:
    """Normalize attribute VALUES (not keys) so filters stay compact."""
    # Yes/No sweep first: downstream sources (pckombo JSON booleans,
    # German "Ja"/qualified answers) skip the extract-time loop.
    for yk in YES_NO_KEYS:
        if yk in attrs:
            attrs[yk] = _canonicalize_yes_no(yk, attrs[yk])
    # TDP: "65 W", "65W (Processor Base Power), 219W (...)" -> "65W".
    # Leading number + W is always the headline figure.
    tdp = attrs.get("tdp")
    if isinstance(tdp, str):
        m = re.match(r"\s*(\d+)\s?W\b", tdp)
        if m:
            attrs["tdp"] = f"{m.group(1)}W"

    # Efficiency: "GOLD" -> "80 PLUS Gold", "80PLUS[ Gold]" -> "80 PLUS[ Gold]".
    # Bare "GOLD" in a PSU title/detail row means 80 PLUS Gold (the metal
    # alone is never any other cert); "Cybenetics X" stays as-is.
    eff = attrs.get("efficiency")
    if isinstance(eff, str):
        e = re.sub(r"(?i)\b80\s?plus\b\s*", "80 PLUS ", eff).strip()
        e = re.sub(r"\s+", " ", e)
        if re.fullmatch(r"(?i)(gold|silver|bronze|platinum|titanium|white)", e):
            e = "80 PLUS " + e.title()
        attrs["efficiency"] = e

    # Modular: case variants ("FULL MODULAR" vs "Full Modular") -> one
    # canonical word. Bare "MODULAR" (vendor didn't specify) -> "Yes".
    mod = attrs.get("modular")
    if isinstance(mod, str):
        mu = mod.upper()
        if "FULL" in mu:
            attrs["modular"] = "Full"
        elif "SEMI" in mu:
            attrs["modular"] = "Semi"
        elif "NON" in mu:
            attrs["modular"] = "No"
        elif "MODULAR" in mu:
            attrs["modular"] = "Yes"

    # Color: title-case ("black" -> "Black") and drop ", inside X"
    # qualifiers ("black, inside black" -> "Black").
    col = attrs.get("color")
    if isinstance(col, str):
        col = re.sub(r",?\s*inside\s+\w+\s*$", "", col, flags=re.I).strip()
        if col:
            attrs["color"] = col.title()

    # GHz clocks -> float ("3.80GHz" -> 3.8, "2542 MHz" -> 2.542, unparseable
    # detail fragments like bare "MHz" are dropped). Powers the sliders.
    for ck in ("base_clock_ghz", "boost_clock_ghz"):
        cv = attrs.get(ck)
        if isinstance(cv, str):
            m = re.search(r"(\d+(?:\.\d+)?)\s?GHz", cv, re.I)
            if m:
                attrs[ck] = float(m.group(1))
                continue
            m = re.search(r"(\d+(?:\.\d+)?)\s?MHz", cv, re.I)
            if m:
                attrs[ck] = round(float(m.group(1)) / 1000, 3)
                continue
            del attrs[ck]

    # Caches: "8MB (8x 1MB)" / "8MiB (8x 1MiB)" -> "8MB".
    for kk in ("l2_cache", "l3_cache"):
        kv = attrs.get(kk)
        if isinstance(kv, str):
            kv = re.sub(r"\s*\(.*$", "", kv).strip()
            kv = re.sub(r"(?i)MiB", "MB", kv)
            attrs[kk] = kv

    # iGPU: "None" and "No" are the same answer.
    ig = attrs.get("integrated_graphics")
    if isinstance(ig, str) and ig.strip().lower() == "none":
        attrs["integrated_graphics"] = "No"

    # Kit/modules: "1x 16GB" -> "1x16GB" (spacing variants split filters).
    for mk in ("modules", "kit"):
        mv = attrs.get(mk)
        if isinstance(mv, str):
            attrs[mk] = re.sub(r"(\d)\s*x\s*(\d+\s?GB)", r"\1x\2", mv, flags=re.I)

    # First-word latency: round to 0.1ns ("16.429" -> 16.4) so the rail
    # shows a dozen options, not dozens.
    fwl = attrs.get("first_word_latency_ns")
    if fwl is not None:
        try:
            attrs["first_word_latency_ns"] = round(float(str(fwl).split()[0]), 1)
        except (ValueError, TypeError):
            pass

    # Voltage: "1.1V (JEDEC-Normspannung)" -> "1.1V".
    vv = attrs.get("voltage")
    if isinstance(vv, str):
        attrs["voltage"] = re.sub(r"\s*\(.*\)\s*$", "", vv).strip()

    # Registered implies ECC: a Registered DIMM without an explicit ECC
    # row must still match the ECC filter.
    if attrs.get("ecc_registered") and not attrs.get("ecc_support"):
        attrs["ecc_support"] = "Yes"

    # PSU catch-all (any source: title, detail rows, pckombo): a cert
    # metal as "color" is always the efficiency tier, never paint.
    if category == "psu":
        pcol = attrs.get("color")
        if isinstance(pcol, str) and re.fullmatch(
                r"(?i)(gold|silver|bronze|platinum|titanium)", pcol.strip()):
            if not attrs.get("efficiency"):
                attrs["efficiency"] = "80 PLUS " + pcol.strip().title()
            attrs.pop("color", None)

    # Case dupe: _parse_case stores the same value in form_factor AND
    # case_type (both are the board-compat "ATX", not PCPP's tower Type).
    # Keep form_factor (the filtered key), drop the twin.
    if category == "case" and attrs.get("case_type") == attrs.get("form_factor"):
        attrs.pop("case_type", None)

    # Case max-GPU-length: "max. 400mm" (graphics_cards detail row) -> int
    # into max_gpu_length_mm (the filtered/slider key).
    if category == "case" and "max_gpu_length_mm" not in attrs:
        gc = attrs.get("graphics_cards")
        if isinstance(gc, str):
            m = re.search(r"max\.\s?(\d+)\s?mm", gc, re.I)
            if m:
                attrs["max_gpu_length_mm"] = int(m.group(1))

    # Case PSU bay: "ATX (max. 200mm deep)" -> "ATX" (depth lives in the
    # detail row; the filter only needs the standard).
    if category == "case":
        ps = attrs.get("power_supply")
        if isinstance(ps, str):
            m = re.match(r"\s*(ATX|SFX-L|SFX|TFX|FLEX\s?ATX)\b", ps, re.I)
            if m:
                attrs["power_supply"] = m.group(1).upper().replace(" ", "")

    # Motherboard memory-max: capacity_gb here is really "max. NNNGB".
    # Whitelisted sizes become memory_max ("256GB"); junk ("1", "2000")
    # is dropped so it never distorts the slider or the rail. The generic
    # capacity/capacity_gb/total_gb aliases above are meaningless for
    # boards, so they go too (a junk "2TB capacity" row is worse than none).
    if category == "motherboard":
        cap = attrs.get("capacity_gb")
        if cap is not None:
            try:
                n = int(cap)
            except (ValueError, TypeError):
                n = None
            if n in _MOBO_MAX_MEM_GB:
                attrs["memory_max"] = f"{n}GB"
            attrs.pop("capacity_gb", None)
            attrs.pop("capacity", None)
            attrs.pop("total_gb", None)

    # Motherboard RAM slots: ram_slots is a German sentence
    # ("4x DDR5 DIMM, ..., max. 256GB (UDIMM)") while memory_slots is the
    # clean int. Harvest count + max from the sentence, then drop it.
    rs = attrs.get("ram_slots")
    if isinstance(rs, str):
        if "memory_slots" not in attrs:
            m = re.match(r"\s*(\d+)\s*x\b", rs)
            if m:
                attrs["memory_slots"] = int(m.group(1))
        if "memory_max" not in attrs:
            for m in re.finditer(r"max\.\s?(\d+)\s?GB", rs, re.I):
                if int(m.group(1)) in _MOBO_MAX_MEM_GB:
                    attrs["memory_max"] = f"{m.group(1)}GB"
                    break
        attrs.pop("ram_slots", None)

    # Motherboard M.2 count: verbose German enumerations
    # ("1x M.2 ..., 2x M.2 ...") -> total int; plain ints pass through.
    m2 = attrs.get("m2_slots")
    if isinstance(m2, str) and "M.2" in m2:
        total = sum(int(n) for n in re.findall(r"(\d+)\s*x\s*M\.?2", m2, re.I))
        if total:
            attrs["m2_slots"] = total

    # GPU external power: "1x 12V-2x6 (via adapter: ...)" -> "1x 12V-2x6".
    pc = attrs.get("power_connections")
    if isinstance(pc, str):
        attrs["power_connections"] = re.sub(r"\s*\(.*\)\s*$", "", pc).strip()

    # Connector lists: "1x CPU 8-pin ,1x CPU 4+4-pin" -> tidy comma spacing.
    for ck in ("cpu_power_connectors", "pcie_power_connectors",
               "sata_connectors", "power_connections"):
        cv = attrs.get(ck)
        if isinstance(cv, str):
            attrs[ck] = re.sub(r"\s*,\s*", ", ", cv).strip()

    # Brand spelling: detail rows shout ("CORSAIR", "THERMALRIGHT") while
    # titles whisper ("Corsair") — one canonical spelling per brand or the
    # rail shows both. Unknown brands pass through untouched.
    # Chip vendors never make boards or DIMMs: an "AMD"/"Intel" brand on a
    # motherboard (Plonter generics like "AMD A520 AM4") or memory ("for
    # AMD Ryzen") is chipset bleed, not a brand — drop it. (CPUs/GPUs keep
    # theirs: AMD/NVIDIA really make those.)
    br = attrs.get("brand")
    if isinstance(br, str):
        canon = _BRAND_CANON.get(br.strip().lower())
        if canon:
            attrs["brand"] = canon
            br = canon
    if category in ("motherboard", "memory") and attrs.get("brand") in ("AMD", "Intel", "NVIDIA"):
        attrs.pop("brand", None)

    # Timings must look like timings ("16-18-18-38"). Bare numbers ("36")
    # are CAS values leaked from detail rows — the cas_latency filter
    # already covers them.
    tm = attrs.get("timings")
    if isinstance(tm, str) and not re.search(r"\d+\s*-\s*\d+", tm):
        attrs.pop("timings", None)

    # Form factor spelling: "mATX"/"Micro ATX" (title regex / detail rows)
    # vs "Micro-ATX"; "E-ATX" vs "EATX". One spelling each.
    ff = attrs.get("form_factor")
    if isinstance(ff, str):
        flu = ff.strip().lower()
        if flu in ("matx", "micro atx"):
            attrs["form_factor"] = "Micro-ATX"
        elif flu == "e-atx":
            attrs["form_factor"] = "EATX"

    # Socket spelling: "STR5" vs "sTR5" (Threadripper); "Intel 4677" detail
    # rows vs "LGA4677"; "3647 (LGA)" detail rows vs "LGA3647".
    sk = attrs.get("socket")
    if isinstance(sk, str):
        sku = sk.strip()
        if sku.upper() == "STR5":
            attrs["socket"] = "sTR5"
        else:
            m = re.match(r"(?i)^intel\s+(\d{4})$", sku)
            if m:
                attrs["socket"] = f"LGA{m.group(1)}"
            else:
                m = re.match(r"^(\d{3,4})\s*\(LGA\)$", sku)
                if m:
                    attrs["socket"] = f"LGA{m.group(1)}"

    # Cores/threads: "24 (24C)" detail suffixes -> plain ints (the slider
    # parses leading numbers anyway, but checkboxes/columns shouldn't show
    # the suffix).
    for ctk in ("cores", "threads"):
        cv = attrs.get(ctk)
        if isinstance(cv, str):
            m = re.match(r"\s*(\d+)", cv)
            if m:
                try:
                    attrs[ctk] = int(m.group(1))
                except (ValueError, TypeError):
                    pass

    # "Sapphire" is a GPU board partner — except when Intel's codename
    # ("Sapphire Rapids") leaks into a CPU title and wins longest-match.
    # CPUs branded Sapphire are always that leak; real Sapphire cards are
    # GPUs and never reach this branch.
    if category == "cpu" and attrs.get("brand") == "Sapphire":
        attrs["brand"] = "Intel"

    # Storage interface: all SATA revisions are SATA 6Gb/s for filtering
    # ("SATA 6.0 Gb/s" vs "SATA 6Gb/s" vs bare "SATA").
    itf = attrs.get("interface")
    if isinstance(itf, str):
        if re.match(r"(?i)^\s*SATA\b", itf):
            attrs["interface"] = "SATA 6 Gb/s"
        else:
            attrs["interface"] = re.sub(r"\bX(\d)", r"x\1", itf)

    # Case PSU bay: an "internal ..." value means the case SHIPS WITH a
    # PSU (PCPP's "Included"), not a bay standard.
    if category == "case":
        ps2 = attrs.get("power_supply")
        if isinstance(ps2, str) and re.match(r"(?i)^\s*internal\b", ps2):
            attrs["power_supply"] = "Included"

    # Microarchitecture: squash detail-row whitespace ("Lion Cove (P-Core)
    #   Skymont (E-Core)") and fix sentence-case ("golden Cove").
    ma = attrs.get("microarchitecture")
    if isinstance(ma, str):
        ma = re.sub(r"\s+", " ", ma).strip()
        if ma[:1].islower():
            ma = ma[:1].upper() + ma[1:]
        attrs["microarchitecture"] = ma

    # iGPU naming: "Intel UHD Graphics 770" vs "Intel UHD 770" (same iGPU,
    # two spellings across title/detail sources).
    ig2 = attrs.get("integrated_graphics")
    if isinstance(ig2, str):
        attrs["integrated_graphics"] = re.sub(
            r"(?i)\bIntel\s+UHD\s+Graphics\s+(\d+)",
            r"Intel UHD \1", ig2)

    # GPU memory type: vendor "SDDR3" -> "DDR3" (see _SDDR_RE note).
    if category == "gpu":
        gm = attrs.get("memory_type")
        if isinstance(gm, str):
            attrs["memory_type"] = _SDDR_RE.sub(r"DDR\1", gm)

    # SSD/HDD DRAM cache plausibility: real sizes are powers of two up to
    # 8GB — anything else ("7500" from a "7500 MB/s" speed row) is a
    # misparse and is dropped instead of becoming a filter option.
    cb = attrs.get("cache_mb")
    if cb is not None:
        try:
            n = int(float(str(cb).split()[0]))
            if n not in (8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192):
                attrs.pop("cache_mb", None)
        except (ValueError, TypeError):
            attrs.pop("cache_mb", None)