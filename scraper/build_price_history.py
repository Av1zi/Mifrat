"""
Builds per-category price history for the product pages' price charts.

Reads today's catalog (product_id -> offers with vendor_id, vendor_sku
and url) plus every data/raw/YYYY-MM-DD/<vendor>.jsonl snapshot, then
emits data/site/history/<category>.json:

  {
    "dates": ["2026-08-22", ..., "2026-09-05"],
    "<product_id>": {"v": {"tms": [312, 309, null, ...], ...}}
  }

Only vendors that ever priced the product are included; a null entry
means the listing wasn't seen that day. Offer identity is (vendor,
vendor_sku) with a (vendor, url) fallback, because 1PC's numeric listing
ids were replaced by real MPNs in the catalog while raw snapshots still
carry the numeric ids.

Usage: called from normalize_and_match.py's main() right after the site
data is written. Safe to re-run standalone:
  python -m scraper.build_price_history
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
HISTORY_DIR = REPO_ROOT / "data" / "site" / "history"

# Plonter dropped 2026-09-29 (see decisions.md) — its series vanish from the
# charts along with its catalog offers (series are catalog-offer-driven; this
# tuple only controls which raw files get scanned). History files on disk keep
# old plonter points until the next rebuild prunes them.
SNAPSHOT_VENDORS = ("tms", "onepc", "ivory", "yahav", "ksp")


def _norm_vendor(vendor_id: str | None) -> str:
    return "onepc" if vendor_id in ("1pc", "onepc") else (vendor_id or "")


def _snapshot_dates(limit: int = 120) -> list[str]:
    """Date dirs (YYYY-MM-DD) that contain at least one vendor snapshot."""
    dates = []
    if not RAW_DIR.is_dir():
        return dates
    for child in RAW_DIR.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if len(name) != 10 or name[4] != "-" or name[7] != "-":
            continue
        if any((child / f"{v}.jsonl").exists() for v in SNAPSHOT_VENDORS):
            dates.append(name)
    dates.sort()
    return dates[-limit:]


def _load_snapshot_prices(
    dates: list[str],
) -> tuple[
    dict[str, dict[tuple[str, str], float | int | None]],
    dict[str, str],
]:
    """
    Per date: (norm_vendor, identity) -> price, where identity is both the
    vendor_sku key and the url key for every listing. A key seen twice in a
    day takes its newest `scraped_at` row (audit 2026-11-10 E: a second TMS
    crawl appended to 2026-11-09 and the first row's superseded price won).
    """
    per_date: dict[str, dict[tuple[str, str], float | int | None]] = {}
    scrape_times: dict[str, str] = {}
    for date in dates:
        index: dict[tuple[str, str], float | int | None] = {}
        seen_at: dict[tuple[str, str], str] = {}

        def put(key: tuple[str, str], price, at: str) -> None:
            if key not in index or at >= seen_at[key]:
                index[key] = price
                seen_at[key] = at

        for vendor_file in SNAPSHOT_VENDORS:
            path = RAW_DIR / date / f"{vendor_file}.jsonl"
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    vendor = _norm_vendor(item.get("vendor_id") or vendor_file)
                    price = item.get("price_ils")
                    if isinstance(price, str):
                        try:
                            price = float(price.replace(",", "").strip())
                        except ValueError:
                            price = None
                    if not isinstance(price, (int, float)):
                        # Still recorded: a newer unpriced row supersedes
                        # an older price (no point that day).
                        price = None
                    scraped_at = item.get("scraped_at")
                    if date not in scrape_times and isinstance(scraped_at, str) and scraped_at:
                        scrape_times[date] = scraped_at
                    at = scraped_at if isinstance(scraped_at, str) else ""
                    sku = str(item.get("vendor_sku") or "").strip()
                    url = str(item.get("url") or "").strip()
                    if sku:
                        put((vendor, f"sku:{sku}"), price, at)
                    if url:
                        put((vendor, f"url:{url}"), price, at)
        per_date[date] = index
    return per_date, scrape_times


def _offer_price(
    offer: dict,
    snapshots: dict[tuple[str, str], float | int | None],
) -> float | int | None:
    vendor = _norm_vendor(offer.get("vendor_id"))
    sku = str(offer.get("vendor_sku") or "").strip()
    if sku and (vendor, f"sku:{sku}") in snapshots:
        return snapshots[(vendor, f"sku:{sku}")]
    url = str(offer.get("url") or "").strip()
    if url:
        return snapshots.get((vendor, f"url:{url}"))
    return None


def _previous_history(history_dir: Path) -> dict[str, dict]:
    """History files from the build this run replaces (pid -> series)."""
    out: dict[str, dict] = {}
    if not history_dir.is_dir():
        return out
    for path in history_dir.glob("*.json"):
        try:
            with path.open(encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            out[path.stem] = payload
    return out


def _join_aliased_history(
    catalog: dict,
    dates: list[str],
    by_category: dict[str, dict[str, dict]],
    history_dir: Path,
) -> int:
    """Carry an old product id's series onto its successor (§3.6).

    The chart is rebuilt from raw snapshots, so a renamed product still gets
    its full line as long as the same offers are on sale. What is lost
    without this join is the vendor that stopped selling: its points only
    exist in the previous file, keyed by the old pid. Vendor ids are stable,
    so the old series can be grafted onto the successor; the two point lists
    line up only when both files cover the same dates.
    """
    aliases = catalog.get("pid_aliases") or {}
    if not aliases:
        return 0

    category_of: dict[str, str] = {}
    for product in catalog.get("products") or []:
        pid = product.get("product_id")
        category = product.get("category")
        if not pid or not category:
            continue
        if category in ("aio", "cooler_air"):
            category = "cpu_cooler"
        category_of[str(pid)] = category

    previous = _previous_history(history_dir)
    joined = 0
    for old_pid, new_pid in aliases.items():
        category = category_of.get(str(new_pid))
        if not category:
            continue
        old_entry = next(
            (payload[str(old_pid)] for payload in previous.values()
             if isinstance(payload.get(str(old_pid)), dict)),
            None,
        )
        if not old_entry:
            continue
        entry = by_category[category].setdefault(str(new_pid), {"v": {}})
        entry.setdefault("v", {})
        for vendor, points in (old_entry.get("v") or {}).items():
            if not isinstance(points, list) or len(points) != len(dates):
                continue
            current = entry["v"].get(vendor)
            if current is None:
                entry["v"][vendor] = list(points)
                joined += 1
            else:
                entry["v"][vendor] = [
                    new_point if new_point is not None else old_point
                    for new_point, old_point in zip(current, points)
                ]
    return joined


def build_price_history(
    catalog: dict,
    limit_days: int = 120,
    history_dir: Path = HISTORY_DIR,
) -> dict[str, int]:
    dates = _snapshot_dates(limit_days)
    if not dates:
        print("[warn] no raw snapshots found — writing empty history", file=sys.stderr)
    per_date, scrape_times = _load_snapshot_prices(dates)

    by_category: dict[str, dict[str, dict]] = defaultdict(dict)

    for product in catalog.get("products", []):
        pid = product.get("product_id")
        category = product.get("category")
        if not pid or not category:
            continue
        # aio + cooler_air ship as the single `cpu_cooler` site category
        # (mirrors site_data.SITE_CATEGORY).
        if category in ("aio", "cooler_air"):
            category = "cpu_cooler"
        series: dict[str, list] = {}
        for offer in product.get("offers", []):
            # A vendor's twin listing (matching.collapse_vendor_twins) is
            # not its offer, so it never draws the vendor's line.
            if offer.get("alias_of"):
                continue
            vendor = _norm_vendor(offer.get("vendor_id"))
            if not vendor or vendor in series:
                continue
            points = [_offer_price(offer, per_date[d]) for d in dates]
            if any(p is not None for p in points):
                series[vendor] = points
        if series:
            by_category[category][pid] = {"v": series}

    history_dir.mkdir(parents=True, exist_ok=True)
    joined = _join_aliased_history(catalog, dates, by_category, history_dir)
    if joined:
        print(f"[ok] joined {joined} vendor series across renamed product ids")
    counts: dict[str, int] = {}
    for category, items in by_category.items():
        payload = {
            "dates": dates,
            "timestamps": [scrape_times.get(date, f"{date}T00:00:00Z") for date in dates],
        }
        payload.update(items)
        out = history_dir / f"{category}.json"
        tmp = out.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(out)
        counts[category] = len(items)

    # Drop history files for categories that no longer have any series.
    wanted = {f"{c}.json" for c in by_category}
    for existing in history_dir.glob("*.json"):
        if existing.name not in wanted:
            existing.unlink()

    total = sum(counts.values())
    print(f"[ok] wrote price history for {total} products ({len(dates)} days)")
    return counts


def main() -> None:
    catalog_path = REPO_ROOT / "data" / "catalog.json"
    if not catalog_path.exists():
        print("[error] data/catalog.json not found — run normalize first", file=sys.stderr)
        sys.exit(1)
    with catalog_path.open(encoding="utf-8") as f:
        catalog = json.load(f)
    build_price_history(catalog)


if __name__ == "__main__":
    main()
