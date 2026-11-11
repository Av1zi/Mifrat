"""Gate: a listing seen twice in one vendor-day shows its newest row (audit 2026-11-10 E).

A vendor-day file can hold one listing key more than once: the same item on
two category pages of one crawl (normal), or two crawls appended to one file
(TMS 2026-11-09, 18h apart: 67 keys changed price and the offer showed the
superseded price on 25). Owner Q2: never drop a crawl's data; the newest
`scraped_at` row wins. So, for every repeated key:

  1. the catalog listing (data/catalog.json, built from the vendor's latest
     day) carries the newest row's price and stock
     (`matching.dedupe_enriched_listings`);
  2. the price-history point for that day is the newest row's price
     (`build_price_history._load_snapshot_prices`).

Also (audit H, 2026-11-12): a TMS new-PC deal row whose deal price is at or
above its price is a misread tile; hard on the newest day once the fixed
tile parser (`tile_parser` >= 2) wrote it, a warning otherwise.

A vendor-day whose repeats come from two separate runs (more than
`matching._SAME_CRAWL_HOURS` apart) is reported as a warning: the cause is
the Nano run honouring its success marker (`nano/run_tms.sh`).

    python scripts/check_snapshot_rows.py --self-test
    python scripts/check_snapshot_rows.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper import build_price_history  # noqa: E402
from scraper.matching import (  # noqa: E402
    _SAME_CRAWL_HOURS,
    _scraped_at,
    dedupe_enriched_listings,
    enrich_listing,
    listing_key,
    normalize_price,
)

RAW = ROOT / "data" / "raw"
CATALOG = ROOT / "data" / "catalog.json"
VENDOR_FILE = {"1pc": "onepc"}


def _rows(path: Path) -> dict[str, list[dict]]:
    """listing key -> raw rows, in file order."""
    vendor = "1pc" if path.stem == "onepc" else path.stem
    out: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row.setdefault("vendor_id", vendor)
            out[listing_key(row)].append(row)
    return out


def _newest(rows: list[dict]) -> dict:
    best = rows[0]
    for row in rows[1:]:
        if _scraped_at(row) >= _scraped_at(best):
            best = row
    return best


def _price(value):
    price = normalize_price(value)
    return float(price) if isinstance(price, (int, float)) else None


def _repeats(path: Path) -> tuple[dict[str, list[dict]], float]:
    repeated = {k: v for k, v in _rows(path).items() if len(v) > 1}
    span = 0.0
    for rows in repeated.values():
        stamps = [_scraped_at(r) for r in rows]
        span = max(span, (max(stamps) - min(stamps)).total_seconds() / 3600)
    return repeated, span


def check_catalog(catalog: dict, failures: list[str], warnings: list[str]) -> int:
    by_file: dict[Path, list[dict]] = defaultdict(list)
    for listing in catalog.get("listings") or []:
        vendor = str(listing.get("vendor_id") or "")
        day = str(listing.get("last_seen") or "")
        if vendor and day:
            by_file[RAW / day / f"{VENDOR_FILE.get(vendor, vendor)}.jsonl"].append(listing)
    checked = 0
    for path, listings in sorted(by_file.items()):
        if not path.exists():
            continue
        repeated, span = _repeats(path)
        if span > _SAME_CRAWL_HOURS:
            warnings.append(f"{path.parent.name}/{path.name}: repeats from two runs, "
                            f"{span:.0f}h apart")
        for listing in listings:
            rows = repeated.get(listing.get("listing_key"))
            if not rows:
                continue
            checked += 1
            newest = _newest(rows)
            want = (_price(newest.get("price_ils")), newest.get("in_stock"))
            got = (_price(listing.get("price_ils")), listing.get("in_stock"))
            if want != got:
                failures.append(f"catalog {listing['listing_key']} ({path.parent.name}): "
                                f"price/stock {got}, newest row {want}")
    return checked


def check_history(failures: list[str], warnings: list[str], seen: set[str]) -> int:
    dates = build_price_history._snapshot_dates()
    targets: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for date in dates:
        for vendor_file in build_price_history.SNAPSHOT_VENDORS:
            path = RAW / date / f"{vendor_file}.jsonl"
            if not path.exists():
                continue
            repeated, span = _repeats(path)
            note = f"{date}/{path.name}: repeats from two runs, {span:.0f}h apart"
            if span > _SAME_CRAWL_HOURS and note not in seen:
                warnings.append(note)
            for rows in repeated.values():
                targets[date].append((vendor_file, _newest(rows)))
    if not targets:
        return 0
    per_date, _ = build_price_history._load_snapshot_prices(sorted(targets))
    checked = 0
    for date, items in sorted(targets.items()):
        index = per_date[date]
        for vendor_file, row in items:
            vendor = build_price_history._norm_vendor(row.get("vendor_id") or vendor_file)
            sku = str(row.get("vendor_sku") or "").strip()
            url = str(row.get("url") or "").strip()
            key = (vendor, f"sku:{sku}") if sku else (vendor, f"url:{url}")
            if key not in index:
                continue
            checked += 1
            got = index[key]
            got = float(got) if isinstance(got, (int, float)) else None
            if got != _price(row.get("price_ils")):
                failures.append(f"history {date} {vendor} {key[1]}: point {got}, "
                                f"newest row {row.get('price_ils')}")
    return checked


def deal_parse_errors(path: Path) -> tuple[list[str], bool]:
    """TMS new-PC deal rows whose deal price is not below the price (audit H).

    A real "הנחת New PC" tile holds the regular price and a cheaper deal
    price. A deal row with promo >= price is a misread tile: on 2026-11-09..11
    the old spider read every "-N%" store-wide sale tile (crossed-out old
    price + current price) as a new-PC deal with promo == price. Returns the
    bad keys and whether the file was written by the fixed tile parser
    (`tile_parser` >= 2 on its rows), which makes the errors hard.
    """
    bad: list[str] = []
    fixed = False
    for key, rows in _rows(path).items():
        for row in rows:
            if (row.get("tile_parser") or 0) >= 2:
                fixed = True
            deal = (row.get("promo_kind") == "tms-new-pc"
                    or "new-pc-deal" in str(row.get("category_guess") or ""))
            price, promo = _price(row.get("price_ils")), _price(row.get("price_promo_ils"))
            if deal and price is not None and promo is not None and promo >= price:
                bad.append(f"{key} (price {price:g}, deal {promo:g}, "
                           f"sticker {row.get('promo_text_raw')!r})")
                break
    return bad, fixed


def check_deal_rows(failures: list[str], warnings: list[str]) -> int:
    """Newest TMS day: misread deal rows fail once the fixed spider wrote it;
    older days (and the newest one before the Nano pulls the fix) warn."""
    days = sorted(p for p in RAW.glob("*/tms.jsonl") if p.parent.name[:2] == "20")
    checked = 0
    for path in days[-14:]:
        bad, fixed = deal_parse_errors(path)
        checked += 1
        if not bad:
            continue
        line = (f"{path.parent.name}/tms.jsonl: {len(bad)} new-PC deal row(s) with the deal "
                f"price at or above the price (misread sale tile), e.g. {bad[0]}")
        if path == days[-1] and fixed:
            failures.append(line)
        else:
            warnings.append(line + (" [old spider; normalize reads them as sales]"
                                    if not fixed else ""))
    return checked


def self_test() -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tms.jsonl"
        sale = {"vendor_id": "tms", "vendor_sku": "CC-9011296-WW", "url": "u1",
                "price_ils": 415, "price_promo_ils": 415, "promo_text_raw": "-12%",
                "promo_kind": "tms-new-pc", "category_guess": "case:new-pc-deal"}
        deal = {"vendor_id": "tms", "vendor_sku": "5600J3636D32GX2-RS5K", "url": "u2",
                "price_ils": 4437, "price_promo_ils": 3993, "promo_text_raw": "הנחת New PC",
                "promo_kind": "tms-new-pc", "category_guess": "ram:new-pc-deal"}
        for rows, want_bad, want_fixed in (
                ([sale, deal], 1, False),
                ([dict(sale, tile_parser=2), dict(deal, tile_parser=2)], 1, True),
                ([deal, dict(sale, price_promo_ils=None, promo_kind="tms-sale",
                             price_was_ils=474, category_guess="case", tile_parser=2)], 0, True)):
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                            encoding="utf-8")
            bad, fixed = deal_parse_errors(path)
            if (len(bad), fixed) != (want_bad, want_fixed):
                errors.append(f"deal_parse_errors {len(bad)} bad, fixed={fixed}; "
                              f"want {want_bad}, {want_fixed}")
    base = {"vendor_id": "tms", "vendor_sku": "CW-9061018-WW", "category_guess": "cpu cooler",
            "url": "https://tms.co.il/x", "title_raw": "Corsair iCUE LINK TITAN 360 RX"}
    first = dict(base, price_ils=843, in_stock=True, scraped_at="2026-11-09T03:37:01+00:00")
    second = dict(base, price_ils=745, in_stock=False, category_guess="cpu cooler:new-pc-deal",
                  scraped_at="2026-11-09T21:29:45+00:00")
    # Older crawl first or last in the file: the newest row wins either way.
    for order in ((first, second), (second, first)):
        out = dedupe_enriched_listings([enrich_listing(dict(r)) for r in order])
        if len(out) != 1 or (out[0].get("price_ils"), out[0].get("in_stock"),
                             out[0].get("new_pc_deal")) != (745, False, True):
            errors.append(f"dedupe kept {[(o.get('price_ils'), o.get('in_stock')) for o in out]}, "
                          "want the newest row (745, out of stock, new-pc-deal)")
    # A lower older price must not win (the pre-fix rule was "lowest price").
    cheap_old = dict(first, price_ils=600)
    out = dedupe_enriched_listings([enrich_listing(dict(cheap_old)), enrich_listing(dict(second))])
    if out[0].get("price_ils") != 745:
        errors.append(f"dedupe took the older lower price {out[0].get('price_ils')}")

    with tempfile.TemporaryDirectory() as tmp:
        day = Path(tmp) / "2026-11-09"
        day.mkdir()
        (day / "tms.jsonl").write_text(
            "\n".join(json.dumps(r) for r in (second, cheap_old)) + "\n", encoding="utf-8")
        saved = build_price_history.RAW_DIR
        build_price_history.RAW_DIR = Path(tmp)
        try:
            per_date, _ = build_price_history._load_snapshot_prices(["2026-11-09"])
        finally:
            build_price_history.RAW_DIR = saved
        point = per_date["2026-11-09"].get(("tms", "sku:CW-9061018-WW"))
        if point != 745:
            errors.append(f"history point {point}, want the newest row's 745")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    errors = self_test()
    if errors:
        print("[snapshot-rows] FAIL - self-test")
        for error in errors:
            print(f"  - {error}")
        return 1
    if args.self_test:
        print("[snapshot-rows] self-test pass")
        return 0

    if not CATALOG.exists():
        print(f"[error] {CATALOG} not found - run the normalizer first", file=sys.stderr)
        return 1
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    failures: list[str] = []
    warnings: list[str] = []
    n_catalog = check_catalog(catalog, failures, warnings)
    n_history = check_history(failures, warnings, set(warnings))
    check_deal_rows(failures, warnings)
    for warning in warnings:
        print(f"[warn] {warning}")
    if failures:
        print(f"[snapshot-rows] FAIL - {len(failures)} repeated key(s) not on their newest row")
        for failure in failures[:40]:
            print(f"  - {failure}")
        return 1
    print(f"[snapshot-rows] pass - {n_catalog} catalog listings and {n_history} history "
          "points of repeated keys carry their newest row")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
