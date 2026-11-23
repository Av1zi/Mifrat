"""Recomputed QA proof decisions, never permanent dismissal-ledger entries.

Only exact-key manufacturer fan-performance evidence is eligible in this
rollout. CPU metrics, partial model descriptions and identity changes stay
open until their own corpus and full-catalog gates exist.
"""
from __future__ import annotations

import math
import re

from . import schema
from .merge import TIER_MANUFACTURER, same_value

RULE_MODES = {"manufacturer_fan_performance": "enabled"}
FAN_FIELDS = frozenset({"rpm_max", "airflow_cfm", "noise_db", "static_pressure_mmh2o"})


def fan_resolution(category: str, field: str, selected, source: str | None,
                   conflicts: list[dict], *, uncertain: bool = False) -> dict | None:
    """Require current final-value proof and inspect every competing claim."""
    rule = "manufacturer_fan_performance"
    mode = RULE_MODES[rule]
    if (mode == "off" or uncertain or category != "case_fan" or field not in FAN_FIELDS
            or selected is None or source != "manufacturer" or not conflicts):
        return None
    from .validate import validate_fact
    if validate_fact(category, schema.field_map(category)[field], selected):
        return None
    for conflict in conflicts:
        kept, dropped = conflict.get("kept"), conflict.get("dropped")
        if not isinstance(kept, dict) or not isinstance(dropped, dict):
            return None
        evidence = kept.get("evidence")
        if not isinstance(evidence, dict):
            return None
        keys = evidence.get("sku_keys")
        if not isinstance(keys, (list, tuple)) or not all(isinstance(key, str) for key in keys):
            return None
        if (kept.get("tier") != "manufacturer"
                or not same_value(selected, kept.get("value"), field=field)
                or evidence.get("match_method") != "exact_key"
                or evidence.get("complete") is not True
                or evidence.get("meaning") != field
                or evidence.get("unit") != schema.field_map(category)[field].unit
                or not str(evidence.get("source_url") or "").startswith("https://")
                or not isinstance(evidence.get("fingerprint"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("fingerprint") or ""))
                or not isinstance(evidence.get("origin"), str) or not evidence.get("origin")
                or not isinstance(evidence.get("matched_key"), str) or not evidence.get("matched_key")
                or evidence.get("matched_key") not in keys):
            return None
        # Missing rank in legacy input grants no new authority. Reference
        # and other manufacturer contradictions always require review.
        rank = dropped.get("rank")
        if (not isinstance(rank, (int, float)) or isinstance(rank, bool)
                or not math.isfinite(rank) or rank <= TIER_MANUFACTURER):
            return None
    proof = conflicts[0]["kept"]["evidence"]
    return {"state": "auto_resolved" if mode == "enabled" else "shadow",
            "reason": "exact_manufacturer_spec", "rule": rule,
            "evidence_ref": proof["fingerprint"]}


def reopen_uncertain(report: dict, identity_cases: list[dict]) -> None:
    """Final grouping flags are computed after specs; they veto resolution."""
    uncertain = {case.get("product_id") for case in identity_cases}
    for case in identity_cases:
        # Cross-product findings name a representative AND every implicated
        # product. None of those products can inherit automatic authority.
        uncertain.update(case.get("product_ids") or [])
    for conflict in report.get("conflicts") or []:
        if conflict.get("product_id") in uncertain:
            conflict.pop("resolution", None)
            conflict.pop("auto_resolved", None)
