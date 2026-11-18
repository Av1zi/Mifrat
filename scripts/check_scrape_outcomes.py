"""Offline checks of block responses through Scrapy's real middleware path."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import logging

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapy.crawler import Crawler
from scrapy.exceptions import CloseSpider
from scrapy.http import Response
from scrapy.settings import Settings
from scrapy.statscollectors import MemoryStatsCollector
from scrapy.spidermiddlewares.httperror import HttpErrorMiddleware
from twisted.python.failure import Failure

from scraper.spiders.ksp import KspSpider
from scraper.spiders.ksp_detail import KspDetailSpider
from scraper.spiders.ksp_eilat import KspEilatSpider
from scraper.spiders.ivory_eilat import IvoryEilatSpider
from scraper.crawl_outcome import StopOnBlockMiddleware, outcome


def make_crawler(cls):
    crawler = Crawler(cls, Settings())
    spider = cls.from_crawler(crawler)
    crawler.spider = spider
    crawler.stats = MemoryStatsCollector(crawler)
    return crawler, spider


class Engine:
    def __init__(self):
        self.closed = []

    def close_spider(self, spider, reason):
        self.closed.append(reason)


def main() -> int:
    logging.disable(logging.CRITICAL)
    failures = []
    for status in (403, 429):
        crawler, spider = make_crawler(KspSpider)
        middleware = HttpErrorMiddleware.from_crawler(crawler)
        request = next(spider._build_requests())
        response = Response(request.url, status=status, request=request)
        reason = None
        try:
            try:
                middleware.process_spider_input(response)
            except Exception:
                failure = Failure()
                failure.request = request
                spider._request_failed(failure)
            else:
                list(spider.parse_page(response, **request.cb_kwargs))
        except CloseSpider as exc:
            reason = exc.reason
        if not reason or "blocked" not in reason:
            failures.append(f"HTTP {status}: no immediate block stop (reason={reason!r})")
        if status in KspSpider.custom_settings["RETRY_HTTP_CODES"]:
            failures.append(f"HTTP {status}: block is retryable")
    # Robots and catalog responses both pass through the downloader before
    # RetryMiddleware and HttpErrorMiddleware, not just the spider callback.
    from scrapy.exceptions import IgnoreRequest
    from scrapy import Request
    for cls in (KspSpider, KspDetailSpider, KspEilatSpider, IvoryEilatSpider):
        for status in (403, 429):
            crawler, spider = make_crawler(cls)
            engine = Engine()
            crawler.engine = engine
            middleware = StopOnBlockMiddleware(crawler)
            for url in ("https://ksp.co.il/robots.txt", "https://ksp.co.il/m_action/api/category/2?page=1"):
                request = Request(url)
                try:
                    middleware.process_response(request, Response(url, status=status, request=request))
                    failures.append(f"{cls.name} HTTP {status} was not rejected")
                except IgnoreRequest:
                    pass
                try:
                    middleware.process_request(Request("https://ksp.co.il/next"))
                    failures.append(f"{cls.name} allowed a request after a block")
                except IgnoreRequest:
                    pass
            if not engine.closed or not crawler.stats.get_value("crawl/blocked"):
                failures.append(f"{cls.name} did not close/record the block")
            if status in cls.custom_settings.get("RETRY_HTTP_CODES", []):
                failures.append(f"{cls.name} retries HTTP {status}")
    cases = [
        ({"finish_reason": "finished"}, 900, "ok"),
        ({"finish_reason": "finished", "crawl/blocked": True}, 900, "blocked"),
        ({"finish_reason": "finished", "downloader/response_status_count/403": 1}, 0, "blocked"),
        ({"finish_reason": "finished", "spider_exceptions/ValueError": 1}, 10, "failed"),
        ({"finish_reason": "shutdown"}, 900, "failed"),
        ({"finish_reason": "ksp incomplete - item floor"}, 0, "partial"),
        ({"finish_reason": "finished"}, 0, "partial"),
    ]
    for stats, items, expected in cases:
        if outcome(stats, items) != expected:
            failures.append(f"runner outcome for {stats}: expected {expected}")
    # KSP covers must stop after the first blocked image, not the shared
    # downloader's legacy two-response threshold. No actual image fetch.
    from scraper import download_images as images
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = Path.cwd()
        os.chdir(tmp)
        Path("data").mkdir()
        Path("data/catalog.json").write_text(json.dumps({"products": [
            {"offers": [{"vendor_id": "ksp", "vendor_sku": str(i),
                         "image_url": f"https://ksp.co.il/images/{i}.jpg"}]}
            for i in (1, 2)]}))
        def blocked_image(url, dest):
            images.LAST_HTTP_STATUS = 403
            return False
        try:
            with patch.object(images, "download_and_save", side_effect=blocked_image) as fetch, \
                 patch("scraper.site_data._local_image_path", return_value=None), \
                 patch("scraper.crawl_outcome.write_result"):
                try:
                    images._backfill_from_catalog(vendors=["ksp"], sleep_secs=0)
                    failures.append("cover block returned success")
                except SystemExit as exc:
                    if exc.code != 3 or fetch.call_count != 1:
                        failures.append("cover block made subsequent requests")
        finally:
            os.chdir(old_cwd)
    # Real Scrapy engine with an in-memory downloader. Exercises shutdown,
    # robots middleware and feed preservation; never opens a vendor socket.
    engine_cases = ("robots", "catalog", "rate_limit", "challenge", "detail", "success")
    for case in engine_cases:
        result = subprocess.run([sys.executable, str(Path(__file__)), "--engine", case],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if result.returncode:
            failures.append(f"engine {case}: {result.stdout[-2000:]} {result.stderr[-2000:]}")
    if failures:
        for failure in failures:
            print(f"[scrape-outcomes] FAIL {failure}")
        return 1
    print(f"[scrape-outcomes] pass - block middleware, errbacks, runner outcomes, {len(engine_cases)} real-engine cases")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--engine"]:
        from scrapy.crawler import CrawlerProcess
        from scrapy.http import TextResponse
        from scrapy.utils.project import get_project_settings
        from twisted.internet.defer import succeed
        from scraper import run_spider, run_ksp_detail
        import scraper.spiders.ksp_detail as detail_module
        case = sys.argv[2]
        requests = []

        class FakeHandler:
            def __init__(self, *args, **kwargs):
                pass

            @classmethod
            def from_crawler(cls, crawler):
                return cls()

            def close(self):
                return succeed(None)

            def download_request(self, request, spider=None):
                requests.append(request.url)
                is_robots = request.url.endswith("/robots.txt")
                status = 200 if is_robots and case != "robots" else 403
                if case == "rate_limit" and not is_robots: status = 429
                if case == "challenge" and not is_robots: status = 200
                body = "User-agent: *\nAllow: /\n" if is_robots else "blocked"
                if case == "success" and not is_robots:
                    from scraper.spiders.ksp import CATEGORY_COUNTS
                    tag = request.cb_kwargs["tag"]
                    total = CATEGORY_COUNTS[tag]
                    status = 200
                    body = json.dumps({"result": {"products_total": total, "next": None,
                        "items": [{"uin": int(tag) * 10000 + i + 1, "name": "Fixture part",
                                   "price": 100, "outOfStock": False} for i in range(total)]}})
                if case == "detail" and request.url.endswith("/1"):
                    status = 200
                    body = json.dumps({"result": {"specification": {"items": [
                        {"head": "model", "body": "fixture"}]}}})
                return succeed(TextResponse(request.url, status=status, body=body.encode(),
                                            encoding="utf-8", request=request,
                                            headers={"cf-mitigated": "challenge"} if case == "challenge" and not is_robots else {}))

        cls = KspDetailSpider if case == "detail" else KspSpider
        class FixtureSpider(cls):
            custom_settings = {**cls.custom_settings, "DOWNLOAD_HANDLERS": {
                "http": "__main__.FakeHandler", "https": "__main__.FakeHandler"},
                "DOWNLOAD_DELAY": 0, "AUTOTHROTTLE_ENABLED": False,
                "TELNETCONSOLE_ENABLED": False, "LOG_LEVEL": "ERROR"}

        class FixtureProcess(CrawlerProcess):
            def create_crawler(self, spider):
                return super().create_crawler(FixtureSpider if isinstance(spider, str) else spider)

        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            os.environ["MIFRAT_CRAWL_RESULT"] = str(temp / "result.json")
            os.environ["MIFRAT_VENDOR_PAUSE"] = str(temp / "paused")
            os.environ["MIFRAT_NIGHT_BLOCK"] = str(temp / "blocked")
            if case == "detail":
                os.chdir(temp)
                detail_module.PENDING_PATH = temp / "pending.json"
                detail_module.PENDING_PATH.write_text(json.dumps([{"vendor_sku": "1"}, {"vendor_sku": "2"}]))
                run_ksp_detail.CrawlerProcess = FixtureProcess
                run_ksp_detail.get_project_settings = get_project_settings
                code = run_ksp_detail.main()
                rows = (temp / "data/raw/detail/ksp.jsonl").read_text().splitlines()
                assert len(rows) == 1, "detail row fetched before the block was lost"
            else:
                run_spider.CrawlerProcess = FixtureProcess
                run_spider.DATA_DIR = temp
                os.environ["MIFRAT_NIGHT"] = "2026-11-18"
                final = temp / "raw/2026-11-18/ksp.jsonl"
                final.parent.mkdir(parents=True)
                final.write_text('{"existing": true}\n')
                sys.argv = ["run_spider.py", "ksp"]
                try:
                    run_spider.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code
                if case == "success":
                    assert len(final.read_text().splitlines()) > 800, "complete crawl did not install"
                else:
                    assert final.read_text() == '{"existing": true}\n', "existing snapshot changed"
            expected_outcome = "ok" if case == "success" else "blocked"
            expected_code = 0 if case == "success" else 3
            assert code == expected_code, f"exit was {code}, expected {expected_code}"
            assert json.loads((temp / "result.json").read_text())["outcome"] == expected_outcome
            assert (temp / "paused").exists() == (case != "success")
            expected = 14 if case == "success" else (3 if case == "detail" else (1 if case == "robots" else 2))
            assert len(requests) == expected, f"made {len(requests)} downloads, expected {expected}"
            print(f"engine {case} passed: {len(requests)} in-memory responses, no vendor traffic")
            os.chdir(ROOT)
    else:
        raise SystemExit(main())
