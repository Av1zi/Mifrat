"""
Transparent product covers: matte every downloaded JPEG to a .webp with an
alpha background.

Why this exists (Sep 2026, "transparent photos"):

The audit (scripts/audit_images.py) measured the near-white border share of
all 7,364 covers: 0.94 on average, 0.99 for 1PC. In other words almost every
vendor photo is a product floating on a white studio backdrop, and the site
rendered that white rectangle as-is on grey/blue/dark cards — the "white box"
symptom, worst in dark mode. Recoloring the card background does nothing (the
white is IN the file); the file needs a real alpha channel.

So: one pass, one output per cover —

    data/images/<vendor>/<sku>.jpg        source of truth (kept forever)
    data/images/<vendor>/<sku>.webp       transparent render, ~40% smaller
    data/images/<vendor>/thumbs/<sku>.webp  same, 128px list variant

The .jpg is deliberately NOT replaced: matting can chew a white-on-white
product (white GPU shroud, white case, a cooler's white fan blades), and the
original is the only way back. site_data._local_image_path prefers .webp and
falls back to .jpg, so a cover with no render yet simply behaves as before.
data/images/keep_jpg.txt is the escape hatch for the handful of covers where
the matte is worse than the white box — a SKU listed there is never rendered.

Idempotency is file mtime, not a manifest: a cover is skipped when its .webp
exists and is newer than the .jpg it came from. That means the pass is safe to
re-run at any time, and the upgrade pass (download_images --upgrade) only has
to delete the stale .webp for it to be regenerated.

Tool choice: rembg with the isnet-general-use model, onnxruntime CPU. No API
keys, no network after the first model download (~170MB, cached in ~/.u2net),
good enough on studio shots, and it runs inside GitHub Actions. Rejected:
white flood-fill (destroys white products), paid removal APIs (would put a
credential in the repo), client-side removal (bundle size + CPU per visitor).

Usage:
    python -m scraper.process_images --limit 100        # newest 100 needs
    python -m scraper.process_images --vendor tms        # only one vendor
    python -m scraper.process_images --dry-run           # plan only
    python -m scraper.process_images data/images/tms/X.jpg   # single file
    python -m scraper.process_images --force --vendor tms    # redo all

The model weights live outside the repo (~/.u2net); CI caches that directory
so a cold runner doesn't re-download them on every run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

try:
    from scraper.image_score import TILE_EDGE  # noqa: F401  (kept for callers)
except ImportError:  # pragma: no cover - script-path invocation
    try:
        from image_score import TILE_EDGE  # type: ignore[no-redef]  # noqa: F401
    except ImportError:
        TILE_EDGE = 300

try:
    from rembg import new_session, remove
except ImportError:  # optional dependency — see requirements-images.txt
    new_session = None
    remove = None

IMAGES_DIR = Path("data/images")
KEEP_JPG_FILE = IMAGES_DIR / "keep_jpg.txt"
THUMB_SUBDIR = "thumbs"

# Same long edge as download_images.MAX_DIMENSION: the render replaces the
# JPEG one-for-one, so it must not be a different size class.
MAX_DIMENSION = 800
WEBP_QUALITY = 85
WEBP_METHOD = 4          # 4 = a bit slower than 0, visibly smaller output
THUMB_MAX_DIMENSION = 128
THUMB_QUALITY = 70

# isnet-general-use is the best general product-shot model rembg ships;
# u2net keeps more of the background on glossy/reflective parts.
MODEL_NAME = "isnet-general-use"

# Below this share of removed pixels the matte did nothing (or ate the whole
# frame); such a cover is still written (smaller bytes) but reported as
# "kept opaque" so the QA eye goes to the right files.
MIN_REMOVED_SHARE = 0.02

# A mask that collapses to a speck is a failed matte, not a tight crop.
MIN_KEPT_AREA_SHARE = 0.05

# Padding kept around the product after cropping to the alpha bounding box,
# as a share of the shorter side (plus a couple of pixels so a hairline edge
# never touches the border).
CROP_PAD_RATIO = 0.03


def load_keep_jpg() -> set[str]:
    """SKUs the matte must never touch (data/images/keep_jpg.txt).

    Accepts `tms/SKU`, `tms/SKU.jpg`, or a bare `SKU`; `#` comments and blank
    lines are ignored. A missing file means "no exceptions" — never an error.
    """
    keep: set[str] = set()
    try:
        if KEEP_JPG_FILE.is_file():
            with KEEP_JPG_FILE.open(encoding="utf-8") as f:
                for line in f:
                    entry = line.strip()
                    if not entry or entry.startswith("#"):
                        continue
                    stem = entry[:-4] if entry.lower().endswith(".jpg") else entry
                    keep.add(stem)
                    keep.add(stem.rsplit("/", 1)[-1])
    except OSError as exc:
        print(f"[process-images] ignoring {KEEP_JPG_FILE}: {exc}")
    return keep


def _needs_render(cover: Path, keep: set[str], force: bool = False) -> bool:
    render = cover.with_suffix(".webp")
    name = f"{cover.parent.name}/{cover.name}"
    if force:
        return True
    if name in keep or cover.stem in keep or f"{cover.parent.name}/{cover.stem}" in keep:
        return False
    if not render.is_file():
        return True
    try:
        return render.stat().st_mtime < cover.stat().st_mtime
    except OSError:
        return True


def _iter_covers(vendors: list[str] | None = None):
    """Every source cover on disk, newest first.

    Newest-first matters for the incremental CI run: already-rendered files
    are skipped cheaply by mtime, so the walk naturally continues into the
    backlog from its newest end while fresh downloads are always rendered
    the same night they arrive.
    """
    if not IMAGES_DIR.is_dir():
        return
    rows: list[tuple[float, Path]] = []
    for vendor_dir in sorted(p for p in IMAGES_DIR.iterdir() if p.is_dir()):
        if vendors and vendor_dir.name not in vendors:
            continue
        for path in vendor_dir.rglob("*.jpg"):
            if THUMB_SUBDIR in path.relative_to(vendor_dir).parts:
                continue
            try:
                rows.append((path.stat().st_mtime, path))
            except OSError:
                continue
    for _mtime, path in sorted(rows, key=lambda row: row[0], reverse=True):
        yield path


def _removed_share(img: Image.Image) -> float:
    """Share of pixels the matte made (semi-)transparent. 0.0 = nothing done."""
    alpha = img.getchannel("A")
    histogram = alpha.histogram()
    total = sum(histogram)
    if not total:
        return 0.0
    opaque = sum(histogram[250:])
    return 1.0 - (opaque / total)


def _crop_to_product(img: Image.Image) -> tuple[Image.Image, bool]:
    """Crop to the opaque content with a small padding.

    Vendor shots pad the product into a small part of a square frame; with the
    background gone, that padding is wasted space the card has to scale down.
    Returns (image, cropped). Anything suspicious — no alpha at all, or a mask
    that collapsed to a speck — is returned untouched rather than cropped.
    """
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return img, False
    width, height = img.size
    x0, y0, x1, y1 = bbox
    if ((x1 - x0) * (y1 - y0)) / max(1, width * height) < MIN_KEPT_AREA_SHARE:
        return img, False
    pad = int(round(CROP_PAD_RATIO * min(width, height))) + 2
    box = (max(0, x0 - pad), max(0, y0 - pad),
           min(width, x1 + pad), min(height, y1 + pad))
    if box == (0, 0, width, height):
        return img, False
    return img.crop(box), True


def _render_cover(cover: Path, session, force: bool = False) -> dict | None:
    """Produce the transparent .webp (+ thumb) for one cover.

    Returns a metrics dict on success, None when the file could not be
    processed (unreadable, or rembg failed) — never raises: one bad cover must
    not stop a 5,000-file pass.
    """
    render = cover.with_suffix(".webp")
    try:
        with Image.open(cover) as source:
            source.load()
            rgb = source.convert("RGB")
    except Exception as exc:
        print(f"  [skip] unreadable {cover}: {exc}")
        return None

    if rgb.size[0] > MAX_DIMENSION or rgb.size[1] > MAX_DIMENSION:
        rgb.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

    try:
        matted = remove(rgb, session=session,
                        alpha_matting=False, post_process_mask=True)
    except Exception as exc:
        print(f"  [skip] matte failed on {cover}: {exc}")
        return None
    if not isinstance(matted, Image.Image):
        matted = Image.open(matted)
    matted = matted.convert("RGBA")

    removed = _removed_share(matted)
    cropped = False
    if removed >= MIN_REMOVED_SHARE:
        matted, cropped = _crop_to_product(matted)

    # A mask that collapsed to a speck is a failed matte, not a tight crop
    # (seen Sep 2026: a 228px black-background tile the model read as
    # backdrop — 99.8% removed, 80 opaque pixels left). Writing it would ship
    # an invisible product, because the site prefers .webp whenever one
    # exists. Fail safe instead: serve the .jpg, log loudly so QA notices.
    # Same MIN_KEPT_AREA_SHARE tripwire _crop_to_product uses above.
    bbox = matted.getchannel("A").getbbox()
    if bbox is not None:
        kept_share = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / max(
            1, matted.size[0] * matted.size[1])
        if kept_share < MIN_KEPT_AREA_SHARE:
            print(f"  [speck] matte collapsed on {cover} "
                  f"(kept {kept_share:.3f}) — leaving the .jpg")
            return None

    try:
        render.parent.mkdir(parents=True, exist_ok=True)
        matted.save(render, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
        thumb = self_thumb_path(cover)
        thumb.parent.mkdir(parents=True, exist_ok=True)
        thumb_img = matted.copy()
        thumb_img.thumbnail((THUMB_MAX_DIMENSION, THUMB_MAX_DIMENSION),
                            Image.Resampling.LANCZOS)
        thumb_img.save(thumb, "WEBP", quality=THUMB_QUALITY, method=WEBP_METHOD)
    except Exception as exc:
        print(f"  [skip] could not write {render}: {exc}")
        return None

    return {
        "cover": str(cover),
        "render": str(render),
        "thumb": str(thumb),
        "removed": removed,
        "cropped": cropped,
        "source_bytes": cover.stat().st_size if cover.is_file() else 0,
        "render_bytes": render.stat().st_size if render.is_file() else 0,
        "forced": force,
    }


def self_thumb_path(cover: Path) -> Path:
    """data/images/<vendor>/thumbs/<stem>.webp for a cover path."""
    vendor_dir = cover.parent
    return vendor_dir / THUMB_SUBDIR / f"{cover.stem}.webp"


def _summarize(rows: list[dict], skipped: int, total_seen: int) -> None:
    if not rows:
        print(f"[process-images] nothing to render ({skipped} already fresh "
              f"of {total_seen} covers)")
        return
    transparent = [r for r in rows if r["removed"] >= MIN_REMOVED_SHARE]
    source_bytes = sum(r["source_bytes"] for r in rows)
    render_bytes = sum(r["render_bytes"] for r in rows)
    saved = 0 if not source_bytes else 100 - round(render_bytes * 100 / source_bytes)
    print(f"[process-images] rendered {len(rows)} covers, {skipped} already fresh "
          f"({total_seen} seen)")
    print(f"[process-images] check_transparency: "
          f"{len(transparent)}/{len(rows)} "
          f"({round(len(transparent) * 100 / len(rows))}%) have a transparent "
          f"background, {len(rows) - len(transparent)} kept opaque")
    if transparent:
        mean_removed = sum(r["removed"] for r in transparent) / len(transparent)
        print(f"[process-images] mean removed area {round(mean_removed * 100)}%, "
              f"cropped to product in "
              f"{sum(1 for r in transparent if r['cropped'])} of them")
    print(f"[process-images] bytes {source_bytes // 1024}KB -> "
          f"{render_bytes // 1024}KB ({saved}% smaller)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*",
                        help="specific .jpg covers to render (optional)")
    parser.add_argument("--vendor", action="append", dest="vendors", default=None,
                        help="only this vendor folder (e.g. --vendor tms); repeatable")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after this many rendered covers (0 = all)")
    parser.add_argument("--force", action="store_true",
                        help="re-render even when the .webp is already fresh")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and write nothing")
    parser.add_argument(
        "--list-out",
        default=None,
        help="write the path of every rendered file here, one per line. CI "
        "stages exactly those paths instead of a broad `git add` on a tree "
        "another job also writes (see the nano/cloud split in AGENTS.md).",
    )
    args = parser.parse_args(argv)

    if args.files:
        covers = [Path(p) for p in args.files]
        if args.vendors:
            covers = [c for c in covers if c.parent.name in args.vendors]
    else:
        covers = list(_iter_covers(args.vendors))

    keep = load_keep_jpg()
    todo = [c for c in covers if _needs_render(c, keep, force=args.force)]

    if args.dry_run:
        print(f"[process-images] {len(todo)} of {len(covers)} covers need a render "
              f"({len(keep)} SKUs in keep_jpg.txt)")
        for cover in todo[:40]:
            print(f"  {cover}")
        if len(todo) > 40:
            print(f"  … {len(todo) - 40} more")
        return 0

    if not todo:
        _summarize([], len(covers), len(covers))
        return 0

    if remove is None or new_session is None:
        print("[process-images] rembg is not installed — no transparent renders "
              "can be produced. The site keeps serving the original .jpg covers.")
        print("  install it with: pip install -r requirements-images.txt")
        return 1

    batch = todo[:args.limit] if args.limit else todo
    print(f"[process-images] rendering {len(batch)} covers "
          f"({len(todo) - len(batch)} left for a later run), model {MODEL_NAME}")
    session = new_session(MODEL_NAME)

    rows: list[dict] = []
    for index, cover in enumerate(batch, start=1):
        row = _render_cover(cover, session, force=args.force)
        if row:
            rows.append(row)
        if index % 25 == 0:
            print(f"  … {index}/{len(batch)}")
    _summarize(rows, len(covers) - len(todo), len(covers))

    if args.list_out:
        out = Path(args.list_out)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(f"{row['render']}\n{row['thumb']}\n")
            print(f"[process-images] wrote {len(rows) * 2} paths to {out}")
        except OSError as exc:
            print(f"[process-images] could not write {out}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
