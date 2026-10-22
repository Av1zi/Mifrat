"""
icecat/store.py - reads data/icecat/<brand>.json for the spec merge (tier 0.75).

Same entry shape and exact-key join as scraper/mfr/store.py (normalised MPN /
barcode keys only; no name matching: an Icecat sheet joins on an identifier it
printed itself). Fields in mapping.DISABLED are dropped at read time too, so
disabling a field takes effect without re-fetching.

Measuring trust: `MIFRAT_NO_ICECAT=1 python -m scraper.normalize_and_match`
then `python -m scraper.icecat --trust` (it compares against that catalog).
"""

from __future__ import annotations

import os
from pathlib import Path

from ..mfr.store import facts_from, load_index
from ..specs.merge import TIER_CATALOG, Fact
from .mapping import DISABLED

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "icecat"
SOURCE = "catalog"


def facts_for(category: str | None, brand: str | None,
              part_numbers) -> dict[str, list[Fact]]:
    # MIFRAT_NO_ICECAT=1 builds the catalog without this tier, which is how
    # `python -m scraper.icecat --trust` sees the vendor values Icecat would
    # otherwise outrank.
    if os.environ.get("MIFRAT_NO_ICECAT"):
        return {}
    facts = facts_from(load_index(DATA_DIR), category, brand, part_numbers, None,
                       tier=TIER_CATALOG, source=f"{SOURCE}:icecat", confidence=0.85)
    for field in DISABLED.get(category or "", ()):
        facts.pop(field, None)
    return facts
