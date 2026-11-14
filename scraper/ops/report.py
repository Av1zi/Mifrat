"""Build data/ops/: what was scraped, when, and what changed.

    python -m scraper.ops.report              # after normalize (CI does this)
    python -m scraper.ops.report --print      # also print the daily summary

Reads every crawl in the last WINDOW_DAYS day folders of data/raw/ plus
data/catalog.json, and writes:

  data/ops/status.json   registry, every crawl per vendor (60-day calendar),
                         catalog facts, generated_at. Small; the Worker's
                         alert cron and the admin page read it.
  data/ops/changes.json  events of the last EVENT_DAYS days (new / gone /
                         returned / price / product) and the listings now
                         missing or recently gone.
  data/ops/memory.json   listing key -> last product id + product names, so
                         a listing that left the catalog keeps its product
                         name next run. The only carried state; deleting it
                         loses names of long-gone products, nothing else.

Everything is recomputed from the raw window each run (~3s for 60 days), so
there is no ledger that can drift; a merge conflict in data/ops/ is resolved
by re-running this script, like every other generated data file.

Facts only, no verdicts: "missing" and "late" depend on the clock, so the
readers (site/src/ops/rules.ts) decide them at read time. A stale report is
itself a finding there.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scraper.ops import lifecycle  # noqa: E402
from scraper.ops.registry import VENDORS, as_json  # noqa: E402
from scraper.ops.snapshots import DAY_RE, load_crawls  # noqa: E402

DATA = ROOT / "data"
RAW = DATA / "raw"
OPS = DATA / "ops"
CATALOG = DATA / "catalog.json"
SITE = DATA / "site"
SCHEMA_VERSION = 1
# 120 days of crawls for the month calendar; weekly-downsample only thins
# day folders older than 90 days, so the oldest month is partly weekly.
WINDOW_DAYS = 120
EVENT_DAYS = 30
# Price moves are the bulkiest events (~2k in 30 days) and only recent ones
# matter on the panel.
PRICE_EVENT_DAYS = 14
ABSENT_DAYS = 30
# changes.json cap per event type (newest kept), so a vendor re-keying its
# whole catalog cannot ship a multi-MB file to the admin page.
MAX_EVENTS_PER_TYPE = 3000


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data, lines: bool = False) -> None:
    """Atomic write (temp file + replace). `lines`: one top-level entry per
    line, so a daily commit of a mostly-unchanged file is a small diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        text = json.dumps(data, ensure_ascii=False, indent=0, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    os.replace(tmp, path)


def first_snapshot_days(raw_dir: Path) -> dict[str, str]:
    """Each vendor's oldest day folder holding its file (onboarding check)."""
    first: dict[str, str] = {}
    if not raw_dir.is_dir():
        return first
    for day_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir() and DAY_RE.match(p.name)):
        for vendor in VENDORS:
            if vendor not in first and (day_dir / f"{vendor}.jsonl").is_file():
                first[vendor] = day_dir.name
    return first


def catalog_facts(catalog: dict) -> dict:
    """What the published catalog says about each vendor and itself."""
    per_vendor: dict[str, dict] = {}
    for row in catalog.get("listings") or []:
        vendor = "onepc" if row.get("vendor_id") == "1pc" else str(row.get("vendor_id"))
        entry = per_vendor.setdefault(vendor, {"listings": 0, "stale": 0, "last_seen": None})
        entry["listings"] += 1
        if row.get("stale"):
            entry["stale"] += 1
        seen = row.get("last_seen")
        if seen and (entry["last_seen"] is None or seen > entry["last_seen"]):
            entry["last_seen"] = seen
    categories: dict[str, int] = {}
    # Per category: how many products each vendor sells, how many are sold by
    # 1 / 2 / 3+ vendors (the comparison value of the catalog), price range.
    detail: dict[str, dict] = {}
    for product in catalog.get("products") or []:
        cat = str(product.get("category"))
        categories[cat] = categories.get(cat, 0) + 1
        entry = detail.setdefault(cat, {"products": 0, "by_vendor": {}, "sellers": {"1": 0, "2": 0, "3+": 0},
                                        "in_stock": 0, "min_price": None, "max_price": None})
        entry["products"] += 1
        vendors = {("onepc" if o.get("vendor_id") == "1pc" else str(o.get("vendor_id")))
                   for o in product.get("offers") or []}
        for v in vendors:
            entry["by_vendor"][v] = entry["by_vendor"].get(v, 0) + 1
        bucket = "3+" if len(vendors) >= 3 else str(max(1, len(vendors)))
        entry["sellers"][bucket] += 1
        best = product.get("best_offer") or {}
        if best.get("in_stock"):
            entry["in_stock"] += 1
        price = best.get("price_ils")
        if isinstance(price, (int, float)) and price > 0:
            entry["min_price"] = price if entry["min_price"] is None else min(entry["min_price"], price)
            entry["max_price"] = price if entry["max_price"] is None else max(entry["max_price"], price)
    for entry in detail.values():
        entry["by_vendor"] = dict(sorted(entry["by_vendor"].items()))
    qa = _read_json(SITE / "qa.json", {})
    qa_counts: dict[str, int] = {}
    for case in qa.get("cases") or []:
        if case.get("dismissed"):
            continue
        kind = str(case.get("kind") or "other")
        qa_counts[kind] = qa_counts.get(kind, 0) + 1
    spec = _read_json(SITE / "spec_report.json", {})
    return {
        "generated_at": catalog.get("generated_at"),
        "products": len(catalog.get("products") or []),
        "listings": len(catalog.get("listings") or []),
        "skipped_vendors": list(catalog.get("skipped_vendors") or []),
        "review_queue": catalog.get("review_queue_count"),
        "vendors": per_vendor,
        "categories": dict(sorted(categories.items())),
        "category_detail": dict(sorted(detail.items())),
        "qa": dict(sorted(qa_counts.items())),
        "spec_counts": spec.get("counts") or {},
    }


def _cap(events: list[dict]) -> tuple[list[dict], dict[str, int]]:
    by_type: dict[str, list[dict]] = {}
    for event in events:
        by_type.setdefault(event["type"], []).append(event)
    kept: list[dict] = []
    dropped: dict[str, int] = {}
    for kind, items in by_type.items():
        if len(items) > MAX_EVENTS_PER_TYPE:
            dropped[kind] = len(items) - MAX_EVENTS_PER_TYPE
            items = items[-MAX_EVENTS_PER_TYPE:]
        kept.extend(items)
    kept.sort(key=lambda e: e["at"], reverse=True)
    return kept, dropped


def build(now: datetime, raw_dir: Path = RAW, catalog: dict | None = None,
          memory: dict | None = None) -> tuple[dict, dict, dict]:
    """(status, changes, memory) for `now`. Pure apart from reading raw_dir."""
    if catalog is None:
        catalog = _read_json(CATALOG, {})
    crawls = load_crawls(raw_dir, now, WINDOW_DAYS)
    window_start = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    firsts = first_snapshot_days(raw_dir)
    onboarding = {v for v, day in firsts.items() if day >= window_start}
    result = lifecycle.replay(crawls, catalog, memory, onboarding)

    per_vendor: dict[str, list[dict]] = {v: [] for v in VENDORS}
    for summary in result.crawls:
        per_vendor[summary["vendor"]].append(summary)
    status = {
        "schema": SCHEMA_VERSION,
        "generated_at": lifecycle.iso(now),
        "window_days": WINDOW_DAYS,
        "vendors": as_json(),
        "first_snapshot": firsts,
        "crawls": per_vendor,
        "catalog": catalog_facts(catalog),
    }

    cutoff = lifecycle.iso(now - timedelta(days=EVENT_DAYS))
    price_cutoff = lifecycle.iso(now - timedelta(days=PRICE_EVENT_DAYS))
    recent = [e for e in result.events
              if e["at"] >= (price_cutoff if e["type"] == "price" else cutoff)]
    events, dropped = _cap(recent)
    changes = {
        "schema": SCHEMA_VERSION,
        "generated_at": status["generated_at"],
        "event_days": EVENT_DAYS,
        "events": events,
        "dropped": dropped,
        "absent": lifecycle.absent_listings(result, now, ABSENT_DAYS),
    }
    return status, changes, lifecycle.next_memory(result)


def summary_lines(status: dict) -> list[str]:
    """Human summary of each vendor's latest crawl (for --print and logs)."""
    lines = []
    for vendor in status["vendors"]:
        if not vendor["active"]:
            continue
        crawls = status["crawls"].get(vendor["id"]) or []
        if not crawls:
            lines.append(f"{vendor['label']:8} no crawl in {status['window_days']} days")
            continue
        c = crawls[-1]
        flags = [f for f, on in (("suspect: " + str(c["suspect"]), c["suspect"]),
                                 ("misfiled", c["misfiled"]),
                                 (f"{c['crawls_in_file']} crawls in file", c["crawls_in_file"] > 1),
                                 ("outside night window", c["outside_window"])) if on]
        lines.append(f"{vendor['label']:8} {c['keys']:>5} items  {c['start'][:16]}Z "
                     f"+{c['new']} new -{c['gone']} gone ~{c['missing']} missing"
                     + (f"  [{'; '.join(flags)}]" if flags else ""))
    return lines


def seed_memory_from_git(days: int) -> dict:
    """Listing -> product memory from past catalogs in git history.

    One-time bootstrap (`--seed-git`): without it, a listing that left the
    catalog before the first ops run has no product name. Reads one
    data/catalog.json per day for `days` days, oldest first, so a key's
    newest product wins. Local use; CI never runs it.
    """
    import subprocess

    log = subprocess.run(
        ["git", "log", f"--since={days} days ago", "--format=%H %cs", "--", "data/catalog.json"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    per_day: dict[str, str] = {}
    for sha, day in zip(log[0::2], log[1::2]):
        per_day.setdefault(day, sha)          # git log is newest first
    pids: dict[str, str] = {}
    products: dict[str, list[str]] = {}
    for day in sorted(per_day):
        blob = subprocess.run(["git", "show", f"{per_day[day]}:data/catalog.json"],
                              cwd=ROOT, capture_output=True, check=True).stdout
        try:
            catalog = json.loads(blob)
        except ValueError:
            continue
        for p in catalog.get("products") or []:
            products[str(p.get("product_id"))] = [str(p.get("canonical_name") or ""),
                                                  str(p.get("category") or "")]
        for row in catalog.get("listings") or []:
            if row.get("listing_key") and row.get("product_id"):
                pids[str(row["listing_key"])] = str(row["product_id"])
        print(f"[ops] seeded from {day} ({per_day[day][:8]}): {len(pids)} keys", flush=True)
    return {"pids": pids, "products": products}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print", action="store_true", help="print the per-vendor summary")
    parser.add_argument("--out", type=Path, default=OPS)
    parser.add_argument("--seed-git", action="store_true",
                        help="one-time: fill memory.json from past catalogs in git history")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    now = datetime.now(timezone.utc)
    memory = _read_json(args.out / "memory.json", {})
    if args.seed_git:
        seeded = seed_memory_from_git(WINDOW_DAYS)
        memory = {"pids": {**seeded["pids"], **(memory.get("pids") or {})},
                  "products": {**seeded["products"], **(memory.get("products") or {})}}
    status, changes, memory = build(now, memory=memory)
    _write_json(args.out / "status.json", status)
    _write_json(args.out / "changes.json", changes)
    _write_json(args.out / "memory.json", memory, lines=True)
    counts: dict[str, int] = {}
    for event in changes["events"]:
        counts[event["type"]] = counts.get(event["type"], 0) + 1
    print(f"[ops] wrote {args.out}: {sum(len(v) for v in status['crawls'].values())} crawls, "
          f"{len(changes['events'])} events {dict(sorted(counts.items()))}, "
          f"{len(changes['absent'])} absent listings")
    if args.print:
        for line in summary_lines(status):
            print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
