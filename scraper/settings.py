BOT_NAME = "pc_parts_il"

SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

# §11: rate-limit yourself. A few req/s sustained over minutes is a very
# different load profile than a burst. Tune per-vendor with custom_settings
# on the spider if one site needs to be gentler.
DOWNLOAD_DELAY = 1.5
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5

ROBOTSTXT_OBEY = False
# Decision (Aug 2026, see pc-parts-il-plan.md §17 decision log): the project
# owner has explicitly chosen to disregard robots.txt Disallow rules after
# weighing the tradeoffs — see the decision log entry for the reasoning and
# caveats. This is a deliberate, documented choice, not an oversight.
# Rate-limiting below is even more important now that we're not
# self-restricting via robots.txt — don't loosen DOWNLOAD_DELAY/
# CONCURRENT_REQUESTS_PER_DOMAIN as a result of this change.

# §7 step 3: some older Israeli retail sites still serve Windows-1255 instead
# of UTF-8 for Hebrew text. Scrapy usually auto-detects from the response's
# Content-Type/meta charset, but if a vendor's pages come through as mojibake,
# override per-spider with:
#   response.replace(encoding="windows-1255")
# rather than assuming UTF-8 project-wide.

USER_AGENT = "pc-parts-il-bot (+https://pcpartsil.example/about)"  # replace with real contact URL once domain is live

ITEM_PIPELINES = {
    # "scraper.pipelines.ValidationPipeline": 100,
}

# Scrapy Cloud (Zyte) picks these up automatically when deployed via shub;
# no extra config needed here for that part.

LOG_LEVEL = "INFO"

# Makes .jsonl output human-readable (real Hebrew characters, ® ™ etc.)
# instead of Scrapy's default \uXXXX-escaped JSON for non-ASCII text. Purely
# cosmetic — json.loads() decodes \uXXXX escapes correctly either way, so
# this doesn't change the actual data, just how it looks when you open the
# file yourself.
FEED_EXPORT_ENCODING = "utf-8"
