"""
specs/merge.py — deterministic tiered merge (the accuracy model).

Sources are ranked, and a lower tier NEVER overwrites a higher one:

    -1 override   data/specs/overrides.json (human-edited, always wins)
     0 reference  PCPartPicker/docyx dataset + curated reference rows
     1 vendor     vendor structured payloads (Ivory cuts/detail, TMS fields,
                  and keys matching.py computes post-match: mpn, accessory_type)
     2 title      typed regex extraction over the listing title/SKU
     3 weak       prose fragments (Plonter dash-dumps, 1PC prose)

Rules (plan §4):
1. Higher tier wins outright.
2. Equal-tier disagreement -> higher confidence wins; a tie keeps the first
   fact (resolvers are called in a fixed order) and is logged as a conflict.
3. A lower-tier value that contradicts the winner is DISCARDED and logged —
   never merged, never silently overwriting.
4. A field no tier supplies ships as `null`. `null` is a real value here:
   wrong specs are worse than missing specs.
5. Every value passes validation before entering the sheet (validate.py);
   rejected candidates are counted in the run report, never kept.

The merge never mutates its inputs: it returns a fresh fixed-key spec dict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import Any

from . import schema

TIER_OVERRIDE = -1
TIER_REFERENCE = 0
TIER_VENDOR = 1
TIER_TITLE = 2
TIER_WEAK = 3

TIER_NAMES = {
    TIER_OVERRIDE: "override",
    TIER_REFERENCE: "reference",
    TIER_VENDOR: "vendor",
    TIER_TITLE: "title",
    TIER_WEAK: "weak",
}


@dataclass(frozen=True)
class Fact:
    """One typed claim about one field, with its provenance."""

    value: Any
    tier: int
    source: str
    confidence: float = 1.0
    listing_key: str | None = None

    @property
    def tier_name(self) -> str:
        return TIER_NAMES.get(self.tier, f"tier{self.tier}")


@dataclass
class Conflict:
    field: str
    kept: Fact
    dropped: Fact
    kind: str  # "cross_tier" | "same_tier"

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "kind": self.kind,
            "kept": {"value": self.kept.value, "tier": self.kept.tier_name,
                     "source": self.kept.source},
            "dropped": {"value": self.dropped.value, "tier": self.dropped.tier_name,
                        "source": self.dropped.source},
        }


@dataclass
class InvalidFact:
    field: str
    value: Any
    tier: str
    source: str
    reason: str

    def as_dict(self) -> dict:
        return {"field": self.field, "value": self.value, "tier": self.tier,
                "source": self.source, "reason": self.reason}


@dataclass
class MergeResult:
    specs: dict[str, Any] = _dc_field(default_factory=dict)
    sources: dict[str, str] = _dc_field(default_factory=dict)
    conflicts: list[Conflict] = _dc_field(default_factory=list)
    invalid: list[InvalidFact] = _dc_field(default_factory=list)

    def conflicts_as_dicts(self) -> list[dict]:
        return [c.as_dict() for c in self.conflicts]

    def invalid_as_dicts(self) -> list[dict]:
        return [f.as_dict() for f in self.invalid]


def model_name_preference(fact: "Fact") -> int:
    """Sort key for the `model` field: 0 for a name, 1 for a part number.

    Kept as a named helper so the rule is greppable from values.py and the
    golden fixture that pinned the bug (model:cpu:ryzen79800x3d-tray).
    """
    from .values import looks_like_part_number

    return 1 if looks_like_part_number(fact.value) else 0


def same_value(a, b) -> bool:
    """Value equality that ignores representation noise ('65W' == '65 w',
    ['A','B'] == ['B','A'] for lists)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(a, dict) and isinstance(b, dict):
        return sorted(map(str, a.items())) == sorted(map(str, b.items()))
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return sorted(map(str, a)) == sorted(map(str, b))
    # Whitespace is presentation, not content: "65 w" and "65W" are the same
    # claim, and treating them as different wrote a phantom conflict for every
    # product whose two sources spell the unit differently (the docstring has
    # promised this since the overhaul; Sep 2026 made the code match it).
    return _eq_key(a) == _eq_key(b)


def _eq_key(value) -> str:
    return re.sub(r"\s+", "", str(value)).lower()


def _rank(fact: Fact, order: int) -> tuple:
    # Lowest tier first; inside a tier, higher confidence first; then the
    # resolver's call order (stable and deterministic across runs).
    return (fact.tier, -fact.confidence, order)


def merge_facts(category: str | None, facts: dict[str, list[Fact]],
                *, run_validators: bool = True) -> MergeResult:
    """Merge per-field fact lists into one fixed-key spec sheet."""
    result = MergeResult(specs=schema.empty_specs(category))

    for name, candidates in facts.items():
        field = schema.field_map(category).get(name)
        if field is None:
            # A resolver emitted a key the schema does not own: drop it.
            for candidate in candidates:
                result.invalid.append(InvalidFact(
                    field=name, value=candidate.value, tier=candidate.tier_name,
                    source=candidate.source, reason="unknown field (not in schema)"))
            continue

        ordered = sorted(enumerate(candidates), key=lambda pair: _rank(pair[1], pair[0]))

        accepted: list[Fact] = []
        for _order, fact in ordered:
            if run_validators:
                from .validate import validate_fact

                reason = validate_fact(category, field, fact.value)
                if reason:
                    result.invalid.append(InvalidFact(
                        field=name, value=fact.value, tier=fact.tier_name,
                        source=fact.source, reason=reason))
                    continue
            accepted.append(fact)

        if not accepted:
            continue

        # `model` is a name, not a code. When several sources answer, a value
        # that is really a manufacturer part number (Ivory's detail page keeps
        # the MPN in its "דגם" row: 100-1000001084WOF for a Ryzen 7 9800X3D)
        # must not outrank a real name just because it arrived at a higher
        # tier — that showed an MPN as the model AND flipped the product's
        # identity key. Stable sort: tier/confidence still order values of the
        # same kind, and a product whose only model value IS a part number
        # keeps it (nothing is dropped, the loser is recorded as a conflict).
        if name == "model" and len(accepted) > 1 and any(
                model_name_preference(fact) == 0 for fact in accepted):
            accepted.sort(key=model_name_preference)

        winner = accepted[0]
        result.specs[name] = winner.value
        result.sources[name] = winner.tier_name

        for loser in accepted[1:]:
            if same_value(winner.value, loser.value):
                continue
            kind = "same_tier" if loser.tier == winner.tier else "cross_tier"
            result.conflicts.append(
                Conflict(field=name, kept=winner, dropped=loser, kind=kind))

    return result


def add_fact(facts: dict[str, list[Fact]], name: str, fact: Fact) -> None:
    """Helper for resolvers: append a Fact to the per-field list."""
    if fact.value is None:
        return
    facts.setdefault(name, []).append(fact)
