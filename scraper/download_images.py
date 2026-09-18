"""
Downloads cover images for products scraped by detail_pages.py spiders.

Run AFTER a detail spider finishes, pointed at that vendor's output
jsonl. Deliberately a plain script rather than Scrapy's ImagesPipeline
— at ~5 new items/day this is simpler to reason about and keeps the
resize/compress step in one place shared across all 4 vendors.

Usage:
    python -m scraper.download_images data/raw/detail/tms.jsonl tms
    python -m scraper.download_images --from-catalog [--limit 200]

Saves to data/images/<vendor>/<vendor_sku>.jpg, resized so the long
edge is at most 800px and re-encoded as JPEG quality 82 — keeps each
file in the ~20-50KB range, which at 5 new items/day is a trivial,
slow-growing addition to the git repo (nothing like the pcpartdb
16MB-of-text problem that forced that data to be gitignored).

Every cover additionally yields data/images/<vendor>/thumbs/<sku>.jpg
(128px long edge, quality 70, ~3-5KB) for list-page rows — same
download, second save. --thumbs-only regenerates missing thumbs
from the covers on disk with no network.
"""
import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

MAX_DIMENSION = 800
JPEG_QUALITY = 82
REQUEST_TIMEOUT = 15

# List-thumbnail derivative (Sep 2026): list pages render ~35KB 800px
# files as 72px thumbs (~2MB per 60 rows). The 128px/q70 thumb (~3-5KB)
# serves those rows instead — same download, second save, no new deps.
THUMB_MAX_DIMENSION = 128
THUMB_QUALITY = 70
THUMB_SUBDIR = "thumbs"


def _has_basename(url: str) -> bool:
    """Same guard as the spiders' _og_image and the normalizer's
    _has_image_basename: a bare ".../full/" directory URL is not an image
    (Plonter emits these for imageless products). Keep the three in sync."""
    try:
        if not url:
            return False
        return bool(urlparse(str(url)).path.rsplit("/", 1)[-1])
    except Exception:
        return False


def download_and_save(image_url: str, dest_path: Path,
                      thumb_path: Path | None = None) -> bool:
    """Returns True on success. Never raises — a failed image download
    should not block the rest of the batch; log and move on.

    When thumb_path is given, the same download additionally yields the
    128px list-thumbnail derivative (no second request).

    Sets LAST_HTTP_STATUS (None on non-HTTP failures) so batch loops can
    implement block detection (see _backfill_from_catalog).
    """
    global LAST_HTTP_STATUS
    LAST_HTTP_STATUS = None
    try:
        resp = requests.get(image_url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MifratBot/1.0)"
        })
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        if thumb_path is not None:
            img.thumbnail((THUMB_MAX_DIMENSION, THUMB_MAX_DIMENSION),
                          Image.Resampling.LANCZOS)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(thumb_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return True
    except Exception as exc:
        try:
            LAST_HTTP_STATUS = exc.response.status_code  # type: ignore[attr-defined]
        except Exception:
            pass
        print(f"  FAILED {image_url} -> {dest_path}: {exc}")
        return False


def write_thumb_from_file(full_path: Path, thumb_path: Path) -> bool:
    """(Re)generate a list thumbnail from an already-downloaded cover.
    No network — safe to run over the whole archive in one go."""
    try:
        img = Image.open(full_path).convert("RGB")
        img.thumbnail((THUMB_MAX_DIMENSION, THUMB_MAX_DIMENSION),
                      Image.Resampling.LANCZOS)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(thumb_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return True
    except Exception as exc:
        print(f"  THUMB FAILED {full_path} -> {thumb_path}: {exc}")
        return False


# HTTP status of the most recent download_and_save call (None when the
# failure wasn't HTTP, or the last call succeeded).
LAST_HTTP_STATUS: int | None = None


def process_jsonl(jsonl_path: str, vendor: str) -> None:
    input_path = Path(jsonl_path)
    if not input_path.exists():
        print(f"No such file: {input_path}")
        sys.exit(1)

    succeeded, failed, skipped = [], [], []
    with input_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            sku = item.get("vendor_sku")
            image_url = item.get("image_url")
            if not sku:
                failed.append("<unknown sku>")
                continue
            if not image_url or not _has_basename(image_url):
                # No photo on the vendor side (Plonter emits a bare
                # directory URL for these). Quiet skip — NOT a failure:
                # specs are still marked done and the listing thumbnail
                # covers the product photo.
                skipped.append(sku)
                continue

            dest = _dest_for(vendor, sku)
            thumb = _dest_for(vendor, sku, thumb=True)
            if dest.exists():
                # Already downloaded (e.g. a re-run after a partial
                # failure) — skip re-fetching, but still ensure the
                # list-thumbnail derivative exists (no network).
                if thumb.exists():
                    succeeded.append(sku)
                elif write_thumb_from_file(dest, thumb):
                    succeeded.append(sku)
                else:
                    failed.append(sku)
                continue

            if download_and_save(image_url, dest, thumb):
                succeeded.append(sku)
            else:
                failed.append(sku)

    print(f"\n{vendor}: {len(succeeded)} images ok, {len(failed)} failed, "
          f"{len(skipped)} skipped (no vendor photo)")
    if failed:
        print(f"Failed SKUs: {failed}")
        print("No image file was saved for these — they are retried")
        print("automatically on the next run (files already on disk are")
        print("skipped, so only the missing ones are re-attempted).")


def _vendor_folder(vendor_id: str) -> str:
    """Same normalization as site_data._image_vendor_key: 1pc -> onepc."""
    return "onepc" if vendor_id in ("1pc", "onepc") else (vendor_id or "")


def _dest_for(vendor_folder: str, sku: str, thumb: bool = False) -> Path:
    """On-disk destination for a downloaded cover. The filename goes
    through site_data._safe_image_stem (strips invisible Cf/Cc chars that
    would otherwise produce uncommittable/unfetchable files) — both sides
    must agree, so never build this path from the raw SKU directly.

    thumb=True addresses the 128px list-thumbnail derivative under
    data/images/<vendor>/thumbs/ (same per-vendor tree, so the existing
    commit-script exemption for data/images/<vendor>/ keeps applying).
    """
    try:
        from scraper.site_data import _safe_image_stem
    except ImportError:
        from site_data import _safe_image_stem  # type: ignore[no-redef]
    stem = _safe_image_stem(sku)
    if thumb:
        return Path(f"data/images/{vendor_folder}/{THUMB_SUBDIR}/{stem}.jpg")
    return Path(f"data/images/{vendor_folder}/{stem}.jpg")


def _backfill_from_catalog(limit: int = 200, vendors: list[str] | None = None,
                         sleep_secs: float = 1.0) -> None:
    """Download listing-thumbnail images for catalog PRODUCTS that currently
    have no local photo (one image per product — the minimal set that
    closes the visible gap). Covers listing-only products (no detail row,
    so no og:image) — exactly the gap that forced the old remote-URL
    fallback.

    A product "has a photo" by the same rule site_data._resolve_image
    uses (an offer whose image file exists on disk); photoless products
    get their product.image_url's offer (else their first usable offer).
    Products whose offers carry no usable image URL at all (~86) can never
    have photos and are skipped — they render as initials thumbs.

    Politeness: sequential, MifratBot UA (see download_and_save), 15s
    timeout, `sleep_secs` pause between downloads, skips files already on
    disk, capped at `limit` new downloads per run. Never raises — image
    gaps must never block the pipeline; missing photos render as initials
    thumbs.

    TMS binding (see AGENTS.md): TMS blocks datacenter IPs and rate-limits
    aggressively, so consecutive 403/429s are a stop signal, not a retry
    cue — abort the run after 2 in a row to protect the daily listing
    scrape, which matters far more than photos.
    """
    try:
        from scraper.site_data import _local_image_path
    except ImportError:
        from site_data import _local_image_path  # type: ignore[no-redef]

    catalog_path = Path("data/catalog.json")
    if not catalog_path.exists():
        print(f"No such file: {catalog_path} — run normalize first")
        sys.exit(1)

    with catalog_path.open(encoding="utf-8") as f:
        catalog = json.load(f)

    def _usable_offer(offer: dict) -> bool:
        sku = str(offer.get("vendor_sku") or "").strip()
        return bool(sku) and bool(offer.get("image_url")) and _has_basename(
            str(offer.get("image_url"))
        )

    def _has_photo(product: dict) -> bool:
        for offer in product.get("offers", []) or []:
            if not _usable_offer(offer):
                continue
            if _local_image_path(
                offer.get("vendor_id"), str(offer.get("vendor_sku") or "")
            ):
                return True
        return False

    # One target per photoless product: prefer the offer behind the
    # product's current image_url (keeps catalog ↔ site choice stable),
    # else the first usable offer.
    pending: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    skipped_no_url = 0
    for product in catalog.get("products", []):
        if _has_photo(product):
            continue
        offers = [o for o in product.get("offers", []) or [] if _usable_offer(o)]
        if not offers:
            skipped_no_url += 1
            continue
        current = product.get("image_url")
        chosen = next(
            (o for o in offers if o.get("image_url") == current), offers[0]
        )
        vendor = str(chosen.get("vendor_id") or "")
        folder = _vendor_folder(vendor)
        if vendors and folder not in vendors and vendor not in vendors:
            continue
        sku = str(chosen.get("vendor_sku") or "").strip()
        dest = _dest_for(folder, sku)
        thumb = _dest_for(folder, sku, thumb=True)
        key = (folder, dest.name)
        if key in seen:
            continue
        seen.add(key)
        if dest.exists() and thumb.exists():
            continue
        pending.append((folder, sku, str(chosen.get("image_url"))))

    print(f"[backfill] {len(pending)} products need an image or thumbnail "
          f"({skipped_no_url} have no usable vendor photo at all)")
    if not pending:
        return

    import time

    batch = pending[:limit]
    succeeded, failed = 0, 0
    blocked_streak = 0
    for folder, sku, url in batch:
        dest = _dest_for(folder, sku)
        thumb = _dest_for(folder, sku, thumb=True)
        if dest.exists():
            # Full already on disk — only the thumbnail is missing.
            if write_thumb_from_file(dest, thumb):
                succeeded += 1
            else:
                failed += 1
            continue
        if download_and_save(url, dest, thumb):
            succeeded += 1
            blocked_streak = 0
        else:
            failed += 1
            if LAST_HTTP_STATUS in (403, 429):
                blocked_streak += 1
                if blocked_streak >= 2:
                    print(
                        f"[backfill] STOP: 2 consecutive {LAST_HTTP_STATUS}s — "
                        f"treating as a block signal (photos must never "
                        f"endanger the listing scrape). "
                        f"{len(pending) - succeeded - failed} remaining."
                    )
                    break
            else:
                blocked_streak = 0
        time.sleep(sleep_secs)

    print(
        f"[backfill] downloaded {succeeded}/{len(batch)} "
        f"({len(pending) - succeeded - failed} remaining for future runs)"
    )
    if failed:
        print(f"[backfill] {failed} failed — retried automatically next run")


def _backfill_thumbs_only(vendors: list[str] | None = None) -> None:
    """Regenerate every missing list thumbnail from the full-size covers
    already in data/images/<vendor>/. Pure local resampling — no network,
    no politeness cap, no block risk. Thumbs live in the per-vendor
    thumbs/ subdir, so the commit-script data/images/<vendor>/ exemption
    keeps applying (commit per vendor, off-peak).
    """
    base = Path("data/images")
    if not base.is_dir():
        print(f"No such directory: {base}")
        sys.exit(1)
    folders = sorted(p for p in base.iterdir() if p.is_dir())
    if vendors:
        wanted = set(vendors)
        folders = [p for p in folders
                   if p.name in wanted or _vendor_folder(p.name) in wanted]
    made, skipped, failed = 0, 0, 0
    for folder in folders:
        # Recursive: covers the legacy ivory per-SKU subdirs
        # (data/images/ivory/<SKU>/<file>.jpg, from slash-bearing SKUs),
        # mirrored 1:1 under thumbs/ — the same layout _dest_for and
        # site_data._local_image_path derive for such SKUs.
        for full in sorted(folder.rglob("*.jpg")):
            if THUMB_SUBDIR in full.relative_to(folder).parts:
                continue
            thumb = folder / THUMB_SUBDIR / full.relative_to(folder)
            if thumb.exists():
                skipped += 1
                continue
            if write_thumb_from_file(full, thumb):
                made += 1
            else:
                failed += 1
    print(f"[thumbs-only] {made} generated, {skipped} already present"
          + (f", {failed} failed" if failed else ""))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download product cover images")
    parser.add_argument("jsonl_path", nargs="?", help="detail jsonl to process")
    parser.add_argument("vendor", nargs="?", help="vendor folder under data/images/")
    parser.add_argument(
        "--from-catalog",
        action="store_true",
        help="backfill listing thumbnails from data/catalog.json offers "
        "(covers listing-only products with no detail row)",
    )
    parser.add_argument(
        "--thumbs-only",
        action="store_true",
        help="regenerate missing 128px list thumbnails from the full-size "
        "files already on disk. No network — safe to run over the whole "
        "archive in one go.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="max new downloads per --from-catalog run (politeness cap)",
    )
    parser.add_argument(
        "--vendor",
        dest="only_vendor",
        action="append",
        default=None,
        help="only backfill this vendor folder (e.g. --vendor tms); "
        "repeatable. Default: all vendors.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="seconds to pause between downloads (default 1.0)",
    )
    args = parser.parse_args()

    if args.thumbs_only:
        _backfill_thumbs_only(vendors=args.only_vendor)
    elif args.from_catalog:
        _backfill_from_catalog(limit=args.limit, vendors=args.only_vendor,
                               sleep_secs=args.sleep)
    elif args.jsonl_path and args.vendor:
        process_jsonl(args.jsonl_path, args.vendor)
    else:
        parser.print_usage()
        print("Usage: python -m scraper.download_images <jsonl_path> <vendor>")
        print("   or: python -m scraper.download_images --from-catalog [--limit 200]")
        print("   or: python -m scraper.download_images --thumbs-only [--vendor tms]")
        sys.exit(1)
