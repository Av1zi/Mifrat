"""Audit the local image corpus: what we actually hold, per vendor and per
category, and how good it is.

Why this exists (Sep 2026, "transparent photos + best-photo picking"):

The site shows the *first* offer that carries any image URL (see
matching.py's product build loop), with no look at resolution, aspect, or
which vendor the photo came from. Two visible symptoms followed: covers
that are plainly the wrong shot (a motherboard photographed from the side
in a wide banner strip) and cards that render vendor JPEGs as hard white
rectangles in dark mode.

Picking a better photo requires knowing what the alternatives look like
today, and the picker needs a *calibrated* per-category vendor priority
table rather than a guess. This script is that measurement:

1. Filesystem side — every cover (data/images/<vendor>/<sku>.jpg, thumbs
   excluded) is measured once with Pillow: long edge, aspect ratio, and the
   share of border pixels that are near-white. Long edge tells us which
   vendors hand us a real full-size shot vs. a listing thumbnail
   (download_images never upscales, so the on-disk size IS the source
   size). Border-white share is the matting worklist: near-white borders
   are photos that will matte cleanly; a large *non*-white border share on
   an extreme aspect ratio is usually a promo banner, not a product shot.
2. Catalog side — every product's currently-chosen image is resolved
   through the same rule site_data._resolve_image uses, then joined to the
   filesystem metrics and grouped by category. This is the table that says
   "for category X, vendor A currently wins, and vendor B's photos are
   both bigger and cleaner" — i.e. the evidence for the per-category
   vendor priority table in data/matching/image_vendor_priority.json.

Read-only: writes nothing except an optional --json path. Prints a report
and a suggested priority JSON for human review; committing that JSON is a
deliberate decision, never automatic.

Usage:
    python scripts/audit_images.py
    python scripts/audit_images.py --json tmp/image_audit.json
    python scripts/audit_images.py --sample 50        # verbose examples
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

IMAGES_DIR = REPO_ROOT / "data" / "images"
CATALOG_PATH = REPO_ROOT / "data" / "catalog.json"
THUMB_SUBDIR = "thumbs"

# A pixel counts as "background white" at or above this on every channel.
# 240 rather than 255: vendor JPEGs compress a white studio backdrop to
# 250-254 near edges, never a flat 255.
WHITE_CUTOFF = 240

# Aspect (long/short) above which a photo is a strip rather than a product
# shot — the "motherboard side view" symptom. 2.2 is deliberately loose:
# real tower cases sit near 2.0 legitimately.
PANO_ASPECT = 2.2

# Long-edge buckets. 800 is download_images.MAX_DIMENSION, so "800" means
# the vendor handed us something at least that big and we downscaled it.
RES_BUCKETS = ((400, "lt400"), (600, "400_599"), (800, "600_799"))


def _iter_covers():
    """Yield (vendor, relpath, Path) for every full-size cover on disk."""
    if not IMAGES_DIR.is_dir():
        return
    for vendor_dir in sorted(p for p in IMAGES_DIR.iterdir() if p.is_dir()):
        for path in sorted(vendor_dir.rglob("*.jpg")):
            if THUMB_SUBDIR in path.relative_to(vendor_dir).parts:
                continue
            yield vendor_dir.name, str(path.relative_to(vendor_dir)), path


def _border_white_share(img: Image.Image) -> float:
    """Share of border pixels that are near-white.

    Sampled rather than exhaustive: every 3rd pixel along each edge is
    plenty for a share estimate and keeps 7k images to a few seconds.
    """
    width, height = img.size
    if width < 4 or height < 4:
        return 0.0
    rgb = img.convert("RGB")
    pixels = rgb.load()
    step_x = max(1, width // 120)
    step_y = max(1, height // 120)
    white = total = 0
    for x in range(0, width, step_x):
        for y in (0, 1, height - 2, height - 1):
            r, g, b = pixels[x, y]
            total += 1
            if r >= WHITE_CUTOFF and g >= WHITE_CUTOFF and b >= WHITE_CUTOFF:
                white += 1
    for y in range(0, height, step_y):
        for x in (0, 1, width - 2, width - 1):
            r, g, b = pixels[x, y]
            total += 1
            if r >= WHITE_CUTOFF and g >= WHITE_CUTOFF and b >= WHITE_CUTOFF:
                white += 1
    return (white / total) if total else 0.0


def measure(path: Path) -> dict | None:
    """Resolution/aspect/border-white metrics for one cover, or None."""
    try:
        with Image.open(path) as img:
            width, height = img.size
            white = _border_white_share(img)
    except Exception as exc:  # unreadable file is itself a finding
        print(f"  [warn] unreadable {path}: {exc}")
        return None
    long_edge = max(width, height)
    short_edge = max(1, min(width, height))
    return {
        "w": width,
        "h": height,
        "long_edge": long_edge,
        "aspect": round(long_edge / short_edge, 2),
        "white_border": round(white, 3),
        "bytes": path.stat().st_size,
    }


def _bucket(long_edge: int) -> str:
    for limit, name in RES_BUCKETS:
        if long_edge < limit:
            return name
    return "800_plus"


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"files": 0}
    longs = sorted(r["long_edge"] for r in rows)
    return {
        "files": len(rows),
        "mb": round(sum(r["bytes"] for r in rows) / 1_048_576, 1),
        "mean_edge": int(statistics.mean(longs)),
        "median_edge": int(statistics.median(longs)),
        "mean_kb": round(sum(r["bytes"] for r in rows) / len(rows) / 1024, 1),
        "share_lt400": round(sum(1 for r in rows if r["long_edge"] < 400) / len(rows), 3),
        "share_800plus": round(sum(1 for r in rows if r["long_edge"] >= 800) / len(rows), 3),
        "share_pano": round(sum(1 for r in rows if r["aspect"] > PANO_ASPECT) / len(rows), 3),
        "mean_white_border": round(statistics.mean(r["white_border"] for r in rows), 3),
    }


def _print_table(title: str, rows: dict[str, dict]) -> None:
    print(f"\n{title}")
    header = ("key", "files", "MB", "mean_edge", "share<400", "share800+",
              "pano", "white_border")
    print("  {:22s} {:>6s} {:>6s} {:>9s} {:>9s} {:>9s} {:>6s} {:>12s}".format(*header))
    for key in sorted(rows):
        s = rows[key]
        if not s.get("files"):
            continue
        print("  {:22s} {:>6d} {:>6.1f} {:>9d} {:>9.2f} {:>9.2f} {:>6.2f} {:>12.2f}".format(
            key[:22], s["files"], s["mb"], s["mean_edge"],
            s["share_lt400"], s["share_800plus"], s["share_pano"],
            s["mean_white_border"],
        ))


def catalog_report(covers: dict[tuple[str, str], dict], sample: int) -> dict:
    """Join the catalog's chosen images to the filesystem metrics."""
    if not CATALOG_PATH.is_file():
        print(f"[audit] no {CATALOG_PATH} — skipping the catalog half")
        return {}

    from scraper.site_data import _resolve_image

    with CATALOG_PATH.open(encoding="utf-8") as f:
        catalog = json.load(f)

    from scraper.site_data import _local_image_path

    by_category: dict[str, dict] = {}
    no_image = 0
    image_raw_only = 0
    per_product: list[dict] = []

    for product in catalog.get("products", []):
        try:
            image, _thumb = _resolve_image(product, product.get("offers") or [])
        except Exception:
            image = None
        if not image:
            no_image += 1
            if product.get("image_url"):
                image_raw_only += 1
            continue

        # Resolve which offer/vendor the chosen file came from, the same way
        # _resolve_image did: match the returned URL back to an offer.
        vendor = sku = None
        for offer in product.get("offers") or []:
            local = _local_image_path(offer.get("vendor_id"),
                                      str(offer.get("vendor_sku") or ""))
            if local == image:
                vendor = offer.get("vendor_id")
                sku = str(offer.get("vendor_sku") or "")
                break
        vendor_folder = "onepc" if vendor in ("1pc", "onepc") else (vendor or "?")
        metrics = covers.get((vendor_folder, f"{_stem(sku)}.jpg"))
        category = str(product.get("category") or "?")
        bucket = by_category.setdefault(category, {"products": 0, "vendors": {}})
        bucket["products"] += 1
        vend = bucket["vendors"].setdefault(vendor_folder,
                                            {"count": 0, "edges": [], "white": [],
                                             "pano": 0, "lt400": 0})
        vend["count"] += 1
        if metrics:
            vend["edges"].append(metrics["long_edge"])
            vend["white"].append(metrics["white_border"])
            vend["pano"] += 1 if metrics["aspect"] > PANO_ASPECT else 0
            vend["lt400"] += 1 if metrics["long_edge"] < 400 else 0
        per_product.append({
            "product_id": product.get("product_id"),
            "category": category,
            "vendor": vendor_folder,
            "sku": sku,
            "image": image,
            **({"long_edge": metrics["long_edge"], "aspect": metrics["aspect"],
                "white_border": metrics["white_border"]} if metrics else {}),
        })

    print(f"\n[audit] catalog: {len(per_product)} products with a local image, "
          f"{no_image} without "
          f"({image_raw_only} of those still carry a non-resolvable image_url)")

    print("\nChosen-image quality by category x vendor "
          "(edge = mean long edge, white = mean border-white share)")
    header = ("category", "vendor", "count", "mean_edge", "lt400", "pano", "white")
    print("  {:20s} {:9s} {:>6s} {:>9s} {:>6s} {:>6s} {:>6s}".format(*header))
    for category in sorted(by_category):
        for vendor in sorted(by_category[category]["vendors"]):
            v = by_category[category]["vendors"][vendor]
            edges = v["edges"]
            print("  {:20s} {:9s} {:>6d} {:>9d} {:>6d} {:>6d} {:>6.2f}".format(
                category[:20], vendor, v["count"],
                int(statistics.mean(edges)) if edges else 0,
                v["lt400"], v["pano"],
                statistics.mean(v["white"]) if v["white"] else 0.0,
            ))

    if sample:
        print(f"\n[audit] {sample} chosen images with the widest aspect "
              f"(the strip/banner suspects):")
        for row in sorted((r for r in per_product if "aspect" in r),
                          key=lambda r: -r["aspect"])[:sample]:
            print("  {category:14s} {vendor:8s} aspect={aspect:4.2f} "
                  "edge={long_edge:4d} white={white_border:4.2f} {image}".format(**row))
    return {"by_category": by_category, "per_product": per_product,
            "no_image": no_image}


def _stem(sku: str) -> str:
    from scraper.site_data import _safe_image_stem
    return _safe_image_stem(sku)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_out", default=None,
                        help="write the full report as JSON here")
    parser.add_argument("--sample", type=int, default=0,
                        help="also print the N most extreme-aspect chosen images")
    parser.add_argument("--limit", type=int, default=0,
                        help="only measure the first N covers (fast smoke run)")
    args = parser.parse_args()

    if not IMAGES_DIR.is_dir():
        print(f"[audit] no {IMAGES_DIR} — nothing to measure")
        return 1

    covers: dict[tuple[str, str], dict] = {}
    by_vendor: dict[str, list[dict]] = {}
    for vendor, relpath, path in _iter_covers():
        if args.limit and len(covers) >= args.limit:
            break
        metrics = measure(path)
        if metrics is None:
            continue
        covers[(vendor, relpath)] = metrics
        by_vendor.setdefault(vendor, []).append(metrics)

    total_rows = [m for rows in by_vendor.values() for m in rows]
    print(f"[audit] measured {len(total_rows)} covers under {IMAGES_DIR.relative_to(REPO_ROOT)}")
    _print_table("Covers by vendor", {v: summarize(r) for v, r in by_vendor.items()})
    _print_table("Covers overall", {"ALL": summarize(total_rows)})

    print("\nResolution mix (share of covers per long-edge bucket)")
    print("  {:10s} {:>7s} {:>7s} {:>7s} {:>7s}".format(
        "vendor", "<400", "400-599", "600-799", "800+"))
    for vendor in sorted(by_vendor):
        rows = by_vendor[vendor]
        counts = {name: 0 for _l, name in RES_BUCKETS}
        counts["800_plus"] = 0
        for row in rows:
            counts[_bucket(row["long_edge"])] += 1
        print("  {:10s} {:>7.2f} {:>7.2f} {:>7.2f} {:>7.2f}".format(
            vendor, counts["lt400"] / len(rows), counts["400_599"] / len(rows),
            counts["600_799"] / len(rows), counts["800_plus"] / len(rows)))

    catalog = catalog_report(covers, args.sample)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump({
                "covers": {f"{v}/{k}": m for (v, k), m in covers.items()},
                "by_vendor": {v: summarize(r) for v, r in by_vendor.items()},
                "overall": summarize(total_rows),
                "catalog": catalog,
            }, f, ensure_ascii=False)
        print(f"\n[audit] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
