"""
KSP Eilat prices (scraper/eilat.py) from KSP's live-price call.

The category API's `eilatPrice` is always 0 (every row since 2026-10-29).
The storefront fills the "אילת :" price under each tile from a second call
(verified 2026-11-16 in a browser and from curl_cffi):

    GET /m_action/api/new-config?url=<page url>   -> sets the ID_computer session cookie
    GET /m_action/api/bms/<uin>,<uin>,...          -> {"result": {"<uin>": {...}}}

Per uin: `price` (the regular price the listing spider records),
`eilat_price` (the Eilat price; null when the item is not sold in Eilat) and
`is_eilat`. A `discount.value_eilat` is today's Eilat sale price; it is kept in
vendor_meta, while `price_ils` is `eilat_price`, the counterpart of the regular
`price` the listing carries. Without the session cookie the call answers
200 {"result": "Error Code: 851"}: that is a failed run, never "not in Eilat".

The uins are tonight's KSP listing snapshot (spiders/ksp.py runs first in
nano/run_ksp.sh), asked 12 at a time like the storefront's own page. Home IP
rules as for the listing spider: the same TLS profile and client hints
(KspFingerprintMiddleware), one request at a time, 3-9 s apart, the first
403/429 stops the run. All-or-nothing: rows are yielded only when every batch
answered, so a partial run never reads as "not sold in Eilat".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import scrapy
from scrapy.exceptions import CloseSpider

from scraper.eilat import EILAT_CHANNEL
from scraper.items import ListingItem
from scraper.night import tonight
from scraper.spiders.ksp import HEADERS, PRODUCT_URL, VENDOR_ID, KspSpider, _as_int

RAW_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
CONFIG_URL = "https://ksp.co.il/m_action/api/new-config?url={page}"
BMS_URL = "https://ksp.co.il/m_action/api/bms/{uins}"
WARMUP_PAGE = "https://ksp.co.il/web/cat/35"
BATCH = 12
# A night whose listing snapshot is this short is not worth a run.
MIN_UINS = 400


def snapshot_uins(path: Path) -> list[str]:
    """Distinct uins of a KSP listing snapshot, in file order."""
    uins: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            uin = str((row or {}).get("vendor_sku") or "").strip()
            if uin.isdigit() and uin not in seen:
                seen.add(uin)
                uins.append(uin)
    return uins


def parse_bms(payload) -> dict[str, dict] | None:
    """uin -> {price, eilat, eilat_sale} for Eilat-sold items; None = bad answer."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    out: dict[str, dict] = {}
    for uin, row in result.items():
        if not isinstance(row, dict):
            continue
        eilat = _as_int(row.get("eilat_price"))
        if row.get("is_eilat") is False or not eilat or eilat <= 0:
            continue
        discount = row.get("discount")
        sale = discount.get("value_eilat") if isinstance(discount, dict) else None
        out[str(uin)] = {
            "price": _as_int(row.get("price")),
            "eilat": eilat,
            "eilat_sale": round(float(sale)) if isinstance(sale, (int, float)) and sale > 0 else None,
        }
    return out


class KspEilatSpider(scrapy.Spider):
    name = "ksp_eilat"
    allowed_domains = ["ksp.co.il"]
    # Block verdicts must reach _block (a 403/429 is a stop signal).
    handle_httpstatus_list = [403, 429]
    # The listing spider's TLS profile, headers middleware, pacing and retry
    # policy (spiders/ksp.py), unchanged.
    custom_settings = KspSpider.custom_settings

    def __init__(self, *args, snapshot: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot = Path(snapshot) if snapshot else RAW_DIR / tonight() / "ksp.jsonl"
        self._uins: list[str] = []
        self._rows: dict[str, dict] = {}
        self._pending = 0
        self._failed = False
        self._scraped_at = datetime.now(timezone.utc).isoformat()

    async def start(self):
        for request in self._build_requests():
            yield request

    def start_requests(self):
        yield from self._build_requests()

    def _build_requests(self):
        if not self._snapshot.is_file():
            raise CloseSpider(f"ksp_eilat: no listing snapshot at {self._snapshot}")
        self._uins = snapshot_uins(self._snapshot)
        if len(self._uins) < MIN_UINS:
            raise CloseSpider(f"ksp_eilat: only {len(self._uins)} uins in {self._snapshot}")
        yield scrapy.Request(
            CONFIG_URL.format(page=quote(WARMUP_PAGE, safe="")),
            callback=self.parse_config,
            errback=self._request_failed,
            headers={**HEADERS, "Referer": WARMUP_PAGE},
            dont_filter=True,
        )

    def parse_config(self, response):
        if response.status in (403, 429):
            self._block(f"new-config: HTTP {response.status}")
        if "ID_computer" not in response.text:
            # The session id comes back in the body's cookie list (and as
            # Set-Cookie); without it every bms call is "Error Code: 851".
            raise CloseSpider("ksp_eilat: new-config returned no session")
        batches = [self._uins[i:i + BATCH] for i in range(0, len(self._uins), BATCH)]
        self._pending = len(batches)
        for batch in batches:
            yield scrapy.Request(
                BMS_URL.format(uins=",".join(batch)),
                callback=self.parse_bms,
                errback=self._request_failed,
                headers={**HEADERS, "Referer": WARMUP_PAGE},
                cb_kwargs={"batch": batch},
                dont_filter=True,
            )

    def parse_bms(self, response, batch):
        if response.status in (403, 429):
            self._block(f"bms: HTTP {response.status}")
        if self._failed:
            return
        try:
            rows = parse_bms(json.loads(response.text))
        except (json.JSONDecodeError, TypeError):
            rows = None
        if rows is None:
            # "Error Code: 851" (no session) or a changed shape: never read
            # as "not sold in Eilat".
            self._failed = True
            raise CloseSpider(f"ksp_eilat: bad bms answer ({response.text[:80]!r})")
        self._rows.update({uin: row for uin, row in rows.items() if uin in batch})
        self._pending -= 1
        if self._pending == 0 and not self._failed:
            yield from self._items()

    def _items(self):
        self.logger.info("[ksp_eilat] %d of %d uins are sold in Eilat", len(self._rows), len(self._uins))
        for uin, row in self._rows.items():
            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=uin,
                url=PRODUCT_URL.format(uin=uin),
                price_ils=row["eilat"],
                in_stock=None,
                channel=EILAT_CHANNEL,
                vendor_meta={"regular_price": row["price"], "eilat_sale_price": row["eilat_sale"]},
                scraped_at=self._scraped_at,
            )

    def _block(self, reason: str):
        self._failed = True
        self.logger.error("[ksp_eilat] BLOCKED: %s - stopping; no snapshot written", reason)
        raise CloseSpider("ksp blocked - no snapshot written")

    def _request_failed(self, failure):
        status = getattr(getattr(failure.value, "response", None), "status", None)
        if status in (403, 429):
            self._block(f"HTTP {status}")
        self._failed = True
        self.logger.error("[ksp_eilat] request failed: %r", failure.value)
        raise CloseSpider("ksp_eilat incomplete - no snapshot written")
