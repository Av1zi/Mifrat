"""Gate: the built site JSON must resolve a local image for nearly every product.

`scraper/site_data.py::_resolve_image` only returns a same-origin
`/images/...` path when the scraped cover actually exists on disk, and the
frontend renders initials for a product with no image. A run that silently
drops a lot of covers (a chooser flip to a pruned file, a vendor 404 wave,
a download job that didn't run) would ship a site full of placeholder tiles.
This fails the build when more than MAX_MISSING of products lack an image.

Run: python scripts/check_site_images.py [--report]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "data" / "site"

# A handful of products have no vendor photo at all (404s) and correctly show
# the initials placeholder; 2% leaves room for those without hiding a real
# regression (the corpus normally resolves >99%).
MAX_MISSING = 0.02

SKIP_FILES = {"meta.json", "qa.json", "index.json", "spec_report.json"}

# KSP covers sit behind a Cloudflare edge that 403s datacenter IPs, so CI can
# never fetch them; the Nano backfills them (`download_images --from-catalog
# --vendor ksp`). KSP-only products without a cover are reported separately
# and held to their own, looser budget instead of eating the cloud budget.
DEFERRED_VENDOR = "ksp"
MAX_DEFERRED = 0.15


def _ksp_only(product: dict) -> bool:
    vendors = {o.get("vendor") for o in product.get("offers") or []}
    return vendors == {DEFERRED_VENDOR}


def scan() -> dict:
    result = {"categories": 0, "products": 0, "with_image": 0, "missing": [],
              "deferred": [], "deferred_total": 0}
    if not SITE_DIR.is_dir():
        return result
    for path in sorted(SITE_DIR.glob("*.json")):
        if path.name in SKIP_FILES:
            continue
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        result["categories"] += 1
        for product in items:
            ksp_only = _ksp_only(product)
            if ksp_only:
                result["deferred_total"] += 1
            if product.get("image"):
                result["products"] += 1
                result["with_image"] += 1
            elif ksp_only:
                result["deferred"].append(f"{path.stem}/{product.get('id')}")
            else:
                result["products"] += 1
                result["missing"].append(
                    f"{path.stem}/{product.get('id')}"
                )
    return result


def main() -> int:
    report = "--report" in sys.argv
    r = scan()
    total = r["products"]
    if not total:
        print("[site-images] no site data found (run the normalizer first)")
        return 0
    missing_share = (total - r["with_image"]) / total
    print(
        f"[site-images] {r['with_image']}/{total} products have a local image "
        f"({r['categories']} categories, {missing_share:.1%} missing)"
    )
    deferred = len(r["deferred"])
    if deferred:
        share = deferred / max(1, r["deferred_total"])
        print(f"[site-images] {deferred} KSP-only products wait for the Nano "
              f"backfill ({share:.1%} of {r['deferred_total']}; budget "
              f"{MAX_DEFERRED:.0%}); not counted above")
        if share > MAX_DEFERRED:
            print("[site-images] FAIL: too many KSP covers missing; run on the "
                  "Nano: python -m scraper.download_images --from-catalog "
                  "--vendor ksp")
            return 1
    if missing_share > MAX_MISSING:
        print(f"[site-images] FAIL: {missing_share:.1%} of products lack a local "
              f"image (budget {MAX_MISSING:.0%})")
        for item in r["missing"][:15]:
            print(f"  - {item}")
        if len(r["missing"]) > 15:
            print(f"  ... {len(r['missing']) - 15} more")
        print("  backfill: python -m scraper.download_images --from-catalog")
        return 1
    if report and r["missing"]:
        print(f"  {len(r['missing'])} without an image: {r['missing'][:8]}")
    print("[site-images] pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
