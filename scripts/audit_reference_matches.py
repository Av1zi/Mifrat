"""Audit the Tier-0 reference join (pcpartdb) against our own vendor data.

The reference tier wins every field it has, so a wrong product->row link
silently overwrites correct vendor values (Oct 2026: the white Antec
CSK750DC-W linked to PCPartPicker's plain black "Antec CSK" 750W and shipped
as "...Black"). This re-runs `match_reference_row` for every catalog product
and flags links that disagree with what the offers themselves say:

- `missing_tokens`: distinctive model tokens in our name the row name lacks
  ("dc" for CSK DC vs CSK) - the usual sign of a sibling model;
- `conflicts`: identity fields where the row contradicts an offer's own
  listing-level value (color, efficiency, modular, size, socket, ...).

Runs the normalize in memory (writes nothing but --out; needs data/raw/ and
data/pcpartdb/index.json):
    python scripts/audit_reference_matches.py [--out tmp/reference_audit.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs.resolvers import reference  # noqa: E402

# Fields that identify WHICH product a row is; a disagreement here means the
# link is wrong, not that one source is more precise than the other.
IDENTITY_FIELDS = (
    "color", "efficiency", "modular", "wattage_w", "size_mm", "socket",
    "chipset", "form_factor", "capacity_gb", "memory_type", "total_gb",
    "speed_mhz", "radiator_size_mm", "memory_gb", "core_count",
)


def _norm(value) -> str:
    return " ".join(str(value).lower().replace("/", " ").replace("-", " ").split())


def _color_words(value) -> set[str]:
    return {w for w in _norm(value).split() if w.isalpha()}


def _disagree(field: str, ours, theirs) -> bool:
    if ours is None or theirs is None:
        return False
    if field == "color":
        # "Black / Yellow" vs "Black" agree; "Black / Yellow" vs "White" do not.
        a, b = _color_words(ours), _color_words(theirs)
        return bool(a) and bool(b) and not (a & b)
    if isinstance(ours, (int, float)) and isinstance(theirs, (int, float)):
        return abs(float(ours) - float(theirs)) > 1e-6
    if isinstance(ours, list) or isinstance(theirs, list):
        return False
    a, b = _norm(ours), _norm(theirs)
    return a not in b and b not in a


def _capture_matches():
    """Run the real normalize in memory, recording every Tier-0 lookup.

    The catalog on disk only has POST-merge state (reference values already
    folded into specs, names rebuilt), so the join has to be observed while
    build_product_specs runs: same query, same provisional anchors.
    """
    from datetime import datetime, timezone

    from scraper import normalize_and_match
    from scraper.specs import build

    seen: dict[str, dict] = {}
    current: dict = {}
    real_query = build.reference_query
    real_match = reference.match_reference_row

    def query_spy(product, specs, category):
        current["product"] = product
        current["known"] = dict(specs)
        return real_query(product, specs, category)

    def match_spy(category, query, known):
        result = real_match(category, query, known)
        product = current.get("product") or {}
        seen[str(product.get("product_id"))] = {
            "query": query, "known": current.get("known") or {}, "match": result}
        return result

    build.reference_query = query_spy
    reference.match_reference_row = match_spy
    try:
        catalog, _queue, _report = normalize_and_match.build_catalog(
            datetime.now(timezone.utc))
    finally:
        build.reference_query = real_query
        reference.match_reference_row = real_match
    return catalog["products"], seen


def audit(products: list[dict], seen: dict[str, dict]) -> dict:
    rows = []
    by_method: Counter = Counter()
    flagged_by_method: Counter = Counter()
    for product in products:
        category = product.get("category")
        record = seen.get(str(product.get("product_id")))
        if not record or record["match"] is None:
            by_method["unmatched"] += 1
            continue
        row, score, method = record["match"]
        query, known = record["query"], record["known"]
        by_method[method] += 1
        row_specs = row.get("specs") or {}
        row_tokens = reference._token_set(row.get("name") or "")
        residual = reference._residual_query(category, query, known)
        missing = sorted(reference._distinctive_tokens(residual) - row_tokens)

        conflicts = {}
        for offer in product.get("offers") or []:
            attrs = offer.get("attributes") or {}
            for field in IDENTITY_FIELDS:
                if _disagree(field, attrs.get(field), row_specs.get(field)):
                    conflicts.setdefault(field, {
                        "ours": attrs.get(field), "row": row_specs.get(field),
                        "vendor": offer.get("vendor_id")})
        if missing or conflicts:
            flagged_by_method[method] += 1
            rows.append({
                "product_id": product.get("product_id"),
                "category": category,
                "query": query,
                "row": row.get("name"),
                "method": method,
                "score": round(float(score or 0), 1),
                "missing_tokens": missing,
                "conflicts": conflicts,
            })
    per_category: dict[str, int] = defaultdict(int)
    for row in rows:
        per_category[row["category"]] += 1
    return {
        "matched_by_method": dict(by_method),
        "flagged_by_method": dict(flagged_by_method),
        "flagged_by_category": dict(sorted(per_category.items())),
        "flagged": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "tmp" / "reference_audit.json"))
    parser.add_argument("--show", type=int, default=15,
                        help="print this many flagged links")
    args = parser.parse_args()

    products, seen = _capture_matches()
    result = audit(products, seen)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print("matched:", result["matched_by_method"])
    print("flagged:", result["flagged_by_method"])
    print("flagged per category:", result["flagged_by_category"])
    for row in result["flagged"][: args.show]:
        print(f"- [{row['method']}] {row['query']!r} -> {row['row']!r} "
              f"missing={row['missing_tokens']} conflicts={list(row['conflicts'])}")
    print(f"full list: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
