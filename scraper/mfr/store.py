"""
mfr/store.py - reads data/mfr/<brand>.json for the spec merge (Tier 0.5).

A fetcher writes one entry per manufacturer page:

    {"url": ..., "fetched": "2026-10-17", "category": "case",
     "keys": ["CO9050111WW", "0761345800501"],      # normalised MPN / UPC
     "names": ["p10flux"],                           # brand-stripped names
     "specs": {"max_gpu_length_mm": 405, ...}}       # schema fields, typed

A product matches an entry when one of its normalised part numbers equals a key
or its brand-stripped name equals a recorded name. Matching is exact on purpose:
a wrong manufacturer row would outrank the retailer's correct one.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..specs import schema
from ..specs.merge import TIER_MANUFACTURER, Fact
from .common import base_mpn, norm_mpn, norm_upc, strict_name

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "mfr"
SOURCE = "manufacturer"


def alt_key(value) -> str:
    """Order-insensitive MPN key: letters and digits kept as two runs.

    Pages keyed by URL slug spell the part as the marketing name reads
    ("csk-dc-750w") while the retailer MPN puts the wattage in the middle
    ("CSK750DC-W"); both become "CSKDCW#750". Looser than `norm_mpn`, so the
    index drops an alt key two pages share and the join only uses it after
    the exact keys missed. Empty unless the value mixes 2+ letters and digits.
    """
    text = norm_mpn(value)
    letters = re.sub(r"[^A-Z]", "", text)
    digits = re.sub(r"\D", "", text)
    if len(letters) < 2 or not digits or len(text) < 5:
        return ""
    return f"{letters}#{digits}"


@lru_cache(maxsize=1)
def _index() -> dict:
    """{(brand_lower, key): entry} over every data/mfr/*.json."""
    return load_index(DATA_DIR)


@lru_cache(maxsize=None)
def load_index(data_dir: Path) -> dict:
    """{(brand_lower, key): entry} over every <data_dir>/*.json at the current
    schema version (shared by data/mfr and data/icecat)."""
    index: dict = {}
    ambiguous: set = set()
    for path in sorted(Path(data_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("schema_version") != schema.SCHEMA_VERSION:
            continue                      # stale vs the schema: ignore, refetch
        brand = str(data.get("brand") or path.stem).lower()
        for entry in (data.get("entries") or {}).values():
            for key in entry.get("keys", []):
                slot = (brand, "k:" + key)
                # An identifier two different pages both claim (a multipack page
                # that repeats the single fan's barcode) joins nothing.
                if slot in index and index[slot].get("url") != entry.get("url"):
                    ambiguous.add(slot)
                index[slot] = entry
            for alt in {alt_key(key) for key in entry.get("keys", [])} - {""}:
                slot = (brand, "a:" + alt)
                if slot in index and index[slot].get("url") != entry.get("url"):
                    ambiguous.add(slot)
                index[slot] = entry
            for name in entry.get("names", []):
                index[(brand, "n:" + name)] = entry
    for slot in ambiguous:
        index.pop(slot, None)
    return index


def facts_for(category: str | None, brand: str | None, part_numbers,
              name: str | None) -> dict[str, list[Fact]]:
    """Tier-0.5 facts for one product ({} when no manufacturer page matched)."""
    return facts_from(_index(), category, brand, part_numbers, name,
                      tier=TIER_MANUFACTURER, source=SOURCE)


def facts_from(index: dict, category: str | None, brand: str | None, part_numbers,
               name: str | None, *, tier: float, source: str,
               confidence: float = 0.9) -> dict[str, list[Fact]]:
    """Facts from one entry index (data/mfr or data/icecat) for one product."""
    if not brand:
        return {}
    if not index:
        return {}
    brand_key = str(brand).lower()
    entry = None
    for value in part_numbers or []:
        for key in (norm_mpn(value), base_mpn(value), norm_upc(value)):
            if key:
                entry = index.get((brand_key, "k:" + key)) or entry
    if entry is None:
        for value in part_numbers or []:
            alt = alt_key(value)
            if alt:
                entry = index.get((brand_key, "a:" + alt)) or entry
    if entry is None and name:
        entry = index.get((brand_key, "n:" + strict_name(name, brand_key)))
    if not entry or entry.get("category") != category:
        return {}
    fields = schema.field_map(category)
    facts: dict[str, list[Fact]] = {}
    for field, value in (entry.get("specs") or {}).items():
        if field in fields and value is not None:
            facts.setdefault(field, []).append(Fact(
                value=value, tier=tier,
                source=f"{source}:{brand_key}", confidence=confidence))
    return facts
