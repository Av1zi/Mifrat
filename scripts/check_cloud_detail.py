"""Actual cloud detail runner, in-memory downloads only; no vendor traffic."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    workflow = (ROOT / ".github/workflows/scrape-cloud.yml").read_text(encoding="utf-8")
    detail = workflow.split("  detail-scrape:\n", 1)[1].split("  publish-detail:\n", 1)[0]
    publish = workflow.split("  publish-detail:\n", 1)[1]
    for job in (detail, publish):
        assert "fail-fast: false" in job and "vendor: [ivory, onepc, yahav]" in job
        assert "publish-detail-${{ matrix.vendor }}" in job, "shared artifact loses vendor isolation"
        assert 'data/raw/detail/$VENDOR.jsonl' in job and 'data/images/$VENDOR/' in job
    assert "python -m scraper.run_cloud_detail" in detail, "workflow bypasses real outcomes"
    assert "steps.crawl.outcome == 'success'" in detail, "failed crawl can still fetch images"
    assert detail.index('make_detail_pending mark') < detail.index('Report failed detail phase')
    assert "!cancelled() && needs.detail-scrape.result != 'skipped'" in publish
    # Syntax-check every shell run block with bash, no execution and no tools
    # from vendor data. This catches indentation/multiline array mistakes.
    blocks = re.findall(r"^        run: \|\n((?:          .*\n|\n)+)", detail + publish, re.M)
    for block in blocks:
        script = "\n".join(line[10:] for line in block.splitlines())
        subprocess.run(["bash", "-n"], input=script, text=True, check=True, capture_output=True)
    for vendor in ("ivory", "onepc", "yahav"):
        for case in ("success", "blocked", "crashed", "empty", "no_specs"):
            result = subprocess.run([sys.executable, str(Path(__file__)), "--engine", vendor, case],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
            if result.returncode:
                print(f"[cloud-detail] FAIL {vendor}/{case}: {result.stdout[-2000:]} {result.stderr[-2000:]}")
                return 1
    print("[cloud-detail] pass - workflow isolation/shell syntax + 15 real-engine cases: outcomes, append preservation, empty queues, block stops, empty specs")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] != ["--engine"]:
        raise SystemExit(main())
    from scrapy.crawler import Crawler, CrawlerProcess
    from scrapy.http import HtmlResponse
    from twisted.internet.defer import succeed
    from scraper import run_cloud_detail as runner
    from scraper.items import DetailItem
    vendor, case = sys.argv[2:]
    requests = []

    class Handler:
        @classmethod
        def from_crawler(cls, crawler):
            return cls()

        def close(self):
            return succeed(None)

        def download_request(self, request, spider=None):
            requests.append(request.url)
            status = 403 if case == "blocked" and request.url.endswith("/2") else 200
            return succeed(HtmlResponse(request.url, request=request, status=status,
                                        body=b"<html>fixture</html>", encoding="utf-8"))

    base = runner.SPIDERS[vendor]

    class FixtureSpider(base):
        custom_settings = {**base.custom_settings, "DOWNLOAD_HANDLERS": {
            "http": "__main__.Handler", "https": "__main__.Handler"},
            "DOWNLOAD_DELAY": 0, "AUTOTHROTTLE_ENABLED": False, "LOG_LEVEL": "ERROR"}

        def parse_detail(self, response):
            if case == "crashed":
                raise ValueError("fixture callback failed")
            yield DetailItem(vendor_id=vendor, vendor_sku=response.meta["vendor_sku"],
                             specs={} if case == "no_specs" else {"model": "fixture"}, url=response.url)

    class Process(CrawlerProcess):
        def create_crawler(self, cls):
            return super().create_crawler(cls if isinstance(cls, Crawler) else FixtureSpider)

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["SCRAPY_SETTINGS_MODULE"] = "scraper.settings"
        old = Path.cwd()
        os.chdir(tmp)
        try:
            pending = Path(f"data/detail_pending/{vendor}.json")
            pending.parent.mkdir(parents=True)
            pending.write_text(json.dumps([] if case == "empty" else [
                {"vendor_sku": str(i), "url": f"https://{base.allowed_domains[0]}/{i}"}
                for i in (1, 2, 3)]))
            output = Path(f"data/raw/detail/{vendor}.jsonl")
            output.parent.mkdir(parents=True)
            existing = '{"vendor_sku":"old","specs":{"model":"existing"}}\n'
            output.write_text(existing)
            with patch.object(runner, "CrawlerProcess", Process):
                code = runner.run(vendor)
            assert code == {"success": 0, "blocked": 3, "crashed": 1, "empty": 0, "no_specs": 1}[case], "empty specs reported success"
            text = output.read_text()
            assert text.startswith(existing), "existing detail history overwritten"
            expected = {"success": 4, "blocked": 2, "crashed": 1, "empty": 1, "no_specs": 4}[case]
            assert len(text.splitlines()) == expected, "completed rows lost or failed response stored"
            expected_requests = {"success": 3, "blocked": 2, "crashed": 3, "empty": 0, "no_specs": 3}[case]
            assert len(requests) == expected_requests, "downloads continued after block"
        finally:
            os.chdir(old)
