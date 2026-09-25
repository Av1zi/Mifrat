"""
specs/text.py — the ONE place regexes live.

These are the battle-tested patterns ported verbatim from the retired
extractors.py (same behavior, same coverage) minus everything that only
existed to serve the old 800-key alias soup. Nothing here decides what a
spec *is*: patterns only pull tokens out of text, and resolvers turn those
tokens into typed schema fields.

Rules:
- No `setdefault` merging here, no knowledge of tiers.
- Knowledge maps (chipset -> socket/memory) live in schema.py, not here.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata

HEBREW = re.compile(r"[\u0590-\u05FF]+")


def clean_text(value) -> str:
    """Normalize a vendor string for matching (HTML entities, trademarks,
    Hebrew stripped, punctuation squeezed). Same contract as the old
    extractors.clean_text — 1PC's JSON-bleed guard included."""
    if value is None:
        return ""
    text = _html.unescape(str(value))
    # Same 1PC JSON-bleed guard as matching._clean (keep in sync).
    text = text.split('",')[0]
    # Trademark symbols MUST go before NFKC: NFKC folds ™->TM / ®->R,
    # gluing them onto the previous word ("Ryzen™" -> "RYZENTM") and
    # breaking every \b-anchored model regex after it.
    text = re.sub(r"[®™©℗]", " ", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufffd", " ")
    text = HEBREW.sub(" ", text)
    text = re.sub(r"[^A-Za-z0-9#+/.&()-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------
# Sockets / chipsets / memory / wireless
# --------------------------------------------------------------------------

# Any socket token (AMD named or Intel LGA). AMD prints its physical package
# in parentheses ("AMD SP5 (LGA6096)"), which is NOT the socket name — see
# socket_from_text() below, which searches the parenthesis-free text first.
SOCKET_RE = re.compile(
    r"\b(AM\d\+?|FM\d\+?|SP\d+|sTRX?\d+|sWRX\d+|TRX\d+|TR\d|LGA\s?\d{3,4}(?:-\d)?)\b",
    re.I,
)
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")

NUMERIC_SOCKET = {
    "1700": "LGA1700", "1851": "LGA1851", "1200": "LGA1200",
    "1151": "LGA1151", "1150": "LGA1150", "1155": "LGA1155",
    "1156": "LGA1156", "1356": "LGA1356", "1366": "LGA1366", "2066": "LGA2066",
    "2011": "LGA2011", "775": "LGA775", "3647": "LGA3647",
    "4189": "LGA4189", "4677": "LGA4677",
}
NUMERIC_SOCKET_RE = re.compile(
    r"\b(1700|1851|1200|1151|1150|1155|1156|1356|1366|2066|2011|775|3647|4189|4677)\b"
)

CHIPSET_RE = re.compile(
    r"\b(X670E|X870E|X870|X670|X570S|X570|X470|X370|X399|X99|X299|"
    r"TRX50|WRX90|TRX40|"
    r"B850|B840|B860|B760|B660|B650E|B650|B560|B550|B460|B450|B360|B350|"
    r"A620|A520|A320|"
    r"Z890|Z790|Z690|Z590|Z490|Z390|Z370|Z270|Z170|"
    r"H810|H770|H670|H610|H570|H510|H470|H410|H370|H310|H270|H170|H110|"
    r"W680|W480|W790|"
    r"B365|H310)([A-Z]?)\b",
    re.I,
)

DDR_RE = re.compile(r"\bDDR\s?([345]L?)\b", re.I)
WIFI_STD_RE = re.compile(r"\bWIFI\s?([67])\s?(E)?\b", re.I)
WIFI_RE = re.compile(r"\bWIFI\b|\bWI-?FI\b|\bWIRELESS\b", re.I)

FORM_FACTOR_PATTERNS = [
    (re.compile(r"\bMINI\s?[- ]?ITX\b|\bITX\b", re.I), "Mini-ITX"),
    (re.compile(r"\bMICRO\s?[- ]?ATX\b|\bM\s?[- ]?ATX\b|\bMATX\b", re.I), "Micro-ATX"),
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
LAN_BASE_T_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?Gb/s\s?BASE-T\b", re.I)
SLOTS_RE = re.compile(r"\b(\d{1,2})\s?X\s?DDR[345]\b", re.I)
DIMMS_RE = re.compile(r"\b(\d{1,2})\s?X\s?DIMMs?\b", re.I)
MEMORY_MAX_RE = re.compile(r"\b(\d+)\s?GB\s*(?:MAX|Maximum)\b", re.I)
M2_SLOTS_RE = re.compile(r"\b(\d+)\s?X\s?M\.?2\b", re.I)
SATA_PORTS_RE = re.compile(r"\b(\d+)\s?X\s?SATA\b", re.I)
PCIE_X16_RE = re.compile(r"\b(\d{1,2})\s?X\s?PCIE\s?(?:GEN\d\s?)?X?16\b", re.I)
PCIE_X1_RE = re.compile(r"\b(\d)\s?X\s?PCIE\s?X?1\b", re.I)
REVISION_RE = re.compile(r"\bREV\.?\s?(\d+(?:\.\d+)?)\b", re.I)
V_REVISION_RE = re.compile(r"\b[Vv](\d+)\b")


# --------------------------------------------------------------------------
# CPU models
# --------------------------------------------------------------------------

AMD_RYZEN_RE = re.compile(r"\bRYZEN\s?(\d)\s?(?:(PRO)\s?)?(\d{4}[A-Z0-9]*)", re.I)
AMD_THREADRIPPER_RE = re.compile(r"\bTHREADRIPPER\s?(PRO\s?)?(\d{4}[A-Z0-9]*)", re.I)
AMD_APU_RE = re.compile(r"\bA(4|6|8|9|10|12)\s?-?\s?(\d{4}[A-Z]{0,2})\b", re.I)
AMD_FX_RE = re.compile(r"\bFX\s?-?\s?(\d{4}[A-Z]?)\b", re.I)
AMD_ATHLON_RE = re.compile(r"\bATHLON\s?(?:64\s?)?(X\d)?\s?-?\s?(\d{3,4}[A-Z]{0,2})\b", re.I)
AMD_EPYC_CODENAME_RE = re.compile(r"\b(NAPLES|ROME|MILAN|GENOA)\s?(\d{4}[A-Z]?)\b", re.I)
EPYC_RE = re.compile(
    r"\bEPYC\s?(?:\d+(?:TH|ST|ND|RD)\s?GEN\s?(?:\([^)]*\)\s?)?)?"
    r"(\d{3,4}[A-Z]{0,2})(?!\s*Series\b)",
    re.I,
)
INTEL_CPU_RE = re.compile(
    r"\b(?:CORE\s?)?(ULTRA\s?\d|I\d)[\s-]?(\d{3,5}[A-Z]{0,4}(?:\s?PLUS)?)", re.I
)
INTEL_CELERON_RE = re.compile(r"\bCELERON\s?(?:DUAL\s?CORE\s?)?([A-Z]?\d{3,4}[A-Z]{0,2})\b", re.I)
INTEL_PENTIUM_RE = re.compile(
    r"\bPENTIUM\s?(?:GOLD\s?|SILVER\s?|DUAL\s?CORE\s?)?([A-Z]?\d{3,4}[A-Z]{0,2})\b", re.I
)
XEON_RE = re.compile(
    r"\bXEON\s?(?:(SILVER|BRONZE|GOLD|PLATINUM|W\d?|E\d?)\s?-?\s?)?(\d{3,5}[A-Z]{0,2})\b",
    re.I,
)
CPU_PACKAGING_TRAY_RE = re.compile(r"\b(?:tray|oem|mpk|bulk)\b", re.I)
CPU_PACKAGING_BOX_RE = re.compile(r"\b(?:box|boxed|retail|wraith|wrapper)\b", re.I)
CPU_COOLER_INCLUDED_RE = re.compile(
    r"\b(?:with|includes?)\s+(?:a\s+)?(?:wraith|stock\s+)?cooler\b", re.I
)
CPU_COOLER_EXCLUDED_RE = re.compile(r"\b(?:without|no)\s+cooler\b", re.I)

# --------------------------------------------------------------------------
# GPU / clocks / power
# --------------------------------------------------------------------------

GPU_CHIP_RE = re.compile(
    r"\b(GEFORCE\s?RTX\s?\d{3,4}(?:\s?(?:TI|SUPER))?|"
    r"RTX\s?PRO\s?\d{3,4}[A-Z]?|RTX\s?A\d{3,4}|RTX\s?\d{3,4}(?:\s?(?:TI|SUPER))?|"
    r"RX\s?\d{3,4}(?:\s?(?:XT|GRE|XTX))?|QUADRO\s?[A-Z0-9]+|TESLA\s?[A-Z0-9]+|"
    r"FIREPRO\s?[A-Z0-9]+|ARC\s?PRO\s?[A-Z]\d+|ARC\s?[A-Z]\d{2,3}|"
    r"GEFORCE\s?GTX?\s?\d{3,4}(?:\s?TI)?|GTX?\s?\d{3,4}(?:\s?TI)?|GTS?\s?\d{3,4}|"
    r"RADEON\s?(?:HD\s?)?\d{3,4}|R[579]\s?\d{3})\b",
    re.I,
)

VRAM_RE = re.compile(r"\b(\d{1,2})\s?G(?:B)?\b")
GMEM_RE = re.compile(r"\bS?DDR([345]X?)\b|\bGDDR([567]X?)\b|\bHBM(\d?)\b", re.I)
CORE_CLOCK_RE = re.compile(r"\b(\d{3,4})\s?MHZ\b", re.I)
BOOST_CLOCK_RE = re.compile(r"\bBOOST\s*[:\\-]?\s*(\d{3,4})\s?MHZ\b", re.I)
TDP_RE = re.compile(r"\b(\d{2,4})\s?W\b")
LENGTH_MM_RE = re.compile(r"\b(\d{2,3})\s?MM\b", re.I)
SLOT_WIDTH_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*-?SLOT\b", re.I)
PCIE_INTERFACE_RE = re.compile(r"PCI\s*E?\s*([345]\.0)?\s*X\s*16", re.I)
PCIE_GEN_INTERFACE_RE = re.compile(r"\bPCIE\s?([345])\.0\b", re.I)
GPU_POWER_8PIN_RE = re.compile(r"\b(\d{1,2})\s?X\s?8[\s-]?PIN\b", re.I)
GPU_POWER_16PIN_RE = re.compile(r"\b(\d?)\s?X?\s?12V-?2X6\b|\b12VHPWR\b", re.I)

# --------------------------------------------------------------------------
# PSU
# --------------------------------------------------------------------------

WATT_RE = re.compile(r"\b(\d{3,4})\s?W\b")
WATT_PSU_FALLBACK_RE = re.compile(r"\b(\d{3,4})P\b")  # e.g. Ai1300P without W
EFF_RE = re.compile(r"80\s?PLUS\s?(TITANIUM|PLATINUM|GOLD|SILVER|BRONZE|WHITE)", re.I)
CYBENETICS_RE = re.compile(r"CYBENETICS\s*(TITANIUM|PLATINUM|GOLD|SILVER|BRONZE)", re.I)
MOD_RE = re.compile(
    r"\b(FULL(?:Y)?\s?MODULAR|SEMI\s?MODULAR|NON\s?MODULAR|MODULAR)\b", re.I
)
FANLESS_RE = re.compile(r"\bFANLESS\b", re.I)
PSU_TYPE_RE = re.compile(r"\b(SFX-L|SFX|TFX|FLEX\s?ATX|ATX)\b", re.I)

# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------

KIT_RE = re.compile(r"\((\d)\s?X\s?(\d{1,3})\s?(?:GB)?\)", re.I)
KIT_ALT_RE = re.compile(r"\b(\d)\s?[Xx×]\s?(\d{1,3})\s?GB\b")
SPEED_RE = re.compile(r"\b(\d{3,4})\s?(?:MHZ|MT/S)\b", re.I)
SPEED_DDR_RE = re.compile(r"\bDDR[345]L?[-\s]?(\d{3,4})\b", re.I)
CL_RE = re.compile(r"\bCL\s?(\d{1,2})\b", re.I)
CAS_RE = re.compile(r"\bC(\d{1,2})\b")
VOLTAGE_RE = re.compile(r"\b(\d+\.\d+)\s?V\b", re.I)
TIMING_RE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{1,2}-\d{1,3})\b")
ECC_RE = re.compile(r"\bECC\b", re.I)
REGISTERED_RE = re.compile(r"\b(REG|REGISTERED)\b", re.I)
HEAT_SPREADER_RE = re.compile(r"\b(HEAT\s?SPREADER|HEATSINK)\b", re.I)
LIGHTING_RE = re.compile(r"\b(ARGB|ADDRESSABLE\s?RGB|RGB|LED)\b", re.I)

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

CAPACITY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(TB|GB)\b(?!\s*/s)", re.I)
STORAGE_TYPE_RE = re.compile(r"\b(SSD|HDD|SSHD|NVME)\b", re.I)
FORM_FACTOR_STORAGE_RE = re.compile(
    r"\b(2\.5[\"'\u2019]*|3\.5[\"'\u2019]*|M\.2\s*22\d{2}|M\.2|U\.2)\b", re.I
)
INTERFACE_RE = re.compile(r"\b(SATA|NVME|PCIE|SAS)\b", re.I)
PCIE_GEN_RE = re.compile(r"PCIE\s*GEN\s*([345])(?:\.0)?(?:\s*X\s*4)?", re.I)
CACHE_RE = re.compile(r"\b(\d+)\s?MB\s*(?:CACHE|DRAM)?\b(?!/s)", re.I)
RPM_RE = re.compile(r"\b(\d{3,4})\s?RPM\b", re.I)

# --------------------------------------------------------------------------
# Cooling / fans
# --------------------------------------------------------------------------

FAN_SIZE_MM_RE = re.compile(r"\b(80|92|120|140|170|200|240|280|360|420)\s?MM\b", re.I)
AIRFLOW_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?CFM\b", re.I)
NOISE_DB_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?dB(?:\(A\))?\b", re.I)
SOCKET_LIST_RE = re.compile(r"\b(AM[45]|LGA\s?\d{3,4}|sTR\d?|sWRX\d|TR4|SP\d|FM\d)\b", re.I)
WATER_COOLED_RE = re.compile(r"\b(AIO|LIQUID|WATER\s?COOLER|WATERCOOL)\b", re.I)

# --------------------------------------------------------------------------
# Hebrew prose (Ivory descriptions) — patterns only, values never surface
# --------------------------------------------------------------------------

HE_CORES_RE = re.compile(r"(\d+)\s*ליבות")
HE_THREADS_RE = re.compile(r"(\d+)\s*תהליכונים")
HE_CLOCK_RE = re.compile(r"([\d.]+)\s*GHz\s*-\s*([\d.]+)\s*GHz")
HE_COOLER_RE = re.compile(r"כולל\s*מאוורר")
HE_NO_COOLER_RE = re.compile(r"ללא\s*מאוורר|בלי\s*מאוורר")

# --------------------------------------------------------------------------
# Small helpers (pure text -> token)
# --------------------------------------------------------------------------


def socket_from_text(text: str) -> str | None:
    # Search the text WITHOUT parentheticals first: "AMD SP5 (LGA6096)" is an
    # SP5 board, but reading the package name in the parentheses stamped 45
    # products with a socket that does not exist as a platform.
    match = SOCKET_RE.search(_PARENTHETICAL_RE.sub(" ", text)) or SOCKET_RE.search(text)
    if match:
        return re.sub(r"\s+", "", match.group(1)).upper()
    match = NUMERIC_SOCKET_RE.search(text)
    if match:
        return NUMERIC_SOCKET.get(match.group(1))
    return None


def form_factor(text: str) -> str | None:
    for pattern, label in FORM_FACTOR_PATTERNS:
        if pattern.search(text):
            return label
    return None


def case_form_factor(text: str) -> str | None:
    for pattern, label in CASE_FORM_FACTOR_PATTERNS:
        if pattern.search(text):
            return label
    return form_factor(text)


def wifi(text: str) -> tuple[bool | None, str | None]:
    match = WIFI_STD_RE.search(text)
    if match:
        return True, ("WIFI" + match.group(1) + (match.group(2) or "")).upper()
    if WIFI_RE.search(text):
        return True, None
    return None, None


def ddr(text: str) -> str | None:
    match = DDR_RE.search(text)
    return f"DDR{match.group(1).upper()}" if match else None


def capacity_gb(text: str) -> int | None:
    """'1TB' / '500 GB' -> integer GB (TB counts as 1000, like the vendors)."""
    match = CAPACITY_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    gb = int(value * 1000) if match.group(2).upper() == "TB" else int(value)
    return gb if 1 <= gb <= 30000 else None


def revision(text: str) -> str | None:
    match = re.search(r"\b[Rr](\d+)\b", text)
    if match:
        return f"R{match.group(1)}"
    match = V_REVISION_RE.search(text)
    if match:
        return f"V{match.group(1)}"
    match = REVISION_RE.search(text)
    if match:
        return f"REV{match.group(1)}"
    if re.search(r"\bIII\b", text):
        return "V3"
    if re.search(r"\bII\b", text):
        return "V2"
    return None
