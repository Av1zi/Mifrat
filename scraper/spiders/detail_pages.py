"""
Detail-page spiders — spec + cover image scrape, run ONCE per vendor_sku.

Design:
- Each spider reads its pending-work list from
  data/detail_pending/<vendor>.json — a JSON list of
  {"vendor_sku": "...", "url": "..."} objects. Something upstream
  (a small script comparing the listing spiders' output against
  data/detail_scraped/<vendor>.json) is responsible for producing
  that pending list; these spiders don't do that comparison
  themselves, to keep "what's already scraped" logic in one place
  rather than duplicated per-spider.
- Output: one DetailItem per product (see below), written to
  data/raw/detail/<vendor>.jsonl via `-O <path>:jsonlines` (Scrapy's
  modern colon syntax) — simpler and less quoting-fragile than the
  `-s "FEEDS={...}"` form used elsewhere in this project, e.g.:
      scrapy crawl tms_detail -O data/raw/detail/tms.jsonl:jsonlines
- Image download is deliberately NOT done inside these spiders.
  At ~5 new items/day, a plain `requests`-based downloader
  (download_images.py, same folder) run once after the spider
  finishes is simpler than wiring up Scrapy's ImagesPipeline for
  this low a volume, and keeps retry/resize logic in one place
  shared across all 4 vendors.
- After a successful run, append the scraped vendor_sku values to
  data/detail_scraped/<vendor>.json — NOT done here either; that's
  the same upstream script's job, run after this spider AND the
  image downloader both succeed, so a crash partway through doesn't
  mark a product "done" without its image.

Rate limiting: TMS runs from the Nano (home IP, datacenter-blocked
per decisions.md §7) — this spider inherits whatever
DOWNLOAD_DELAY/AUTOTHROTTLE settings are already in settings.py for
that context. At ~5 new items/day total across all vendors this is a
non-issue, but do NOT batch-request the full existing catalog through
these spiders on the very first big run — see the note in
decisions.md addendum below.
"""
import html as _html
import json
import re
import scrapy
from datetime import datetime, timezone
from pathlib import Path
from scrapy.exceptions import CloseSpider
from scraper.items import DetailItem  # add this to items.py — shape shown at bottom of file

# Same §7 rule 6 threshold as spiders/tms.py: two block responses in one
# run closes the spider. Detail-page volume is tiny (~5/day) but it's the
# same home IP and the same site, so the same protection applies.
MAX_BLOCKS_PER_RUN = 2
BLOCK_STATUS_CODES = {403, 429}

# Forces plain HTTP(S) downloading regardless of what settings.py registers
# globally. Only PlonterDetailSpider (and Ivory/TMS/1PC's *listing* spiders
# never having needed this either) should ever launch a browser — Ivory,
# TMS, and 1PC's detail pages are static HTML. Without this override, if
# settings.py registers scrapy-playwright's handler project-wide (which
# it appears to, since a Playwright crash took down a `tms_detail` run
# that never sends a single playwright=True request), EVERY spider pays
# the cost of starting a Playwright browser at crawl-open, and on the
# Nano specifically that browser can't even launch (no Chromium build for
# ubuntu18.04-arm64) — so it doesn't just slow things down, it hard-crashes
# spiders that should have nothing to do with Playwright at all.
NON_PLAYWRIGHT_DOWNLOAD_HANDLERS = {
    "DOWNLOAD_HANDLERS": {
        "http": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
        "https": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
    },
}


def _load_pending(vendor: str) -> list:
    path = Path(f"data/detail_pending/{vendor}.json")
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _og_image(response) -> str | None:
    """Every vendor we've checked (Ivory, TMS, 1PC, Plonter) puts the
    full-resolution cover image in og:image — no need for per-vendor
    image selectors."""
    return response.css('meta[property="og:image"]::attr(content)').get()


class IvoryDetailSpider(scrapy.Spider):
    name = "ivory_detail"
    allowed_domains = ["ivory.co.il"]
    custom_settings = {**NON_PLAYWRIGHT_DOWNLOAD_HANDLERS}

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
        # "מפרט המוצר" section: each row is a dt/dd-style pair rendered
        # as a heading (spec label) followed by its value paragraph.
        # Observed structure (Aug 2026, catalog.php?id=30398):
        #   - **מותג**\n\n  AMD\n\n- **דגם**\n\n  Ryzen™ 3 3200G\n\n...
        # In raw HTML this is a definition-list-like block; the
        # reliable anchor is the "מפרט המוצר" header immediately
        # preceding it. Select list items within that container.
        spec_rows = response.css("div.item-properties li, div.specification li")
        if not spec_rows:
            # Fallback: some Ivory templates render the same content
            # as a plain list under a heading containing "מפרט"
            spec_rows = response.xpath(
                "//*[contains(text(), 'מפרט המוצר')]/following::ul[1]/li"
            )
        for row in spec_rows:
            label = (row.css("strong::text, b::text").get() or "").strip()
            value = " ".join(t.strip() for t in row.css("::text").getall() if t.strip())
            if label and value:
                # value includes the label text itself since ::text
                # grabs everything; strip the label prefix back off
                value = value[len(label):].strip(" :\u200f\u200e")
                specs[label] = value

        yield DetailItem(
            vendor_id="ivory",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_og_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )


class TmsDetailSpider(scrapy.Spider):
    name = "tms_detail"
    allowed_domains = ["tms.co.il"]

    # Mirrors spiders/tms.py exactly — same site, same home IP, same §7
    # rules apply to detail pages as to category pages. Block responses
    # must reach parse_detail (not be silently dropped) so _register_block
    # can count them.
    handle_httpstatus_list = list(BLOCK_STATUS_CODES)

    custom_settings = {
        **NON_PLAYWRIGHT_DOWNLOAD_HANDLERS,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_TIMEOUT": 60,
        "USER_AGENT": "pc-parts-il-bot (+https://pcpartsil.example/about)",
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._block_count = 0

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
        if self._register_block(response):
            return

        specs = {}
        # TMS's "מפרט" section renders as repeating (### label, value)
        # pairs — in the actual HTML this is a definition list
        # (dl > dt/dd pairs) under a container with the spec heading.
        # Confirmed working selector pattern for OpenCart-style themes:
        for dt, dd in zip(
            response.css("div.product-specification dt, div#tab-specification dt"),
            response.css("div.product-specification dd, div#tab-specification dd"),
        ):
            label = (dt.css("::text").get() or "").strip()
            value = " | ".join(t.strip() for t in dd.css("::text").getall() if t.strip())
            if label and value:
                specs[label] = value

        # Bonus: TMS puts brand/availability/price directly in meta
        # tags too — free, cheap-to-grab confirmation fields.
        meta_extra = {
            "brand": response.css('meta[property="product:brand"]::attr(content)').get(),
            "availability": response.css('meta[property="product:availability"]::attr(content)').get(),
        }

        # מק"ט (SKU) shown on-page — useful as a cross-check that the
        # vendor_sku we requested actually matches this page.
        sku_on_page = response.xpath(
            "//*[contains(text(), 'מק\"ט')]/following-sibling::text()[1]"
        ).get()

        yield DetailItem(
            vendor_id="tms",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_og_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
            extra={**meta_extra, "sku_on_page": (sku_on_page or "").strip()},
        )

    def _register_block(self, response) -> bool:
        """Same choke point as spiders/tms.py's _register_block — returns
        True (caller should stop processing this response) once a block
        is seen, and hard-closes the spider after MAX_BLOCKS_PER_RUN."""
        if response.status not in BLOCK_STATUS_CODES:
            return False

        self._block_count += 1
        self.logger.error(
            "[tms_detail] blocked (status %s) on %s — block %d/%d this run",
            response.status, response.url, self._block_count, MAX_BLOCKS_PER_RUN,
        )
        if self._block_count >= MAX_BLOCKS_PER_RUN:
            self.logger.error(
                "[tms_detail] %d block responses this run — stopping per §7 "
                "rule 6. Whatever SKUs didn't get scraped stay pending for "
                "tomorrow's run.",
                self._block_count,
            )
            raise CloseSpider(f"blocked_{self._block_count}x")
        return True


class OnePcDetailSpider(scrapy.Spider):
    name = "onepc_detail"
    allowed_domains = ["1pc.co.il"]
    custom_settings = {**NON_PLAYWRIGHT_DOWNLOAD_HANDLERS}

    # A line counts as a bare sub-group heading (like "מפרט זיכרון" /
    # "מאפייני גרפיקה" inside the packed "Specifications" cell — see
    # detail below) only if it's ALL Hebrew letters/whitespace, no
    # Latin letters or digits. Every real label/value we've seen
    # (including Hebrew-adjacent ones like "Max Memory Size...") has
    # at least one Latin letter or digit in it, so this is a safe
    # split condition rather than a guess.
    _HEBREW_ONLY_RE = re.compile(r"^[\u0590-\u05FF\s]+$")

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        for entry in _load_pending("1pc"):
            yield scrapy.Request(
                url=entry["url"],
                callback=self.parse_detail,
                meta={"vendor_sku": entry["vendor_sku"]},
            )

    def parse_detail(self, response):
        specs = self._parse_spec_table(response)
        if not specs:
            # Fallback for products where the specs tab is empty/
            # missing: the flat comma-separated string still shows
            # on the main Overview panel, worse data but better than
            # nothing.
            overview_text = " ".join(
                t.strip()
                for t in response.css("div.product-overview ::text, div.short-description ::text").getall()
                if t.strip()
            )
            specs = {"overview_text_raw": overview_text} if overview_text else {}

        yield DetailItem(
            vendor_id="1pc",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_og_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def _parse_spec_table(cls, response) -> dict:
        """Parses the real 'Products specifications' table:
        table.data-table, rows are either a full-width
        tr.spec-header (group name, e.g. 'CPU', 'hardware', 'Spec')
        or a td.spec-name / td.spec-value pair. Some spec-value cells
        (seen on the 'Specifications' row) pack an entire secondary
        table's worth of label/value pairs into one <p> as
        alternating text separated by <br> tags, WITH bare Hebrew
        sub-group headings (e.g. 'מפרט זיכרון' before the memory
        fields) interleaved into that same stream — those headings
        must be detected and pulled out, not paired as a label.
        """
        specs = {}
        current_group = "General"
        for row in response.css("table.data-table tr"):
            group_name = row.css("td.spec-group-name::text").get()
            if group_name:
                current_group = group_name.strip()
                continue

            label = " ".join(
                t.strip() for t in row.css("td.spec-name ::text").getall() if t.strip()
            )
            value_cell = row.css("td.spec-value")
            if not label or not value_cell:
                continue

            nested_p = value_cell.css("p")
            if nested_p:
                specs.update(cls._parse_packed_cell(nested_p.get(), current_group, label))
            else:
                value = " ".join(t.strip() for t in value_cell.css("::text").getall() if t.strip())
                if value:
                    specs[f"{current_group} / {label}"] = value
        return specs

    @classmethod
    def _parse_packed_cell(cls, html_fragment: str, group: str, label: str) -> dict:
        # Split the cell's inner HTML on <br> tags, strip remaining
        # tags from each piece, drop empties.
        raw_parts = re.split(r"<br\s*/?>", html_fragment)
        lines = []
        for part in raw_parts:
            text = re.sub(r"<[^>]+>", "", part).strip()
            if text:
                lines.append(text)

        result = {}
        subgroup = None
        i = 0
        while i < len(lines):
            line = lines[i]
            if cls._HEBREW_ONLY_RE.match(line):
                # It's a bare sub-heading, not a label — attach it as
                # a subgroup prefix for what follows and do NOT
                # consume the next line as its "value".
                subgroup = line
                i += 1
                continue
            if i + 1 >= len(lines):
                # Trailing unpaired line — nothing to pair it with,
                # keep it visible rather than silently dropping it.
                key_parts = [group, label, subgroup, f"{line} (unpaired)"]
                result[" / ".join(p for p in key_parts if p)] = ""
                i += 1
                continue
            sub_label, value = line, lines[i + 1]
            key_parts = [group, label, subgroup, sub_label]
            result[" / ".join(p for p in key_parts if p)] = value
            i += 2
        return result


class PlonterDetailSpider(scrapy.Spider):
    name = "plonter_detail"
    allowed_domains = ["plonter.co.il"]

    def start_requests(self):
        yield from self._build_requests()

    async def start(self):
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        # Plonter needs Playwright to get past its WAF — same as
        # plonter.py's alon.tmpl fetch. Plain scrapy.Request almost
        # certainly 403s or gets a challenge page here.
        for entry in _load_pending("plonter"):
            yield scrapy.Request(
                url=entry["url"],
                callback=self.parse_detail,
                meta={
                    "vendor_sku": entry["vendor_sku"],
                    "playwright": True,
                    "playwright_include_page": False,
                    "playwright_context": "default",
                },
            )

    def parse_detail(self, response):
        response = response.replace(encoding="windows-1255")
        specs = {}

        # Plonter's spec table: <table width="100%"> rows with 3 <td> cells:
        #   cell 0 — Hebrew label (often bare ":" when no translation exists)
        #   cell 1 — value in <td dir="ltr">, sometimes wrapped in <a> whose
        #            href has attcode=Key and att=Value params (most reliable)
        #   cell 2 — English attribute key in <td align="left">
        #
        # Verified against real saved HTML (AMD 100-100000510BOX detail page,
        # lines ~7825-8044 of the saved view-source). The only rows with
        # 3+ cells are the real spec rows; header/section rows have fewer cells
        # or use colspan, so len(cells) < 3 is a reliable skip condition.
        for row in response.css("table > tbody > tr"):
            cells = row.css("td")
            if len(cells) < 3:
                continue

            value_cell = cells[1]
            key_cell = cells[2]

            key = (key_cell.css("::text").get() or "").strip()
            if not key:
                continue

            # Prefer the att= URL param from the value link (machine-readable,
            # never mangled by encoding). Fall back to plain cell text.
            link = value_cell.css("a[href*='stores_word/mainatt.tmpl']")
            if link:
                href = link.attrib.get("href", "")
                att_match = re.search(r"att=([^&]+)", href)
                value = (
                    _html.unescape(att_match.group(1)).strip()
                    if att_match
                    else " ".join(
                        t.strip()
                        for t in link.css("::text").getall()
                        if t.strip()
                    )
                )
            else:
                value = " ".join(
                    t.strip()
                    for t in value_cell.css("::text").getall()
                    if t.strip()
                )

            if key and value:
                specs[key] = value

        yield DetailItem(
            vendor_id="plonter",
            vendor_sku=response.meta["vendor_sku"],
            url=response.url,
            specs=specs,
            image_url=_og_image(response),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )


"""
Add to scraper/items.py:

class DetailItem(scrapy.Item):
    vendor_id = scrapy.Field()
    vendor_sku = scrapy.Field()
    url = scrapy.Field()
    specs = scrapy.Field()       # dict[str, str]
    image_url = scrapy.Field()   # source URL, downloaded separately
    scraped_at = scrapy.Field()
    extra = scrapy.Field()       # optional, vendor-specific bonus fields
"""
