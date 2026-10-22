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


class NoKey(RuntimeError):
    """No ANTHROPIC_API_KEY: the runner reports and stops, it never guesses."""


def model_name() -> str:
    return os.environ.get("MIFRAT_EXTRACT_MODEL") or DEFAULT_MODEL


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
