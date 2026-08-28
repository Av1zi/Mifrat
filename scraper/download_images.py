"""
Downloads cover images for products scraped by detail_pages.py spiders.

Run AFTER a detail spider finishes, pointed at that vendor's output
jsonl. Deliberately a plain script rather than Scrapy's ImagesPipeline
— at ~5 new items/day this is simpler to reason about and keeps the
resize/compress step in one place shared across all 4 vendors.

Usage:
    python -m scraper.download_images data/raw/detail/tms.jsonl tms

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

import requests
from PIL import Image

MAX_DIMENSION = 800
JPEG_QUALITY = 82
REQUEST_TIMEOUT = 15


def download_and_save(image_url: str, dest_path: Path) -> bool:
    """Returns True on success. Never raises — a failed image download
    should not block the rest of the batch; log and move on."""
    try:
        resp = requests.get(image_url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MifratBot/1.0)"
        })
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return True
    except Exception as exc:
        print(f"  FAILED {image_url} -> {dest_path}: {exc}")
        return False


def process_jsonl(jsonl_path: str, vendor: str) -> None:
    input_path = Path(jsonl_path)
    if not input_path.exists():
        print(f"No such file: {input_path}")
        sys.exit(1)

    succeeded, failed = [], []
    with input_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            sku = item.get("vendor_sku")
            image_url = item.get("image_url")
            if not sku or not image_url:
                failed.append(sku or "<unknown sku>")
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

    print(f"\n{vendor}: {len(succeeded)} images ok, {len(failed)} failed")
    if failed:
        print(f"Failed SKUs: {failed}")
        print("These SKUs should NOT be added to data/detail_scraped/<vendor>.json")
        print("until their image succeeds on a re-run — keeps 'scraped' meaning")
        print("'fully scraped, spec + image both present'.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m scraper.download_images <jsonl_path> <vendor>")
        sys.exit(1)
    process_jsonl(sys.argv[1], sys.argv[2])
