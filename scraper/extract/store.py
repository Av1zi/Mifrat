"""
extract/store.py - reads data/extract/products.json for the spec merge (tier 1.5).

Keyed by product id, so a value only ever lands on the product whose text it
was quoted from. Two checks at read time:

- the field passed the audit (runner.trusted_fields: measured, under 3%);
- the quote is still in the product's current listing text. A vendor that
  rewrote its page takes the extracted value with it.

MIFRAT_NO_EXTRACT=1 leaves the tier out (to measure what it adds).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from ..specs import schema
from ..specs.merge import TIER_EXTRACTED, Fact
from .runner import PRODUCTS, trusted_fields
from .verify import normalize, product_text

SOURCE = "extracted"


@lru_cache(maxsize=1)
def _entries() -> dict:
    try:
        data = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("schema_version") != schema.SCHEMA_VERSION:
        return {}
    return data.get("entries") or {}


@lru_cache(maxsize=1)
def _trusted() -> frozenset:
    return frozenset(trusted_fields())


def facts_for(product_id, category: str | None, listings: list[dict]) -> dict[str, list[Fact]]:
    if os.environ.get("MIFRAT_NO_EXTRACT"):
        return {}
    entry = _entries().get(str(product_id))
    if not entry or entry.get("category") != category:
        return {}
    text = None
    fields = schema.field_map(category)
    facts: dict[str, list[Fact]] = {}
    for field, value in (entry.get("specs") or {}).items():
        if field not in fields or value is None or (category, field) not in _trusted():
            continue
        if text is None:
            text = normalize(product_text(listings))
        quote = normalize((entry.get("quotes") or {}).get(field) or "")
        if not quote or quote not in text:
            continue
        facts.setdefault(field, []).append(Fact(
            value=value, tier=TIER_EXTRACTED,
            source=f"{SOURCE}:{entry.get('model') or 'claude'}", confidence=0.7))
    return facts
