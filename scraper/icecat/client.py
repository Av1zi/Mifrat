"""
icecat/client.py - polite client for the Open Icecat JSON API.

One request per second, every answer cached on disk (data/icecat/.cache,
gitignored) so re-parsing never re-asks. Icecat answers a product that exists
only in its paid catalog with HTTP 403 and a JSON body (StatusCode 9); that is
"not open", not a block. A 429, or a 403 without that JSON, is a stop signal.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "icecat" / ".cache"
API = "https://live.icecat.biz/api"
PUBLIC_USER = "openIcecat-live"

# Icecat StatusCode values in an error body (live API documentation).
NOT_FOUND = "not_found"       # 1 / 4: no such product (or not under this brand)
NOT_OPEN = "not_open"         # 9: exists, but only in Full (paid) Icecat


class Blocked(RuntimeError):
    """429 / a non-API 403: stop the run, do not retry."""


class IcecatClient:
    def __init__(self, *, delay: float = 1.0, offline: bool = False,
                 timeout: float = 30.0) -> None:
        self.username = os.environ.get("ICECAT_USERNAME") or PUBLIC_USER
        self.delay = max(delay, 1.0)
        self.offline = offline
        self.timeout = timeout
        self.requests = 0
        self._last = 0.0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, params: dict) -> Path:
        key = json.dumps(params, sort_keys=True)
        return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def lookup(self, *, brand: str | None = None, code: str | None = None,
               gtin: str | None = None) -> tuple[str, dict | None]:
        """('ok', data) | ('not_found' | 'not_open', None). Cached forever: a
        product sheet changes rarely, and --refresh is a cache delete."""
        params = {"Language": "en"}
        if gtin:
            params["GTIN"] = gtin
        else:
            params["Brand"], params["ProductCode"] = brand or "", code or ""
        path = self._cache_path(params)
        if path.exists():
            return self._decode(json.loads(path.read_text(encoding="utf-8")))
        if self.offline:
            return NOT_FOUND, None
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        query = urllib.parse.urlencode({"UserName": self.username, **params})
        request = urllib.request.Request(f"{API}?{query}",
                                         headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise Blocked(f"icecat: HTTP 429 on {params}") from error
            try:
                body = json.loads(error.read().decode("utf-8", "replace"))
            except ValueError:
                body = None
            if not isinstance(body, dict) or "StatusCode" not in body:
                if error.code == 403:
                    raise Blocked(f"icecat: HTTP 403 without an API answer on {params}") from error
                raise
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return self._decode(body)

    @staticmethod
    def _decode(body: dict) -> tuple[str, dict | None]:
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            return "ok", body["data"]
        status = (body or {}).get("StatusCode") if isinstance(body, dict) else None
        return (NOT_OPEN if status == 9 else NOT_FOUND), None
