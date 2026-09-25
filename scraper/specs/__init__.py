"""
scraper/specs — the typed, tiered spec system.

    schema.py     canonical field definitions (names, types, units, enums,
                  ranges, aliases, filter/display metadata, labels)
    values.py     typed coercion at the resolver boundary
    canon.py      canonical forms for known-value fields
    text.py       the one place regexes live
    validate.py   per-value validators + cross-field consistency
    merge.py      deterministic tiered merge (what wins, what is logged)
    derive.py     UI facets derived from typed specs (cpu tier/generation)
    legacy.py     transitional `attributes` view derived from `specs`
    build.py      orchestration (listing pass + product pass)
    report.py     coverage/conflict report for a normalize run
    api.py        public surface consumed by matching.py / normalize_and_match.py
    resolvers/    one module per source tier (reference/vendor/title/weak)
    golden/       hand-verified fixtures + check_golden.py

Read specs/README.md for the design rationale and the handoff notes.
"""

from __future__ import annotations

from .api import (
    CoverageReport,
    build_listing_attributes,
    build_product_specs,
    canonicalize_filter_values,
    extract_attributes,
    listing_facts,
    unify_duplicate_attributes,
)
from .merge import (
    TIER_NAMES,
    TIER_OVERRIDE,
    TIER_REFERENCE,
    TIER_TITLE,
    TIER_VENDOR,
    TIER_WEAK,
    Fact,
)
from .schema import SCHEMA, SCHEMA_VERSION, empty_specs, field_names, filterable_fields

__all__ = [
    "SCHEMA",
    "SCHEMA_VERSION",
    "TIER_NAMES",
    "TIER_OVERRIDE",
    "TIER_REFERENCE",
    "TIER_TITLE",
    "TIER_VENDOR",
    "TIER_WEAK",
    "CoverageReport",
    "Fact",
    "build_listing_attributes",
    "build_product_specs",
    "canonicalize_filter_values",
    "empty_specs",
    "extract_attributes",
    "field_names",
    "filterable_fields",
    "listing_facts",
    "unify_duplicate_attributes",
]
