"""
scraper/extractors.py

Phase 2B: structured attribute extraction, text-only.

Confirmed (Aug 2026, real Ivory ws/get sample inspected): Ivory's payload
has no structured compatibility fields at all - title/description are
Hebrew marketing text, and cuts/properCuts are opaque internal filter-facet
IDs we have no lookup table for. So this runs purely on
enriched["match_text"], which matching.py builds uniformly for every
vendor (vendor_sku + title_raw) - no vendor-specific payload parsing.

Only motherboard and CPU are fully modeled (they carry the socket, which
Phase 3 needs first for CPU<->motherboard compatibility). Other categories
get a couple of cheap high-confidence fields. Expand after Phase 3
exercises this end to end (plan §13: build incrementally).
"""

from __future__ import annotations
import re

CHIPSET_INFO = {
    "A320": ("AM4", "DDR4"), "B450": ("AM4", "DDR4"), "X470": ("AM4", "DDR4"),
    "A520": ("AM4", "DDR4"), "B550": ("AM4", "DDR4"), "X570": ("AM4", "DDR4"),
    "A620": ("AM5", "DDR5"), "B650": ("AM5", "DDR5"), "X670": ("AM5", "DDR5"),
    "X670E": ("AM5", "DDR5"), "X870": ("AM5", "DDR5"), "X870E": ("AM5", "DDR5"),
    "H610": ("LGA1700", None), "B660": ("LGA1700", None), "H670": ("LGA1700", None),
    "Z690": ("LGA1700", None), "B760": ("LGA1700", None), "H770": ("LGA1700", None),
    "Z790": ("LGA1700", None),
    "B860": ("LGA1851", "DDR5"), "Z890": ("LGA1851", "DDR5"),
}
# Standard public chipset info - verify against real listings before
# trusting fully in Phase 3, not vendor-confirmed.

CHIPSET_RE = re.compile(
    r"\b(X670E|X870E|X870|X670|X570|X470|B860|B760|B660|B650|B550|B450|"
    r"A620|A520|A320|Z890|Z790|Z690|H610)\b", re.I,
)
SOCKET_RE = re.compile(r"\b(LGA\s?\d{3,4}|AM[45])\b", re.I)
DDR_RE = re.compile(r"\bDDR\s?([345])\b", re.I)
WIFI_RE = re.compile(r"\bWI-?FI\b|\bWIRELESS\b", re.I)
WATT_RE = re.compile(r"\b(\d{3,4})\s?W\b")
FORM_FACTOR_PATTERNS = [
    (re.compile(r"\bMINI[- ]?ITX\b|\bITX\b", re.I), "Mini-ITX"),
    (re.compile(r"\bM(?:ICRO)?[- ]?ATX\b|\bMATX\b", re.I), "mATX"),
    (re.compile(r"\bE[- ]?ATX\b", re.I), "EATX"),
    (re.compile(r"\bATX\b", re.I), "ATX"),
]

# AMD Ryzen desktop generation -> socket. First digit after "RYZEN N " is
# the generation for mainstream parts (Threadripper/server excluded).
RYZEN_RE = re.compile(r"\bRYZEN\s*\d?\s*(\d)\d{3}[A-Z]*\b", re.I)
RYZEN_GEN_SOCKET = {
    "1": "AM4", "2": "AM4", "3": "AM4", "4": "AM4", "5": "AM4",
    "7": "AM5", "8": "AM5", "9": "AM5",
}

# Intel Core "iX-NNNNN": 5-digit model, generation = first two digits.
INTEL_5DIGIT_RE = re.compile(r"\bI[3579]\s?-?\s?(\d{2})\d{3}[A-Z]*\b", re.I)
# Older "iX-NNNN": 4-digit model, generation = first digit (gen 6-9 only).
INTEL_4DIGIT_RE = re.compile(r"\bI[3579]\s?-?\s?([6-9])\d{3}[A-Z]*\b", re.I)
INTEL_ULTRA_RE = re.compile(r"\bCORE\s?ULTRA\b", re.I)

INTEL_GEN_SOCKET = {
    "10": "LGA1200", "11": "LGA1200",
    "12": "LGA1700", "13": "LGA1700", "14": "LGA1700",
    "6": "LGA1151", "7": "LGA1151", "8": "LGA1151", "9": "LGA1151",
}


def _form_factor(text: str) -> str | None:
    for rx, label in FORM_FACTOR_PATTERNS:
        if rx.search(text):
            return label
    return None


def _parse_motherboard(text: str) -> dict:
    a = {}
    chipset_m = CHIPSET_RE.search(text)
    chipset = chipset_m.group(1).upper() if chipset_m else None
    if chipset:
        a["chipset"] = chipset

    known_socket, known_mem = CHIPSET_INFO.get(chipset or "", (None, None))
    socket_m = SOCKET_RE.search(text)
    socket = socket_m.group(1).upper().replace(" ", "") if socket_m else known_socket
    if socket:
        a["socket"] = socket

    ddr_m = DDR_RE.search(text)
    mem = f"DDR{ddr_m.group(1)}" if ddr_m else known_mem
    if mem:
        a["memory_type"] = mem

    ff = _form_factor(text)
    if ff:
        a["form_factor"] = ff
    if WIFI_RE.search(text):
        a["wifi"] = True

    return a


def _parse_cpu(text: str) -> dict:
    a = {}

    m = RYZEN_RE.search(text)
    if m and m.group(1) in RYZEN_GEN_SOCKET:
        a["socket"] = RYZEN_GEN_SOCKET[m.group(1)]
        return a

    if INTEL_ULTRA_RE.search(text):
        a["socket"] = "LGA1851"
        return a

    m = INTEL_5DIGIT_RE.search(text)
    if m and m.group(1) in INTEL_GEN_SOCKET:
        a["socket"] = INTEL_GEN_SOCKET[m.group(1)]
        return a

    m = INTEL_4DIGIT_RE.search(text)
    if m and m.group(1) in INTEL_GEN_SOCKET:
        a["socket"] = INTEL_GEN_SOCKET[m.group(1)]

    return a


def _parse_psu(text: str) -> dict:
    w = WATT_RE.search(text)
    return {"wattage_w": int(w.group(1))} if w else {}


def _parse_memory(text: str) -> dict:
    m = DDR_RE.search(text)
    return {"memory_type": f"DDR{m.group(1)}"} if m else {}


def _parse_case(text: str) -> dict:
    ff = _form_factor(text)
    return {"form_factor": ff} if ff else {}


_PARSERS = {
    "motherboard": _parse_motherboard,
    "cpu": _parse_cpu,
    "psu": _parse_psu,
    "memory": _parse_memory,
    "case": _parse_case,
}


def extract_attributes(listing: dict) -> dict:
    category = listing.get("category_normalized") or ""
    text = listing.get("match_text") or ""
    parser = _PARSERS.get(category)
    return parser(text) if parser else {}