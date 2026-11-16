"""
TMS Eilat prices (scraper/eilat.py): the same category pages in Eilat mode.

TMS's site has an Eilat mode (the "לאתר אילת" switch, verified 2026-11-16):
`?eilat=1` on any page sets it for the session (body class `eilat`), and every
tile price then is the Eilat price (C2130T-P: 84 regular, 71 Eilat). The Eilat
listing is not the regular one: 3 of 30 processor tiles were Eilat-only and 3
regular items were missing. So this spider reuses the TMS listing parser
(spiders/tms.py) over Eilat-mode pages, and a tile here is "sold in Eilat".

Stock: the Claris availability call TMS's own widget makes lists every
branch; the Eilat branch's `inStock` is the Eilat stock (the regular spider
reads the network-wide status).

Home IP, same rules and headers as spiders/tms.py (robots obeyed; `?eilat=1`
and `&page=N` are allowed). The first page of each category carries
`?eilat=1`; later pages follow with the session cookie still in Eilat mode,
and every page is checked to really be in Eilat mode: a regular-mode page is
never written as Eilat prices.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from scraper.eilat import EILAT_CHANNEL
from scraper.items import ListingItem
from scraper.spiders.tms import START_CATEGORIES, TmsSpider

import scrapy
from scrapy.exceptions import CloseSpider

EILAT_BRANCH = "אילת"


def eilat_url(url: str) -> str:
    """`url` with eilat=1 added to its query (kept on every page)."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["eilat"] = ["1"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def eilat_branch_stock(row: dict) -> bool | None:
    for branch in row.get("BranchAvailability") or []:
        if isinstance(branch, dict) and branch.get("name") == EILAT_BRANCH:
            stock = branch.get("inStock")
            return stock if isinstance(stock, bool) else None
    return None


def in_eilat_mode(response) -> bool:
    classes = (response.css("body::attr(class)").get() or "").split()
    return "eilat" in classes


class TmsEilatSpider(TmsSpider):
    name = "tms_eilat"

    async def start(self):
        for category_guess, url in START_CATEGORIES:
            yield scrapy.Request(
                eilat_url(url),
                callback=self.parse,
                cb_kwargs={"category_guess": category_guess},
            )

    def parse(self, response, category_guess):
        if response.status not in (403, 429) and not in_eilat_mode(response):
            self.logger.error("[tms_eilat] %s is not in Eilat mode - stopping", response.url)
            raise CloseSpider("tms_eilat: page not in Eilat mode")
        for out in super().parse(response, category_guess):
            if isinstance(out, scrapy.Request) and out.callback == self.parse:
                out = out.replace(url=eilat_url(out.url))
            elif isinstance(out, ListingItem):
                out["channel"] = EILAT_CHANNEL
            yield out

    def _yield_pending(self, pending, stock_by_code):
        for item in super()._yield_pending(pending, stock_by_code):
            item["channel"] = EILAT_CHANNEL
            yield item

    @staticmethod
    def _stock_from_row(row):
        return eilat_branch_stock(row)
