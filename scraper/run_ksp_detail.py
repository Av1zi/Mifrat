"""Run KSP detail append-only, preserving rows even on a block or crash.

Unlike Scrapy's CLI, the exit status reflects the crawler's actual outcome.
MIFRAT_CRAWL_RESULT is a local-only, credential-free result for the Nano.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from scraper.crawl_outcome import outcome, write_result


def main() -> int:
    settings = get_project_settings()
    settings.set("TELNETCONSOLE_ENABLED", False, priority="cmdline")
    path = Path("data/raw/detail/ksp.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    settings.set("FEEDS", {str(path): {"format": "jsonlines", "encoding": "utf8",
                                     "overwrite": False, "store_empty": False}}, priority="cmdline")
    process = CrawlerProcess(settings)
    crawler = process.create_crawler("ksp_detail")
    process.crawl(crawler)
    process.start()
    stats = crawler.stats.get_stats() if crawler.stats else {}
    items = int(stats.get("item_scraped_count", 0))
    result = outcome(stats, items, allow_empty=True)
    write_result("ksp_detail", result, items)
    return 3 if result == "blocked" else (0 if result == "ok" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
