"""
xref/store.py - reads data/xref/<site>/<brand>.json for the spec merge.

Vendor tier (`vendor`): a foreign retailer's table counts like one of ours;
the brand's page, Open Icecat and the reference rows outrank it. Exact
MPN / EAN keys only, as in mfr/store.py.
"""

from __future__ import annotations

from pathlib import Path

from ..mfr.store import facts_from, load_index
from ..specs.merge import TIER_VENDOR, Fact

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "xref"
SITES = ("overclockers",)


def facts_for(category: str | None, brand: str | None,
              part_numbers) -> dict[str, list[Fact]]:
    facts: dict[str, list[Fact]] = {}
    for site in SITES:
        directory = DATA_ROOT / site
        if not directory.is_dir():
            continue
        for key, value in facts_from(load_index(directory), category, brand, part_numbers, None,
                                     tier=TIER_VENDOR, source=f"xref:{site}",
                                     confidence=0.8).items():
            facts.setdefault(key, []).extend(value)
    return facts
