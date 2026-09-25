"""
specs/api.py — the spec system's public surface for the rest of the pipeline.

`extract_attributes` keeps the pre-overhaul name and contract (a listing in,
an `attributes` dict out) so scraper/matching.py only changes an import; it now
returns the DERIVED view of the typed spec resolution (specs/legacy.py).

The two other names exist because matching.py's PC-Kombo path used them from
the retired extractors module:

- `canonicalize_filter_values(attrs, category)` — canonicalizes/validates
  values in an attributes dict in place (brands, colors, units, junk removal);
- `unify_duplicate_attributes(attrs, category)` — a documented no-op: with one
  schema there is exactly one key per fact, so there is nothing left to fold.
"""

from __future__ import annotations

from . import schema
from .build import build_listing_attributes, build_product_specs, listing_facts
from .derive import cpu_generation, cpu_tier
from .report import CoverageReport
from .values import InvalidValue, coerce, is_placeholder

# Backwards-compatible name for matching.py's import.
extract_attributes = build_listing_attributes


def canonicalize_filter_values(attributes: dict, category: str | None) -> None:
    """Normalize/filter an attributes dict in place (post-enrichment clean-up)."""
    if not isinstance(attributes, dict):
        return
    for key in list(attributes):
        value = attributes[key]
        if value in (None, "", [], {}):
            continue
        field = schema.field_for_key(category or "", key)
        if field is None:
            continue
        try:
            attributes[key] = coerce(field, value, category)
        except InvalidValue:
            del attributes[key]


def unify_duplicate_attributes(attributes: dict, category: str | None) -> None:
    """No-op kept for import compatibility (one schema = one key per fact)."""
    return


__all__ = [
    "CoverageReport",
    "build_listing_attributes",
    "build_product_specs",
    "canonicalize_filter_values",
    "cpu_generation",
    "cpu_tier",
    "extract_attributes",
    "is_placeholder",
    "listing_facts",
    "unify_duplicate_attributes",
]
