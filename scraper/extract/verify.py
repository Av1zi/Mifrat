"""
extract/verify.py - what text the model reads, and when its answer is believed.

`product_text(listings)` is the only document a product's extraction sees: every
offer's title, description and detail rows. `verified()` accepts a claimed
(field, value, quote) only when

1. the quote is a verbatim piece of that text (whitespace and case aside),
2. the value coerces to the field's type through values.coerce, and
3. the quote itself carries the value: the number for a numeric field, the
   word for a text / enum / boolean field (or the quote re-parses to it).

Anything else is dropped. A model that answers from general knowledge cannot
pass 1; one that quotes the right row but misreads it cannot pass 3.
"""

from __future__ import annotations

import hashlib
import re

from ..specs import schema
from ..specs.merge import same_value
from ..specs.values import InvalidValue, coerce

# Identity fields come from the matcher and the part-number joins, never from
# a model; dict fields have no single quotable value.
NOT_EXTRACTED = frozenset({"manufacturer", "model", "part_numbers", "mpn", "ean", "series"})
_MAX_QUOTE = 300
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def normalize(text: str) -> str:
    """Whitespace collapsed, case folded, Hebrew direction marks dropped."""
    text = re.sub(r"[‎‏‪-‮⁦-⁩]", "", str(text or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def product_text(listings: list[dict]) -> str:
    """Every offer's title, description and detail rows, one line each."""
    lines: list[str] = []
    seen: set[str] = set()

    def add(line: str) -> None:
        line = re.sub(r"\s+", " ", str(line or "")).strip()
        if line and normalize(line) not in seen:
            seen.add(normalize(line))
            lines.append(line)

    for listing in listings:
        meta = listing.get("vendor_meta") or {}
        add(listing.get("title_raw"))
        if isinstance(meta.get("description"), str):
            add(meta["description"])
        detail = meta.get("detail_specs")
        if isinstance(detail, dict):
            for key, value in detail.items():
                if isinstance(value, (list, tuple)):
                    value = ", ".join(str(item) for item in value)
                add(f"{key}: {value}")
    return "\n".join(lines)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def extractable(category: str | None, field: str) -> bool:
    spec = schema.field_map(category).get(field)
    return bool(spec) and field not in NOT_EXTRACTED and spec.type != "dict_int"


def _numbers(text: str) -> list[float]:
    out = []
    for raw in _NUMBER_RE.findall(text.replace(" ", " ")):
        try:
            out.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    # "2 542 MHz" is one number in clock fields: join digit groups too.
    for raw in re.findall(r"\d{1,3}(?: \d{3})+", text):
        out.append(float(raw.replace(" ", "")))
    return out


def _carries(spec, category: str | None, typed, value, quote: str) -> bool:
    """Does the quote itself state `typed`?"""
    try:
        if same_value(coerce(spec, quote, category), typed):
            return True
    except InvalidValue:
        pass
    norm_quote = normalize(quote)
    if spec.type in ("int", "float"):
        target = float(typed)
        scales = (1.0, 1000.0, 1024.0) if spec.name.endswith("_gb") else (1.0,)
        return any(abs(number * scale - target) < 0.011
                   for number in _numbers(quote) for scale in scales)
    if spec.type == "bool":
        return False                     # only a quote that re-parses (above)
    if spec.type == "list_str":
        return all(normalize(item) in norm_quote for item in typed)
    # enum / str: the canonical word, or the raw claimed word that canon maps.
    return normalize(typed) in norm_quote or (
        len(normalize(value)) >= 2 and normalize(value) in norm_quote)


def verified(category: str | None, field: str, value, quote: str, text: str):
    """The typed value when the claim survives every check, else None."""
    if not extractable(category, field) or value is None:
        return None
    quote = str(quote or "").strip()
    if not 2 <= len(quote) <= _MAX_QUOTE or normalize(quote) not in normalize(text):
        return None
    spec = schema.field_map(category)[field]
    try:
        typed = coerce(spec, value, category)
    except InvalidValue:
        return None
    return typed if _carries(spec, category, typed, str(value), quote) else None
