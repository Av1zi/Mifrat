"""
Single entrypoint for running one spider and writing its output to
data/raw/YYYY-MM-DD/<spider_name>.jsonl — the layout §5 of the plan
describes. This is deliberately the ONE place that decides the output path,
so the two execution environments (GitHub Actions for cloud vendors, the
Jetson Nano for TMS) can never drift into writing different layouts. Both
call this exact script; nothing execution-environment-specific lives here.

The folder is the scrape night (scraper/night.py, GLOSSARY.md): the crawl's
START time in UTC plus 3 hours, so a run that starts at 23:51 UTC and one
that starts at 00:17 UTC are two nights, never one folder. MIFRAT_NIGHT pins
it (the Nano wrappers set it so their commit paths match). Until 2026-11-15
it was the UTC start date, which put two 1PC nights in one folder.

A second crawl the same night replaces the file only when it is at least as
complete (scraper/night.py `install`); a thinner one is dropped.

Usage:
  python scraper/run_spider.py <spider_name>
  python scraper/run_spider.py tms
  python scraper/run_spider.py onepc
  python scraper/run_spider.py plonter

Exits non-zero if the spider produced zero items — this is the count-check
described in §10 ("if a vendor's raw file is missing or has far fewer items
than expected, the job fails and alerts fire"). It's a blunt zero-vs-nonzero
check here; per-vendor minimum-item-count thresholds are an open item
(plan §17) once there's a baseline from real runs to calibrate against.
"""
import sys
from pathlib import Path

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
sys.path.insert(0, str(DATA_DIR.parent))

from scraper.night import install, tonight  # noqa: E402
from scraper.ops.registry import min_counts  # noqa: E402
from scraper.crawl_outcome import outcome, write_result  # noqa: E402

# Per-vendor minimum-item warning thresholds (plan §17 open item, Sep 2026),
# kept in scraper/ops/registry.py so the ops report flags the same crawls.
# Calibrated at ~75-80% of each vendor's steady state (tms ~2260, onepc
# ~2000, plonter ~2310, ivory ~635, YahavPC 1,079 on 2026-10-14, KSP 1,087
# on 2026-10-30) so a one-day degradation like onepc's -26% drop on
# 2026-09-28 (2010 → 1486) warns in the job log BEFORE it becomes a zero.
# Warning only — the zero-items hard failure below stays the gate; a
# new-vendor onboarding day must never fail on a threshold.
VENDOR_MIN_COUNTS = min_counts()


def build_output_path(spider_name: str, run_date: str) -> Path:
    out_dir = DATA_DIR / "raw" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{spider_name}.jsonl"


def main():
    if len(sys.argv) != 2:
        print("Usage: python scraper/run_spider.py <spider_name>", file=sys.stderr)
        sys.exit(1)

    spider_name = sys.argv[1]
    run_date = tonight()
    output_path = build_output_path(spider_name, run_date)

    # Write next to the final file, then rename only on success. A re-run
    # (manual dispatch retry, Nano catch-up) must not delete an already-good
    # same-day snapshot before the new crawl proves it produced data — the
    # all-or-nothing spiders deliberately yield nothing on a block, and the
    # old "unlink first" behaviour turned that into a lost day.
    part_path = output_path.with_name(output_path.name + ".part")
    if part_path.exists():
        part_path.unlink()

    settings = get_project_settings()
    settings.set("TELNETCONSOLE_ENABLED", False, priority="cmdline")
    settings.set(
        "FEEDS",
        {
            str(part_path): {
                "format": "jsonlines",
                "encoding": "utf8",
                "store_empty": False,
                "overwrite": True,
            }
        },
        priority="cmdline",
    )

    process = CrawlerProcess(settings)
    crawler = process.create_crawler(spider_name)
    process.crawl(crawler)
    process.start()  # blocks until the crawl finishes

    stats = crawler.stats.get_stats() if crawler.stats else {}
    result = outcome(stats, int(stats.get("item_scraped_count", 0)))
    write_result(spider_name, result, int(stats.get("item_scraped_count", 0)))
    if result in ("blocked", "failed", "partial"):
        part_path.unlink(missing_ok=True)
        print(f"[error] {spider_name}: {result}; existing snapshot left untouched", file=sys.stderr)
        sys.exit(3 if result == "blocked" else 1)

    if not part_path.exists() or part_path.stat().st_size == 0:
        if part_path.exists():
            part_path.unlink()
        print(
            f"[error] {spider_name}: zero items written to {part_path} — "
            "failing so the count-check (§10) catches it rather than "
            "silently shipping an empty day. Any existing snapshot for "
            f"{output_path.name} was left untouched.",
            file=sys.stderr,
        )
        sys.exit(1)

    action, line_count, earlier = install(part_path, output_path)
    if action == "empty":
        print(f"[error] {spider_name}: {part_path} held no rows; "
              f"{output_path.name} was left untouched.", file=sys.stderr)
        sys.exit(1)
    if action == "kept":
        print(
            f"[warn] {spider_name}: this crawl has {line_count} items, tonight's "
            f"{output_path} already has {earlier}; kept the fuller one.",
            file=sys.stderr,
        )
        return
    print(f"[ok] {spider_name}: wrote {line_count} items to {output_path}"
          + (f" (replaced tonight's {earlier})" if earlier else ""))

    floor = VENDOR_MIN_COUNTS.get(spider_name)
    if floor and line_count < floor:
        print(
            f"[warn] {spider_name}: only {line_count} items (floor {floor}) — "
            "possible feed degradation or partial block; check the spider log "
            "(plonter markers: plonter-terminal-403x4 / 200-but-N-pre / "
            "parsed-N-filtered-0 / wait-timeout).",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
