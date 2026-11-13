"""
KSP detail spider: the maker part number and spec table from KSP's item JSON.

KSP's listing feed carries no part number, so KSP-only products could not
join the same part at other vendors (8% shared on 2026-11-13). The item
endpoint the storefront uses,

    GET https://ksp.co.il/m_action/api/item/<uin>

answered 200 JSON from the Nano on 2026-11-13 (docs/ksp-detail-plan.md,
Phase 0 outcome). Its `result.specification.items` is a list of
{head, body-HTML} rows copied from the maker; on a Kingston kit the `דגם`
(model) row is the maker part number "KF556C40BBK2-32", on an Intel CPU it
is only "i5-14600K". So the row is stored as-is in `specs`, a part-number
shaped value rides as `extra.model_row`, and normalize_and_match makes it
the listing's `mpn` only when another vendor prints the same code.

Rules (home IP only, never CI, same as the listing spider):
- the listing spider's TLS profile and client hints (KspFingerprintMiddleware),
  one request at a time, 6s +-50% between requests;
- the first 403 or 429 (after Scrapy's bounded 429 retries) stops the run;
  nothing already fetched is lost (rows are yielded as they arrive) and the
  rest stays pending for tomorrow;
- the pending list (data/detail_pending/ksp.json, make_detail_pending)
  is capped by the Nano job, KSP-only products first.

Output: one DetailItem per uin, appended to data/raw/detail/ksp.jsonl.
"""

from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import scrapy
from scrapy.exceptions import CloseSpider

from scraper.items import DetailItem
from scraper.spiders.ksp import HEADERS, USER_AGENT, VENDOR_ID

ITEM_URL = "https://ksp.co.il/m_action/api/item/{uin}"
PENDING_PATH = Path("data/detail_pending/ksp.json")

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"<br\s*/?>|</(?:div|p|li)>", re.I)


def spec_text(body) -> str:
    """One spec cell's HTML as plain text; line breaks become " | "."""
    text = _BREAK_RE.sub(" | ", str(body or ""))
    text = _html.unescape(_TAG_RE.sub(" ", text))
    parts = [re.sub(r"\s+", " ", part).strip() for part in text.split("|")]
    return " | ".join(part for part in parts if part)


def parse_specification(payload) -> dict[str, str]:
    """`result.specification.items` as {head: text}; a repeated head gets " 2"."""
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    spec = result.get("specification") if isinstance(result, dict) else None
    items = spec.get("items") if isinstance(spec, dict) else None
    out: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        head = re.sub(r"\s+", " ", str(item.get("head") or "")).strip()
        value = spec_text(item.get("body"))
        if not head or not value:
            continue
        if head in out and out[head] != value:
            head = f"{head} 2"
        out[head] = value
    return out


# A part-number-shaped `דגם` cell: one token of letters AND digits. Shape
# alone cannot tell "KF556C40BBK2-32" from the model name "i5-14600K", so
# this is only a candidate; normalize_and_match makes it the listing's `mpn`
# only when another vendor prints the same code (ksp_detail_part_numbers).
_PART_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_-]{5,39}$")


def ksp_model_part_number(specs: dict) -> str | None:
    """The `דגם` row when it is shaped like a part number, else None."""
    value = str(specs.get("דגם") or "").strip()
    if not _PART_NUMBER_RE.match(value):
        return None
    compact = re.sub(r"[^A-Za-z0-9]", "", value)
    if (len(compact) < 7 or not re.search(r"[A-Za-z]", compact)
            or not re.search(r"\d", compact)):
        return None
    return value


class KspDetailSpider(scrapy.Spider):
    name = "ksp_detail"
    allowed_domains = ["ksp.co.il"]
    handle_httpstatus_list = [403, 429]

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_curl_cffi.handlers.CurlCffiDownloadHandler",
            "https": "scrapy_curl_cffi.handlers.CurlCffiDownloadHandler",
        },
        "DOWNLOADER_MIDDLEWARES": {
            "scraper.spiders.ksp.KspFingerprintMiddleware": 543,
        },
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 6.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "USER_AGENT": USER_AGENT,
        "ROBOTSTXT_OBEY": True,
        # 429 gets Scrapy's bounded retries first; whatever still answers
        # 429 or 403 reaches parse_item and stops the run.
        "RETRY_HTTP_CODES": [408, 425, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 2,
        "DOWNLOAD_TIMEOUT": 60,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetched = 0
        self.with_part_number = 0
        self._queue: list[dict] = []
        self._stopped = False

    async def start(self):
        for request in self._first_request():
            yield request

    def start_requests(self):
        yield from self._first_request()

    def _first_request(self):
        if PENDING_PATH.exists():
            self._queue = [
                entry for entry in json.loads(PENDING_PATH.read_text(encoding="utf-8"))
                if str(entry.get("vendor_sku") or "").strip().isdigit()
            ]
        yield from self._next_request()

    def _next_request(self):
        """One request in flight at a time: the next uin is asked for only
        after the previous answer was handled, so a block can never find a
        second request already queued behind it."""
        if self._stopped or not self._queue:
            return
        entry = self._queue.pop(0)
        uin = str(entry["vendor_sku"]).strip()
        yield scrapy.Request(
            ITEM_URL.format(uin=uin),
            callback=self.parse_item,
            errback=self._request_failed,
            headers=HEADERS,
            meta={"vendor_sku": uin, "listing_url": entry.get("url")},
            dont_filter=True,
        )

    def _stop(self, reason: str):
        self._stopped = True
        self._queue.clear()
        raise CloseSpider(reason)

    def _request_failed(self, failure):
        self.logger.warning("[ksp_detail] uin %s: request failed: %r",
                            failure.request.meta.get("vendor_sku"), failure.value)
        yield from self._next_request()

    def parse_item(self, response):
        uin = response.meta["vendor_sku"]
        if response.status in (403, 429):
            self.logger.error("[ksp_detail] BLOCKED (HTTP %s) on uin %s - stopping; "
                              "the rest stays pending", response.status, uin)
            self._stop(f"ksp_detail blocked {response.status}")
        if response.status != 200:
            self.logger.warning("[ksp_detail] uin %s: HTTP %s", uin, response.status)
            yield from self._next_request()
            return
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            # A 200 that is not JSON is a challenge page: same verdict as 403.
            self.logger.error("[ksp_detail] uin %s: non-JSON 200 (challenge?) - stopping", uin)
            self._stop("ksp_detail non-JSON response")

        specs = parse_specification(payload)
        self.fetched += 1
        extra: dict = {"spec_rows": len(specs)}
        part_number = ksp_model_part_number(specs)
        if part_number:
            # A candidate only (see ksp_model_part_number); not `mpn`, so
            # the generic detail merge never trusts it unchecked.
            extra["model_row"] = part_number
            self.with_part_number += 1
        brand = specs.get("יצרן")
        if brand:
            extra["brand"] = brand
        yield DetailItem(
            vendor_id=VENDOR_ID,
            vendor_sku=uin,
            url=response.meta.get("listing_url") or response.url,
            specs=specs,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            extra=extra,
        )
        yield from self._next_request()

    def closed(self, reason):
        self.logger.info("[ksp_detail] %s: %d items fetched, %d with a part number",
                         reason, self.fetched, self.with_part_number)
