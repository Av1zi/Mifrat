"""
specs/resolvers/reference.py — Tier 0: reference data + manual overrides.

Two authoritative sources:

1. The MIT-licensed docyx/pc-part-dataset (PCPartPicker specs) indexed by
   scraper/pcpartdb.py into data/pcpartdb/index.json. It is authoritative but
   SPARSE: it carries 5-8 spec fields per category (core_count/boost_clock for
   CPUs, socket/form_factor/max_memory for boards, ...) and, notably, NO part
   numbers. Tier 0 therefore wins every field it has, and every other field
   still comes from tiers 1-3.
2. `data/specs/overrides.json` — human-edited corrections keyed by product id
   and field. Highest priority of all (TIER_OVERRIDE): the escape hatch for a
   wrong value spotted in production without a code deploy.

Identity (plan §5) — specs are only as good as the product->row link:
1. exact normalized-name equality (zero ambiguity);
2. fuzzy name match at a per-category threshold PLUS a hard anchor check: at
   least one structured field parsed from OUR OWN data must equal the
   candidate's, and the candidate must not contradict any other anchored field
   we know. No anchor agreement -> no match. This is what makes it safe to
   treat reference values as authoritative.
3. ties / ambiguity -> no Tier-0 match (wrong specs are worse than null specs).

Degradation: a missing or schema-stale index logs one warning and disables
Tier 0; the pipeline continues on tiers 1-3 and the coverage report shows it.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .. import schema
from ..merge import TIER_OVERRIDE, TIER_REFERENCE, Fact, add_fact
from ..values import InvalidValue, coerce

SOURCE_REFERENCE = "reference:pcpartdb"
SOURCE_OVERRIDE = "override:file"

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OVERRIDES_PATH = ROOT / "data" / "specs" / "overrides.json"

# Fuzzy threshold per category (matches today's tuned values in matching.py).
THRESHOLD = {
    "cpu": 90.0, "motherboard": 90.0, "memory": 88.0, "storage": 88.0,
    "gpu": 88.0, "case": 88.0, "psu": 88.0, "case_fan": 90.0,
    "aio": 90.0, "cooler_air": 90.0,
}

# Fields that must agree between our own parsed data and the reference row
# before a fuzzy match is trusted. These are the fields that identify a
# product's variant (8GB vs 16GB, 6000 vs 5600, 750W vs 850W).
ANCHOR_FIELDS: dict[str, tuple[str, ...]] = {
    "cpu": ("socket", "core_count", "boost_clock_ghz"),
    "motherboard": ("socket", "form_factor", "memory_slots"),
    "memory": ("total_gb", "speed_mhz", "memory_type"),
    "storage": ("capacity_gb", "type", "form_factor"),
    "gpu": ("chipset", "memory_gb"),
    "psu": ("wattage_w",),
    "case": ("type",),
    "case_fan": ("size_mm",),
    "aio": ("radiator_size_mm",),
    "cooler_air": ("fan_size_mm", "height_mm"),
}

# Tolerance for the fuzzy match to be considered "tied" (ambiguity guard).
_TIE_MARGIN = 2.0

# Our category id -> the `cat` value pcpartdb.py's index stores. The index
# re-keys PCPartPicker slugs to OUR ids (cpu-cooler -> "cooler"), but our
# pipeline splits coolers into three categories (aio/cooler_air/
# cooling_other) — all three must look up the single "cooler" pool.
# (Sep 2026 bug: the lookup passed the PCPP *slug* — "video-card",
# "power-supply", ... — to find_matches(), which compares against the
# index's OUR-id `cat`. Every category whose slug differs from our id got
# zero candidates, so Tier 0 silently covered only cpu/motherboard/memory/
# case. The slugs are still used for nothing now; the index speaks our ids.)
INDEX_CAT: dict[str, str] = {
    "aio": "cooler",
    "cooler_air": "cooler",
    "cooling_other": "cooler",
}

# --------------------------------------------------------------------------
# Identity-scoped join (Sep 2026): many unmatched products DO exist in the
# index, but the index names boards by board-model ("MSI VENTUS 3X OC") with
# the chip only in specs.chipset, so name-similarity never sees the chip.
# For those, slice the index pool by exact identity-field equality (chip,
# wattage, capacity, socket, module shape), strip the identity tokens from
# the query, and fuzzy-match the residual board-model words — with a brand
# gate, an anchor re-check and the usual tie refusal. Plan §5: multiple
# independent anchors before a fuzzy join; ambiguity is refused, not guessed.
# --------------------------------------------------------------------------

# Exact-equality slice keys per category (all must be present on both sides).
# These are the variant-determining fields: two rows with the same identity
# but different board models are genuine model candidates, not variants.
IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "gpu": ("chipset", "memory_gb"),
    "memory": ("memory_type", "module_count", "module_size_gb"),
    "psu": ("wattage_w",),
    "storage": ("capacity_gb",),
    "motherboard": ("socket",),
    "cpu": ("socket",),
}

# Query tokens contributed by identity/physical facts rather than the board
# model: stripped before residual scoring so a 12GB chip's VRAM or a kit's
# 2x16GB does not water down the model-name match.
_RESIDUAL_STRIP_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:tb|gb|mb|w)\b"
    r"|\b\d+\s?x\s?\d+\s?gb\b|\bcl\s?\d+\b|\b\d{4,5}\s?(?:mhz|mt/s)\b"
    r"|\b80\s?\+\s?(?:plus\s*)?(?:white|bronze|silver|gold|platinum|titanium)\b"
    r"|\bddr[345]\b|\bnvme\b|\bm\.?2\b|\bsata\b|\bssd\b|\bhdd\b|\bdrive\b"
    r"|\bgeforce\b|\brtx\b|\bgtx\b|\bradeon\b|\barc\b|\brx\b|\br\d{1,2}\b"
    r"|\bti\b|\bxtx?\b|\bsuper\b|\bintel\b|\bamd\b|\bcore\b|\bryzen\b",
    re.I,
)

# Brands the brand gate must treat as the same company (sub-brands and
# merged/resold lines). Keys are already-normalized tokens.
_BRAND_ALIASES = {
    "seasonic": "seasonic",
    "wd": "western digital", "western": "western digital",
    "westerndigital": "western digital", "western digital": "western digital",
    "g": "g skill", "gskill": "g skill", "g skill": "g skill",
    "kingston": "kingston", "fury": "kingston",
    "crucial": "crucial", "micron": "crucial",
    "hp": "hp", "hpe": "hp", "hewlett": "hp",
    "coolermaster": "cooler master", "master": "cooler master",
    "cooler": "cooler master",
}


def index_cat(category: str | None) -> str | None:
    """Index `cat` pool for one of our category ids (None when unknown)."""
    if not category:
        return None
    if category in INDEX_CAT:
        return INDEX_CAT[category]
    return category


def _norm_text(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _identity_key(category: str, specs: dict):
    """Tuple of identity-field values (None when any member is unknown)."""
    fields = IDENTITY_FIELDS.get(category)
    if not fields:
        return None
    values = []
    for name in fields:
        value = specs.get(name)
        if value is None:
            return None
        values.append(_norm_text(value) if isinstance(value, str) else value)
    return tuple(values)


def _identity_slice(category: str, key) -> list[dict]:
    """Index rows whose identity fields equal `key` (built once)."""
    module, index = _load_reference()
    if module is None or index is None:
        return []
    cache_key = (category, json.dumps(key, sort_keys=True, default=str))
    cached = _IDENTITY_SLICE_CACHE.get(cache_key)
    if cached is None:
        want = index_cat(category)
        fields = IDENTITY_FIELDS.get(category, ())
        rows: list[dict] = []
        for part in index["parts"]:
            if part.get("cat") != want:
                continue
            row_key = _identity_key(category, part.get("specs") or {})
            if row_key == key:
                rows.append(part)
        _IDENTITY_SLICE_CACHE[cache_key] = rows
        cached = rows
    return cached


_IDENTITY_SLICE_CACHE: dict[tuple, list[dict]] = {}


def _residual_query(category: str, query: str, specs: dict) -> str:
    """Query with identity tokens removed, leaving board-model words.

    'MSI GeForce RTX 5070 Ti 16GB VENTUS 3X OC' -> 'msi ventus 3x oc'
    (chipset tokens are removed individually so 'RTX 5070 Ti' disappears as
    a unit; VRAM/capacity/wattage and category keywords go too).
    """
    text = _norm_text(query)
    chipset = specs.get("chipset")
    if category == "gpu" and chipset:
        for token in _norm_text(chipset).split():
            if token:
                text = re.sub(rf"\b{re.escape(token)}\b", " ", text)
    text = _RESIDUAL_STRIP_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# Words that carry no board-model identity (marketing/physical/protocol
# boilerplate a reseller title adds). A token outside this set and outside
# the brand slots is a *distinctive model token* the winning row must
# contain — this is what keeps 'Patriot VP4300 Lite' away from
# 'Patriot P400 Lite' while letting 'MSI MPG Carbon WiFi' reach
# 'MSI MPG Z890 CARBON WIFI'.
_GENERIC_TOKENS = frozenset({
    "pro", "max", "plus", "wifi", "gaming", "oc", "rgb", "argb",
    "black", "white", "ultra", "edition", "atx", "matx", "itx", "mini",
    "micro", "power", "unit", "psu", "drives", "drive", "series", "system",
    "tower", "gen", "express", "usb", "type", "lan", "card", "graphics",
    "internal", "original", "official", "warranty", "importer", "new",
    "core", "color", "e", "s", "a", "b", "c", "g", "m", "x", "v2", "v3",
})


def _distinctive_tokens(text: str) -> set[str]:
    """Non-brand, non-generic tokens a matching row name must contain."""
    tokens = [t for t in _norm_text(text).split() if len(t) >= 2]
    if not tokens:
        return set()
    return {t for t in tokens[1:]  # tokens[0] is the brand slot
            if t not in _GENERIC_TOKENS and t not in _BRAND_ALIASES}


def _brand_tokens(text: str) -> set[str]:
    """First-word brand candidates from a normalized string."""
    words = text.split()
    if not words:
        return set()
    first = words[0]
    return {first, _BRAND_ALIASES.get(first, first)}


def _brand_agrees(query: str, row: dict) -> bool:
    """Brand gate: residual tokens must not name a brand the row contradicts.

    Prevents the model-token false positive where an Antec 'G650' matched a
    Rosewill 'G650' and a Lenovo kit matched a Corsair one: a reseller title
    always carries the maker, and the index names carry it too. A row whose
    first word is not a brand word at all ('Ultra', 'PULSE') passes — the
    gate only rejects, never invents agreement.
    """
    q_brands = _brand_tokens(query)
    r_brands = _brand_tokens(_norm_text(row.get("name") or ""))
    if not q_brands or not r_brands:
        return True
    if q_brands & r_brands:
        return True
    # 'asus'/'gigabyte'/'msi' titles never name a row of another known brand.
    known = {"asus", "msi", "gigabyte", "asrock", "sapphire", "powercolor",
             "xfx", "zotac", "pny", "gainward", "palit", "corsair",
             "kingston", "g skill", "crucial", "adata", "patriot", "lexar",
             "samsung", "wd", "seagate", "seasonic", "antec", "be quiet",
             "coolermaster", "cooler", "master", "thermaltake", "lian li",
             "nzxt", "fractal", "deepcool", "noctua", "arctic", "fsp",
             "superflower", "evga", "leadtek", "sparkle", "intel", "amd"}
    return not (q_brands & known) and not (r_brands & known)


def _identity_join(category: str, query: str, specs: dict, anchors):
    """The Sep 2026 identity-scoped join; same contract as the fuzzy path."""
    module, _ = _load_reference()
    if module is None:
        return None
    key = _identity_key(category, specs)
    if key is None:
        return None
    rows = _identity_slice(category, key)
    if not rows:
        return None
    residual = _residual_query(category, query, specs)
    if not residual:
        return None

    distinctive = _distinctive_tokens(residual)
    if not distinctive:
        # A brand-only residual ('Sapphire Radeon RX 9060 XT' after chip
        # stripping) cannot identify a board model: every same-brand row in
        # the slice scores alike. Refuse rather than pick one.
        return None

    scored: list[tuple[float, dict]] = []
    for row in rows:
        if not _brand_agrees(residual, row):
            continue
        name = _norm_text(row.get("name") or "")
        if not distinctive <= set(name.split()):
            continue
        score = module._score(_norm_text(residual), row)
        if score < 88.0:
            continue
        agrees, contradicts = _anchor_check(category, anchors, row)
        if contradicts or not agrees:
            continue
        scored.append((float(score), row))
    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], item[1].get("name") or ""))
    best_score, best_row = scored[0]
    if len(scored) > 1 and abs(best_score - scored[1][0]) <= _TIE_MARGIN:
        tied = [row for score, row in scored
                if abs(score - best_score) <= _TIE_MARGIN]
        names = {_norm_text(row.get("name")) for row in tied}
        if len(names) > 1:
            # Genuinely different board models score alike -> refuse.
            return None
        shared = _intersect_rows(tied)
        if shared.get("specs"):
            return shared, best_score, "identity+anchor"
        return None
    return best_row, best_score, "identity+anchor"

_OVERRIDES_CACHE: dict | None = None
_INDEX_WARNED = False


def load_overrides() -> dict:
    """product_id -> {field: value}; missing/empty file is fine."""
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is None:
        try:
            data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
            _OVERRIDES_CACHE = data.get("products", data) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _OVERRIDES_CACHE = {}
    return _OVERRIDES_CACHE


def overrides_for(product: dict) -> dict[str, list[Fact]]:
    """Manual override facts for one product (highest tier)."""
    category = product.get("category")
    entry = load_overrides().get(str(product.get("product_id") or ""))
    if not isinstance(entry, dict):
        return {}
    facts: dict[str, list[Fact]] = {}
    for key, value in entry.items():
        field = schema.field_for_key(category, key) or schema.field_map(category).get(key)
        if field is None or value is None:
            continue
        try:
            typed = coerce(field, value, category)
        except InvalidValue:
            continue
        add_fact(facts, field.name, Fact(value=typed, tier=TIER_OVERRIDE,
                                        source=SOURCE_OVERRIDE, confidence=1.0))
    return facts


# --------------------------------------------------------------------------
# Reference index access
# --------------------------------------------------------------------------


def _reference_module():
    """scraper.pcpartdb, imported lazily (it is optional enrichment)."""
    try:
        from scraper import pcpartdb
    except ImportError:  # pragma: no cover - direct-module execution
        import pcpartdb  # type: ignore

    return pcpartdb


def _load_reference():
    """(module, index) or (None, None) when Tier 0 is unavailable."""
    global _INDEX_WARNED
    module = _reference_module()
    try:
        index = module.load_index()
    except Exception as exc:  # pragma: no cover - defensive
        if not _INDEX_WARNED:
            print(f"[specs] reference index unavailable, Tier 0 disabled: {exc}")
            _INDEX_WARNED = True
        return None, None
    if not index.get("parts"):
        if not _INDEX_WARNED:
            print("[specs] reference index is empty, Tier 0 disabled "
                  "(run: python -m scraper.pcpartdb refresh)")
            _INDEX_WARNED = True
        return None, None
    return module, index


_NAME_INDEX_CACHE: dict[str, dict[str, list[dict]]] = defaultdict(dict)


def _name_index(category: str, parts: list[dict]):
    """Normalized-name -> rows, built once per run per category."""
    cached = _NAME_INDEX_CACHE.get(category)
    if cached is not None:
        return cached
    cached = {}
    module = _reference_module()
    want = index_cat(category)
    for part in parts:
        if part.get("cat") != want:
            continue
        key = module._norm_name(part.get("name"))
        if key:
            cached.setdefault(key, []).append(part)
    _NAME_INDEX_CACHE[category] = cached
    return cached


def _anchors(category: str, known: dict) -> list[tuple[str, object]]:
    """Anchor (field, value) pairs we already know about this product."""
    return [(field, known[field]) for field in ANCHOR_FIELDS.get(category, ())
            if known.get(field) is not None]


def _agree(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return str(a).strip().lower() == str(b).strip().lower()


def _anchor_agree(field: str, ours, theirs) -> bool:
    """Anchor equality with two known representation gaps factored out.

    - GPU chipset: the dataset bakes VRAM into the name ("GeForce RTX 3060
      12GB") while our title parse strips it ("GeForce RTX 3060"). Compare
      the base name.
    - Storage form factor: we keep the length ("M.2-2280"), the dataset
      keeps the family ("M.2"). A family match agrees; anything else must
      be exact.
    """
    if _agree(ours, theirs):
        return True
    low_ours, low_theirs = str(ours).strip().lower(), str(theirs).strip().lower()
    if field == "chipset":
        import re as _re

        base = lambda s: _re.sub(r"\s*\d+\s?gb\s*$", "", s).strip()
        return base(low_ours) == base(low_theirs) and bool(base(low_ours))
    if field == "form_factor":
        family = lambda s: str(s).split("-")[0].strip().lower()
        return family(low_ours) == family(low_theirs) and len(family(low_ours)) >= 3
    return False


def _anchor_check(category: str, anchors: list[tuple[str, object]], row: dict):
    """(agrees, contradicts) for one candidate row."""
    specs = row.get("specs") or {}
    agrees = 0
    for field, value in anchors:
        other = specs.get(field)
        if other is None:
            continue
        if _anchor_agree(field, value, other):
            agrees += 1
        else:
            return agrees, True
    return agrees, False


def _intersect_rows(rows: list[dict]) -> dict:
    """One synthetic row keeping only the specs EVERY row agrees on.

    The dataset lists colour/CAS variants of one product under the same name.
    Matching such a name is safe, but only the agreed fields may be used —
    a value that differs across rows is exactly the ambiguity the plan says to
    refuse rather than guess.
    """
    if not rows:
        return {}
    shared: dict = {}
    for key, value in (rows[0].get("specs") or {}).items():
        if all(_agree(value, (row.get("specs") or {}).get(key)) for row in rows[1:]
               if (row.get("specs") or {}).get(key) is not None):
            shared[key] = value
    return {"name": rows[0].get("name"), "cat": rows[0].get("cat"),
            "specs": shared, "variants": len(rows)}


def match_reference_row(category: str | None, query: str, known: dict):
    """Return (row, score, method) for a confident Tier-0 match, else None.

    `known` is the merged non-reference spec sheet for the product; it supplies
    the anchors. Method is "exact-name" or "fuzzy+anchor" (provenance for the
    coverage report).
    """
    if not category or not query:
        return None
    want = index_cat(category)
    if not want:
        return None
    module, index = _load_reference()
    if module is None or index is None:
        return None

    anchors = _anchors(category, known)

    # 1) exact normalized-name equality (zero ambiguity about the product)
    name_index = _name_index(category, index["parts"])
    exact = name_index.get(module._norm_name(query))
    if exact:
        if len(exact) == 1:
            return exact[0], 100.0, "exact-name"
        viable = [row for row in exact
                  if not _anchor_check(category, anchors, row)[1]]
        agreeing = [row for row in viable
                    if _anchor_check(category, anchors, row)[0]]
        if len(agreeing) == 1:
            return agreeing[0], 100.0, "exact-name"
        if len(agreeing) > 1:
            shared = _intersect_rows(agreeing)
            if shared.get("specs"):
                return shared, 100.0, "exact-name"
        return None

    if not anchors:
        # No structured identity of our own -> fuzzy-only matching may not
        # pick a reference row (plan §5: no anchor, no match).
        return None

    # 2) identity-scoped join: chip/wattage/capacity/socket slice + residual
    #    board-model fuzzy. Catches products whose index row is named by the
    #    board model while our query names the chip ("GeForce RTX 5070 Ti").
    joined = _identity_join(category, query, known, anchors)
    if joined is not None:
        return joined

    threshold = THRESHOLD.get(category, 90.0)
    candidates = module.find_matches(query, category=want,
                                     threshold=threshold, limit=4)
    viable: list[tuple[float, dict]] = []
    for score, row in candidates:
        agrees, contradicts = _anchor_check(category, anchors, row)
        if contradicts or not agrees:
            continue
        viable.append((float(score), row))
    if not viable:
        return None

    viable.sort(key=lambda item: (-item[0], item[1].get("name") or ""))
    best_score, best_row = viable[0]
    if len(viable) > 1 and abs(best_score - viable[1][0]) <= _TIE_MARGIN:
        # Two equally good rows for DIFFERENT products: refuse rather than
        # guess. Same-name variant rows (color/CAS twins of one product) are
        # safe: only the fields they agree on are used.
        tied = [row for score, row in viable
                if abs(score - best_score) <= _TIE_MARGIN]
        names = {module._norm_name(row.get("name")) for row in tied}
        if len(names) == 1:
            shared = _intersect_rows(tied)
            if shared.get("specs"):
                return shared, best_score, "fuzzy+anchor"
        return None
    return best_row, best_score, "fuzzy+anchor"


def reference_facts(category: str | None, row: dict,
                    confidence: float = 1.0) -> dict[str, list[Fact]]:
    """Coerce a reference row's specs into Tier-0 facts."""
    facts: dict[str, list[Fact]] = {}
    for key, value in (row.get("specs") or {}).items():
        field = schema.field_map(category).get(key) or schema.field_for_key(category, key)
        if field is None or value is None:
            continue
        try:
            typed = coerce(field, value, category)
        except InvalidValue:
            continue
        add_fact(facts, field.name, Fact(value=typed, tier=TIER_REFERENCE,
                                         source=SOURCE_REFERENCE,
                                         confidence=confidence))
    return facts
