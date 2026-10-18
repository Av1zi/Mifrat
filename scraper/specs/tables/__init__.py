"""
specs/tables - curated lookup tables for derived specs (plan Phase 1c).

Each JSON file is DATA, not logic: a table keyed by an anchor the product
already carries (GPU chipset, CPU model token) mapping to facts the anchor
fixes for every SKU that shares it. `derive.infer_specs` is the only reader;
a cell it fills is tagged `derived:<table>.<rule>` and only ever fills a null,
so any sourced value from any tier still wins.

Rules for editing a table:
- list a field only when it is INVARIANT for the anchor (an RTX 3060 has
  12GB/192-bit AND 8GB/128-bit variants, so its bus width is absent);
- cite the source in `_source`; `scripts/fill_report.py --check-tables`
  compares every row to the vendor-published values already in the catalog
  and prints disagreements - run it after any edit;
- if the table cannot answer, the field stays null. Never fill a guess.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    """The `rows` mapping of tables/<name>.json ({} when the file is absent)."""
    try:
        data = json.loads((DIR / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("rows")
    return rows if isinstance(rows, dict) else {}
