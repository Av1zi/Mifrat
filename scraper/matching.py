"""
Phase 2 matching helpers.

This module enriches raw vendor listings and builds canonical products.

Matching hierarchy:
1. Manual confirmed merges from data/matching/manual_products.json
2. Exact MPN / manufacturer part number matches
3. Exact normalized vendor SKU matches
4. Singleton products for everything else
5. Optional fuzzy review suggestions, not auto-merged by default

This intentionally avoids silently merging uncertain products.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import unquote

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

# Photo picking (Sep 2026): which offer's image becomes the product cover was
# previously "the first offer with any URL" — see scraper/image_score.py for
# the scoring that replaced it.
try:
    from scraper.image_score import pick_image
    from scraper.image_urls import candidate_urls
except ImportError:
    from image_score import pick_image  # type: ignore[no-redef]
    from image_urls import candidate_urls  # type: ignore[no-redef]

# The spec system owns attribute extraction (scraper/specs/). These names are
# kept so the rest of this module reads exactly as before: extract_attributes()
# now returns the DERIVED view of the typed spec sheet (specs/legacy.py), and
# the two canonicalization helpers moved with it.
try:
    from scraper.specs.api import extract_attributes
    from scraper.specs.api import canonicalize_filter_values as _canonicalize_filter_values
    from scraper.specs.api import unify_duplicate_attributes as _unify_duplicate_attributes
except ImportError:
    from specs.api import extract_attributes
    from specs.api import canonicalize_filter_values as _canonicalize_filter_values
    from specs.api import unify_duplicate_attributes as _unify_duplicate_attributes

# Optional: docyx/pc-part-dataset reference specs (Aug 2026, see
# DECISIONS.md). Never required for the core pipeline — if it can't be
# imported (or the index hasn't been built), Tier 0 is skipped with a loud warning
# below skips itself entirely and the catalog builds exactly as before.
# Reference specs (docyx/pc-part-dataset + PC Kombo) are merged into
# `product["specs"]` by scraper/specs/build.py, which matches with a strict
# per-category anchor cross-check. matching.py no longer attaches reference
# data itself: a score-only fuzzy attach was exactly the wrong-spec risk the
# spec overhaul removed.

try:
    from scraper.pckombo import find_by_mpn as _pckombo_find_by_mpn
    from scraper.pckombo import load_index as _pckombo_load_index
except ImportError:
    try:
        from pckombo import find_by_mpn as _pckombo_find_by_mpn
        from pckombo import load_index as _pckombo_load_index
    except ImportError:
        _pckombo_find_by_mpn = None
        _pckombo_load_index = None


HEBREW = re.compile(r"[\u0590-\u05FF]+")


CATEGORY_ALIASES = {
    # Motherboards
    "motherboard": "motherboard",
    "motherboards": "motherboard",

    # Cases
    "case": "case",
    "cases": "case",
    "computercase": "case",
    "computercases": "case",

    # Memory
    "memory": "memory",
    "ram": "memory",

    # CPU
    "cpu": "cpu",
    "cpus": "cpu",

    # GPU
    "gpu": "gpu",
    "displayadapter": "gpu",
    "displayadapters": "gpu",
    "graphicscard": "gpu",

    # PSU
    "psu": "psu",
    "powersupply": "psu",
    "powersupplies": "psu",

    # Case fans
    "casefan": "case_fan",
    "casefans": "case_fan",

    # Liquid cooling
    "liquidcooling": "aio",
    "aio": "aio",

    # General cooling
    "fansandcoolingsolutions": "cooling",
    "fans": "cooling",
    "fan": "cooling",
    "cooling": "cooling",
    "coolingother": "cooling_other",
    "othercooling": "cooling_other",

    # Thermal paste
    "thermalpaste": "thermal_paste",

    # Storage
    "storage": "storage",
    "harddrives": "storage",
    "ssd": "storage",

        # --- storage gaps (1PC "harddrive", TMS/Ivory "hdd") ---
    "hdd": "storage",
    "harddrive": "storage",
    "solidstatedrive": "storage",
    "solidstatedrives": "storage",
    "nvme": "storage",
    "m2": "storage",
    # --- CPU-cooling gaps (TMS "cpu cooler", 1PC "cpu_cooling",
    #     Ivory "cpu_cooler_air" / "cpu_cooler_aio") ---
    # Generic umbrella guesses ("cpu cooler", "cpu cooling") stay ambiguous
    # ("cooling") so the title classifier decides air vs liquid vs fan vs
    # accessory per listing. Only explicit air/aio guesses map directly.
    # (Mapping the umbrella straight to cooler_air misfiled every TMS/1PC
    # liquid cooler whose title lacked an English liquid keyword — e.g.
    # HydroShift Hebrew titles — as air.)
    "cpucooler": "cooling",
    "cpucoolers": "cooling",
    "cpucoling": "cooling",
    "cpucooling": "cooling",
    "cpucoolerair": "cooler_air",
    "aircooler": "cooler_air",
    "aircoolers": "cooler_air",
    "cpucooleraio": "aio",
    "liquidcooler": "aio",
    "liquidcoolers": "aio",
    "watercooler": "aio",
    "allinonecooler": "aio",
    # --- PSU / GPU variants ---
    "psus": "psu",
    "powersupplyunit": "psu",
    "powersupplyunits": "psu",
    "videocard": "gpu",
    "videocards": "gpu",
    "graphicscards": "gpu",
    "gpus": "gpu",
    # --- not build parts -> other ---
    "monitor": "other",
    "monitors": "other",
    "laptop": "other",
    "laptops": "other",
    "tablet": "other",
    "tablets": "other",
}


ACCESSORY_CATEGORIES = {
    "thermal_paste",
    "fan_controller",
    "rgb_lighting",
    "cooler_accessory",
    # Case mods (LAN216 USB/ARGB modules, front-panel controls): own subtype
    # so they filter separately from cooler mounts and fan hubs, while still
    # living under the single `accessories` umbrella category.
    "case_accessory",
}


BRAND_ALIASES = {
    # Motherboard / GPU / general brands
    "asus": "ASUS",
    "gigabyte": "Gigabyte",
    "msi": "MSI",
    "asrock": "ASRock",
    "sapphire": "Sapphire",
    "maxsun": "MAXSUN",
    "afox": "AFOX",
    "zotac": "ZOTAC",
    "inno3d": "Inno3D",
    "powercolor": "PowerColor",
    "nvidia": "NVIDIA",
    "palit": "Palit",
    "xfx": "XFX",
    "intel": "Intel",
    "amd": "AMD",

    # Cases / cooling
    "fractal design": "Fractal Design",
    "fractal": "Fractal Design",
    "lian li": "Lian Li",
    "lian-li": "Lian Li",
    "corsair": "Corsair",
    "be quiet": "be quiet!",
    "arctic": "Arctic",
    "noctua": "Noctua",
    "cooler master": "Cooler Master",
    "coolermaster": "Cooler Master",
    "deepcool": "Deepcool",
    "zalman": "Zalman",
    "gamdias": "GAMDIAS",
    "antec": "Antec",
    "istarusa": "iStarUSA",
    "supermicro": "Supermicro",
    "silverstone": "SilverStone",
    "havn": "HAVN",
    "cougar": "Cougar",
    "1stplayer": "1stPlayer",
    "nzxt": "NZXT",
    "thermaltake": "Thermaltake",
    "ivory": "Ivory",
    "arktek": "ARKTEK",
    "biostar": "Biostar",

    # Memory
    "kingston": "Kingston",
    "fury": "Kingston",
    "patriot": "Patriot",
    "viper": "Patriot",
    "g.skill": "G.Skill",
    "gskill": "G.Skill",
    "lexar": "Lexar",
    "geil": "GeIL",
    "v-color": "V-Color",
    "vcolor": "V-Color",
    "adata": "ADATA",
    "pny": "PNY",
    "silicon power": "Silicon Power",
    "teamgroup": "TeamGroup",
    "t-force": "TeamGroup",

    # PSU
    "seasonic": "Seasonic",
    "fsp": "FSP",
}


MPN_PATTERNS = [
    # ASUS motherboards / GPUs
    r"90MB[A-Z0-9-]+",
    r"90YV[A-Z0-9-]+",

    # Corsair
    r"CO-90\d{5}-WW",
    r"CC-90\d{5}-WW",
    r"CL-90\d{5}-WW",
    r"CT-90\d{5}-WW",

    # Gigabyte
    r"GV-[A-Z0-9-]+",

    # Kingston / Corsair memory
    r"KF[0-9A-Z-]+",
    r"CMK[0-9A-Z-]+",

    # Fractal cases
    r"FD-C-[A-Z0-9-]+",

    # Cooler Master examples
    r"MAZ-[A-Z0-9-]+",
    r"MAP-[A-Z0-9-]+",
    r"MCM-[A-Z0-9-]+",
    r"MB\d{3}-[A-Z0-9-]+",

    # be quiet!
    r"BW\d{2,3}",
    r"BK\d{2,3}",
    r"BGW\d{2,3}",

    # AMD CPU OPNs
    r"100-\d{8,}[A-Z]*",

    # Antec UPC-style codes
    r"0-761345-\d{5}-\d",

    # Generic barcode / EAN-like identifiers
    r"\b\d{12,14}\b",
]


# --------------------------------------------------------------------------
# Basic normalization
# --------------------------------------------------------------------------

def _compact_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _clean(value: str | None) -> str:
    """
    Clean text for matching.

    - Unescape HTML entities
    - Unicode normalize
    - Remove Hebrew script
    - Keep Latin letters, digits, and useful punctuation
    """
    if value is None:
        return ""

    s = html.unescape(str(value))
    # 1PC's malformed title spans bleed JSON key/value fragments into the
    # title ('NX420 ... Black", "product_short_description": ...'). The real
    # name always precedes the first '",' — cut there (already-poisoned
    # snapshots are cleaned by this; the spider truncates going forward).
    s = s.split('",')[0]
    # Trademark symbols MUST go before NFKC: NFKC folds ™->TM / ®->R,
    # gluing them onto the previous word ("Ryzen™" -> "RYZENTM") and
    # breaking every \b-anchored model regex after it. (Mirrors
    # extractors.clean_text — keep the two in sync.)
    s = re.sub(r"[®™©℗]", " ", s)
    s = unicodedata.normalize("NFKC", s)

    # Common mojibake / trademark noise seen in some feeds.
    s = s.replace("Ö²Â®", " ").replace("\ufffd", " ")

    # Hebrew characters are useful for UI, but usually noise for model matching.
    s = HEBREW.sub(" ", s)

    # Keep letters, numbers, and some punctuation useful for MPNs/models.
    s = re.sub(r"[^A-Za-z0-9#+/.&()-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def canonical_vendor_id(value: str | None) -> str:
    v = str(value or "").lower()
    if v in {"1pc", "onepc"}:
        return "1pc"
    return v


def normalize_price(value):
    """
    Coerce vendor price to integer ILS.

    Handles int, float, string numbers, 1PC floating-point noise,
    and Plonter string prices.
    """
    if value is None or value == "":
        return None

    s = re.sub(r"[^\d.,-]", "", str(value))
    s = s.replace(",", "")

    if not s:
        return None

    try:
        d = Decimal(s)
        return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Category normalization
# --------------------------------------------------------------------------

AIO_TITLE_RE = re.compile(
    # NOTE: bare "hydro" and bare "radiator" deliberately excluded.
    # "Hydro Bearing"/"Fluid Dynamic Bearing" is a fan bearing type found on
    # air coolers (AG400 etc.), and "Thermal Radiator"/"Twin Tower Radiator"
    # is air-tower marketing (PH-TC14PE). Both used to false-positive every
    # air cooler into `aio`. Bare "liquid" counts (AIO titles like "H100i
    # ... Liquid" or "ML240 Vivid liquid" name no cool* word); known air
    # families mislabeled "liquid cooling" by a vendor (BOREAS M2-51D) are
    # rescued by checking AIR first. Spaceless "IllusionLiquid Cooler"
    # still hits via the substring match. Explicit AIO model families listed.
    r"(aio|all[\s\-]*in[\s\-]*one|liquid|water[\s\-]*cool|"
    r"hydroshift|pure loop|kraken|eisbaer|eiswolf|nucleus|masterliquid|"
    r"coreliquid|navis|levante|silent loop|ryujin|ryuo|liquid freezer|"
    r"galahad|ek-aio|coolit|alphacool)",
    re.I,
)
AIR_TITLE_RE = re.compile(
    # NOTE: the generic "CPU/air/tower cooler" phrases are deliberately NOT
    # here — they appear in AIO titles too ("H100i ... Liquid CPU Cooler")
    # and live in _GENERIC_COOLER_PHRASE_RE (checked after AIO) instead.
    # Everything below never appears on a liquid cooler: heatsinks,
    # heatpipes, towers, and air-only model families.
    r"\b(heatsink|heat sinks?|"
    # Plural-aware: "4x 6mm Heat Pipes" must match, not just singular.
    r"heat\s*pipes?|heatpipes?|"
    r"dual tower|twin tower|single tower|"
    r"cnps[\w-]+|burst assassin|"
    r"masterair|gammaxx|boreas|a115|"
    r"peerless assassin|phantom spirit|assassin x|assassin spirit|"
    # Model families with suffixes: the trailing model letters are part of
    # the alternative itself ("NH-U9S", "AG400", "AK500S" must all hit) so
    # the pattern keeps its trailing \b — without it, "freezer i" matches
    # inside the AIO "freezer iii" ("Liquid Freezer III" -> cooler_air).
    r"ak\d{3}[a-z]*|ag\d{3}[a-z]*|aero\s?cool|tjmax|"
    r"nh-[dulp][a-z0-9]*|dark rock|pure rock|shadow rock|"
    r"hyper 212|freezer 3[46]|freezer i\b|freezer e|big shuriken|katana|"
    # ID-Cooling's air line is "Frozn A410/A610" (Frozn + A-series number).
    # Bare "frozen" would also catch Thermalright's Frozen Magic/Warframe/
    # Notte AIOs — those stay liquid.
    r"grandis|ta-?120|ps120|pa120|axp90|ax120|tc14pe|frozn[\s\-]*a\d{3})\b",
    re.I,
)
# Generic cooler phrases shared by air AND liquid titles ("Liquid CPU
# Cooler" is an AIO) — checked only after the AIO pass, so liquid wins.
_GENERIC_COOLER_PHRASE_RE = re.compile(
    r"\b(cpu cooler|air cooler|tower cooler|low[- ]profile cooler)\b", re.I)

# A bare "tower" also appears in case titles ("Mid Tower"), so tower alone
# is never a cooler signal — it only counts with cooler internals nearby.
_TOWER_COOLER_RE = re.compile(
    r"\btowers?\b.{0,60}\b(heat\s*pipes?|heatsink|tdp|cpu|lga|am[45])\b"
    r"|\b(heat\s*pipes?|heatsink|tdp)\b.{0,60}\btowers?\b",
    re.I,
)
# Cooler internals that never appear on a bare case fan: any of these makes
# a listing a CPU cooler, full stop (used to guard the case_fan heuristics
# and the backplate accessory rule below).
_COOLER_INTERNALS_RE = re.compile(
    r"\b(heat\s*pipes?|heatpipes?|heatsinks?|heat\s*sinks?|tower|tdp|"
    r"socket|lga\s*\d+|am[45]|processor|cpu\s*(cooler|fan|cooling))\b",
    re.I,
)
# Corsair's "FRAME 4000D/4500X/5000D" is a case line, not a fan frame.
_CORSAIR_FRAME_CASE_RE = re.compile(
    r"\bframe\s*(4000d|4500x|5000d)\b|\bframe\b.{0,30}\b(case|tower|chassis|atx)\b",
    re.I,
)
# Fan telemetry glued to digits ("1200rpm", "2200RPM") has no word boundary
# before the unit — \brpm\b never matches it. Match digit-glued RPM too.
_RPM_RE = r"(?:pwm|cfm|airflow|\d\s*rpm|\brpm\b)"
# Fan-BUNDLE signals (strict): a hub/controller/remote bundled WITH a sized
# or packed set of fans is still fans ("RX120 120mm PWM ... Requires Hub",
# "Prizm 120 ... 3 in 1 Pack ... Controller", "4x 120mm Trio Ring ... with
# Controller"). Sized/packed evidence only — a bare "fan" word is NOT enough
# here, or every pure port-count splitter ("5-Way 4-pin PWM Fan Splitter",
# "sleeved 3-Way ... to 3 fans") poses as a fan kit. (The looser fan-word
# test lives only in the connector-rule guard below, where over-blocking
# merely falls through to the normal fan branches.)
_FAN_KIT_RE = re.compile(
    r"\b\d{2,3}\s*mm\b"
    r"|\b\d+\s*x\s*fans?\b|\bfans?\b.{0,20}\bx\s*[2-9]\b"
    r"|\b\d+\s*in\s*1\b"
    r"|\b(pack|kit|bundle)\b",
    re.I,
)
# Case signals for the accessory peel-off: form factors/towers, fan arrays,
# glass/windows, and WxHxD case dimensions ("770x225x595mm").
_CASE_LOOK_RE = re.compile(
    r"\b(?:tower|chassis|atx|e-?atx|m-?atx|itx)\b|"
    r"\b\d+x\s*(?:80|92|120|140|170|200)\s*mm\b|"
    r"\bglass\b|\bwindows?\b|"
    r"\b\d{3,4}\s*x\s*\d{3,4}\s*x\s*\d{2,4}\b",
    re.I,
)
_FRAME_ACCESSORY_RE = re.compile(r"\bframes?\b", re.I)
_FAN_LED_RE = re.compile(r"\b(fans?|led|rgb|argb|halo)\b", re.I)
# Generic small-part words: connectors, cables, adapters, control modules.
# Guarded by _BOARD_SIGNAL_RE so board/case spec prose never trips it.
_CONNECTOR_RE = re.compile(
    r"\b(connectors?|cables?|adapters?|extenders?|extensions?|modules?|"
    r"controls?(?:ler)?s?|splitters?)\b",
    re.I,
)
_BOARD_SIGNAL_RE = re.compile(
    r"\b(motherboards?|boards?|chipsets?|sockets?|lga\s*\d+|am[45]|"
    r"ddr[345]l?|atx|m[\s\-]?atx|e[\s\-]?atx|mini[\s\-]?itx|itx|"
    r"pcie\s*x?\d*|m\.?2|sata|usb\s*\d|hdmi|displayport)\b",
    re.I,
)
_CHIPSETISH_RE = re.compile(
    r"\b([abh]x\d{3}[a-z]?|z\d{3}[a-z]?|x\d{3}[a-z]?|b\d{3}[a-z]?|"
    r"h\d{3}[a-z]?|w\d{3}|trx50|wrx90)\b",
    re.I,
)

# Hebrew category hints (TMS/1PC/Ivory titles carry the category in Hebrew;
# _clean strips Hebrew entirely, so check the raw title first).
_HEBREW_LIQUID_RE = re.compile(r"נוזלי")
_HEBREW_CASE_FAN_RE = re.compile(r"מארז")
_HEBREW_CPU_COOLER_RE = re.compile(r"קירור\s*למעבד|קירור\s*מעבד")
_HEBREW_THERMAL_RE = re.compile(r"משחה\s*תרמית|גריז\s*תרמי|משחה")


def _hebrew_category_hint(title_raw: str) -> str | None:
    """Coarse category from Hebrew words in the raw (pre-clean) title."""
    if not title_raw:
        return None
    if _HEBREW_THERMAL_RE.search(title_raw):
        return "thermal_paste"
    # Liquid check first: "קירור נוזלי למעבד" contains both liquid and the
    # generic CPU-cooler phrase — liquid wins.
    if _HEBREW_LIQUID_RE.search(title_raw):
        return "aio"
    if _HEBREW_CASE_FAN_RE.search(title_raw):
        return "case_fan"
    if _HEBREW_CPU_COOLER_RE.search(title_raw):
        return "cooler_air"
    return None


def _category_from_title(title_clean: str) -> str | None:
    """Strong title-based hints for sub-classifying messy listings.

    Priority order is load-bearing (verified against 2026-09-16 snapshots):
    cooler internals (heatpipes/tower/TDP/socket) and liquid phrases beat
    the generic mm+fan heuristics — otherwise every tower cooler with a fan
    spec ("MasterAir MA612 Dual Tower 2x120mm ... LGA1700", "AK500S ...
    120mm PWM fan") falls into case_fan, and every "Hydro Bearing" air
    cooler falls into aio.
    """
    if not title_clean:
        return None
    t = title_clean
    if "thermal paste" in t or "thermal grease" in t:
        return "thermal_paste"
    # A kit explicitly sold WITHOUT the cooler is never the cooler itself —
    # checked before the model-family regexes (kit titles list compatible
    # cooler models like "NH-U14S, NH-U12A" which would otherwise trip AIR).
    if "mounting kit" in t and "cooler not included" in t:
        return "cooler_accessory"
    # Mounting ADAPTERS for a socket ("Adapter to LGA1700 for SHADOW ROCK
    # 3...") name compatible cooler lines, which is exactly what trips AIR
    # ("shadow rock") — but an adapter has no heatpipes/tower/TDP/fan/liquid
    # of its own, so it is an accessory all the same.
    if ("adapter" in t or "adaptor" in t) and re.search(
            r"\b(lga\s*\d+|am[45]|socket|mounting|bracket)\b", t):
        if not re.search(
                r"\b(heat\s*pipes?|heatpipes?|heatsinks?|tower|tdp|"
                r"radiator|pump|liquid|water[\s\-]*cool)\b", t):
            if not re.search(r"\bfans?\b", t):
                return "cooler_accessory"
    # --- Strong cooler signals first (beat fan/mm heuristics below) ---
    # Air internals and air-only model families never appear on a liquid
    # cooler, so they beat everything below — including a bare vendor
    # "liquid" word (1PC mislabels the air tower BOREAS M2-51D as "liquid
    # cooling": model identity wins over the generic word). The generic
    # "CPU cooler" phrase is NOT in this set (it appears in AIO titles too:
    # "H100i ... Liquid CPU Cooler") — it is checked after the AIO pass.
    # Air internals: heatpipes/heatsinks/towers never appear on bare fans.
    if AIR_TITLE_RE.search(t) or _TOWER_COOLER_RE.search(t):
        return "cooler_air"
    # An LCD/OLED screen on a 240mm+ part is a pump-cap display (AIO), not a
    # fan: air-tower screens pair with 92-140mm fan sizes and never with a
    # socket-compat list ("Frozr-O II 360 LCD ... 3x120mm ARGB" is liquid).
    # Case-insensitive: title_clean is already lowercased here.
    if (re.search(r"\b(240|280|360|420)\s?mm\b", t)
            and re.search(r"\b(lcd|oled)\b", t)):
        return "aio"
    # be quiet!'s "Light Loop" AIO line vs Corsair's "Light Loop" (LL120)
    # FANS: the name alone decides nothing — a 240mm+ radiator or an
    # explicit liquid word makes it the AIO ("LIGHT LOOP 240mm" from a
    # Hebrew TMS title that lost its liquid word to Hebrew-stripping).
    if re.search(r"light loop", t) and (
            re.search(r"\b(240|280|360|420)\s?mm\b", t)
            or re.search(r"(liquid|water[\s\-]*cool|aio)", t)):
        return "aio"
    # AIO liquids: "Liquid ...", "Water Cooler", HydroShift, Kraken, etc.
    if AIO_TITLE_RE.search(t):
        return "aio"
    # Generic cooler phrases, only when no liquid signal claimed the title.
    if _GENERIC_COOLER_PHRASE_RE.search(t):
        return "cooler_air"
    if (
        re.search(r"\btdp\s*:?\s*\d+\s*w\b", t)
        or re.search(r"\b\d+\s*w\s*tdp\b", t)
    ) and re.search(r"\b(?:lga\s*\d+|am[45])\b", t):
        return "cooler_air"
    # --- Accessories (guarded: never when cooler internals present) ---
    # A cooler mentioning its bracket ("NH-U9S ... backplate required") is
    # still a cooler — standalone brackets have no cooler/fan/tower/TDP.
    if (
        re.search(r"\b(?:backplate|mounting bracket|retention bracket)\b", t)
        and re.search(r"\b(?:am[45]|lga\s*\d+|intel|amd)\b", t)
        and not _COOLER_INTERNALS_RE.search(t)
        and "cooler" not in t
        and not re.search(r"\bfans?\b", t)
    ):
        return "cooler_accessory"
    # Fan frames (Phanteks Halos ... Frame) are accessories, not fans.
    # Corsair "FRAME 4000D/4500X/5000D" is a case line — excluded.
    if (
        _FRAME_ACCESSORY_RE.search(t)
        and _FAN_LED_RE.search(t)
        and not _CORSAIR_FRAME_CASE_RE.search(t)
        and not _COOLER_INTERNALS_RE.search(t)
    ):
        return "cooler_accessory"
    # A fan bundle that SHIPS WITH its controller ("Prizm 120 ... 3 in 1
    # Pack With Fan Controller") is fans, not a controller — but only with
    # bundle words (pack/kit/bundle): a pure controller counting its ports
    # ("5 x 4 Pin PWM connectors") has none and stays a controller.
    if ("fan controller" in t or "fan hub" in t):
        if re.search(r"\b(pack|kit|bundle|box|set)\b", t) and _FAN_KIT_RE.search(t):
            return "case_fan"
        return "fan_controller"
    # "Hub mounted" is a fan design phrase (NZXT F140 Hub-Mounted RGB), not
    # a hub product — excluded from the hub rule outright.
    _hub_product = ("hub" in t and "hub mounted" not in t
                    and "hub-mounted" not in t)
    # Hub/splitter kits (PWM/SATA power, RGB) are fan controllers even when
    # the title omits the word "fan" ("10Way 4pin PWM Controller Hub
    # Splitter with Sata Power connector") — unless they ARE a fan kit
    # ("RX120 ... Expansion Requires Hub" with 120mm PWM is fans).
    if ("splitter" in t or _hub_product) and (
        "fan" in t or "rgb" in t or "argb" in t
        or "pwm" in t or "controller" in t
    ):
        if _FAN_KIT_RE.search(t):
            return "case_fan"
        return "fan_controller"
    # "Light Tint" is tinted glass (Fractal Epoch TG RGB Light Tint), not
    # lighting — excluded from both lighting rules.
    _light_tint = "light tint" in t
    if not _light_tint and re.search(r"\b(?:rgb\s+)?(?:led|light)\s+strips?\b", t):
        return "rgb_lighting"
    # LED starter kits / light bars ("Digital RGB LED Starter Kit") are
    # lighting even without the word "strip". The fan guard is real fan
    # evidence (fan words/sizes/RPM), not _FAN_KIT_RE — that also matches
    # a bare "kit", which every starter kit has by definition. Same
    # case/board/cooler guards as the connector rule.
    if (not _light_tint and re.search(r"\bled\b", t)
            and re.search(r"\bstarter\s*kits?\b|\blight\s*bars?\b", t)
            and not re.search(r"\bfans?\b|\b\d{2,3}\s*mm\b|\brpm\b", t)
            and not _CASE_LOOK_RE.search(t)
            and not re.search(
                r"\b(motherboards?|boards?|chipsets?|sockets?|lga\s*\d+|am[45]|"
                r"ddr[345]l?|atx|m[\s\-]?atx|e[\s\-]?atx|mini[\s\-]?itx)\b", t)
            and not _CHIPSETISH_RE.search(t)
            and not _COOLER_INTERNALS_RE.search(t)
            and not re.search(r"\b(motherboards?|cases?|chassis|towers?)\b", t)):
        return "rgb_lighting"
    # A fan kit that SHIPS WITH a controller ("3x SP120 ... with Lighting
    # Node CORE", "LL120 ... with Lighting Node PRO", "Prizm 120 ... with
    # Controller") is still fans — only a standalone controller/strip with
    # no fan is lighting.
    if not _light_tint and re.search(
            r"\b(?:rgb\s+light|led\s+light|lighting node|controller|remote)\b", t):
        if _FAN_KIT_RE.search(t):
            return "case_fan"
        return "rgb_lighting"
    # Generic small parts (connectors/cables/adapters/modules) with no
    # board/case/cooler/fan signals: RGB-Connector, LAN216 USB modules, etc.
    # Board-identity guard is deliberately narrow (board/chipset/socket/DDR/
    # form-factor words only): interface words like SATA/USB/PCIe/M.2 also
    # appear in accessory titles ("SATA power connector", "USB module") and
    # must not block them — real boards always name a chipset/socket too.
    # Fan-kit and case guards come first: a fan's own connectors ("4 pin PWM
    # connector" on a 120mm PWM fan) and a case's bundled controller ("5x RGB
    # Fans ... Glass Windows ... 770x225x595mm") are not accessories.
    if (
        _CONNECTOR_RE.search(t)
        and not _FAN_KIT_RE.search(t)
        and not _CASE_LOOK_RE.search(t)
        and not re.search(
            r"\b(motherboards?|boards?|chipsets?|sockets?|lga\s*\d+|am[45]|"
            r"ddr[345]l?|atx|m[\s\-]?atx|e[\s\-]?atx|mini[\s\-]?itx)\b", t)
        and not _CHIPSETISH_RE.search(t)
        and not _COOLER_INTERNALS_RE.search(t)
        and not re.search(r"\b(motherboards?|cases?|chassis|towers?)\b", t)
    ):
        # Fan-hub wording ("controller hub splitter with SATA power") is a
        # fan controller; case mods (USB/ARGB/front-panel modules) get their
        # own subtype; plain connectors are cooler accessories (all land in
        # the `accessories` umbrella downstream).
        if re.search(r"\b(hub|controller)\b", t) and not re.search(
                r"\b(module|lan\d+|lancool|front\s*panel)\b", t):
            return "fan_controller"
        if re.search(r"\b(module|lan\d+|lancool|front\s*panel)\b", t):
            return "case_accessory"
        return "cooler_accessory"
    # Splitter semantics without the word ("4 pin - female to two
    # females - 30cm"): pin + male/female ends + length is a cable or
    # splitter, never a case/fan/board. The fan guard is real fan
    # evidence (see the LED rule above), not bare-"kit" matching.
    if (
        re.search(r"\bfemales?\b|\bmales?\b", t)
        and re.search(r"\b\d+\s*pins?\b|\bpins?\b", t)
        and not re.search(r"\bfans?\b|\b\d{2,3}\s*mm\b|\brpm\b", t)
        and not _CASE_LOOK_RE.search(t)
        and not re.search(
            r"\b(motherboards?|boards?|chipsets?|sockets?|lga\s*\d+|am[45]|"
            r"ddr[345]l?|atx|m[\s\-]?atx|e[\s\-]?atx|mini[\s\-]?itx)\b", t)
        and not _CHIPSETISH_RE.search(t)
        and not _COOLER_INTERNALS_RE.search(t)
        and not re.search(r"\b(motherboards?|cases?|chassis|towers?)\b", t)
    ):
        return "cooler_accessory"
    if "starter kit" in t and "fan" in t:
        return "case_fan"
    if "expansion kit" in t and "fan" in t:
        return "case_fan"
    # Hub-mounted-LED fans (NZXT F140 Hub-Mounted RGB): the hub is the LED
    # mount design, the product is a sized fan.
    if "hub mounted" in t or "hub-mounted" in t:
        if re.search(r"\b\d{2,3}\s*mm\b", t):
            return "case_fan"
    # --- Case fans (all branches exclude cooler internals) ---
    if (
        re.search(r"\b\d{2,3}\s*mm\b", t)
        and re.search(r"\bfans?\b", t)
        and not _COOLER_INTERNALS_RE.search(t)
        and "cooler" not in t
    ):
        return "case_fan"
    # Many vendor feeds omit the word "fan" from model-style titles
    # ("NF-A14 140MM PWM", "120mm ... RPM", "CFD 120mm ... 1200rpm").  Do
    # not let coolers or socket-compatible parts fall into case_fan.
    if (
        re.search(r"\b\d{2,3}\s*mm\b", t)
        and re.search(_RPM_RE, t)
        and not _COOLER_INTERNALS_RE.search(t)
        and "cooler" not in t
        and "radiator" not in t
    ):
        return "case_fan"
    if (
        re.search(r"\bcooler\b", t)
        and re.search(r"\b\d{2,3}\s*mm\b", t)
        and not _COOLER_INTERNALS_RE.search(t)
    ):
        return "case_fan"
    if re.search(r"\bcooler\b", t):
        return "cooler_air"
    # --- broad fallbacks, used only when the vendor guess is missing/unknown ---
    if re.search(r"\b(ssd|solid state|nvme|m\.2)\b", t):
        return "storage"
    if re.search(r"\bddr[345]\b", t) and re.search(
        r"\b(ram|memory|dimms?|vengeance|trident|ripjaws|fury|predator)\b|\d+\s?gb\b", t
    ):
        return "memory"
    if re.search(r"\b(?:geforce|radeon|quadro)\b", t):
        return "gpu"
    # \b after a single digit can never match real cards (RX 7600, RTX 5060Ti
    # — a digit follows the digit). Match 3-4 digit model numbers instead;
    # no trailing \b so Ti/Super/XT suffixes and spaceless "RTX5060" still hit.
    if re.search(r"\b(?:rtx\s?\d{3,4}|rx\s?\d{3,4}|arc\s?[ab]\s?\d{3})", t):
        return "gpu"
    if re.search(r"\b(power supply|psu|80 plus|80\+|cybenetics)\b", t) and re.search(
        r"\b\d{3,4}\s?w\b", t
    ):
        return "psu"
    if re.search(r"\b(case|chassis|tower)\b", t) and re.search(
        r"\b(atx|micro-atx|matx|mini-itx|itx|e-atx)\b", t
    ):
        return "case"
    return None


RISER_RE = re.compile(
    r"\b(risers?|pci-?e?\s?(riser|extender|extension|splitter)|ver00\d{1,2}[a-z]?|"
    r"mining\s?(frame|rig|bundle)|gpu\s?(riser|extender|splitter))\b",
    re.I,
)
# "mining/crypto" CARDS are junk, but mining *motherboards* stay boards.
MINING_CARD_RE = re.compile(
    r"\b(crypto|bitcoin|btc|ethereum|mining|miner)\b",
    re.I,
)
BOARD_EVIDENCE_RE = re.compile(r"\b(motherboard|board)\b", re.I)
MONITOR_RE = re.compile(r"\b(monitor|television|led tv)\b", re.I)

# GPU support brackets / holders / anti-sag stands are accessories, never GPUs.
# Checked before the vendor-guess win so a "gpu" guess can't keep them as cards.
# Verified against current snapshots: no real GPU title contains these words.
# Bare "holder"/"bracket" alone also matches cooler mounting brackets, so those
# only count with GPU context (gpu/vga/graphics); anti-sag phrases are
# unambiguous on their own.
GPU_HOLDER_SPECIFIC_RE = re.compile(
    r"\b(support\s+brace|anti[\s-]?sag|sag\s+holder|gpu\s+stand)\b",
    re.I,
)
GPU_HOLDER_GENERIC_RE = re.compile(
    r"\b(holders?|brackets?)\b",
    re.I,
)
GPU_CONTEXT_RE = re.compile(r"\b(gpu|vga|graphics|video\s*cards?)\b", re.I)

# Back-compat alias: the union of both holder patterns.
GPU_HOLDER_RE = re.compile(
    r"\b(holders?|brackets?|support\s+brace|anti[\s-]?sag|sag\s+holder|gpu\s+stand)\b",
    re.I,
)


def _is_gpu_holder(title_clean: str) -> bool:
    if GPU_HOLDER_SPECIFIC_RE.search(title_clean):
        return True
    return bool(
        GPU_HOLDER_GENERIC_RE.search(title_clean)
        and GPU_CONTEXT_RE.search(title_clean)
    )

TMS_FLAG_SUFFIXES = ("bundle-only", "new-pc-deal")


def _split_category_flags(guess: str | None) -> tuple[str, set[str]]:
    """Split a vendor category_guess into (base, flags).

    TMS appends ":bundle-only" / ":new-pc-deal" to the guess (tms.py).
    The base alone is looked up in CATEGORY_ALIASES; the flags ride along
    as offer attributes. Never looks up the suffixed string.
    """
    raw = str(guess or "")
    parts = raw.split(":")
    base = (parts[0] or "").strip()
    flags: set[str] = set()
    for part in parts[1:]:
        key = part.strip().lower()
        if key in TMS_FLAG_SUFFIXES:
            flags.add(key)
    # Legacy safety: a guess that already embeds the flag without a colon
    # (should not happen from the spider, but old snapshots exist).
    compact = _compact_key(base)
    if "bundleonly" in compact:
        flags.add("bundle-only")
    if "newpcdeal" in compact:
        flags.add("new-pc-deal")
    return base, flags


def _is_junk_listing(
    title_clean: str,
    category_guess_base: str = "",
    url: str = "",
) -> bool:
    if RISER_RE.search(title_clean):
        return True
    m = MINING_CARD_RE.search(title_clean)
    if not m:
        return False
    # Mining motherboards stay boards, mining CARDS go to "other".
    # A bare motherboard guess is not enough: Plonter misfiles its crypto
    # expansion card (DCBTC2 "Crypto Mining Card") under Motherboards, so a
    # motherboard guess only protects titles with real board signals
    # (board words, chipset, socket, DDR, or form factor). Real mining
    # boards (B250 MINING EXPERT etc.) always carry at least one.
    window = title_clean[max(0, m.start() - 40):m.end() + 40]
    if BOARD_EVIDENCE_RE.search(window):
        return False
    if _BOARD_SIGNAL_RE.search(title_clean) or _CHIPSETISH_RE.search(title_clean):
        return False
    if _compact_key(category_guess_base) in ("motherboard", "motherboards"):
        # Guess says board but the title has zero board signals and names a
        # card/adapter/riser/extender — trust the title, it is a card.
        if re.search(r"\b(cards?|adapters?|risers?|extenders?|expansions?)\b",
                     title_clean):
            return True
        return False
    if re.search(r"motherboard|/board", str(url or "").lower()):
        return False
    return True


def _reclassify(category: str, title_clean: str) -> str:
    if category == "gpu" and MONITOR_RE.search(title_clean):
        return "other"
    return category

def canonical_category(
    guess: str | None, title: str = "", url: str = "", sku: str = ""
) -> str:
    """Map vendor category guesses into canonical categories.

    TMS flag suffixes (":bundle-only", ":new-pc-deal") are split off first —
    only the base is ever looked up in CATEGORY_ALIASES.

    `sku` is consulted ONLY as accessory evidence in the case-peel below
    (vendor SKUs like "RGB-Extender" name the part when the title is a
    bare spec fragment). It never drives primary classification — SKU
    tokens name whole model lines that collide with product families.
    """
    guess_base, _flags = _split_category_flags(guess)
    raw_key = _compact_key(guess_base).replace("bundleonly", "").replace(
        "newpcdeal", ""
    )
    raw_title = str(title or "")
    title_clean = _clean(raw_title).lower()

    # GPU holders / brackets / anti-sag stands are accessories, never GPUs —
    # re-routed before the vendor guess can win. Bare holder/bracket needs
    # GPU context so cooler mounting brackets are not hijacked.
    if _is_gpu_holder(title_clean):
        return "accessories"

    # Hard blacklist: risers / mining cards never enter a build category —
    # dump them into "other" (owner decision, Aug 2026). Mining motherboards
    # stay boards via board-evidence (title window, board signals, or URL).
    if _is_junk_listing(title_clean, guess_base, url):
        return "other"

    # Hebrew-first: TMS/Ivory titles carry the category in Hebrew
    # ("קירור נוזלי"=liquid, "מארז"=enclosure, "קירור למעבד"=CPU cooler).
    # _clean strips Hebrew entirely, so consult the raw title before the
    # English classifier. The Hebrew hint is authoritative for the coarse
    # fan-vs-air-vs-liquid split; the English pass below still refines
    # accessories (frames, hubs, strips) which Hebrew never names.
    hebrew_cat = _hebrew_category_hint(raw_title)
    title_cat = _category_from_title(title_clean)
    if hebrew_cat in ("aio", "cooler_air", "case_fan", "thermal_paste"):
        # English accessory evidence (a real hub/strip/frame/bracket title)
        # still wins over a coarse Hebrew cooler/fan hint — e.g. a Hebrew
        # "מאוורר למארז" fan kit titled "... with Lighting Node" is decided
        # by the fan+controller rule above, not here. But a Hebrew liquid
        # hint beats an English miss (model-only titles like HydroShift with
        # no English liquid word).
        if title_cat in ACCESSORY_CATEGORIES and hebrew_cat in (
            "aio", "cooler_air", "case_fan"):
            pass
        elif title_cat in ("aio", "cooler_air", "case_fan",
                           "thermal_paste") and title_cat != hebrew_cat:
            # Both sides claim a primary type but disagree: trust Hebrew for
            # the vendor's own storefront language (TMS "קירור נוזלי למעבד
            # ... HydroShift" has no English liquid word — English says
            # nothing/air, Hebrew says liquid), unless English found cooler
            # internals Hebrew cannot see (heatpipes/TDP/tower in English).
            if _COOLER_INTERNALS_RE.search(title_clean) and hebrew_cat == "case_fan":
                pass
            else:
                title_cat = hebrew_cat
        elif title_cat is None:
            title_cat = hebrew_cat

    if raw_key in CATEGORY_ALIASES:
        category = CATEGORY_ALIASES[raw_key]
    elif raw_key.startswith("case") and "fan" not in raw_key:
        category = "case"
    else:
        # No usable vendor guess — fall back to title detection before "other".
        category = title_cat or "other"

    # Single umbrella Accessories category: the old granular accessory ids
    # (thermal_paste / fan_controller / rgb_lighting / cooler_accessory /
    # case_accessory) merge here; the old value is preserved in
    # attributes.accessory_type.
    if category in ACCESSORY_CATEGORIES:
        return "accessories"

    # Plonter sometimes puts accessory items under COMPUTER CASES (and 1PC
    # files case mods like the LAN216 USB/ARGB modules under `case`).
    # Peel off accessory-only titles, but never a genuine case: cases name a
    # form factor/tower/chassis, a fan array (Nx120mm), glass/windows, or
    # WxHxD dimensions — accessories never do.
    if category == "case" and title_cat in ACCESSORY_CATEGORIES:
        # "COMPUTER CASES" is a noisy Plonter parent category.  It also
        # contains genuine cases whose marketing copy mentions bundled RGB
        # strips/controllers, so only peel off unambiguous accessory-only
        # titles (splitters, hubs, strips, kits, connectors, modules, frames,
        # or thermal paste).
        looks_like_case = bool(_CASE_LOOK_RE.search(title_clean))
        accessory_only = (
            title_cat in ("thermal_paste", "cooler_accessory",
                          "case_accessory", "fan_controller", "rgb_lighting")
            and not looks_like_case
        )
        if accessory_only:
            return "accessories"
        return "case"

    # Same peel on SKU-only evidence: the title can be a bare spec
    # fragment ("4 pin - female to two females - 30cm") while the vendor
    # SKU names the part ("RGB-Extender"). Only when the title says
    # nothing decidable (title_cat None) and nothing looks like a case —
    # a conflicting primary title verdict always wins.
    if category == "case" and title_cat is None and sku:
        try:
            sku_cat = _category_from_title(_clean(str(sku)))
        except Exception:
            sku_cat = None
        if sku_cat in ("thermal_paste", "cooler_accessory",
                       "case_accessory", "fan_controller", "rgb_lighting") \
                and not _CASE_LOOK_RE.search(title_clean):
            return "accessories"

    # Ambiguous cooling guesses ("Fans and Cooling solutions", "cpu cooler").
    if category == "cooling":
        if title_cat in (
            "aio",
            "cooler_air",
            "case_fan",
            "fan_controller",
            "rgb_lighting",
            "thermal_paste",
            "cooler_accessory",
            "case_accessory",
        ):
            return "accessories" if title_cat in ACCESSORY_CATEGORIES else title_cat
        return "cooling_other"

    # Vendor feeds also use "cooling_other" for CPU coolers and fan hubs.
    # Re-run the title classifier for this broad bucket instead of exposing
    # those products under an undifferentiated category.
    if category == "cooling_other" and title_cat in (
        "aio",
        "cooler_air",
        "case_fan",
        "fan_controller",
        "rgb_lighting",
        "thermal_paste",
        "cooler_accessory",
        "case_accessory",
    ):
        return "accessories" if title_cat in ACCESSORY_CATEGORIES else title_cat

    if category == "case_fan" and title_cat in ("cooler_air", "aio"):
        return title_cat

    # Explicit fan buckets holding an accessory (frames, standalone hubs):
    # the title is authoritative over the vendor bucket.
    if category == "case_fan" and title_cat in ACCESSORY_CATEGORIES:
        return "accessories"

    if category == "cooler_air" and title_cat == "case_fan":
        return title_cat

    # Explicit cooler buckets holding a pure accessory (mounting kit filed
    # under cpu cooling): same rule, opposite direction.
    if category in ("cooler_air", "aio") and title_cat in ACCESSORY_CATEGORIES:
        return "accessories"

    if category in ("fan_controller", "rgb_lighting") and title_cat == "case":
        return "case"

    # Accessory words in a case title describe bundled lighting/fans, not the
    # product's primary type.
    if category in ("fan_controller", "rgb_lighting") and re.search(
        r"\b(?:tower|chassis|case|atx|e-?atx|m-?atx|itx)\b", title_clean
    ):
        return "case"

    if category in ("cooler_air", "aio") and title_cat in ("cooler_air", "aio"):
        return title_cat

    return _reclassify(category, title_clean)


# --------------------------------------------------------------------------
# Listing identity
# --------------------------------------------------------------------------

def listing_key(listing: dict) -> str:
    """
    Build a stable unique key for a vendor listing.

    Special handling:
    - 1PC product URLs contain stable numeric product IDs; 1PC vendor_sku is
      NOT unique (Hebrew color slugs repeat across products).
    - Ivory can repeat `barcode` across catalog IDs, so prefer URL id.
    """
    vendor = canonical_vendor_id(listing.get("vendor_id"))
    sku = str(listing.get("vendor_sku", "") or "").strip()
    url = str(listing.get("url", "") or "").strip()

    if vendor == "1pc":
        m = re.search(r"product-(\d+)", url)
        if m:
            return f"1pc:{m.group(1)}"
        if sku:
            return f"1pc:{sku}"

    if vendor == "ivory":
        m = re.search(r"[?&]id=(\d+)", url)
        if m:
            return f"ivory:{m.group(1)}"
        if sku:
            return f"ivory:{sku}"

    if sku:
        return f"{vendor}:{sku}"

    if url:
        return f"{vendor}:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}"

    payload = json.dumps(listing, sort_keys=True, ensure_ascii=False)
    return f"{vendor}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]}"


def normalize_sku(value: str | None) -> str:
    """
    Normalize vendor SKU for exact SKU matching.

    Decodes URL-encoded Hebrew SKUs and removes non-alphanumerics.
    """
    s = unquote(str(value or ""))
    s = html.unescape(s)
    # Replacement characters are already-lossy vendor encoding artifacts,
    # never part of a product identity.
    s = s.replace("\ufffd", " ")
    s = unicodedata.normalize("NFKC", s)
    s = HEBREW.sub(" ", s)
    s = re.sub(r"[^A-Za-z0-9]", "", s)
    return s.upper()


def match_text(listing: dict) -> str:
    """
    Text used for matching.

    Combines vendor SKU and raw title because vendor SKUs often contain
    the model, especially for TMS and Plonter.
    """
    return _clean(f"{listing.get('vendor_sku', '')} {listing.get('title_raw', '')}")


def detect_brand(text: str) -> str | None:
    t = " " + _clean(text).lower() + " "
    best_len = 0
    best_brand = None

    for alias, brand in BRAND_ALIASES.items():
        if f" {alias} " in t:
            if len(alias) > best_len:
                best_len = len(alias)
                best_brand = brand

    return best_brand


def extract_mpn(text: str) -> str | None:
    """
    Extract likely manufacturer part number from SKU/title.

    Normalized MPN removes dashes and uppercase:
    FD-C-POV2A-02 => FDCPOV2A02
    """
    t = _clean(text).upper()
    found = []

    for pattern in MPN_PATTERNS:
        found.extend(re.findall(pattern, t))

    if not found:
        return None

    # Prefer longer MPNs; usually more specific.
    found.sort(key=len, reverse=True)
    for cand in found:
        mpn = re.sub(r"[^A-Z0-9]", "", cand)
        # Pure-digit strings of 12+ chars are GTIN/EAN barcodes, not
        # manufacturer part numbers (e.g. 4711377028363). Accepting them
        # as MPNs produced products literally named after their barcode.
        if mpn.isdigit() and len(mpn) >= 12:
            continue
        return mpn
    return None


def _strip_gv_prefix(key: str) -> str:
    """Strip Gigabyte's vendor prefix for cross-vendor keying.

    Gigabyte cards are listed as "GV-N5070AERO OC-12GD" by some vendors and
    "N5070AEROOC12GD" by others (likewise "GV-R9070..." vs "R9070...") — the
    same card. The normalized part key drops the leading GV so both land on
    one product. Only applies when the remainder still looks like a part
    number (3+ chars with a digit).
    """
    if len(key) > 5 and key.startswith("gv"):
        rest = key[2:]
        if len(rest) >= 3 and re.search(r"\d", rest):
            return rest
    return key


def mpn_part_key(mpn: str | None) -> str:
    """Normalized lookup key for an MPN/SKU part number (tiers 3+4 share
    this so a part reached via its MPN meets the same part reached via its
    vendor SKU)."""
    return _strip_gv_prefix(_compact_key(mpn))


def mpn_affix_related(a: str | None, b: str | None) -> bool:
    """True when two MPN candidates are the same code at different
    truncation levels (one compact form affixes the other, modulo the GV
    vendor prefix) — e.g. "GVN5070AERO" vs "N5070AEROOC12GD", "KFGX" vs
    "WD161KFGX". Used to tell truncation apart from true conflicts."""
    if not a or not b:
        return False
    c = _strip_gv_prefix(_compact_key(a))
    n = _strip_gv_prefix(_compact_key(b))
    if not c or not n or c == n:
        return bool(c and n)
    return (n.startswith(c) or n.endswith(c)
            or c.startswith(n) or c.endswith(n))


def prefer_longer_mpn(current: str | None, candidate: str | None) -> str | None:
    """Reconcile two MPN candidates for one listing.

    Pattern extraction truncates at spaces/slashes ("GV-N5070AERO" out of
    "GV-N5070AERO OC-12GD", "KF432C16BBK2" out of "KF432C16BBK2/16",
    "BW029" out of "BW029EU") while the vendor SKU — or a detail scrape —
    carries the full code; conversely a detail row sometimes carries only
    the tail ("KFGX" for "WD161KFGX"). When one compact candidate extends
    the other (affix, modulo the GV vendor prefix), the longer one is the
    full part number — take it. Unrelated candidates (different parts)
    resolve to `current` (status quo: the earlier/authoritative source
    wins over fallback/detail sources).
    """
    if not current:
        return candidate
    if not candidate or _compact_key(current) == _compact_key(candidate):
        return current
    c = _strip_gv_prefix(_compact_key(current))
    n = _strip_gv_prefix(_compact_key(candidate))
    if c == n:
        return current if len(str(current)) >= len(str(candidate)) else candidate
    if n.startswith(c) or n.endswith(c) or c.startswith(n) or c.endswith(n):
        return candidate if len(n) > len(c) else current
    return current


def sku_as_mpn(vendor_sku: str | None) -> str | None:
    """Fallback MPN for listing spiders that carry the manufacturer part
    number as their SKU (TMS/Plonter/Ivory all do) without it matching any
    MPN_PATTERNS brand prefix — e.g. ARKTEK's "AK-H81MEL-VS", a bare
    Supermicro "MZ73-LM0", Gigabyte "GB550MAORUSE".

    Guard rails (all must hold, else None):
    - must contain BOTH letters and digits (pure digits are vendor ids like
      1PC's "217314" or bar codes; pure letters are generic slugs),
    - 4-22 alphanumeric chars,
    - at least one dash OR 4+ compact chars — short vendor codes such as
      "BL114" are still valid when they contain both letters and digits.

    Returns the mpn in normalized (compact) form so it merges with detail
    scrapes and other vendors' identical part numbers regardless of how they
    hyphenate.
    """
    if not vendor_sku:
        return None
    mpn = re.sub(r"[^A-Za-z0-9]", "", str(vendor_sku))
    if not mpn:
        return None
    if len(mpn) < 4 or len(mpn) > 22:
        return None
    if not re.search(r"[A-Za-z]", mpn) or not re.search(r"\d", mpn):
        return None
    # NOTE: no digit-leading rejection here. The letters+digits requirement
    # above already excludes pure-numeric vendor ids ("217314") and pure
    # slugs, while digit-leading MPNs are legitimate and common (G.Skill
    # "5600J3636C16GX2-RS5K", Lenovo "4X71M23186x2"). A previous
    # fullmatch guard for `\d+([A-Z]+\d*)*` rejected exactly those and split
    # same-SKU cross-vendor listings into duplicate products (Sep 2026).
    return mpn.upper()


# --------------------------------------------------------------------------
# Enrichment
# --------------------------------------------------------------------------

# Vendor-guess fallback for accessory subtypes when the title carries no
# granular hint. Keys are compacted guess bases (see _split_category_flags).
_GUESS_ACCESSORY_SUBTYPE = {
    "thermalpaste": "thermal_paste",
}


def _accessory_subtype(title: str, title_cat: str | None) -> str:
    """Subtype for the umbrella `accessories` category."""
    t = _clean(title).lower()
    if _is_gpu_holder(t):
        return "gpu_holder"
    if title_cat == "thermal_paste":
        return "thermal_paste"
    if title_cat == "rgb_lighting":
        return "rgb_lighting"
    if title_cat == "fan_controller":
        return "fan_controller"
    if title_cat == "cooler_accessory":
        return "cooler_accessory"
    if title_cat == "case_accessory":
        return "case_accessory"
    if re.search(r"\bfan\b", t):
        return "fan_accessory"
    return "other_accessory"


def enrich_listing(listing: dict) -> dict:
    """
    Add Phase 2 matching metadata to a raw listing.

    This does not mutate the original spider contract; it only adds fields.
    """
    enriched = dict(listing)

    enriched["vendor_id"] = canonical_vendor_id(listing.get("vendor_id"))
    enriched["listing_key"] = listing_key(listing)
    if enriched["vendor_id"] == "ivory" and enriched.get("image_url"):
        image_url = str(enriched["image_url"])
        image_url = re.sub(
            r"^(https?://[^/]+/)?computer/[^/]+/ws/",
            "https://www.ivory.co.il/",
            image_url.lstrip("/"),
        )
        if image_url.startswith("https://www.ivory.co.il/"):
            enriched["image_url"] = image_url

    enriched["price_ils_raw"] = listing.get("price_ils")
    enriched["price_ils"] = normalize_price(listing.get("price_ils"))

    _guess_base, _guess_flags = _split_category_flags(
        listing.get("category_guess")
    )
    enriched["category_normalized"] = canonical_category(
        listing.get("category_guess"),
        listing.get("title_raw", ""),
        str(listing.get("url") or ""),
        str(listing.get("vendor_sku") or ""),
    )

    enriched["match_text"] = match_text(listing)
    enriched["brand"] = detect_brand(enriched["match_text"])
    # Prefix-aware pick: pattern extraction truncates at spaces/slashes
    # ("GV-N5070AERO" out of "GV-N5070AERO OC-12GD") while the vendor SKU
    # carries the full code — take the longer when one extends the other.
    enriched["mpn"] = prefer_longer_mpn(
        extract_mpn(enriched["match_text"]),
        sku_as_mpn(listing.get("vendor_sku")),
    )

    enriched["bundle_only"] = "bundle-only" in _guess_flags
    enriched["new_pc_deal"] = "new-pc-deal" in _guess_flags
    # TMS promo side-column (Phase 1): regular price stays price_ils; the
    # conditional deal price rides along and must never set min/sorting.
    if listing.get("price_promo_ils") is not None:
        enriched["price_promo_ils"] = normalize_price(listing.get("price_promo_ils"))
    if listing.get("promo_kind"):
        enriched["promo_kind"] = str(listing.get("promo_kind"))
    if listing.get("promo_text_raw"):
        enriched["promo_text_raw"] = str(listing.get("promo_text_raw"))

    enriched["attributes"] = extract_attributes(enriched)

    if enriched.get("category_normalized") == "accessories":
        _tc = _category_from_title(_clean(listing.get("title_raw", "")).lower())
        if _tc not in ACCESSORY_CATEGORIES:
            # Title gives no granular hint (e.g. "Kryonaut 1g" without the
            # words "thermal paste") — fall back to the vendor guess itself,
            # which may be the old granular id ("thermal paste").
            _tc = _GUESS_ACCESSORY_SUBTYPE.get(
                _compact_key(_guess_base), _tc)
        enriched["attributes"].setdefault(
            "accessory_type",
            _accessory_subtype(str(listing.get("title_raw") or ""), _tc),
        )

    # Attribute-level brand: the title parsers only set brand for some
    # categories (cpu/gpu/...), but the offer-level detect_brand above
    # fires everywhere — propagate it so brand filters/columns work for
    # memory/cases/etc. too. Runs before the motherboard rule below.
    _attrs = enriched["attributes"]
    if "brand" not in _attrs and enriched.get("brand"):
        _attrs["brand"] = enriched["brand"]

    # Chip-vendor cleanup: "AMD"/"Intel"/"NVIDIA" as a motherboard brand
    # (Plonter generics like "AMD A520 AM4" with no board partner) or a
    # memory brand ("compatible with AMD EXPO" sticks with no maker named)
    # is chipset bleed, not a brand — a wrong facet is worse than none.
    # (CPUs/GPUs keep theirs: AMD/NVIDIA really make those.)
    if enriched.get("category_normalized") in ("motherboard", "memory"):
        if _attrs.get("brand") in ("AMD", "Intel", "NVIDIA"):
            del _attrs["brand"]
        if enriched.get("brand") in ("AMD", "Intel", "NVIDIA"):
            enriched["brand"] = None

    # Server-board SKU brands: spec-dump titles name no maker ("AMD EPYC
    # 9004 DP Server Board"), but the SKU does (MZ73-LM0 = Gigabyte,
    # MBD-H12SSL = Supermicro). Without this backstop these boards have
    # no brand facet at all (no rail entry, no PDP brand, no variants).
    # Runs after the chip-vendor cleanup so it only fills true gaps.
    if enriched.get("category_normalized") == "motherboard" \
            and not enriched.get("brand"):
        try:
            _stoks = re.sub(
                r"[^A-Za-z0-9]+", " ",
                str(listing.get("vendor_sku") or "")).split()
            _sb = _board_sku_brand(_stoks)
        except Exception:
            _sb = None
        if _sb:
            enriched["brand"] = _sb
            _attrs.setdefault("brand", _sb)

    # "Sapphire Rapids" (Intel codename) in a CPU title wins longest-match
    # brand detection over "Intel" — but Sapphire only makes GPUs. (Attrs
    # level is fixed in _canonicalize_filter_values; this is offer level.)
    if enriched.get("category_normalized") == "cpu":
        if enriched.get("brand") == "Sapphire":
            enriched["brand"] = "Intel"

    return enriched


def dedupe_enriched_listings(enriched_listings: list[dict]) -> list[dict]:
    """
    Deduplicate listings with the same listing_key.

    If the same listing_key appears multiple times, keep the best offer:
    lowest known price, in-stock preferred, non-stale preferred.
    """
    best: dict[str, dict] = {}

    def date_num(e: dict) -> int:
        try:
            return int(str(e.get("last_seen", "")).replace("-", ""))
        except Exception:
            return 0

    def rank(e: dict):
        price = e.get("price_ils")
        return (
            price is None,
            price if price is not None else 0,
            e.get("in_stock") is not True,
            e.get("stale", False),
            -date_num(e),
            e.get("url", ""),
        )

    for e in enriched_listings:
        k = e["listing_key"]
        if k not in best or rank(e) < rank(best[k]):
            best[k] = e

    return list(best.values())


# --------------------------------------------------------------------------
# Manual merge ledger
# --------------------------------------------------------------------------

def load_manual(path: Path | str | None):
    """
    Load manual product merges.

    Returns (key_to_product, products, blocked_pairs).
    """
    if not path:
        return {}, {}, set()

    path = Path(path)
    if not path.exists():
        return {}, {}, set()

    data = json.loads(path.read_text(encoding="utf-8"))

    key_to_product: dict[str, str] = {}
    products: dict[str, dict] = {}
    blocked_pairs: set[frozenset[str]] = set()

    for product in data.get("products", []):
        pid = product["product_id"]
        products[pid] = product

        for listing_key_value in product.get("listing_keys", []):
            key_to_product[listing_key_value] = pid

    for pair in data.get("blocked_pairs", []):
        if len(pair) == 2:
            blocked_pairs.add(frozenset(pair))

    return key_to_product, products, blocked_pairs


# --------------------------------------------------------------------------
# Product building
# --------------------------------------------------------------------------

# Categories where a (brand, model) pair fully and unambiguously identifies
# the physical part, so leftover listings can be merged across vendors on the
# model name alone (see the model-merge tier in match_listings). Deliberately
# conservative: GPUs/memory/etc. have model names that don't uniquely pin the
# part (two AIB cards can share a chip; two kits can share a name at different
# speeds), so they stay on MPN/SKU matching only.
MODEL_MERGE_CATEGORIES = {"cpu"}


def model_identity(enriched: dict) -> tuple | None:
    """
    Return a (category, brand, normalized_model) merge key for listings where
    the model name uniquely identifies the part, else None.

    Only categories in MODEL_MERGE_CATEGORIES participate. The key normalizes
    away case/whitespace/punctuation so "Core I7 14700K" and "core_i7-14700K"
    collide, but keeps distinct model numbers (14700K vs 14700KF) apart.
    Intel `series` ("225" vs "225 series 2") is handled one step down in
    _split_series_subgroups(): explicit series conflicts split the group,
    while listings whose vendor omits the tag ride with the majority — a
    strict series element in this key would fragment every same-part
    cross-vendor merge whenever a single vendor omits the tag.
    """
    category = enriched.get("category_normalized")
    if category not in MODEL_MERGE_CATEGORIES:
        return None

    attrs = enriched.get("attributes") or {}
    brand = attrs.get("brand") or enriched.get("brand")
    model = attrs.get("model") or enriched.get("model") or enriched.get("name")

    if not brand or not model:
        return None

    brand_key = re.sub(r"[^a-z0-9]+", "", str(brand).lower())
    model_key = re.sub(r"[^a-z0-9]+", "", str(model).lower())

    if not brand_key or not model_key:
        return None

    return (category, brand_key, model_key)


def offer_from_listing(enriched: dict) -> dict:
    offer = {
        "vendor_id": enriched.get("vendor_id"),
        "vendor_sku": enriched.get("vendor_sku"),
        "listing_key": enriched.get("listing_key"),
        "url": enriched.get("url"),
        "price_ils": enriched.get("price_ils"),
        "in_stock": enriched.get("in_stock"),
        "last_seen": enriched.get("last_seen"),
        "stale": enriched.get("stale", False),
        "title_raw": enriched.get("title_raw"),
        "category_guess": enriched.get("category_guess"),
        "category_normalized": enriched.get("category_normalized"),
        "brand": enriched.get("brand"),
        "mpn": enriched.get("mpn"),
        "image_url": enriched.get("image_url"),
        "bundle_only": enriched.get("bundle_only", False),
        "attributes": enriched.get("attributes", {}),
    }
    if enriched.get("price_promo_ils") is not None:
        offer["price_promo_ils"] = enriched.get("price_promo_ils")
    if enriched.get("promo_kind"):
        offer["promo_kind"] = enriched.get("promo_kind")
    if enriched.get("promo_text_raw"):
        offer["promo_text_raw"] = enriched.get("promo_text_raw")
    if enriched.get("new_pc_deal"):
        offer["new_pc_deal"] = True
    return offer


TITLE_NOISE_RE = re.compile(
    r"\b(free shipping|ship(?:s|ping)? worldwide|brand new|new in (?:sealed )?box|"
    r"open box|b-?stock|refurbished|used|best price|cheap|wholesale|"
     r"bulk (?:pack|order)|with (?:heatsink|fan|rgb lighting)|color tray|"
     r"with (?:lcd|oled|digital)\s+displays?|"
     r"with (?:a\s+)?(?:[\d.]+\s?-?inch\s+)?(?:lcd|oled)\s+(?:screen|display)|"
     r"flat color|flat|tray|"
    r"oem(?: (?:box|packaging))?|retail (?:box|packaging)|warranty included|"
    r"\d+(?:-| )?years? (?:warranty|warr)|incl\.? (?:vat|ma'am)|vat included)\b",
    re.I,
)

# Generic part-type words vendors prepend to titles ("Motherboard ARKTEK...",
# "Processor AMD..."). These add nothing once the product already has a
# category, so strip them from the front of a display name only.
LEADING_CATEGORY_WORD_RE = re.compile(
    r"^((water|liquid)\s+(cooling|cooler)\s+(system\s+)?for\s+(the\s+|cpu\s+)?|"
    r"motherboard|processor|cpu|graphics card|video card|power supply|"
    # "Cooler Master" is a brand, not the category word — guard it.
    r"memory|ram|case|chassis|for|with|cooler(?!\s+master))\b[\s:.-]*",
    re.I,
)

# Extra filler phrases scrubbed from display names (beyond TITLE_NOISE_RE,
# which targets match-text). All case-insensitive, applied to raw titles.
NAME_FILLER_RE = re.compile(
    r"\b(processor|processors|graphics card|video card|motherboard|power supply|"
    r"with integrated graphics|color tray|flat color|\bdimm\b|"
    r"laptop memory|desktop memory|blister pack|\bram\b|\bmemory\b|\bmodel\b|"
    r"computer case|liquid cooling|liquid cooler|water cooling|water cooler|"
    r"air cooler|cpu cooler|\bcpu\b|\bgpu\b|\bfans?\b|\bcase\b)\b",
    re.I,
)

HEBREW_RUN_RE = re.compile(r"[\u0590-\u05FF]+")
TRADEMARK_RE = re.compile(r"[®™©℗ªº]")
# "(series 2)" is identity, not noise (disambiguates same-numbered Intel
# parts) — hoisted out before the generic paren-drop below. Same for model
# years ("Corsair RM850x (2024)" vs "(2021)" are different products).
SERIES_PAREN_RE = re.compile(r"\(\s*series\s?(\d{1,2})\s*\)", re.I)
YEAR_PAREN_RE = re.compile(r"\(\s*((?:19|20)\d{2})\s*\)")
PAREN_RE = re.compile(r"\([^)]*\)")
DASH_RUN_RE = re.compile(r"\s*(?:[–—|·]|-(?:\s*-)+|-)\s*")


def _scrub_title(text: str) -> str:
    """Aggressive display-name scrub for raw vendor titles.

    Hebrew runs, trademark symbols, parentheticals (except Intel series
    tags), dash-runs ("- -"), filler phrases ("graphics card", "color
    tray"), duplicated words ("Intel Intel") and trailing MPN tails
    ("HX318LC11FB/8") all go. Returns "" when nothing salvageable remains.
    """
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ""
    # 1PC JSON-bleed guard (mirrors _clean — the raw title hits this path).
    s = s.split('",')[0]
    # Ivory titles carry HTML entities ("12 ס&#39;&#39;מ"); without decoding
    # they leak verbatim into display names.
    s = html.unescape(s)
    s = s.replace("\ufffd", " ")
    # Inch-mark artifacts ("12 ''", '12 ""') never carry identity.
    s = re.sub(r"['`\"’‘]{1,2}", "", s)
    s = HEBREW_RUN_RE.sub(" ", s)
    s = TRADEMARK_RE.sub("", s)
    sm = SERIES_PAREN_RE.search(s)
    series_tag = f" series {sm.group(1)}" if sm else ""
    s = SERIES_PAREN_RE.sub(" ", s)
    ym = YEAR_PAREN_RE.search(s)
    year_tag = f" ({ym.group(1)})" if ym else ""
    s = YEAR_PAREN_RE.sub(" ", s)
    s = PAREN_RE.sub(" ", s)
    # Lone unbalanced parens ("...x4) M.2...") survive the pair-drop above.
    s = re.sub(r"[()]", " ", s)
    # Comma-separated spec clauses ("..., 15th generation, socket 1851
    # BOX."): identity lives in the first segment; later segments that are
    # pure packaging/generation/socket noise go, real continuations stay.
    if "," in s:
        segs = [p.strip() for p in s.split(",")]
        kept = [segs[0]] if segs[0] else []
        for seg in segs[1:]:
            if re.fullmatch(
                r"(?:BOX\.?|TRAY|WOF|OEM|.*\bgeneration\b|socket\s+\S+|"
                r".*\bcompatible\b.*|(?:intel|amd)?\s*(?:LGA\s?[\d/]+|AM\s?\d\S*|sockets?).*|"
                r".*\bwith\s+\d+\s*$|"
                r"LGA\s*\d*|retail.*|bulk.*)",
                seg, re.I,
            ):
                continue
            kept.append(seg)
        s = ", ".join(kept)
    # Comma color-variant tails ("COOLDEX ST4 CPU, white" -> "...ST4 CPU").
    s = re.sub(
        r",\s*(black|white|red|blue|green|gr[ae]y|silver|brown|pink|"
        r"purple|orange|beige)\s*$", "", s, flags=re.I)
    # Trailing bare "CPU" on the identity segment ("...AIO CPU, LCD" ->
    # "...AIO, LCD"); the whole-string strip below can't reach it.
    s = re.sub(r"\s+CPU\s*(?=,)", " ", s)
    # Loop: layered prefixes peel one at a time ("Cooler for CPU Coolleo"
    # -> "for CPU Coolleo" -> "CPU Coolleo" -> "Coolleo").
    for _ in range(3):
        s2 = LEADING_CATEGORY_WORD_RE.sub("", s)
        if s2 == s:
            break
        s = s2
    s = TITLE_NOISE_RE.sub(" ", s)
    # "U-DIMM"/"U DIMM" shorthand -> UDIMM before the filler pass sees it.
    s = re.sub(r"\bU[-\s]?DIMM\b", "UDIMM", s, flags=re.I)
    s = NAME_FILLER_RE.sub(" ", s)
    # Spec tokens that belong in attributes, never in a name: pin counts
    # ("260pin"), rail voltages ("1.2V"), JEDEC codes ("PC3-12800").
    s = re.sub(r"\b\d{3}\s?pin\b", " ", s, flags=re.I)
    s = re.sub(r"\b\d\.\d+\s?V\b", " ", s)
    s = re.sub(r"\bPC\d+-\d+\b", " ", s, flags=re.I)
    # Unit casing / shorthand normalization (display-only).
    s = re.sub(r"(\d)\s?[mM][hH][zZ]\b", r"\1MHz", s)
    s = re.sub(r"\bU\s+(?=DDR)", "UDIMM ", s)
    # Split on dash separators, drop empties (kills "- -" artifacts), rejoin.
    parts = [p.strip(" ,;:|·") for p in DASH_RUN_RE.split(s)]
    parts = [p for p in parts if p]
    # Echo-clause drop: spec-dump titles (server/workstation boards)
    # restate the brand+model in a later clause ("AMD EPYC 9004 DP Server
    # Board - AMD EPYC 9004 series processor family - ..."). A clause whose
    # first three tokens repeat the first clause's is marketing echo, never
    # new identity — drop it.
    if len(parts) > 1:
        def _lead3(p: str) -> tuple:
            return tuple(re.findall(r"[A-Za-z0-9]+", p.lower())[:3])
        lead = _lead3(parts[0])
        if len(lead) >= 3:
            parts = [parts[0]] + [p for p in parts[1:] if _lead3(p) != lead]
    s = " ".join(parts)
    # Second filler pass: the dash-split can expose filler words that were
    # hyphen-joined before ("U-DIMM" -> "U DIMM" -> "U").
    s = NAME_FILLER_RE.sub(" ", s)
    # Collapse empty comma segments left by filler removal ("CPU Air Cooler"
    # -> ", ,") and any resulting double-whitespace.
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    # Trailing dots/spaces shield every $-anchored tail rule below
    # ("...in green color."), so they go first. Only literal trailing
    # "./space runs — "Gen 3.0"/"v2.0" end in digits and survive.
    s = re.sub(r"[.\s]+$", "", s)
    # The word "color(s)" is never identity ("Blue Color 140mm" -> "Blue
    # 140mm"); the adjective stays, the attribute column carries the rest.
    s = re.sub(r"\s+colou?rs?\b", "", s, flags=re.I)
    # Dangling "in <color...>" tails ("...in white", "...in charcoal gray",
    # "...in white with 4 ARGB" after the with-clause rule below exposes it).
    s = re.sub(r"\s+in\s+[A-Za-z/]+(?:\s+[A-Za-z/]+){0,2}\s*$", "", s)
    # Mid-title "in <color>" ("BS 2 in black BK...") — the color adjective
    # is kept in attributes; inline it only obscures the model.
    s = re.sub(
        r"\s+in\s+((?:charcoal|midnight|light|dark)\s+)?"
        r"(black|white|red|blue|green|gr[ae]y|silver|brown|pink|"
        r"purple|orange|beige)(?![A-Za-z])",
        " ", s, flags=re.I)
    # SKU tails ("...White SKU: BL090") and controller-remote tails
    # ("...with black remote") — accessories, not identity.
    s = re.sub(r"\s*\bSKU\s*:?\s*\S+\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+with\s+[A-Za-z]+\s+remote\s*$", "", s, flags=re.I)
    # Bare model years ("AF140 LED 2018"). Paren-years were hoisted above;
    # a bare 19xx/20xx token mid-title is a revision marker, never identity
    # (speeds are 3-4 digits by whitelist, core counts carry "cores").
    s = re.sub(r"\b(?:19|20)\d{2}\b", " ", s)
    # "support 14th/13th/12th Generation Intel Core" clauses on workstation
    # boards — chipset identity lives elsewhere in the title.
    s = re.sub(r"\s*\bsupport\s+[\w/]+\s+generation\b[^,]*,?", " ", s, flags=re.I)
    # "with N ARGB" clauses ("...in white with 4 ARGB" -> "...in white",
    # which the in-tail rule above then takes).
    s = re.sub(r"\s+with\s+\d+\s+ARGB\w*\b", " ", s, flags=re.I)
    # Socket-compat tails on non-CPU fallback titles ("...for AM5 Socket",
    # "...with LGA1851 socket", "...for Socket LGA 1700", "...for the CPU").
    # CPU/cooler templates never reach this path, so no identity is lost.
    s = re.sub(
        r"\s+(for|with)\s+(the\s+)?(socket\s+)?(AM\s?\d|LGA\s?\d+|sTRX4|TR4|SP3|CPU)\b(\s+socket)?\.?\s*$",
        "", s, flags=re.I)
    # Mid-title lone "CPU" between model tokens ("TS4 360 CPU TS4-360").
    # Grep over 2026-09-03 snapshots: zero non-cooler/fan/cpu titles contain
    # " CPU ", so this is cooler-vendor filler, never identity.
    s = re.sub(r"\s+CPU\s+(?=[A-Za-z0-9])", " ", s)
    # Trailing bare "CPU" is never identity — real CPU names end in model
    # numbers, and a snapshot grep shows zero non-CPU titles end in "CPU"
    # except cooler filler ("Symphony 240 ARGB CPU").
    s = re.sub(r"\s+CPU\s*$", "", s)
    # Wraith-style revision / blade-count tails ("...Rev E 7 Blades").
    s = re.sub(r"\s+Rev\s+[A-Z]\b", " ", s)
    s = re.sub(r"\s+\d+\s+Blades\b", " ", s, flags=re.I)
    # Packaging / color tails vendors append after the real name ("...BOX.",
    # "...black color.", "...memory in green color."). Trailing-only, so
    # genuine mid-title words never match. These run BEFORE the MPN pop
    # below — a color tail would otherwise shield the MPN behind it.
    s = re.sub(r"\s*\bBOX\.?\s*$", "", s)
    s = re.sub(r"\s+in\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+colou?rs?\.?\s*$", "", s, flags=re.I)
    s = re.sub(
        r"\s+(black|white|green|red|blue|grey|gray|silver|brown|pink|"
        r"purple|orange|beige)\s+colou?rs?\.?\s*$", "", s, flags=re.I)
    # Trailing MPN tail: token with a slash ("HX318LC11FB/8") or an
    # all-caps digit-letter jumble ("AD4U320032G22", "B3200GSST"). The
    # dash-split above can sever an MPN from its suffix ("...G22-SGN" ->
    # "...G22 SGN"), so after the jumbles allow one short all-caps suffix
    # ("SGN"). Genuine board/CPU models survive: they are short ("B550M"),
    # lack digits, or sit mid-title — and edition words ("EVO", "OC") are
    # only reachable after a jumble pop, which never precedes them.
    toks = s.split(" ")

    def _is_jumble(tok: str) -> bool:
        return (
            len(tok) >= 8
            and re.fullmatch(r"[A-Z0-9-]+", tok) is not None
            and re.search(r"\d", tok) is not None
            and re.search(r"[A-Z]", tok) is not None
        )

    # A dash-severed MPN suffix ("...G22-SGN" -> "...G22 SGN"): drop the
    # short all-caps tail when it sits right behind a jumble/slash token —
    # or behind a long pure-digit token (Corsair "CW-9061001-WW" ->
    # "CW 9061001 WW"). Edition words ("EVO", "OC") never qualify — no
    # jumble precedes them.
    if (
        len(toks) >= 2
        and re.fullmatch(r"[A-Z]{2,5}", toks[-1]) is not None
        and ("/" in toks[-2] or _is_jumble(toks[-2])
             or (toks[-2].isdigit() and len(toks[-2]) >= 6))
    ):
        toks.pop()
    while toks and ("/" in toks[-1] or _is_jumble(toks[-1])
                    or (toks[-1].isdigit() and len(toks[-1]) >= 6)):
        toks.pop()
    # Severed Corsair SKU prefix left behind by the pops above
    # ("...420mm Liquid CW").
    s = re.sub(r"\s+\bC[WC]\b\s*$", "", " ".join(toks))
    # End pass: later steps (color-word drop, clause removals) expose new
    # tails the early pass couldn't see ("..., white color." -> "..., white"
    # -> "" ; "...ST4 CPU" -> "...ST4"). Idempotent — safe to repeat.
    s = re.sub(
        r",\s*(black|white|red|blue|green|gr[ae]y|silver|brown|pink|"
        r"purple|orange|beige)\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+CPU\s*(?=,)", " ", s)
    s = re.sub(r"\s+CPU\s*$", "", s)
    # Trailing dangling prepositions from dropped clauses ("...EPYC Series
    # Without", left by "...Without Cooler").
    s = re.sub(r"\s*\b(Without|With)\s*$", "", s, flags=re.I)
    toks = s.split(" ")
    s = " ".join(toks)
    # Dedupe consecutive duplicate words ("Intel Intel", "DDR4 DDR4") and
    # repeated adjacent bigrams ("TS4 360 TS4 360" from dash-split models).
    # Also normalize " ," artifacts from dropped clauses.
    s = re.sub(r"\s+,", ",", s)
    # Empty tokens from clause removals would break adjacency checks below.
    words = [w for w in s.split(" ") if w]
    deduped = [words[0]] if words else []
    for w in words[1:]:
        if w.lower() != deduped[-1].lower():
            deduped.append(w)
    # Adjacent bigram repeats ("TS4 360 TS4 360 WH" -> "TS4 360 WH").
    merged: list[str] = []
    i = 0
    while i < len(deduped):
        if (
            i + 3 < len(deduped)
            and deduped[i].lower() == deduped[i + 2].lower()
            and deduped[i + 1].lower() == deduped[i + 3].lower()
            and re.fullmatch(r"[A-Za-z0-9]+", deduped[i])
            and re.fullmatch(r"[A-Za-z0-9]+", deduped[i + 1])
        ):
            merged.extend([deduped[i], deduped[i + 1]])
            i += 4
        else:
            merged.append(deduped[i])
            i += 1
    s = re.sub(r"\s{2,}", " ", " ".join(merged)).strip(" -–—|·,;:. ")
    if series_tag and series_tag.strip().lower() not in s.lower():
        s = f"{s}{series_tag}"
    if year_tag and ym is not None and ym.group(1) not in s:
        s = f"{s}{year_tag}"
    return s


def display_title(text: str, max_len: int = 120) -> str:
    """Trim marketing noise and hard-cap display names."""
    s = _scrub_title(text)
    if not s:
        return "unknown"
    if len(s) > max_len:
        # Clause-aware truncation: prefer a comma boundary within the first
        # 60% of max_len (keeps identity visible) over a mid-word cut.
        first_comma = s.find(",")
        if 25 <= first_comma <= int(max_len * 0.7):
            cut = s[:first_comma]
        else:
            cut = s[:max_len]
            if " " in cut:
                cut = cut.rsplit(" ", 1)[0]
        # Strip trailing dangling spec fragments that the word-cut may leave
        # behind ("… DIMMs 24x", "… ports 1x", "… audio 2.1") and
        # technology/category words left by echo-clause removal ("Dual",
        # "5nm").
        cut = re.sub(
            r"(?:\s+(?:\d+[xX]?|\d+nm\b|[:/,;]|and|or|with|for|to|of|in|up|max|min"
            r"|support|supports|channel|ports?|slots?|Dual|Quad|Single|Octa))+$",
            "", cut, flags=re.I,
        )
        s = cut.rstrip(" -–—|·,;:. ") + "…"
    return s or "unknown"


def _memory_canonical_name(group: list[dict], attributes: dict) -> str | None:
    """'Kingston DDR4 8GB 3200 CL22' from structured parts + title tokens.

    Brand: first matching combo below (word-boundary, title order across
    the group). Model: first digit-bearing token after the brand span that
    isn't itself a spec token (capacity/speed/CL/JEDEC/voltage/DIMM/color).
    Specs (capacity/type/speed/CAS) come from attributes, so Hebrew filler
    and MPN tails never survive.
    """
    cap: Any = attributes.get("capacity_gb") or attributes.get("total_gb")
    try:
        cap = int(cap) if cap is not None else None
    except (ValueError, TypeError):
        cap = None
    mem_type = attributes.get("memory_type")
    speed: Any = attributes.get("speed_mhz")
    try:
        speed = int(speed) if speed is not None else None
    except (ValueError, TypeError):
        speed = None
    cas: Any = attributes.get("cas_latency")
    try:
        cas = int(cas) if cas is not None else None
    except (ValueError, TypeError):
        cas = None
    if not cap or not mem_type or not speed:
        return None

    titles = [str(e.get("title_raw") or "") for e in group]
    blob = " | ".join(titles)
    clean = HEBREW_RUN_RE.sub(" ", blob)
    # Normalize look-alike dashes (en/em dashes, Hebrew maqaf) to ASCII
    # hyphens for tokenizing only — display keeps clean ASCII. (Never in
    # clean_text/match_text: that would re-key every existing product.)
    clean = re.sub(r"[‐‑‒–—―־]", "-", clean)
    low = clean.lower()

    brand = None
    brand_end = 0
    brand_in_title = False
    brand_key = ""
    for key, canon in MEMORY_NAME_BRANDS:
        m = re.search(rf"\b{re.escape(key)}\b", low)
        if m:
            brand = canon
            brand_end = m.end()
            brand_in_title = True
            brand_key = key
            break
    if not brand:
        # Brand-less titles ("32GB ... SODIMM") often carry the maker in
        # the vendor SKU (ADATA's "AD5S560016G-Sx2") — search those too.
        sku_blob = " | ".join(str(e.get("vendor_sku") or "") for e in group)
        sku_low = sku_blob.lower()
        for key, canon in MEMORY_NAME_BRANDS:
            if re.search(rf"\b{re.escape(key)}", sku_low):
                brand = canon
                break
    if not brand:
        return None

    # Speed unit follows the vendor's own wording (MT/s vs MHz).
    unit = "MT/s" if re.search(r"\b\d+\s*MT/?s\b", clean, re.I) else "MHz"

    # Model token: first digit-bearing token after the brand that isn't a
    # spec token itself — searched only BEFORE the first capacity mention
    # in the whole title ("OSCOO OSC-P200 DDR4 … 8GB" -> OSC-P200). When
    # the brand sits after all specs ("… HyperX Fury Series - Black -
    # HX318LC11FB/8") the region is empty and no model is emitted, which
    # keeps trailing MPN tails from ever becoming the "model". Pure
    # numbers (speeds, years) are never models.
    #
    # Series words use a wider region: unlike model codes they come from a
    # closed whitelist ("Beast", "Vengeance"), so a post-brand search is
    # safe even when the brand trails the specs ("… CL40 - FURY Beast
    # Black Series" -> Beast).
    model = ""
    after = clean[brand_end:] if brand_in_title else clean
    cap_all = re.search(r"\d+\s?GB", clean, re.I)
    if cap_all and brand_in_title and cap_all.start() > brand_end:
        region = clean[brand_end:cap_all.start()]
        series_region = region
    elif cap_all and brand_in_title:
        region = ""
        series_region = after[:80]
    else:
        region = after[:80]
        series_region = region
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", region):
        up = tok.upper()
        if re.fullmatch(r"(DDR\dL?|PC\d+\S*|\d+G(B)?|\d+MHZ|\d+MT/S|CL\d+|1\.\d+V?|DIMM|SODIMM|RGB|ARGB|BLACK|WHITE|GREY|GRAY|RED|BLUE|GREEN|\d+X\d+GB)", up, re.I):
            continue
        if tok.isdigit():
            continue
        if re.search(r"\d", tok) and len(tok) >= 4 and "/" not in tok:
            model = tok.upper()
            break

    parts = [brand]
    # The matched brand key itself can be the series ("VENGEANCE" titles
    # match brand "Corsair" via the vengeance key) — hunt it too.
    series = _memory_series(f"{brand_key} {series_region}", brand)
    # Overlap join: brand "Kingston Fury" + series "Fury Beast" must become
    # "Kingston Fury Beast", not "Kingston Fury Fury Beast"; a series fully
    # inside the brand adds nothing.
    if series:
        last = brand.split()[-1].lower() if brand.split() else ""
        if series.lower() in (brand.lower(), last):
            series = ""
        elif last and series.lower().startswith(last + " "):
            series = series[len(last) + 1:].strip()
    if series:
        parts.append(series)
    lighting = attributes.get("lighting")
    if isinstance(lighting, str) and lighting.upper() in ("RGB", "ARGB"):
        parts.append(lighting.upper())
    if model:
        parts.append(model)
    # With an explicit model/series the type reads naturally right after
    # it ("OSC-P200 DDR4 8GB…", "Trident Z5 DDR5 32GB…"); without either
    # the capacity leads ("HyperX Fury 8GB DDR3L…").
    if model or series:
        parts.append(str(mem_type).upper())
        parts.append(f"{cap}GB")
    else:
        parts.append(f"{cap}GB")
        parts.append(str(mem_type).upper())
    # Kit config disambiguates same-total twins ("64GB (2x32GB)" vs
    # "64GB (4x16GB)" — different MPNs, different prices).
    modules = attributes.get("modules") or attributes.get("kit")
    if isinstance(modules, str) and re.fullmatch(
            r"\d+x\d+GB", modules.strip(), re.I):
        parts.append(f"({modules.strip()})")
    parts.append(f"{speed}{unit}")
    if cas:
        parts.append(f"CL{cas}")
    return " ".join(parts)


# Memory product lines (heatsink series). Without these, every same-spec
# kit from one brand collapses to one identical display name ("G.Skill 32GB
# DDR5 6000MHz CL30" x27) even though the MPNs — and prices — differ.
MEMORY_SERIES_WORDS = (
    "ripjaws", "trident", "flare", "vengeance", "predator", "viper",
    "beast", "ballistix", "dominator", "aegis", "spectrix", "delta",
    "fury", "t-force", "tforce",
)

# Bare suffix tokens that belong to the series ("Ripjaws S5", "Trident Z5",
# "Vengeance LPX"). RGB/ARGB/DDR/DIMM/CL are lighting/specs, never suffixes.
_MEMORY_SERIES_SUFFIX_RE = re.compile(
    r"^(?:[A-Z]{1,4}\d{1,2}[A-Z]{0,2}|LPX|RS|SL|PRO|GT|XT)$")


def _memory_series(region: str, brand: str = "") -> str:
    """'Ripjaws S5' / 'Trident Z5' from the title region. Words already in
    the brand are skipped ("Kingston Fury Beast" with brand "Kingston
    Fury" yields "Beast" — the caller overlap-joins it back). Returns ''
    when no known series word is present."""
    brand_words = set(re.findall(r"[a-z0-9]+", brand.lower()))
    toks = re.findall(r"[A-Za-z][A-Za-z0-9.+-]*", region)
    lows = [t.lower() for t in toks]
    for i, low in enumerate(lows):
        norm = low.replace("-", "")
        if norm in ("tforce",):
            norm = "t-force"
        if norm not in MEMORY_SERIES_WORDS:
            continue
        if norm in brand_words:
            continue
        series = toks[i].title()
        if norm == "t-force":
            series = "T-Force"
        # Optional second word: a short model suffix ("S5", "LPX") or a
        # second series word ("T-Force Delta", "Kingston Fury Beast").
        if i + 1 < len(lows):
            nxt, nxt_low = toks[i + 1], lows[i + 1]
            if (nxt_low in MEMORY_SERIES_WORDS
                    or _MEMORY_SERIES_SUFFIX_RE.match(nxt.upper())):
                series += f" {nxt.upper() if _MEMORY_SERIES_SUFFIX_RE.match(nxt.upper()) else nxt.title()}"
        return series
    return ""


def _gpu_canonical_name(group: list[dict], attributes: dict) -> str | None:
    """'ASUS GeForce GT 710 2GB EVO' from brand + chip + VRAM + edition.

    Memory type (GDDR5/SDDR3), bus width and MPN tails are deliberately
    dropped — the canonical name carries identity, the attributes carry
    the rest.
    """
    brand = attributes.get("brand") or next(
        (e.get("brand") for e in group if e.get("brand")), None
    )
    if not brand:
        # Last resort: scan the raw titles against the global brand
        # aliases (some vendors' board-partner names never reached attrs).
        blob_all = " | ".join(str(e.get("title_raw") or "") for e in group)
        brand = detect_brand(blob_all)
    chip = attributes.get("gpu_chip") or attributes.get("chipset")
    vram: Any = attributes.get("vram_gb")
    try:
        vram = int(vram) if vram is not None else None
    except (ValueError, TypeError):
        vram = None
    if not brand or not chip:
        return None

    cu = re.sub(r"\s+", " ", str(chip).upper()).strip()
    if cu.startswith("GEFORCE "):
        family, core = "GeForce", cu[len("GEFORCE "):].strip()
    elif cu.startswith("RADEON "):
        family, core = "Radeon", cu[len("RADEON "):].strip()
    elif cu.startswith("ARC "):
        family, core = "Arc", cu[len("ARC "):].strip()
    elif re.match(r"^(RTX|RX|GTX|GT|GTS|R[579]|HD)\b", cu):
        fam_word = "Radeon" if re.match(r"^(RX|R[579]|HD)\b", cu) else "GeForce"
        family, core = fam_word, cu
    else:
        family, core = "", cu

    # Edition: "Low Profile" phrase wins; else trailing all-caps tokens
    # after the VRAM token (EVO, LP, OC…), excluding memory-type words,
    # bus widths and digit-bearing MPN tails.
    edition = ""
    titles = [str(e.get("title_raw") or "") for e in group]
    blob = HEBREW_RUN_RE.sub(" ", " | ".join(titles))
    if re.search(r"\blow profile\b", blob, re.I):
        edition = "Low Profile"
    else:
        for t in titles:
            tc = HEBREW_RUN_RE.sub(" ", t)
            vm = re.search(r"\b\d{1,2}\s?GB?\b", tc, re.I)
            tail = tc[vm.end():] if vm else tc
            toks = re.findall(r"[A-Za-z][A-Za-z0-9.+-]*", tail)
            picks = []
            for tok in toks:
                up = tok.upper()
                # Skip memory-type / bus-width tokens to reach the real
                # edition word behind them ("SDDR3 LP", "GDDR5 EVO").
                if up in ("GDDR", "SDDR", "DDR", "HBM", "BIT", "PCI", "RGB", "ARGB", "LED"):
                    continue
                if re.fullmatch(r"(G|S)?DDR\dX?|HBM\d?|\d+BIT", up):
                    continue
                if re.fullmatch(r"[A-Z]{2,4}s?", up):
                    picks.append(up)
                    if len(picks) == 2:
                        break
                    continue
                break
            if picks:
                edition = " ".join(picks)
                break

    parts = [brand]
    if family:
        parts.append(family)
    parts.append(core)
    if vram:
        parts.append(f"{vram}GB")
    if edition:
        parts.append(edition)
    return " ".join(parts)


# --------------------------------------------------------------------------
# Short canonical names for the remaining categories (Sep 2026).
#
# Plonter titles are dash-separated spec dumps ("AMD B550 (Ryzen AM4) ROG
# STRIX ATX - 4x DDR4 - ...", "Z10 Black Mid Tower Case - 4x 120mm Fans -
# ...") and TMS/1PC titles append paint/packaging tails — without builders
# these products inherit the whole dump as their display name (see
# site_names dumps: "AMD A520 AM4 4x DDR4 DVI Displayport HDMI ...",
# "Flux Black Wood 3x 120mm PWM in front ... 530x245x545mm"). The builders
# below compose identity-only names ("Brand Model [key specs]") from
# structured attributes + first-clause title/SKU tokens; the dropped spec
# clauses already live in `attributes` (filters/spec table) and the full
# vendor title is preserved verbatim as product `description`
# (build_description). Every builder returns None when its essentials are
# missing so the caller falls back to best_name() — and a length gate there
# guarantees a built name never exceeds the scrubbed-title fallback.
# --------------------------------------------------------------------------

# Plonter dash-clause separator: hyphens with whitespace on BOTH sides, so
# intra-word hyphens in models/SKUs ("Sneaker-X", "B550M-DS3H") survive.
_CLAUSE_SPLIT_RE = re.compile(r"\s+[–—-]\s+")

_COLOR_WORDS_NAME = (
    "black", "white", "silver", "gray", "grey", "red", "blue", "green",
    "pink", "purple", "orange", "beige", "brown", "gold",
)


def _display_token(tok: str) -> str:
    """Display casing for one name token: digit-bearing codes, short codes
    and known acronyms stay upper ("DS3H", "WIFI6", "X", "TG", "ARGB"),
    plain words title-case ("Gaming", "Eagle", "Strix"). Hyphenated
    compounds are cased per part ("Sneaker-X", "Trio-Ring") instead of
    collapsing to "Sneaker-x"."""
    t = str(tok or "").strip(".,;:|·\"'()")
    if not t:
        return ""

    def _one(part: str) -> str:
        if not part:
            return ""
        if part.upper() in _ACRONYMS:
            return part.upper()
        if re.search(r"\d", part):
            return part.upper()
        if len(part) <= 3:
            return part.upper()
        return part[:1].upper() + part[1:].lower()

    return "-".join(_one(p) for p in t.split("-"))


# Industry acronyms that must never title-case ("Argb" / "M.2" would be
# wrong; "Strix" is a line name and correctly title-cases).
_ACRONYMS = frozenset({
    "ARGB", "RGB", "LED", "LCD", "OLED", "WIFI", "WIFI6", "WIFI6E", "WIFI7",
    "USB", "USBC", "HDMI", "DP", "VGA", "DVI", "PWM", "RPM", "CFM",
    "ATX", "MATX", "EATX", "ITX", "SFX", "DDR3", "DDR4", "DDR5",
    "NVME", "SATA", "SAS", "SSD", "HDD", "M2", "M.2", "PSU", "CPU", "GPU",
    "AIO", "TDP", "RAM", "GB", "TB", "MB", "MHZ", "GHZ",
})


def _tok_drop(low: str, drop: set[str]) -> bool:
    """Stop-word test that also sees through hyphen compounds: "Mid-tower"
    drops via its "mid"/"tower" parts, while "Sneaker-X" survives (neither
    part is a stop word)."""
    if low in drop:
        return True
    if "-" in low:
        return any(p in drop for p in low.split("-") if p)
    return False


def _clause_tokens(clause: str, strip_mpn_tail: bool = True) -> list[str]:
    """Word-ish tokens of a title clause with edge punctuation stripped.
    The token regex admits interior dots ("M.2", "5+C") so trailing dots
    ("Fans.") and dashes ("V2-") must be stripped here — otherwise "Fans."
    never equals the "fans" stop word and leaks into names everywhere.
    Slashes always split ("LGA2066/2011/1200" socket lists must not glue
    into one unmatchable token that then poses as a model word).
    A trailing vendor part-number tail ("...Single Fan CO-9050097-WW",
    "...338mm 90DC00G0-B39010", "...Cooler GP-AORUSWXII360I") is never
    identity — that lives in the model words and the SKU paths — so it
    goes. Narrow on purpose: a 4-digit run alone is not enough ("RM1000e"
    is the model), it needs a dash or jumble length with it."""
    toks = []
    for raw in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]*", clause):
        t = raw.strip(".,;:-")
        if t:
            toks.append(t)
    if strip_mpn_tail and toks:
        last = toks[-1]
        if (re.search(r"\d{5,}", last)
                or (re.search(r"\d{4,}", last)
                    and ("-" in last or len(last) > 12))):
            toks.pop()
    return toks


# Color abbreviations vendors bake into model tokens ("AG400 BK ARGB",
# "CC-9011257-WW").
_TOKEN_COLORS = {
    "bk": "Black", "blk": "Black", "wh": "White", "wt": "White",
    "wht": "White", "ww": "White", "gry": "Gray", "gr": "Gray",
}

# Edition markers worth merging from a SKU when the accepted title model
# omits them ("SE" in Alpha2-SE-A24-WHITE). Closed set on purpose: an
# open merge pulled vendor-code fragments ("GHS", "MAP") into names.
_EDITION_WORDS = frozenset({
    "SE", "PRO", "MAX", "PLUS", "ULTRA", "LITE", "MINI", "NANO", "XT",
    "EVO", "II", "III", "IV", "V2", "R2",
})


def _compact_alnum(s: str) -> str:
    """Lowercase alphanumeric fold for equality checks ("A-RGB" == "ARGB",
    "B550M" == "b550m")."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# Lighting/display suffixes glued onto model words in compact vendor codes
# ("MATRIXARGB", "SLINFARGB"): split off so they filter as specs instead
# of fusing into phantom model words ("Matrixargb").
_SPLIT_SUFFIXES = ("ARGB", "RGB", "LED", "PWM", "LCD", "OLED")


def _split_compact_sku(tok: str) -> list[str]:
    """Split a dash-less vendor code into runs ("OMNI240ARGB" ->
    ["OMNI", "240", "ARGB"]) so model words hidden in compact TMS SKUs
    still match title words and gate tokens. Only for fully-glued
    letter/digit runs; dashed tokens arrive pre-split. Short codes ("E4",
    "P2", "X3") stay whole — only long glued runs ("OMNI240ARGB") split."""
    t = str(tok or "")
    if len(t) < 6:
        return [t]
    if not re.fullmatch(r"[A-Za-z0-9]+", t):
        return [t]
    if not (re.search(r"[A-Za-z]", t) and re.search(r"\d", t)):
        return [t]
    if re.search(r"[^A-Za-z0-9]", t):
        return [t]
    parts = re.findall(r"[A-Za-z]+|\d+", t)
    out: list[str] = []
    for part in parts:
        up = part.upper()
        split_done = False
        for suffix in _SPLIT_SUFFIXES:
            if (len(up) > len(suffix) and up.endswith(suffix)
                    and not up == suffix):
                head = part[:len(part) - len(suffix)]
                if len(head) >= 2:
                    out.extend([head, part[len(head):]])
                    split_done = True
                    break
        if not split_done:
            out.append(part)
    return out if len(out) > 1 else [t]


def _first_clause(text: str) -> str:
    """Identity head of a spec-dump title: text before the first dash/comma
    clause separator ("Z10 Black Mid Tower Case - 4x ..." -> "Z10 Black Mid
    Tower Case")."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ""
    s = HEBREW_RUN_RE.sub(" ", s)
    head = _CLAUSE_SPLIT_RE.split(s)[0]
    head = head.split(",")[0]
    return head.strip(" ,;:|·")


def _last_clause(text: str) -> str:
    """Trailing series clause of a spec-dump title ("... - MP600 ELITE
    Series" -> "MP600 ELITE Series"). Trailing pure-measurement clauses
    ("7100/6000" speeds after the series) are skipped — the series names
    the product, the speeds don't."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ""
    s = HEBREW_RUN_RE.sub(" ", s)
    parts = [p.strip(" ,;:|·") for p in _CLAUSE_SPLIT_RE.split(s)]
    parts = [p for p in parts if p]
    for part in reversed(parts):
        # Pure-measurement tails ("7100/6000" speeds, "3 Years Warranty")
        # name nothing — the series clause sits just before them.
        if re.fullmatch(r"[\d\s/x.,-]+", part):
            continue
        if re.search(r"\bwarrant|\byears?\b|\btbw\b|\bmtbf\b", part, re.I):
            continue
        return part
    return parts[-1] if parts else ""


def _brand_words(brand: str | None) -> set[str]:
    """Normalized brand vocabulary for token comparison: punctuation-free
    lowercase words, so "quiet!" in "be quiet!" actually matches the title
    word "Quiet" (a naive .split() compares "quiet" against "quiet!" and
    leaks brand echo into names: "be quiet! Quiet Pure Base 501")."""
    return set(
        re.sub(r"[^a-z0-9]+", " ", str(brand or "").lower()).split())


def _is_brand_word(low: str, brand: str | None) -> bool:
    """Brand-word test that sees through hyphen compounds: title token
    "Lian-Li" matches brand "Lian Li" via its parts (exact match alone
    compares "lian-li" against {"lian", "li"} and doubles the brand:
    "Lian Li Lian-LI TL120 ...")."""
    if not brand:
        return False
    words = _brand_words(brand)
    if low in words:
        return True
    if "-" in low:
        return any(p in words for p in low.split("-") if p)
    return False


def _group_brand(
    attributes: dict, group: list, exclude: tuple[str, ...] = ()
) -> str | None:
    brand = attributes.get("brand") or next(
        (e.get("brand") for e in group if e.get("brand")), None)
    if brand:
        return str(brand)
    blob = " | ".join(
        f"{e.get('vendor_sku', '')} {e.get('title_raw', '')}" for e in group)
    found = detect_brand(blob)
    if found and found in exclude:
        return None
    return found


_CHIP_BRANDS = ("AMD", "Intel", "NVIDIA")

# Genuine chip-maker cooling products: bundled stock coolers ("AMD Wraith
# Stealth", "Intel Stock Cooler", "Laminar"). Anything else wearing a chip
# brand ("... for Intel LGA1700 ...", "... compatible with AMD AM4") is
# socket-compat prose, not a maker.
_STOCK_COOLER_RE = re.compile(r"\b(stock|wraith|prism|spire|laminar)\b", re.I)

# Bare CPU-line words: a "name" made only of these ("Ryzen Threadripper"
# for a generic TR4 cooler) is marketing echo, not identity.
_CPU_LINE_WORDS = frozenset({
    "ryzen", "threadripper", "epyc", "athlon", "core", "celeron", "pentium",
    "xeon", "processor", "processors",
})


def _cooler_fan_brand(attributes: dict, group: list, blob: str) -> str | None:
    """Maker for cooler/fan builders: chip brands count only on genuine
    bundled stock coolers, otherwise they are socket-compat bleed."""
    brand = _group_brand(attributes, group)
    if brand in _CHIP_BRANDS and not _STOCK_COOLER_RE.search(blob):
        return None
    return brand


def _title_color(group: list, attributes: dict, text: str | None = None) -> str:
    col = attributes.get("color")
    if isinstance(col, str) and col.strip():
        return _display_token(col.split(",")[0].split("/")[0])
    # Blob scan is first-clause-only when the caller passes one: a full-text
    # scan mistakes spec prose for paint ("850W Gold" efficiency, "RGB Gold"
    # trim) and appends phantom colors.
    blob = text if text is not None else " | ".join(
        str(e.get("title_raw") or "") for e in group)
    m = re.search(
        r"\b(black|white|silver|gray|grey|red|blue|green|pink|purple|orange|beige|brown)\b",
        blob, re.I)
    if m:
        return _display_token(m.group(1))
    # TMS/Ivory Hebrew titles carry the paint in Hebrew (לבן/שחור/...).
    for stem, canon in (
        ("שחור", "Black"), ("לבן", "White"), ("אדום", "Red"),
        ("כחול", "Blue"), ("אפור", "Gray"), ("ירוק", "Green"),
        ("ורוד", "Pink"), ("סגול", "Purple"), ("כתום", "Orange"),
    ):
        if stem in blob:
            return canon
    # Bare color abbreviations in model tails ("... Vision 360 BK",
    # "... LAN216-1W").
    m = re.search(r"\b(BK|BLK)\b", blob, re.I)
    if m:
        return "Black"
    m = re.search(r"\b(WT|WH|WHT)\b", blob, re.I)
    if m:
        return "White"
    return ""


def _pure_number(tok: str, max_keep_digits: int = 0) -> bool:
    """Bare numeric token with more than `max_keep_digits` digits ("1600",
    "1.4", "9020"). Short numbers ("4", "12") are usually model parts
    ("DARK ROCK 4", "PRO 12") and are kept."""
    m = re.fullmatch(r"(\d+)(?:\.\d+)?", tok)
    return bool(m) and len(m.group(1)) > max_keep_digits


def _longest_title(group: list) -> str:
    titles = [str(e.get("title_raw") or "") for e in group]
    titles = [t for t in titles if t.strip()]
    return max(titles, key=len) if titles else ""


def _sku_display_tokens(group: list) -> list[str]:
    """De-dashed vendor-SKU tokens of the most model-like SKU in the group
    ("A520M-DS3H" -> ["A520M", "DS3H"]). Skips numeric vendor ids (1PC) and
    digit-leading internal codes (ASUS "90MB...") — those are not models."""
    best: list[str] = []
    for e in group:
        toks = re.sub(r"[^A-Za-z0-9]+", " ",
                      str(e.get("vendor_sku") or "")).split()
        if not toks or not toks[0][:1].isalpha():
            continue
        if not re.search(r"[A-Za-z]", " ".join(toks)):
            continue
        if len(" ".join(toks)) > len(" ".join(best)):
            best = toks
    return best


# Storage brand overlay (first-match-wins, longest names first). Lines map
# to their makers; bare series words ("Barracuda" -> Seagate) included since
# Plonter storage titles rarely name the vendor.
STORAGE_NAME_BRANDS = [
    ("western digital", "WD"), ("san disk", "SanDisk"), ("sandisk", "SanDisk"),
    ("ultrastar", "WD"), ("hgst", "WD"), ("seagate", "Seagate"),
    ("barracuda", "Seagate"), ("firecuda", "Seagate"), ("ironwolf", "Seagate"),
    ("skyhawk", "Seagate"), ("toshiba", "Toshiba"), ("kioxia", "KIOXIA"),
    ("sk hynix", "SK Hynix"), ("hynix", "SK Hynix"), ("samsung", "Samsung"),
    ("crucial", "Crucial"), ("micron", "Crucial"), ("kingston", "Kingston"),
    ("fury", "Kingston"), ("adata", "ADATA"), ("xpg", "ADATA"),
    ("pny", "PNY"), ("lexar", "Lexar"), ("silicon power", "Silicon Power"),
    ("siliconpower", "Silicon Power"), ("teamgroup", "TeamGroup"),
    ("t-force", "TeamGroup"), ("tforce", "TeamGroup"), ("patriot", "Patriot"),
    ("viper", "Patriot"), ("apacer", "Apacer"), ("transcend", "Transcend"),
    ("corsair", "Corsair"), ("gigabyte", "Gigabyte"), ("aorus", "Gigabyte"),
    ("msi", "MSI"), ("sabrent", "Sabrent"), ("solidigm", "Solidigm"),
    ("geil", "GeIL"), ("v-color", "V-Color"), ("netac", "Netac"),
    ("fanxiang", "Fanxiang"), ("oscoo", "OSCOO"),
]


def _storage_brand(blob: str) -> str | None:
    low = f" {blob.lower()} "
    for key, canon in STORAGE_NAME_BRANDS:
        if f" {key} " in low or f" {key}-" in low or f" {key}/" in low:
            return canon
    return None


# Vendor-exclusive board line prefixes in Plonter SKUs ("ROG-STRIX-B650-A"
# is always ASUS; "B850M-DS3H" always Gigabyte). Conservative: only lines a
# single maker uses. Used to brand otherwise anonymous spec-dump boards.
BOARD_SKU_BRANDS = (
    ("rog", "ASUS"), ("strix", "ASUS"), ("tuf", "ASUS"), ("prime", "ASUS"),
    ("aorus", "Gigabyte"), ("eagle", "Gigabyte"), ("ds3h", "Gigabyte"),
    ("d3hp", "Gigabyte"),
    ("mag", "MSI"), ("mpg", "MSI"), ("meg", "MSI"), ("tomahawk", "MSI"),
    ("mortar", "MSI"),
    ("taichi", "ASRock"),
    ("mbd", "Supermicro"),
)

# WiFi-bearing SKU fragments and their canonical tag. "AC"/"AX" are Intel
# WiFi generations board makers bake into model names ("DS3H AC",
# "GAMING X AX" — kept verbatim as model words); WF6/WF6E/WF7 are
# Gigabyte's shorthand, normalized so the WiFi-tag dedupe below sees them.
_BOARD_WIFI_FRAGMENTS = {
    "WIFI": "WIFI", "WIFI6": "WIFI6", "WIFI6E": "WIFI6E", "WIFI7": "WIFI7",
    "WF6": "WIFI6", "WF6E": "WIFI6E", "WF7": "WIFI7",
}


def _board_sku_model(group: list) -> tuple[list[str], str]:
    """Model tokens from the most structured dashed SKU in the group.

    Plonter board SKUs ARE the model ("ROG-STRIX-B650-A-GAMING-WIFI"),
    while board titles are pure spec dumps with no model words at all.
    Only bare numbers go ("V2-1_4" tails); DDR/GEN markers stay — they
    tell twins apart ("DS3H DDR4" vs "DS3H GEN5"). Returns (tokens,
    wifi_tag). Empty when no usable SKU exists (numeric 1PC ids,
    digit-leading internal codes)."""
    toks = _sku_display_tokens(group)
    if not toks:
        return [], ""
    model: list[str] = []
    wifi_tag = ""
    for tok in toks:
        up = tok.upper()
        if _pure_number(tok):
            continue
        norm_wifi = _BOARD_WIFI_FRAGMENTS.get(up)
        if norm_wifi:
            wifi_tag = norm_wifi
            model.append(norm_wifi)
            continue
        model.append(_display_token(tok))
        if len(model) >= 5:
            break
    return model, wifi_tag


def _board_sku_brand(sku_toks: list[str]) -> str | None:
    low = [t.lower() for t in sku_toks]
    for key, canon in BOARD_SKU_BRANDS:
        if key in low:
            return canon
    # Gigabyte server lines (MZ73-LM0, MZ31-AR0, MZ01-CE1 EPYC boards):
    # the line prefix carries digits, so exact-token matching above
    # never fires — prefix-match instead. No other maker uses MZ\d.
    if any(re.fullmatch(r"mz\d+", t) for t in low):
        return "Gigabyte"
    return None


def _server_board_name(group: list, attributes: dict) -> str | None:
    """Short fallback for chipset-less (server) boards: brand +
    de-dashed SKU model + server socket ("Gigabyte MZ73 LM0 SP5",
    "Supermicro H12SSL CO SP3").

    Only fires on server sockets — a consumer board whose chipset parse
    merely failed keeps today's best_name() fallback (its prose title is
    usually a fine name). Returns None when even the SKU yields nothing,
    preserving the old fallback chain.
    """
    socket = attributes.get("socket")
    socket = str(socket or "").strip()
    if socket not in ("SP3", "SP5", "sTR5", "sWRX8", "sTRX4", "TR4"):
        return None
    brand = _group_brand(attributes, group, exclude=("AMD", "Intel", "NVIDIA"))
    sku_toks = _sku_display_tokens(group)
    if not brand:
        brand = _board_sku_brand(sku_toks)
    if not brand:
        return None
    model, _ = _board_sku_model(group)
    # "MBD" is Supermicro's literal board prefix, not a line name —
    # drop the leading token so it doesn't echo the brand.
    if model and model[0].upper() == "MBD":
        model = model[1:]
    if not model:
        return None
    parts = [str(brand), *model[:4], socket]
    return re.sub(r"\s+", " ", " ".join(parts)).strip() or None


def _motherboard_canonical_name(group: list, attributes: dict) -> str | None:
    """'Gigabyte B850 Gaming WIFI6' / 'ASUS ROG STRIX B650-A GAMING WIFI' /
    'A520M DS3H' from brand + chipset + model.

    Plonter board titles are pure spec dumps with no model words
    ("Socket AM5 - AMD B850 Chipset - 4x DDR5 - WIFI - ATX"), so the model
    comes from the vendor SKU (which for boards IS the model), while
    TMS/1PC/Ivory titles carry the model in prose ("Gigabyte B850M DS3H")
    and are read from the first clause. The spec clauses
    (socket/DDR/form factor/ports) stay in attributes; WiFi/DDR markers
    ride along only to tell twins apart (EAGLE vs EAGLE WIFI6E, DS3H DDR4
    vs DS3H).

    Server boards (EPYC/Xeon-SP) have no chipset — they take a short
    fallback instead of the full title: brand + de-dashed SKU model +
    socket ("Gigabyte MZ73 LM0 SP5")."""
    chipset = attributes.get("chipset")
    if not isinstance(chipset, str) or not chipset.strip():
        return _server_board_name(group, attributes)
    chipset = chipset.strip().upper()
    # Chip vendors never make boards: an "AMD"/"Intel" hit on a motherboard
    # title is chipset bleed, not a brand (mirrors the enrich_listing rule).
    brand = _group_brand(attributes, group, exclude=("AMD", "Intel", "NVIDIA"))

    wifi_tag = ""
    std = attributes.get("wifi_standard")
    if isinstance(std, str) and re.fullmatch(r"WIFI\s?\dE?", std.strip(), re.I):
        wifi_tag = re.sub(r"\s+", "", std.strip().upper())
    elif attributes.get("wifi") is True or str(
            attributes.get("wifi") or "").strip().lower() in ("yes", "true"):
        wifi_tag = "WiFi"

    sku_toks = _sku_display_tokens(group)
    if not brand:
        brand = _board_sku_brand(sku_toks)
    sku_model, sku_wifi = _board_sku_model(group)
    if sku_wifi and not wifi_tag:
        wifi_tag = sku_wifi

    stop = {
        "motherboard", "motherboards", "mainboard", "desktop", "support",
        "supports", "with", "for", "and", "the", "in", "on", "at",
        "is", "are", "was", "were", "be", "it", "its",
        "this", "that", "these", "those", "has", "have", "had",
        "processor", "processors",
        "family", "generation", "ryzen", "core", "chipset", "chipsets",
        "socket", "sockets", "memory", "memories", "series", "atx", "matx",
        "microatx", "micro-atx", "eatx", "e-atx", "itx", "mini-itx",
        "miniitx", "amd", "intel", "ddr3", "ddr3l", "ddr4", "ddr5", "board",
        "boards", "ddr", "pcie", "m.2", "m2", "sata", "usb", "hdmi",
        "digital", "solution", "solutions", "design", "smart", "rev",
        "revision", "version", "ver",
        # "Gaming" stays: weak alone but real identity ("B550 Gaming").
        # Lone lowercase "a" goes, but uppercase "A"/"X" stay ("B650-A",
        # "GAMING X" need them) — hence the stop holds "a", matched
        # case-insensitively below only for lowercase tokens.
    }
    def _take_into(clause: str, kept: list[str], seen: set[str]) -> None:
        for tok in _clause_tokens(clause):
            if len(kept) >= 4:
                return
            up = tok.upper()
            low = tok.lower()
            # Articles only when lowercase ("is a motherboard"); uppercase
            # single letters are variants ("B650-A", "GAMING X").
            if low in ("a", "an") and tok.islower():
                continue
            if _tok_drop(low, stop):
                continue
            if re.fullmatch(r"(AM[45]|LGA\s?\d+|STR5|SWRX8|TR4)", up):
                continue
            if re.sub(r"[^A-Z0-9]", "", up) == re.sub(r"[^A-Z0-9]", "", chipset):
                continue
            if re.fullmatch(
                    r"(DDR[345]L?|PCIE?(\d|X\d*)?|M\.?2|SATA|USB|HDMI|WIFI\d?E?|BT)",
                    up, re.I):
                continue
            if low in ("wi-fi", "wifi") or low.startswith("wifi"):
                continue
            if _pure_number(tok):
                continue
            if _is_brand_word(low, brand):
                continue
            key = re.sub(r"[^a-z0-9]", "", low)
            if not key or key in seen:
                continue
            # A longer token restating a kept one ("AK-B760MEG-DDR4" over
            # "AK-B760M") adds nothing — skip, don't double.
            if any(key.startswith(k) or k.startswith(key)
                   for k in seen if len(k) >= 4 and len(key) >= 4):
                continue
            seen.add(key)
            kept.append(_display_token(tok))

    def _candidate_for_clause(clause: str) -> list[str]:
        c_kept: list[str] = []
        c_seen: set[str] = set()
        _take_into(clause, c_kept, c_seen)
        return c_kept

    # Branded prose titles (TMS/1PC/Ivory: "Gigabyte B850M DS3H") carry the
    # model in words — use them when they yield 2+ tokens, else the SKU.
    # Per-offer voting (chimera fix 2026-09-18): the old code accumulated
    # tokens across offers into one shared kept list, so same-MPN offers
    # with disagreeing titles (1PC B850-F vs TMS/Ivory B850M-F) concatenated
    # into one phantom name. Now each offer votes one candidate; majority
    # wins, ties prefer branded prose (TMS/1PC/Ivory) over spec-dump/SKU
    # sources, then longest, then alphabetical (deterministic).
    kept: list[str] = []
    if brand:
        _BRANDED_VENDORS = {"tms", "1pc", "ivory"}
        _votes: dict[tuple[str, ...], dict] = {}
        for e in group:
            cand = _candidate_for_clause(
                _first_clause(e.get("title_raw") or ""))
            if not cand:
                continue
            fold = tuple(_compact_alnum(t) for t in cand)
            if not any(fold):
                continue
            entry = _votes.setdefault(
                fold, {"count": 0, "branded": False, "rep": cand})
            entry["count"] += 1
            try:
                v = canonical_vendor_id(e.get("vendor_id"))
            except Exception:
                v = str(e.get("vendor_id") or "").lower()
            if v in _BRANDED_VENDORS:
                entry["branded"] = True
        if _votes:
            def _vote_rank(item: tuple[tuple[str, ...], dict]):
                fold, entry = item
                rep = entry["rep"]
                label = " ".join(rep)
                return (
                    -entry["count"],
                    0 if entry["branded"] else 1,
                    -len(rep),
                    label,
                )
            _winner_fold, _winner = sorted(
                _votes.items(), key=_vote_rank)[0]
            if len(_winner["rep"]) >= 2:
                kept = list(_winner["rep"])
    if len(kept) < 2 and sku_model:
        kept = sku_model[:5]
    if not kept:
        return None
    # Bare revision tokens ("V2") lose to real model words ("Gaming").
    if any(len(re.sub(r"[^A-Za-z]", "", k)) >= 4 for k in kept):
        filtered = [k for k in kept
                    if not re.fullmatch(r"(V|R|REV)\d*(\.\d+)?", k.upper())]
        if filtered:
            kept = filtered

    parts: list[str] = []
    if brand:
        parts.append(str(brand))
    if not any(chipset in re.sub(r"[^A-Z0-9]", "", p.upper()) for p in parts + kept):
        parts.append(chipset)
    parts.extend(kept)
    if wifi_tag and not any("WIFI" in p.upper() or p.upper() in ("AC", "AX")
                           for p in parts):
        parts.append(wifi_tag)
    name = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return name or None


def _psu_canonical_name(group: list, attributes: dict) -> str | None:
    """'Corsair RM1000e 1000W 80 PLUS Gold White' from brand + series tokens
    + wattage + efficiency. Spec clauses (ATX version, fan size, PCIe 5.1)
    stay in attributes."""
    watts: Any = attributes.get("wattage_w")
    try:
        watts = int(watts) if watts is not None else None
    except (ValueError, TypeError):
        watts = None
    if not watts:
        return None
    brand = _group_brand(attributes, group)
    eff = attributes.get("efficiency")
    eff = str(eff).strip() if isinstance(eff, str) and eff.strip() else ""

    drop = {
        # "power" stays: "DARK POWER PRO 12", "SYSTEM POWER 10" need it
        # ("supply"/"supplies" still go).
        "psu", "supply", "supplies", "active", "pfc", "modular",
        "semi", "full", "non", "atx", "sfx", "sfx-l", "sfxl", "tfx",
        "fan", "fans", "silent", "silence", "noise", "low-noise", "hdb",
        "series", "edition", "version", "rev", "revision", "model",
        "cables", "cable", "sleeved", "white", "black", "plus", "80",
        "gold", "silver", "bronze", "platinum", "titanium", "cybenetics",
        "fully", "certified", "eu", "uk", "cable-free", "zero",
        "in", "on", "at",
    }
    kept: list[str] = []
    seen: set[str] = set()
    clause = _first_clause(_longest_title(group))
    for tok in _clause_tokens(clause):
        up = tok.upper()
        low = tok.lower()
        if re.fullmatch(r"P?\d+\s*W", up):
            continue
        if re.fullmatch(r"\d+\s?(MM|CM)\b", up, re.I):
            continue
        if low in ("mm", "cm"):
            continue
        # Short numbers are series parts ("PRO 12", "POWER 10"); 3+ digit
        # runs are wattage/version noise.
        if _pure_number(tok, max_keep_digits=2):
            continue
        if _tok_drop(low, drop):
            continue
        if _is_brand_word(low, brand):
            continue
        key = re.sub(r"[^a-z0-9]", "", low)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(_display_token(tok))
        if len(kept) >= 4:
            break

    if not kept:
        # Spec-only title ("550W 80 Plus Bronze"): the SKU is the series
        # ("ATLAS-550" -> "ATLAS 550").
        kept = [_display_token(t) for t in _sku_display_tokens(group)[:2]
                if not re.fullmatch(r"\d+", t)]
        if not kept:
            return None
    parts: list[str] = []
    if brand:
        parts.append(str(brand))
    parts.extend(kept)
    parts.append(f"{watts}W")
    if eff:
        parts.append(eff)
    color = _title_color(group, attributes)
    if color and color.lower() not in {p.lower() for p in parts}:
        parts.append(color)
    return re.sub(r"\s+", " ", " ".join(parts)).strip() or None


def _tb_str(cap_gb: int) -> str:
    """1024/2048/4096/8192 (binary) and round 1000s display as TB."""
    table = {512: "512GB", 1024: "1TB", 2048: "2TB", 4096: "4TB", 8192: "8TB"}
    if cap_gb in table:
        return table[cap_gb]
    if cap_gb >= 1000 and cap_gb % 1000 == 0:
        return f"{cap_gb // 1000}TB"
    return f"{cap_gb}GB"


def _storage_canonical_name(group: list, attributes: dict) -> str | None:
    """'XPG GAMMIX S70 Blade 1TB NVMe Gen4 M.2' from brand + trailing series
    clause + capacity + interface. Speeds/warranty/NAND trivia stay in
    attributes."""
    cap: Any = attributes.get("capacity_gb")
    try:
        cap = int(cap) if cap is not None else None
    except (ValueError, TypeError):
        cap = None
    if not cap:
        return None

    blob = " | ".join(
        f"{e.get('vendor_sku', '')} {e.get('title_raw', '')}" for e in group)
    brand = attributes.get("brand") or _storage_brand(blob)

    dtype = attributes.get("drive_type")
    dtype = str(dtype).upper() if isinstance(dtype, str) else ""
    iface = attributes.get("interface")
    iface = str(iface) if isinstance(iface, str) else ""
    gen = ""
    gm = re.search(r"Gen\s?([345])", attributes.get("pcie_gen") or iface or "")
    if gm:
        gen = f"Gen{gm.group(1)}"
    form = attributes.get("drive_form_factor")
    form = str(form).strip() if isinstance(form, str) else ""
    if re.fullmatch(r"M\.?\s*2(\s*2280)?", form, re.I):
        form = "M.2"

    drop = {
        "series", "ssd", "hdd", "sshd", "nvme", "sata", "sas", "pcie",
        "warranty", "warranties", "years", "year", "tlc", "qlc", "nand",
        "3d", "cache", "dram", "heatsink", "w", "with", "without",
        "oem", "bulk", "tray", "retail", "box",
    }
    iface_pat = re.compile(
        r"(SATA\d*|NVME|PCIE\d*|GEN\d|M\.?2|2280|2260|2242|2230)$", re.I)
    series: list[str] = []
    seen: set[str] = set()
    tail = _last_clause(_longest_title(group))
    for tok in _clause_tokens(tail):
        up = tok.upper()
        low = tok.lower()
        if re.fullmatch(r"\d+\s?(GB|TB|MB/S|G|MM)\b", up, re.I):
            continue
        if re.fullmatch(r"\d+(\.\d+)?", tok):
            continue
        if re.search(r"\d", tok) and "/" in tok:
            continue
        # Interface fragments inside the series clause ("SATA3 6GB/s")
        # describe the bus, not the product line.
        if iface_pat.search(re.sub(r"[^A-Za-z0-9]", "", up)):
            continue
        if re.search(r"[GM]B/S", up):
            continue
        if low in drop:
            continue
        if _is_brand_word(low, brand):
            continue
        key = re.sub(r"[^a-z0-9]", "", low)
        if not key or key in seen:
            continue
        seen.add(key)
        series.append(_display_token(tok))
        if len(series) >= 4:
            break

    parts: list[str] = []
    if brand:
        parts.append(str(brand))
    parts.extend(series)
    if not series and not brand:
        return None
    parts.append(_tb_str(cap))
    if "NVME" in iface.upper() or dtype == "SSD" and gen:
        parts.append("NVMe")
        if gen:
            parts.append(gen)
        if form:
            parts.append(form)
        elif dtype:
            parts.append(dtype.title())
    elif dtype == "SSD" and "SATA" in iface.upper():
        parts.append("SATA")
        parts.append("SSD")
        if form:
            parts.append(form)
    elif dtype in ("SSD", "HDD", "SSHD"):
        if form:
            parts.append(form)
        parts.append(dtype.title() if dtype != "SSHD" else "SSHD")
        if gen:
            parts.append(gen)
    elif form:
        parts.append(form)
    return re.sub(r"\s+", " ", " ".join(parts)).strip() or None


# Vendor-exclusive case prefixes in SKUs. Corsair's own part numbers all
# open CC-9011 ("CC-9011257-WW" = Corsair 6500X); without this, compat
# prose naming other makers ("...supports ASUS BTF motherboards") wins
# brand detection and the case is misbranded ("ASUS CC WW Black").
_CASE_SKU_BRANDS = (
    ("cc-901", "Corsair"), ("cs-hyte", "HYTE"),
)


def _case_canonical_name(group: list, attributes: dict) -> str | None:
    """'ASUS Prime AP201 Black' / 'Z10 Black' from brand + first-clause model
    + color. Fan arrays, dimensions, GPU clearance stay in attributes."""
    # SKU evidence first: it beats title prose (compat text naming other
    # makers must never win brand detection).
    brand: str | None = None
    for e in group:
        sku = re.sub(r"[^a-z0-9]+", "-", str(e.get("vendor_sku") or "").lower())
        for prefix, canon in _CASE_SKU_BRANDS:
            if sku.startswith(prefix):
                brand = canon
                break
        if brand:
            break
    if not brand:
        brand = _group_brand(attributes, group)
    # Bundle titles ("Sneaker-X + 850W + Liquid Cooler"): identity is the
    # segment before the first plus — color is read from the first two
    # segments, never from the bundle tail ("850W Gold" efficiency is not
    # paint; metals only count in the identity segment).
    longest = _longest_title(group)
    s_long = re.sub(r"\s+", " ", longest).strip()
    clauses_all = [p.strip(" ,;:|·")
                   for p in _CLAUSE_SPLIT_RE.split(HEBREW_RUN_RE.sub(" ", s_long))]
    clause = _first_clause(longest).split("+")[0]
    color = _title_color(group, attributes, text=clause)
    if not color and len(clauses_all) > 1:
        m2 = re.search(
            r"\b(black|white|red|blue|green|pink|purple|orange|beige|brown|gray|grey)\b",
            clauses_all[1], re.I)
        if m2:
            color = _display_token(m2.group(1))

    drop = {
        "tower", "towers", "case", "cases", "chassis", "computer", "pc",
        "gaming", "atx", "matx", "microatx", "micro-atx", "eatx", "e-atx",
        "itx", "mini-itx", "miniitx", "with", "without", "window", "windows",
        "glass", "tempered", "mesh", "mid", "full", "mini", "dual",
        "chamber", "series", "for", "support", "supports", "offer", "offers",
        "offered", "radiator", "radiators", "graphics", "card", "cards",
        "clean", "cable", "cables", "management", "options", "option",
        "color", "colors", "colour", "colours", "two", "up", "to", "and",
        "or", "the", "a", "max", "maximum", "height", "length", "size",
        "sizes", "fits", "fit", "compatible", "compatibility", "includes",
        "included", "including", "panel", "side", "front", "silent",
        "sound", "dampening", "foam", "fan", "fans", "nps", "in", "on",
        "at",
        # "Elite"/"Pro" stay: line names ("ARGUS E4 Elite"; dropping costs
        # more than keeping).
    }
    model: list[str] = []
    seen: set[str] = set()
    prev_kept = False
    for tok in _clause_tokens(clause):
        low = tok.lower()
        if _tok_drop(low, drop) or low in _COLOR_WORDS_NAME:
            prev_kept = False
            continue
        # Bare single digits are counts in case titles ("4 Built-in 120mm
        # fans"), never models — without this they fill the model slots
        # and block the SKU rescue below ("4 ARGB PWM" for ATLAS-M4).
        if re.fullmatch(r"\d", tok):
            prev_kept = False
            continue
        if low in ("mm", "cm", "inch", "inches"):
            prev_kept = False
            continue
        if _pure_number(tok, max_keep_digits=1):
            # A short number directly extending a kept model word is the
            # model ("Elite 301", "GT502"); standalone counts ("360 mm"
            # of radiator support) are specs.
            if not (prev_kept and re.fullmatch(r"\d{2,3}", tok)):
                prev_kept = False
                continue
        if re.fullmatch(r"\d+\s?(MM|CM)\b", tok, re.I):
            prev_kept = False
            continue
        # Pack counts are single digits ("5x"); multi-digit x-tails are
        # model numbers ("6500X", "4500X") and must survive.
        if re.fullmatch(r"[2-9]\s*x\b|\bx\s*[2-9]\b", low):
            prev_kept = False
            continue
        if _is_brand_word(low, brand):
            prev_kept = False
            continue
        key = re.sub(r"[^a-z0-9]", "", low)
        if not key or key in seen:
            prev_kept = False
            continue
        seen.add(key)
        model.append(_display_token(tok))
        prev_kept = True
        if len(model) >= 4:
            break

    if len(model) < 2 or (
        # Spec-word title model ("ARGB PWM" — no digit-bearing token)
        # with a model-like SKU ("ATLAS-M4"): the SKU names the line.
        not any(re.search(r"\d", m) for m in model)
        and any(re.search(r"\d", t)
                for t in _sku_display_tokens(group))):
        # Thin title model ("5x RGB Fans", "C8", "ARGB PWM"): the SKU
        # ("VCX200-RGB-ELITE", "C8-Aluminum-White"). Digit-bearing line
        # tokens lead ("VCX200 RGB Elite", not "RGB Elite VCX200"); colors
        # and NPS ride as themselves, not model words.
        # Hyphen-parts of kept compounds join `seen` first, so a dashed
        # SKU restating the title ("ATHENA-M6-LITE" over title token
        # "Athena-M6-Lite") adds nothing instead of doubling it.
        for m in list(model):
            for part in re.split(r"[-]", m.lower()):
                key = _compact_alnum(part)
                if len(key) >= 2:
                    seen.add(key)
        sku_toks = _sku_display_tokens(group)
        extra: list[str] = []

        def _sku_ok(t: str) -> bool:
            low = t.lower()
            if (low in drop or low in _COLOR_WORDS_NAME
                    or low in _TOKEN_COLORS):
                return False
            if _tok_drop(low, drop):
                return False
            if low in ("mm", "cm", "nps"):
                return False
            # 2-letter vendor prefixes ("CC" in CC-9011257) are not models.
            if re.fullmatch(r"[a-z]{2}", low):
                return False
            if _pure_number(t, max_keep_digits=1) and not (
                    model and re.fullmatch(r"\d{2,3}", t)):
                return False
            key = _compact_alnum(t)
            if not key or key in seen:
                return False
            # Affix dupes of the title model ("C8W" over title "C8") are
            # skipped, not doubled ("Antec C8 C8W White").
            if any(key.startswith(k) or k.startswith(key)
                   for k in seen if len(k) >= 2 and len(key) >= 2):
                return False
            return True

        # Single ordered pass: vendor SKUs are already line-leading
        # ("ATLAS-M4", "VCX200-RGB-ELITE"), so SKU order IS model order.
        # (An earlier two-pass version put digit-bearing tokens first and
        # scrambled "ATLAS M4" into "M4 ATLAS".)
        for t in sku_toks:
            if not _sku_ok(t):
                continue
            seen.add(_compact_alnum(t))
            extra.append(_display_token(t))
        # Line-leading SKU tokens ("VCX200") go first only when the title
        # left no digit-bearing model ("RGB"); otherwise ("C8") they would
        # scramble the title order ("ARGB C8").
        if any(re.search(r"\d", m) for m in model):
            model = (model + extra)[:4]
        else:
            model = (extra + model)[:4]
    if not model:
        return None

    parts: list[str] = []
    if brand:
        parts.append(str(brand))
    parts.extend(model)
    if color and color.lower() not in {p.lower() for p in parts}:
        parts.append(color)
    return re.sub(r"\s+", " ", " ".join(parts)).strip() or None


def _cooler_canonical_name(
    group: list, attributes: dict, category: str
) -> str | None:
    """Air: 'AG400 BK ARGB [95W]'. AIO: 'H100i ELITE CAPELLIX XT 240mm
    [ARGB] [LCD]'. Model = first-clause tokens minus spec words; the
    radiator size (AIO) or TDP (air) tells same-model twins apart."""
    blob = _longest_title(group)
    brand = (_cooler_fan_brand(attributes, group, blob)
             or _cooler_sku_brand(group))

    tdp = ""
    lighting = ""
    if category == "cooler_air":
        m = re.search(r"(\d{2,3})\s?W\s*TDP|TDP[^\d]{0,10}(\d{2,3})\s?W", blob, re.I)
        if m:
            tdp = f"{m.group(1) or m.group(2)}W"
    li = attributes.get("lighting")
    if isinstance(li, str) and li.upper() in ("ARGB", "RGB"):
        lighting = li.upper()
    elif re.search(r"\bARGB\b", blob, re.I):
        lighting = "ARGB"
    elif re.search(r"\bRGB\b", blob, re.I):
        lighting = "RGB"

    size = ""
    if category == "aio":
        rad: Any = attributes.get("radiator_size_mm") or attributes.get(
            "fan_size_mm")
        try:
            rad = int(rad) if rad is not None else None
        except (ValueError, TypeError):
            rad = None
        if rad not in (120, 140, 240, 280, 360, 420):
            m = re.search(r"\b(120|140|240|280|360|420)\s?MM\b", blob, re.I)
            rad = int(m.group(1)) if m else None
        if rad:
            size = f"{rad}mm"

    # Air fan size ("Bloody Tiger 92mm") when no TDP was parsed: same-model
    # twins are told apart by something, and the size is the next best fact.
    air_size = ""
    if category == "cooler_air" and not tdp:
        m = re.search(r"\b(92|120|140|170|200)\s?MM\b", blob, re.I)
        if m:
            air_size = f"{m.group(1)}mm"

    drop = {
        "liquid", "water", "cooler", "coolers", "cooling", "cpu", "processor",
        "processors", "thermal", "radiator", "radiators", "heatsink",
        "heatsinks", "tower", "towers", "twin", "dual", "with", "without",
        "for", "and", "all-in-one", "aio", "system", "series", "socket",
        "sockets", "fan", "fans", "recommend", "recommended", "in", "on",
        "at", "weight", "weights", "lxwxh", "dimensions", "dimension",
        "amd", "intel", "nvidia", "display", "displays", "screen", "screens",
        "lcd", "oled", "color", "colors", "colour", "colours", "icue",
        "link",
    }
    model: list[str] = []
    seen: set[str] = set()
    clause = _first_clause(blob)
    for tok in _clause_tokens(clause):
        up = tok.upper()
        low = tok.lower()
        if _tok_drop(low, drop):
            continue
        if low in ("mm", "cm"):
            continue
        # Ranges and decimals with units ("600-2200RPM", "103.7x86.6x126mm").
        if re.fullmatch(r"[\d.x-]+\s?(MM|CM|G|GR|KG|RPM|DBA?|CFM|W)\b", up, re.I):
            continue
        if re.fullmatch(r"\d+(\.\d+)?x\d+(\.\d+)?(x\d+(\.\d+)?)?(MM)?", up, re.I):
            continue
        # Short numbers are model parts ("DARK ROCK 4"); long runs are
        # weights/speeds ("3100", "2200").
        if _pure_number(tok, max_keep_digits=1):
            continue
        if re.fullmatch(r"(AM[45]|LGA\s?\d+|PWM|ARGB|RGB|LED|TDP)", up):
            continue
        if _is_brand_word(low, brand):
            continue
        key = re.sub(r"[^a-z0-9]", "", low)
        if not key or key in seen:
            continue
        seen.add(key)
        model.append(_display_token(tok))
        # Cap 5, not 4: cooler lines carry edition tails that matter
        # ("WATERFORCE X II" + "ICE" are different products). The length
        # gate still rejects runaway models against the scrubbed title.
        if len(model) >= 5:
            break

    # Split compact vendor codes once for both SKU paths below
    # ("OMNI240ARGB" -> OMNI/240/ARGB). Long-number neighbors mark
    # vendor-internal codes: "CW" in "CW-9061018-WW" is Corsair's prefix,
    # not a model — while "SE" in "Alpha2-SE-A24-WHITE" (surrounded by
    # model words) is the edition.
    raw_toks: list[str] = []
    for t in _sku_display_tokens(group):
        raw_toks.extend(_split_compact_sku(t))
    long_idx = {i for i, t in enumerate(raw_toks)
                if re.fullmatch(r"\d{4,}", t)}
    neighbor_of_long = {i - 1 for i in long_idx} | {i + 1 for i in long_idx}

    if not model or not _has_model_id(model):
        # Spec-prose titles ("360mm ARGB Liquid Cooler With Real-time
        # Digital Display") yield word-only models: the SKU carries the
        # real model ("CHIONE-E4-360"). Short numbers are model parts here
        # ("SE-914-XT": 914 tells the 914/207/214 apart); long runs are
        # internal codes, and the size itself ("360" next to "360mm") is
        # redundant.
        rad_num = ""
        msz = re.fullmatch(r"(\d+)mm", size)
        if msz:
            rad_num = msz.group(1)

        def _sku_num_ok(t: str) -> bool:
            # Long runs are internal codes ("000052"); the size itself
            # ("360" next to "360mm") is redundant; short numbers are
            # model parts ("SE-914-XT").
            if not _pure_number(t):
                return True
            if rad_num and t == rad_num:
                return False
            return bool(re.fullmatch(r"\d{2,3}", t))

        sku_toks = [t for i, t in enumerate(raw_toks)
                    if _sku_num_ok(t)
                    and i not in neighbor_of_long
                    and len(t) > 1
                    and t.lower() not in drop
                    and t.lower() not in _COLOR_WORDS_NAME
                    and t.lower() not in _TOKEN_COLORS
                    and t.upper() not in ("ARGB", "RGB", "LED", "PWM")]
        sku_model = [_display_token(t) for t in sku_toks[:3]]
        # A digit-bearing or multi-token SKU model beats spec prose
        # ("CHIONE E4" over "Real-Time Digital Display"); a lone
        # abbreviation ("CW") never does.
        if sku_model and (any(re.search(r"\d", m) for m in sku_model)
                          or len(sku_model) >= 2):
            model = sku_model
    elif model:
        # Title model accepted, but the SKU may carry an edition marker
        # the title omits ("SE" in Alpha2-SE-A24-WHITE vs the plain A24,
        # whose titles are otherwise identical). Only known edition words
        # merge — vendor-code fragments ("GHS"/"SB"/"TW" in TMS's glued
        # "GHS2LCDS36CB", "MAP"/"T6PS" in "MAP-T6PS-218PK-R1") must never
        # sneak in, which an open-ended merge did (HydroShift/AG400 names
        # regressed). Appended after the title model, capped with it.
        for t in raw_toks:
            if len(model) >= 5:
                break
            if t.upper() not in _EDITION_WORDS:
                continue
            key = _compact_alnum(t)
            if not key or key in seen:
                continue
            seen.add(key)
            model.append(_display_token(t))
    if not model:
        return None

    # A bare brand ("AMD Ryzen") is not a name — let the scrubbed title
    # speak instead (it carries the edition/dims). Same for a model made
    # only of CPU-line echo ("Ryzen Threadripper" for a generic TR4 unit).
    # A single digit-bearing token ("NH-U9S") is a complete model, though.
    if (len(model) < 2 and not size and not tdp and not air_size
            and not lighting and not any(re.search(r"\d", m) for m in model)):
        return None
    if not brand and model and all(
            m.lower() in _CPU_LINE_WORDS for m in model):
        return None

    parts: list[str] = []
    if brand and brand.lower() not in {p.lower() for p in model}:
        parts.append(str(brand))
    parts.extend(model)
    if size:
        parts.append(size)
    if category == "cooler_air":
        if tdp:
            parts.append(tdp)
        elif air_size:
            parts.append(air_size)
    if lighting and _compact_alnum(lighting) not in {
            _compact_alnum(p) for p in parts}:
        parts.append(lighting)
    if category == "aio" and re.search(r"\b(LCD|OLED|DISPLAY|SCREEN)\b", blob, re.I):
        if "LCD" not in {p.upper() for p in parts}:
            parts.append("LCD")
    color = _title_color(group, attributes)
    # A model token may already carry the color as an abbreviation
    # ("AG400 BK ARGB" is already black — don't append "Black").
    if color and color.lower() not in {p.lower() for p in parts}:
        if not any(_TOKEN_COLORS.get(re.sub(r"[^a-z]", "", p.lower())) == color
                   for p in parts):
            parts.append(color)
    return re.sub(r"\s+", " ", " ".join(parts)).strip() or None


# Vendor-exclusive prefixes in SKUs ("ZM-AF120R" is always Zalman; "NF-"
# always Noctua; Noctua's AIO line is "NL-LC1"). Tight: bare model numbers
# never qualify. The cooler map rescues brand-less AIO titles whose maker
# lives only in the SKU ("420mm Quiet All-in-One Water Cooler" is a
# Noctua NL-LC1).
_FAN_SKU_BRANDS = (
    ("zm-", "Zalman"), ("nf-", "Noctua"),
)

_COOLER_SKU_BRANDS = (
    ("nl-lc", "Noctua"),
)


def _cooler_sku_brand(group: list) -> str | None:
    for e in group:
        sku = re.sub(r"[^a-z0-9]+", "-", str(e.get("vendor_sku") or "").lower())
        for prefix, canon in _COOLER_SKU_BRANDS:
            if sku.startswith(prefix):
                return canon
    return None


def _fan_sku_brand(group: list) -> str | None:
    for e in group:
        sku = re.sub(r"[^a-z0-9]+", "-", str(e.get("vendor_sku") or "").lower())
        for prefix, canon in _FAN_SKU_BRANDS:
            if sku.startswith(prefix):
                return canon
    return None


def _fan_canonical_name(group: list, attributes: dict) -> str | None:
    """'Antec 120mm ARGB x3' / 'NF-F12 IndustrialPPC-2000 120mm PWM' from
    brand + model + size + PWM + lighting + pack count."""
    blob = _longest_title(group)
    brand = (_group_brand(attributes, group) or _fan_sku_brand(group))
    if brand in _CHIP_BRANDS and not _STOCK_COOLER_RE.search(blob):
        brand = None


    size = ""
    fsz: Any = attributes.get("fan_size_mm")
    try:
        fsz = int(fsz) if fsz is not None else None
    except (ValueError, TypeError):
        fsz = None
    blob = _longest_title(group)
    if fsz not in (40, 60, 80, 92, 120, 140, 170, 200):
        m = re.search(r"\b(40|60|80|92|120|140|170|200)\s?MM\b", blob, re.I)
        fsz = int(m.group(1)) if m else None
    if fsz:
        size = f"{fsz}mm"

    pwm = attributes.get("pwm") == "Yes" or bool(
        re.search(r"\bPWM\b", blob, re.I))
    li = attributes.get("lighting")
    lighting = ""
    if isinstance(li, str) and li.upper() in ("ARGB", "RGB"):
        lighting = li.upper()
    elif re.search(r"\bARGB\b", blob, re.I):
        lighting = "ARGB"
    elif re.search(r"\bRGB\b", blob, re.I):
        lighting = "RGB"

    pack = ""
    # Hebrew pack counts ("3 מאווררים" = 3 fans) for Ivory/TMS kit titles.
    # No inner word boundary on the x-count: glued "3xFans" is the common
    # vendor spelling ("\bx\b" between x and F never matches).
    m = re.search(r"\b([2-9])\s*x|\bx\s*([2-9])\b|\b([2-9])\s*in\s*1\b|\b([2-9])\s*(?:fan\s*)?pack\b",
                  blob, re.I)
    if not m:
        m = re.search(r"([2-9])\s*מאוורר", blob)
    if m:
        pack = f"x{next(g for g in m.groups() if g)}"
    if not pack:
        # Word packs in kit/pack context ("Triple Starter Kit", "Dual Fan
        # Kit"). Bare "dual" alone is excluded — it usually means dual-loop
        # lighting ("Dual Light Loop"), not two fans — and digit counts
        # above already won where present. "Single" maps to nothing
        # (singles are the unmarked default).
        wm = re.search(
            r"\b(dual|triple|trio|quad)\s+(?:fans?\s+)?(?:kit|pack)\b",
            blob, re.I)
        if wm:
            pack = {"dual": "x2", "triple": "x3", "trio": "x3", "quad": "x4"}[
                wm.group(1).lower()]
    drop = {
        "fan", "fans", "case", "computer", "pc", "pwm", "argb", "rgb", "led",
        "kit", "kits", "pack", "packs", "bulk", "oem", "triple", "quad",
        "with", "without", "for", "and", "performance", "series",
        "edition", "sold", "as", "connected", "each", "other", "requires",
        "controller", "controllers", "remote",
        "control", "in", "on", "at", "amd", "intel", "nvidia",
        "color", "colors", "colour", "colours", "icue", "link",
        # Bearing types are specs ("FDB", "Hydro Bearing"), never model
        # words — the size + lighting already tell fans apart.
        "fdb", "hdb", "rifle", "hydro", "sleeve", "ball", "fluid",
        "dynamic", "magnetic", "levitation", "bearing", "bearings",
        # "single"/"dual" stay: they tell kit twins apart ("Single
        # Expansion" vs "Dual Starter Kit") once xN packs are normalized.
        # "starter"/"expansion"/"trio" stay for the same reason ("Trio" is
        # also Cougar's line name).
    }
    model: list[str] = []
    seen: set[str] = set()

    def _take(clause: str) -> None:
        for tok in _clause_tokens(clause):
            if len(model) >= 3:
                return
            up = tok.upper()
            low = tok.lower()
            if _tok_drop(low, drop) or low in _COLOR_WORDS_NAME:
                continue
            if low in ("mm", "cm"):
                continue
            if re.fullmatch(r"\d+\s?(MM|CM|RPM|DBA?|CFM)\b", up, re.I):
                continue
            # Bare telemetry units ("...1500 RPM 120MM...") are specs, not
            # model words.
            if re.fullmatch(r"(RPM|DBA?|CFM)", up):
                continue
            if re.fullmatch(r"\d+(\.\d+)?", tok):
                continue
            # Single-digit pack counts only ("3x"); model tails ("6500X").
            if re.fullmatch(r"[2-9]\s*x\b|\bx\s*[2-9]\b", low):
                continue
            if _is_brand_word(low, brand):
                continue
            key = re.sub(r"[^a-z0-9]", "", low)
            if not key or key in seen:
                continue
            seen.add(key)
            model.append(_display_token(tok))

    _take(_first_clause(blob))
    if not model:
        # Model lives in a later clause ("120mm PWM Case Fan - F12 RACING
        # ARGB"): scan two more before falling back to the SKU.
        s = re.sub(r"\s+", " ", blob).strip()
        clauses = [p.strip(" ,;:|·")
                   for p in _CLAUSE_SPLIT_RE.split(HEBREW_RUN_RE.sub(" ", s))]
        for clause in clauses[1:3]:
            _take(clause)
            if model:
                break
    if not model:
        # De-dashed SKU ("AEOLUS-P2-1201" -> "AEOLUS P2 1201"): dedupes the
        # otherwise identical "120mm PWM ARGB" generics. Vendor prefixes
        # ("ZM"), single letters ("W" white-abbrev, "R") and colors ride
        # as brand/color, not model words. Compact codes split first
        # ("F12RARGB" -> F12/R/ARGB) the same way.
        brand_prefixes = {p.rstrip("-") for p, _ in _FAN_SKU_BRANDS}
        raw_toks: list[str] = []
        for t in _sku_display_tokens(group):
            raw_toks.extend(_split_compact_sku(t))
        sku_model = [t for t in raw_toks
                     if len(t) > 1
                     and t.lower() not in drop
                     and t.lower() not in _COLOR_WORDS_NAME
                     and t.lower() not in brand_prefixes
                     and not re.fullmatch(r"\d+\s?(MM|CM|RPM|DBA?|CFM)",
                                          t, re.I)]
        model = [_display_token(t) for t in sku_model[:3]]
        if not model:
            return None

    parts: list[str] = []
    if brand:
        parts.append(str(brand))
    parts.extend(model)
    if size:
        parts.append(size)
    if pwm:
        parts.append("PWM")
    if lighting and _compact_alnum(lighting) not in {
            _compact_alnum(p) for p in parts}:
        parts.append(lighting)
    # A screen tells screen twins apart ("UNI SL Wireless LCD" vs the
    # plain "UNI SL Wireless") the same way lighting does.
    if re.search(r"\b(LCD|OLED)\b", blob, re.I):
        if "LCD" not in {p.upper() for p in parts}:
            parts.append("LCD")
    if pack:
        parts.append(pack)
    # Color variants share everything else ("DF120 BLACK" vs "DF120 WHITE").
    color = _title_color(group, attributes)
    if color and color.lower() not in {p.lower() for p in parts}:
        if not any(_TOKEN_COLORS.get(re.sub(r"[^a-z]", "", p.lower())) == color
                   for p in parts):
            parts.append(color)
    if len(parts) <= (1 if brand else 0) and not size:
        return None
    return re.sub(r"\s+", " ", " ".join(parts)).strip() or None


# Memory brand combos for canonical names, first-match-wins on the
# lowercased title (multi-word lines before their parents).
MEMORY_NAME_BRANDS = [
    ("hyperx fury", "HyperX Fury"),
    ("kingston fury", "Kingston Fury"),
    ("kingston beast", "Kingston Beast"),
    ("g.skill", "G.Skill"),
    ("gskill", "G.Skill"),
    ("ripjaws", "G.Skill"),
    ("trident", "G.Skill"),
    ("flare", "G.Skill"),
    ("corsair vengeance", "Corsair Vengeance"),
    ("corsair", "Corsair"),
    ("vengeance", "Corsair"),
    ("kingston", "Kingston"),
    ("hyperx", "HyperX"),
    ("fury", "Kingston Fury"),
    ("beast", "Kingston"),
    ("teamgroup", "TeamGroup"),
    ("t-force", "TeamGroup"),
    ("tforce", "TeamGroup"),
    ("delta", "TeamGroup"),
    ("silicon power", "Silicon Power"),
    ("siliconpower", "Silicon Power"),
    ("adata", "ADATA"),
    ("a data", "ADATA"),
    # ADATA OEM SODIMM prefixes (brand-less titles, maker only in SKU).
    ("ad5s", "ADATA"),
    ("ad4s", "ADATA"),
    ("xpg", "ADATA"),
    ("samsung", "Samsung"),
    ("crucial", "Crucial"),
    ("ballistix", "Crucial"),
    ("sk hynix", "SK Hynix"),
    ("hynix", "SK Hynix"),
    ("patriot", "Patriot"),
    ("viper", "Patriot"),
    ("pny", "PNY"),
    ("oscoo", "OSCOO"),
    ("lexar", "Lexar"),
    ("geil", "GeIL"),
    ("v-color", "V-Color"),
    ("klevv", "Klevv"),
    ("apacer", "Apacer"),
    ("transcend", "Transcend"),
    ("timetec", "Timetec"),
    ("thermaltake", "Thermaltake"),
    ("gloway", "Gloway"),
    # OEM/server lines: brand-less titles whose maker hides in the vendor
    # SKU (Crucial "CT8G4...", Kingston ValueRAM "KVR...", Lexar "LD4AS...").
    # The short SKU prefixes never match whole title words (the title pass
    # needs a trailing boundary); the four below match in titles too and
    # are unambiguous maker signals there as well.
    ("ct", "Crucial"),
    ("kvr", "Kingston"),
    ("ld4", "Lexar"),
    ("ld5", "Lexar"),
    ("thinkpad", "Lenovo"),
    ("lenovo", "Lenovo"),
    ("jetram", "Transcend"),
    ("ktl", "Kingston"),
]


_GATE_STRIP_RE = re.compile(
    r"\b(black|white|silver|gray|grey|red|blue|green|pink|purple|orange|"
    r"beige|brown|gold|argb|rgb|led|lcd|oled|wifi\d?e?|liquid|"
    r"water|cooler|cooling|fan|fans|cpu|aio|system|blade|blades|design|"
    r"icue|link|fdb|hdb|rifle|hydro|sleeve|ball|fluid|dynamic|magnetic|"
    r"levitation|bearings?)\b"
    # Units glued to digits ("1600RPM", "120mm", "1500W") need no leading
    # boundary — \brpm\b never matches inside "1600RPM".
    r"|\b\d+\s?(mm|cm|rpm|dba?|cfm|w|gb|tb|mhz|ghz|pwm)\b"
    r"|\b(rpm|pwm|dba?|cfm)\b",
    re.I,
)


_ROMAN_MODEL_RE = re.compile(r"^(II|III|IV|VI|VII|VIII|IX|X|XI|XII)$", re.I)


def _has_model_id(model: list[str]) -> bool:
    """True when a model token list carries real identity: a digit-bearing
    token ("NH-U9S", "AG400") or a roman-numeral revision ("Freezer III"
    vs "Freezer III Pro" — without this, word-only models always lose to
    the SKU fallback and "ACFRE00150A" becomes "Acfre A")."""
    return any(
        re.search(r"\d", m) or _ROMAN_MODEL_RE.fullmatch(m)
        for m in model)


def _gate_toks(name: str) -> set[str]:
    """Identity tokens of a name minus paint/lighting/size/category trivia
    ("360mm Black Liquid AIO, LCD" carries no identity at all). Single
    letters ("A" from a split "A-RGB") and bare numbers ("3", "12" from
    Hebrew pack/size prose) are scrub artifacts, never identity."""
    s = _GATE_STRIP_RE.sub(" ", str(name or ""))
    toks = re.sub(r"[^a-z0-9]+", " ", s.lower()).split()
    return {t for t in toks if len(t) > 1 and not t.isdigit()}


def _shorter_than_fallback(built: str | None, group: list) -> str | None:
    """Length gate for the speculative builders below: a structured name is
    only an improvement when it is actually shorter than the scrubbed-title
    fallback (ties go to the structured form — deterministic casing beats
    vendor shout-case). A built name that is a strict informational
    SUPERSET of the fallback (same identity + color/lighting/size the
    scrubber ate, e.g. "CHIONE E4-420 Black" vs "CHIONE E4 420") also wins
    within a small premium — otherwise color twins collapse onto one
    colorless name. Returns the winner or None."""
    if not built:
        return None
    built = re.sub(r"\s+", " ", built).strip()
    if not built:
        return None
    fallback = best_name(group)
    if len(built) <= len(fallback):
        return built
    if (_gate_toks(fallback) <= _gate_toks(built)
            and len(built) <= len(fallback) + 25):
        return built
    return None


def build_description(group: list) -> str | None:
    """Vendor spec prose for the product page: the most spec-dense raw title
    in the group (Plonter's dash-dump titles carry the full clause list),
    whitespace-collapsed and capped. The short canonical name carries
    identity; this preserves everything the scrub drops. Returns None when
    there is nothing worth keeping."""
    titles = [(e.get("vendor_id"), str(e.get("title_raw") or ""))
              for e in group]
    titles = [(v, t) for v, t in titles if t.strip()]
    if not titles:
        return None
    plonter = [t for v, t in titles
               if canonical_vendor_id(v) == "plonter"]
    src = max(plonter or [t for _, t in titles], key=len)
    s = html.unescape(src).split('",')[0]
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 500:
        cut = s[:500].rsplit(" ", 1)[0]
        s = (cut or s[:500]).rstrip(" ,;:-") + "…"
    return s or None


def name_from_attributes(
    category: str, attributes: dict, group: list | None = None
) -> str | None:
    """
    Canonical display names built from structured data, not scrubbed titles:
    - cpu: "<brand> <model>" (+ "Dual Core" for 2-core parts, "+ series N"
      for Intel series-tagged parts).
    - memory: "<brand> [model] <type> <cap>GB <speed><unit> [CLnn]".
    - gpu: "<brand> <family> <chip> <vram>GB [edition]".
    - motherboard: "<brand> <chipset> <model...> [WIFI tag]".
    - psu: "<brand> <series...> <watts>W <efficiency> [color]".
    - storage: "<brand> <series...> <cap> <type/interface>".
    - case: "<brand> <model...> [color]".
    - cooler_air/aio: "<brand> <model...> [size|tdp] [lighting] [LCD] [color]".
    - case_fan: "<brand> <model...> <size>mm [PWM] [lighting] [xN]".
    Returns None to fall back to best_name() when the parts aren't there.
    """
    group = group or []
    if category == "cpu":
        brand = attributes.get("brand")
        model = attributes.get("model")
        if not brand or not model:
            return None
        name = f"{brand} {model}".strip()
        cores_raw: Any = attributes.get("cores")
        try:
            cores = int(cores_raw) if cores_raw is not None else None
        except (ValueError, TypeError):
            cores = None
        if cores == 2:
            name += " Dual Core"
        series = attributes.get("series")
        if series and f"series {series}" not in name.lower():
            name += f" series {series}"
        # Tray CPUs are separate products from boxed ones (different
        # items, prices, warranties) — the suffix tells them apart in
        # lists; Box is the unmarked default.
        if attributes.get("packaging") == "Tray":
            name += " Tray"
        return name
    if category == "memory":
        return _memory_canonical_name(group, attributes)
    if category == "gpu":
        return _gpu_canonical_name(group, attributes)
    if category == "motherboard":
        return _shorter_than_fallback(
            _motherboard_canonical_name(group, attributes), group)
    if category == "psu":
        return _shorter_than_fallback(
            _psu_canonical_name(group, attributes), group)
    if category == "storage":
        return _shorter_than_fallback(
            _storage_canonical_name(group, attributes), group)
    if category == "case":
        return _shorter_than_fallback(
            _case_canonical_name(group, attributes), group)
    if category in ("cooler_air", "aio"):
        return _shorter_than_fallback(
            _cooler_canonical_name(group, attributes, category), group)
    if category == "case_fan":
        return _shorter_than_fallback(
            _fan_canonical_name(group, attributes), group)
    return None


def best_name(enriched_listings: list[dict]) -> str:
    """Choose a display name, preferring branded, model-bearing, sane-length titles."""
    if not enriched_listings:
        return "unknown"
    vendor_preference = {"tms": 0, "1pc": 1, "ivory": 2, "plonter": 3}

    def sort_key(e: dict):
        vendor_rank = vendor_preference.get(canonical_vendor_id(e.get("vendor_id")), 9)
        text = e.get("match_text", "") or ""
        has_brand_penalty = 0 if e.get("brand") else 1
        too_long_penalty = 1 if len(text) > 110 else 0
        has_model_bonus = 0 if re.search(r"\d{3,}", text) else 1
        return (has_brand_penalty, too_long_penalty, has_model_bonus, vendor_rank, -len(text))

    chosen = sorted(enriched_listings, key=sort_key)[0]
    title_value = chosen.get("title_raw")
    if isinstance(title_value, str) and title_value.strip():
        raw_title = title_value.strip()
        # Plonter's board and server feeds often put the identity first and
        # then append every port, slot, and compatibility sentence with
        # " - ". If no structured builder won, keep that identity clause
        # instead of truncating a feature dump at an arbitrary word.
        clauses = re.split(r"\s+-\s+", raw_title)
        if len(raw_title) > 120 and len(clauses) >= 3 and len(clauses[0]) >= 16:
            raw_title = clauses[0]
        return display_title(raw_title)
    match_text_value = chosen.get("match_text")
    if isinstance(match_text_value, str) and match_text_value.strip():
        return display_title(match_text_value)
    listing_key_value = chosen.get("listing_key")
    if isinstance(listing_key_value, str) and listing_key_value.strip():
        return display_title(listing_key_value)
    return "unknown"


def choose_best_offer(offers: list[dict]) -> dict | None:
    priced = [o for o in offers if isinstance(o.get("price_ils"), (int, float))]
    if not priced:
        return None

    known_in_stock = [o for o in priced if o.get("in_stock") is True]
    unknown_stock = [o for o in priced if o.get("in_stock") is None]

    if known_in_stock:
        pool = known_in_stock
    elif unknown_stock:
        pool = unknown_stock
    else:
        pool = priced

    return min(
        pool,
        key=lambda o: (
            o["price_ils"],
            o.get("stale", False),
            o.get("vendor_id", ""),
        ),
    )


def merge_offer_attributes(enriched_listings: list[dict]) -> tuple[dict, dict]:
    """
    Union of attributes across all offers of one product.

    If offers disagree on a field, keep the majority value and record the
    disagreement in `conflicts` — an attribute conflict is also a signal
    that the merge itself may be wrong.
    """
    tallies: dict[str, dict[str, list]] = {}

    for e in enriched_listings:
        for k, v in (e.get("attributes") or {}).items():
            if v in (None, ""):
                continue
            norm = str(v).strip().lower()
            slot = tallies.setdefault(str(k), {}).setdefault(norm, [0, v])
            slot[0] += 1

    # Values so vague they lose to any specific rival on the same product:
    # a vendor saying merely "modular" must not outvote "Full Modular"; a
    # gen-less "M.2 PCIe NVMe" must not outvote "M.2 PCIe 4.0 x4".
    VAGUE_VALUES: dict[str, set[str]] = {
        "modular": {"yes"},
        "interface": {"m.2 pcie nvme", "pcie", "nvme"},
    }

    merged: dict = {}
    conflicts: dict = {}

    for k, options in tallies.items():
        if len(options) == 1:
            merged[k] = next(iter(options.values()))[1]
        else:
            vague = VAGUE_VALUES.get(k, set())
            specific = {n: opt for n, opt in options.items() if n not in vague}
            pool = specific or options
            best = max(pool, key=lambda n: pool[n][0])
            merged[k] = pool[best][1]
            conflicts[k] = [opt[1] for opt in options.values()]

    return merged, conflicts


_CPU_TIER_ALIASES = {
    "intel core i3": "I3",
    "intel core i5": "I5",
    "intel core i7": "I7",
    "intel core i9": "I9",
    "intel core ultra 3": "Ultra 3",
    "intel core ultra 5": "Ultra 5",
    "intel core ultra 7": "Ultra 7",
    "intel core ultra 9": "Ultra 9",
    "amd ryzen 3": "Ryzen 3",
    "amd ryzen 5": "Ryzen 5",
    "amd ryzen 7": "Ryzen 7",
    "amd ryzen 9": "Ryzen 9",
}

_CPU_GEN_REWRITES = [
    ("intel core ultra series", "Ultra Series"),
    ("core ultra series", "Ultra Series"),
]


def normalize_cpu_legacy_attrs(attributes: dict) -> None:
    """
    Reconcile the legacy Ivory-style CPU attribute keys (``cpu_tier`` /
    ``cpu_generation``, verbose values like "Intel Core i5" / "Gen 12
    Alder Lake 12th Gen") with the canonical short-form keys that
    ``extractors._parse_cpu`` produces (``tier`` = "I5", ``generation`` =
    "Gen 12").

    This keeps exactly ONE set of tier/generation values per product so the
    filter rail doesn't show two overlapping generation/tier groups with
    inconsistent values. It mutates the dict in place and runs after all
    vendor attributes are merged, before the product is built.
    """
    legacy_gen = attributes.pop("cpu_generation", None)
    legacy_tier = attributes.pop("cpu_tier", None)

    for legacy_key, canonical_key in (
        ("number_of_cores", "cores"),
        ("number_of_processor_cores", "cores"),
        ("processor_cores", "cores"),
        ("core_count", "cores"),
        ("number_of_threads", "threads"),
        ("number_of_processor_threads", "threads"),
        ("processor_threads", "threads"),
        ("thread_count", "threads"),
    ):
        legacy_value = attributes.pop(legacy_key, None)
        if legacy_value is not None and not attributes.get(canonical_key):
            try:
                attributes[canonical_key] = int(str(legacy_value).split()[0])
            except (ValueError, TypeError):
                pass

    if legacy_gen and not attributes.get("generation"):
        g = str(legacy_gen).strip()
        m = re.match(r"^Gen\s+([0-9]+)", g)
        if m:
            attributes["generation"] = f"Gen {m.group(1)}"
        else:
            gl = g.lower()
            for pat, repl in _CPU_GEN_REWRITES:
                if pat in gl:
                    attributes["generation"] = repl
                    break

    if legacy_tier and not attributes.get("tier"):
        t = str(legacy_tier).strip().lower()
        for alias, canonical in _CPU_TIER_ALIASES.items():
            if t.startswith(alias):
                attributes["tier"] = canonical
                break


# --------------------------------------------------------------------------
# Reference specs (pcpartdb + PC Kombo) are merged into product[specs] by
# scraper/specs/build.py with a strict per-category anchor cross-check.
# See scraper/specs/README.md (Tier 0).
# --------------------------------------------------------------------------

PCKOMBO_SPEC_KEYS = {
    "Cache | Cache": "cache_mb",
    "Clock | Base Clock": "base_clock_ghz",
    "Clock | Turbo Clock": "boost_clock_ghz",
    "Core | Cache": "cache_mb",
    "Core | Chipset": "chipset",
    "Core | Clock": "base_clock_ghz",
    "Core | Efficiency Rating": "efficiency",
    "Core | Cores": "cores",
    "Core | Form Factor": "form_factor",
    "Core | NAND": "nand",
    "Core | Protocol": "interface",
    "Core | Ram Type": "memory_type",
    "Core | RPM": "rpm",
    "Core | Socket": "socket",
    "Core | TDP": "tdp",
    "Core | Timings": "timings",
    "Core | Unlocked": "unlocked",
    "Core | Watt": "wattage_w",
    "Cores | Cores": "cores",
    "Cores | Threads": "threads",
    "Dimensions | Length": "length_mm",
    "Dimensions | Slots": "slots",
    "Dimensions | Supported GPU length": "gpu_length_mm",
    "Memory | Memory Capacity": "capacity_gb",
    "Memory | Memory Type": "memory_type",
    "Memory | Supported Ramspeeds": "speed_mhz",
    "Misc | Color": "color",
    "Misc | Form Factor": "form_factor",
    "Misc | Integrated graphics": "integrated_graphics",
    "Misc | Socket": "socket",
    "Misc | TDP": "tdp",
    "Performance | Boost Clock": "boost_clock_ghz",
    "Performance | Memory Clock": "memory_clock_mhz",
    "Performance | Vram": "vram_gb",
}


def _scrub_float_noise(value: str) -> str:
    """Collapse float-arithmetic artifacts in scraped spec strings.

    The PC Kombo dataset carries values like "5.300000000000001 GHz"
    (produced by float math upstream). Round every decimal token to at
    most 3 places and strip trailing zeros, so "5.300000000000001 GHz"
    becomes "5.3 GHz" while clean values ("16GB", "3.8GHz") pass through
    unchanged.
    """

    def _fix(m: re.Match) -> str:
        try:
            rounded = round(float(m.group(0)), 3)
        except (ValueError, OverflowError):
            return m.group(0)
        return f"{rounded:.3f}".rstrip("0").rstrip(".")

    return re.sub(r"\d+\.\d+", _fix, value)


# PC Kombo values carry units and the target field's unit lives in its NAME
# ("_gb", "_mb"), so numbers must be converted, never just extracted. Without
# this a "2 TB" drive landed as capacity_gb=2 and a "1 GB" DRAM cache as
# cache_mb=1 — Tier-0/1 numbers that are simply wrong (Sep 2026).
_PCKOMBO_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "capacity_gb": {"tb": 1000.0, "t": 1000.0},
    "cache_mb": {"gb": 1000.0, "g": 1000.0},
    "vram_gb": {"mb": 1.0 / 1000.0},
}


def normalize_pckombo_specs(specs: dict[str, str]) -> dict[str, str | int | float]:
    """Convert PC Kombo's grouped headers into our canonical filter keys.

    Count/size keys come back as real numbers (matching our own parsers'
    types), everything else stays a string — hence the union value type.
    """
    normalized: dict[str, str | int | float] = {}
    for raw_key, raw_value in specs.items():
        key = PCKOMBO_SPEC_KEYS.get(raw_key)
        if not key or not raw_value or "Notices" in raw_key:
            continue
        if key in normalized:
            continue
        cleaned = _scrub_float_noise(raw_value)
        parsed: str | int | float = cleaned
        if key in {
            "cores", "threads", "cache_mb", "capacity_gb", "speed_mhz",
            "vram_gb", "wattage_w", "length_mm", "gpu_length_mm",
            "memory_clock_mhz", "rpm",
        }:
            match = re.search(r"\d+(?:\.\d+)?", cleaned)
            if match:
                num = float(match.group(0))
                factors = _PCKOMBO_UNIT_FACTORS.get(key)
                if factors:
                    unit = re.search(r"[A-Za-z]+", cleaned[match.end():])
                    if unit:
                        num *= factors.get(unit.group(0).lower(), 1.0)
                # Match our own parsers' types (ints for counts/sizes):
                # a merged "395" next to our 395 would render the same
                # but split strict-equality paths — one type per fact.
                parsed = int(num) if float(num).is_integer() else round(num, 3)
        normalized[key] = parsed
    return normalized


def enrich_products_with_pckombo(products: list[dict]) -> None:
    """Attach PC Kombo specs using exact MPN matches only."""
    if _pckombo_find_by_mpn is None or _pckombo_load_index is None:
        return

    try:
        _pckombo_load_index()
    except (OSError, ValueError) as exc:
        print(f"[pckombo] skipping enrichment (dataset unavailable): {exc}", file=sys.stderr)
        return

    matched = 0
    for product in products:
        mpns = {
            value
            for offer in product.get("offers", [])
            for value in (offer.get("mpn"), offer.get("vendor_sku"))
            if value
        }
        mpns.update(
            value for value in [product.get("attributes", {}).get("mpn")] if value
        )
        candidates = [(_pckombo_find_by_mpn(mpn), mpn) for mpn in mpns]
        rows: list[tuple[dict, Any]] = [
            (row, mpn) for row, mpn in candidates
            if row is not None and row.get("specs")
        ]
        if not rows:
            continue
        row, _ = max(rows, key=lambda item: len(item[0]["specs"]))
        normalized_specs = normalize_pckombo_specs(row["specs"])
        product["attributes"].update(
            (key, value)
            for key, value in normalized_specs.items()
            if key not in product["attributes"]
        )
        # PC Kombo rows are raw German vendor specs ("65 W", "2542 MHz",
        # "256" for board max-memory) — run the same value canonicalization
        # the title parsers get, or the rail shows dupes ("65W" + "65 W").
        # _unify_duplicate_attributes folds keys pckombo introduces under
        # legacy names ("gpu_length_mm" vs our max_gpu_length_mm) — without
        # this the same fact lands under two keys again, one level up.
        try:
            _canonicalize_filter_values(
                product["attributes"], product.get("category") or "")
            _unify_duplicate_attributes(
                product["attributes"], product.get("category") or "")
            _canonicalize_filter_values(
                product["attributes"], product.get("category") or "")
        except Exception:
            pass
        product["pckombo"] = {
            "mpn": row["mpn"],
            "url": row["url"],
            "specs": normalized_specs,
        }
        matched += 1

    print(f"[pckombo] enriched {matched}/{len(products)} products with exact MPN specs")


def _mpn_keys(e: dict) -> set[str]:
    """Compact MPN/SKU identity keys carried by one listing."""
    keys: set[str] = set()
    for raw in (e.get("mpn"), e.get("vendor_sku")):
        if raw:
            k = re.sub(r"[^A-Z0-9]", "", str(raw).upper())
            if k:
                keys.add(k)
    return keys


def _split_series_subgroups(group: list[dict]) -> list[list[dict]]:
    """Split a model-merge group on explicit Intel series conflicts.

    Listings tagged "series 1" vs "series 2" are different parts and must
    never share a product. Listings whose vendor omits the tag ride along
    with the majority explicit series (ties go to the lowest series value,
    deterministic); a group with fewer than two DISTINCT KNOWN series is
    returned whole.
    """
    known: dict[str, list[dict]] = {}
    unknown: list[dict] = []

    for e in group:
        series = str((e.get("attributes") or {}).get("series") or "").strip()
        if series:
            known.setdefault(series, []).append(e)
        else:
            unknown.append(e)

    if len(known) < 2:
        return [group]

    order = sorted(known, key=lambda s: (-len(known[s]), s))
    subs = {s: list(members) for s, members in known.items()}
    for e in unknown:
        subs[order[0]].append(e)
    return [subs[s] for s in order]


def _split_packaging_subgroups(
    group: list[dict],
) -> list[tuple[str, list[dict]]]:
    """Split a model-merge group into (packaging, members) subgroups.

    Box and Tray listings of one model are different items (different
    prices, coolers, warranties) and must never share a product. Listings
    with unknown packaging ride along with the majority subgroup (ties go
    to Box, deterministic) — EXCEPT unknown-packaging listings carrying a
    distinct MPN/SKU unseen among the known-packaging members: those stay
    separate so the MPN tier can place them by their part number instead of
    majority-joining the wrong packaging. A group with fewer than two KNOWN
    packagings is returned whole. The subgroup key is "" when nothing is
    known.
    """
    known: dict[str, list[dict]] = {}
    unknown: list[dict] = []

    for e in group:
        pack = (e.get("attributes") or {}).get("packaging")
        if pack in ("Box", "Tray"):
            known.setdefault(pack, []).append(e)
        else:
            unknown.append(e)

    if len(known) < 2:
        only = next(iter(known)) if known else ""
        return [(only, group)]

    known_keys: set[str] = set()
    for members in known.values():
        for e in members:
            known_keys |= _mpn_keys(e)

    joinable: list[dict] = []
    distinct: list[dict] = []
    for e in unknown:
        keys = _mpn_keys(e)
        if keys and known_keys and keys.isdisjoint(known_keys):
            distinct.append(e)
        else:
            joinable.append(e)

    order = sorted(known, key=lambda p: (-len(known[p]), p))
    subs = {p: list(members) for p, members in known.items()}
    for e in joinable:
        subs[order[0]].append(e)
    out = [(p, subs[p]) for p in order]
    # Distinct-MPN unknowns stay out of the model merge: group same-MPN
    # ones together, singletons alone — downstream the len<2 guard leaves
    # them for the MPN tier.
    by_mpn: dict[str, list[dict]] = {}
    for e in distinct:
        keys = sorted(_mpn_keys(e))
        by_mpn.setdefault(keys[0] if keys else "", []).append(e)
    for _k in sorted(by_mpn):
        out.append(("", by_mpn[_k]))
    return out


_MODEL_TOKEN_RE = re.compile(r"[A-Z]*\d{3,4}[A-Z]*")


def _offer_model_tokens(enriched: dict) -> set[str]:
    """Digit-bearing model tokens of one offer's title ("B850M",
    "5070", "X870E"). Title-only: vendor SKUs name whole model lines
    that collide with cooler families (see the product-level category
    re-vote in match_listings)."""
    try:
        text = _clean(enriched.get("title_raw") or "").upper()
    except Exception:
        return set()
    if not text:
        return set()
    return set(_MODEL_TOKEN_RE.findall(text))


# Unit suffixes stripped before model-token comparison ("5600MT" vs
# "5600MHZ" is unit phrasing for one speed, not a model conflict).
_CONFLICT_UNIT_SUFFIXES = (
    "MHZ", "GHZ", "KHZ", "HZ", "MT", "GT",
    "GB", "TB", "MB", "KB", "PB", "MM", "CM", "RPM", "DB",
)


def _model_token_conflict(sets: list[set[str]]) -> bool:
    """True when two offers' token sets disagree on one model slot:
    tokens that normalize differently but share a core ("B850" vs
    "B850M"). Mere presence/absence (SKU codes one vendor prints and
    another omits: {120MM,BL066} vs {120MM}) and unit phrasing
    ("5600MT" vs "5600MHZ") are not conflicts. Both sides need a
    letter, so bare measurements ("500", "360") never trip this."""
    def _norm(tok: str) -> str:
        for unit in _CONFLICT_UNIT_SUFFIXES:
            if (len(tok) > len(unit) and tok.endswith(unit)
                    and tok[:-len(unit)][-1].isdigit()):
                return tok[:-len(unit)]
        if len(tok) > 1 and tok[-1] in "WV" and tok[-2].isdigit():
            return tok[:-1]
        return tok

    def _core(tok: str) -> str:
        return re.sub(r"[A-Z]+$", "", tok)

    def _has_letter(tok: str) -> bool:
        return bool(re.search(r"[A-Z]", tok))

    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            for a in sets[i]:
                for b in sets[j]:
                    na, nb = _norm(a), _norm(b)
                    if (na != nb and _has_letter(na) and _has_letter(nb)
                            and _core(na) and _core(na) == _core(nb)):
                        return True
    return False


def match_listings(
    enriched_listings: list[dict],
    manual_path: Path | str | None = None,
) -> dict:
    """
    Build canonical products.

    Phase 2A behavior:
    - Manual merges first
    - Exact MPN matches second
    - Exact normalized vendor SKU matches third
    - Everything else becomes a singleton product
    """
    manual_key_to_pid, manual_products, blocked_pairs = load_manual(manual_path)

    assignments: dict[str, str] = {}
    product_meta: dict[str, dict] = {}

    def _is_blocked_pair(lk1: str | None, lk2: str | None) -> bool:
        """Human not_match verdict: these two listings must never share
        a product (Sep 2026). Manual merges override (explicit human
        merge wins over an older veto)."""
        if not lk1 or not lk2 or lk1 == lk2:
            return False
        try:
            return frozenset((lk1, lk2)) in blocked_pairs
        except TypeError:
            return False

    # 1. Manual merges.
    for enriched in enriched_listings:
        pid = manual_key_to_pid.get(enriched["listing_key"])
        if pid:
            assignments[enriched["listing_key"]] = pid

            meta = dict(manual_products.get(pid, {}))
            meta.setdefault("product_id", pid)
            meta.setdefault("matched_by", "manual")
            product_meta.setdefault(pid, meta)

    # 2. Model-based merges.
    #
    # The same physical part sold by different vendors carries a different
    # SKU / product id at each vendor, so MPN/SKU matching can never link
    # them — which is exactly why "the same CPU from three vendors" shows up
    # as three separate one-vendor products instead of one product with three
    # offers. For categories where the model name alone unambiguously
    # identifies the part, merge on (category, brand, model) BEFORE the
    # MPN/SKU tiers so a cross-vendor model match wins over each vendor's
    # own SKU/MPN product.
    #
    # Guarded four ways so we never silently merge the wrong thing:
    #   - Only categories/keys we explicitly trust (see MODEL_MERGE_CATEGORIES).
    #   - Listings that disagree on a critical attribute (DDR generation,
    #     capacity, speed, wattage, etc.) are kept apart.
    #   - Explicit Intel series tags are NEVER merged across ("225" vs
    #     "225 series 2"); listings with no series tag ride with the majority.
    #   - Box vs Tray packaging is NEVER merged: a boxed CPU (retail,
    #     cooler, warranty) and a tray CPU (OEM, bare) are different items
    #     with different prices — merging them defeats the packaging
    #     filter. Each (model, packaging) pair becomes its own product;
    #     listings with unknown packaging join the majority subgroup.
    model_groups: dict[tuple, list[dict]] = {}

    for enriched in enriched_listings:
        if enriched["listing_key"] in assignments:
            continue

        ident = model_identity(enriched)
        if ident is None:
            continue

        model_groups.setdefault(ident, []).append(enriched)

    for ident, group in list(model_groups.items()):
        # A single listing isn't a merge; leave it for the MPN/SKU/singleton
        # tiers.
        if len(group) < 2:
            continue

        category = ident[0]
        slug_part = re.sub(r"[^a-z0-9]+", "-", ident[2]).strip("-")

        # Explicit Intel series conflicts split first ("225" vs
        # "225 series 2" never share a product); packaging splits each
        # series subgroup after that.
        for series_group in _split_series_subgroups(group):
            subgroups = _split_packaging_subgroups(series_group)
            if not subgroups:
                continue

            for pack_key, sub in subgroups:
                # A lone listing isn't a merge (e.g. the only Tray offer of a
                # model otherwise sold boxed) — leave it for the MPN/SKU tiers
                # instead of minting a one-offer "model" product.
                if len(sub) < 2:
                    continue

                # Blocked-pair veto: a human not_match verdict keeps these
                # apart. Vetoed listings fall through to the MPN/SKU tiers
                # instead of merging here.
                accepted = []
                for enriched in sub:
                    if any(_is_blocked_pair(
                            enriched["listing_key"], a["listing_key"])
                            for a in accepted):
                        continue
                    accepted.append(enriched)
                if len(accepted) < 2:
                    continue
                sub = accepted

                # Critical-attribute guard: if any two listings in the
                # prospective merge disagree on a spec that changes the part
                # (e.g. a CPU sold as both 65W and 125W TDP), it's not the same
                # part — drop the subgroup and let each remain separate.
                if any(
                    critical_conflict(a, b)
                    for i, a in enumerate(sub)
                    for b in sub[i + 1 :]
                ):
                    continue

                pid = f"model:{category}:{slug_part}"
                if pack_key == "Tray":
                    pid += "-tray"

                for enriched in sub:
                    assignments[enriched["listing_key"]] = pid

                product_meta.setdefault(
                    pid,
                    {
                        "product_id": pid,
                        "matched_by": "model",
                    },
                )

    # 3. Exact MPN matches.
    mpn_groups: dict[str, list[dict]] = {}

    for enriched in enriched_listings:
        if enriched["listing_key"] in assignments:
            continue

        mpn = enriched.get("mpn")
        category = enriched.get("category_normalized")

        if mpn and category not in ("other", "", None):
            # Key on the normalized MPN (strip dashes/spaces) so identical
            # part numbers match regardless of where each side got it from:
            # 1PC's detail-page extra yields "AK-H81MEL-VS" (dashed), the
            # sku_as_mpn fallback yields "AKH81MELVS" — both must land on
            # the same product. Gigabyte's "GV-" vendor prefix is stripped
            # too ("GV-N5070AERO OC-12GD" == "N5070AEROOC12GD").
            mpn_key = mpn_part_key(mpn)
            pid = f"mpn:{category}:{mpn_key}"
            mpn_groups.setdefault(pid, []).append(enriched)

    for pid, group in mpn_groups.items():
        # Box vs Tray is NEVER merged (same rule as the model tier): a
        # retail-box CPU and its tray twin share the MPN but are different
        # items (mpn:cpu:c7500tp shipped one mixed product before this
        # split existed). Box keeps the base pid (it is the unmarked
        # default); the Tray subgroup becomes pid-tray.
        for pack_key, sub in _split_packaging_subgroups(group):
            sub_pid = f"{pid}-tray" if pack_key == "Tray" else pid
            for enriched in sub:
                # Blocked-pair veto (human not_match): the vetoed listing
                # falls through to the SKU tier instead of joining here.
                _members = [
                    lk for lk, ap in assignments.items() if ap == sub_pid
                ]
                if any(_is_blocked_pair(enriched["listing_key"], lk)
                       for lk in _members):
                    continue
                assignments[enriched["listing_key"]] = sub_pid

            product_meta.setdefault(
                sub_pid,
                {
                    "product_id": sub_pid,
                    "matched_by": "mpn",
                },
            )

    # 4. Exact normalized vendor SKU matches.
    #
    # This helps when multiple vendors use the same model code,
    # e.g. Lian Li O11DMIV2W.
    sku_groups: dict[str, list[dict]] = {}

    for enriched in enriched_listings:
        if enriched["listing_key"] in assignments:
            continue

        category = enriched.get("category_normalized")
        sku_norm = normalize_sku(enriched.get("vendor_sku"))

        if (
            sku_norm
            and len(sku_norm) >= 5
            # Pure-numeric vendor ids (1PC's "217314") are database keys, not
            # part numbers — never merge on them. Long all-digit codes are
            # UPC/EAN/GTINs vendors use as the SKU itself (Antec's
            # "0-761345-10090-8"), so those MAY merge.
            and not (sku_norm.isdigit() and len(sku_norm) < 12)
            and category not in ("other", "", None)
        ):
            # Same GV-strip as the MPN tier so "GV-N5070WF3OC-12GD" (vendor
            # SKU) meets "N5070WF3OC12GD" (detail MPN) on one product.
            pid = f"sku:{category}:{_strip_gv_prefix(sku_norm.lower())}"
            sku_groups.setdefault(pid, []).append(enriched)

    for pid, group in sku_groups.items():
        # Same Box/Tray split as the MPN tier: one vendor SKU covering
        # both packagings must still yield two products.
        for pack_key, sub in _split_packaging_subgroups(group):
            sub_pid = f"{pid}-tray" if pack_key == "Tray" else pid
            for enriched in sub:
                # Blocked-pair veto, same as the MPN tier: vetoed listings
                # fall through to singletons.
                _members = [
                    lk for lk, ap in assignments.items() if ap == sub_pid
                ]
                if any(_is_blocked_pair(enriched["listing_key"], lk)
                       for lk in _members):
                    continue
                assignments[enriched["listing_key"]] = sub_pid

            product_meta.setdefault(
                sub_pid,
                {
                    "product_id": sub_pid,
                    "matched_by": "sku",
                },
            )

    # 4b. MPN/SKU unification.
    #
    # Both tiers above normalize to the same keyspace (strip all
    # non-alphanumerics, lowercase) but emit different pid prefixes, so one
    # vendor reaching a part via its MPN while another reaches the identical
    # part number via its SKU produced two one-vendor products for the same
    # physical part (e.g. 1PC's detail-scraped "5600J3636C16GX2-RS5K" MPN vs
    # TMS's identical vendor SKU while sku_as_mpn rejected digit-leading
    # codes; Antec UPC SKUs vs their MPN-tier twins). An identical normalized
    # part number in the same category is exactly as strong as a within-tier
    # match, so reunite them — preferring the `mpn:` pid as survivor for
    # URL/history stability. Runs before singletons so merged-away pids leave
    # no trace.
    suffix_to_pids: dict[str, list[str]] = {}
    for pid in list(product_meta):
        m = re.match(r"^(?:mpn|sku):([^:]+):(.+)$", pid)
        if m:
            suffix_to_pids.setdefault(f"{m.group(1)}:{m.group(2)}", []).append(pid)

    # Indexed reassignment (was O(pids × listings) with a full scan per
    # merged pid — same result, linear time).
    _pid_members: dict[str, list[str]] = {}
    for _lk, _pid in assignments.items():
        _pid_members.setdefault(_pid, []).append(_lk)
    for suffix, pids in suffix_to_pids.items():
        if len(pids) < 2:
            continue
        survivor = next(
            (p for p in sorted(pids) if p.startswith("mpn:")), sorted(pids)[0]
        )
        for pid in pids:
            if pid == survivor:
                continue
            # Blocked-pair veto: never reunite two pids across a human
            # not_match verdict — the vetoed pid stays separate.
            try:
                _cross_blocked = any(
                    _is_blocked_pair(a, b)
                    for a in _pid_members.get(pid, [])
                    for b in _pid_members.get(survivor, [])
                )
            except Exception:
                _cross_blocked = False
            if _cross_blocked:
                continue
            for _lk in _pid_members.pop(pid, []):
                assignments[_lk] = survivor
                _pid_members.setdefault(survivor, []).append(_lk)
            product_meta.pop(pid, None)

    # 4c. Merge consistency guard (Sep 2026): never auto-merge across a
    # hard spec conflict, and flag same-MPN title disagreements instead
    # of silently concatenating them (see the Phase-1 chimera fix).
    # Runs on MPN/SKU-tier groups only — manual and model-tier merges
    # are human/explicit and out of scope.
    # - Naming conflict: offers disagree on one model slot (same core,
    #   different token: 1PC "B850-F" vs TMS/Ivory "B850M-F" on
    #   90MB1N90-M0EAY0) with one identical compact MPN. Kept merged
    #   (user decision) but flagged: attribute_conflicts["model_titles"]
    #   + product["naming_conflict"] + a naming_conflict QA case.
    #   Presence/absence (a SKU code one vendor prints) and unit
    #   phrasing ("5600MT" vs "5600MHZ") never flag — see
    #   _model_token_conflict.
    # - Split: differing compact MPNs inside one group PLUS a
    #   critical_conflict (extended: board size letter, WiFi) between
    #   the pair — those listings fall through to singletons.
    _naming_flagged: dict[str, list[str]] = {}
    _e_by_lk = {e["listing_key"]: e for e in enriched_listings}
    _auto_pids = {
        pid for pid, meta in product_meta.items()
        if meta.get("matched_by") in ("mpn", "sku")
    }
    _guard_members: dict[str, list[str]] = {}
    for _lk, _pid in assignments.items():
        if _pid in _auto_pids:
            _guard_members.setdefault(_pid, []).append(_lk)
    for _pid, _members in list(_guard_members.items()):
        if len(_members) < 2:
            continue
        _mes = [_e_by_lk[lk] for lk in _members if lk in _e_by_lk]
        if len(_mes) < 2:
            continue
        _to_split: set[str] = set()
        for _i, _a in enumerate(_mes):
            for _b in _mes[_i + 1:]:
                _ma, _mb = _a.get("mpn"), _b.get("mpn")
                if (_ma and _mb
                        and mpn_part_key(_ma) != mpn_part_key(_mb)
                        and critical_conflict(_a, _b)):
                    _to_split.add(_a["listing_key"])
                    _to_split.add(_b["listing_key"])
        for _lk in _to_split:
            assignments.pop(_lk, None)
        _survivors = [lk for lk in _members if lk not in _to_split]
        if not _survivors:
            product_meta.pop(_pid, None)
            continue
        if _to_split:
            _mes = [_e_by_lk[lk] for lk in _survivors if lk in _e_by_lk]
            if len(_mes) < 2:
                continue
        _mpns = {e.get("mpn") for e in _mes if e.get("mpn")}
        if _mpns and len({mpn_part_key(m) for m in _mpns}) == 1:
            _sets = []
            for e in _mes:
                _toks = _offer_model_tokens(e)
                if _toks:
                    _sets.append(_toks)
            if len(_sets) >= 2 and _model_token_conflict(_sets):
                _naming_flagged[_pid] = sorted({
                    str(e.get("title_raw") or "").strip()
                    for e in _mes
                    if str(e.get("title_raw") or "").strip()
                })

    # 5. Singletons.
    for enriched in enriched_listings:
        if enriched["listing_key"] in assignments:
            continue

        category = enriched.get("category_normalized", "other")
        vendor = enriched.get("vendor_id", "unknown")
        pid = f"{category}:{vendor}:{slug(enriched['listing_key'])}"

        assignments[enriched["listing_key"]] = pid
        product_meta.setdefault(
            pid,
            {
                "product_id": pid,
                "matched_by": "singleton",
                "category": category,
            },
        )

    # Build product objects (indexed once — was a full listings scan per
    # product, i.e. O(products × listings)).
    products = []
    product_sizes: dict[str, int] = {}
    _by_listing_key = {e["listing_key"]: e for e in enriched_listings}
    _groups: dict[str, list[dict]] = {}
    for _lk, _pid in assignments.items():
        _e = _by_listing_key.get(_lk)
        if _e is not None:
            _groups.setdefault(_pid, []).append(_e)

    for pid, meta in product_meta.items():
        group = _groups.get(pid, [])
        product_sizes[pid] = len(group)

        if not group:
            continue

        offers = [offer_from_listing(e) for e in group]
        offers.sort(
            key=lambda o: (
                o.get("vendor_id", ""),
                o.get("price_ils") is None,
                o.get("price_ils") if o.get("price_ils") is not None else 0,
            )
        )

        category = meta.get("category") or group[0].get("category_normalized", "other")
        # Title-only vote: match_text carries the vendor SKU, and SKUs name
        # whole model lines ("Frozen-Warframe-...") that collide with the
        # air-cooler families — e.g. Thermalright Frozen (AIO) vs ID-Cooling
        # Frozn (air). The per-listing pass already folded any SKU-only
        # signal it trusts into category_normalized; re-voting with the SKU
        # here only reintroduces the collision.
        title_categories = {
            _category_from_title(
                _clean(e.get("title_raw", "")).lower()
            )
            for e in group
        }
        # Product-level backstop: every offer's title re-voted after the
        # per-listing pass, so a stale vendor bucket cannot hold a product
        # in the wrong cooling family (e.g. TMS HydroShift singletons filed
        # as cooler_air before the Hebrew/liquid fixes, or a Plonter air
        # cooler that slipped into aio via one bad title). Only fires when
        # the titled offers unanimously agree — mixed groups keep the
        # matched (MPN/SKU) category.
        _mapped_titles = {
            ("accessories" if tc in ACCESSORY_CATEGORIES else tc)
            for tc in title_categories if tc
        }
        if category in ("case_fan", "cooler_air", "aio", "cooling_other",
                        "accessories") and len(_mapped_titles) == 1:
            _voted = next(iter(_mapped_titles))
            if _voted in ("case_fan", "cooler_air", "aio", "accessories",
                          "cooling_other") and _voted != category:
                category = _voted
        elif category in ("case_fan", "cooling_other"):
            if "aio" in title_categories:
                category = "aio"
            elif "cooler_air" in title_categories:
                category = "cooler_air"
            elif "case_fan" in title_categories:
                category = "case_fan"

        merged_attributes, attribute_conflicts = merge_offer_attributes(group)

        mpns: set[str] = {
            mpn for e in group if (mpn := e.get("mpn"))
        }
        # Dash-variant twins ("90MB1N90-M0EAY0" vs "90MB1N90M0EAY0") match
        # identically via mpn_part_key but compare as 2 raw strings, which
        # left model None. Fold via mpn_part_key; when all compact forms
        # agree, keep the dashed-preferred form (prefer "-", then longest,
        # then lexicographic) so display MPN/model and cellSpec readers see
        # one canonical value.
        mpn_chosen: str | None = None
        if mpns:
            if len(mpns) == 1:
                mpn_chosen = next(iter(mpns))
            else:
                try:
                    compact_forms = {mpn_part_key(m) for m in mpns}
                except Exception:
                    compact_forms = set()
                if len(compact_forms) == 1:
                    def _mpn_rank(m: object) -> tuple[int, int, str]:
                        s = str(m)
                        return (0 if "-" in s else 1, -len(s), s)
                    mpn_chosen = sorted(mpns, key=_mpn_rank)[0]
            if mpn_chosen is not None:
                merged_attributes["mpn"] = mpn_chosen

        # Surface the real manufacturer part number as the product model so
        # the site shows "AK-H81MEL-VS" instead of a vendor-internal id
        # ("126902") or a product-id slug. Attributes' own model (parsed
        # from titles, e.g. "Ryzen 3 4100") wins when present.
        model = meta.get("model") or merged_attributes.get("model")
        if not model and mpn_chosen is not None:
            model = mpn_chosen

        if any(e.get("bundle_only") for e in group):
            merged_attributes["bundle_only"] = True

        attributes = {
            **merged_attributes,
            **meta.get("attributes", {}),
        }
        normalize_cpu_legacy_attrs(attributes)

        canonical_name = (
            meta.get("canonical_name")
            or name_from_attributes(category, merged_attributes, group)
            or best_name(group)
        )
        # Vendor spec prose (Plonter's dash-dump title when present): kept
        # only when it adds information beyond the name, so the site payload
        # doesn't pay ~bytes for an echo of the title.
        description = build_description(group)
        if description and len(description) <= len(canonical_name or "") + 30:
            description = None

        product = {
            "product_id": meta.get("product_id", pid),
            "canonical_name": canonical_name,
            "description": description,
            "category": category,
            "brand": meta.get("brand") or next(
                (e.get("brand") for e in group if e.get("brand")),
                None,
            ),
            "model": model,
            "attributes": attributes,
            "matched_by": meta.get("matched_by", "auto"),
            "vendor_count": len({o.get("vendor_id") for o in offers if o.get("vendor_id")}),
            "offers": offers,
        }

        # Cover photo: the best candidate across the group's offers, not the
        # first one that carries any URL. See scraper/image_score.py — an
        # audited 657 TMS covers on disk were 228px listing tiles because
        # "first" won, while the same product page served a 1500px original,
        # and the offer list order is not a quality signal in any case.
        # Deterministic scoring means the pick only moves when the data does.
        # No local-file metrics here on purpose: the matcher must never touch
        # data/images (the download step runs after it).
        image_candidates: list[dict] = []
        for e in group:
            for url in candidate_urls(str(e.get("image_url") or "")):
                image_candidates.append({
                    "url": url,
                    "vendor": e.get("vendor_id"),
                    "in_stock": bool(e.get("in_stock")),
                })
        img = pick_image(image_candidates, category=str(category))
        if img:
            product["image_url"] = img["url"]

        if pid in _naming_flagged:
            attribute_conflicts.setdefault(
                "model_titles", _naming_flagged[pid])
        if attribute_conflicts:
            product["attribute_conflicts"] = attribute_conflicts

        # Duplicate-vendor flag (public): one vendor contributing ≥2 offers
        # with different vendor_skus to the same product (e.g. 1PC Box+Tay
        # twins landing together). Same-SKU dedupe in
        # dedupe_enriched_listings stays unflagged — only genuinely distinct
        # listings trip this.
        dup_vendors: list[str] = []
        by_vendor: dict[str, list[dict]] = {}
        for o in offers:
            by_vendor.setdefault(str(o.get("vendor_id") or ""), []).append(o)
        for vendor, olist in by_vendor.items():
            if not vendor or len(olist) < 2:
                continue
            skus = {str(o.get("vendor_sku") or "").strip() for o in olist}
            if len(skus) > 1:
                dup_vendors.append(vendor)
        if dup_vendors:
            product["duplicate_vendors"] = sorted(dup_vendors)

        # Merge-consistency flag (see tier 4c): same compact MPN, but
        # the offers' titles disagree on the model. Kept merged by
        # decision; surfaced for human review via qa.json.
        if pid in _naming_flagged:
            product["naming_conflict"] = True

        product["best_offer"] = choose_best_offer(offers)
        products.append(product)

    # Reference specs are merged by scraper/specs/build.py (Tier 0)
    # inside build_product_specs(); nothing to attach here anymore.
    enrich_products_with_pckombo(products)

    products.sort(key=lambda p: p.get("product_id", ""))

    return {
        "products": products,
        "assignments": assignments,
        "product_sizes": product_sizes,
    }


def find_duplicate_vendor_cases(products: list[dict]) -> list[dict]:
    """Public QA cases for products with duplicate same-vendor listings.

    One entry per (product, vendor) with ≥2 offers under different
    vendor_skus. Entries carry kind="duplicate_vendor" so the #/qa page can
    filter them; legacy fuzzy entries have no kind and are unaffected.
    """
    cases: list[dict] = []
    for product in products:
        dup_vendors = product.get("duplicate_vendors") or []
        if not dup_vendors:
            continue
        by_vendor: dict[str, list[dict]] = {}
        for o in product.get("offers", []):
            by_vendor.setdefault(str(o.get("vendor_id") or ""), []).append(o)
        for vendor in sorted(dup_vendors):
            olist = by_vendor.get(vendor, [])
            cases.append(
                {
                    "kind": "duplicate_vendor",
                    "product_id": product.get("product_id"),
                    "category": product.get("category"),
                    "vendor": vendor,
                    "offers": [
                        {
                            "listing_key": o.get("listing_key"),
                            "vendor_sku": o.get("vendor_sku"),
                            "title": o.get("title_raw"),
                            "price": o.get("price_ils"),
                        }
                        for o in olist
                    ],
                }
            )
    return cases


def find_naming_conflict_cases(products: list[dict]) -> list[dict]:
    """Public QA cases for same-MPN products whose offer titles disagree
    on the model (tier-4c flag). One entry per product; same offer shape
    as find_duplicate_vendor_cases plus the conflicting titles, so the
    #/qa page renders both kinds uniformly.
    """
    cases: list[dict] = []
    for product in products:
        if not product.get("naming_conflict"):
            continue
        cases.append(
            {
                "kind": "naming_conflict",
                "product_id": product.get("product_id"),
                "category": product.get("category"),
                "vendor": "",
                "titles": list(
                    (product.get("attribute_conflicts") or {}).get(
                        "model_titles", [])
                ),
                "offers": [
                    {
                        "listing_key": o.get("listing_key"),
                        "vendor_sku": o.get("vendor_sku"),
                        "title": o.get("title_raw"),
                        "price": o.get("price_ils"),
                    }
                    for o in product.get("offers", [])
                ],
            }
        )
    return cases


# --------------------------------------------------------------------------
# Optional fuzzy review suggestions
# --------------------------------------------------------------------------

def extract_critical_attributes(text: str) -> dict:
    """
    Very rough critical attribute extraction.

    This is only used to prevent obvious bad fuzzy merges.
    """
    t = _clean(text).lower()
    compact = re.sub(r"\s+", "", t)

    out: dict = {
        "ddr": None,
        "total_gb": None,
        "speed_mhz": None,
        "wattage": None,
        "pack_size": None,
        "revs": re.findall(r"\b[vr]\d+\b", t),
    }

    m = re.search(r"ddr([3-5])", compact)
    if m:
        out["ddr"] = m.group(1)

    m = re.search(r"(\d+)gb", compact)
    if m:
        out["total_gb"] = m.group(1)

    m = re.search(r"(\d{3,4})mhz", compact)
    if m:
        out["speed_mhz"] = m.group(1)

    m = re.search(r"(\d{3,4})w\b", t)
    if m:
        out["wattage"] = m.group(1)

    m = re.search(r"\b(\d+)\s*(?:pack|pcs|pieces)\b", t)
    if not m:
        m = re.search(r"\bpack of\s*(\d+)\b", t)
    if m:
        out["pack_size"] = m.group(1)

    return out


def _board_wifi_signals(enriched: dict) -> tuple[list[str], bool | None]:
    """Title-only board identity signals for the tier-4c split check.

    Letter-led digit tokens ("B850M", "X870E") plus a WiFi mention flag.
    Title-only on purpose: match_text carries vendor SKU/box codes
    (Intel "BX80715..." vs tray codes) that differ across vendors for
    one chip and must never split a merge. CPU digit-led models
    ("14700K", "5600X") yield no board tokens by construction, so the
    CPU model tier is untouched.
    """
    try:
        up = _clean(enriched.get("title_raw") or "").upper()
    except Exception:
        return [], None
    boards = sorted({
        tok for tok in _MODEL_TOKEN_RE.findall(up)
        if re.match(r"^[A-Z]+\d", tok)
    })
    wifi: bool | None = None
    if re.search(r"\bWI-?FI(\dE?)?\b", up):
        wifi = True
    elif boards:
        wifi = False
    return boards, wifi


def critical_conflict(a: dict, b: dict) -> bool:
    ca = extract_critical_attributes(a.get("match_text", ""))
    cb = extract_critical_attributes(b.get("match_text", ""))

    if ca["ddr"] and cb["ddr"] and ca["ddr"] != cb["ddr"]:
        return True

    if ca["total_gb"] and cb["total_gb"] and ca["total_gb"] != cb["total_gb"]:
        return True

    if ca["speed_mhz"] and cb["speed_mhz"] and ca["speed_mhz"] != cb["speed_mhz"]:
        return True

    if ca["wattage"] and cb["wattage"] and ca["wattage"] != cb["wattage"]:
        return True

    if ca["pack_size"] and cb["pack_size"] and ca["pack_size"] != cb["pack_size"]:
        return True

    if ca["revs"] and cb["revs"] and not set(ca["revs"]) & set(cb["revs"]):
        return True

    # Motherboard form-factor letter ("B850M" vs "B850") and WiFi
    # presence: different boards that must never auto-merge. Title-only
    # signals (see _board_wifi_signals) — the CPU model tier only ever
    # pairs digit-led CPU models, which yield no board tokens.
    ba, wa = _board_wifi_signals(a)
    bb, wb = _board_wifi_signals(b)
    if ba and bb:
        if not set(ba) & set(bb):
            return True
        if wa is not None and wb is not None and wa != wb:
            return True

    return False


def suggest_fuzzy_matches(
    enriched_listings: list[dict],
    manual_path: Path | str | None = None,
    threshold: int = 88,
    exclude_multi_keys: set[str] | None = None,
    assignments: dict[str, str] | None = None,
) -> list[dict]:
    """
    Generate fuzzy match candidates for manual review.

    This does not merge anything automatically.

    Requires:
        pip install rapidfuzz

    If rapidfuzz is not installed, this returns an empty list.
    """
    if fuzz is None:
        return []

    _, _, blocked_pairs = load_manual(manual_path)
    exclude_multi_keys = set(exclude_multi_keys or [])

    buckets: dict[tuple[str, str], list[dict]] = {}

    for enriched in enriched_listings:
        category = enriched.get("category_normalized")
        brand = enriched.get("brand")

        if category in ("other", "", None):
            continue

        # Unknown-brand fuzzy matching is too noisy for Phase 2A.
        if not brand:
            continue

        buckets.setdefault((category, brand), []).append(enriched)

    suggestions = []

    for (category, brand), items in buckets.items():
        if len(items) < 2:
            continue

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a = items[i]
                b = items[j]

                a_key = a["listing_key"]
                b_key = b["listing_key"]

                if not a.get("match_text") or not b.get("match_text"):
                    continue

                if (
                    assignments
                    and assignments.get(a_key)
                    and assignments.get(a_key) == assignments.get(b_key)
                ):
                    continue

                # If both are already in multi-vendor merged products, skip.
                if a_key in exclude_multi_keys and b_key in exclude_multi_keys:
                    continue

                if frozenset((a_key, b_key)) in blocked_pairs:
                    continue

                # If both have MPNs and they differ, do not suggest.
                if a.get("mpn") and b.get("mpn") and a["mpn"] != b["mpn"]:
                    continue

                if critical_conflict(a, b):
                    continue

                score = fuzz.token_set_ratio(
                    a.get("match_text", ""),
                    b.get("match_text", ""),
                )

                if score >= threshold:
                    suggestions.append(
                        {
                            "score": int(score),
                            "category": category,
                            "brand": brand,
                            "listing_a": a_key,
                            "listing_b": b_key,
                            "title_a": a.get("title_raw"),
                            "title_b": b.get("title_raw"),
                            "match_text_a": a.get("match_text"),
                            "match_text_b": b.get("match_text"),
                        }
                    )

    suggestions.sort(key=lambda x: -x["score"])
    return suggestions