"""
Pulls the latest job's items from Zyte Scrapy Cloud via its API and writes
them to data/listings_latest.jsonl for normalize_and_match.py to consume.

Runs inside the GitHub Actions sync-and-deploy workflow (§9), ~1-2h after the
Scrapy Cloud periodic job is expected to finish.

Env vars expected (set as GitHub Actions secrets):
  SHUB_APIKEY      - Scrapy Cloud API key
  SHUB_PROJECT_ID  - numeric project id from the Scrapy Cloud dashboard

Usage:
  python scraper/sync_from_scrapy_cloud.py
"""
import json
import os
import sys
from pathlib import Path

try:
    from scrapinghub import ScrapinghubClient
except ImportError:
    print("Run: pip install scrapinghub --break-system-packages", file=sys.stderr)
    raise

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "listings_latest.jsonl"

# Vendors currently in scope (KSP intentionally excluded — see spiders/ksp.py)
SPIDER_NAMES = ["tms", "ivory", "onepc", "plonter"]


def fetch_latest_items_for_spider(client, project_id, spider_name):
    project = client.get_project(project_id)
    spider = project.spiders.get(spider_name)
    jobs = spider.jobs.list(state="finished", count=1)
    if not jobs:
        print(f"[warn] no finished jobs found for spider '{spider_name}'", file=sys.stderr)
        return []
    latest_job_key = jobs[0]["key"]
    job = project.jobs.get(latest_job_key)
    return list(job.items.iter())


def main():
    api_key = os.environ.get("SHUB_APIKEY")
    project_id = os.environ.get("SHUB_PROJECT_ID")
    if not api_key or not project_id:
        print("SHUB_APIKEY and SHUB_PROJECT_ID must be set", file=sys.stderr)
        sys.exit(1)

    client = ScrapinghubClient(api_key)
    DATA_DIR.mkdir(exist_ok=True)

    total = 0
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for spider_name in SPIDER_NAMES:
            items = fetch_latest_items_for_spider(client, project_id, spider_name)
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            total += len(items)
            print(f"[ok] {spider_name}: {len(items)} items")

    # §9: fail loudly if today's item count is zero or drastically down —
    # cheap insurance against "vendor changed their HTML, scraper silently
    # returns nothing."
    if total == 0:
        print("[error] zero items pulled across all spiders — failing the job", file=sys.stderr)
        sys.exit(1)

    print(f"[ok] wrote {total} total items to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
