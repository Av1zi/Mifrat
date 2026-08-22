"""
Normalizer + matcher: reads today's + recent raw per-vendor snapshots from
data/raw/YYYY-MM-DD/<vendor>.jsonl and builds data/catalog.json.

Phase 2:
- enriches listings with stable listing keys
- normalizes prices/categories
- builds canonical products
- writes optional fuzzy review queue to data/review_queue.json

Stale-forward rule:
If a vendor's raw snapshot is missing today, use the most recent snapshot
within the lookback window and mark those listings stale.

Usage (from the repo root):
python -m scraper.normalize_and_match
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scraper.matching import (
        dedupe_enriched_listings,
        enrich_listing,
        match_listings,
        suggest_fuzzy_matches,
    )
except ImportError:
    from matching import (
        dedupe_enriched_listings,
        enrich_listing,
        match_listings,
        suggest_fuzzy_matches,
    )


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_PATH = DATA_DIR / "catalog.json"
REVIEW_PATH = DATA_DIR / "review_queue.json"
MANUAL_PATH = DATA_DIR / "matching" / "manual_products.json"

# Ivory is now included. If its raw file is missing, it is skipped gracefully.
VENDOR_SPIDER_NAMES = ["tms", "onepc", "plonter", "ivory"]

# Supports either onepc.jsonl or 1pc.jsonl.
VENDOR_FILE_ALIASES = {
    "onepc": ["onepc", "1pc"],
    "1pc": ["1pc", "onepc"],
}

STALE_LOOKBACK_DAYS = 14


def _date_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def find_latest_snapshot(vendor_spider_name: str, today: datetime):
    """
    Return (path, date_str) for the most recent available raw file for
    this vendor within the lookback window, or None if there isn't one.
    """
    base_names = VENDOR_FILE_ALIASES.get(vendor_spider_name, [vendor_spider_name])

    for offset in range(STALE_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=offset)
        day_str = _date_str(day)

        for name in base_names:
            candidate = RAW_DIR / day_str / f"{name}.jsonl"
            if candidate.exists():
                return candidate, day_str

    return None


def load_listings(path: Path) -> list[dict]:
    """
    Load JSONL listings.

    This also tries to recover from concatenated JSON objects on one line,
    which can happen when copy/pasting raw output.
    """
    listings = []
    decoder = json.JSONDecoder()

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                listings.append(json.loads(line))
                continue
            except json.JSONDecodeError:
                idx = 0

                while idx < len(line):
                    while idx < len(line) and line[idx] not in "{[":
                        idx += 1

                    if idx >= len(line):
                        break

                    try:
                        obj, end = decoder.raw_decode(line[idx:])
                        listings.append(obj)
                        idx += end
                    except json.JSONDecodeError:
                        break

    return listings


def build_catalog(today: datetime):
    today_str = _date_str(today)

    all_listings = []
    skipped_vendors = []

    for vendor_spider_name in VENDOR_SPIDER_NAMES:
        found = find_latest_snapshot(vendor_spider_name, today)

        if found is None:
            skipped_vendors.append(vendor_spider_name)
            print(
                f"[info] {vendor_spider_name}: no snapshot in the last "
                f"{STALE_LOOKBACK_DAYS} days — not onboarded yet or down "
                "for longer than the lookback window",
                file=sys.stderr,
            )
            continue

        path, snapshot_date = found
        is_stale = snapshot_date != today_str

        listings = load_listings(path)

        for listing in listings:
            listing["last_seen"] = snapshot_date
            listing["stale"] = is_stale

            if not listing.get("vendor_id"):
                listing["vendor_id"] = (
                    "1pc" if vendor_spider_name == "onepc" else vendor_spider_name
                )

        level = "warn" if is_stale else "ok"
        print(
            f"[{level}] {vendor_spider_name}: {len(listings)} listings from {snapshot_date}"
            + (" (stale)" if is_stale else "")
        )

        all_listings.extend(listings)

    enriched = [enrich_listing(listing) for listing in all_listings]
    enriched = dedupe_enriched_listings(enriched)

    # Stable output ordering.
    enriched.sort(key=lambda e: (e.get("vendor_id", ""), e.get("listing_key", "")))

    match_result = match_listings(enriched, manual_path=MANUAL_PATH)

    assignments = match_result["assignments"]
    product_sizes = match_result["product_sizes"]

    for e in enriched:
        e["product_id"] = assignments.get(e["listing_key"])

    exclude_multi_keys = {
        listing_key_value
        for listing_key_value, pid in assignments.items()
        if product_sizes.get(pid, 0) > 1
    }

    review_queue = suggest_fuzzy_matches(
        enriched,
        manual_path=MANUAL_PATH,
        threshold=88,
        exclude_multi_keys=exclude_multi_keys,
        assignments=assignments,
    )

    catalog = {
        "generated_at": today.isoformat(),
        "listings": enriched,
        "products": match_result["products"],
        "review_queue_count": len(review_queue),
        "skipped_vendors": skipped_vendors,
    }

    return catalog, review_queue


def main():
    today = datetime.now(timezone.utc)

    catalog, review_queue = build_catalog(today)

    DATA_DIR.mkdir(exist_ok=True)
    MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    with open(REVIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(review_queue, f, ensure_ascii=False, indent=2)

    # Count-check: zero listings across every vendor means the whole
    # pipeline is broken, so fail loudly rather than commit an empty catalog.
    if not catalog["listings"]:
        print("[error] zero listings across all vendors — failing the job", file=sys.stderr)
        sys.exit(1)

    print(
        f"[ok] wrote {len(catalog['listings'])} listings, "
        f"{len(catalog['products'])} products, "
        f"{len(review_queue)} review candidates "
        f"to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()