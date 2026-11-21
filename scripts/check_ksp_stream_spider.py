"""Offline transport integration: SSE -> existing all-or-nothing KSP spider."""
from copy import deepcopy
import json
import os
import subprocess
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapy.crawler import Crawler
from scrapy.http import TextResponse
from scrapy.settings import Settings
from scrapy.statscollectors import MemoryStatsCollector
from scrapy.exceptions import CloseSpider
from scraper.spiders.ksp_stream import KspStreamSpider
from scraper.spiders.ksp_stream import load_category_routes
from scraper.spiders.ksp import CATEGORIES
from tempfile import TemporaryDirectory

FIXTURE = ROOT / "scraper/fixtures/ksp/cpu_stream.json"


def response(request, events):
    body = "".join(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                   for event, data in events)
    return TextResponse(request.url, request=request, body=body.encode(), encoding="utf-8",
                        headers={"Content-Type": "text/event-stream"})


def main():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    crawler = Crawler(KspStreamSpider, Settings())
    crawler.stats = MemoryStatsCollector(crawler)
    manifest = {"2": {"path": "31635..2..61615", "sort": 1}}
    # Gate defaults closed. Approval here authorizes only fixture execution,
    # with no real downloader and no inherited user state.
    try:
        with patch("scraper.ksp_schedule.ready", return_value=False):
            KspStreamSpider(routes="fixture")
        raise AssertionError("unapproved transport enabled")
    except ValueError:
        pass
    os.environ["MIFRAT_KSP_STREAM_APPROVED"] = "1"
    state = TemporaryDirectory()
    os.environ["XDG_STATE_HOME"] = state.name
    for name in ("MIFRAT_VENDOR_PAUSE", "MIFRAT_NIGHT_BLOCK"):
        os.environ.pop(name, None)
    with patch("scraper.spiders.ksp_stream.load_category_routes", return_value=manifest):
        spider = KspStreamSpider.from_crawler(crawler, routes="fixture")
    crawler.spider = spider
    # Small, single-category fixture reaches the real original completeness
    # logic. Production has all 13 categories and the original item floor.
    spider._tag_uins = {"2": set()}
    spider._pending_categories = 1
    listing = deepcopy(fixture["listing"])
    listing["data"]["result"]["products_total"] = 12
    listing["data"]["result"]["next"] = None
    request = spider._page_request("2", "cpu", 1)
    with patch("scraper.spiders.ksp.MIN_TOTAL_ITEMS", 1), \
         patch("scraper.spiders.ksp.CATEGORY_COUNTS", {"2": 12}):
        price_request = list(spider.parse_stream_page(response(request, [("partial", listing), ("done", fixture["done"])]), **request.cb_kwargs))
        assert len(price_request) == 1
        assert not spider._items, "listings emitted before live-price batch"
        bms = deepcopy(fixture["prices"])
        first_uin = str(listing["data"]["result"]["items"][0]["uin"])
        bms["data"]["result"][first_uin]["price"] = 351
        rows = list(spider.parse_stream_prices(response(price_request[0], [("partial", bms), ("done", fixture["done"])]), **price_request[0].cb_kwargs))
        assert len(rows) == 12
        assert rows[0]["vendor_sku"] == first_uin
        assert rows[0]["price_ils"] == 351, "live regular price not used"
    assert rows[0]["vendor_meta"]["stream_eilat_price"] == 296
    assert spider._pending_categories == 0
    from scraper.matching import enrich_listing, match_listings
    enriched = [enrich_listing(dict(row)) for row in rows]
    matched = match_listings(enriched)
    offers = [offer for product in matched["products"] for offer in product["offers"]]
    assert len(offers) == 12
    assert any(offer["vendor_sku"] == "505073" and offer["price_ils"] == 351 for offer in offers)
    from datetime import datetime, timezone
    from scraper.normalize_and_match import _attach_eilat
    with patch("scraper.normalize_and_match.find_latest_snapshot", return_value=None):
        _, states = _attach_eilat(enriched, {"ksp": {"stale": False}},
                                  datetime(2026, 11, 18, 3, tzinfo=timezone.utc))
    from scraper.matching import offer_from_listing
    offer = offer_from_listing(enriched[0])
    assert offer.get("eilat_price_ils") == 296, "observed inline Eilat price lost before offers"
    assert offer["price_ils"] == 351, "inline Eilat price replaced regular price"
    assert states["ksp"]["state"] == "fresh", "complete inline prices need no second snapshot"
    assert all(not offer.get("eilat_only") for offer in offers)
    assert json.loads(request.body)["components"][0]["key"] == "cat.categoryListing"
    assert json.loads(price_request[0].body)["components"][0]["key"] == "item.bms"
    assert not any(k in request.headers for k in (b"Cookie", b"Persistent", b"Authorization"))
    assert json.loads(request.body)["context"] == {"tt": 0}, "browser token accidentally replayed"
    assert spider.custom_settings["COOKIES_ENABLED"] is False
    assert spider.custom_settings["RETRY_ENABLED"] is False
    # Existing parser's pagination creates the next request through the new
    # transport, never retries/falls back to the blocked legacy endpoint.
    with patch("scraper.spiders.ksp_stream.load_category_routes", return_value=manifest):
        second = KspStreamSpider.from_crawler(crawler, routes="fixture")
    second._tag_uins = {"2": set()}
    second._pending_categories = 1
    first_page = second._page_request("2", "cpu", 1)
    next_data = deepcopy(fixture["listing"]["data"]["result"])
    next_data["products_total"] = 24
    with patch("scraper.spiders.ksp.CATEGORY_COUNTS", {"2": 24}):
        next_request = list(second._accept_page(response(first_page, []), next_data, "2", "cpu", 1))
    assert len(next_request) == 1 and next_request[0].method == "POST"
    assert json.loads(next_request[0].body)["components"][0]["params"]["page"] == "2"
    assert second._pending_categories == 1, "partial page finalized category"
    # A missing done event must not map even one listing.
    with patch("scraper.spiders.ksp_stream.load_category_routes", return_value=manifest):
        broken = KspStreamSpider.from_crawler(crawler, routes="fixture")
    bad_request = broken._page_request("2", "cpu", 1)
    try:
        list(broken.parse_stream_page(response(bad_request, [("partial", listing)]), **bad_request.cb_kwargs))
        raise AssertionError("incomplete SSE accepted")
    except CloseSpider:
        assert broken._failed and not broken._items
    # A price stream that omits a requested product cannot shrink a category
    # silently or mark that product unavailable.
    missing = deepcopy(fixture["prices"])
    missing["data"]["result"].pop(first_uin)
    with patch("scraper.spiders.ksp_stream.load_category_routes", return_value=manifest):
        short = KspStreamSpider.from_crawler(crawler, routes="fixture")
    try:
        list(short.parse_stream_prices(response(price_request[0], [("partial", missing), ("done", fixture["done"])]),
                                       **price_request[0].cb_kwargs))
        raise AssertionError("short price batch accepted")
    except CloseSpider:
        assert short._failed and not short._items
    with patch("scraper.spiders.ksp_stream.load_category_routes", return_value=manifest):
        blocked = KspStreamSpider.from_crawler(crawler, routes="fixture")
    block_request = blocked._page_request("2", "cpu", 1)
    api_block = {**listing, "ok": False, "error": {"status": 403, "message": "SECRET_FIXTURE"}}
    try:
        list(blocked.parse_stream_page(response(block_request, [("partial", api_block), ("done", fixture["done"])]), **block_request.cb_kwargs))
        raise AssertionError("API-level block accepted")
    except CloseSpider as error:
        assert "blocked" in error.reason, "HTTP-200 stream block misclassified as partial"
        assert Path(state.name, "pc-parts-il/ksp.paused").exists(), "API-level block did not persist pause"
    Path(state.name, "pc-parts-il/ksp.paused").unlink()
    # Routes fail closed: all 13 must be captured, and credential-bearing
    # extra fields are never accepted. Fixture-only synthetic routes exercise
    # validation; no such route is supplied to a real crawl.
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "routes.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            load_category_routes(str(path))
            raise AssertionError("missing category routes accepted")
        except ValueError:
            pass
        complete = {tag: {"path": tag, "sort": 1} for tag, _ in CATEGORIES}
        path.write_text(json.dumps(complete), encoding="utf-8")
        assert set(load_category_routes(str(path))) == {tag for tag, _ in CATEGORIES}
        complete["2"]["tt"] = "SECRET_FIXTURE"
        path.write_text(json.dumps(complete), encoding="utf-8")
        try:
            load_category_routes(str(path))
            raise AssertionError("token-bearing route accepted")
        except ValueError as error:
            assert "SECRET_FIXTURE" not in str(error)
    pause = Path(state.name) / "pc-parts-il/ksp.paused"
    pause.parent.mkdir(parents=True, exist_ok=True)
    pause.touch()
    try:
        KspStreamSpider(routes="fixture")
        raise AssertionError("stream bypassed pause")
    except ValueError:
        pass
    state.cleanup()
    engine = subprocess.run([sys.executable, str(Path(__file__)), "--engine"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if engine.returncode:
        print("[ksp-stream-spider] FAIL real engine", engine.stdout[-2000:], engine.stderr[-2000:])
        return 1
    print("[ksp-stream-spider] pass - saved category/live-price stream -> real KSP all-or-nothing pipeline")
    return 0


if __name__ == "__main__":
    if "--engine" not in sys.argv:
        raise SystemExit(main())
    from scrapy.crawler import CrawlerProcess
    from twisted.internet.defer import succeed
    from scrapy.utils.project import get_project_settings
    from scraper import run_spider
    from scraper.spiders import ksp as original, ksp_stream as transport
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    requests = []

    class FixtureHandler:
        @classmethod
        def from_crawler(cls, crawler):
            return cls()

        def close(self):
            return succeed(None)

        def download_request(self, request, spider=None):
            requests.append(request)
            if request.url.endswith("/robots.txt"):
                return succeed(TextResponse(request.url, request=request, body=b"User-agent: *\nAllow: /\n", encoding="utf-8"))
            if request.method == "GET":
                return succeed(TextResponse(request.url, request=request, body=b"<html>category fixture</html>", encoding="utf-8"))
            payload = json.loads(request.body)
            key = payload["components"][0]["key"]
            partial = deepcopy(fixture["listing"] if key == "cat.categoryListing" else fixture["prices"])
            if key == "cat.categoryListing":
                partial["data"]["result"]["products_total"] = 12
                partial["data"]["result"]["next"] = None
            return succeed(response(request, [("partial", partial), ("done", fixture["done"])]))

    class FixtureSpider(KspStreamSpider):
        custom_settings = {**KspStreamSpider.custom_settings,
                           "DOWNLOAD_HANDLERS": {"http": "__main__.FixtureHandler", "https": "__main__.FixtureHandler"},
                           "DOWNLOAD_DELAY": 0, "AUTOTHROTTLE_ENABLED": False,
                           "TELNETCONSOLE_ENABLED": False, "LOG_LEVEL": "ERROR"}

    with TemporaryDirectory() as tmp:
        temp = Path(tmp)
        os.environ["XDG_STATE_HOME"] = tmp
        os.environ["MIFRAT_KSP_STREAM_APPROVED"] = "1"
        for name in ("MIFRAT_VENDOR_PAUSE", "MIFRAT_NIGHT_BLOCK"):
            os.environ.pop(name, None)
        output = temp / "raw/2026-11-22/ksp.jsonl"
        routes = temp / "routes.json"
        routes.write_text(json.dumps({"2": {"path": "31635..2..61615", "sort": 1}}))
        with patch.object(transport, "CATEGORIES", (("2", "cpu"),)), \
             patch.object(original, "CATEGORIES", (("2", "cpu"),)), \
             patch.object(original, "CATEGORY_COUNTS", {"2": 12}), \
             patch.object(original, "MIN_TOTAL_ITEMS", 1):
            class FixtureProcess(CrawlerProcess):
                def create_crawler(self, cls):
                    return super().create_crawler(FixtureSpider if cls is KspStreamSpider else cls)

                def crawl(self, crawler, **kwargs):
                    return super().crawl(crawler, routes=str(routes))

            run_spider.DATA_DIR = temp
            os.environ['MIFRAT_NOW'] = '2026-11-22T01:00:00Z'
            os.environ['MIFRAT_NIGHT'] = '2026-11-22'
            sys.argv = ['run_spider.py', 'ksp']
            with patch.object(run_spider, 'CrawlerProcess', FixtureProcess):
                run_spider.main()
        rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 12
        assert rows[0]["vendor_sku"] == "505073"
        assert len(requests) == 4, "unexpected startup, retry or fallback requests"
        assert len([r for r in requests if r.method == "POST"]) == 2
        assert not output.with_name(output.name + '.part').exists()
        print("[ksp-stream-spider] real engine passed, 12 fixture listings, robots+warmup+2 in-memory stream responses")
