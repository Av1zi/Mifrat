"""
Detail-page spiders — spec + cover image scrape, run ONCE per vendor_sku.

Design (unchanged): each spider reads its pending-work list from
data/detail_pending/<vendor>.json — a JSON list of {"vendor_sku", "url"}
objects produced by scraper/make_detail_pending.py ("make"), which is also
the only place that updates the data/detail_scraped/<vendor>.json ledger
("mark"), and only for SKUs whose resized image already exists on disk —
so a crash partway through never marks a product "done" without its image.

Selectors in this revision are VERIFIED against raw HTML saves taken
Aug 2026 (one real product page per vendor), lifting the "unverified"
caveat from the first revision:

  Ivory  — spec panel is div#panel2: one <li> per row; first inner <div>
           holds the <b>label</b>, second inner <div> the value (the value
           div may nest further divs/links, e.g. the warranty row).
           Cover image: the save has NO og:image — use
           link[rel=image_src] / img.xzoom@xoriginal fallbacks.
  TMS    — div.product-attribute-item microdata pairs
           (h3.specification-title / div.specification-data). Multi-value
           cells arrive as separate text nodes ("VGA |", "HDMI").
           Bonus metas: product:brand / product:availability /
           product:price:amount; on-page מק"ט in span.param-model.
  1PC    — the Specifications tab is SERVER-RENDERED into #quickTab-default
           as table.data-table (tr.spec-header group rows + odd/even rows
           with td.spec-name / td.spec-value). The first revision's fear
           (table only reachable via a robots-blocked AJAX endpoint) was
           wrong for the real page. The long Intel-ark-style
           "Specifications" cell keeps its line structure by joining text
           nodes with newlines. Flat comma-string parser kept as fallback.
  Plonter— the data table is the only table whose rows carry
           onmouseover="ChangeBackgroundColor(this)"; each row is
           [Hebrew label][value, dir=ltr, often a link][English key].
           Page is windows-1255; keep the explicit re-decode.

Image download stays in download_images.py (requests+Pillow, 800px/JPEG
q82, data/images/<vendor>/<sku>.jpg) — unchanged.
"""
import json
import re
import scrapy
from datetime import datetime, timezone
from pathlib import Path

from scraper.items import DetailItem


def _load_pending(vendor: str) -> list:
    path = Path(f"data/detail_pending/{vendor}.json")
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _cover_image(response) -> str | None:
    """Cover image, in priority order. og:image confirmed on TMS/1PC/
    Plonter saves; Ivory needs the link[rel=image_src] / xzoom fallbacks."""
    raw = (
        response.css('meta[property="og:image"]::attr(content)').get()
        or response.css('meta[property="og:image:url"]::attr(content)').get()
        or response.css('link[rel="image_src"]::attr(href)').get()
        or response.css("img.xzoom::attr(xoriginal)").get()
    )
    return response.urljoin(raw) if raw else None


def _parts(cell) -> list:
    return [t.strip() for t in cell.css("::text").getall() if t.strip()]


class IvoryDetailSpider(scrapy.Spider):
    name = "ivory_detail"
    allowed_domains = ["ivory.co.il"]

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for entry in _load_pending("ivory"):
            yield scrapy.Request(
                url=entry["url"],
                callback=self.parse_detail,
                meta={"vendor_sku": entry["vendor_sku"]},
            )

    def parse_detail(self, response):
        specs = {}
        # Verified (catalog.php?id=30398): div#panel2, one <li> per row.
        for li in response.css("div#panel2 li"):
            divs = li.css("div")
            if len(divs) < 2:
                continue
            label = " ".join(_parts(divs[0])).strip(" :*‎‏")
            value = " ".join(_parts(divs[1]))
            if label and value:
                specs[label] = value
        if not specs:
            # Fallback: list under the "מפרט המוצר" heading.
            for row in response.xpath(
                "//*[contains(text(), 'מפרט המוצר')]/following::ul[1]/li"
            ):
                label = (row.css("strong::text, b::text").get() or "").strip()
                value = " ".join(_parts(row))
                if label and value:
                    if value.startswith(label):
                        value = value[len(label):].strip(" :*‎‏")
                    if value:
                        specs[label] = value
        yield DetailItem(
            vendor_id="ivory",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_cover_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )


class TmsDetailSpider(scrapy.Spider):
    name = "tms_detail"
    allowed_domains = ["tms.co.il"]

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for entry in _load_pending("tms"):
            yield scrapy.Request(
                url=entry["url"],
                callback=self.parse_detail,
                meta={"vendor_sku": entry["vendor_sku"]},
            )

    def parse_detail(self, response):
        specs = {}
        # Verified (arktek-ak-h81mel-vs): schema.org PropertyValue blocks.
        for item in response.css("div.product-attribute-item"):
            label = (item.css("h3.specification-title::text").get() or "").strip()
            value_cells = item.css("div.specification-data")
            if not label or not value_cells:
                continue
            cleaned = [p.strip(" |") for p in _parts(value_cells[0])]
            value = " | ".join(cleaned)
            if value:
                specs[label] = value
        sku_on_page = (response.css("span.param-model::text").get() or "").strip()
        if not sku_on_page:
            sku_on_page = (response.xpath(
                "//*[contains(text(), 'מק\"ט')]/following-sibling::text()[1]"
            ).get() or "").strip()
        yield DetailItem(
            vendor_id="tms",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_cover_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
            extra={
                "brand": response.css('meta[property="product:brand"]::attr(content)').get(),
                "availability": response.css('meta[property="product:availability"]::attr(content)').get(),
                "price_meta": response.css('meta[property="product:price:amount"]::attr(content)').get(),
                "sku_on_page": sku_on_page,
            },
        )


class OnePcDetailSpider(scrapy.Spider):
    name = "onepc_detail"
    allowed_domains = ["1pc.co.il"]

    # Fallback only (flat Overview string), kept from the first revision.
    _PAIR_RE = re.compile(r"([A-Za-z][A-Za-z0-9 /™®()._-]*):\s*")

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for entry in _load_pending("onepc"):
            yield scrapy.Request(
                url=entry["url"],
                callback=self.parse_detail,
                meta={"vendor_sku": entry["vendor_sku"]},
            )

    def parse_detail(self, response):
        specs = {}
        group = ""
        # Verified (product-217314): server-rendered table.data-table.
        for tr in response.css("table.data-table tr"):
            cls = tr.attrib.get("class") or ""
            if "spec-header" in cls:
                group = (tr.css("td.spec-group-name::text").get() or "").strip()
                continue
            name = (tr.css("td.spec-name::text").get() or "").strip()
            value_cells = tr.css("td.spec-value")
            if not name or not value_cells:
                continue
            value = "\n".join(_parts(value_cells[0]))
            if not value:
                continue
            key = name
            if key in specs and group:
                key = f"{group}: {name}"
            specs[key] = value
        overview_text = " ".join(
            t.strip()
            for t in response.css("div.short-description ::text").getall()
            if t.strip()
        )
        if not specs:
            specs = self._parse_flat_specs(overview_text)
        yield DetailItem(
            vendor_id="1pc",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_cover_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
            extra={"overview_text_raw": overview_text},
        )

    @classmethod
    def _parse_flat_specs(cls, text: str) -> dict:
        specs = {}
        matches = list(cls._PAIR_RE.finditer(text))
        for i, m in enumerate(matches):
            label = m.group(1).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            value = text[start:end].strip(" ,.")
            if label and value:
                specs[label] = value
        return specs


class PlonterDetailSpider(scrapy.Spider):
    name = "plonter_detail"
    allowed_domains = ["plonter.co.il"]

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for entry in _load_pending("plonter"):
            yield scrapy.Request(
                url=entry["url"],
                callback=self.parse_detail,
                meta={"vendor_sku": entry["vendor_sku"]},
            )

    def parse_detail(self, response):
        # Page is windows-1255; keep the explicit re-decode.
        response = response.replace(encoding="windows-1255")
        specs = {}
        # Verified (detail.tmpl?sku=100-100000510BOX): the data table is
        # the only table whose rows carry onmouseover=ChangeBackgroundColor;
        # columns are [HE label][value][EN key]. Prefer the EN key.
        for tr in response.css('tr[onmouseover*="ChangeBackgroundColor"]'):
            tds = tr.css("td")
            if len(tds) < 3:
                continue
            heb = " ".join(_parts(tds[0])).strip(" :")
            value = " ".join(_parts(tds[1]))
            en = " ".join(_parts(tds[2])).strip()
            key = en or heb
            if key and value and key not in specs:
                specs[key] = value
        extra = {}
        if not specs:
            description = response.css('meta[name="description"]::attr(content)').get() or ""
            specs = {"description_raw": description.strip(" -")}
            extra["needs_manual_verification"] = True
        yield DetailItem(
            vendor_id="plonter",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_cover_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
            extra=extra,
        )