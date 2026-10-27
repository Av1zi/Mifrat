"""
extract/client.py - one Claude request per (product text, field list), cached.

Structured output (a JSON schema whose `field` enum is exactly the fields
asked), low effort, no tools. Every answer, refusals included, is cached under
data/extract/.cache/ keyed by model + prompt version + text + fields, so a page
is paid for once and a re-run is free.

Providers (MIFRAT_EXTRACT_BACKEND, a comma list tried in order; keys in .env):
  anthropic  ANTHROPIC_API_KEY             default model Claude Haiku 5.5
  gemini     GOOGLE_KEY                    default model gemini-3.5-flash
  groq       GROQ_KEY                      OpenAI-compatible; model default below
  intern     INTERN_KEY + INTERN_BASE_URL  OpenAI-compatible; model required
The model of a provider is MIFRAT_EXTRACT_MODEL_<NAME> (or MIFRAT_EXTRACT_MODEL
when only one provider is configured). A provider that reports a per-day quota,
or stays overloaded, is skipped for the rest of the run and the next one answers.
Every model is audited on its own (runner.py): a field is used from a model only
if that model's audit passed it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from ..specs import schema

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "extract" / ".cache"
DEFAULT_MODEL = "claude-haiku-5-5"
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DELAY = 7.0            # free tier: ~10 requests a minute
OPENAI_STYLE: dict[str, dict[str, Any]] = {
    # name: base URL (or the env var holding it), key env var, default model, seconds between requests
    "groq": {"base": "https://api.groq.com/openai/v1", "key": "GROQ_KEY",
             "model": "openai/gpt-oss-20b", "delay": 2.5,
             "extra": {"reasoning_effort": "low"}},        # gpt-oss: little thinking, short answers
    # Intern-S2 ignores json_schema and answers a flat {"field": value} object (Oct 2026):
    # plain JSON mode, with the exact shape spelled out in the prompt.
    "intern": {"base_env": "INTERN_BASE_URL", "key": "INTERN_KEY", "model": None, "delay": 3.0,
               "json_object": True},
}
# Per-request timeout: reasoning models (Intern-S2) can think for minutes.
# MIFRAT_EXTRACT_TIMEOUT overrides it (seconds).
REQUEST_TIMEOUT = 120.0
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


def openai_quota_info(reply) -> tuple[float | None, bool, str]:
    """Same triple for an OpenAI-style 429: Retry-After header, or the 'try again
    in 2m30s' sentence; 'per day' / TPD / RPD in the message = a daily quota."""
    import re

    text = reply.text or ""
    daily = bool(re.search(r"per day|\b(?:TPD|RPD)\b|daily", text, re.I))
    delay = None
    header = (getattr(reply, "headers", None) or {}).get("retry-after")
    if header and re.fullmatch(r"[\d.]+", str(header).strip()):
        delay = float(header)
    else:
        match = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?", text)
        if match and (match.group(1) or match.group(2)):
            delay = float(match.group(1) or 0) * 60 + float(match.group(2) or 0)
    return delay, daily, f"HTTP 429 daily={daily} retryAfter={delay}"


def parse_facts(body: str) -> list | None:
    """The `facts` list from a model's text: plain JSON, or JSON inside a code
    fence / after some prose. None when no JSON object with a list is there."""
    import re

    candidates = [body or ""]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", body or "", re.S)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = (body or "").find("{"), (body or "").rfind("}")
    if 0 <= start < end:
        candidates.append(body[start:end + 1])
    for text in candidates:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("facts"), list):
            return data["facts"]
        if isinstance(data, list):
            return data
    return None


def backends() -> list[str]:
    names = [n.strip().lower() for n in (os.environ.get("MIFRAT_EXTRACT_BACKEND")
                                         or "anthropic").split(",") if n.strip()]
    return [n for n in dict.fromkeys(names)] or ["anthropic"]


def model_for(name: str, only: bool) -> str | None:
    """The model a provider uses: MIFRAT_EXTRACT_MODEL_<NAME>, then (single
    provider only) MIFRAT_EXTRACT_MODEL, then the provider's default."""
    explicit = os.environ.get(f"MIFRAT_EXTRACT_MODEL_{name.upper()}")
    if explicit:
        return explicit
    if only and os.environ.get("MIFRAT_EXTRACT_MODEL"):
        return os.environ["MIFRAT_EXTRACT_MODEL"]
    if name == "anthropic":
        return DEFAULT_MODEL
    if name == "gemini":
        return GEMINI_MODEL
    return (OPENAI_STYLE.get(name) or {}).get("model")


def provider_models() -> list[tuple[str, str | None]]:
    names = backends()
    return [(name, model_for(name, len(names) == 1)) for name in names]


def model_name() -> str:
    """The first provider's model (the one a single-backend run reports)."""
    return provider_models()[0][1] or "?"


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
        self.providers = provider_models()
        self.model = self.providers[0][1] or "?"
        self.last_model = self.model
        self.offline = offline
        self.requests = 0
        self.cached = 0
        self.refused = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.samples = 0                         # raw empty answers shown so far
        self.exhausted: dict[str, str] = {}      # provider -> why it was skipped
        self._client = None
        self._last: dict[str, float] = {}
        self._json_object: set[str] = set()      # providers that refused json_schema

    def _cache_path(self, model: str, category: str, fields: list[str], text: str) -> Path:
        key = json.dumps([model, PROMPT_VERSION, category, sorted(fields), text],
                         ensure_ascii=False)
        return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")

    def _pace(self, name: str, delay: float) -> None:
        import time

        wait = delay - (time.time() - self._last.get(name, 0.0))
        if wait > 0:
            time.sleep(wait)

    def _post(self, name: str, url: str, headers: dict, body: dict, delay: float,
              retry_after: Callable[[requests.Response], tuple[float | None, bool, str]]):
        """POST with the shared 5xx / 429 policy; RateLimited when the provider
        should be skipped. `retry_after(reply)` -> (seconds|None, daily, detail)."""
        import time

        self._pace(name, delay)
        reply: requests.Response | None = None
        timeout = float(os.environ.get("MIFRAT_EXTRACT_TIMEOUT") or REQUEST_TIMEOUT)
        failures = 0
        for attempt in range(5):
            try:
                reply = requests.post(url, json=body, timeout=timeout, headers=headers)
            except requests.RequestException as error:      # timeout, reset, DNS: not fatal
                failures += 1
                self._last[name] = time.time()
                if failures >= 2:
                    raise RateLimited(f"{name}: {type(error).__name__} twice in a row "
                                      f"(timeout {timeout:.0f}s; a reasoning model may need "
                                      "MIFRAT_EXTRACT_TIMEOUT or a no-thinking option)") from error
                continue
            if reply.status_code in (500, 502, 503):     # "high demand": back off, retry
                if attempt < 3:
                    time.sleep(10 * 2 ** attempt)
                    continue
            elif reply.status_code == 429:
                wait, daily, detail = retry_after(reply)
                if daily or wait is None or wait > MAX_QUOTA_WAIT or attempt >= 3:
                    self._last[name] = time.time()
                    raise RateLimited(f"{name}: {detail}", daily=daily)
                time.sleep(wait + 1)                     # a per-minute quota: wait it out
                continue
            break
        if reply is None:                       # every attempt raised before a response
            raise RateLimited(f"{name}: no response after {failures} network failure(s)")
        self._last[name] = time.time()
        if reply.status_code in (500, 502, 503):
            raise RateLimited(f"{name}: HTTP {reply.status_code}, still overloaded after retries")
        return reply

    def _gemini(self, model: str, category: str, fields: list[str], text: str):
        """One generateContent call, returned in the shape facts() reads."""
        from types import SimpleNamespace

        key = os.environ.get("GOOGLE_KEY")
        if not key:
            raise NoKey("GOOGLE_KEY is not set")
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt(category, fields, text)}]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseJsonSchema": output_schema(fields),
                                 "maxOutputTokens": 4000, "temperature": 0},
        }
        reply = self._post("gemini", GEMINI_URL.format(model=model),
                           {"x-goog-api-key": key}, body, GEMINI_DELAY,
                           lambda r: quota_info(r.text))
        if reply.status_code in (401, 403):
            raise NoKey(f"gemini: the key was rejected (HTTP {reply.status_code}); check GOOGLE_KEY")
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

    def _openai(self, name: str, model: str, category: str, fields: list[str], text: str):
        """One OpenAI-style /chat/completions call (Groq, Intern, ...)."""
        from types import SimpleNamespace

        config = OPENAI_STYLE[name]
        base = config.get("base") or os.environ.get(config.get("base_env", ""), "")
        key = os.environ.get(config["key"])
        if not key or not base:
            raise NoKey(f"{config['key']} / base URL is not set for {name}")
        if not model:
            raise NoKey(f"MIFRAT_EXTRACT_MODEL_{name.upper()} is not set")
        schema_ = output_schema(fields)
        user = prompt(category, fields, text)
        if name in self._json_object or config.get("json_object"):
            user += ("\n\nAnswer with ONE JSON object of exactly this shape, and nothing else:\n"
                     '{"facts": [{"field": "<field name from the list>", "value": "<value>", '
                     '"quote": "<exact words copied from the listing>"}]}\n'
                     'Every fact needs its "quote". If the listing states none of the fields, '
                     'answer {"facts": []}.\nJSON schema:\n' + json.dumps(schema_))
            response_format = {"type": "json_object"}
        else:
            response_format = {"type": "json_schema", "json_schema": {
                "name": "facts", "schema": schema_, "strict": False}}
        extra = dict(config.get("extra") or {})
        override = os.environ.get(f"MIFRAT_EXTRACT_EXTRA_{name.upper()}")
        if override:                                     # JSON object of extra request fields
            try:
                extra = json.loads(override)
            except ValueError:
                raise NoKey(f"MIFRAT_EXTRACT_EXTRA_{name.upper()} is not valid JSON") from None
        body = {**extra, "model": model, "temperature": 0, "max_tokens": 4000,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": user}],
                "response_format": response_format}
        reply = self._post(name, base.rstrip("/") + "/chat/completions",
                           {"Authorization": f"Bearer {key}"}, body, config["delay"],
                           openai_quota_info)
        if reply.status_code == 400 and name not in self._json_object and \
                "response_format" in reply.text:
            self._json_object.add(name)                  # no json_schema here: plain JSON mode
            return self._openai(name, model, category, fields, text)
        if reply.status_code in (400, 404) and "model" in reply.text.lower():
            raise NoKey(f"{name}: the model {model!r} was not accepted "
                        f"(set MIFRAT_EXTRACT_MODEL_{name.upper()}): {reply.text[:160]}")
        if reply.status_code in (401, 403):
            raise NoKey(f"{name}: the key was rejected (HTTP {reply.status_code}); "
                        f"check {config['key']} in .env")
        reply.raise_for_status()
        data = reply.json()
        choice = (data.get("choices") or [{}])[0]
        reason = choice.get("finish_reason", "")
        usage = data.get("usage") or {}
        stop = ("end_turn" if reason == "stop" else
                "max_tokens" if reason == "length" else "refusal")
        content = (choice.get("message") or {}).get("content") or ""
        return SimpleNamespace(
            stop_reason=stop,
            content=[SimpleNamespace(type="text", text=content)],
            usage=SimpleNamespace(input_tokens=usage.get("prompt_tokens", 0),
                                  output_tokens=usage.get("completion_tokens", 0)))

    def _api(self):
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise NoKey("ANTHROPIC_API_KEY is not set")
            import anthropic  # type: ignore[import-not-found]  # optional provider

            self._client = anthropic.Anthropic(max_retries=4)
        return self._client

    def _anthropic(self, model: str, category: str, fields: list[str], text: str):
        request = dict(
            model=model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt(category, fields, text)}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": output_schema(fields)}},
        )
        client = self._api()
        if model.startswith("claude-opus-5"):
            # Opus declines on its classifiers re-run on the recommended model.
            return client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
        return client.messages.create(**request)

    def facts(self, category: str, fields: list[str], text: str) -> list[dict] | None:
        """[{field, value, quote}] as the model claimed them (unverified), or
        None when nothing usable came back (offline miss, refusal, cut off).
        `self.last_model` names the model that answered."""
        for _, model in self.providers:
            path = self._cache_path(model or "?", category, fields, text)
            if path.exists():
                self.cached += 1
                self.last_model = model or "?"
                return json.loads(path.read_text(encoding="utf-8")).get("facts")
        if self.offline:
            return None
        response = self._create(category, fields, text)
        model = getattr(response, "model_used", None) or self.model
        self.last_model = model
        path = self._cache_path(model, category, fields, text)
        self.requests += 1
        usage = getattr(response, "usage", None)
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        facts = None
        if response.stop_reason == "refusal":
            self.refused += 1
        elif response.stop_reason != "max_tokens":
            body = next((block.text for block in response.content if block.type == "text"), "")
            facts = parse_facts(body)
            if not facts and self.samples < 3:          # show what a silent model really said
                self.samples += 1
                self._say(f"{model} returned no facts; raw answer: {body[:300]!r}")
        if response.stop_reason == "refusal" or (response.stop_reason == "end_turn"
                                                 and facts is not None):
            # Cache refusals and parsed answers (an empty list included); an answer we
            # could not parse is not cached, so a parser fix retries it.
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": model, "stop": response.stop_reason,
                                        "facts": facts}, ensure_ascii=False), encoding="utf-8")
        return facts

    @staticmethod
    def _say(message: str) -> None:
        import sys

        print(f"[extract] {message}", file=sys.stderr, flush=True)

    def _create(self, category: str, fields: list[str], text: str):
        """Ask the providers in order; skip one that is rate limited for the
        rest of the run (or has no key), raise when none is left."""
        problems: list[str] = []
        daily = True
        for name, model in self.providers:
            if name in self.exhausted:
                problems.append(self.exhausted[name])
                continue
            try:
                if name == "anthropic":
                    response = self._anthropic(model or DEFAULT_MODEL, category, fields, text)
                elif name == "gemini":
                    response = self._gemini(model or GEMINI_MODEL, category, fields, text)
                elif name in OPENAI_STYLE:
                    response = self._openai(name, model or "", category, fields, text)
                else:
                    raise NoKey(f"unknown provider {name!r}")
            except RateLimited as error:
                self.exhausted[name] = str(error)
                self._say(f"skipping {name} for this run: {error}")
                problems.append(str(error))
                daily = daily and error.daily
                continue
            except NoKey as error:
                self.exhausted[name] = str(error)
                self._say(f"skipping {name} for this run: {error}")
                problems.append(str(error))
                continue
            response.model_used = model
            return response
        if problems and all("is not set" in p or "not accepted" in p or "unknown provider" in p
                            or "was rejected" in p for p in problems):
            raise NoKey("; ".join(problems))
        raise RateLimited("; ".join(problems), daily=daily)
