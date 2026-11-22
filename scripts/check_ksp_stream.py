"""Offline KSP storefront component-stream reader regression.

Saved product-only capture from the owner Chromium; no tokens/cookies or
vendor requests. Malformed input errors must never echo response content.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.ksp_stream import (CATEGORY_COMPONENT, PRICE_COMPONENT, MAX_STREAM_BYTES, MAX_ENVELOPE_DEPTH,
                               StreamError, category_payload, parse_stream, prices_payload, unwrap)
from scraper.spiders.ksp import KspSpider

FIXTURE = ROOT / "scraper/fixtures/ksp/cpu_stream.json"


def stream(*events):
    return "".join(f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                   for event, payload in events)


def main():
    if not FIXTURE.exists():
        print("[ksp-stream] FAIL: saved stream fixture is missing")
        return 1
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    failures = []
    assertions = 0

    def equal(name, got, want):
        nonlocal assertions
        assertions += 1
        if got != want:
            failures.append(f"{name}: got {got!r}, want {want!r}")

    def refuses(name, body, keys=None):
        nonlocal assertions
        assertions += 1
        try:
            parse_stream(body, keys or [CATEGORY_COMPONENT])
            failures.append(name + ": accepted an invalid stream")
        except StreamError as error:
            if "SECRET_FIXTURE" in str(error):
                failures.append(name + ": response content leaked into error")

    listing, prices, done = fixture["listing"], fixture["prices"], fixture["done"]
    body = stream(("partial", listing), ("done", done))
    data = category_payload(body)
    equal("reported category total", data["products_total"], 45)
    equal("first visible page only", len(data["items"]), 12)
    equal("follows response page", data["next"], 2)
    equal("uin differs from printed SKU", (data["items"][0]["uin"], data["items"][0]["uinsql"]), (505073, "445612"))
    spider = KspSpider()
    rows = [dict(spider._map_item(item, "cpu")) for item in data["items"]]
    equal("real listing mapper reused", len(rows), 12)
    equal("identity stays uin", rows[0]["vendor_sku"], "505073")
    equal("price from feed", rows[0]["price_ils"], 349)
    equal("stock from feed", rows[0]["in_stock"], True)
    equal("tags preserved", rows[0]["vendor_meta"]["tags"]["תושבת"], "AM4")
    uins = [str(item["uin"]) for item in data["items"]]
    bms = prices_payload(stream(("partial", prices), ("done", done)), uins)
    equal("all requested prices", len(bms), 12)
    equal("real Eilat price", bms["505073"]["eilat_price"], 296)
    equal("CRLF and UTF-8 BOM", category_payload("\ufeff" + body.replace("\n", "\r\n")), data)
    equal("EOF without final blank", category_payload(body.rstrip()), data)
    equal("comment heartbeat", category_payload(": keepalive\n\n" + body), data)
    equal("nested data/result envelope", unwrap({"data": {"result": {"x": 1}}, "seo": {"title": "x"}}), {"x": 1, "seo": {"title": "x"}})
    equal("terminal list", unwrap({"result": [1, 2], "seo": {}}), [1, 2])
    equal("outer envelope siblings are not unwrapped twice",
          unwrap({"result": {"x": 1}, "data": {"y": 2}}),
          {"x": 1, "data": {"y": 2}})
    equal("multiline data", category_payload(body.replace('data: {"requestId":', 'data: {\ndata: "requestId":', 1)), data)
    # U+2028 inside a JSON string is not an SSE newline. Hebrew vendor prose
    # can carry Unicode separators; splitlines() would corrupt the event.
    unicode_row = deepcopy(listing)
    unicode_row["data"]["result"]["items"][0]["name"] += "\u2028fixture"
    try:
        parsed = category_payload(stream(("partial", unicode_row), ("done", done)))
        equal("Unicode line separator stays in value", parsed["items"][0]["name"], unicode_row["data"]["result"]["items"][0]["name"])
    except StreamError:
        failures.append("Unicode line separator incorrectly split the SSE event")
    refuses("missing done", stream(("partial", listing)))
    refuses("missing component", stream(("done", done)))
    refuses("failed batch", stream(("partial", listing), ("done", {"status": "failed", "message": "SECRET_FIXTURE"})))
    refuses("duplicate component", stream(("partial", listing), ("partial", listing), ("done", done)))
    refuses("duplicate done", body + stream(("done", done)))
    refuses("late partial", body + stream(("partial", listing)))
    refuses("unknown component", stream(("partial", {**listing, "key": "cat.popularItems"}), ("done", done)))
    refuses("wrong request id", stream(("partial", {**listing, "requestId": "r2"}), ("done", done)))
    refuses("component failed", stream(("partial", {**listing, "ok": False, "error": "SECRET_FIXTURE"}), ("done", done)))
    refuses("non-JSON", "event: partial\ndata: SECRET_FIXTURE\n\nevent: done\ndata: {}\n\n")
    refuses("invalid UTF-8", b"\xff")
    refuses("oversized", b"x" * (MAX_STREAM_BYTES + 1))
    refuses("API error", stream(("partial", {**listing, "data": {"statusCode": 403, "message": "SECRET_FIXTURE"}}), ("done", done)))
    deep = {"items": []}
    for _ in range(MAX_ENVELOPE_DEPTH + 1):
        deep = {"result": deep}
    refuses("envelope depth cap", stream(("partial", {**listing, "data": deep}), ("done", done)))
    for changed, name in (({**data, "products_total": 0}, "zero total"),
                          ({**data, "next": "next"}, "invalid next"),
                          ({**data, "items": [{"uin": "abc"}]}, "invalid uin")):
        try:
            category_payload(stream(("partial", {**listing, "data": changed}), ("done", done)))
            failures.append(name + " accepted")
        except StreamError:
            assertions += 1
    # Out-of-order arrival is valid when BOTH ids and keys match the request.
    second = {**prices, "requestId": "r2"}
    result = parse_stream(stream(("partial", second), ("partial", listing), ("done", done)), [CATEGORY_COMPONENT, PRICE_COMPONENT])
    equal("out-of-order response follows request order", [c.key for c in result], [CATEGORY_COMPONENT, PRICE_COMPONENT])
    try:
        prices_payload(stream(("partial", prices), ("done", done)), uins + ["999"])
        failures.append("missing price row accepted")
    except StreamError:
        assertions += 1
    wrong = deepcopy(prices)
    wrong["data"]["result"][uins[0]]["uin"] = 1
    try:
        prices_payload(stream(("partial", wrong), ("done", done)), uins)
        failures.append("mismatched price identity accepted")
    except StreamError:
        assertions += 1
    # A live Nov22 response was HTTP200/completed but its unwrapped price
    # payload was a string, not a price map. Completion never excuses that.
    for invalid in ("SECRET_FIXTURE", None, [], {}):
        bad_prices = {**prices, "data": {"result": invalid}}
        try:
            prices_payload(stream(("partial", bad_prices), ("done", done)), uins)
            failures.append("non-map/empty price batch accepted")
        except StreamError as error:
            assertions += 1
            if "SECRET_FIXTURE" in str(error):
                failures.append("price-batch response content leaked into error")
    # This capture is data only. No opaque request credentials entered git.
    def private_fields(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in {"tt", "cookie", "persistent", "authorization", "token", "session"}:
                    return True
                if private_fields(child):
                    return True
        if isinstance(value, list):
            return any(private_fields(child) for child in value)
        return False
    equal("fixture has no credential fields", private_fields(fixture), False)
    if failures:
        for failure in failures:
            print("[ksp-stream] FAIL", failure)
        return 1
    print(f"[ksp-stream] pass - {assertions} assertions, saved 12-row capture, no vendor requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
