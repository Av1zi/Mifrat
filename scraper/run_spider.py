"""
Single entrypoint for running one spider and writing its output to
data/raw/YYYY-MM-DD/<spider_name>.jsonl — the layout §5 of the plan
describes. This is deliberately the ONE place that decides the output path,
so the two execution environments (GitHub Actions for cloud vendors, the
Jetson Nano for TMS) can never drift into writing different layouts. Both
call this exact script; nothing execution-environment-specific lives here.

Date is UTC, matching the rest of the pipeline (GitHub Actions cron is
UTC-only per §3, and the Nano syncs NTP per §4) — using local time here
would make "today's" folder ambiguous between the two writers.

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
from datetime import datetime, timezone
from pathlib import Path

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Per-vendor minimum-item warning thresholds (plan §17 open item, Sep 2026).
# Calibrated at ~80% of the Sep 20-27 steady-state baselines (tms ~2260,
# onepc ~2000, plonter ~2310, ivory ~635) so a one-day degradation like
# onepc's -26% drop on 2026-09-28 (2010 → 1486) warns in the job log BEFORE
# it becomes a zero. Warning only — the zero-items hard failure below stays
# the gate; a new-vendor onboarding day must never fail on a threshold.
VENDOR_MIN_COUNTS = {
    "tms": 1800,
    "onepc": 1600,
    "plonter": 1800,
    "ivory": 500,
}


def build_output_path(spider_name: str, run_date: str) -> Path:
    out_dir = DATA_DIR / "raw" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{spider_name}.jsonl"


def main():
    if len(sys.argv) != 2:
        print("Usage: python scraper/run_spider.py <spider_name>", file=sys.stderr)
        sys.exit(1)

    spider_name = sys.argv[1]
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = build_output_path(spider_name, run_date)

    # Overwrite, not append — a re-run (manual dispatch retry, Nano catch-up
    # after downtime) should replace today's file, not duplicate into it.
    if output_path.exists():
        output_path.unlink()

    settings = get_project_settings()
    settings.set(
        "FEEDS",
        {
            str(output_path): {
                "format": "jsonlines",
                "encoding": "utf8",
                "store_empty": False,
            }
        },
        priority="cmdline",
    )

    process = CrawlerProcess(settings)
    process.crawl(spider_name)
    process.start()  # blocks until the crawl finishes

    if not output_path.exists() or output_path.stat().st_size == 0:
        print(
            f"[error] {spider_name}: zero items written to {output_path} — "
            "failing so the count-check (§10) catches it rather than "
            "silently shipping an empty day.",
            file=sys.stderr,
        )
        sys.exit(1)

    line_count = sum(1 for _ in output_path.open(encoding="utf-8"))
    print(f"[ok] {spider_name}: wrote {line_count} items to {output_path}")

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
