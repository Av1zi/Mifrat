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
from functools import lru_cache
from pathlib import Path

from ..specs import schema
from ..specs.merge import TIER_MANUFACTURER, Fact
from .common import base_mpn, norm_mpn, norm_upc, strict_name

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "mfr"
SOURCE = "manufacturer"


@lru_cache(maxsize=1)
def _index() -> dict:
    """{(brand_lower, key): entry} over every data/mfr/*.json."""
    index: dict = {}
    ambiguous: set = set()
    for path in sorted(DATA_DIR.glob("*.json")):
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
            for name in entry.get("names", []):
                index[(brand, "n:" + name)] = entry
    for slot in ambiguous:
        index.pop(slot, None)
    return index


def reset_cache() -> None:
    _index.cache_clear()


def facts_for(category: str | None, brand: str | None, part_numbers,
              name: str | None) -> dict[str, list[Fact]]:
    """Tier-0.5 facts for one product ({} when no manufacturer page matched)."""
    if not brand:
        return {}
    index = _index()
    if not index:
        return {}
    brand_key = str(brand).lower()
    entry = None
    for value in part_numbers or []:
        for key in (norm_mpn(value), base_mpn(value), norm_upc(value)):
            if key:
                entry = index.get((brand_key, "k:" + key)) or entry
    if entry is None and name:
        entry = index.get((brand_key, "n:" + strict_name(name, brand_key)))
    if not entry or entry.get("category") != category:
        return {}
    fields = schema.field_map(category)
    facts: dict[str, list[Fact]] = {}
    for field, value in (entry.get("specs") or {}).items():
        if field in fields and value is not None:
            facts.setdefault(field, []).append(Fact(
                value=value, tier=TIER_MANUFACTURER,
                source=f"{SOURCE}:{brand_key}", confidence=0.9))
    return facts
