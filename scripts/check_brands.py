"""Gate: one product, one maker; and every product names its brand (audit 2026-11-10 C, N).

C: a model code is only unique inside one maker. Antec F12/P14 and Arctic
F12/P14 are different fans, yet the identity tier joined them on the code.
`identity.brand_subgroups` now splits a code group by brand family (a
sub-brand maps to its maker: Lancool -> Lian Li, ROG -> ASUS); a part number
printed under two families keeps them together. Hard gate: no product's
offers hold two brand families (the chip vendor on a GPU is no brand).

N: 212 products had an empty brand although their merged specs named the
manufacturer. `normalize_and_match._fill_empty_brands` fills it. Budget gate:
the empty-brand count stays within EMPTY_BRAND_BUDGET.

    python scripts/check_brands.py --self-test
    python scripts/check_brands.py [--catalog data/catalog.json]
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper import identity  # noqa: E402
from scraper.normalize_and_match import _fill_empty_brands  # noqa: E402

# 212 before the fix, 0 after it: room for a few new makers, not a regression.
EMPTY_BRAND_BUDGET = 20


def self_test() -> list[str]:
    errors: list[str] = []
    for raw, want in {"LIAN-LI": "lianli", "Lancool": "lianli", "ROG": "asus",
                      "T-Force": "teamgroup", "Team Group": "teamgroup", "WD": "westerndigital",
                      "": None, None: None}.items():
        got = identity.brand_family(raw)
        if got != want:
            errors.append(f"brand_family({raw!r}) = {got!r}, want {want!r}")

    def row(key, brand, mpn=None):
        return {"listing_key": key, "brand": brand, "mpn": mpn}

    def keys(groups):
        return [sorted(e["listing_key"] for e in g) for g in groups]

    cases = [
        ("case_fan", [row("a", "Antec"), row("b", "Antec"), row("c", "Arctic"), row("d", None)],
         [["a", "b", "d"], ["c"]]),
        ("case_fan", [row("a", "Antec", "0-761345-75287-9"), row("c", "Arctic", "0-761345-75287-9")],
         [["a", "c"]]),
        ("gpu", [row("a", "PNY"), row("b", "NVIDIA")], [["a", "b"]]),
        ("case", [row("a", "Lian Li"), row("b", "Lancool")], [["a", "b"]]),
        ("motherboard", [row("a", "ASUS"), row("b", "ROG"), row("c", "MSI")], [["a", "b"], ["c"]]),
    ]
    for category, rows, want in cases:
        got = keys(identity.brand_subgroups(category, rows))
        if got != want:
            errors.append(f"brand_subgroups({category}, {[r['brand'] for r in rows]}) = {got}, want {want}")
    if not identity.brands_conflict("case_fan", [row("a", "Antec")], [row("b", "Arctic")]):
        errors.append("brands_conflict(Antec, Arctic) is False")
    if identity.brands_conflict("case_fan", [row("a", "Antec")], [row("b", None)]):
        errors.append("brands_conflict(Antec, no brand) is True")

    products = [
        {"product_id": "x1", "brand": "TeamGroup", "canonical_name": "TeamGroup T-Force"},
        {"product_id": "x2", "brand": "TeamGroup", "canonical_name": "TeamGroup Elite"},
        {"product_id": "x3", "brand": "Crucial", "canonical_name": "Crucial P3"},
        {"product_id": "x4", "brand": "Crucial", "canonical_name": "Crucial T500"},
        {"product_id": "m", "brand": "", "specs": {"manufacturer": "Team Group"},
         "canonical_name": "Crucial-compatible 64GB kit"},
        {"product_id": "n", "brand": None, "specs": {}, "canonical_name": "Crucial P5 Plus 1TB"},
        {"product_id": "t", "brand": "", "specs": {}, "canonical_name": "TeamGroup vs Crucial bundle"},
        {"product_id": "j", "brand": "", "specs": {"manufacturer": "Jonsbo"}, "canonical_name": "Jonsbo D41"},
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        _fill_empty_brands(products)
    got = {p["product_id"]: p.get("brand") for p in products[4:]}
    want = {"m": "TeamGroup", "n": "Crucial", "t": "", "j": "Jonsbo"}
    if got != want:
        errors.append(f"_fill_empty_brands = {got}, want {want}")
    return errors


def check_catalog(catalog: dict) -> list[str]:
    errors: list[str] = []
    mixed = []
    for product in catalog.get("products") or []:
        if product.get("matched_by") == "manual":
            continue
        groups = identity.brand_subgroups(product.get("category"), product.get("offers") or [])
        if len(groups) > 1:
            mixed.append(product)
    for product in mixed[:20]:
        brands = sorted({str(o.get("brand")) for o in product.get("offers") or [] if o.get("brand")})
        errors.append(f"C: {product.get('product_id')} joins two makers: {', '.join(brands)}")
    empty = [p for p in catalog.get("products") or [] if not str(p.get("brand") or "").strip()]
    if len(empty) > EMPTY_BRAND_BUDGET:
        errors.append(f"N: {len(empty)} products have no brand (budget {EMPTY_BRAND_BUDGET}), "
                      f"e.g. {', '.join(str(p.get('product_id')) for p in empty[:5])}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.json"))
    args = parser.parse_args()

    errors = self_test()
    if errors:
        print("[brands] FAIL - self-test")
        for error in errors:
            print(f"  - {error}")
        return 1
    if args.self_test:
        print("[brands] self-test pass")
        return 0

    path = Path(args.catalog)
    if not path.exists():
        print(f"[error] {path} not found - run the normalizer first", file=sys.stderr)
        return 1
    catalog = json.loads(path.read_text(encoding="utf-8"))
    errors = check_catalog(catalog)
    if errors:
        print(f"[brands] FAIL - {len(errors)} problem(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    empty = sum(1 for p in catalog.get("products") or [] if not str(p.get("brand") or "").strip())
    print(f"[brands] pass - {len(catalog.get('products') or [])} products, one maker each; "
          f"{empty} without a brand (budget {EMPTY_BRAND_BUDGET})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
