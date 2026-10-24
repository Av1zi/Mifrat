#!/usr/bin/env python
"""
check_extract.py - offline checks for scraper/extract (no API key, no network).

The verifier is the whole safety argument for AI extraction, so its accept /
reject cases are pinned here: invented quotes, misread numbers, paraphrases and
identity fields must all be dropped. The client is driven with a fake API
response to pin the refusal / cut-off / cache handling.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.extract import client as client_module  # noqa: E402
from scraper.extract.verify import product_text, verified  # noqa: E402
from scraper.specs.merge import TIER_EXTRACTED, TIER_NAMES, TIER_TITLE, TIER_VENDOR  # noqa: E402

failures = 0


def check(label: str, got, want) -> None:
    global failures
    if got != want:
        failures += 1
        print(f"FAIL {label}: got {got!r}, want {want!r}")


LISTINGS = [{
    "title_raw": "Lian Li Galahad II Trinity 360 ARGB White",
    "vendor_meta": {
        "description": "Pump speed up to 3100 RPM. ‏מאווררים: 3 x 120mm. "
                       "The radiator is 27mm thick and the kit has no LCD screen.",
        "detail_specs": {"Warranty": "6 years", "Fan noise": "8.5 - 32.6 dBA",
                         "Socket": ["AM5", "LGA1700"]},
    },
}]
TEXT = product_text(LISTINGS)

# Accepted: the quote is in the text and carries the value.
check("fan rpm", verified("aio", "fan_rpm_max", "3100", "up to 3100 RPM", TEXT), 3100)
check("fan count via Hebrew row",
      verified("aio", "fan_count", "3", "מאווררים: 3 x 120mm", TEXT), 3)
check("quote case/space-insensitive",
      verified("aio", "fan_rpm_max", "3100", "pump  SPEED up to 3100 rpm", TEXT), 3100)
check("radiator thickness", verified("aio", "radiator_thickness_mm", "27",
                                     "radiator is 27mm thick", TEXT), 27)

# Rejected.
check("invented quote", verified("aio", "fan_rpm_max", "2800", "pump at 2800 RPM", TEXT), None)
check("quote does not carry the number",
      verified("aio", "fan_rpm_max", "2800", "up to 3100 RPM", TEXT), None)
check("identity field never extracted",
      verified("aio", "model", "Galahad II Trinity", "Galahad II Trinity", TEXT), None)
check("one-character quote", verified("aio", "fan_count", "3", "3", TEXT), None)
check("value outside the field's range",
      verified("aio", "fan_rpm_max", "310000", "up to 3100 RPM", TEXT), None)
check("unknown field", verified("aio", "no_such_field", "1", "up to 3100 RPM", TEXT), None)
check("bool from a quote that says nothing yes/no",
      verified("case_fan", "pwm", "Yes", "Lian Li Galahad", TEXT), None)
check("bool from a quote that says it",
      verified("case_fan", "pwm", "Yes", "PWM: Yes", "Lian Li fan\nPWM: Yes"), True)
check("list items must all be quoted",
      verified("aio", "sockets", "AM5, LGA1700, AM4", "Socket: AM5, LGA1700", TEXT), None)

# Tier placement: below a vendor table, above the title parser.
check("tier order", TIER_VENDOR < TIER_EXTRACTED < TIER_TITLE, True)
check("tier name", TIER_NAMES[TIER_EXTRACTED], "extracted")


class FakeAPI:
    def __init__(self, stop: str, body: str):
        self.calls = 0
        self.stop, self.body = stop, body

    def create(self, category, fields, text):
        self.calls += 1
        return SimpleNamespace(stop_reason=self.stop,
                               content=[SimpleNamespace(type="text", text=self.body)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


with tempfile.TemporaryDirectory() as tmp:
    client_module.CACHE_DIR = Path(tmp)
    body = json.dumps({"facts": [{"field": "pump_rpm", "value": "3100", "quote": "up to 3100 RPM"}]})
    for stop, want, cached in (("end_turn", [{"field": "pump_rpm", "value": "3100",
                                              "quote": "up to 3100 RPM"}], True),
                               ("refusal", None, True), ("max_tokens", None, False)):
        extractor = client_module.Extractor()
        fake = FakeAPI(stop, body)
        extractor._create = fake.create
        text = f"{TEXT}\n{stop}"            # a distinct cache key per case
        check(f"{stop}: facts", extractor.facts("aio", ["pump_rpm"], text), want)
        again = client_module.Extractor()
        again._create = fake.create
        again.facts("aio", ["pump_rpm"], text)
        check(f"{stop}: second run served from cache", fake.calls == 1, cached)

    schema = client_module.output_schema(["pump_rpm", "fan_count"])
    item = schema["properties"]["facts"]["items"]
    check("schema field enum is exactly the fields asked",
          item["properties"]["field"]["enum"], ["pump_rpm", "fan_count"])

# Gemini 429 bodies: a per-minute quota with a retry delay is waited out, a
# per-day quota stops the run at once.
minute_body = json.dumps({"error": {"code": 429, "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "34s"}]}})
day_body = json.dumps({"error": {"code": 429, "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
check("429 per minute", client_module.quota_info(minute_body)[:2], (34.0, False))
check("429 per day", client_module.quota_info(day_body)[1], True)
check("429 per day names its quota", "PerDay" in client_module.quota_info(day_body)[2], True)
check("429 with a body we cannot read", client_module.quota_info("not json")[:2], (None, False))

# OpenAI-style 429s (Groq / Intern): Retry-After header, "try again in" text, daily words.
class FakeReply:
    def __init__(self, text, headers=None):
        self.text, self.headers = text, headers or {}


check("openai 429 retry-after header",
      client_module.openai_quota_info(FakeReply("Rate limit reached", {"retry-after": "12"}))[:2], (12.0, False))
check("openai 429 'try again in'",
      client_module.openai_quota_info(FakeReply("Please try again in 1m30.5s. Limit (TPM)"))[:2], (90.5, False))
check("openai 429 per day",
      client_module.openai_quota_info(FakeReply("Rate limit reached ... requests per day (RPD): Limit 1000"))[1], True)

# Provider fallback: the first provider is daily-limited, the second answers.
with tempfile.TemporaryDirectory() as tmp:
    client_module.CACHE_DIR = Path(tmp)
    import os

    old_backend = os.environ.get("MIFRAT_EXTRACT_BACKEND")
    os.environ["MIFRAT_EXTRACT_BACKEND"] = "gemini,groq"
    os.environ["MIFRAT_EXTRACT_MODEL_GEMINI"] = "gem-x"
    os.environ["MIFRAT_EXTRACT_MODEL_GROQ"] = "groq-y"
    reply = SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                            content=[SimpleNamespace(type="text", text=json.dumps({"facts": [
                                {"field": "pump_rpm", "value": "1", "quote": "x1"}]}))])
    calls = []

    def limited(model, category, fields, text):
        calls.append("gemini")
        raise client_module.RateLimited("gemini: HTTP 429 daily=True", daily=True)

    def answers(name, model, category, fields, text):
        calls.append(name)
        return SimpleNamespace(**reply.__dict__)

    extractor = client_module.Extractor()
    extractor._gemini, extractor._openai = limited, answers
    got = extractor.facts("aio", ["pump_rpm"], "listing text for fallback " * 5)
    check("fallback: the second provider answered", extractor.last_model, "groq-y")
    check("fallback: the facts came back", bool(got), True)
    got = extractor.facts("aio", ["pump_rpm"], "another listing for fallback " * 5)
    check("fallback: the limited provider is not asked again", calls, ["gemini", "groq", "groq"])
    check("fallback: cache is per model and found again",
          client_module.Extractor().facts("aio", ["pump_rpm"], "listing text for fallback " * 5) is not None, True)

    both = client_module.Extractor()
    both._gemini = limited
    both._openai = lambda *a: (_ for _ in ()).throw(client_module.RateLimited("groq: daily", daily=True))
    try:
        both.facts("aio", ["pump_rpm"], "nothing is left to ask " * 5)
        check("all providers limited raises", False, True)
    except client_module.RateLimited as error:
        check("all providers daily-limited: daily=True", error.daily, True)
    for name in ("MIFRAT_EXTRACT_BACKEND", "MIFRAT_EXTRACT_MODEL_GEMINI", "MIFRAT_EXTRACT_MODEL_GROQ"):
        os.environ.pop(name, None)
    if old_backend:
        os.environ["MIFRAT_EXTRACT_BACKEND"] = old_backend

# Trust is per model: a field passed for model A is not used for model B, and the
# first file format (one model, "fields") still reads.
from scraper.extract import runner  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    runner.TRUST = Path(tmp) / "trust.json"
    good = {"overlap": 20, "agree": 20, "examples": []}
    bad = {"overlap": 20, "agree": 15, "examples": []}
    runner.TRUST.write_text(json.dumps({"prompt_version": runner.PROMPT_VERSION, "models": {
        "A": {"fields": {"memory.color": good, "case.color": bad}},
        "B": {"fields": {"memory.color": bad}}}}), encoding="utf-8")
    check("trust: A passes memory.color", ("A", "memory", "color") in runner.trusted_fields(), True)
    check("trust: B does not pass memory.color", ("B", "memory", "color") in runner.trusted_fields(), False)
    check("trust: A fails case.color", ("A", "case", "color") in runner._distrusted(), True)
    runner.TRUST.write_text(json.dumps({"model": "L", "prompt_version": runner.PROMPT_VERSION,
                                        "fields": {"memory.color": good}}), encoding="utf-8")
    check("trust: legacy single-model file", runner.trusted_fields(), {("L", "memory", "color")})

offline = client_module.Extractor(offline=True)
check("offline miss asks nothing", offline.facts("aio", ["pump_rpm"], "not cached " * 20), None)

if failures:
    print(f"[check-extract] {failures} failure(s)")
    sys.exit(1)
print("[check-extract] verifier and client behave")
