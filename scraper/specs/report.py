"""
specs/report.py — the accuracy dashboard for one normalize run.

Per category x field it tracks how many products got a value and which tier
supplied it, plus every conflict, dropped-invalid value and cross-field issue
the merge produced. This is what makes silent degradation visible: if Tier 0
(reference data) is missing, `ref` collapses to 0% and the summary says so.

`to_dict()` output lands in data/site/spec_report.json (for humans debugging a
run and for strict CI gates); conflicts also become `spec_conflict` QA cases
for the public #/qa page (site_data.py reads them from the catalog).
"""

from __future__ import annotations

import json
import re

from . import schema

CORE_FIELDS = ("socket", "chipset", "memory_type", "wattage_w", "form_factor")


class CoverageReport:
    def __init__(self) -> None:
        self.total = 0
        self.per_category: dict[str, dict] = {}
        self.conflicts: list[dict] = []
        self.invalid: list[dict] = []
        self.issues: list[dict] = []
        self.reference: dict[str, int] = {"exact-name": 0, "fuzzy+anchor": 0,
                                          "identity+anchor": 0,
                                          "other": 0, "unmatched": 0}
        self.derived = 0
        self.source_distribution: dict[str, int] = {}
        self.unknown: list[dict] = []
        self.core_gaps: list[dict] = []
        # (category, vendor label) -> {count, sample product ids}: vendor
        # vocabulary that mapped to no schema field. This is the queue for
        # specs/labels.py, kept in the report so growth is evidence-driven.
        self.label_gaps: dict[tuple[str, str], dict] = {}
        # Vendor values an enum refused (vendor_struct.SCHEMA_MISSES).
        self.schema_misses: list[dict] = []

    # -- collection --------------------------------------------------------

    def add_product(self, *, product_id: str, category: str | None, specs: dict,
                    sources: dict, conflicts: list[dict], invalid: list[dict],
                    reference: dict, issues: list[dict],
                    label_gaps: list[dict] | None = None) -> None:
        self.total += 1
        category = category or ""
        bucket = self.per_category.setdefault(
            category, {"products": 0, "fields": {}, "tier0": 0, "core": {},
                       "source_distribution": {}, "derived": 0, "unknown": 0})

        bucket["products"] += 1
        if reference.get("matched"):
            bucket["tier0"] += 1
            method = reference.get("method") or "other"
            self.reference[method if method in self.reference else "other"] += 1
        else:
            self.reference["unmatched"] += 1

        invalid_fields = {str(item.get("field")) for item in invalid}
        issue_fields = {str(item.get("field")) for item in issues if item.get("field")}
        for field in schema.field_names(category):
            slot = bucket["fields"].setdefault(
                field, {"filled": 0, "null": 0, "tier0": 0,
                        "source_distribution": {}, "unknown_reasons": {}})
            source = sources.get(field)
            if specs.get(field) is None:
                slot["null"] += 1
                bucket["unknown"] += 1
                reason = ("invalid" if field in invalid_fields else
                          "consistency" if field in issue_fields else
                          "reference_unmatched" if not reference.get("matched")
                          else "no_source")
                slot["unknown_reasons"][reason] = (
                    slot["unknown_reasons"].get(reason, 0) + 1)
                self.unknown.append({"product_id": product_id, "category": category,
                                     "field": field, "reason": reason})
                if field in CORE_FIELDS:
                    self.core_gaps.append({"product_id": product_id,
                                           "category": category, "field": field,
                                           "reason": reason})
                continue
            slot["filled"] += 1
            source_group = ("derived" if str(source or "").startswith("derived:")
                            else source or "unknown")
            slot["source_distribution"][source_group] = (
                slot["source_distribution"].get(source_group, 0) + 1)
            bucket["source_distribution"][source_group] = (
                bucket["source_distribution"].get(source_group, 0) + 1)
            if source == "reference":
                slot["tier0"] += 1
            if str(source or "").startswith("derived"):
                self.derived += 1
                bucket["derived"] += 1
            self.source_distribution[source_group] = (
                self.source_distribution.get(source_group, 0) + 1)
        for field in CORE_FIELDS:
            if specs.get(field) is not None:
                bucket["core"][field] = bucket["core"].get(field, 0) + 1

        for gap in label_gaps or []:
            label = str(gap.get("label") or "").strip()
            if not label:
                continue
            slot = self.label_gaps.setdefault(
                (category, label),
                {"category": category, "label": label, "count": 0, "products": []})
            slot["count"] += int(gap.get("count") or 0)
            if len(slot["products"]) < 5 and product_id not in slot["products"]:
                slot["products"].append(product_id)

        for conflict in conflicts:
            self.conflicts.append({"product_id": product_id, "category": category,
                                   **conflict})
        for dropped in invalid:
            self.invalid.append({"product_id": product_id, "category": category,
                                 **dropped})
        for issue in issues:
            self.issues.append({"product_id": product_id, "category": category,
                                **issue})

    # -- output ------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "products": self.total,
            "categories": self.per_category,
            "reference": dict(self.reference),
            "derived": self.derived,
            "source_distribution": dict(self.source_distribution),
            "unknown": self.unknown,
            "core_gaps": self.core_gaps,
            "conflicts": self.conflicts,
            "invalid": self.invalid,
            "issues": self.issues,
            "label_gaps": sorted(self.label_gaps.values(),
                                 key=lambda slot: -slot["count"]),
            "schema_misses": self.schema_misses,
        }

    def core_coverage(self) -> dict[str, float]:
        """% of products per core field, across all categories."""
        totals: dict[str, int] = {}
        filled: dict[str, int] = {}
        for category, bucket in self.per_category.items():
            for field in CORE_FIELDS:
                if field not in schema.field_names(category):
                    continue
                totals[field] = totals.get(field, 0) + bucket["products"]
                filled[field] = filled.get(field, 0) + (
                    bucket.get("fields", {}).get(field, {}).get("filled", 0))
        return {field: (filled.get(field, 0) / totals[field])
                for field in totals if totals[field]}

    def print_summary(self) -> None:
        if not self.total:
            print("[specs] no products to report")
            return
        print(f"[specs] {self.total} products; reference matches: "
              f"{self.reference.get('exact-name', 0)} exact-name, "
              f"{self.reference.get('fuzzy+anchor', 0)} fuzzy+anchor, "
              f"{self.reference.get('identity+anchor', 0)} identity+anchor, "
              f"{self.reference.get('unmatched', 0)} none")
        for category in sorted(self.per_category):
            bucket = self.per_category[category]
            products = bucket["products"] or 1
            lines = []
            for name, slot in sorted(bucket["fields"].items()):
                percent = slot["filled"] * 100 // products
                if percent >= 60:
                    lines.append(f"{name}={percent}%")
            print(f"  {category:<14} n={bucket['products']:<5} "
                  f"ref={bucket['tier0'] * 100 // products:>3}% "
                  f"unknown={bucket.get('unknown', 0):<4} "
                  f"derived={bucket.get('derived', 0):<4} "
                  + " ".join(lines[:8]))
        core = self.core_coverage()
        if core:
            print("[specs] core compat coverage: " + "  ".join(
                f"{field}={value * 100:.0f}%" for field, value in sorted(core.items())))
        if self.label_gaps:
            top = sorted(self.label_gaps.values(), key=lambda slot: -slot["count"])[:8]
            print("[specs] unmapped vendor labels (candidates for specs/labels.py): "
                  + "  ".join(f"{slot['category']}:{slot['label']}={slot['count']}"
                              for slot in top))
        print(f"[specs] conflicts={len(self.conflicts)} "
              f"invalid={len(self.invalid)} issues={len(self.issues)} "
              f"unknown={len(self.unknown)} core_gaps={len(self.core_gaps)} "
              f"derived={self.derived}")


def _bare_value(payload):
    """Merge-conflict payloads carry provenance ({value, tier, source}); the
    QA page shows the value itself, so unwrap it."""
    if isinstance(payload, dict) and "value" in payload:
        return payload.get("value")
    return payload


# Name-like fields where a value that only adds words to the other ("ASETEK
# 510LC 120" vs "510LC 120", "ARGB | LCD" vs "ARGB") is the same answer in more
# detail, not a contradiction a human must settle.
_WORDY_FIELDS = frozenset({"model", "series", "lighting", "color"})


def _tokens(value) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", str(value).lower()))


def _wording_only(field, kept, dropped) -> bool:
    if field not in _WORDY_FIELDS or not isinstance(kept, str) or not isinstance(dropped, str):
        return False
    a, b = _tokens(kept), _tokens(dropped)
    return bool(a and b) and (a <= b or b <= a)


def _case_key(case: dict) -> str:
    return json.dumps([case.get("kind"), case.get("product_id"), case.get("field"),
                       case.get("kept"), case.get("dropped"), case.get("detail")],
                      sort_keys=True, ensure_ascii=False, default=str)


def case_id(case: dict) -> str:
    """The key `data/matching/qa_dismissed.json` stores a case under."""
    return f"{case.get('kind')}|{case.get('product_id')}|{case.get('field') or case.get('vendor') or ''}"


def qa_cases(report_dict: dict, limit: int | None = 200,
             per_category: int | None = None,
             dismissed: frozenset | set | None = None) -> list[dict]:
    """spec_conflict + core_gap cases for data/site/qa.json (public #/qa page).

    One case per distinct (product, field, kept, dropped): the merge records a
    conflict per losing fact, so one disagreement arrives once per source.
    `per_category` caps the merge conflicts of each category, so a cap cannot
    fill up with the alphabetically first category. `limit=None` returns every
    case; a finite `limit` cuts after the category sort. A case whose
    `case_id` is in `dismissed` is kept but flagged `dismissed`, and no cap
    counts it: the local QA tool still lists it (to reopen it), the public
    page and the counts skip it."""
    dismissed = dismissed or frozenset()
    cases: list[dict] = []
    seen: set[str] = set()
    taken: dict[str, int] = {}

    def add(case: dict) -> None:
        key = _case_key(case)
        if key in seen:
            return
        seen.add(key)
        cases.append(case)

    for conflict in report_dict.get("conflicts", []):
        kept, dropped = _bare_value(conflict.get("kept")), _bare_value(conflict.get("dropped"))
        if _wording_only(conflict.get("field"), kept, dropped):
            continue
        category = str(conflict.get("category") or "")
        case = {
            "kind": "spec_conflict",
            "product_id": conflict.get("product_id"),
            "category": conflict.get("category"),
            "vendor": "",
            "field": conflict.get("field"),
            "titles": [],
            "kept": kept,
            "dropped": dropped,
            "offers": [],
        }
        if _case_key(case) in seen:
            continue
        if case_id(case) in dismissed:
            add({**case, "dismissed": True})
            continue
        if per_category is not None and taken.get(category, 0) >= per_category:
            continue
        taken[category] = taken.get(category, 0) + 1
        add(case)
    for issue in report_dict.get("issues", []):
        if issue.get("kind") != "spec_conflict":
            continue
        case = {
            "kind": "spec_conflict",
            "product_id": issue.get("product_id"),
            "category": issue.get("category"),
            "vendor": "",
            "field": issue.get("field"),
            "titles": [],
            "kept": issue.get("kept"),
            "detail": issue.get("detail"),
            "offers": [],
            **({"rule": issue["rule"]} if issue.get("rule") else {}),
        }
        if case_id(case) in dismissed:
            case["dismissed"] = True
        add(case)

    # Core-compatibility gaps (plan todo #7): one case per product, listing
    # every missing core field. These are the products that cannot answer
    # "will it fit/work with the rest of my build" — the ones a human should
    # look at first, ahead of value conflicts.
    by_product: dict[tuple, dict] = {}
    for gap in report_dict.get("core_gaps", []):
        key = (str(gap.get("product_id") or ""), str(gap.get("category") or ""))
        slot = by_product.setdefault(key, {
            "kind": "core_gap",
            "product_id": gap.get("product_id"),
            "category": gap.get("category"),
            "vendor": "",
            "titles": [],
            "fields": [],
            "offers": [],
        })
        field = str(gap.get("field") or "")
        if field and field not in slot["fields"]:
            slot["fields"].append(field)
    for gap_case in by_product.values():
        if case_id(gap_case) in dismissed:
            gap_case["dismissed"] = True
        cases.append(gap_case)

    cases.sort(key=lambda c: (str(c.get("category") or ""),
                              str(c.get("product_id") or "")))
    return cases[:limit]
