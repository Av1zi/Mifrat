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
from urllib.parse import unquote

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

try:
    from scraper.extractors import extract_attributes
except ImportError:
    from extractors import extract_attributes

# Optional: docyx/pc-part-dataset reference specs (Aug 2026, see
# DECISIONS.md). Never required for the core pipeline — if it can't be
# imported (or the index hasn't been built), enrich_products_with_pcpartdb()
# below skips itself entirely and the catalog builds exactly as before.
try:
    from scraper.pcpartdb import find_matches as _pcpartdb_find_matches
    from scraper.pcpartdb import load_index as _pcpartdb_load_index
except ImportError:
    try:
        from pcpartdb import find_matches as _pcpartdb_find_matches
        from pcpartdb import load_index as _pcpartdb_load_index
    except ImportError:
        _pcpartdb_find_matches = None
        _pcpartdb_load_index = None

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
    "fury": "Kingston Fury",
    "patriot": "Patriot",
    "viper": "Patriot Viper",
    "g.skill": "G.Skill",

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
    s = unicodedata.normalize("NFKC", s)

    # Common mojibake / trademark noise seen in some feeds.
    s = s.replace("Ö²Â®", " ")

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
    r"\b(aio|all-in-one|liquid|watercool|water cool|radiator|hydro|"
    r"kraken|eisbaer|eiswolf|nucleus|masterliquid|silent loop|ryujin|ryuo|"
    r"liquid freezer|galahad|ek-aio|coolit|alphacool)\b"
)
AIR_TITLE_RE = re.compile(
    r"\b(cpu cooler|air cooler|tower cooler|heatsink|heat sink|"
    r"peerless assassin|phantom spirit|assassin x|assassin spirit|"
    r"ak400|ak620|nh-d|nh-u|nh-l|nh-p|nh-a|dark rock|pure rock|shadow rock|"
    r"hyper 212|freezer 3[46]|freezer i|freezer e|big shuriken|katana|"
    r"grandis|ta-?120|ps120|pa120|axp90|ax120)\b"
)


def _category_from_title(title_clean: str) -> str | None:
    """Strong title-based hints for sub-classifying messy listings."""
    if not title_clean:
        return None
    t = title_clean
    if "thermal paste" in t or "thermal grease" in t:
        return "thermal_paste"
    if "mounting kit" in t and "cooler not included" in t:
        return "cooler_accessory"
    if "fan controller" in t or "fan hub" in t:
        return "fan_controller"
    if "splitter" in t and ("fan" in t or "rgb" in t or "argb" in t):
        return "fan_controller"
    if "light strip" in t or "light strips" in t or "rgb led" in t:
        return "rgb_lighting"
    if "starter kit" in t and "fan" in t:
        return "case_fan"
    if "expansion kit" in t and "fan" in t:
        return "case_fan"
    if re.search(r"\b\d{2,3}\s*mm\b", t) and re.search(r"\bfans?\b", t):
        return "case_fan"
    # AIO check must run before the air-cooler check ("Liquid Freezer" etc.)
    if AIO_TITLE_RE.search(t):
        return "aio"
    if AIR_TITLE_RE.search(t):
        return "cooler_air"
    # --- broad fallbacks, used only when the vendor guess is missing/unknown ---
    if re.search(r"\b(ssd|solid state|nvme|m\.2)\b", t):
        return "storage"
    if re.search(r"\bddr[345]\b", t) and re.search(
        r"\b(ram|memory|dimms?|vengeance|trident|ripjaws|fury|predator)\b|\d+\s?gb\b", t
    ):
        return "memory"
    if re.search(r"\b(geforce|radeon|quadro|arc a|arc b|rtx \d|rx \d)\b", t):
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
    r"\b(crypto|bitcoin|btc|ethereum|mining|miner)\b(?!.{0,24}\b(motherboard|board)\b)",
    re.I,
)
MONITOR_RE = re.compile(r"\b(monitor|television|led tv)\b", re.I)

def _is_junk_listing(title_clean: str) -> bool:
    return bool(RISER_RE.search(title_clean) or MINING_CARD_RE.search(title_clean))


def _reclassify(category: str, title_clean: str) -> str:
    if category == "gpu" and MONITOR_RE.search(title_clean):
        return "other"
    return category

def canonical_category(guess: str | None, title: str = "") -> str:
    """Map vendor category guesses into canonical categories."""
    raw_key = _compact_key(guess).replace("bundleonly", "")
    title_clean = _clean(title).lower()

    # Hard blacklist: risers / mining cards never enter a build category —
    # dump them into "other" (owner decision, Aug 2026).
    if _is_junk_listing(title_clean):
        return "other"

    title_cat = _category_from_title(title_clean)

    if raw_key in CATEGORY_ALIASES:
        category = CATEGORY_ALIASES[raw_key]
    elif raw_key.startswith("case") and "fan" not in raw_key:
        category = "case"
    else:
        # No usable vendor guess — fall back to title detection before "other".
        category = title_cat or "other"

    # Plonter sometimes puts accessory items under COMPUTER CASES.
    if category == "case" and title_cat in ACCESSORY_CATEGORIES:
        return title_cat

    # Ambiguous cooling guesses ("Fans and Cooling solutions", "cpu cooler").
    if category == "cooling":
        if title_cat in ("aio", "cooler_air", "case_fan"):
            return title_cat
        return "cooling_other"

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


# --------------------------------------------------------------------------
# Enrichment
# --------------------------------------------------------------------------

def enrich_listing(listing: dict) -> dict:
    """
    Add Phase 2 matching metadata to a raw listing.

    This does not mutate the original spider contract; it only adds fields.
    """
    enriched = dict(listing)

    enriched["vendor_id"] = canonical_vendor_id(listing.get("vendor_id"))
    enriched["listing_key"] = listing_key(listing)

    enriched["price_ils_raw"] = listing.get("price_ils")
    enriched["price_ils"] = normalize_price(listing.get("price_ils"))

    enriched["category_normalized"] = canonical_category(
        listing.get("category_guess"),
        listing.get("title_raw", ""),
    )

    enriched["match_text"] = match_text(listing)
    enriched["brand"] = detect_brand(enriched["match_text"])
    enriched["mpn"] = extract_mpn(enriched["match_text"])

    enriched["bundle_only"] = "bundle-only" in str(listing.get("category_guess", "")).lower()

    enriched["attributes"] = extract_attributes(enriched)

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
    return {
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


TITLE_NOISE_RE = re.compile(
    r"\b(free shipping|ship(?:s|ping)? worldwide|brand new|new in (?:sealed )?box|"
    r"open box|b-?stock|refurbished|used|best price|cheap|wholesale|"
    r"bulk (?:pack|order)|with (?:heatsink|fan|rgb lighting)|color tray|"
    r"flat color|flat|tray|"
    r"oem(?: (?:box|packaging))?|retail (?:box|packaging)|warranty included|"
    r"\d+(?:-| )?years? (?:warranty|warr)|incl\.? (?:vat|ma'am)|vat included)\b",
    re.I,
)

# Generic part-type words vendors prepend to titles ("Motherboard ARKTEK...",
# "Processor AMD..."). These add nothing once the product already has a
# category, so strip them from the front of a display name only.
LEADING_CATEGORY_WORD_RE = re.compile(
    r"^(motherboard|processor|cpu|graphics card|video card|power supply|"
    r"memory|ram|case|chassis|cooler)\b[\s:.-]*",
    re.I,
)

# Extra filler phrases scrubbed from display names (beyond TITLE_NOISE_RE,
# which targets match-text). All case-insensitive, applied to raw titles.
NAME_FILLER_RE = re.compile(
    r"\b(processor|processors|graphics card|video card|motherboard|power supply|"
    r"with integrated graphics|color tray|flat color|\bdimm\b)\b",
    re.I,
)

HEBREW_RUN_RE = re.compile(r"[\u0590-\u05FF]+")
TRADEMARK_RE = re.compile(r"[®™©℗ªº]")
# "(series 2)" is identity, not noise (disambiguates same-numbered Intel
# parts) — hoisted out before the generic paren-drop below.
SERIES_PAREN_RE = re.compile(r"\(\s*series\s?(\d{1,2})\s*\)", re.I)
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
    s = HEBREW_RUN_RE.sub(" ", s)
    s = TRADEMARK_RE.sub("", s)
    sm = SERIES_PAREN_RE.search(s)
    series_tag = f" series {sm.group(1)}" if sm else ""
    s = SERIES_PAREN_RE.sub(" ", s)
    s = PAREN_RE.sub(" ", s)
    s = LEADING_CATEGORY_WORD_RE.sub("", s)
    s = TITLE_NOISE_RE.sub(" ", s)
    s = NAME_FILLER_RE.sub(" ", s)
    # Split on dash separators, drop empties (kills "- -" artifacts), rejoin.
    parts = [p.strip(" ,;:|·") for p in DASH_RUN_RE.split(s)]
    parts = [p for p in parts if p]
    s = " ".join(parts)
    # Trailing MPN tail: token with a slash ("HX318LC11FB/8") or a long
    # digit-letter jumble at the very end. Board model numbers survive
    # because they rarely end the title after spec tokens... conservative:
    # only slash-tokens and 12+ char all-caps jumbles go.
    toks = s.split(" ")
    while toks and (
        "/" in toks[-1]
        or (len(toks[-1]) >= 12 and re.fullmatch(r"[A-Z0-9-]+", toks[-1]) and re.search(r"\d", toks[-1]) and re.search(r"[A-Z]", toks[-1]))
    ):
        toks.pop()
    s = " ".join(toks)
    # Dedupe consecutive duplicate words ("Intel Intel", "DDR4 DDR4").
    words = s.split(" ")
    deduped = [words[0]] if words else []
    for w in words[1:]:
        if w.lower() != deduped[-1].lower():
            deduped.append(w)
    s = re.sub(r"\s{2,}", " ", " ".join(deduped)).strip(" -–—|·,;:")
    if series_tag and series_tag.strip().lower() not in s.lower():
        s = f"{s}{series_tag}"
    return s


def display_title(text: str, max_len: int = 120) -> str:
    """Trim marketing noise and hard-cap display names."""
    s = _scrub_title(text)
    if not s:
        return "unknown"
    if len(s) > max_len:
        cut = s[:max_len]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        s = cut.rstrip(" -–—|·,;:") + "…"
    return s or "unknown"


def _memory_canonical_name(group: list[dict], attributes: dict) -> str | None:
    """'Kingston DDR4 8GB 3200 CL22' from structured parts + title tokens.

    Brand: first matching combo below (word-boundary, title order across
    the group). Model: first digit-bearing token after the brand span that
    isn't itself a spec token (capacity/speed/CL/JEDEC/voltage/DIMM/color).
    Specs (capacity/type/speed/CAS) come from attributes, so Hebrew filler
    and MPN tails never survive.
    """
    cap = attributes.get("capacity_gb") or attributes.get("total_gb")
    try:
        cap = int(cap) if cap is not None else None
    except (ValueError, TypeError):
        cap = None
    mem_type = attributes.get("memory_type")
    speed = attributes.get("speed_mhz")
    try:
        speed = int(speed) if speed is not None else None
    except (ValueError, TypeError):
        speed = None
    cas = attributes.get("cas_latency")
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
    for key, canon in MEMORY_NAME_BRANDS:
        m = re.search(rf"\b{re.escape(key)}\b", low)
        if m:
            brand = canon
            brand_end = m.end()
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
    model = ""
    after = clean[brand_end:]
    cap_all = re.search(r"\d+\s?GB", clean, re.I)
    if cap_all and cap_all.start() > brand_end:
        region = clean[brand_end:cap_all.start()]
    elif cap_all:
        region = ""
    else:
        region = after[:80]
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", region):
        up = tok.upper()
        if re.fullmatch(r"(DDR\dL?|PC\d+\S*|\d+G(B)?|\d+MHZ|\d+MT/S|CL\d+|1\.\d+V?|DIMM|SODIMM|RGB|ARGB|BLACK|WHITE|GREY|GRAY|RED|BLUE|GREEN)", up, re.I):
            continue
        if tok.isdigit():
            continue
        if re.search(r"\d", tok) and len(tok) >= 4 and "/" not in tok:
            model = tok.upper()
            break

    parts = [brand]
    if model:
        # With an explicit model code the type reads naturally right after
        # it ("OSC-P200 DDR4 8GB…"); without one the capacity leads
        # ("HyperX Fury 8GB DDR3L…").
        parts.append(model)
        parts.append(str(mem_type).upper())
        parts.append(f"{cap}GB")
    else:
        parts.append(f"{cap}GB")
        parts.append(str(mem_type).upper())
    parts.append(f"{speed}{unit}")
    if cas:
        parts.append(f"CL{cas}")
    return " ".join(parts)


def _gpu_canonical_name(group: list[dict], attributes: dict) -> str | None:
    """'ASUS GeForce GT 710 2GB EVO' from brand + chip + VRAM + edition.

    Memory type (GDDR5/SDDR3), bus width and MPN tails are deliberately
    dropped — the canonical name carries identity, the attributes carry
    the rest.
    """
    brand = attributes.get("brand") or next(
        (e.get("brand") for e in group if e.get("brand")), None
    )
    chip = attributes.get("gpu_chip") or attributes.get("chipset")
    vram = attributes.get("vram_gb")
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
    ("klevv", "Klevv"),
    ("apacer", "Apacer"),
    ("transcend", "Transcend"),
    ("timetec", "Timetec"),
    ("thermaltake", "Thermaltake"),
    ("gloway", "Gloway"),
]


def name_from_attributes(
    category: str, attributes: dict, group: list | None = None
) -> str | None:
    """
    Canonical display names built from structured data, not scrubbed titles:
    - cpu: "<brand> <model>" (+ "Dual Core" for 2-core parts, "+ series N"
      for Intel series-tagged parts).
    - memory: "<brand> [model] <type> <cap>GB <speed><unit> [CLnn]".
    - gpu: "<brand> <family> <chip> <vram>GB [edition]".
    Returns None to fall back to best_name() when the parts aren't there.
    """
    group = group or []
    if category == "cpu":
        brand = attributes.get("brand")
        model = attributes.get("model")
        if not brand or not model:
            return None
        name = f"{brand} {model}".strip()
        try:
            cores = int(attributes.get("cores")) if attributes.get("cores") is not None else None
        except (ValueError, TypeError):
            cores = None
        if cores == 2:
            name += " Dual Core"
        series = attributes.get("series")
        if series and f"series {series}" not in name.lower():
            name += f" series {series}"
        return name
    if category == "memory":
        return _memory_canonical_name(group, attributes)
    if category == "gpu":
        return _gpu_canonical_name(group, attributes)
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
        return display_title(title_value)
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

    merged: dict = {}
    conflicts: dict = {}

    for k, options in tallies.items():
        if len(options) == 1:
            merged[k] = next(iter(options.values()))[1]
        else:
            best = max(options, key=lambda n: options[n][0])
            merged[k] = options[best][1]
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
# pcpartdb reference-spec enrichment (Aug 2026, see DECISIONS.md)
#
# Attaches a small, separately-namespaced "pcpartdb" block to products in
# categories the MIT-licensed docyx/pc-part-dataset covers. Deliberately
# conservative:
#   - Stored under its own "pcpartdb" key on the product, never merged into
#     the vendor-derived "attributes" blob. Things like GPU length or CPU
#     TDP are per-exact-SKU facts; a fuzzy name match is a reference figure
#     for "a product like this", not a verified measurement of the vendor's
#     exact listing. The site is responsible for labeling it as such.
#   - Only attaches on a near-exact model-name match (see
#     PCPARTDB_MATCH_THRESHOLD) — a loose match would be worse than no data.
#   - Never raises and never required: if the index hasn't been built
#     (missing rapidfuzz, first-time checkout, a network hiccup in CI), this
#     silently no-ops and the core catalog is completely unaffected.
# --------------------------------------------------------------------------

# Our canonical category -> pcpartdb's internal category id (see
# scraper/pcpartdb.py's PCPP_TO_OURS). Categories already well covered by
# extractors.py's deterministic knowledge maps (motherboard, memory, psu,
# storage) are intentionally left out here — a fuzzy dataset match would
# only add risk, not new information, for those.
OUR_CATEGORY_TO_PCPARTDB = {
    "cpu": "cpu",
    "cooler_air": "cooler",
    "aio": "cooler",
    "gpu": "gpu",
    "case": "case",
    "case_fan": "case_fan",
    "fan_controller": "fan_controller",
    "thermal_paste": "thermal_paste",
}

# Per-category match confidence floor. GPU physical specs vary the most
# between AIB variants sharing similar names, so it gets the highest bar;
# accessory categories (fan controllers, thermal paste) are low-stakes
# informational specs, so a slightly looser bar is fine.
PCPARTDB_MATCH_THRESHOLD = {
    "gpu": 92,
    "cpu": 90,
    "case": 90,
    "cooler_air": 90,
    "aio": 90,
    "case_fan": 88,
    "fan_controller": 85,
    "thermal_paste": 85,
}

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


def normalize_pckombo_specs(specs: dict[str, str]) -> dict[str, str]:
    """Convert PC Kombo's grouped headers into our canonical filter keys."""
    normalized: dict[str, str] = {}
    for raw_key, value in specs.items():
        key = PCKOMBO_SPEC_KEYS.get(raw_key)
        if not key or not value or "Notices" in raw_key:
            continue
        if key in normalized:
            continue
        if key in {
            "cores", "threads", "cache_mb", "capacity_gb", "speed_mhz",
            "vram_gb", "wattage_w", "length_mm", "gpu_length_mm",
            "memory_clock_mhz", "rpm",
        }:
            match = re.search(r"\d+(?:\.\d+)?", value)
            if match:
                value = match.group(0)
        normalized[key] = value
    return normalized


def _pcpartdb_query(product: dict, category: str) -> str:
    """
    Build the cleanest available query text for a product.

    CPU and GPU get a purpose-built query from extractors.py's already
    clean brand/model fields (e.g. "AMD Ryzen 7 7800X3D") when available —
    far less noisy than the raw vendor title. Everything else falls back to
    the product's display name.
    """
    attrs = product.get("attributes") or {}

    if category == "cpu":
        brand = attrs.get("brand") or product.get("brand") or ""
        model = attrs.get("model") or ""
        combined = f"{brand} {model}".strip()
        if combined:
            return combined

    if category == "gpu":
        brand = product.get("brand") or ""
        chip = attrs.get("gpu_chip") or ""
        combined = f"{brand} {chip}".strip()
        if combined:
            return combined

    return str(product.get("canonical_name") or "")


def enrich_products_with_pcpartdb(products: list[dict]) -> None:
    """
    Mutates `products` in place, adding a `pcpartdb` block where a
    confident match is found. See module note above for the safety
    reasoning; this function is intentionally impossible to crash the
    pipeline with.
    """
    if _pcpartdb_find_matches is None or _pcpartdb_load_index is None:
        return

    try:
        # Touch the index once up front so a missing/unbuilt index prints
        # exactly one warning instead of one per product.
        _pcpartdb_load_index()
    except Exception as exc:
        print(f"[pcpartdb] skipping enrichment (index unavailable): {exc}", file=sys.stderr)
        return

    matched = 0

    for product in products:
        category = product.get("category")
        if not category:
            # No category means nothing to look up against — also happens
            # to be what fixes the type checker's complaint below: without
            # this guard, `category` is `str | None` and every dict lookup
            # keyed on it (OUR_CATEGORY_TO_PCPARTDB, PCPARTDB_MATCH_THRESHOLD)
            # and the call into _pcpartdb_query() are typed to require `str`.
            continue

        pcpp_category = OUR_CATEGORY_TO_PCPARTDB.get(category)
        if not pcpp_category:
            continue

        query = _pcpartdb_query(product, category)
        if not query:
            continue

        threshold = PCPARTDB_MATCH_THRESHOLD.get(category, 90)

        try:
            results = _pcpartdb_find_matches(
                query, category=pcpp_category, threshold=threshold, limit=1
            )
        except Exception as exc:
            print(f"[pcpartdb] lookup failed for {query!r}: {exc}", file=sys.stderr)
            continue

        if not results:
            continue

        score, part = results[0]
        specs = part.get("specs") or {}
        if not specs:
            continue

        product["pcpartdb"] = {
            "name": part.get("name"),
            "score": round(score, 1),
            "specs": specs,
        }
        matched += 1

    print(f"[pcpartdb] enriched {matched}/{len(products)} products with reference specs")


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
        rows = [(_pckombo_find_by_mpn(mpn), mpn) for mpn in mpns]
        rows = [(row, mpn) for row, mpn in rows if row and row.get("specs")]
        if not rows:
            continue
        row, _ = max(rows, key=lambda item: len(item[0]["specs"]))
        normalized_specs = normalize_pckombo_specs(row["specs"])
        product["attributes"].update(
            (key, value)
            for key, value in normalized_specs.items()
            if key not in product["attributes"]
        )
        product["pckombo"] = {
            "mpn": row["mpn"],
            "url": row["url"],
            "specs": normalized_specs,
        }
        matched += 1

    print(f"[pckombo] enriched {matched}/{len(products)} products with exact MPN specs")


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
    manual_key_to_pid, manual_products, _ = load_manual(manual_path)

    assignments: dict[str, str] = {}
    product_meta: dict[str, dict] = {}

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
    # identifies the part (CPU: a model number *is* the CPU — packaging is
    # cosmetic), merge on (category, brand, model) BEFORE the MPN/SKU tiers so
    # a cross-vendor model match wins over each vendor's own SKU/MPN product.
    #
    # Guarded two ways so we never silently merge the wrong thing:
    #   - Only categories/keys we explicitly trust (see MODEL_MERGE_CATEGORIES).
    #   - Listings that disagree on a critical attribute (DDR generation,
    #     capacity, speed, wattage, etc.) are kept apart.
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

        # Critical-attribute guard: if any two listings in the prospective
        # merge disagree on a spec that changes the part (e.g. a CPU sold as
        # both 65W and 125W TDP), it's not the same part — drop the whole
        # group and let each remain separate.
        if any(
            critical_conflict(a, b)
            for i, a in enumerate(group)
            for b in group[i + 1 :]
        ):
            continue

        category = ident[0]
        slug_part = re.sub(r"[^a-z0-9]+", "-", ident[2]).strip("-")
        pid = f"model:{category}:{slug_part}"

        for enriched in group:
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
            pid = f"mpn:{category}:{mpn.lower()}"
            mpn_groups.setdefault(pid, []).append(enriched)

    for pid, group in mpn_groups.items():
        for enriched in group:
            assignments[enriched["listing_key"]] = pid

        product_meta.setdefault(
            pid,
            {
                "product_id": pid,
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
            and not sku_norm.isdigit()
            and category not in ("other", "", None)
        ):
            pid = f"sku:{category}:{sku_norm.lower()}"
            sku_groups.setdefault(pid, []).append(enriched)

    for pid, group in sku_groups.items():
        for enriched in group:
            assignments[enriched["listing_key"]] = pid

        product_meta.setdefault(
            pid,
            {
                "product_id": pid,
                "matched_by": "sku",
            },
        )

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

    # Build product objects.
    products = []
    product_sizes: dict[str, int] = {}

    for pid, meta in product_meta.items():
        group = [e for e in enriched_listings if assignments[e["listing_key"]] == pid]
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

        merged_attributes, attribute_conflicts = merge_offer_attributes(group)

        mpns = {e.get("mpn") for e in group if e.get("mpn")}
        if len(mpns) == 1:
            merged_attributes["mpn"] = next(iter(mpns))

        # Surface the real manufacturer part number as the product model so
        # the site shows "AK-H81MEL-VS" instead of a vendor-internal id
        # ("126902") or a product-id slug. Attributes' own model (parsed
        # from titles, e.g. "Ryzen 3 4100") wins when present.
        model = meta.get("model") or merged_attributes.get("model")
        if not model and len(mpns) == 1:
            model = next(iter(mpns))

        if any(e.get("bundle_only") for e in group):
            merged_attributes["bundle_only"] = True

        attributes = {
            **merged_attributes,
            **meta.get("attributes", {}),
        }
        normalize_cpu_legacy_attrs(attributes)

        product = {
            "product_id": meta.get("product_id", pid),
            "canonical_name": (
                meta.get("canonical_name")
                or name_from_attributes(category, merged_attributes, group)
                or best_name(group)
            ),
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

        # Propagate cover image URL from any offer that has one.
        # Only one image per product is needed — take the first
        # available (detail-scraped images are the most reliable).
        img_url = next(
            (e.get("image_url") for e in group if e.get("image_url")),
            None,
        )
        if img_url:
            product["image_url"] = img_url

        if attribute_conflicts:
            product["attribute_conflicts"] = attribute_conflicts

        product["best_offer"] = choose_best_offer(offers)
        products.append(product)

    enrich_products_with_pcpartdb(products)
    enrich_products_with_pckombo(products)

    products.sort(key=lambda p: p.get("product_id", ""))

    return {
        "products": products,
        "assignments": assignments,
        "product_sizes": product_sizes,
    }


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

    out = {
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