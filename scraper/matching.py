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
    "ivory": "Ivory",

    # Memory
    "kingston": "Kingston",
    "fury": "Kingston Fury",
    "patriot": "Patriot",
    "viper": "Patriot Viper",

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

    Handles:
    - int
    - float
    - string numbers
    - 1PC floating-point noise
    - Plonter string prices
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


def _category_from_title(title_clean: str) -> str | None:
    """
    Strong title-based hints for sub-classifying messy cooling/accessory listings.
    """
    if not title_clean:
        return None

    if "thermal paste" in title_clean or "thermal grease" in title_clean:
        return "thermal_paste"

    if "mounting kit" in title_clean and "cooler not included" in title_clean:
        return "cooler_accessory"

    if "fan controller" in title_clean or "fan hub" in title_clean:
        return "fan_controller"

    if "splitter" in title_clean and (
        "fan" in title_clean or "rgb" in title_clean or "argb" in title_clean
    ):
        return "fan_controller"

    if (
        "light strip" in title_clean
        or "light strips" in title_clean
        or "rgb led" in title_clean
    ):
        return "rgb_lighting"

    if "starter kit" in title_clean and "fan" in title_clean:
        return "case_fan"

    if "expansion kit" in title_clean and "fan" in title_clean:
        return "case_fan"

    if re.search(r"\b\d{2,3}\s*mm\b", title_clean) and re.search(r"\bfans?\b", title_clean):
        return "case_fan"

    if "liquid cooling" in title_clean or "aio" in title_clean:
        return "aio"

    if "cpu cooler" in title_clean or "air cooler" in title_clean:
        return "cooler_air"

    return None


def canonical_category(guess: str | None, title: str = "") -> str:
    """
    Map vendor category guesses into canonical categories.
    """
    # TMS uses things like case:bundle-only / motherboard:bundle-only.
    raw_key = _compact_key(guess).replace("bundleonly", "")
    title_clean = _clean(title).lower()
    title_cat = _category_from_title(title_clean)

    if raw_key in CATEGORY_ALIASES:
        category = CATEGORY_ALIASES[raw_key]
    elif raw_key.startswith("case") and "fan" not in raw_key:
        category = "case"
    else:
        category = "other"

    # Plonter sometimes puts accessory items under COMPUTER CASES.
    if category == "case" and title_cat in ACCESSORY_CATEGORIES:
        return title_cat

    # Plonter's "Fans and Cooling solutions" is ambiguous.
    if category == "cooling":
        return title_cat or "cooling_other"

    return category


def listing_key(listing: dict) -> str:
    """
    Build a stable unique key for a vendor listing.

    Special handling:
    - 1PC product URLs contain stable numeric product IDs.
    - Ivory can repeat vendor_sku across multiple catalog IDs, so prefer URL id.
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

    This decodes URL-encoded Hebrew SKUs and removes non-alphanumerics.
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
    mpn = found[0]
    return re.sub(r"[^A-Z0-9]", "", mpn)


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

    # Phase 2B: structured compatibility attributes (socket, chipset,
    # memory type, form factor, wattage...), parsed from match_text only -
    # see extractors.py docstring for why this doesn't touch vendor payloads.
    enriched["attributes"] = extract_attributes(enriched)

    return enriched


def dedupe_enriched_listings(enriched_listings: list[dict]) -> list[dict]:
    """
    Deduplicate listings with the same listing_key.

    If the same listing_key appears multiple times, keep the best offer:
    - lowest known price
    - in stock preferred
    - non-stale preferred
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


def load_manual(path: Path | str | None) -> tuple[dict[str, str], dict[str, dict], set[frozenset[str]]]:
    """
    Load manual product merges.

    Expected file format:

    {
      "products": [
        {
          "product_id": "case:antec:st20m",
          "canonical_name": "Antec ST20M",
          "category": "case",
          "brand": "Antec",
          "model": "ST20M",
          "attributes": {},
          "listing_keys": [
            "1pc:216305",
            "tms:ST20M"
          ]
        }
      ],
      "blocked_pairs": [
        ["listing_key_a", "listing_key_b"]
      ]
    }
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
        "bundle_only": enriched.get("bundle_only", False),
        "attributes": enriched.get("attributes", {}),
    }


def best_name(enriched_listings: list[dict]) -> str:
    """
    Choose a display name.

    Manual overrides should provide canonical_name for important merged products.
    """
    if not enriched_listings:
        return "unknown"

    vendor_preference = {
        "tms": 0,
        "1pc": 1,
        "ivory": 2,
        "plonter": 3,
    }

    def sort_key(e: dict):
        vendor_rank = vendor_preference.get(canonical_vendor_id(e.get("vendor_id")), 9)
        has_brand_penalty = 0 if e.get("brand") else 1
        text_len = len(e.get("match_text", ""))
        too_long_penalty = 1 if text_len > 150 else 0
        return (has_brand_penalty, too_long_penalty, vendor_rank, -text_len)

    chosen = sorted(enriched_listings, key=sort_key)[0]

    match_text = chosen.get("match_text")
    if isinstance(match_text, str) and match_text.strip():
        return match_text.strip()

    listing_key = chosen.get("listing_key")
    if isinstance(listing_key, str) and listing_key.strip():
        return listing_key.strip()

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


def merge_offer_attributes(group: list[dict]) -> tuple[dict, dict]:
    """
    Union attributes across a product's offers.

    If offers disagree on a field, keep the majority value and record the
    disagreement in `conflicts` - a conflict is also a signal the merge
    itself might be wrong (e.g. two different chipsets grouped as one
    product), worth spot-checking, not just data noise to average away.
    """
    tallies: dict[str, dict[str, list]] = {}

    for e in group:
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

    # 2. Exact MPN matches.
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

    # 3. Exact normalized vendor SKU matches.
    #
    # This helps when multiple vendors use the same model code, e.g.
    # Lian Li O11DMIV2W.
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

    # 4. Singletons.
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

        # Phase 2B: union offer-level attributes into the product, with
        # majority-vote conflict detection (see merge_offer_attributes).
        merged_attributes, attribute_conflicts = merge_offer_attributes(group)

        mpns = {e.get("mpn") for e in group if e.get("mpn")}
        if len(mpns) == 1:
            merged_attributes["mpn"] = next(iter(mpns))

        if any(e.get("bundle_only") for e in group):
            merged_attributes["bundle_only"] = True

        attributes = {
            **merged_attributes,
            **meta.get("attributes", {}),
        }

        product = {
            "product_id": meta.get("product_id", pid),
            "canonical_name": meta.get("canonical_name") or best_name(group),
            "category": category,
            "brand": meta.get("brand") or next(
                (e.get("brand") for e in group if e.get("brand")),
                None,
            ),
            "model": meta.get("model"),
            "attributes": attributes,
            "matched_by": meta.get("matched_by", "auto"),
            "vendor_count": len({o.get("vendor_id") for o in offers if o.get("vendor_id")}),
            "offers": offers,
        }

        if attribute_conflicts:
            product["attribute_conflicts"] = attribute_conflicts

        product["best_offer"] = choose_best_offer(offers)
        products.append(product)

    products.sort(key=lambda p: p.get("product_id", ""))

    return {
        "products": products,
        "assignments": assignments,
        "product_sizes": product_sizes,
    }


def extract_critical_attributes(text: str) -> dict:
    """
    Very rough critical attribute extraction.

    This is only used to prevent obvious bad fuzzy merges.
    Phase 2B should replace this with proper per-category extractors.
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

    # Different DDR generation is almost always a bad match.
    if ca["ddr"] and cb["ddr"] and ca["ddr"] != cb["ddr"]:
        return True

    # Different RAM total capacity is bad for memory products.
    if ca["total_gb"] and cb["total_gb"] and ca["total_gb"] != cb["total_gb"]:
        return True

    # Different RAM speed is bad for memory products.
    if ca["speed_mhz"] and cb["speed_mhz"] and ca["speed_mhz"] != cb["speed_mhz"]:
        return True

    # Different PSU wattage is bad.
    if ca["wattage"] and cb["wattage"] and ca["wattage"] != cb["wattage"]:
        return True

    # Different fan pack size is usually important.
    if ca["pack_size"] and cb["pack_size"] and ca["pack_size"] != cb["pack_size"]:
        return True

    # Different hardware revisions, e.g. V2 vs V3.
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

                if assignments and assignments.get(a_key) and assignments.get(a_key) == assignments.get(b_key):
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