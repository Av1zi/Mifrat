BOT_NAME = "pc_parts_il"
SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

# §11: rate-limit yourself. A few req/s sustained over minutes is a very
# different load profile than a burst. Tune per-vendor with custom_settings
# on the spider if one site needs to be gentler.

# --- Global Settings ---
DOWNLOAD_DELAY = 1.5
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5
DOWNLOAD_TIMEOUT = 60

# Decision (Aug 2026, see pc-parts-il-plan.md §17 decision log): the project
# owner has explicitly chosen to disregard robots.txt Disallow rules after
# weighing the tradeoffs — see the decision log entry for the reasoning and
# caveats. This is a deliberate, documented choice, not an oversight.
# Rate-limiting below is even more important now that we're not
# self-restricting via robots.txt.
ROBOTSTXT_OBEY = False

# §7 step 3: some older Israeli retail sites still serve Windows-1255 instead
# of UTF-8 for Hebrew text. Scrapy usually auto-detects from the response's
# Content-Type/meta charset, but if a vendor's pages come through as mojibake,
# override per-spider with:
# response.replace(encoding="windows-1255")
# rather than assuming UTF-8 project-wide.

# Cloudflare/WAFs 403 self-declared bots from datacenter IPs.
# Present as an ordinary Chrome browser instead.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Generic, well-formed browser headers for ALL vendors. 
# CRITICAL FIX: 
# 1. Removed trailing spaces from keys (e.g. "Accept " -> "Accept")
# 2. Fixed the broken wildcard ("/ " -> "*/*")
# 3. Removed vendor-specific Referer (handled per-request if needed)
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

# Scrapy Cloud (Zyte) picks these up automatically when deployed via shub;
# no extra config needed here for that part.
LOG_LEVEL = "INFO"

# Makes .jsonl output human-readable (real Hebrew characters, ® ™ etc.)
# instead of Scrapy's default \uXXXX-escaped JSON for non-ASCII text.
FEED_EXPORT_ENCODING = "utf-8"