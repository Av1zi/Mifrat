"""
specs/canon.py — canonical forms for known-value fields.

Vendors spell the same fact many ways ("Full Modular" / "full-modular" /
"yes", "mATX" / "Micro ATX" / "MATX", "gold" / "80+ Gold", "NVMe" / "SSD").
Without one canonical form the filter rail splits a single choice into
three checkboxes — that is exactly the mess this overhaul removes.

Rules:
- Canonicalization is applied *before* type coercion + range/enum checks
  (values.coerce calls canonicalize first).
- A value we cannot recognize confidently is returned unchanged (coercion
  then rejects it) — never guessed.
- Maps are keyed by (category, field name) with a generic fallback, because
  `form_factor` means different things for a board and an SSD.
"""

from __future__ import annotations

import re

from .schema import CHIPSET_INFO
from .text import NUMERIC_SOCKET

# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------

COLOR_WORDS = (
    "black", "white", "silver", "gray", "grey", "charcoal", "blue", "midnight",
    "red", "pink", "purple", "brown", "gold", "titanium", "green", "yellow",
    "orange",
)
_COLOR_DISPLAY = {"grey": "Gray", "charcoal": "Charcoal", "midnight": "Midnight"}

# Israeli vendors write colors in Hebrew ("שחור | כסוף"). Translating the word
# to its English equivalent first means one color vocabulary downstream, and
# `specs.labels` reuses the same table when cleaning Hebrew detail values.
HE_COLOR_WORDS = {
    "שחור": "black", "לבן": "white", "כסוף": "silver", "אפור": "gray",
    "אדום": "red", "כחול": "blue", "ירוק": "green", "ורוד": "pink",
    "כתום": "orange", "צהוב": "yellow", "סגול": "purple", "חום": "brown",
    "זהב": "gold", "טיטניום": "titanium", "שקוף": "transparent",
}


def translate_hebrew_colors(text: str) -> str:
    for hebrew, english in HE_COLOR_WORDS.items():
        if hebrew in text:
            text = text.replace(hebrew, english)
    return text


def canon_color(value) -> str:
    """Recognized color words in a value ('Black / Silver' -> 'Black / Silver').

    A two-tone case really is two colors, so both are kept (canonical order)
    instead of splitting the filter into two extra single-color options.
    """
    text = translate_hebrew_colors(str(value).strip())
    words = re.findall(r"[A-Za-z]+", text.lower())
    found: list[str] = []
    for word in words:
        for color in COLOR_WORDS:
            if word == color or (len(word) >= 5 and word.startswith(color[:4])
                                 and color in word):
                display = _COLOR_DISPLAY.get(color, color.title())
                if display not in found:
                    found.append(display)
                break
    if not found:
        return text
    if len(found) == 1:
        return found[0]
    return " / ".join(found[:2])


# --------------------------------------------------------------------------
# Brands
# --------------------------------------------------------------------------

# Carried over verbatim from the pre-overhaul extractors (GPU board partners,
# memory lines, cooling/case/PSU/storage brands) so display names don't churn.
BRANDS = {
    "asus": "ASUS", "gigabyte": "Gigabyte", "aorus": "Gigabyte",
    "msi": "MSI", "inno3d": "Inno3D", "inno3": "Inno3D",
    "arktek": "ARKTEK", "zotac": "ZOTAC", "pny": "PNY",
    "sapphire": "Sapphire", "xfx": "XFX", "asrock": "ASRock",
    "palit": "Palit", "gainward": "Gainward", "evga": "EVGA",
    "galax": "GALAX", "kfa2": "KFA2", "leadtek": "Leadtek",
    "maxsun": "Maxsun", "colorful": "Colorful", "powercolor": "PowerColor",
    "nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel",
    # memory
    "g.skill": "G.Skill", "gskill": "G.Skill", "ripjaws": "G.Skill",
    "trident": "G.Skill", "flare": "G.Skill",
    "corsair": "Corsair", "vengeance": "Corsair",
    "kingston": "Kingston", "fury": "Kingston", "beast": "Kingston",
    "hyperx": "Kingston", "samsung": "Samsung", "crucial": "Crucial",
    "ballistix": "Crucial", "micron": "Crucial", "adata": "ADATA", "xpg": "ADATA",
    "teamgroup": "TeamGroup", "t-force": "TeamGroup", "tforce": "TeamGroup",
    "silicon power": "Silicon Power", "siliconpower": "Silicon Power",
    "patriot": "Patriot", "viper": "Patriot", "sk hynix": "SK Hynix",
    "hynix": "SK Hynix", "klevv": "Klevv", "apacer": "Apacer",
    "transcend": "Transcend", "oscoo": "OSCOO", "gloway": "Gloway",
    "thermaltake": "Thermaltake", "timetec": "Timetec", "lexar": "Lexar",
    "geil": "GeIL", "v-color": "V-Color", "vcolor": "V-Color",
    # cooling / cases / power / storage
    "noctua": "Noctua", "be quiet": "be quiet!", "bequiet": "be quiet!",
    "arctic": "ARCTIC", "thermalright": "Thermalright", "deepcool": "DeepCool",
    "cooler master": "Cooler Master", "coolermaster": "Cooler Master",
    "lian li": "Lian Li", "lianli": "Lian Li", "nzxt": "NZXT",
    "fractal design": "Fractal Design", "fractal": "Fractal Design",
    "phanteks": "Phanteks", "montech": "Montech", "antec": "Antec",
    "seasonic": "Seasonic", "super flower": "Super Flower", "fsp": "FSP",
    "silverstone": "SilverStone", "chieftec": "Chieftec", "gigant": "Gigant",
    "sandisk": "SanDisk", "seagate": "Seagate",
    "western digital": "Western Digital", "wd": "Western Digital",
    "toshiba": "Toshiba", "hiksemi": "Hiksemi", "netac": "Netac",
    "kingbank": "KingBank", "sapphire tech": "Sapphire",
}


def canon_brand(value) -> str:
    text = str(value).strip()
    key = re.sub(r"\s+", " ", text.lower())
    if key in BRANDS:
        return BRANDS[key]
    inner = re.sub(r"[^a-z0-9 ]", "", key)
    if inner in BRANDS:
        return BRANDS[inner]
    return text


# --------------------------------------------------------------------------
# Form factors (per category: the same field name means different things)
# --------------------------------------------------------------------------

_MB_FORM_FACTORS = {
    "atx": "ATX", "eatx": "EATX", "e-atx": "EATX", "xl-atx": "XL-ATX",
    "matx": "Micro-ATX", "m-atx": "Micro-ATX", "micro-atx": "Micro-ATX",
    "micro atx": "Micro-ATX", "microatx": "Micro-ATX", "uatx": "Micro-ATX",
    "itx": "Mini-ITX", "mini-itx": "Mini-ITX", "mini itx": "Mini-ITX",
    "mini-dtx": "Mini-DTX", "thin mini-itx": "Thin Mini-ITX",
    "ssi-eeb": "SSI-EEB", "ssi eeb": "SSI-EEB", "eeb": "SSI-EEB",
    "ssi-ceb": "SSI-CEB",
}


def canon_form_factor_mb(value) -> str:
    key = re.sub(r"\s+", " ", str(value).strip().lower()).replace("_", "-")
    return _MB_FORM_FACTORS.get(key, str(value).strip())


_STORAGE_FORM_FACTORS = {
    "m.2": "M.2", "m2": "M.2", "m.2 2280": "M.2-2280", "m2 2280": "M.2-2280",
    "m.2-2280": "M.2-2280", "2.5": '2.5"', '2.5"': '2.5"',
    "3.5": '3.5"', '3.5"': '3.5"', "3.5 inch": '3.5"', "u.2": "U.2",
    "u.3": "U.3", "pcie add-in card": "PCIe Add-In Card", "aik": "PCIe Add-In Card",
}


def canon_storage_form_factor(value) -> str:
    key = re.sub(r"\s+", " ", str(value).strip().lower())
    return _STORAGE_FORM_FACTORS.get(key, str(value).strip())


# Vendor pages print the manufacturer inside the lineup name ("AMD EPYC",
# "Intel Core i5"); the site's `series` facet is vendor-free ("EPYC",
# "Core i5"), so a TMS detail row must not fork the filter into two entries.
_SERIES_VENDOR_WORDS = ("AMD", "INTEL", "NVIDIA", "ASUS", "MSI", "GIGABYTE",
                        "ASROCK", "ASROCK RACK")


def canon_series(value) -> str:
    text = re.sub(r"\s+", " ", str(value).strip())
    for word in _SERIES_VENDOR_WORDS:
        if text.upper().startswith(f"{word} "):
            return text[len(word) + 1:].strip()
    return text


def canon_form_factor_memory(value) -> str:
    key = str(value).strip().lower()
    if "so" in key and "dimm" in key:
        return "SO-DIMM"
    if "dimm" in key:
        return "DIMM"
    return str(value).strip()


FIELD_FORM_FACTOR = {
    "motherboard": canon_form_factor_mb,
    "storage": canon_storage_form_factor,
    "memory": canon_form_factor_memory,
}

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

_PSU_TYPE_CANON = {
    "atx": "ATX", "atx12v": "ATX", "sfx": "SFX", "sfx-l": "SFX-L", "sfxl": "SFX-L",
    "tfx": "TFX", "flex atx": "Flex ATX", "flex": "Flex ATX",
    "micro atx": "Micro ATX", "matx": "Micro ATX", "mini itx": "Mini ITX",
    "1u": "1U",
}


def canon_psu_type(value) -> str:
    return _PSU_TYPE_CANON.get(str(value).strip().lower(), str(value).strip())


_EFFICIENCY_CANON = {
    "white": "80+ White", "80+ white": "80+ White", "80plus white": "80+ White",
    "bronze": "80+ Bronze", "80+ bronze": "80+ Bronze", "80plus bronze": "80+ Bronze",
    "silver": "80+ Silver", "80+ silver": "80+ Silver", "80plus silver": "80+ Silver",
    "gold": "80+ Gold", "80+ gold": "80+ Gold", "80plus gold": "80+ Gold",
    "platinum": "80+ Platinum", "80+ platinum": "80+ Platinum",
    "80plus platinum": "80+ Platinum",
    "titanium": "80+ Titanium", "80+ titanium": "80+ Titanium",
    "80plus titanium": "80+ Titanium",
}

# The tier word inside a longer certification blob ("80 PLUS Gold (according
# to manufacturer, 115V)"). Requires the 80 PLUS lead so a bare "platinum"
# (a legit spelling on its own) still takes the plain-key path.
_EFFICIENCY_TIER_RE = re.compile(
    r"80\s?\+?\s*(?:plus\s*)?(white|bronze|silver|gold|platinum|titanium)\b", re.I)


def canon_efficiency(value) -> str:
    text = re.sub(r"\s+", " ", str(value).strip())
    # "80 PLUS Gold (according to manufacturer, 115V), ETA-Gold (…)" — Plonter
    # wraps the tier in vendor commentary; the tier word is the fact.
    tier = _EFFICIENCY_TIER_RE.search(text)
    if tier:
        return _EFFICIENCY_CANON.get(tier.group(1).lower(), text)
    key = text.lower()
    key = re.sub(r"^80\s?\+?\s*", "80+ ", key) if key.startswith("80") else key
    return _EFFICIENCY_CANON.get(key, text)


def canon_modular(value) -> str:
    """'Full Modular' -> 'full'. A bare 'modular'/'yes' is genuinely
    ambiguous (could be semi), so it stays as-is and fails the enum check
    rather than inventing a fact."""
    key = str(value).strip().lower()
    if key.startswith("full") or key in ("yes", "true", "1"):
        return "full"
    if key.startswith("semi"):
        return "semi"
    if key.startswith(("no", "non")) or key in ("false", "0"):
        return "no"
    return str(value).strip()


_PACKAGING_CANON = {
    "box": "boxed", "boxed": "boxed", "retail": "boxed",
    "tray": "tray", "oem": "oem", "bulk": "bulk", "mpk": "tray",
}


def canon_packaging(value) -> str:
    key = str(value).strip().lower()
    if key in _PACKAGING_CANON:
        return _PACKAGING_CANON[key]
    if "tray" in key or "oem" in key:
        return "tray"
    if "box" in key or "retail" in key:
        return "boxed"
    return str(value).strip()


_STORAGE_TYPE_CANON = {
    "ssd": "SSD", "nvme": "SSD", "nvme ssd": "SSD", "m.2": "SSD",
    "hdd": "HDD", "hard drive": "HDD", "hard disk": "HDD",
    "sshd": "Hybrid", "hybrid": "Hybrid",
}

# TMS case drive-bay shorthand: "2+2" = 2 dedicated + 2 shared bays -> 4
# (a bay sold as shared can still take a drive, so the sum is the fact).
_BAY_SUM_RE = re.compile(r"^(\d)\s*\+\s*(\d)$")


def canon_bay_count(value):
    if isinstance(value, str):
        match = _BAY_SUM_RE.match(value.strip())
        if match:
            return int(match.group(1)) + int(match.group(2))
    return value


def canon_storage_type(value) -> str:
    key = re.sub(r"\s+", " ", str(value).strip().lower())
    if key in _STORAGE_TYPE_CANON:
        return _STORAGE_TYPE_CANON[key]
    if "ssd" in key or "nvme" in key:
        return "SSD"
    if "sshd" in key or "hybrid" in key:
        return "Hybrid"
    if "hdd" in key or "hard" in key:
        return "HDD"
    return str(value).strip()


def canon_storage_interface(value) -> str:
    """Vendor interface strings: expand truncated tokens, keep real ones
    ("M.2 PCIe 5.0 x4") untouched so the precise form survives."""
    text = re.sub(r"\s+", " ", str(value).strip())
    # Vendors/datasets print the PCIe lane suffix as "X4"/"X16"; keep one form.
    text = re.sub(r"\bX(\d+)\b", r"x\1", text)
    low = text.lower()
    if low in ("nvm", "nvme", "m.2 nvme", "m2 nvme"):
        return "NVMe"
    if low in ("sata", "sata iii", "sata 6gb/s", "sata 6.0 gb/s", "sata3"):
        return "SATA 6.0 Gb/s"
    if low in ("pcie", "pci-e", "pci express"):
        return "PCIe"
    if low in ("sas",):
        return "SAS"
    return text


def canon_memory_type(value) -> str:
    match = re.search(r"DDR\s?([345])", str(value), re.I)
    return f"DDR{match.group(1)}" if match else str(value).strip()


# A socket TOKEN anywhere in the value is the socket; everything else in the
# string is packaging noise. AMD prints the socket name first and its physical
# package second ("AMD AM5 (LGA1718)"), so parentheticals are dropped before
# the search — reading them produced phantom sockets (LGA1718, LGA6096) that
# ranked among the most common CPU sockets on the site.
# The lookahead (not \b) closes the token so "FM2+" keeps its plus sign.
_SOCKET_TOKEN_RE = re.compile(
    r"\b(sTRX\d+|sWRX\d+|sTR\d+|STRX\d+|SWRX\d+|STR\d+|TRX\d+|TR\d|"
    r"SP\d+|AM\d\+?|FM\d\+?|LGA\s?\d{3,4}|BGA\d+|PGA\d+|G\d{1,2})(?![A-Za-z0-9])",
    re.I,
)
_SOCKET_FILLER_RE = re.compile(
    r"\b(?:SOCKET|SOC\w*|CPU|AMD|INTEL|ASUS|MSI|GIGABYTE|ASROCK|BIOSTAR)\b",
    re.I,
)
# "LGA2011-3" vs "LGA2011-0" are different platforms (DDR4 vs DDR3).
# No leading \b: it must also match the canonical "LGA2011-3" (where the
# digit run follows a letter), or canonicalizing twice would erase the suffix.
_SOCKET_LGA_VARIANT_RE = re.compile(r"(?:LGA\s?)?(\d{4})\s*-\s*(\d)\b", re.I)
_SOCKET_ALIASES = (("STRX", "sTRX"), ("STR", "sTR"), ("SWRX", "sWRX"))


def _canon_socket_token(raw: str) -> str:
    text = re.sub(r"\s+", "", raw).upper()
    for alias, display in _SOCKET_ALIASES:
        if text.startswith(alias):
            return display + text[len(alias):]
    return text


def canon_socket(value) -> str:
    """One spelling per socket: 'AMD AM5 (LGA1718)' -> 'AM5', '1851' -> 'LGA1851'."""
    text = re.sub(r"\s+", " ", str(value).strip()).upper()
    if not text:
        return text
    prefix = ""
    count = re.match(r"^(\d)\s*X\s+", text)
    if count:
        # "2 x LGA2011" is a dual-socket board, a different slot than LGA2011.
        prefix = f"{count.group(1)} x "
        text = text[count.end():]
    text = _SOCKET_FILLER_RE.sub(" ", re.sub(r"\([^)]*\)", " ", text))
    text = re.sub(r"\s+", " ", text).strip()
    variant = _SOCKET_LGA_VARIANT_RE.search(text)
    if variant and variant.group(1) in NUMERIC_SOCKET:
        return f"{prefix}LGA{variant.group(1)}-{variant.group(2)}"
    token = _SOCKET_TOKEN_RE.search(text)
    if token:
        return prefix + _canon_socket_token(token.group(1))
    digits = re.search(r"\b(\d{3,4})\b", text)
    if digits and digits.group(1) in NUMERIC_SOCKET:
        return prefix + NUMERIC_SOCKET[digits.group(1)]
    return prefix + text


def canon_socket_list(value) -> list[str]:
    """Cooler socket lists are sold as groups ('1150/1151/1155/1156/1200',
    'AM2/AM2+/AM3/AM3+'). Split them so the compatibility filter offers one
    entry per real socket instead of a dozen vendor groupings."""
    parts = [str(part) for part in value] if isinstance(value, (list, tuple)) else [str(value)]
    out: list[str] = []
    for part in parts:
        for piece in re.split(r"\s*[/,;|]\s*|\s{2,}", part):
            piece = piece.strip()
            if not piece:
                continue
            socket = canon_socket(piece)
            if socket and socket not in out:
                out.append(socket)
    return out


# Vendor prefixes glued onto a chipset token (Plonter prints "AMDB850",
# "INTELB760"). Stripped only when the remainder is a known chipset, so a
# genuine token is never mangled.
_CHIPSET_VENDOR_PREFIXES = ("AMDRYZEN", "AMDPROM", "AMD", "INTEL", "ASUS", "MSI")


def _chipset_candidates(text: str):
    """Ordered candidate readings of a normalized chipset token."""
    yield text
    # Strip a form-factor/suffix letter the vendor glued on ("B760M" -> B760).
    if len(text) > 3:
        yield text[:-1]
    for prefix in _CHIPSET_VENDOR_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            rest = text[len(prefix):]
            yield rest
            if len(rest) > 3:
                yield rest[:-1]


def canon_chipset(value) -> str:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    for candidate in _chipset_candidates(text):
        if candidate in CHIPSET_INFO:
            return candidate
    # Vendors concatenate the supported-chipset list into one cell
    # ("AMDB850AMDX670", "INTELH810INTELH610", "Z890INTELZ890",
    # "C612PCH", "B760EXPRESS"). Split on the glued brand/suffix words and
    # take the first segment that is a known chipset — a board carries one,
    # and vendors list the board's own chipset first.
    segments = re.split(r"AMD|INTEL|ASUS|MSI|EXPRESS|PCH", text)
    for segment in segments:
        for candidate in _chipset_candidates(segment):
            if candidate in CHIPSET_INFO:
                return candidate
    return text


def canon_wireless(value) -> str:
    """Board wireless: 'yes'/'no' become 'Yes'/'None'; standards are kept."""
    text = str(value).strip()
    low = text.lower()
    match = re.search(r"wi-?fi\s?([67])\s?(e)?", low)
    if match:
        return f"Wi-Fi {match.group(1)}{(match.group(2) or '').upper()}"
    if low in ("yes", "y", "true", "1", "wifi", "wi-fi", "wireless"):
        return "Yes"
    if low in ("no", "n", "false", "0", "none", "without"):
        return "None"
    return text


# --------------------------------------------------------------------------
# GPU chipsets
# --------------------------------------------------------------------------

# The reference data spells a GPU chip PCPP-style ("GeForce RTX 5070",
# "Radeon RX 9070 XT", "RTX A4000"); vendors spell the same chip
# "GEFORCE RTX5070", "RTX 5070" or "NVIDIA GeForce RTX 5070". Without one
# canonical form the filter rail showed three separate chips for one part.
_GPU_FAMILY = {
    "RTX": "GeForce RTX", "GTX": "GeForce GTX", "GTS": "GeForce GTS",
    "GT": "GeForce GT", "MX": "GeForce MX",
    "RX": "Radeon RX", "HD": "Radeon HD",
    "R9": "Radeon R9", "R7": "Radeon R7", "R5": "Radeon R5",
    "RADEON": "Radeon", "ARC": "Arc", "QUADRO": "Quadro",
    "TESLA": "Tesla", "FIREPRO": "FirePro",
}
# Pro/compute parts stay prefixless in the reference data: "RTX A4000".
_GPU_PREFIXLESS_RE = re.compile(r"^(?:A\d{3,4}|PRO\b|T\d{1,2}\b|GV\s?\d|M\s?\d{4})", re.I)
# "RTX A 4000"/"R9 Nano" style: re-glue a single-letter model prefix that the
# letter/digit split above pulled apart.
_GPU_SINGLE_LETTER_RE = re.compile(r"\b([A-Z]) (\d{1,4})(?![0-9A-Za-z])")
_GPU_WORD_CASE = {"TI": "Ti", "SUPER": "Super", "MAX-Q": "Max-Q", "NANO": "Nano",
                  "PRO": "Pro", "SE": "SE", "XT": "XT", "XTX": "XTX",
                  "GRE": "GRE", "OC": "OC", "LP": "LP", "D": "D", "G": "G"}
_GPU_VENDOR_WORDS = ("NVIDIA", "GEFORCE", "AMD", "ATI", "INTEL", "VGA")


def canon_gpu_chipset(value) -> str:
    text = re.sub(r"[^A-Za-z0-9.+\- ]", " ", str(value)).upper()
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return str(value).strip()
    for word in _GPU_VENDOR_WORDS:
        if text.startswith(word + " "):
            text = text[len(word) + 1:].strip()
    # Glued model numbers: "RTX5070" -> "RTX 5070", "RX9070XT" -> "RX 9070 XT".
    text = re.sub(r"(?<=[A-Z]{2})(?=\d)", " ", text)
    # Split a glued suffix ("RX9070XT" -> "RX 9070 XT") but never a VRAM
    # suffix ("GTX 1060 6GB" stays one token).
    text = re.sub(r"(?<=\d)(?=(?:TI|SUPER|XTX|XT|GRE|SE)\b)", " ", text)
    text = _GPU_SINGLE_LETTER_RE.sub(r"\1\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Anything that still looks like a listing dump (a second brand word, five
    # tokens, no model number) is left alone so validation can drop it.
    if len(text) > 32 or not re.search(r"\d", text) or len(text.split()) > 5:
        return str(value).strip()
    if any(re.search(rf"\b{word}\b", text) for word in _GPU_VENDOR_WORDS):
        return str(value).strip()
    words = text.split()
    head, model_words = words[0], words[1:]
    family = _GPU_FAMILY.get(head)
    if family is None:
        # A family token with the model glued on ("RTXA4000" -> RTX + A4000).
        for key in sorted(_GPU_FAMILY, key=len, reverse=True):
            if head.startswith(key) and len(head) > len(key):
                family, model_words = _GPU_FAMILY[key], [head[len(key):]] + model_words
                head = key
                break
    if family is None:
        return text
    model = " ".join(_GPU_WORD_CASE.get(word, word) for word in model_words)
    model = _GPU_SINGLE_LETTER_RE.sub(r"\1\2", model)
    if not model or len([word for word in model.split() if word.isdigit()]) > 2:
        return str(value).strip()
    if _GPU_PREFIXLESS_RE.match(model):
        # Pro/compute parts keep the reference spelling: "RTX A4000", not
        # "GeForce RTX A4000".
        return f"{head} {model}"
    return f"{family} {model}"


def canon_gpu_memory_type(value) -> str:
    match = re.search(r"(G?DDR\dX?|HBM\d?)", str(value), re.I)
    return match.group(1).upper() if match else str(value).strip()


def canon_lighting(value) -> str:
    """Lighting is a string facet; 'yes'/'no' become 'ARGB'/'None' only when
    the vendor gave no standard, so the filter never shows 'yes' next to 'RGB'."""
    low = str(value).strip().lower()
    if low in ("yes", "y", "true", "1", "argb", "addressable rgb"):
        return "ARGB"
    if low in ("no", "n", "false", "0", "none", "without", "non-rgb"):
        return "None"
    return str(value).strip()


def canon_speed_string(generation: int | str | None, mhz: int | float | None) -> str | None:
    """PCPP-style memory speed label: (5, 6000) or ("DDR5", 6000) -> 'DDR5-6000'."""
    if not mhz:
        return None
    if generation is None:
        return None
    if isinstance(generation, str):
        match = re.search(r"([345])", generation)
        if not match:
            return None
        digit = match.group(1)
    else:
        digit = str(int(generation))
    return f"DDR{digit}-{int(mhz)}"


# Generic field-name rules (applied for every category unless overridden).
_GENERIC_RULES = {
    "manufacturer": canon_brand,
    "color": canon_color,
    "series": canon_series,
    "socket": canon_socket,
    "efficiency": canon_efficiency,
    "modular": canon_modular,
    "packaging": canon_packaging,
    "wireless": canon_wireless,
    "lighting": canon_lighting,
}

# Category-specific overrides: (category, field name) -> rule.
# `chipset` only canonicalizes for motherboards: a GPU chipset is a marketing
# name ("GeForce RTX 5070 Ti") and must keep its spaces and case.
_CATEGORY_RULES = {
    ("motherboard", "chipset"): canon_chipset,
    ("motherboard", "memory_type"): canon_memory_type,
    ("memory", "memory_type"): canon_memory_type,
    ("gpu", "memory_type"): canon_gpu_memory_type,
    ("gpu", "chipset"): canon_gpu_chipset,
    ("psu", "type"): canon_psu_type,
    ("storage", "type"): canon_storage_type,
    ("storage", "interface"): canon_storage_interface,
    ("storage", "memory_type"): canon_memory_type,
    ("accessories", "lighting"): canon_lighting,
    ("case", "drive_bays_35"): canon_bay_count,
    ("case", "drive_bays_25"): canon_bay_count,
}


def canonicalize(field, value, category: str | None = None):
    """Apply the canonical form for (category, field) to `value`.

    Structural types (lists/dicts/numbers/bools) pass through untouched: they
    have no ambiguous spellings to normalize.
    """
    if field.name == "sockets":
        return canon_socket_list(value)
    if isinstance(value, (list, tuple, dict, int, float, bool)):
        return value
    if field.name == "form_factor":
        rule = FIELD_FORM_FACTOR.get(category or "")
        return rule(value) if rule else value
    rule = _CATEGORY_RULES.get((category or "", field.name)) or _GENERIC_RULES.get(field.name)
    return rule(value) if rule else value
