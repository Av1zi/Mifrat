"""
specs/resolvers/vendor_struct.py — Tier 1: structured vendor payloads.

Sources handled here:
- `vendor_meta` scalar fields (TMS/Ivory builder payloads);
- `detail_specs` rows from the detail-enrichment spiders (Ivory/1PC/Plonter
  spec tables) — keys go through schema.field_for_key(), which owns the
  vendor spelling aliases, so the old 70-entry key table is gone;
- Ivory's opaque builder `cuts` ids, decoded from the committed ground-truth
  table data/ivory_cut_labels.json (never inferred at runtime);
- the post-match bridge: `specs.ingest_computed_attributes()` promotes keys
  matching.py computes from the listing (brand, model, mpn, accessory_type)
  into Tier-1 facts so they are part of the spec sheet instead of a parallel
  blob. This is the ONLY place matching feeds the spec system.

Guards kept from the old code (they prevented real, visible bugs):
- Hebrew / mojibake keys or values are dropped (validate.py enforces this a
  second time) — Plonter's poisoned nav tables and Ivory promo paragraphs;
- Ivory promo/marketing labels ("לחץ/י לרכישה...") are never a spec;
- opaque parent ids / category ids are never exposed as specs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import schema
from ..merge import TIER_VENDOR, Fact, add_fact
from ..values import InvalidValue, coerce

SOURCE_DETAIL = "vendor:detail"
SOURCE_META = "vendor:meta"
SOURCE_CUTS = "ivory:cut-label"
SOURCE_COMPUTED = "matching:computed"

# Detail rows nobody filters on / that merely echo the title.
DETAIL_KEY_BLACKLIST = frozenset({
    "name", "sku", "segment", "scalability", "remote_management",
    "remote_manageability", "not_available", "warranty", "upc",
})

HEBREW_LABELS = {
    "\u05de\u05d5\u05ea\u05d2": "brand",       # מותג
    "\u05d3\u05d2\u05dd": "model",             # דגם
    "\u05d0\u05e8\u05d9\u05d6\u05d4": "packaging",  # אריזה
}

# English parenthetical hints Ivory appends to Hebrew labels ("ליבות (cores)").
HINT_ALIASES = {
    "cores": "core_count",
    "threads": "thread_count",
    "clock": "__clock_range__",
    "cache": "cache_mb",
    "socket": "socket",
    "brand": "manufacturer",
    "model": "model",
    "packing": "packaging",
    "packaging": "packaging",
    "chipset": "chipset",
    "memory": "memory_gb",
    "speed": "speed_mhz",
}

_PAREN_HINT_RE = re.compile(r"\(([^)]+)\)")
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_MOJIBAKE_RE = re.compile(r"[\ufffd\u05f3]")
_PROMO_RE = re.compile(r"\u05dc\u05d7\u05e5/\u05d9|\u05dc\u05e8\u05db\u05d9\u05e9\u05d4|"
                       r"\u05de\u05d5\u05de\u05dc\u05e5|\u05dc\u05e7\u05e8\u05e8")
_CLOCK_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*ghz\s*-\s*(\d+(?:\.\d+)?)\s*ghz?", re.I)

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CUT_LABELS_PATH = _ROOT / "data" / "ivory_cut_labels.json"

_LABELS_CACHE: dict | None = None


def is_junk_text(value) -> bool:
    """Hebrew prose, mojibake or Ivory promo copy — never a spec value."""
    if not isinstance(value, str):
        return False
    if _HEBREW_RE.search(value) or _MOJIBAKE_RE.search(value):
        return True
    return bool(_PROMO_RE.search(value))


def is_promo_label(value) -> bool:
    """Ivory occasionally uses a whole marketing paragraph as a filter label."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return len(stripped) > 40 or bool(_PROMO_RE.search(stripped))


def _emit(facts: dict, category: str, name: str, value, source: str,
          confidence: float = 0.9) -> None:
    field = schema.field_map(category).get(name)
    if field is None or value is None:
        return
    try:
        typed = coerce(field, value, category)
    except InvalidValue:
        return
    add_fact(facts, name, Fact(value=typed, tier=TIER_VENDOR, source=source,
                               confidence=confidence))


def _emit_by_key(facts: dict, category: str, key: str, value, source: str,
                 confidence: float = 0.9) -> None:
    """Emit one vendor (key, value) row through the schema alias map."""
    if key is None or value is None:
        return
    normalized = schema.normalize_key(key)
    if not normalized or normalized in DETAIL_KEY_BLACKLIST:
        return
    if is_junk_text(str(value)):
        return
    field = schema.field_for_key(category, key)
    if field is None:
        return
    _emit(facts, category, field.name, value, source, confidence)


def translate_ivory_label(label) -> str | None:
    """Hebrew label (+ optional English parenthetical) -> schema-ish key."""
    raw = str(label or "").strip()
    if not raw:
        return None
    for hebrew, mapped in HEBREW_LABELS.items():
        if hebrew in raw:
            return mapped
    hint = _PAREN_HINT_RE.search(raw)
    if hint:
        token = re.sub(r"[^a-z]", "", hint.group(1).lower())
        return HINT_ALIASES.get(token)
    if _HEBREW_RE.search(raw):
        return None
    return raw


# --------------------------------------------------------------------------
# Detail-spec rows (data/raw/detail/<vendor>.jsonl -> vendor_meta.detail_specs)
# --------------------------------------------------------------------------

_PROSE_KEYS = frozenset({
    "overview_text_raw", "overview", "description", "title", "name",
    "specs_table_raw", "image_url",
})


def _emit_clock_range(facts: dict, category: str, value) -> None:
    """'3.6GHz - 4GHz' -> base_clock_ghz + boost_clock_ghz."""
    match = _CLOCK_RANGE_RE.search(str(value or ""))
    if not match:
        return
    _emit(facts, category, "base_clock_ghz", float(match.group(1)), SOURCE_DETAIL, 0.8)
    _emit(facts, category, "boost_clock_ghz", float(match.group(2)), SOURCE_DETAIL, 0.8)


def parse_detail_specs(category: str | None, detail_specs) -> dict[str, list[Fact]]:
    """Structured spec rows from a vendor product page."""
    facts: dict[str, list[Fact]] = {}
    if not detail_specs:
        return facts

    if isinstance(detail_specs, dict):
        for key, value in detail_specs.items():
            if str(key) in _PROSE_KEYS:
                continue
            label = translate_ivory_label(key)
            if label == "__clock_range__":
                _emit_clock_range(facts, category or "", value)
                continue
            _emit_by_key(facts, category or "", label or key, value, SOURCE_DETAIL)
        return facts

    for row in detail_specs:
        if not isinstance(row, dict):
            continue
        key = row.get("key") or row.get("label") or row.get("name")
        value = row.get("value") or row.get("spec") or row.get("data")
        label = translate_ivory_label(key)
        if label == "__clock_range__":
            _emit_clock_range(facts, category or "", value)
            continue
        _emit_by_key(facts, category or "", label or key or "", value, SOURCE_DETAIL)
    return facts


# --------------------------------------------------------------------------
# vendor_meta scalars + Ivory cuts
# --------------------------------------------------------------------------


def parse_meta_scalars(category: str | None, meta) -> dict[str, list[Fact]]:
    """Scalar keys in the vendor payload (TMS/Ivory builder dicts)."""
    facts: dict[str, list[Fact]] = {}
    if not isinstance(meta, dict):
        return facts
    for key, value in meta.items():
        if key in ("detail_specs", "cuts", "tree", "description", "title",
                   "images", "image_url", "parent_id", "category_id"):
            continue
        if isinstance(value, (dict, list)) or value is None:
            continue
        _emit_by_key(facts, category or "", key, value, SOURCE_META, 0.8)
    return facts


def load_cut_labels() -> dict:
    """Ivory builder cut-id -> spec mapping (committed ground truth)."""
    global _LABELS_CACHE
    if _LABELS_CACHE is None:
        try:
            _LABELS_CACHE = json.loads(CUT_LABELS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LABELS_CACHE = {}
    return _LABELS_CACHE


def parse_cuts(category: str | None, cuts) -> dict[str, list[Fact]]:
    """Decode Ivory's opaque builder filter ids into schema fields."""
    facts: dict[str, list[Fact]] = {}
    if not isinstance(cuts, list):
        return facts
    labels = load_cut_labels().get("cuts") or {}
    for cut in cuts:
        mapping = labels.get(str(cut))
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            if is_promo_label(value):
                continue
            _emit_by_key(facts, category or "", key, value, SOURCE_CUTS, 0.8)
    return facts


# --------------------------------------------------------------------------
# Post-match bridge (matching.py computed attributes -> Tier 1 facts)
# --------------------------------------------------------------------------


def ingest_computed_attributes(category: str | None, attributes) -> dict[str, list[Fact]]:
    """Promote `attributes` keys computed outside the spec system.

    After this overhaul `attributes` is a *derived* view of `specs`
    (specs/legacy.py), so the only genuinely new information in it is what
    matching.py computes from the listing dict itself: canonical `brand`,
    `model`, `mpn`, `accessory_type` and the like. Those enter here as Tier-1
    facts so the same fact stops existing twice in two shapes.

    Idempotent: re-ingesting the legacy view yields identical values.
    """
    facts: dict[str, list[Fact]] = {}
    if not isinstance(attributes, dict):
        return facts
    for key, value in attributes.items():
        if value in (None, "", [], {}):
            continue
        field = schema.field_for_key(category or "", key)
        if field is None:
            continue
        if field.type == "list_str" and not isinstance(value, (list, tuple)):
            value = [value]
        _emit(facts, category or "", field.name, value, SOURCE_COMPUTED, 0.9)
    return facts


def parse_listing_identity(category: str | None, listing: dict) -> dict[str, list[Fact]]:
    """Listing-level identity fields matching.py maintains (mpn/brand)."""
    facts: dict[str, list[Fact]] = {}
    mpn = listing.get("mpn")
    if mpn:
        _emit(facts, category or "", "part_numbers", [str(mpn)], SOURCE_COMPUTED, 0.95)
    brand = listing.get("brand")
    if brand:
        _emit(facts, category or "", "manufacturer", brand, SOURCE_COMPUTED, 0.7)
    return facts


def parse_vendor_struct(category: str | None, listing: dict) -> dict[str, list[Fact]]:
    """All Tier-1 facts for one listing."""
    meta = listing.get("vendor_meta") or {}
    facts = parse_detail_specs(category, meta.get("detail_specs"))
    for key, value in parse_meta_scalars(category, meta).items():
        facts.setdefault(key, []).extend(value)
    for key, value in parse_cuts(category, meta.get("cuts")).items():
        facts.setdefault(key, []).extend(value)
    return facts
