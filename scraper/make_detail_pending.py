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
        initial backfill can be chunked (important for TMS on the Nano ΓÇö
        never batch-request the whole catalog in one run, ┬º7).
    python -m scraper.make_detail_pending mark [vendor ...]
        Append to the ledger every vendor_sku that appears in
        data/raw/detail/<vendor>.jsonl. Run ONLY after the detail spider
        succeeds ΓÇö a crash partway through must not mark products whose
        spec rows were never written.

        NOTE (Sep 2026): the ledger means "specs scraped", NOT "specs +
        image". Image presence deliberately does NOT gate marking: products
        with no vendor photo (Plonter emits a bare directory URL for
        these), 404s and truncated files would otherwise stay pending
        forever and burn a Playwright page load every single day. Photos
        resolve independently ΓÇö download_images.py retries missing files
        on every run (it skips files already on disk), and the normalizer
        falls back to the listing thumbnail when no detail image exists.
        A detail row is marked only when it contains usable specs. Empty
        rows and common challenge/error payloads are rejected; leaving them
        pending allows a later run (or a parser fix) to retry them instead
        of permanently losing specification coverage.

Vendor keys everywhere here: onepc / plonter / ivory / tms (matches the
spider names and the _load_pending() keys in detail_pages.py; run
download_images with the same key so image paths line up).
"""
import json
import sys
from collections import Counter
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
        # 'detail' is the detail-spider OUTPUT dir, not a dated snapshot —
        # without this guard it sorts before YYYY-MM-DD names (reverse
        # alphabetical) and its (often empty) files masquerade as listings,
        # silently producing 0 pending for every vendor.
        if child.name == "detail":
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


def _core_gap_priorities() -> dict[tuple[str, str], int]:
    """Return listing URL priorities for products with missing core specs.

    The normalized site payload is the only persisted join between a product
    id in spec_report.json and the vendor listing URL.  Missing or stale
    reports are deliberately treated as advisory: normal pending generation
    still works, it just falls back to listing order.
    """
    report_path = Path("data/site/spec_report.json")
    if not report_path.exists():
        return {}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        gaps = report.get("core_gaps") or []
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    gap_counts = Counter(
        str(gap.get("product_id") or "")
        for gap in gaps
        if isinstance(gap, dict) and gap.get("product_id")
    )
    if not gap_counts:
        return {}

    priorities: dict[tuple[str, str], int] = {}
    for path in sorted(Path("data/site").glob("*.json")):
        if path.name in {"spec_report.json", "qa.json", "meta.json", "index.json"}:
            continue
        try:
            products = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(products, list):
            continue
        for product in products:
            if not isinstance(product, dict):
                continue
            score = gap_counts.get(str(product.get("id") or ""), 0)
            if not score:
                continue
            for offer in product.get("offers") or []:
                if not isinstance(offer, dict) or not offer.get("url"):
                    continue
                vendor = _normalize_vendor(str(offer.get("vendor") or ""))
                if vendor:
                    priorities[(vendor, str(offer["url"]))] = score
    return priorities


_CHALLENGE_MARKERS = (
    "access denied", "captcha", "challenge", "cloudflare", "forbidden",
    "incapsula", "just a moment", "robot check", "verify you are human",
    "temporarily blocked", "too many requests", "403", "429",
)


def _usable_specs(specs) -> bool:
    """Reject empty, whitespace-only, and common block-page payloads."""
    if not isinstance(specs, dict) or not specs:
        return False
    values = [str(value).strip() for value in specs.values() if value is not None]
    if not any(values):
        return False
    text = " ".join(values).casefold()
    return not any(marker in text for marker in _CHALLENGE_MARKERS)


def _load_ledger(v: str) -> set:
    p = _ledger(v)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")))


def make(vendors: list, limit: int | None) -> None:
    priorities = _core_gap_priorities()
    for v in vendors:
        done = _load_ledger(v)
        pending, seen = [], set()
        prioritized = 0
        for item in _load_jsonl(_listing(v)):
            sku = item.get("vendor_sku")
            url = item.get("url")
            if not sku or not url or sku in done or sku in seen:
                continue
            seen.add(sku)
            score = priorities.get((_normalize_vendor(v), str(url)), 0)
            pending.append((score, {"vendor_sku": sku, "url": url}))
        pending.sort(key=lambda entry: -entry[0])
        if limit:
            pending = pending[:limit]
        prioritized = sum(1 for score, _ in pending if score)
        pending_rows = [entry for _, entry in pending]
        _pending(v).parent.mkdir(parents=True, exist_ok=True)
        _pending(v).write_text(
            json.dumps(pending_rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(
            f"{v}: {len(pending_rows)} pending "
            f"({prioritized} core-coverage priority, {len(done)} already in ledger)"
        )


def mark(vendors: list) -> None:
    for v in vendors:
        done = _load_ledger(v)
        added = 0
        rejected = 0
        for item in _load_jsonl(_detail(v)):
            sku = item.get("vendor_sku")
            if not sku:
                continue
            # A DetailItem can still be emitted for a challenge/error page
            # or a page whose specification selector matched nothing. Such
            # rows must remain pending so they can be retried.
            if not _usable_specs(item.get("specs")):
                rejected += 1
                continue
            if sku in done:
                continue
            done.add(sku)
            added += 1
        if added:
            _ledger(v).parent.mkdir(parents=True, exist_ok=True)
            _ledger(v).write_text(
                json.dumps(sorted(done), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        print(
            f"{v}: +{added} marked done ({len(done)} total in ledger; "
            f"{rejected} empty/challenge rows rejected)"
        )


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
