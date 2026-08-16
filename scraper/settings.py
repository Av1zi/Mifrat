# scraper/settings.py

BOT_NAME = "pc_parts_il"
SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

# =====================================================================
# 1. IDENTITY & ANTI-BOT (Applies to ALL spiders: TMS, 1PC, Plonter, Ivory)
# =====================================================================
# We use a realistic browser User-Agent so vendors don't immediately 
# reject us as a python-requests/scrapy script.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"

DEFAULT_REQUEST_HEADERS = {
   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
   "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
   "Accept-Encoding": "gzip, deflate, br",
   "Sec-Fetch-Dest": "document",
   "Sec-Fetch-Mode": "navigate",
   "Sec-Fetch-Site": "none",
   "Sec-Fetch-User": "?1",
   "Upgrade-Insecure-Requests": "1"
}

# Disable cookies to prevent vendors from tracking our session and banning us
COOKIES_ENABLED = False

# =====================================================================
# 2. ROBOTS.TXT POLICY (Per project plan §17)
# =====================================================================
# Explicitly ignoring robots.txt to access TMS configurator and Plonter alon.tmpl
ROBOTSTXT_OBEY = False

# =====================================================================
# 3. ERROR HANDLING & DEBUGGING
# =====================================================================
# Allow HTTP errors to pass through to the spider's parse method.
# By default, Scrapy drops 403/404 silently. This is crucial for debugging WAF blocks.
HTTPERROR_ALLOWED_CODES = [403, 404, 500, 502, 503, 504]

# =====================================================================
# 4. RATE LIMITING & POLITENESS
# =====================================================================
# Since we are ignoring robots.txt, we MUST be polite with concurrency 
# and delays to avoid getting our Scrapy Cloud IPs permanently banned.
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.5

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.5
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5

# =====================================================================
# 5. TIMEOUTS & RETRIES
# =====================================================================
# Plonter's alon.tmpl is a massive single file containing the whole catalog.
# We need a longer timeout to ensure it doesn't fail halfway through downloading.
DOWNLOAD_TIMEOUT = 90
RETRY_ENABLED = True
RETRY_TIMES = 2

# =====================================================================
# 6. OUTPUT & LOGGING
# =====================================================================
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"

# =====================================================================
# 7. SCRAPY CLOUD SPECIFICS
# =====================================================================
# Telnet console host needs to be 0.0.0.0 for Scrapy Cloud to work properly
TELNETCONSOLE_HOST = "0.0.0.0"