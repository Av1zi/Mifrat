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


def download_and_save(image_url: str, dest_path: Path) -> bool:
    """Returns True on success. Never raises — a failed image download
    should not block the rest of the batch; log and move on.

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
        return True
    except Exception as exc:
        try:
            LAST_HTTP_STATUS = exc.response.status_code  # type: ignore[attr-defined]
        except Exception:
            pass
        print(f"  FAILED {image_url} -> {dest_path}: {exc}")
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

            dest = Path(f"data/images/{vendor}/{sku}.jpg")
            if dest.exists():
                # Already downloaded (e.g. a re-run after a partial
                # failure) — skip re-fetching.
                succeeded.append(sku)
                continue

            if download_and_save(image_url, dest):
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
        key = (folder, sku)
        if key in seen:
            continue
        seen.add(key)
        dest = Path(f"data/images/{folder}/{sku}.jpg")
        if dest.exists():
            continue
        pending.append((folder, sku, str(chosen.get("image_url"))))

    print(f"[backfill] {len(pending)} photoless products need an image "
          f"({skipped_no_url} have no usable vendor photo at all)")
    if not pending:
        return

    import time

    batch = pending[:limit]
    succeeded, failed = 0, 0
    blocked_streak = 0
    for folder, sku, url in batch:
        dest = Path(f"data/images/{folder}/{sku}.jpg")
        if download_and_save(url, dest):
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

    if args.from_catalog:
        _backfill_from_catalog(limit=args.limit, vendors=args.only_vendor,
                               sleep_secs=args.sleep)
    elif args.jsonl_path and args.vendor:
        process_jsonl(args.jsonl_path, args.vendor)
    else:
        parser.print_usage()
        print("Usage: python -m scraper.download_images <jsonl_path> <vendor>")
        print("   or: python -m scraper.download_images --from-catalog [--limit 200]")
        sys.exit(1)
