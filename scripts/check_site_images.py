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


def scan() -> dict:
    result = {"categories": 0, "products": 0, "with_image": 0, "missing": []}
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
            result["products"] += 1
            if product.get("image"):
                result["with_image"] += 1
            else:
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
