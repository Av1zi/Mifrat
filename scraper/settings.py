# MUST be at the very top of the file, before ANY other imports or settings
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

BOT_NAME = "pc_parts_il"
SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

# --- Global Settings ---
DOWNLOAD_DELAY = 1.5
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5
DOWNLOAD_TIMEOUT = 60

# Default for cloud-run vendors (1PC, Plonter, later Ivory)
ROBOTSTXT_OBEY = False

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

ITEM_PIPELINES = {
    # "scraper.pipelines.ValidationPipeline": 100,
}

# --- scrapy-playwright (required for Plonter) ---
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
# 90s so the Incapsula JS challenge has wall-clock time to set its cookie
# before navigation resolves. A fast 403 still resolves fast — the timeout
# only matters when the challenge is actually running.
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 90000
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    # `channel: "chromium"` selects Playwright's *full* Chromium build instead
    # of the headless *shell* it otherwise launches. Plonter sits behind
    # Imperva Incapsula, and the shell is detected by it: every navigation
    # comes back as the JS-challenge page (Sep 2026 — the 403/zero-item
    # scrape-cloud failure). Verified 2026-09-28: the shell returned 0 <pre>
    # rows on every attempt while the full build returned the 5,654-row feed
    # on the first try. `playwright install chromium` (what both workflows
    # run) installs BOTH builds, so no extra install step is needed; spiders
    # that never set playwright=True (TMS on the Nano, onepc, ivory) are
    # unaffected — no browser is launched for them.
    "channel": "chromium",
}
# Coherent desktop shape for the shared "default" Playwright context (used by
# the Plonter listing + detail fetches). The challenge risk-scores the whole
# fingerprint: UA (== USER_AGENT above), he-IL locale, Asia/Jerusalem
# timezone, and a normal desktop viewport instead of the default headless
# profile. Deliberately NOT stealth plugins, flag-stripping, proxies, or
# CAPTCHA services (plan §14 + AGENTS.md binding).
PLAYWRIGHT_CONTEXTS = {
    "default": {
        "user_agent": USER_AGENT,
        "viewport": {"width": 1366, "height": 768},
        "locale": "he-IL",
        "timezone_id": "Asia/Jerusalem",
    },
}

LOG_LEVEL = "INFO"
FEED_EXPORT_ENCODING = "utf-8"