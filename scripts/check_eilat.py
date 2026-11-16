"""Gate: Eilat prices are scraped, attached and kept out of regular prices.

Offline (code level). Pins:
  1. the Ivory tile parser on saved category tiles (Eilat price, sale price,
     a tile with no Eilat price gives no row);
  2. the KSP bms parser (an item not sold in Eilat and the "Error Code: 851"
     no-session answer are told apart);
  3. TMS Eilat-branch stock and the Eilat-mode URL;
  4. `eilat.attach`: twins get the Eilat price, an implausible one is
     dropped, a thin crawl is partial, Eilat-only items come only from a
     fresh, complete TMS crawl and never carry a regular price;
  5. the site row: `eilat_min_price` never changes `min_price`, and an
     Eilat-only offer never sets it;
  6. price history ignores Eilat rows, Eilat files and Eilat-only offers.

    python scripts/check_eilat.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from scrapy.http import HtmlResponse  # noqa: E402

from scraper import build_price_history, eilat  # noqa: E402
from scraper.matching import enrich_listing, offer_from_listing  # noqa: E402
from scraper.site_data import _trim_product  # noqa: E402
from scraper.spiders.ivory_eilat import parse_tiles  # noqa: E402
from scraper.spiders.ksp_eilat import parse_bms  # noqa: E402
from scraper.spiders.tms_eilat import eilat_branch_stock, eilat_url  # noqa: E402

FIXTURES = ROOT / "scraper" / "fixtures" / "eilat"
problems: list[str] = []


def expect(label: str, got, want) -> None:
    if got != want:
        problems.append(f"{label}: got {got!r}, want {want!r}")


def tiles(name: str) -> dict[str, dict]:
    body = (FIXTURES / name).read_bytes()
    resp = HtmlResponse(url="https://www.ivory.co.il/catalog.php?act=cat&id=1", body=body, encoding="utf-8")
    return {t["id"]: t for t in parse_tiles(resp)}


def check_ivory() -> None:
    case = tiles("ivory_tiles.html")
    expect("ivory plain Eilat tile", (case.get("157396") or {}).get("eilat"), 372)
    sale = tiles("ivory_tiles_sale.html")
    expect("ivory sale tile reads the Eilat sale price", (sale.get("37837") or {}).get("eilat"), 419)
    cpu = tiles("ivory_tiles_cpu.html")
    expect("ivory Eilat tile", (cpu.get("45329") or {}).get("eilat"), 507)
    expect("ivory regular price beside it", (cpu.get("45329") or {}).get("regular"), 599)
    expect("ivory tile without an Eilat price gives no row", "85530" in cpu, False)


def check_ksp() -> None:
    payload = {"result": {
        "390282": {"uin": 390282, "price": 2999, "eilat_price": 2542, "is_eilat": True},
        "396383": {"uin": 396383, "price": 106, "eilat_price": None, "is_eilat": False},
        "369217": {"uin": 369217, "price": 4160, "eilat_price": 3525, "is_eilat": True,
                   "discount": {"value": 4110, "value_eilat": 3483}},
    }}
    rows = parse_bms(payload)
    expect("ksp Eilat item", (rows or {}).get("390282", {}).get("eilat"), 2542)
    expect("ksp item not sold in Eilat gives no row", "396383" in (rows or {}), False)
    expect("ksp Eilat sale price kept aside", (rows or {}).get("369217", {}).get("eilat_sale"), 3483)
    expect("ksp no-session answer is a failure, not 'not in Eilat'",
           parse_bms({"result": "Error Code: 851"}), None)


def check_tms() -> None:
    row = {"BranchAvailability": [{"name": "נתניה", "inStock": True}, {"name": "אילת", "inStock": False}]}
    expect("tms Eilat branch stock", eilat_branch_stock(row), False)
    expect("tms no branch list", eilat_branch_stock({}), None)
    expect("tms Eilat URL", eilat_url("https://tms.co.il/hard-drives?page=2"),
           "https://tms.co.il/hard-drives?page=2&eilat=1")
    expect("tms Eilat URL is idempotent", eilat_url("https://tms.co.il/x?eilat=1"), "https://tms.co.il/x?eilat=1")


def listing(vendor: str, sku: str, price: int, url: str | None = None) -> dict:
    return enrich_listing({"vendor_id": vendor, "vendor_sku": sku, "url": url or f"https://{vendor}.example/{sku}",
                           "title_raw": f"Part {sku}", "price_ils": price, "in_stock": True,
                           "category_guess": "ssd", "scraped_at": "2026-11-16T01:00:00+00:00"})


def eilat_row(vendor: str, sku: str, price: int, stock=None) -> dict:
    return {"vendor_id": vendor, "vendor_sku": sku, "url": f"https://{vendor}.example/{sku}",
            "title_raw": f"Part {sku}", "price_ils": price, "in_stock": stock, "channel": "eilat",
            "category_guess": "ssd", "scraped_at": "2026-11-16T02:00:00+00:00"}


def check_attach() -> None:
    regular = [listing("tms", f"S{i}", 1000) for i in range(4)]
    rows = {e["listing_key"]: eilat_row("tms", e["vendor_sku"], 847, True) for e in regular[:3]}
    rows["tms:S1"]["price_ils"] = 400                        # implausible: dropped
    only = eilat_row("tms", "ONLY", 500, True)
    rows["tms:ONLY"] = only
    out = eilat.attach("tms", regular, rows, eilat_stale=False, main_stale=False,
                       seen_day="2026-11-16", snapshot_day="2026-11-16")
    expect("attach state", out.state, eilat.FRESH)
    expect("attach matched", out.matched, 2)
    expect("attach implausible", out.implausible, 1)
    expect("twin gets the Eilat price", regular[0].get("eilat_price_ils"), 847)
    expect("twin keeps its regular price", regular[0].get("price_ils"), 1000)
    expect("implausible price not attached", "eilat_price_ils" in regular[1], False)
    expect("item missing from Eilat has no Eilat price", "eilat_price_ils" in regular[3], False)
    expect("one Eilat-only item", len(out.eilat_only or []), 1)
    o = (out.eilat_only or [{}])[0]
    expect("Eilat-only has no regular price", o.get("price_ils"), None)
    expect("Eilat-only row is no Eilat-channel row any more", "channel" in o, False)

    # A stale regular snapshot or a non-discovering vendor: no Eilat-only items.
    again = [listing("tms", f"S{i}", 1000) for i in range(2)]
    rows2 = {e["listing_key"]: eilat_row("tms", e["vendor_sku"], 847) for e in again}
    rows2["tms:ONLY"] = only
    out = eilat.attach("tms", again, rows2, eilat_stale=False, main_stale=True,
                       seen_day=None, snapshot_day="2026-11-15")
    expect("stale regular snapshot makes no Eilat-only", len(out.eilat_only or []), 0)
    ivory = [listing("ivory", "A", 600, "https://www.ivory.co.il/catalog.php?id=1")]
    out = eilat.attach("ivory", ivory, {"ivory:2": {**eilat_row("ivory", "", 400),
                                                   "url": "https://www.ivory.co.il/catalog.php?id=2"}},
                       eilat_stale=False, main_stale=False, seen_day=None, snapshot_day=None)
    expect("ivory never discovers Eilat-only", len(out.eilat_only or []), 0)
    expect("ivory with no twin matched is partial", out.state, eilat.PARTIAL)

    # A thin Eilat crawl: partial, and no Eilat-only items.
    many = [listing("tms", f"M{i}", 1000) for i in range(10)]
    thin = {many[0]["listing_key"]: eilat_row("tms", "M0", 847), "tms:ONLY": only}
    out = eilat.attach("tms", many, thin, eilat_stale=False, main_stale=False,
                       seen_day=None, snapshot_day=None)
    expect("thin crawl is partial", out.state, eilat.PARTIAL)
    expect("partial crawl makes no Eilat-only", len(out.eilat_only or []), 0)


def check_site_row() -> None:
    base = listing("tms", "X1", 1000)
    base.update(eilat_price_ils=847, eilat_in_stock=True, eilat_stale=False)
    plain = listing("ksp", "X1", 1100)
    only = enrich_listing({**eilat_row("ivory", "Y", 700), "channel": None})
    only.update(price_ils=None, in_stock=False, eilat_price_ils=700, eilat_in_stock=True, eilat_only=True)
    product = {"product_id": "p1", "category": "storage", "canonical_name": "X",
               "offers": [offer_from_listing(e) for e in (base, plain, only)]}
    row = _trim_product(product)
    expect("min_price stays the regular minimum", row["min_price"], 1000)
    expect("eilat_min_price is the Eilat minimum", row.get("eilat_min_price"), 700)
    expect("mixed product is not Eilat-only", row.get("eilat_only"), None)
    shipped = {o["vendor"]: o for o in row["offers"]}
    expect("site offer carries the Eilat price", shipped["tms"].get("eilat_price"), 847)
    expect("Eilat-only offer has no regular price", shipped["ivory"]["price"], None)
    alone = _trim_product({"product_id": "p2", "category": "storage", "canonical_name": "Y",
                           "offers": [offer_from_listing(only)]})
    expect("Eilat-only product has no min_price", alone["min_price"], None)
    expect("Eilat-only product is flagged", alone.get("eilat_only"), True)


def check_matching() -> None:
    """End to end through the matcher: an Eilat-only item becomes a product
    (or an offer) of its own and never moves a regular price."""
    from scraper.matching import match_listings

    def reg(vendor: str, sku: str, price: int) -> dict:
        e = enrich_listing({"vendor_id": vendor, "vendor_sku": sku, "url": f"https://{vendor}.example/{sku}",
                            "title_raw": "Samsung 990 PRO 2TB NVMe SSD MZ-V9P2T0BW", "price_ils": price,
                            "in_stock": True, "category_guess": "ssd",
                            "scraped_at": "2026-11-16T01:00:00+00:00"})
        e.update(last_seen="2026-11-16", seen_day="2026-11-16", stale=False)
        return e

    tms, ksp = reg("tms", "MZ-V9P2T0BW", 800), reg("ksp", "123", 820)
    rows = {"tms:MZ-V9P2T0BW": eilat_row("tms", "MZ-V9P2T0BW", 678, True),
            "tms:ELTPCG03": {**eilat_row("tms", "ELTPCG03", 3000, True),
                             "title_raw": "TMS EILAT AMD PRO - מחשב מורכב", "category_guess": "case"}}
    out = eilat.attach("tms", [tms], rows, eilat_stale=False, main_stale=False,
                       seen_day="2026-11-16", snapshot_day="2026-11-16")
    result = match_listings([tms, ksp] + [enrich_listing(r) for r in out.eilat_only])
    rows_by_offer = {}
    for product in result["products"]:
        row = _trim_product(product)
        for o in row["offers"]:
            rows_by_offer[(o["vendor"], o["url"])] = row
    ssd = rows_by_offer.get(("tms", "https://tms.example/MZ-V9P2T0BW")) or {}
    expect("matched product keeps its regular min", ssd.get("min_price"), 800)
    expect("matched product carries the Eilat min", ssd.get("eilat_min_price"), 678)
    only = rows_by_offer.get(("tms", "https://tms.example/ELTPCG03")) or {}
    expect("Eilat-only item is on the site", bool(only), True)
    expect("Eilat-only item has no regular min", only.get("min_price"), None)
    expect("Eilat-only item has its Eilat min", only.get("eilat_min_price"), 3000)


def check_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        day = Path(tmp) / "2026-11-16"
        day.mkdir()
        regular = {"vendor_id": "tms", "vendor_sku": "H1", "url": "u", "price_ils": 1000,
                   "scraped_at": "2026-11-16T01:00:00+00:00"}
        stray = dict(regular, price_ils=847, channel="eilat", scraped_at="2026-11-16T02:00:00+00:00")
        (day / "tms.jsonl").write_text("\n".join(json.dumps(r) for r in (regular, stray)) + "\n", encoding="utf-8")
        (day / "tms_eilat.jsonl").write_text(json.dumps(dict(stray, vendor_sku="H2")) + "\n", encoding="utf-8")
        saved = build_price_history.RAW_DIR
        build_price_history.RAW_DIR = Path(tmp)
        try:
            per_date, _ = build_price_history._load_snapshot_prices(["2026-11-16"])
        finally:
            build_price_history.RAW_DIR = saved
        index = per_date["2026-11-16"]
        expect("history point is the regular price", index.get(("tms", "sku:H1")), 1000)
        expect("history never reads the Eilat file", ("tms", "sku:H2") in index, False)
    expect("Eilat files are not history vendors",
           set(eilat.spider_names()) & set(build_price_history.SNAPSHOT_VENDORS), set())


def main() -> int:
    for check in (check_ivory, check_ksp, check_tms, check_attach, check_site_row, check_matching,
                  check_history):
        try:
            check()
        except Exception as exc:  # a crashed case is a failed case
            problems.append(f"{check.__name__} crashed: {type(exc).__name__}: {exc}")
    if problems:
        print(f"[eilat] FAIL - {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("[eilat] pass - parsers, attach, site row and history rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
