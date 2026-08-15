"""
Normalizer + matcher: turns data/listings_latest.jsonl (raw, per-vendor) into
data/catalog.json (canonical products with vendor_links) — see §6 for the
target schema and §8 for the matching strategy.

This is a Phase 2 task (§16) — deliberately a stub during Phase 1, where the
goal is just proving the raw scrape -> commit -> deploy loop end to end
without matching yet ("a bare-bones static page listing raw scraped prices").

Planned approach when this gets built out (§8):
  1. Extract structured signals from title_raw (brand, model, capacity) via
     regex/keyword rules — don't match on raw title strings.
  2. Prefer vendor_sku / URL-slug model numbers over parsed titles when
     available — more reliable than display text.
  3. Fuzzy match (rapidfuzz) on normalized (brand+model+capacity) as a
     fallback, with a confidence threshold. Below-threshold -> review queue,
     not straight into the catalog.
  4. Store confirmed vendor_sku -> product_id mappings so a listing is only
     matched once, not re-matched every day.
  5. Build a tiny manual-merge review script early (even a local CLI) — see
     README for where that fits once Phase 2 starts.

Usage:
  python scraper/normalize_and_match.py
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_PATH = DATA_DIR / "listings_latest.jsonl"
OUTPUT_PATH = DATA_DIR / "catalog.json"


def load_raw_listings():
    if not INPUT_PATH.exists():
        return []
    with open(INPUT_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def phase1_passthrough(listings):
    """
    Phase 1 behavior: no matching yet, just reshape raw listings into a flat
    list the bare-bones static page can render directly. Replace this with
    real product-level matching in Phase 2.
    """
    return {"listings": listings, "products": []}


def main():
    listings = load_raw_listings()
    catalog = phase1_passthrough(listings)
    DATA_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {len(listings)} raw listings to {OUTPUT_PATH} (Phase 1: no matching yet)")


if __name__ == "__main__":
    main()
