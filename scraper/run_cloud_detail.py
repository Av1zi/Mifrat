"""Run one cloud detail vendor, preserving append-only rows and real outcomes.

Workflow matrix jobs isolate vendors. A block/callback error fails this run,
but already captured rows remain available for ledger marking/publication.
Never use a successful Scrapy CLI exit as proof the crawl succeeded.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from scraper.crawl_outcome import outcome, write_result
from scraper.spiders.detail_pages import IvoryDetailSpider, OnePcDetailSpider, YahavDetailSpider
from scraper.make_detail_pending import _pending, _usable_specs

SPIDERS = {"ivory": IvoryDetailSpider, "onepc": OnePcDetailSpider, "yahav": YahavDetailSpider}


def run(vendor: str) -> int:
    pending = _pending(vendor)
    entries = json.loads(pending.read_text(encoding="utf-8")) if pending.exists() else []
    if not entries:
        write_result(f"{vendor}_detail", "ok", 0)
        return 0
    output = Path(f"data/raw/detail/{vendor}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    settings = get_project_settings()
    settings.set("TELNETCONSOLE_ENABLED", False, priority="cmdline")
    settings.set("FEEDS", {str(output): {"format": "jsonlines", "encoding": "utf8",
                 "store_empty": False, "overwrite": False}}, priority="cmdline")
    process = CrawlerProcess(settings)
    crawler = process.create_crawler(SPIDERS[vendor])
    usable = 0

    def accepted(item, response, spider):
        nonlocal usable
        if _usable_specs(item.get("specs")):
            usable += 1

    crawler.signals.connect(accepted, signal=signals.item_scraped, weak=False)
    process.crawl(crawler)
    process.start()
    stats = crawler.stats.get_stats() if crawler.stats else {}
    count = int(stats.get("item_scraped_count", 0))
    result = outcome(stats, count)
    if result == "ok" and count and not usable:
        result = "partial"
    write_result(f"{vendor}_detail", result, count)
    return 0 if result == "ok" else 3 if result == "blocked" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vendor", choices=SPIDERS)
    raise SystemExit(run(parser.parse_args().vendor))
