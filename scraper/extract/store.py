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
from ..specs.values import InvalidValue, coerce
from .runner import PRODUCTS, ROOT, trusted_fields
from .verify import normalize, product_text

SOURCE = "extracted"
ALIASES = ROOT / "data" / "site" / "meta.json"


@lru_cache(maxsize=1)
def _entries() -> dict:
    try:
        data = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("schema_version") != schema.SCHEMA_VERSION:
        return {}
    return data.get("entries") or {}


_RUN_ALIASES: dict[str, str] = {}


def set_run_aliases(aliases: dict | None) -> None:
    """This run's pid renames (`match_listings` `pid_aliases`), read before
    the build writes them (review 2, 2026-11-12): a pid retired IN this run
    is not yet in the previous build's meta.json, so its facts were lost
    for one build."""
    _RUN_ALIASES.clear()
    _RUN_ALIASES.update({str(k): str(v) for k, v in (aliases or {}).items()})
    _alias_sources.cache_clear()


def _resolve(target: str, aliases: dict[str, str]) -> str:
    seen = {target}
    while target in aliases and aliases[target] not in seen:
        target = aliases[target]
        seen.add(target)
    return target


@lru_cache(maxsize=1)
def _alias_sources() -> dict[str, tuple[str, ...]]:
    """Live pid -> the retired pids that alias to it (audit 2026-11-10 K).

    The previous build's `data/site/meta.json` `pid_aliases` (chains already
    resolved by `_carry_pid_aliases`) plus this run's own renames
    (`set_run_aliases`), chains followed through both, so an entry extracted
    under a pid that a rework retired still reaches its product without
    rekeying the git-tracked store."""
    try:
        meta = json.loads(ALIASES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    aliases = {str(k): str(v) for k, v in (meta.get("pid_aliases") or {}).items()}
    aliases.update(_RUN_ALIASES)
    sources: dict[str, list[str]] = {}
    for old_pid in aliases:
        sources.setdefault(_resolve(old_pid, aliases), []).append(old_pid)
    return {target: tuple(sorted(olds)) for target, olds in sources.items()}


@lru_cache(maxsize=1)
def _trusted() -> frozenset:
    return frozenset(trusted_fields())


def _part_key(value) -> str:
    """Compact part-number key mirroring matching.mpn_part_key (lowercase)."""
    import re

    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if len(key) > 5 and key.startswith("gv"):
        rest = key[2:]
        if len(rest) >= 3 and re.search(r"\d", rest):
            return rest
    return key


def _candidate_part_numbers(listings: list[dict]) -> list[str]:
    """Part numbers carried by one product's listings (mpn / sku / part rows)."""
    seen: list[str] = []
    for listing in listings or []:
        for value in (listing.get("mpn"), listing.get("vendor_sku")):
            if value and str(value) not in seen:
                seen.append(str(value))
        attrs = listing.get("attributes") or {}
        for name in ("part_numbers", "part_number", "mpn"):
            raw = attrs.get(name)
            values = raw if isinstance(raw, (list, tuple, set)) else [raw]
            for value in values:
                if value and str(value) not in seen:
                    seen.append(str(value))
    return seen


def _candidate_ids(product_id, category: str | None, listings: list[dict]) -> list[str]:
    """Cache keys worth trying for one product: exact id, aliased ids, PNs.

    Product ids churn with every identity rework (the token-sort rework moved
    ~3.7k pids from ``mpn:`` to ``model:``), but the extraction cache is keyed
    by the pid it was extracted under — so a rekeyed product silently loses
    every extracted fact. The part number is stable across rekeys, so when the
    exact id misses, the same lookups the matcher uses (``mpn:<category>:<key>``
    and ``sku:<category>:<key>``) recover the entry. Each fact is still
    quote-verified against this product's own text below, so a wrong candidate
    cannot land on the wrong product.
    """
    ids = [str(product_id)]
    # Retired pids that alias to this product (a rekey must not orphan a fact).
    ids += [old for old in _alias_sources().get(str(product_id), ()) if old not in ids]
    if not category:
        return ids
    for raw in _candidate_part_numbers(listings):
        key = _part_key(raw)
        if not key:
            continue
        for prefix in ("mpn", "sku"):
            candidate = f"{prefix}:{category}:{key}"
            if candidate not in ids:
                ids.append(candidate)
    return ids


def facts_for(product_id, category: str | None, listings: list[dict]) -> dict[str, list[Fact]]:
    if os.environ.get("MIFRAT_NO_EXTRACT"):
        return {}
    entries = _entries()
    text = None
    fields = schema.field_map(category)
    facts: dict[str, list[Fact]] = {}
    for candidate in _candidate_ids(product_id, category, listings):
        entry = entries.get(candidate)
        if not entry or entry.get("category") != category:
            continue
        for field, value in (entry.get("specs") or {}).items():
            if field not in fields or value is None or (
                    entry.get("model"), category, field) not in _trusted():
                continue
            if text is None:
                text = normalize(product_text(listings))
            quote = normalize((entry.get("quotes") or {}).get(field) or "")
            if not quote or quote not in text:
                continue
            # The model wrote the vendor's spelling ("INTELHM770"): canonicalize
            # it like a vendor value, so it is a schema key or no fact at all.
            try:
                value = coerce(fields[field], value, category)
            except InvalidValue:
                continue
            facts.setdefault(field, []).append(Fact(
                value=value, tier=TIER_EXTRACTED,
                source=f"{SOURCE}:{entry.get('model') or 'claude'}", confidence=0.7))
    return facts
