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

# Default for cloud-run vendors (1PC, Plonter, later Ivory) — see
# pc-parts-il-plan.md §14 and DECISIONS.md. TMS overrides this to True in
# its own custom_settings (scraper/spiders/tms.py) since it's the one
# spider that runs on the Nano, where robots.txt IS followed.
ROBOTSTXT_OBEY = False

# Cloudflare/WAFs 403 self-declared bots from datacenter IPs.
# Present as an ordinary Chrome browser instead.
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

LOG_LEVEL = "INFO"

FEED_EXPORT_ENCODING = "utf-8"