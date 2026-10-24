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

offline = client_module.Extractor(offline=True)
check("offline miss asks nothing", offline.facts("aio", ["pump_rpm"], "not cached " * 20), None)

if failures:
    print(f"[check-extract] {failures} failure(s)")
    sys.exit(1)
print("[check-extract] verifier and client behave")
