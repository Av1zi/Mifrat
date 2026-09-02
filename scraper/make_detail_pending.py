"""
Pending-work + ledger bookkeeping for the detail-page scrape.
The detail spiders deliberately don't do this themselves (same logic
4x over otherwise); this is the single place that knows what "already
scraped" means.

Usage:
    python -m scraper.make_detail_pending make [vendor ...] [--limit N]
        Diff listing output (data/raw/<vendor>.jsonl) against the ledger
        (data/detail_scraped/<vendor>.json) and write
        data/detail_pending/<vendor>.json. --limit N caps the list so the
        initial backfill can be chunked (important for TMS on the Nano —
        never batch-request the whole catalog in one run, §7).
    python -m scraper.make_detail_pending mark [vendor ...]
        Append to the ledger every vendor_sku that appears in
        data/raw/detail/<vendor>.jsonl AND whose resized image already
        exists at data/images/<vendor>/<sku>.jpg. Run ONLY after the
        detail spider AND download_images both succeeded — a crash
        partway through must not mark a product done without its image.

Vendor keys everywhere here: onepc / plonter / ivory / tms (matches the
spider names and the _load_pending() keys in detail_pages.py; run
download_images with the same key so image paths line up).
"""
import json
import sys
from pathlib import Path

VENDORS = ["onepc", "plonter", "ivory", "tms"]
VENDOR_ALIASES = {
    "onepc": ["onepc", "1pc"],
    "1pc": ["1pc", "onepc"],
}


def _normalize_vendor(v: str) -> str:
    return "onepc" if v in {"1pc", "onepc"} else v


def _candidate_names(v: str) -> list[str]:
    v = _normalize_vendor(v)
    return VENDOR_ALIASES.get(v, [v])


def _latest_listing_path(v: str) -> Path:
    names = _candidate_names(v)
    flat = Path(f"data/raw/{_normalize_vendor(v)}.jsonl")
    if flat.exists():
        return flat

    raw_root = Path("data/raw")
    newest = None
    for child in sorted(raw_root.glob("*"), reverse=True):
        if not child.is_dir():
            continue
        for name in names:
            candidate = child / f"{name}.jsonl"
            if candidate.exists():
                newest = candidate
                break
        if newest:
            break
    return newest or flat


def _listing(v):
    return _latest_listing_path(v)


def _pending(v):
    v = _normalize_vendor(v)
    return Path(f"data/detail_pending/{v}.json")


def _ledger(v):
    v = _normalize_vendor(v)
    return Path(f"data/detail_scraped/{v}.json")

def _detail(v):
    v = _normalize_vendor(v)
    return Path(f"data/raw/detail/{v}.jsonl")

def _image(v, sku):
    v = _normalize_vendor(v)
    return Path(f"data/images/{v}/{sku}.jpg")

def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load_ledger(v: str) -> set:
    p = _ledger(v)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")))


def make(vendors: list, limit: int | None) -> None:
    for v in vendors:
        done = _load_ledger(v)
        pending, seen = [], set()
        for item in _load_jsonl(_listing(v)):
            sku = item.get("vendor_sku")
            url = item.get("url")
            if not sku or not url or sku in done or sku in seen:
                continue
            seen.add(sku)
            pending.append({"vendor_sku": sku, "url": url})
            if limit and len(pending) >= limit:
                break
        _pending(v).parent.mkdir(parents=True, exist_ok=True)
        _pending(v).write_text(
            json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{v}: {len(pending)} pending ({len(done)} already in ledger)")


def mark(vendors: list) -> None:
    for v in vendors:
        done = _load_ledger(v)
        added = 0
        for item in _load_jsonl(_detail(v)):
            sku = item.get("vendor_sku")
            if not sku or sku in done:
                continue
            if not _image(v, sku).exists():
                continue  # scraped but no image on disk => not done yet
            done.add(sku)
            added += 1
        if added:
            _ledger(v).parent.mkdir(parents=True, exist_ok=True)
            _ledger(v).write_text(
                json.dumps(sorted(done), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        print(f"{v}: +{added} marked done ({len(done)} total in ledger)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("make", "mark"):
        print("Usage: python -m scraper.make_detail_pending <make|mark> [vendor ...] [--limit N]")
        sys.exit(1)
    cmd = args.pop(0)
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]
    vendors = args or VENDORS
    if cmd == "make":
        make(vendors, limit)
    else:
        mark(vendors)