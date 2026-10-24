"""
extract/client.py - one Claude request per (product text, field list), cached.

Structured output (a JSON schema whose `field` enum is exactly the fields
asked), low effort, no tools. Every answer, refusals included, is cached under
data/extract/.cache/ keyed by model + prompt version + text + fields, so a page
is paid for once and a re-run is free. Needs ANTHROPIC_API_KEY; the model is
MIFRAT_EXTRACT_MODEL (default Claude Haiku 5.5: high volume, short answers).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ..specs import schema

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "extract" / ".cache"
DEFAULT_MODEL = "claude-haiku-5-5"
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DELAY = 7.0            # free tier: ~10 requests a minute
PROMPT_VERSION = 1

SYSTEM = """You read computer-part listings from retailers (English and Hebrew) \
and report the specifications the text states.

Rules:
- Report a field only when the listing text states it. Never answer from the \
product name's general reputation, from model-number conventions, or from what \
you know about the product: those facts are filled elsewhere, and a guess here \
is worse than nothing.
- For each fact, `quote` is the shortest exact span of the listing that states \
it, copied character for character in its original language. It is checked \
against the text; a paraphrased or translated quote is discarded.
- `value` is the value in the field's unit (numbers without the unit) or one \
of its allowed values when the field lists them. Yes/No fields take "Yes" or "No".
- Leave out every field the text does not state. An empty list is a fine answer."""


def _load_dotenv() -> None:
    """KEY=VALUE lines of the repo's .env (gitignored) fill env vars that are not
    already set. Plain parsing, no dependency; a missing file is fine."""
    try:
        lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if name and value:
            os.environ.setdefault(name, value)


_load_dotenv()


class NoKey(RuntimeError):
    """No ANTHROPIC_API_KEY: the runner reports and stops, it never guesses."""


MAX_QUOTA_WAIT = 90.0         # seconds a per-minute 429 is waited out instead of stopping


class RateLimited(RuntimeError):
    """The free tier said 429 / still overloaded: stop, the cache keeps what was
    answered. `daily` = a per-day quota: nothing more today."""

    def __init__(self, message, daily: bool = False):
        super().__init__(message)
        self.daily = daily


def quota_info(body: str) -> tuple[float | None, bool, str]:
    """(retry delay in seconds, per-day quota?, readable detail) from a 429 body."""
    import json
    import re

    try:
        error = json.loads(body).get("error") or {}
    except ValueError:
        error = {}
    delay, ids = None, []
    for detail in error.get("details") or []:
        raw = detail.get("retryDelay")
        if raw and re.fullmatch(r"[\d.]+s", str(raw)):
            delay = float(str(raw)[:-1])
        for violation in detail.get("violations") or []:
            ids.append(str(violation.get("quotaId") or violation.get("quotaMetric") or ""))
    daily = any(re.search(r"PerDay", quota, re.I) for quota in ids)
    text = f"HTTP 429 quota={','.join(i for i in ids if i) or '?'} retryDelay={delay}"
    return delay, daily, text


def backend() -> str:
    return (os.environ.get("MIFRAT_EXTRACT_BACKEND") or "anthropic").lower()


def model_name() -> str:
    return os.environ.get("MIFRAT_EXTRACT_MODEL") or (
        GEMINI_MODEL if backend() == "gemini" else DEFAULT_MODEL)


def _field_lines(category: str, fields: list[str]) -> str:
    specs = schema.field_map(category)
    lines = []
    for name in fields:
        spec = specs[name]
        kind = "Yes/No" if spec.type == "bool" else (
            "list" if spec.type == "list_str" else spec.type)
        parts = [f"- {name} ({spec.label_en or name}; {kind}"
                 + (f", unit {spec.unit}" if spec.unit else "") + ")"]
        if spec.enum:
            parts.append(f" allowed: {', '.join(spec.enum)}")
        lines.append("".join(parts))
    return "\n".join(lines)


def output_schema(fields: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"facts": {"type": "array", "items": {
            "type": "object",
            "properties": {"field": {"type": "string", "enum": list(fields)},
                           "value": {"type": "string"},
                           "quote": {"type": "string"}},
            "required": ["field", "value", "quote"],
            "additionalProperties": False}}},
        "required": ["facts"],
        "additionalProperties": False,
    }


def prompt(category: str, fields: list[str], text: str) -> str:
    return (f"Category: {category}\n\nFields:\n{_field_lines(category, fields)}\n\n"
            f"<listing>\n{text}\n</listing>")


class Extractor:
    def __init__(self, *, offline: bool = False):
        self.model = model_name()
        self.offline = offline
        self.requests = 0
        self.cached = 0
        self.refused = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._client = None

    def _cache_path(self, category: str, fields: list[str], text: str) -> Path:
        key = json.dumps([self.model, PROMPT_VERSION, category, sorted(fields), text],
                         ensure_ascii=False)
        return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def _gemini(self, category: str, fields: list[str], text: str):
        """One generateContent call, returned in the shape facts() reads."""
        import time
        from types import SimpleNamespace

        import requests

        key = os.environ.get("GOOGLE_KEY")
        if not key:
            raise NoKey("GOOGLE_KEY is not set")
        wait = GEMINI_DELAY - (time.time() - getattr(self, "_last", 0.0))
        if wait > 0:
            time.sleep(wait)
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt(category, fields, text)}]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseJsonSchema": output_schema(fields),
                                 "maxOutputTokens": 4000, "temperature": 0},
        }
        for attempt in range(5):
            reply = requests.post(GEMINI_URL.format(model=self.model), json=body, timeout=120,
                                  headers={"x-goog-api-key": key})
            if reply.status_code in (500, 503):          # "high demand": back off, retry
                if attempt < 3:
                    time.sleep(10 * 2 ** attempt)
                    continue
            elif reply.status_code == 429:
                delay, daily, detail = quota_info(reply.text)
                if daily or delay is None or delay > MAX_QUOTA_WAIT or attempt >= 3:
                    self._last = time.time()
                    raise RateLimited(detail, daily=daily)
                time.sleep(delay + 1)                    # a per-minute quota: wait it out
                continue
            break
        self._last = time.time()
        if reply.status_code in (500, 503):
            raise RateLimited(f"HTTP {reply.status_code}: still overloaded after retries")
        reply.raise_for_status()
        data = reply.json()
        candidate = (data.get("candidates") or [{}])[0]
        reason = candidate.get("finishReason", "")
        parts = (candidate.get("content") or {}).get("parts") or []
        usage = data.get("usageMetadata") or {}
        stop = ("end_turn" if reason == "STOP" else
                "max_tokens" if reason == "MAX_TOKENS" else "refusal")
        return SimpleNamespace(
            stop_reason=stop,
            content=[SimpleNamespace(type="text", text="".join(p.get("text", "") for p in parts))],
            usage=SimpleNamespace(input_tokens=usage.get("promptTokenCount", 0),
                                  output_tokens=usage.get("candidatesTokenCount", 0)))

    def _api(self):
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise NoKey("ANTHROPIC_API_KEY is not set")
            import anthropic

            self._client = anthropic.Anthropic(max_retries=4)
        return self._client

    def facts(self, category: str, fields: list[str], text: str) -> list[dict] | None:
        """[{field, value, quote}] as the model claimed them (unverified), or
        None when nothing usable came back (offline miss, refusal, cut off)."""
        path = self._cache_path(category, fields, text)
        if path.exists():
            self.cached += 1
            return json.loads(path.read_text(encoding="utf-8")).get("facts")
        if self.offline:
            return None
        response = self._create(category, fields, text)
        self.requests += 1
        usage = getattr(response, "usage", None)
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        facts = None
        if response.stop_reason == "refusal":
            self.refused += 1
        elif response.stop_reason != "max_tokens":
            body = next((block.text for block in response.content if block.type == "text"), "")
            try:
                facts = json.loads(body).get("facts")
            except (ValueError, AttributeError):
                facts = None
        if response.stop_reason in ("refusal", "end_turn"):
            # Cache refusals too: the same text would be refused again.
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.model, "stop": response.stop_reason,
                                        "facts": facts}, ensure_ascii=False), encoding="utf-8")
        return facts

    def _create(self, category: str, fields: list[str], text: str):
        if backend() == "gemini":
            return self._gemini(category, fields, text)
        request = dict(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt(category, fields, text)}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": output_schema(fields)}},
        )
        client = self._api()
        if self.model.startswith("claude-opus-5"):
            # Opus declines on its classifiers re-run on the recommended model.
            return client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
        return client.messages.create(**request)
