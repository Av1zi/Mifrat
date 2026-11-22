"""Current-storefront transport with delayed recovery, never auto-fallback.

The legacy API and Nov22 delayed stream recovery rejected the Nano. A fixed
owner-reviewed UA update exists, but full-crawl acceptance is still unverified
(see docs/ksp-stream-transport.md). No timers or pause markers change here.
No copied browser credentials, dynamic tt replay, profile rotation or CAPTCHA.
Uses the site's literal default tt=0; if that is insufficient, stop.

All 13 category routes must be captured from real public UI links and passed
as a token-free routes JSON. No guessed routes/parameters. Existing mapping,
pagination coverage and per-category/total floors remain unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import TextResponse

from scraper.ksp_stream import (CATEGORY_COMPONENT, PRICE_COMPONENT, STREAM_URL,
                               StreamBlocked, StreamError, category_payload, prices_payload)
from scraper.night import tonight
from scraper.spiders.ksp import CATEGORIES, HEADERS, KspSpider

SAFE_ITEM_FIELDS = ("uin", "uinsql", "name", "price", "min_price", "eilatPrice",
                    "outOfStock", "addToCart", "brandName", "img", "tags", "labels",
                    "is_dynamic_parent", "main_family_id")


def load_category_routes(path: str | None) -> dict:
    if not path:
        raise ValueError("stream transport needs a captured category routes file")
    try:
        routes = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("captured category routes file is not readable JSON") from None
    tags = {tag for tag, _ in CATEGORIES}
    if not isinstance(routes, dict) or set(routes) != tags:
        raise ValueError("captured routes must cover every configured KSP category")
    for tag, route in routes.items():
        if not isinstance(route, dict) or set(route) != {"path", "sort"}:
            raise ValueError("category route contains unsupported fields")
        category_path = route["path"]
        if not isinstance(category_path, str) or not re.fullmatch(r"\d+(?:\.\.\d+)*", category_path):
            raise ValueError("category route path is invalid")
        if tag not in category_path.split(".."):
            raise ValueError("captured route does not include its category tag")
        if isinstance(route["sort"], bool) or route["sort"] not in (1, 2, 3, 4, 5):
            raise ValueError("category route sort is not a storefront choice")
    return routes


class KspStreamSpider(KspSpider):
    name = "ksp_stream"
    custom_settings = {
        **KspSpider.custom_settings,
        # Recovery doesn't retry transport/HTTP failures either. Unknown
        # access requirements are a stop, not a trial of another strategy.
        "RETRY_ENABLED": False,
        "DOWNLOAD_MAXSIZE": 2_000_000,
        "DOWNLOAD_WARNSIZE": 1_000_000,
        "COOKIES_ENABLED": False,
    }

    def __init__(self, *args, routes: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        from scraper.ksp_schedule import ready
        if os.environ.get("MIFRAT_KSP_STREAM_APPROVED") != "1" and not ready():
            raise ValueError("stream recovery date has not arrived")
        state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "pc-parts-il"
        if (state / "ksp.paused").exists():
            raise ValueError("KSP is paused; stream transport must not bypass the block")
        self._routes = load_category_routes(routes)
        state.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MIFRAT_VENDOR_PAUSE", str(state / "ksp.paused"))
        os.environ.setdefault("MIFRAT_NIGHT_BLOCK", str(state / f"ksp-{tonight()}.blocked"))
        self._category_index = 0

    async def start(self):
        for request in self._build_requests():
            yield request

    def start_requests(self):
        yield from self._build_requests()

    def _build_requests(self):
        # Never enqueue every category in advance: next is requested only
        # after the previous page and price batch completed successfully.
        tag, guess = CATEGORIES[0]
        yield scrapy.Request("https://ksp.co.il/web/cat/" + self._routes[tag]["path"],
                             headers={**HEADERS, "Accept": "text/html", "sec-fetch-dest": "document",
                                      "sec-fetch-mode": "navigate", "sec-fetch-site": "none"},
                             callback=self._warmup, errback=self._stream_failed,
                             cb_kwargs={"tag": tag, "guess": guess}, meta={"tag": tag}, dont_filter=True)

    def _warmup(self, response, tag, guess):
        if response.status in (403, 429):
            self._stream_block(tag)
        if any(marker in response.text.lower() for marker in (
                "cf-mitigated", "verify you are human", "הגישה נחסמה", "אימות אבטחה")):
            self._stream_block(tag)
        if response.status != 200:
            self._stop_incomplete("category page warmup failed")
        yield self._page_request(tag, guess, 1)

    def _headers(self, tag):
        return {**HEADERS, "Accept": "text/event-stream", "Content-Type": "application/json",
                "lang": "he", "Referer": "https://ksp.co.il/web/cat/" + self._routes[tag]["path"]}

    def _stream_request(self, tag, component, params, callback, cb_kwargs):
        # Literal default in the public storefront's pn() function. No token
        # generation/replay or browser cookie transfer. If the endpoint needs
        # extra access state, don't try to manufacture it.
        body = json.dumps({"components": [{"key": component, "params": params}],
                           "context": {"tt": 0}}).encode()
        return scrapy.Request(STREAM_URL, method="POST", body=body,
                              headers=self._headers(tag), callback=callback,
                              cb_kwargs=cb_kwargs, errback=self._stream_failed,
                              meta={"tag": tag}, dont_filter=True)

    def _page_request(self, tag, guess, page):
        route = self._routes[tag]
        params = {"categoryPath": route["path"], "withSuggestion": 1,
                  "sort": route["sort"], "number": 12, "tags_size": 30}
        if page > 1:
            params["page"] = str(page)  # site's Zx() serializes query fields
        return self._stream_request(tag, CATEGORY_COMPONENT, params, self.parse_stream_page,
                                    {"tag": tag, "guess": guess, "page": page})

    def _check_response(self, response):
        if response.status in (403, 429):
            self._stream_block(response.meta.get("tag", "?"))
        if response.status != 200:
            self._stop_incomplete("stream HTTP failure")
        content_type = response.headers.get(b"Content-Type", b"").lower()
        if not content_type.startswith(b"text/event-stream"):
            # A 200 HTML challenge must not be followed by a price/category
            # request; conservatively pause rather than trying formats.
            self._stream_block(response.meta.get("tag", "?"))

    def parse_stream_page(self, response, tag, guess, page):
        self._check_response(response)
        try:
            data = category_payload(response.body)
        except StreamBlocked:
            self._stream_block(tag)
        except StreamError:
            self._stop_incomplete("category stream invalid or incomplete")
        # Retain only known product fields, never opaque session/tt data.
        data = {"products_total": data["products_total"], "next": data.get("next"),
                "items": [{key: row[key] for key in SAFE_ITEM_FIELDS if key in row}
                          for row in data["items"]]}
        if not data["items"]:
            yield from self._accept_page(response, data, tag, guess, page)
            return
        uins = [str(row["uin"]) for row in data["items"]]
        if len(set(uins)) != len(uins):
            self._stop_incomplete("category stream repeated product ids")
        yield self._stream_request(tag, PRICE_COMPONENT, {"uins": ",".join(uins)},
                                   self.parse_stream_prices,
                                   {"tag": tag, "guess": guess, "page": page,
                                    "data": data, "uins": uins})

    def parse_stream_prices(self, response, tag, guess, page, data, uins):
        self._check_response(response)
        try:
            current = prices_payload(response.body, uins)
        except StreamBlocked:
            self._stream_block(tag)
        except StreamError:
            self._stop_incomplete("price stream invalid or incomplete")
        for row in data["items"]:
            price = current[str(row["uin"])]
            row["price"] = price["price"]
            # Both counters arrive in this same price response. Preserve the
            # availability verdict too: null alone is not evidence of absence.
            row["_stream_eilat_price"] = price.get("eilat_price")
            row["_stream_is_eilat"] = price.get("is_eilat")
        yield from self._accept_page(response, data, tag, guess, page)

    def _accept_page(self, response, data, tag, guess, page):
        # The existing listing parser owns ALL coverage checks and mapping.
        legacy = TextResponse(response.url, request=response.request,
                              body=json.dumps({"result": data}).encode(), encoding="utf-8")
        for result in super().parse_page(legacy, tag, guess, page):
            if isinstance(result, scrapy.Request):
                yield self._page_request(tag, guess, result.cb_kwargs["page"])
                return
            yield result
        if self._failed:
            self._stop_incomplete("category completeness check failed")
        if tag in self._done_categories and not self._finalized:
            self._category_index += 1
            next_tag, next_guess = CATEGORIES[self._category_index]
            yield self._page_request(next_tag, next_guess, 1)

    def _map_item(self, raw, guess):
        item = super()._map_item(raw, guess)
        if item is not None:
            item["vendor_meta"]["transport"] = "component-stream"
            item["vendor_meta"]["display_sku"] = raw.get("uinsql")
            if raw.get("_stream_eilat_price") is not None:
                item["vendor_meta"]["stream_eilat_price"] = raw["_stream_eilat_price"]
            item["vendor_meta"]["eilat"] = {
                "price_ils": raw.get("_stream_eilat_price"),
                "available": raw.get("_stream_is_eilat"),
            }
        return item

    def _stop_incomplete(self, reason):
        self._failed = True
        self.crawler.stats.set_value("crawl/failed", True)
        self.logger.error("[ksp-stream] %s; no snapshot", reason)
        raise CloseSpider("ksp incomplete — stream transport")

    def _stream_block(self, tag):
        state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "pc-parts-il"
        state.mkdir(parents=True, exist_ok=True)
        (state / "ksp.paused").touch()
        self._block(tag, "component access blocked")

    def _stream_failed(self, failure):
        from scraper.crawl_outcome import stop_failure
        stop_failure(self, failure)
        self._stop_incomplete("stream request failed")
