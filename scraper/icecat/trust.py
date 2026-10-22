"""
icecat/trust.py - how often each Icecat field agrees with what sources say.

For every catalog product an Icecat entry joins, compare each Icecat field with
the product's value from a sourced tier (vendor, maker page, reference,
override; never derived or title, never Icecat itself). A field whose
disagreement rate exceeds mapping.TRUST_MAX_DISAGREE on at least MIN_OVERLAP
overlaps belongs in mapping.DISABLED. Prints the table; exits 1 when a field
that is NOT disabled is over the limit.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from .mapping import DISABLED, REVIEWED_OVER, TRUST_MAX_DISAGREE

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT / "data" / "catalog.json"
MIN_OVERLAP = 10
_SOURCED = ("vendor", "manufacturer", "reference", "override")


def report() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from backtest_rules import agrees  # noqa: E402  (scripts/)

    from ..mfr.store import load_index
    from .store import DATA_DIR

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    index = load_index(DATA_DIR)
    from ..mfr.common import base_mpn, norm_mpn, norm_upc

    tally: dict = defaultdict(lambda: {"overlap": 0, "agree": 0, "examples": []})
    for product in catalog["products"]:
        specs = product.get("specs") or {}
        sources = product.get("spec_sources") or {}
        brand = str(specs.get("manufacturer") or product.get("brand") or "").lower()
        entry = None
        for value in specs.get("part_numbers") or []:
            for key in (norm_mpn(value), base_mpn(value), norm_upc(value)):
                entry = entry or (index.get((brand, "k:" + key)) if key else None)
        if not entry or entry.get("category") != product.get("category"):
            continue
        category = product["category"]
        for field, value in (entry.get("specs") or {}).items():
            if str(sources.get(field) or "").split(":", 1)[0] not in _SOURCED:
                continue
            actual = specs.get(field)
            if actual is None:
                continue
            slot = tally[(category, field)]
            slot["overlap"] += 1
            if agrees(category, field, value, actual):
                slot["agree"] += 1
            elif len(slot["examples"]) < 3:
                slot["examples"].append((product.get("canonical_name"), value, actual))
    bad = []
    print(f"{'category.field':<36}{'overlap':>8}{'agree':>7}{'disagree%':>11}  state")
    for (category, field), slot in sorted(tally.items()):
        rate = 1 - slot["agree"] / slot["overlap"]
        disabled = field in DISABLED.get(category, ())
        reviewed = field in REVIEWED_OVER.get(category, ())
        over = slot["overlap"] >= MIN_OVERLAP and rate > TRUST_MAX_DISAGREE and not reviewed
        state = ("disabled" if disabled else "OVER" if over
                 else "reviewed: sourced side wrong" if reviewed else "")
        print(f"{category + '.' + field:<36}{slot['overlap']:>8}{slot['agree']:>7}"
              f"{rate * 100:>10.1f}%  {state}")
        if over and not disabled:
            bad.append((category, field))
            for name, ours, theirs in slot["examples"]:
                print(f"      icecat={ours!r} sourced={theirs!r}  {str(name)[:60]}")
    if bad:
        print(f"[icecat-trust] {len(bad)} enabled field(s) over "
              f"{TRUST_MAX_DISAGREE:.0%} disagreement: add them to mapping.DISABLED")
        return 1
    print("[icecat-trust] every enabled field within the limit")
    return 0
