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
import re
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
                      # Review 2 (2026-11-12) families and two-name strings.
                      "Micron": "crucial", "Crucial": "crucial", "Hynix": "skhynix",
                      "SK Hynix": "skhynix", "Kingston FURY": "kingston", "Toshiba": "kioxia",
                      "Kioxia": "kioxia", "Crucial by Micron": "crucial",
                      "KIOXIA (Toshiba)": "kioxia",
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
        ("motherboard", [row("a", "ASUS"), row("b", "AMD")], [["a", "b"]]),
        ("memory", [row("a", "Crucial"), row("b", "Micron")], [["a", "b"]]),
        ("storage", [row("a", "Toshiba"), row("b", "Kioxia")], [["a", "b"]]),
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
    # A chip maker builds the chip, not the board or card (review 2,
    # 2026-11-12): its `manufacturer` falls back to the name's brand.
    products += [
        {"product_id": "a1", "brand": "ASUS", "category": "motherboard", "canonical_name": "ASUS Prime"},
        {"product_id": "a2", "brand": "ASUS", "category": "motherboard", "canonical_name": "ASUS TUF"},
        {"product_id": "p1", "brand": "PNY", "category": "gpu", "canonical_name": "PNY RTX 5060"},
        {"product_id": "p2", "brand": "PNY", "category": "gpu", "canonical_name": "PNY RTX 5070"},
        {"product_id": "mb", "brand": "", "category": "motherboard",
         "specs": {"manufacturer": "AMD"}, "canonical_name": "ASUS ROG Crosshair X870E Hero"},
        {"product_id": "gp", "brand": "", "category": "gpu",
         "specs": {"manufacturer": "NVIDIA"}, "canonical_name": "PNY GeForce RTX 5070 Ti"},
        {"product_id": "mb2", "brand": "", "category": "motherboard",
         "specs": {"manufacturer": "Intel"}, "canonical_name": "Z890 board"},
        {"product_id": "cpu", "brand": "", "category": "cpu",
         "specs": {"manufacturer": "AMD"}, "canonical_name": "Ryzen 7 9700X"},
        {"product_id": "ref", "brand": "", "category": "gpu",
         "specs": {"manufacturer": "NVIDIA"}, "canonical_name": "NVIDIA RTX PRO 4000 Blackwell"},
        {"product_id": "pnyb", "brand": "NVIDIA", "category": "gpu", "canonical_name": "RTX 5060",
         "offers": [{"title_raw": "כרטיס מסך NVIDIA GeForce RTX 5060"},
                    {"title_raw": "כרטיס מסך PNY RTX 5060 OC Dual Fan 8GB"}]},
        {"product_id": "nv", "brand": "NVIDIA", "category": "gpu", "canonical_name": "RTX A2000",
         "offers": [{"title_raw": "כרטיס מסך NVIDIA RTX A2000"}]},
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        _fill_empty_brands(products)
    got = {p["product_id"]: p.get("brand") for p in products
           if p["product_id"] in ("m", "n", "t", "j", "mb", "gp", "mb2", "cpu", "ref", "pnyb", "nv")}
    want = {"m": "TeamGroup", "n": "Crucial", "t": "", "j": "Jonsbo",
            "mb": "ASUS", "gp": "PNY", "mb2": "", "cpu": "AMD", "ref": "NVIDIA",
            "pnyb": "PNY", "nv": "NVIDIA"}
    if chip_brand_partners({"products": products}):
        errors.append(f"chip_brand_partners after the fill: {chip_brand_partners({'products': products})}")
    if got != want:
        errors.append(f"_fill_empty_brands = {got}, want {want}")
    return errors


def chip_brand_partners(catalog: dict) -> list[str]:
    """Board/card products branded with the chip maker while their own titles
    name a board partner from the catalog ("MSI NVIDIA GeForce RTX 5060 Ti"
    branded NVIDIA). A chip maker is the brand only of its own reference /
    workstation cards, whose titles name no partner (NVIDIA RTX PRO 4000)."""
    products = catalog.get("products") or []
    counts: dict[str, int] = {}
    for p in products:
        brand = str(p.get("brand") or "").strip()
        if brand and identity.brand_family(brand) not in identity.CHIP_MAKERS:
            counts[brand] = counts.get(brand, 0) + 1
    partners = sorted({b for b, n in counts.items() if n >= 2 and len(b) >= 3}, key=len, reverse=True)
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(b) for b in partners)
                         + r")(?![A-Za-z0-9])", re.I) if partners else None
    out = []
    for p in products:
        if p.get("category") not in identity.BOARD_PARTNER_CATEGORIES or pattern is None:
            continue
        if identity.brand_family(p.get("brand")) not in identity.CHIP_MAKERS:
            continue
        named = {m.group(1).lower() for o in p.get("offers") or []
                 for m in pattern.finditer(str(o.get("title_raw") or ""))}
        named = {n for n in named if identity.brand_family(n) not in identity.CHIP_MAKERS}
        if named:
            out.append(f"{p.get('product_id')} ({p.get('brand')}; titles name {', '.join(sorted(named))})")
    return out


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
    chip_brand = chip_brand_partners(catalog)
    if chip_brand:
        errors.append(f"N: {len(chip_brand)} board/card product(s) branded with the chip maker "
                      f"while their titles name the partner, e.g. {'; '.join(chip_brand[:5])}")
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
