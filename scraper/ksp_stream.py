"""KSP's component stream protocol, parsed without browser/session credentials.

Observed 2026-11-18 through the owner's normal category-page UI. The
storefront requests cat.categoryListing and item.bms via POST /sse/streams.
Each requested component arrives in a `partial` SSE event; `done` marks the
batch complete. Payloads retain the legacy listing shape under result/data.

This module makes no requests. A working browser capture is not evidence
that the endpoint permits a standalone Nano client. Never synthesize a tt,
copy browser cookies/clearance, or switch endpoints after a block.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

STREAM_URL = "https://ksp.co.il/m_action/sse/streams"
CATEGORY_COMPONENT = "cat.categoryListing"
PRICE_COMPONENT = "item.bms"
MAX_STREAM_BYTES = 2_000_000
MAX_EVENTS = 100
MAX_ENVELOPE_DEPTH = 8


class StreamError(ValueError):
    """Fixed messages only: never include the response body or credentials."""


class StreamBlocked(StreamError):
    """HTTP 200 may wrap a component-level 403/429 rejection."""


@dataclass(frozen=True)
class Component:
    request_id: str
    key: str
    data: object


def unwrap(payload, _depth=0):
    """Same result/data envelope semantics as the storefront's cn() reader.

    Keep outer sibling fields (SEO/next etc.) while unwrapping a dictionary.
    Terminal lists/scalars replace an envelope, like the site does. Depth is
    bounded; unknown/malformed structures are not guessed.
    """
    if _depth > MAX_ENVELOPE_DEPTH:
        raise StreamError("component envelopes exceed depth limit")
    if not isinstance(payload, dict):
        return payload
    name = "result" if "result" in payload else "data" if "data" in payload else None
    if name is None:
        return payload
    inner = unwrap(payload[name], _depth + 1)
    if not isinstance(inner, dict):
        return inner
    return {**inner, **{key: value for key, value in payload.items() if key != name}}


def parse_stream(body: bytes | str, expected_keys: list[str]) -> list[Component]:
    """A complete SSE batch -> components in request order, never partial data.

    Match BOTH requestId rN and component key; popular/suggested listings
    must never masquerade as category rows. EOF without `done: completed`,
    any failed/missing/duplicate component and an API-level error are failures.
    Accept LF/CRLF, multiline data, comment heartbeats, BOM and final EOF
    without an empty separator. UTF-8 errors and oversized streams fail.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_STREAM_BYTES:
        raise StreamError("stream exceeds byte limit")
    if not expected_keys or len(expected_keys) > MAX_EVENTS:
        raise StreamError("invalid expected component list")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise StreamError("stream is not valid UTF-8") from None

    expected = {f"r{i + 1}": key for i, key in enumerate(expected_keys)}
    found: dict[str, Component] = {}
    done = False
    event = "message"
    lines: list[str] = []
    event_count = 0

    def dispatch():
        nonlocal event, lines, done, event_count
        if not lines:
            event, lines = "message", []
            return
        event_count += 1
        if event_count > MAX_EVENTS:
            raise StreamError("too many stream events")
        if event not in ("partial", "done"):
            # Site ignores message/heartbeat events. A data-bearing unknown
            # event never contributes a component or completion verdict.
            event, lines = "message", []
            return
        try:
            data = json.loads("\n".join(lines))
        except (ValueError, TypeError):
            raise StreamError("stream event is not valid JSON") from None
        if not isinstance(data, dict):
            raise StreamError("stream event has no object")
        if done:
            raise StreamError("data event after completion")
        if event == "done":
            if data.get("status") != "completed":
                raise StreamError("stream batch did not complete successfully")
            done = True
        else:
            request_id, key = data.get("requestId"), data.get("key")
            if (not isinstance(request_id, str) or not isinstance(key, str)
                    or expected.get(request_id) != key):
                raise StreamError("unexpected component identity")
            if request_id in found:
                raise StreamError("duplicate component")
            if data.get("ok") is not True:
                error = data.get("error")
                if isinstance(error, dict) and error.get("status") in (403, 429, "403", "429"):
                    raise StreamBlocked("component access blocked")
                raise StreamError("component failed")
            if "data" not in data:
                raise StreamError("component has no data")
            payload = unwrap(data["data"])
            if isinstance(payload, dict):
                status = payload.get("statusCode", payload.get("status"))
                if status in (403, 429, "403", "429"):
                    raise StreamBlocked("component access blocked")
                if status is not None and status not in (200, "200", "ok", "success"):
                    raise StreamError("component data reports a failure")
            found[request_id] = Component(request_id, key, payload)
        event, lines = "message", []

    # SSE uses CR/LF, not Python splitlines' Unicode separators inside JSON.
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            dispatch()
        elif line.startswith(":"):
            continue
        else:
            field, separator, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event = value.strip()
            elif field == "data":
                lines.append(value if separator else "")
    dispatch()
    if not done:
        raise StreamError("stream ended before completion")
    if found.keys() != expected.keys():
        raise StreamError("stream is missing a requested component")
    return [found[request_id] for request_id in expected]


def category_payload(body: bytes | str) -> dict:
    """The existing KSP listing shape; not promotions or unrelated components."""
    data = parse_stream(body, [CATEGORY_COMPONENT])[0].data
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise StreamError("category component has no items list")
    total = data.get("products_total")
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        raise StreamError("category component has no positive total")
    next_page = data.get("next")
    if next_page is not None and next_page is not False and (
        isinstance(next_page, bool) or not isinstance(next_page, int) or next_page < 0
    ):
        raise StreamError("category component has invalid pagination")
    for row in data["items"]:
        if not isinstance(row, dict) or not str(row.get("uin") or "").isdigit():
            raise StreamError("category component has an invalid product id")
    return data


MAX_SHAPE_DEPTH = 4
SHAPE_FIELDS = frozenset({
    "result", "data", "items", "products_total", "next", "uin", "price",
    "eilat_price", "is_eilat", "status", "statusCode",
})


def _shape_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    raise StreamError("shape input is not JSON")


def shape_summary(value, depth: int = 0) -> dict:
    """Sanitized structure of a vendor payload: never its values.

    Only fixed public protocol field names, types and counts may leave this
    helper. Arbitrary dictionary keys can themselves contain credentials;
    never copy them, product ids, text or header values into diagnostics.
    """
    summary = {"type": _shape_type(value)}
    if depth >= MAX_SHAPE_DEPTH:
        return {**summary, "truncated": True}
    if isinstance(value, str):
        summary["length"] = len(value)
        if len(value) > MAX_STREAM_BYTES:
            raise StreamError("shape string exceeds byte limit")
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            summary["json"] = False
        else:
            summary["json"] = True
            summary["decoded"] = shape_summary(decoded, depth + 1)
    elif isinstance(value, list):
        summary["length"] = len(value)
        summary["items"] = [shape_summary(item, depth + 1) for item in value[:3]]
    elif isinstance(value, dict):
        numeric = [key for key in value if isinstance(key, str) and key.isascii() and key.isdigit()]
        known = sorted(key for key in value if key in SHAPE_FIELDS)
        summary.update({"key_count": len(value), "numeric_keys": len(numeric),
                        "unknown_keys": len(value) - len(numeric) - len(known),
                        "fields": {key: shape_summary(value[key], depth + 1) for key in known},
                        "numeric_values": [shape_summary(value[key], depth + 1) for key in numeric[:3]]})
    return summary


def price_stream_shape(body: bytes | str) -> dict:
    """Offline diagnostic only; JSON strings remain invalid price batches.

    No request, file write, marker change or parser acceptance is performed.
    Inspect a captured native response in memory; return sanitized shape only.
    """
    try:
        payload = parse_stream(body, [PRICE_COMPONENT])[0].data
    except RecursionError:
        raise StreamError("shape input exceeds nesting limit") from None
    return {"component": PRICE_COMPONENT, "payload": shape_summary(payload)}


def prices_payload(body: bytes | str, expected_uins: list[str]) -> dict:
    """Complete current-price batch, including items not sold in Eilat.

    Every requested uin must answer. Missing items are a failed batch, not
    evidence they are unavailable or not sold in Eilat. Keys and row ids must
    agree; never confuse KSP uin with its different printed uinsql SKU.
    """
    data = parse_stream(body, [PRICE_COMPONENT])[0].data
    if not isinstance(data, dict) or set(data) != set(expected_uins):
        raise StreamError("price batch does not cover requested product ids")
    for uin, row in data.items():
        if not isinstance(row, dict) or str(row.get("uin")) != uin:
            raise StreamError("price row identity differs from batch key")
        price = row.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise StreamError("price row has no positive regular price")
    return data
