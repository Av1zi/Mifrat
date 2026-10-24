"""
mfr/client.py - the polite HTTP client every manufacturer fetcher shares.

Rules (AGENTS.md scraping politeness, binding for every brand):
- robots.txt is fetched once per host and OBEYED for the `*` agent; a disallowed
  URL is skipped, never fetched - except the per-host paths in ROBOTS_OVERRIDES,
  an explicit owner decision recorded next to each entry.
- At most one request per second per host (`delay`), browser-like headers.
- A 403 or 429 is a STOP signal: `Blocked` is raised, the run for that brand
  ends, and nothing retries. No proxies, no header games, no evasion - a brand
  that blocks is dropped from the supported list (see mfr/README.md).
- Raw pages are cached on disk (data/mfr/.cache, gitignored) for `max_age_days`
  so re-running the parser never re-hits the site; only the extracted JSON
  (data/mfr/<brand>.json) is committed. `offline=True` reads the cache at any
  age and never touches the network (a page that is not cached is None).
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_ROOT = ROOT / "data" / "mfr" / ".cache"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# New fetchers say what they are (decision 2026-10-23): a spoofed Chrome string
# with no browser behind it is what bot protection flags, and an honest client
# is served by every site that is going to serve us at all.
BOT_USER_AGENT = ("MifratSpecBot/1.0 (+https://github.com/Av1zi/Mifrat; "
                  "ziv.avivi.28.11@gmail.com)")
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# robots.txt paths the owner chose to fetch anyway (decision 2026-10-22: "override
# robots, never bypass blocks"). Per host and per path prefix, never global;
# each entry names why. A 403 / 429 still stops the run. Remove a host here on
# the site's request.
ROBOTS_OVERRIDES: dict[str, tuple[str, ...]] = {
    # One search per catalog part number replaces crawling the whole store to
    # find the page that prints that MPN (scraper/xref/overclockers.py).
    "www.overclockers.co.uk": ("/search",),
    # Owner decision 2026-10-22 (scraper/mfr/fractal.py): fractal-design.com's
    # robots.txt allows `*` everywhere but /studio/ and /api/, and disallows
    # ClaudeBot / anthropic-ai / GPTBot / CCBot / Google-Extended outright. The
    # owner chose to read the product pages anyway; this entry is the record of
    # that choice and covers ONLY the category listings + variant pages under
    # /products/ (the spec JSON is embedded in that HTML). /api/ and /studio/
    # stay disallowed. Remove this line if Fractal Design asks.
    "www.fractal-design.com": ("/products/",),
    # Owner policy "override robots, never bypass blocks" (2026-10-22), applied
    # 2026-10-23: ldlc.com disallows /en/search/ for `*` (robots.txt line 20) and
    # nothing else we read; no AI crawler is named. One search per catalog part
    # number, 1 req/s, identified as MifratSpecBot, run from the owner's own
    # connection (scraper/xref/ldlc.py). Remove this line if LDLC asks.
    "www.ldlc.com": ("/en/search/",),
}


class Blocked(RuntimeError):
    """The host answered 403/429: stop this brand's run, do not retry."""


class PoliteClient:
    def __init__(self, brand: str, base_url: str, *, delay: float = 1.0,
                 max_age_days: float = 7.0, timeout: float = 25.0,
                 offline: bool = False, identify: bool = False) -> None:
        self.brand = brand
        self.headers = ({"User-Agent": BOT_USER_AGENT,
                         "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
                        if identify else HEADERS)
        self.base_url = base_url.rstrip("/")
        self.delay = max(delay, 1.0)
        self.max_age = max_age_days * 86400
        self.timeout = timeout
        self.offline = offline
        self.cache_dir = CACHE_ROOT / brand
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last = 0.0
        self.requests = 0
        self.skipped_robots = 0
        self._robots: urllib.robotparser.RobotFileParser | None = None

    # -- robots -----------------------------------------------------------

    def _load_robots(self) -> urllib.robotparser.RobotFileParser:
        if self._robots is None:
            parser = urllib.robotparser.RobotFileParser()
            body = self._fetch(self.base_url + "/robots.txt", cache=True, check_robots=False)
            if body is None:
                parser.parse([])           # no robots.txt (404): nothing disallowed
            else:
                parser.parse(body.splitlines())
            self._robots = parser
        return self._robots

    def allowed(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        if any(parsed.path.startswith(prefix)
               for prefix in ROBOTS_OVERRIDES.get(parsed.netloc, ())):
            return True
        return self._load_robots().can_fetch("*", url)

    # -- fetching ---------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".html")

    def _fetch(self, url: str, *, cache: bool, check_robots: bool = True) -> str | None:
        if check_robots and not self.allowed(url):
            self.skipped_robots += 1
            return None
        path = self._cache_path(url)
        if cache and path.exists() and (
                self.offline or time.time() - path.stat().st_mtime < self.max_age):
            return path.read_text(encoding="utf-8", errors="replace")
        if self.offline:
            return None
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(8_000_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code in (403, 429):
                raise Blocked(f"{self.brand}: HTTP {error.code} on {url}") from error
            if error.code in (404, 410):
                return None
            raise
        if cache:
            path.write_text(body, encoding="utf-8")
        return body

    def get(self, url: str) -> str | None:
        """Page text (cached), or None when robots disallow / the page is gone."""
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc and parsed.netloc != urllib.parse.urlparse(self.base_url).netloc:
            raise ValueError(f"{url} is outside {self.base_url}")
        return self._fetch(url, cache=True)
