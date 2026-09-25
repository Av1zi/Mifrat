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
                                          "other": 0, "unmatched": 0}
        self.derived = 0
        self.source_distribution: dict[str, int] = {}
        self.unknown: list[dict] = []
        self.core_gaps: list[dict] = []

    # -- collection --------------------------------------------------------

    def add_product(self, *, product_id: str, category: str | None, specs: dict,
                    sources: dict, conflicts: list[dict], invalid: list[dict],
                    reference: dict, issues: list[dict]) -> None:
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


def qa_cases(report_dict: dict, limit: int = 200) -> list[dict]:
    """spec_conflict cases for data/site/qa.json (public #/qa page)."""
    cases: list[dict] = []
    for conflict in report_dict.get("conflicts", []):
        cases.append({
            "kind": "spec_conflict",
            "product_id": conflict.get("product_id"),
            "category": conflict.get("category"),
            "vendor": "",
            "field": conflict.get("field"),
            "titles": [],
            "kept": _bare_value(conflict.get("kept")),
            "dropped": _bare_value(conflict.get("dropped")),
            "offers": [],
        })
    for issue in report_dict.get("issues", []):
        if issue.get("kind") != "spec_conflict":
            continue
        cases.append({
            "kind": "spec_conflict",
            "product_id": issue.get("product_id"),
            "category": issue.get("category"),
            "vendor": "",
            "field": issue.get("field"),
            "titles": [],
            "kept": issue.get("kept"),
            "detail": issue.get("detail"),
            "offers": [],
        })
    cases.sort(key=lambda c: (str(c.get("category") or ""),
                              str(c.get("product_id") or "")))
    return cases[:limit]
