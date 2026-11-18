"""Machine-readable crawl outcomes, without responses, URLs or credentials.

Scrapy can exit zero after CloseSpider or callback errors. Runners inspect
stats before installing a snapshot, and the Nano reads this small result
instead of inferring success from the process status or journal wording.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from scrapy.exceptions import CloseSpider, IgnoreRequest

BLOCK_CODES = {403, 429}


def mark_blocked(spider) -> None:
    spider._blocked = True
    spider.crawler.stats.set_value("crawl/blocked", True)
    if spider.name.startswith("ksp"):
        for name in ("MIFRAT_VENDOR_PAUSE", "MIFRAT_NIGHT_BLOCK"):
            path = os.environ.get(name)
            if path:
                Path(path).touch()


def is_challenge(response) -> bool:
    return response.headers.get(b"cf-mitigated", b"").lower() == b"challenge"


class StopOnBlockMiddleware:
    """Stop at the downloader boundary, including robots/startup responses.

    Higher priority than RetryMiddleware: blocked responses never get retried.
    The flag also refuses queued requests before a callback closes the engine.
    """
    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        if getattr(self.crawler.spider, "_blocked", False):
            raise IgnoreRequest("vendor blocked; no further requests this run")

    def process_response(self, request, response):
        if response.status in BLOCK_CODES or is_challenge(response):
            spider = self.crawler.spider
            # Persist before wrapper cleanup, including on a later timeout.
            mark_blocked(spider)
            spider.logger.error("[crawl] blocked HTTP %s; stopping all requests", response.status)
            # close_spider returns a Deferred; do not await shutdown from inside
            # the request it must drain (that would deadlock). The flag above
            # stops queued downloads while shutdown completes.
            if self.crawler.engine is not None:
                self.crawler.engine.close_spider(spider, reason="vendor blocked")
            raise IgnoreRequest("vendor blocked")
        return response


def stop_failure(spider, failure) -> None:
    """Defensive block detection when HttpError reaches an errback directly."""
    response = getattr(failure.value, "response", None)
    if response is not None and (response.status in BLOCK_CODES or is_challenge(response)):
        mark_blocked(spider)
        raise CloseSpider("vendor blocked")


def outcome(stats: dict, items: int, *, allow_empty: bool = False) -> str:
    reason = str(stats.get("finish_reason") or "").lower()
    if stats.get("crawl/blocked") or "blocked" in reason or any(
        stats.get(f"downloader/response_status_count/{code}", 0) for code in BLOCK_CODES
    ):
        return "blocked"
    if "incomplete" in reason:
        return "partial"
    if (stats.get("crawl/failed") or stats.get("spider_exceptions/count", 0) or
            any(k.startswith("spider_exceptions/") and v for k, v in stats.items()) or
            reason not in ("finished",)):
        return "failed"
    if items == 0 and not allow_empty:
        return "partial"
    return "ok"


def write_result(spider: str, result: str, items: int) -> None:
    """Optional local file set by the wrapper; contains only fixed vocabulary."""
    data = {"spider": spider, "outcome": result, "items": items}
    path = os.environ.get("MIFRAT_CRAWL_RESULT")
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        part.write_text(json.dumps(data) + "\n", encoding="utf-8")
        part.replace(target)
    print(f"[crawl-result] spider={spider} outcome={result} rows={items}")
