"""
Plonter spider.

## robots.txt: NOT observed for this project (see decisions.md). This
spider deliberately hits a path (`/pnp/alon.tmpl`) that Plonter's
robots.txt disallows (`Disallow: /pnp/`) — an intentional, documented
decision, not an oversight. See settings.py (ROBOTSTXT_OBEY = False).

## Canonical domain: plonter.co.il only

plonter.com/main.tmpl was also checked and appears to serve the same
content without redirecting — a genuinely separate, independently-served
site rather than a mirror. Only plonter.co.il has been characterized. Do
not point this spider at plonter.com without separately re-verifying it.

## The data source: /pnp/alon.tmpl — full catalog feed

  GET https://www.plonter.co.il/pnp/alon.tmpl

Response is windows-1255-encoded HTML containing one `<pre>` tag per row
(the first `<pre>` is the tab-separated header):

  sku  title  description  category  division  shelf  price_total  tree
  image_file  amount  engdivision

Entire catalog in one response — no pagination.

## Product URL (RESOLVED, Aug 2026 — see PlonterFindings.md)

  https://www.plonter.co.il/detail.tmpl?sku={sku}

Confirmed directly from Plonter's own recon doc, not guessed. Previously
this spider shipped with url=None; that gap is closed below.

## `tree` field (Aug 2026: now wired into vendor_meta)

Space-separated list of internal category IDs per listing (e.g. `ACAM4`
for AMD AM4 CPUs, `B1700D5ATX` for Intel LGA1700 DDR5 ATX boards) — a much
finer-grained taxonomy than `category`/`division`. Passed through as
vendor_meta["tree"]; scraper/extractors.py's PLONTER_TREE_LABELS decodes
it into socket/chipset/memory_type/form_factor attributes instead of
re-deriving them from title text alone.

## WAF (Imperva Incapsula) — read this before changing the fetch

Plonter fronts the whole site with Imperva Incapsula. An unrecognized client
gets a JS-challenge page instead of the feed — and *which* build of Chromium
we ask for decides whether that challenge ever clears:

  - Playwright's default headless **shell** is detected: every navigation
    returns the challenge (Sep 2026 status 200 with an `_Incapsula_Resource`
    iframe, or 403 from the CI datacenter IP), so the spider yielded zero
    items and scrape-cloud's §10 count-check failed the job.
  - The full Chromium build (`channel: "chromium"` in settings.py) solves the
    challenge and gets the real feed.

Even so, the *first* response can still be the challenge page while the
solved cookie is being set, so `parse()` re-requests the feed a bounded
number of times (MAX_FEED_ATTEMPTS) before giving up loudly. Cookies live on
the shared `default` Playwright context, so the retry is what makes the
solved challenge stick.

## Known gaps (still open)
- `amount` blank in several sampled rows — unclear whether blank means
  "in stock, quantity not tracked" or "out of stock, 0 suppressed."
  Treating blank as unknown (in_stock=None) rather than assuming.
- Content spans well beyond PC-hardware (storage controllers, USB devices,
  etc.) — no filtering applied here; normalize_and_match.py should expect
  out-of-scope rows and filter by category/division/tree downstream.
  (Encoding: this feed arrives via Playwright as decoded Unicode — do NOT
  force windows-1255 on the response; that mojibakes Hebrew. See parse().)

## Also available, not yet wired in
`/pnp/alonDT.tmpl` returns the category tree as JSON
(`categories['systems']['Platform']['subsystems']['Form Factor'][]` etc.,
per PlonterFindings.md). Not necessary for the raw scrape — noted here in
case the matcher wants richer category structure later.
"""
import scrapy
from datetime import datetime, timezone
from urllib.parse import quote
from scrapy_playwright.page import PageMethod
from scraper.items import ListingItem

VENDOR_ID = "plonter"
ALON_FEED_URL = "https://www.plonter.co.il/pnp/alon.tmpl"
PRODUCT_URL_TEMPLATE = "https://www.plonter.co.il/detail.tmpl?sku={sku}"

# Incapsula answers an unrecognized client with 403 (CI) or a 200-status
# challenge body.
BLOCK_STATUS_CODES = {403, 429}
# The challenge clears on a subsequent request against the same browser
# context, so a couple of extra tries is all this needs — this is not a
# "keep hammering a blocking WAF" loop (see the module docstring).
MAX_FEED_ATTEMPTS = 4

COLUMNS = [
    "sku", "title", "description", "category", "division",
    "shelf", "price_total", "tree", "image_file", "amount", "engdivision",
]

# Only include relevant PC building components. 
# Normalized to lowercase for case-insensitive matching against the feed.
ALLOWED_ENGDIVISIONS = {
    "hard drives",          # Includes SSDs per feed structure
    "motherboards",
    "cpus",
    "fans and cooling solutions",
    "liquid cooling",
    "computer cases",
    "memory",
    "display adapters",
    "power supply",
    "power supplies",       # Added plural just in case the feed varies
}

class PlonterSpider(scrapy.Spider):
    name = "plonter"
    allowed_domains = ["plonter.co.il"]
    # Let a blocked response reach parse() instead of Scrapy's
    # HttpErrorMiddleware swallowing it as "Ignoring non-200 response"
    # before anything can retry the challenge.
    handle_httpstatus_list = sorted(BLOCK_STATUS_CODES)

    def start_requests(self):
        # Fallback for Scrapy <2.13
        yield from self._build_requests()

    async def start(self):
        # Scrapy >=2.13 entrypoint (StartSpiderMiddleware calls this)
        for request in self._build_requests():
            yield request

    def _build_requests(self):
        # Phase-0 verification (Sep 2026 403x4): the CI "Overridden settings"
        # dump never shows PLAYWRIGHT_* keys because they are BASE settings,
        # not overrides — log them once here so any job log proves which
        # browser shape actually ran (full chromium vs headless shell, and
        # the coherent he-IL desktop context).
        try:
            self.logger.info(
                "Plonter PLAYWRIGHT_LAUNCH_OPTIONS=%r PLAYWRIGHT_CONTEXTS=%r "
                "NAV_TIMEOUT=%r",
                self.settings.get("PLAYWRIGHT_LAUNCH_OPTIONS"),
                self.settings.get("PLAYWRIGHT_CONTEXTS"),
                self.settings.get("PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT"),
            )
        except Exception:
            pass
        self.logger.info("Plonter _build_requests – requesting alon.tmpl with Playwright")
        yield self._feed_request(1)

    def _feed_request(self, attempt: int):
        return scrapy.Request(
            ALON_FEED_URL,
            meta={
                "playwright": True,
                "playwright_include_page": False,
                "playwright_context": "default",
                "plonter_attempt": attempt,
                # Real challenge wait: the pre-fix spider resolved each
                # attempt in ~7s total, so the Incapsula JS never had time to
                # set its cookie before parse() judged the page. Waiting for
                # the feed's own <pre> (30s) gives a solving challenge time
                # to land; a hard IP-block still surfaces as a bounded
                # wait-timeout via _error (distinct marker), never a loop —
                # MAX_FEED_ATTEMPTS stays 4 (plan §7 spirit: no hammering).
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", "pre", timeout=30000),
                ],
            },
            callback=self.parse,
            errback=self._error,
            # The challenge retry re-requests an already-seen URL, which the
            # duplicate filter would otherwise drop.
            dont_filter=True,
        )

    def parse(self, response):
        attempt = int(response.meta.get("plonter_attempt") or 1)

        # NOTE: no response.replace(encoding="windows-1255") here. The feed
        # arrives via Playwright, which hands us already-decoded Unicode
        # re-serialized as UTF-8; forcing windows-1255 re-interprets those
        # UTF-8 bytes and mojibakes every Hebrew string (same bug that
        # poisoned the detail scrape — see detail_pages.py). Scrapy's
        # default decoding is correct as-is.

        pre_blocks = response.css("pre::text").getall()
        try:
            body_len = len(response.body or b"")
        except Exception:
            body_len = -1
        try:
            incapsula = "_Incapsula_Resource" in (response.text or "")
        except Exception:
            incapsula = False
        self.logger.info(
            "plonter-attempt status=%s attempt=%s/%s pre=%s bytes=%s incapsula=%s",
            response.status, attempt, MAX_FEED_ATTEMPTS,
            len(pre_blocks), body_len, incapsula,
        )

        if response.status in BLOCK_STATUS_CODES or len(pre_blocks) < 2:
            kind = (
                f"403x{attempt}" if response.status in BLOCK_STATUS_CODES
                else f"200-but-{len(pre_blocks)}-pre"
            )
            if attempt < MAX_FEED_ATTEMPTS:
                self.logger.warning(
                    f"plonter-retry {kind} "
                    f"(status {response.status}, {len(pre_blocks)} <pre>, "
                    f"{body_len} bytes, incapsula={incapsula}) - retrying; the "
                    "Incapsula challenge clears on the next request once the "
                    "browser has run its JS."
                )
                yield self._feed_request(attempt + 1)
                return
            # Terminal markers are greppable and distinct: 403x4 (IP-class
            # block) vs 200-but-0/1-pre (challenge served, feed missing) vs
            # parsed-N-filtered-0 below (feed parsed, filter ate everything).
            self.logger.error(
                f"plonter-terminal-{kind}-after-{MAX_FEED_ATTEMPTS} "
                f"(status {response.status}, {len(pre_blocks)} <pre>, "
                f"{body_len} bytes, incapsula={incapsula}) - Plonter's WAF is "
                "refusing this client/IP. Zero items are written, so "
                "run_spider.py's count-check (section 10) fails the job "
                "instead of shipping an empty day."
            )
            return

        # Header guard: pre_blocks[0] is the tab-separated header. COLUMNS is
        # zipped positionally below, so a silent column add/reorder would
        # misalign every field — log the header and fail loud per-row.
        try:
            header_fields = pre_blocks[0].strip("\r\n").split("\t")
            self.logger.info(
                "plonter-header cols=%s header=%r",
                len(header_fields), pre_blocks[0][:200],
            )
            if len(header_fields) != len(COLUMNS):
                self.logger.warning(
                    f"plonter-header-mismatch got={len(header_fields)} "
                    f"expected={len(COLUMNS)} — per-row misalignment guard "
                    "will skip off-count rows"
                )
        except Exception as exc:
            self.logger.warning(f"plonter-header-unparseable: {exc!r}")

        n_rows = 0
        n_kept = 0
        n_filtered_engdiv = 0
        n_skip_no_sku = 0
        n_skip_col_mismatch = 0
        for raw_row in pre_blocks[1:]:
            n_rows += 1
            fields = raw_row.strip("\r\n").split("\t")
            if len(fields) != len(COLUMNS):
                n_skip_col_mismatch += 1
                if n_skip_col_mismatch <= 3:
                    self.logger.warning(
                        f"plonter-col-mismatch row {n_rows}: got={len(fields)} "
                        f"expected={len(COLUMNS)} sku_field={fields[0] if fields else ''!r}"
                    )
                continue
            row = dict(zip(COLUMNS, fields))

            sku = row.get("sku")
            if not sku:
                n_skip_no_sku += 1
                continue

            # Filter by engdivision to only include relevant PC parts
            eng_div = (row.get("engdivision") or "").strip().lower()
            if eng_div not in ALLOWED_ENGDIVISIONS:
                n_filtered_engdiv += 1
                continue  # Skip networking, peripherals, cables, etc.
            n_kept += 1

            # The feed's image_file is a filename (e.g. MG07ACA12TE.jpg);
            # full-size images live under graphics/product_images/full/
            # (same path as the detail pages' og:image:url). Free photo
            # coverage for every listing; detail og:image still wins when
            # present (see _merge_detail_specs).
            image_file = (row.get("image_file") or "").strip()
            image_url = (
                f"https://www.plonter.co.il/graphics/product_images/full/{image_file}"
                if image_file
                else None
            )

            yield ListingItem(
                vendor_id=VENDOR_ID,
                vendor_sku=sku,
                title_raw=row.get("title"),
                url=PRODUCT_URL_TEMPLATE.format(sku=quote(sku)),
                price_ils=row.get("price_total"),
                in_stock=True,  # Explicitly set to True
                category_guess=row.get("engdivision"),  # Clean English category
                image_url=image_url,
                vendor_meta={
                    # Space-separated internal taxonomy IDs (e.g. "ACAM4",
                    # "B1700D5ATX") — decoded downstream via the static
                    # PLONTER_TREE_LABELS table in extractors.py (see
                    # PlonterFindings.md). Finer-grained than engdivision.
                    "tree": row.get("tree"),
                },
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

        # Kept-vs-filtered summary: distinguishes "feed shrank" from "filter
        # ate everything" (parsed-N-filtered-0) from "blocked" above.
        self.logger.info(
            "plonter-rows total=%s kept=%s filtered_engdiv=%s skip_no_sku=%s "
            "skip_col_mismatch=%s",
            n_rows, n_kept, n_filtered_engdiv, n_skip_no_sku,
            n_skip_col_mismatch,
        )
        if n_kept == 0:
            self.logger.error(
                f"plonter-terminal-parsed-{n_rows}-filtered-0 "
                f"(filtered_engdiv={n_filtered_engdiv} "
                f"skip_no_sku={n_skip_no_sku} "
                f"skip_col_mismatch={n_skip_col_mismatch}) - feed parsed but "
                "the engdivision filter kept nothing; suspect a feed format "
                "change (new column order or fresh engdivision values), not "
                "an IP block. Zero items are written, so run_spider.py's "
                "count-check fails the job."
            )

    def _error(self, failure):
        """Network/Playwright failure (403/429 bodies go to parse() instead).

        Terminal marker here means the browser itself never delivered a page
        (launch crash, navigation timeout, <pre>-wait timeout) — distinct
        from the WAF-block markers in parse().
        """
        request = getattr(failure, "request", None)
        attempt = int((request.meta.get("plonter_attempt") if request else 0) or 1)
        err = repr(failure.value)
        # The <pre>-wait timeout is the expected shape of a hard block under
        # the new wait: the challenge never renders the feed. Name it so the
        # log greps apart from launch crashes.
        kind = (
            "wait-timeout" if ("Timeout" in err or "timeout" in err) else "browser-launch-failure"
        )
        self.logger.error(f"plonter-{kind} attempt={attempt}/{MAX_FEED_ATTEMPTS}: {err}")
        if attempt < MAX_FEED_ATTEMPTS:
            self.logger.warning(
                f"Plonter feed attempt {attempt}/{MAX_FEED_ATTEMPTS} failed "
                f"({kind}) — retrying"
            )
            yield self._feed_request(attempt + 1)
        else:
            self.logger.error(
                f"plonter-terminal-{kind}-after-{MAX_FEED_ATTEMPTS} - browser "
                "never delivered the feed. Zero items are written, so "
                "run_spider.py's count-check fails the job."
            )
