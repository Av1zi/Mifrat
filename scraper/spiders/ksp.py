"""
KSP (ksp.co.il) spider — the store's own public catalog JSON.

## Why curl_cffi is needed

KSP sits behind Cloudflare Bot Management. A plain HTTP client (including
Scrapy's default downloader and a headless Chromium session) receives a
custom "הגישה נחסמה" 403 page; the same public catalog answers 200 to a
browser-shaped TLS handshake plus the storefront's XHR headers. The
`scrapy-curl-cffi` handler provides that handshake; the spider sets the
headers and a per-request impersonation profile. This is a deliberate,
logged exception (see decisions.md) under the home-run rules: one run/day,
one request at a time, no proxies, no CAPTCHA solving, abort on blocks.

## Client hints (2026-11-04)

Since roughly 2026-11-02 the edge also answers a *browser-shaped* request
with a managed challenge (`403`, `cf-mitigated: challenge`, the Hebrew
"אימות אבטחה" page) unless the request repeats the high-entropy UA client
hints named in the challenge's `Accept-CH`/`Critical-CH` headers. curl_cffi
sends only the low-entropy hints (`sec-ch-ua`, `-mobile`, `-platform`) and
never performs the browser's "retry with the requested hints" step, so a
plain impersonated request is now challenged while the identical request
with the hints below answers 200 (verified on all 13 category tags). CLIENT_HINTS
therefore goes on every KSP request, including Scrapy's own robots.txt
fetch. Keep the UA and the `sec-ch-ua*` values on the same browser build as
IMPERSONATE: the edge risk-scores the whole fingerprint, not just TLS.

## API

    GET https://ksp.co.il/m_action/api/category/<tag>?page=<n>

12 items per page, `result.products_total` and `result.next` are present on
every page. Tag ids and their canonical category guesses are in CATEGORIES.

The detail endpoint (`/m_action/api/item/<uin>`) is WAF-blocked (403 under
every impersonation, including an in-page browser fetch), and the product
page is an empty SPA shell, so this spider is listing-only. The listing
`tags` dict is preserved in `vendor_meta` for a future typed-spec mapping.

## All-or-nothing

Items are buffered in memory and only yielded once every category has
completed successfully. Any unrecoverable page/category failure closes the
spider before anything is yielded, so `run_spider.py` sees a zero-item feed
and exits non-zero rather than publishing a partial day.
"""

import json
import re
from datetime import datetime, timezone

import scrapy
from scrapy.exceptions import CloseSpider

from scraper.items import ListingItem

VENDOR_ID = "ksp"
API_URL = "https://ksp.co.il/m_action/api/category/{tag}?page={page}"
PRODUCT_URL = "https://ksp.co.il/web/item/{uin}"
# Pin the TLS profile instead of using the "chrome" alias: the alias follows
# whatever curl-cffi ships last, but the UA and CLIENT_HINTS below are a fixed
# build, and Cloudflare compares them. Bump all three together.
IMPERSONATE = "chrome146"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

# KSP catalog tag id -> our pipeline category guess. Counts checked 2026-10-30.
# The guesses use the same vendor-agnostic spellings Ivory does (`ram`, `ssd`,
# `hdd`, `cpu_cooler_air`, `cpu_cooler_aio`, `case_fans`); canonical_category()
# maps them to memory/storage/cooler_air/aio/case_fan. `accessories` is the
# single accessory umbrella the pipeline already uses.
#
# The cooling tags are a HINT, not a verdict: KSP's "קירור" tree mixes parts
# and accessories, and its two cooler leaves overlap (a liquid cooler is
# listed under BOTH `מאווררים למעבדים` (182) and `קירור נוזלי` (1329)). The
# air/liquid split and the accessory/out-of-scope rows are therefore decided
# per row in _refine_guess, from the row's own title and `סוג` tag — see the
# regexes below. Guessing by tag alone made the split depend on which page
# answered first (the tag that claimed a uin won it).
CATEGORIES = (
    ("2", "cpu"),                     # מעבדים — 45 (was 53; rebaselined 2026-11-11)
    ("3", "motherboard"),             # לוחות אם — 158
    ("1038", "ram"),                  # זכרונות למחשב — 156
    ("35", "gpu"),                    # כרטיסי מסך — 104
    ("130", "case"),                  # מארזים — 130
    ("140", "psu"),                   # ספקי כוח — 65
    ("152", "ssd"),                   # כונני SSD פנימיים — 99
    ("145", "hdd"),                   # ד. קשיחים פנימיים — 18
    ("182", "cpu_cooler_air"),        # מאווררים למעבדים — 94 (some AIOs are filed here too)
    ("1329", "cpu_cooler_aio"),       # קירור נוזלי — 63
    ("186", "case_fans"),             # מאווררים למארזים — 107
    ("187", "accessories"),           # משחות תרמיות — 22
    ("188", "accessories"),           # בקרים למאווררים — 18
)
CATEGORY_COUNTS = {tag: count for tag, count in (
    ("2", 45), ("3", 158), ("1038", 156), ("35", 104), ("130", 130),
    ("140", 65), ("152", 99), ("145", 18), ("182", 94), ("1329", 63),
    ("186", 107), ("187", 22), ("188", 18),
)}
# A complete run must still ship at least 80% of the verified baseline total
# (the uin dedupe across cooling tags accounts for ~5%). This is deliberately
# a hard gate, not the warning-only run_spider floor.
MIN_TOTAL_ITEMS = int(sum(CATEGORY_COUNTS.values()) * 0.80)
# Per-category floor on page-1 products_total. 0.85 was too tight for normal
# catalog churn: 2026-11-08..11 the CPU tag listed 43-45 of its 53 baseline
# (< 45.05) and four nights of all-200 crawls were thrown away. 0.70 still
# fails a category that collapses; truncation is MIN_FETCHED_SHARE's job.
MIN_CATEGORY_SHARE = 0.70
MIN_FETCHED_SHARE = 0.95
MAX_UNKNOWN_STOCK_SHARE = 0.05
# Small categories get absolute slack instead of a pure percentage. A tiny
# leaf naturally churns a few SKUs, and the all-or-nothing rule would turn a
# 2-item dip into a total outage (2026-11-06: HDD tag 145 fell 18->15, and
# 15 < 18*0.85 = 15.3 killed a run whose 93 pages all answered 200;
# 2026-11-07: 14). Baselines under MIN_SMALL_CATEGORY_BASELINE allow up to
# MIN_SMALL_CATEGORY_SLACK missing rows (18 -> 13 here); anything deeper
# still fails and asks for a re-baseline review. Real truncation remains
# caught by MIN_FETCHED_SHARE (0.95) and MIN_TOTAL_ITEMS (80%).
MIN_SMALL_CATEGORY_BASELINE = 25
MIN_SMALL_CATEGORY_SLACK = 5

# Cooling-row placement (KSP storefront's "קירור" tree, verified 2026-11-02):
#
#   מאווררים למעבדים  (182)  desktop CPU coolers, air AND liquid in one leaf
#   קירור נוזלי       (1329) the same liquid coolers, listed a second time
#   מאווררים למארזים  (186)  case fans, plus anti-vibration pads and mounts
#   משחות תרמיות      (187)  thermal paste and thermal pads
#   בקרים למאווררים   (188)  fan controllers, hubs and iCUE/SATA cables
#   מאוורר USB, קירור למחשבים ניידים, קירור לכונני אחסון
#                            laptop / USB / drive cooling — not desktop parts
COOLING_GUESSES = frozenset(
    {"cpu_cooler_air", "cpu_cooler_aio", "case_fans", "accessories"}
)

# Rows inside the "קירור" tree that are *accessories* rather than the part
# they plug into: anti-vibration pads, Y-cables, mounting adapters, cooler
# expansion / offset / air-duct kits. They are real products this catalogue
# sells, so they go to `accessories` — not to the cooler/fan leaf that merely
# names the part they fit. Only cosmetic covers are dropped (see below).
# Hebrew first: KSP titles are Hebrew-only, so the English rules in
# matching._category_from_title never see them (see the matching.py hints for
# the same words on the normalizer side).
COOLING_ACCESSORY_TITLE_RE = re.compile(
    r"^\s*(?:סט\s+\d+\s+|זוג\s+|שני\s+|שתי\s+)?"
    r"(?:רפידות|תושבות|פדים|מתא(?:ם|מי)|כבלי?|תעלת\s*אוויר)\b|"
    r"^\s*ערכת\s*(?:הרחבה|התקנה|הרכבה|הסטה|שדרוג|כבלים|תעלת)|"
    r"\bNA-(?:SAV|SYC|SFMA|FK|FD)\w*\b",
    re.I,
)
# KSP lists decorative cooler shrouds ("כיסוי עיצובי") under the CPU coolers;
# they are not comparable products, and they are the one cooling row group
# this catalogue still drops.
COSMETIC_COVER_TITLE_RE = re.compile(r"כיסוי\s*עיצובי", re.I)

# The whole "קירור" section also carries laptop pads, USB fans and M.2/SSD
# heatsinks. They are filtered out at the source, before the normalizer.
OUT_OF_SCOPE_COOLING_TITLE_RE = re.compile(
    r"קירור\s*למחשב(?:ים)?\s*נייד|קירור\s*לנייד|משטח\s*קירור|"
    r"מאוורר\s*USB|USB\s*(?:fan|מאוורר)|"
    r"קירור\s*לכוננ|קירור\s*ל[- ]?(?:SSD|M\.?2)|"
    r"\bheatsinks?\s*(?:for|ל)\s*(?:SSD|M\.?2|NVMe)\b",
    re.I,
)

# Liquid coolers: KSP files them under the CPU-fan leaf with `סוג` =
# "מאווררים למעבדים", so the title is the only air/liquid evidence. The
# Hebrew phrase (not the bare word) avoids the "מיסב דינמי נוזלי" bearing
# spec that matching._HEBREW_BEARING_RE also guards.
LIQUID_TITLE_RE = re.compile(
    r"קירור\s*נוזלי|נוזלי\s*למעבד|\bliquid\b|\baio\b|water\s*cool",
    re.I,
)

CASE_FAN_TITLE_RE = re.compile(r"למארז|מאוורר(?:י|ים)?\s*מארז")

# The high-entropy UA client hints the edge asks for via `Accept-CH` and
# treats as `Critical-CH` (see the module docstring). A real browser resends
# the same request with these after the first response; curl_cffi does not, so
# we send them up front on every request. Values are the Windows Chrome 146
# build named by IMPERSONATE/USER_AGENT above.
CLIENT_HINTS = {
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-arch": '"x86"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version": '"146.0.7680.76"',
    "sec-ch-ua-full-version-list": (
        '"Chromium";v="146.0.7680.76", "Not-A.Brand";v="24.0.0.0", '
        '"Google Chrome";v="146.0.7680.76"'
    ),
    "sec-ch-ua-platform-version": '"19.0.0"',
    "sec-ch-ua-model": '""',
    # Same-origin XHR, which is what this is — curl_cffi's navigation defaults
    # say document/navigate/none and contradict the JSON Accept header.
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    "Referer": "https://ksp.co.il/web/",
    "Origin": "https://ksp.co.il",
    "User-Agent": USER_AGENT,
    **CLIENT_HINTS,
}

MAX_PAGES_PER_CATEGORY = 60


def _as_int(value):
    """KSP sometimes sends numbers as strings; return None when unusable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _category_threshold(baseline: int) -> float:
    """Minimum acceptable products_total for one category page 1."""
    if baseline < MIN_SMALL_CATEGORY_BASELINE:
        return max(0, baseline - MIN_SMALL_CATEGORY_SLACK)
    return baseline * MIN_CATEGORY_SHARE


class KspFingerprintMiddleware:
    """Attach the Chrome TLS profile and client hints to every KSP request.

    One profile per run: rotating fingerprints on a 403 would be probing the
    WAF, which the home-IP exception forbids. A 403 is a stop signal (see
    KspSpider._block), not a retry cue. The middleware is still the right
    place for this because Scrapy's robots.txt fetch also runs through the
    downloader chain and needs the same options and, since 2026-11-04, the
    same client hints (a hint-less request is what the edge challenges).
    """

    IMPERSONATE = IMPERSONATE

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        spider = self.crawler.spider
        if spider is None or spider.name != VENDOR_ID:
            return None
        request.meta["curl_cffi_options"] = {"impersonate": self.IMPERSONATE}
        if request.url.endswith("/robots.txt"):
            request.headers.setdefault(b"Referer", b"https://ksp.co.il/web/")
            request.headers.setdefault(
                b"Accept-Language", b"he-IL,he;q=0.9,en;q=0.8"
            )
        for name, value in CLIENT_HINTS.items():
            request.headers.setdefault(name.encode(), value.encode())
        return None


class KspSpider(scrapy.Spider):
    name = VENDOR_ID
    allowed_domains = ["ksp.co.il"]

    custom_settings = {
        # Keep Playwright out of this spider: the Nano has no browser, and
        # KSP does not need one. Both schemes go through curl_cffi so no
        # default HTTP11 request can leak a plain TLS handshake.
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_curl_cffi.handlers.CurlCffiDownloadHandler",
            "https": "scrapy_curl_cffi.handlers.CurlCffiDownloadHandler",
        },
        "DOWNLOADER_MIDDLEWARES": {
            "scraper.spiders.ksp.KspFingerprintMiddleware": 543,
        },
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        # Randomized 3-9s (Scrapy randomizes 0.5x-1.5x). KSP rate-limits per
        # IP over a window, not just per second: 90 pages at 1.5s produced 17
        # HTTP 429s, and a 3s retry after that hit the limit twice more. Six
        # seconds keeps a daily run around 10-15 minutes, well inside the
        # Nano's 40-minute timeout, and leaves 429 retries room to recover.
        "DOWNLOAD_DELAY": 6.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        "USER_AGENT": USER_AGENT,
        # The site's robots.txt explicitly allows the catalog. Scrapy fetches
        # it through the same downloader chain (the middleware above adds the
        # TLS options and referer), verified 200 in the onboarding crawl.
        "ROBOTSTXT_OBEY": True,
        # 403 is a WAF verdict, never retried (the run stops instead).
        # 429 is a rate limit; four retries at the 6s floor covers the
        # observed per-window cap without probing the WAF.
        "RETRY_HTTP_CODES": [408, 425, 429, 500, 502, 503, 504, 522, 524],
        "RETRY_TIMES": 4,
        "DOWNLOAD_TIMEOUT": 60,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._items = []
        self._seen_uins = set()
        self._tag_uins = {tag: set() for tag, _ in CATEGORIES}
        self._tag_totals = {}
        self._done_categories = set()
        self._pending_categories = len(CATEGORIES)
        self._failed = False
        self._finalized = False
        self._counts = {}
        self._unknown_stock = 0
        self._skipped_price = 0
        self._skipped_scope = 0
        self._scraped_at = datetime.now(timezone.utc).isoformat()

    async def start(self):
        for request in self._build_requests():
            yield request

    def start_requests(self):
        # Fallback for Scrapy <2.13 (the cloud/Nano pinnings are >=2.17, but
        # the project keeps both entrypoints for every spider).
        yield from self._build_requests()

    def _build_requests(self):
        for tag, guess in CATEGORIES:
            yield scrapy.Request(
                API_URL.format(tag=tag, page=1),
                callback=self.parse_page,
                errback=self._request_failed,
                cb_kwargs={"tag": tag, "guess": guess, "page": 1},
                headers=HEADERS,
                meta={"tag": tag, "guess": guess, "page": 1},
                dont_filter=True,
            )

    def parse_page(self, response, tag, guess, page):
        # 403 is the WAF verdict and 429 (after Scrapy's bounded retries) is a
        # rate-limit stop signal. Both end the run: the home-IP exception is
        # not worth probing.
        if response.status in (403, 429):
            self._block(tag, f"page {page}: HTTP {response.status}")
            return
        if response.status != 200:
            self._fail(tag, f"page {page}: HTTP {response.status}")
            return

        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            self._fail(tag, f"page {page}: non-JSON response (possible challenge)")
            return

        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            self._fail(tag, f"page {page}: no result object")
            return

        items = result.get("items")
        if not isinstance(items, list):
            self._fail(tag, f"page {page}: no items list (API drift)")
            return

        if page == 1:
            total = _as_int(result.get("products_total"))
            if not total:
                self._fail(tag, "products_total is 0/missing — known category changed")
                return
            baseline = CATEGORY_COUNTS[tag]
            threshold = _category_threshold(baseline)
            if total < threshold:
                self._fail(
                    tag,
                    f"products_total {total} is below the minimum "
                    f"{threshold:g} for the verified baseline {baseline}",
                )
                return
            self._tag_totals[tag] = total

        # Track every uin the API showed, including rows we may skip later,
        # so pagination/coverage is measured against products_total rather
        # than against what survived mapping.
        tag_uins = self._tag_uins[tag]
        page_uins = {
            str(raw.get("uin"))
            for raw in items
            if isinstance(raw, dict) and raw.get("uin")
        }
        fresh_uins = page_uins - tag_uins
        tag_uins |= page_uins
        if page > 1 and items and not fresh_uins:
            self._fail(tag, f"page {page} added no new uins (pagination loop)")
            return
        if page == 1 and not items:
            self._fail(tag, "page 1 is empty")
            return

        for raw in items:
            mapped = self._map_item(raw, guess)
            if mapped is not None:
                self._items.append(mapped)
                self._counts[guess] = self._counts.get(guess, 0) + 1

        next_page = _as_int(result.get("next"))
        if next_page and next_page > page and page < MAX_PAGES_PER_CATEGORY:
            yield scrapy.Request(
                API_URL.format(tag=tag, page=next_page),
                callback=self.parse_page,
                errback=self._request_failed,
                cb_kwargs={"tag": tag, "guess": guess, "page": next_page},
                headers=HEADERS,
                meta={"tag": tag, "guess": guess, "page": next_page},
                dont_filter=True,
            )
            return

        total = self._tag_totals[tag]
        if len(tag_uins) < total * MIN_FETCHED_SHARE:
            self._fail(
                tag,
                f"fetched {len(tag_uins)} unique uins of {total} "
                f"(below {MIN_FETCHED_SHARE:.0%}) — short or truncated category",
            )
            return

        if self._finish_category(tag):
            yield from self._items

    @staticmethod
    def _refine_guess(title, tags, guess):
        """Place each row in the category the row itself describes.

        Scope, not spec work: KSP's memory tag includes laptop SO-DIMMs, the
        GPU and case tags include holders/panels, and the whole "קירור"
        (cooling) tree mixes parts with accessories and with laptop/USB/drive
        cooling. Before this pass the cooling tags handed their entire leaf to
        one guess — every row in the CPU-cooler leaf became `cpu_cooler_air`,
        and which tag claimed a uin depended on page order. The rules below
        read the row, so the split is stable and the accessories/out-of-scope
        rows never reach the normalizer:
          - liquid words            -> cpu_cooler_aio
          - case-fan leaf / "למארז" -> case_fans
          - pads/cables/mounts/kits -> accessories
          - paste/controller leaf   -> accessories
          - cosmetic covers         -> dropped
          - laptop/USB/drive cooler -> dropped
        """
        type_tag = str(tags.get("סוג") or "")
        if guess == "ram" and ("SODIMM" in type_tag or "לניידים" in type_tag):
            return guess, False
        if guess == "gpu" and "מחזיק" in type_tag:
            return guess, False
        if guess == "case" and "פאנלים" in type_tag:
            return guess, False

        if guess not in COOLING_GUESSES:
            return guess, True

        if OUT_OF_SCOPE_COOLING_TITLE_RE.search(title):
            return guess, False
        if COSMETIC_COVER_TITLE_RE.search(title):
            return guess, False
        if COOLING_ACCESSORY_TITLE_RE.search(title):
            return "accessories", True
        if guess == "accessories":
            # Tags 187/188: thermal paste/pads and fan controllers/hubs/cables.
            return "accessories", True
        if guess == "case_fans":
            # The leaf's own rows are fans except the pads/mounts caught above.
            return "case_fans", True
        if type_tag == "קירור נוזלי" or LIQUID_TITLE_RE.search(title):
            return "cpu_cooler_aio", True
        if CASE_FAN_TITLE_RE.search(title):
            return "case_fans", True
        return "cpu_cooler_air", True

    def _map_item(self, raw, guess):
        if not isinstance(raw, dict):
            return None

        uin = str(raw.get("uin") or "").strip()
        title = str(raw.get("name") or "").strip()
        if not uin or not title:
            return None

        tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
        guess, in_scope = self._refine_guess(title, tags, guess)
        if not in_scope:
            self._skipped_scope += 1
            return None

        price = _as_int(raw.get("price"))
        if not price or price <= 0:
            self._skipped_price += 1
            return None

        if uin in self._seen_uins:
            return None
        self._seen_uins.add(uin)

        # `outOfStock` is the store's own flag and was present on every row in
        # the onboarding crawl. Only fall back to `addToCart` when it is
        # genuinely absent; if both are absent, record out-of-stock and count
        # it so a schema change cannot silently make everything "available".
        out_of_stock = raw.get("outOfStock")
        add_to_cart = raw.get("addToCart")
        if out_of_stock is not None:
            in_stock = not bool(out_of_stock)
        elif add_to_cart is not None:
            in_stock = bool(add_to_cart)
        else:
            in_stock = False
            self._unknown_stock += 1

        labels = [
            str(label.get("msg"))
            for label in (raw.get("labels") or [])
            if isinstance(label, dict) and label.get("msg")
        ]

        image = raw.get("img")
        image_url = image if isinstance(image, str) and image.startswith("http") else None

        return ListingItem(
            vendor_id=VENDOR_ID,
            vendor_sku=uin,
            url=PRODUCT_URL.format(uin=uin),
            title_raw=title,
            price_ils=price,
            in_stock=in_stock,
            category_guess=guess,
            image_url=image_url,
            vendor_meta={
                "brand": raw.get("brandName"),
                "tags": tags,
                "min_price": raw.get("min_price"),
                "eilat_price": raw.get("eilatPrice"),
                "labels": labels,
                "dynamic_parent": bool(raw.get("is_dynamic_parent")),
                "family_id": raw.get("main_family_id"),
            },
            scraped_at=self._scraped_at,
        )

    def _finish_category(self, tag):
        if tag in self._done_categories:
            return False
        self._done_categories.add(tag)
        self._pending_categories -= 1

        if self._pending_categories > 0 or self._finalized:
            return False

        self._finalized = True
        if self._failed or not self._items:
            raise CloseSpider("ksp incomplete — no snapshot written")

        fetched = len(self._items) + self._skipped_price
        if fetched and self._skipped_price / fetched > 0.05:
            self.logger.error(
                "[ksp] %d/%d rows had no usable price (>5%%) — refusing a "
                "partial catalog",
                self._skipped_price,
                fetched,
            )
            raise CloseSpider("ksp incomplete — price coverage")
        if len(self._items) < MIN_TOTAL_ITEMS:
            self.logger.error(
                "[ksp] only %d items; hard floor is %d (80%% of the verified "
                "baseline) — refusing a short catalog",
                len(self._items),
                MIN_TOTAL_ITEMS,
            )
            raise CloseSpider("ksp incomplete — item floor")
        if self._items and self._unknown_stock / len(self._items) > MAX_UNKNOWN_STOCK_SHARE:
            self.logger.error(
                "[ksp] %d/%d rows had no stock signal — the API shape changed",
                self._unknown_stock,
                len(self._items),
            )
            raise CloseSpider("ksp incomplete — stock coverage")

        self.logger.info(
            "[ksp] complete: %d items across %d categories %s "
            "(skipped-price=%d skipped-scope=%d unknown-stock=%d)",
            len(self._items),
            len(CATEGORIES),
            self._counts,
            self._skipped_price,
            self._skipped_scope,
            self._unknown_stock,
        )
        return True

    def _fail(self, tag, reason):
        self._failed = True
        self.logger.error("[ksp] category %s: %s", tag, reason)
        if self._finish_category(tag):
            # Defensive: _finish_category raises on failure before returning
            # True, but never yield a failed buffer.
            raise CloseSpider("ksp incomplete — no snapshot written")

    def _block(self, tag, reason):
        """A WAF/rate verdict stops the whole run immediately.

        The queued category requests are cancelled by CloseSpider; nothing is
        yielded, so the day stays missing and the normalizer stale-forwards.
        """
        self._failed = True
        self.logger.error(
            "[ksp] BLOCKED (%s): %s — stopping; no snapshot written", tag, reason
        )
        raise CloseSpider("ksp blocked — no snapshot written")

    def _request_failed(self, failure):
        request = failure.request
        tag = request.meta.get("tag", "?")
        page = request.meta.get("page", "?")
        self._fail(tag, f"page {page}: request failed: {failure.value!r}")

    def closed(self, reason):
        if not self._finalized:
            self.logger.error(
                "[ksp] closed before completion (%s): pending=%d failed=%s — "
                "nothing was yielded, so today's snapshot stays missing and "
                "the normalizer stale-forwards the previous one.",
                reason,
                self._pending_categories,
                self._failed,
            )
