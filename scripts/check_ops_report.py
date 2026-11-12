"""Gate: the ops report (scraper/ops) reads crawls and lifecycles correctly.

Offline, synthetic fixtures only (no data/raw needed):

  1. a file holding two crawls >6h apart is two crawls; the first is
     `misfiled` when its UTC day is not the file's day (TMS 2026-11-11);
  2. a crawl starting outside 21:00-04:00 UTC is `outside_window`;
  3. a vendor's first crawl is its baseline: no `new` events;
  4. one absence is `missing`, not gone (1PC flaps ~50 rows a day);
  5. two absences spanning >= 36h are one `gone` event; two absences 12h
     apart are not;
  6. a suspect (partial) crawl never counts an absence;
  7. a gone listing seen again is one `returned` event;
  8. a product of only new listings is `new_product`; a new listing in an
     existing product is `vendor_added`, never `new_product`;
  9. a gone listing whose product is still listed is `vendor_lost`; whose
     product left the catalog is `product_gone`; a pid alias is neither;
 10. price moves under PRICE_EVENT_SHARE are counted, not evented;
 11. a U+200E in a SKU keys like the clean SKU (normalize's clean_text);
 12. the report's files carry schema + generated_at and stay under budget.

    python scripts/check_ops_report.py --self-test
    python scripts/check_ops_report.py          # + the written data/ops/
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper.ops import lifecycle, report  # noqa: E402
from scraper.ops.snapshots import load_crawls, split_crawls  # noqa: E402

OPS = ROOT / "data" / "ops"
# Budgets for the shipped files (the admin page downloads status + changes).
MAX_BYTES = {"status.json": 300_000, "changes.json": 3_000_000, "memory.json": 4_000_000}

T0 = datetime(2026, 11, 1, 22, 0, tzinfo=timezone.utc)


def _rows(vendor: str, at: datetime, skus: list[str], price: int = 100,
          prices: dict[str, int] | None = None) -> list[dict]:
    vid = "1pc" if vendor == "onepc" else vendor
    base = {"onepc": "https://1pc.co.il/web/product/", "ivory": "https://www.ivory.co.il/catalog.php?id="}
    out = []
    for sku in skus:
        url = base.get(vendor, f"https://{vendor}.example/p/") + sku
        out.append({"vendor_id": vid, "vendor_sku": sku, "url": url,
                    "title_raw": f"part {sku}", "price_ils": (prices or {}).get(sku, price),
                    "in_stock": True, "category_guess": "cpu",
                    "scraped_at": at.isoformat()})
    return out


def _skus(n: int, prefix: str = "S") -> list[str]:
    return [f"{prefix}{i:04d}" for i in range(n)]


class Raw:
    """A temp data/raw/ tree."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def write(self, day: str, vendor: str, rows: list[dict], append: bool = False) -> None:
        path = self.dir / day / f"{vendor}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if append else "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def close(self) -> None:
        self.tmp.cleanup()


def _nightly(raw: Raw, vendor: str, nights: list[list[str]], start: datetime = T0,
             prices: list[dict[str, int]] | None = None) -> None:
    for i, skus in enumerate(nights):
        at = start + timedelta(days=i)
        raw.write(at.strftime("%Y-%m-%d"), vendor,
                  _rows(vendor, at, skus, prices=(prices[i] if prices else None)))


def _replay(raw: Raw, catalog: dict | None = None, now: datetime | None = None,
            onboarding: set[str] | None = None, memory: dict | None = None):
    now = now or T0 + timedelta(days=30)
    crawls = load_crawls(raw.dir, now, 60)
    return lifecycle.replay(crawls, catalog or {}, memory, onboarding or set())


def _types(out, kind: str) -> list[dict]:
    return [e for e in out.events if e["type"] == kind]


def self_test() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{name}: {detail}")

    big = _skus(2000)                      # over every registry floor

    # 1-2. Double crawl in one file, misfiled first crawl, outside window.
    first = datetime(2026, 11, 10, 22, 23, tzinfo=timezone.utc)
    second = datetime(2026, 11, 11, 21, 30, tzinfo=timezone.utc)
    rows = _rows("tms", first, big[:5]) + _rows("tms", second, big[:5])
    crawls = split_crawls("tms", "2026-11-11", rows)
    check("1 double crawl", len(crawls) == 2, f"{len(crawls)} crawls")
    check("1 misfiled", crawls[0].misfiled and not crawls[1].misfiled,
          f"{[c.misfiled for c in crawls]}")
    check("1 crawls_in_file", all(c.crawls_in_file == 2 for c in crawls), "")
    late = split_crawls("ivory", "2026-11-12",
                        _rows("ivory", datetime(2026, 11, 12, 5, 10, tzinfo=timezone.utc), ["a"]))
    check("2 outside window", late[0].outside_window, "05:10 UTC is outside")
    check("2 inside window", not crawls[1].outside_window, "21:30 UTC is inside")
    # Same crawl, two pages minutes apart: one crawl.
    one = split_crawls("tms", "2026-11-12", _rows("tms", first, ["a"]) +
                       _rows("tms", first + timedelta(minutes=7), ["b"]))
    check("1 one crawl", len(one) == 1 and one[0].keys == 2, f"{len(one)}")

    # 3-5. Baseline, flapping, gone after two absences >= 36h.
    raw = Raw()
    try:
        nights = [big, big[:-1], big, big[:-2], big[:-2], big[:-2]]
        _nightly(raw, "onepc", nights)
        out = _replay(raw)
        summaries = out.crawls
        check("3 baseline", summaries[0]["baseline"] and summaries[0]["new"] == 0,
              f"{summaries[0]}")
        check("3 no new events", not _types(out, "new"), f"{len(_types(out, 'new'))}")
        gone = _types(out, "gone")
        gone_skus = sorted(e["url"].rsplit("/", 1)[-1] for e in gone)
        # big[-1]: absent night 2 (missing), back night 3, absent 4-6 -> gone
        # once, at its second absence (night 5); big[-2]: absent 4-6 -> same.
        check("4 one absence is missing", summaries[1]["missing"] == 1 and
              summaries[1]["gone"] == 0, f"{summaries[1]}")
        check("5 gone once each", gone_skus == sorted([big[-2], big[-1]]), f"{gone_skus}")
        check("5 gone at second absence", all(e["at"].startswith("2026-11-05") for e in gone),
              f"{[e['at'] for e in gone]}")
    finally:
        raw.close()

    raw = Raw()
    try:
        # Two absences, the second only 30h after the last sighting (a
        # same-day re-run): still missing, not gone.
        a = T0
        raw.write("2026-11-01", "tms", _rows("tms", a, big))
        raw.write("2026-11-02", "tms", _rows("tms", a + timedelta(hours=24), big[1:]))
        raw.write("2026-11-02", "tms", _rows("tms", a + timedelta(hours=30), big[1:]), append=True)
        out = _replay(raw)
        check("5 not gone within 36h", not _types(out, "gone"),
              f"{[e['at'] for e in _types(out, 'gone')]}")
        check("5 state missing", out.listings[f"tms:{big[0]}"].state == "missing",
              out.listings[f"tms:{big[0]}"].state)
    finally:
        raw.close()

    raw = Raw()
    try:
        # Three crawls 6h+ apart in under 36h (manual re-runs): two absences,
        # but only 13h since the last sighting, so still missing.
        a = T0
        raw.write("2026-11-01", "tms", _rows("tms", a, big))
        raw.write("2026-11-01", "tms", _rows("tms", a + timedelta(hours=7), big[1:]), append=True)
        raw.write("2026-11-02", "tms", _rows("tms", a + timedelta(hours=14), big[1:]))
        out = _replay(raw)
        check("5 two absences under 36h", out.listings[f"tms:{big[0]}"].state == "missing"
              and not _types(out, "gone"), out.listings[f"tms:{big[0]}"].state)
    finally:
        raw.close()

    raw = Raw()
    try:
        # One absence after a 5-day scrape gap (KSP 11-07 -> 11-12): the
        # listing is 5 days stale but was missed by ONE crawl, so missing.
        raw.write("2026-11-07", "ksp", _rows("ksp", T0, big))
        raw.write("2026-11-12", "ksp", _rows("ksp", T0 + timedelta(days=5), big[1:]))
        out = _replay(raw)
        check("4 one absence after a gap", out.listings[f"ksp:{big[0]}"].state == "missing"
              and not _types(out, "gone"), out.listings[f"ksp:{big[0]}"].state)
    finally:
        raw.close()

    # 6. A suspect crawl never counts an absence.
    raw = Raw()
    try:
        _nightly(raw, "tms", [big, big, big[:900], big[:900], big])
        out = _replay(raw)
        check("6 suspect flagged", out.crawls[2]["suspect"] is not None, f"{out.crawls[2]}")
        check("6 no mass gone", not _types(out, "gone"), f"{len(_types(out, 'gone'))} gone")
    finally:
        raw.close()

    # 7. Gone, then seen again: one returned event.
    raw = Raw()
    try:
        _nightly(raw, "tms", [big, big[1:], big[1:], big[1:], big])
        out = _replay(raw)
        ret = _types(out, "returned")
        check("7 returned", len(ret) == 1 and ret[0]["key"] == f"tms:{big[0]}", f"{ret}")
        check("7 gone days", ret and ret[0]["gone_days"] == 4, f"{ret}")
        check("7 active again", out.listings[f"tms:{big[0]}"].state == "active", "")
    finally:
        raw.close()

    # 8-9. Product events.
    raw = Raw()
    try:
        _nightly(raw, "tms", [big, big + ["NEW1"], big + ["NEW1"], big[2:] + ["NEW1"],
                              big[2:] + ["NEW1"]])
        _nightly(raw, "ivory", [big[:600], big[:600] + ["X9"], big[:600] + ["X9"],
                                big[:600] + ["X9"], big[:600] + ["X9"]])
        catalog = {
            "products": [
                {"product_id": "p-new", "canonical_name": "Brand New", "category": "cpu",
                 "best_offer": {"price_ils": 100}},
                {"product_id": "p-old", "canonical_name": "Old Part", "category": "cpu"},
                {"product_id": "p-kept", "canonical_name": "Kept", "category": "cpu"},
            ],
            "listings": [
                {"listing_key": "tms:NEW1", "product_id": "p-new"},
                {"listing_key": f"tms:{big[5]}", "product_id": "p-old"},
                {"listing_key": "ivory:X9", "product_id": "p-old"},
                {"listing_key": f"ivory:{big[1]}", "product_id": "p-kept"},
            ],
            "pid_aliases": {"p-renamed": "p-kept"},
        }
        memory = {"pids": {f"tms:{big[0]}": "p-gone", f"tms:{big[1]}": "p-renamed"},
                  "products": {"p-gone": ["Gone Part", "cpu"], "p-renamed": ["Kept", "cpu"]}}
        out = _replay(raw, catalog, memory=memory)
        new_products = {e["pid"] for e in _types(out, "new_product")}
        check("8 new_product", new_products == {"p-new"}, f"{new_products}")
        added = {(e["pid"], e["vendor"]) for e in _types(out, "vendor_added")}
        check("8 vendor_added", added == {("p-old", "ivory")}, f"{added}")
        gone_products = {e["pid"] for e in _types(out, "product_gone")}
        check("9 product_gone", gone_products == {"p-gone"}, f"{gone_products}")
        lost = {(e["pid"], e["vendor"]) for e in _types(out, "vendor_lost")}
        check("9 alias is vendor_lost", lost == {("p-kept", "tms")}, f"{lost}")
        mem = lifecycle.next_memory(out)
        check("9 memory keeps gone pid", mem["pids"].get(f"tms:{big[0]}") == "p-gone",
              f"{mem['pids'].get(f'tms:{big[0]}')}")
    finally:
        raw.close()

    raw = Raw()
    try:
        # A retired product (no alias) whose TMS listing is gone while its
        # Ivory listing is only missing: undecided, no product event yet. Once
        # Ivory's is gone too, one product_gone.
        _nightly(raw, "tms", [big] + [big[1:]] * 4)
        _nightly(raw, "ivory", [big[:600]] * 4 + [big[1:600]])
        memory = {"pids": {f"tms:{big[0]}": "p-old", f"ivory:{big[0]}": "p-old"},
                  "products": {"p-old": ["Old", "cpu"]}}
        out = _replay(raw, {}, memory=memory)
        events = [e["type"] for e in out.events if e.get("pid") == "p-old"
                  and e["type"] in ("product_gone", "vendor_lost")]
        check("9 wait for a missing sibling", events == [], f"{events}")
        _nightly(raw, "ivory", [big[1:600]], start=T0 + timedelta(days=5))
        out = _replay(raw, {}, memory=memory)
        events = [e["type"] for e in out.events if e.get("pid") == "p-old"
                  and e["type"] in ("product_gone", "vendor_lost")]
        check("9 then product_gone", events == ["product_gone"], f"{events}")
    finally:
        raw.close()

    # 10. Small price moves are counted, not evented.
    raw = Raw()
    try:
        _nightly(raw, "tms", [big, big, big], prices=[{}, {big[0]: 101, big[1]: 120}, {}])
        out = _replay(raw)
        price = [(e["key"], e["old"], e["price"]) for e in _types(out, "price")]
        # big[1]: 100 -> 120 (night 2) -> 100 (night 3): two 20% events.
        # big[0]: 100 -> 101 -> 100: two 1% moves, counted, never evented.
        want = [(f"tms:{big[1]}", 100, 120), (f"tms:{big[1]}", 120, 100)]
        check("10 big moves evented", price == want, f"{price}")
        check("10 small moves counted", out.crawls[1]["price_changes"] == 2 and
              out.crawls[2]["price_changes"] == 2, f"{out.crawls[1:]}")
    finally:
        raw.close()

    # 11. A bidi mark in the SKU keys like the clean SKU.
    raw = Raw()
    try:
        rows = _rows("yahav", T0, ["CO-9050139-WW"])
        rows[0]["vendor_sku"] = "\u200eCO-9050139-WW"
        raw.write("2026-11-01", "yahav", rows)
        crawls = load_crawls(raw.dir, T0 + timedelta(days=1), 60)["yahav"]
        check("11 clean key", list(crawls[0].items) == ["yahav:CO-9050139-WW"],
              f"{list(crawls[0].items)}")
    finally:
        raw.close()

    # 12. The report itself.
    raw = Raw()
    try:
        _nightly(raw, "tms", [big, big])
        status, changes, memory = report.build(T0 + timedelta(days=2), raw.dir, {}, {})
        check("12 schema", status["schema"] == report.SCHEMA_VERSION and
              changes["schema"] == report.SCHEMA_VERSION, "")
        check("12 generated_at", status["generated_at"] == changes["generated_at"], "")
        check("12 every vendor listed", set(status["crawls"]) >= {"tms", "onepc", "ksp", "ivory", "yahav"},
              f"{sorted(status['crawls'])}")
        check("12 crawl recorded", len(status["crawls"]["tms"]) == 2, "")
        check("12 onboarding", status["crawls"]["tms"][0]["baseline"], "")
    finally:
        raw.close()

    for failure in failures:
        print(f"[ops-report] FAIL {failure}")
    if failures:
        return 1
    print("[ops-report] self-test pass - 12 rule groups")
    return 0


def check_files(ops_dir: Path = OPS) -> int:
    problems = []
    docs = {}
    for name, budget in MAX_BYTES.items():
        path = ops_dir / name
        if not path.is_file():
            problems.append(f"{path} missing - run python -m scraper.ops.report")
            continue
        size = path.stat().st_size
        if size > budget:
            problems.append(f"{name} is {size} bytes, budget {budget}")
        try:
            docs[name] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{name} is not JSON: {exc}")
    status, changes = docs.get("status.json"), docs.get("changes.json")
    if status and changes:
        if status.get("generated_at") != changes.get("generated_at"):
            problems.append("status.json and changes.json come from different runs")
        for vendor in status.get("vendors") or []:
            if vendor["id"] not in (status.get("crawls") or {}):
                problems.append(f"status.json has no crawl list for {vendor['id']}")
    for problem in problems:
        print(f"[ops-report] FAIL {problem}")
    if problems:
        return 1
    print(f"[ops-report] pass - {ops_dir.relative_to(ROOT) if ops_dir.is_relative_to(ROOT) else ops_dir}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return check_files()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
