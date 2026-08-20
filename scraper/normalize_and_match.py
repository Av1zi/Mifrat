"""
Normalizer + matcher: reads today's + recent raw per-vendor snapshots from
data/raw/YYYY-MM-DD/<vendor>.jsonl (§5) and builds data/catalog.json.

This is still a Phase 1 passthrough (§16) — no product-level matching yet,
just reshaping raw listings for the bare-bones static page. Real matching
(brand/model extraction, fuzzy fallback, manual-merge review) is Phase 2
(§12) and belongs in this file when that starts.

## Stale-forward rule (§5)

A vendor's raw snapshot can be missing for today for ordinary operational
reasons (Nano down, a spider broke, a site blocked us for the day) — that
must never wipe the vendor's listings off the site. So for each vendor
independently:
  1. Look for today's data/raw/<today>/<vendor>.jsonl.
  2. If missing, walk backwards through recent date folders and use the
     most recent one that has this vendor's file instead.
  3. Every listing carries `last_seen` (the date of the snapshot it
     actually came from) and `stale` (True if that date isn't today) — the
     frontend is expected to show staleness visibly rather than silently
     presenting old prices as current.
  4. A vendor with NO snapshot in the lookback window at all (never
     scraped yet, e.g. Ivory pre-Phase-2) is skipped entirely, not treated
     as an error — onboarding a new vendor is normal, not a failure.

Usage:
  python scraper/normalize_and_match.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_PATH = DATA_DIR / "catalog.json"

# Vendors currently wired into the pipeline. Ivory joins here in Phase 2
# once its spider is built (§16) — adding it is a one-line change, and
# until then it's simply absent from raw/, which the stale-forward lookup
# already treats as "not onboarded yet" rather than an error.
VENDOR_SPIDER_NAMES = ["tms", "onepc", "plonter"]

# How many days back to look for a vendor's most recent snapshot before
# giving up on it for this run. Generous on purpose — a vendor down for a
# long weekend shouldn't vanish from the site; if it's down for longer than
# this, that's a real problem the count-check / Sentry alerting (§9) should
# have already surfaced well before this window closes.
STALE_LOOKBACK_DAYS = 14


def _date_str(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def find_latest_snapshot(vendor_spider_name: str, today: datetime) -> tuple[Path, str] | None:
    """Return (path, date_str) for the most recent available raw file for
    this vendor within the lookback window, or None if there isn't one."""
    for offset in range(STALE_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=offset)
        day_str = _date_str(day)
        candidate = RAW_DIR / day_str / f"{vendor_spider_name}.jsonl"
        if candidate.exists():
            return candidate, day_str
    return None


def load_listings(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_catalog(today: datetime) -> dict:
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

        level = "warn" if is_stale else "ok"
        print(f"[{level}] {vendor_spider_name}: {len(listings)} listings from {snapshot_date}"
              + (" (stale)" if is_stale else ""))
        all_listings.extend(listings)

    return {
        "generated_at": today.isoformat(),
        "listings": all_listings,
        "products": [],  # Phase 2 (§12): canonical matched products go here
        "skipped_vendors": skipped_vendors,
    }


def main():
    today = datetime.now(timezone.utc)
    catalog = build_catalog(today)

    DATA_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    # §10 count-check: zero listings across every vendor means the whole
    # pipeline is broken (not just one vendor having a bad day), so fail
    # loudly rather than commit an empty catalog.
    if not catalog["listings"]:
        print("[error] zero listings across all vendors — failing the job", file=sys.stderr)
        sys.exit(1)

    print(f"[ok] wrote {len(catalog['listings'])} total listings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
