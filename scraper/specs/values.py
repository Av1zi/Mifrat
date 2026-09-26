"""
specs/values.py — typed coercion at the resolver boundary.

Every resolver returns *typed* values (int/float/bool/str/list/dict) in the
schema's canonical unit. This module is the one place that knows how to turn
vendor text ("155 mm", "25.6 dB", "1.4V", "2 x 16GB", "yes") into those
values, and it never guesses: text with no number is invalid, not zero.

Anything that cannot be coerced to the field's declared type is DROPPED
(InvalidValue) — validators then check ranges/enums. Contract:

    coerce(field, raw) -> typed value      (raises InvalidValue)
    parse_* helpers are unit-aware flavours resolvers use directly.
"""

from __future__ import annotations

import math
import re

from .schema import FieldSpec


class InvalidValue(ValueError):
    """Raised when a raw value cannot be represented as the field's type."""


# Vendor placeholders meaning "no data" — never a spec value.
PLACEHOLDERS = frozenset({
    "", "-", "--", "---", "—", "...", "n/a", "na", "none", "null", "unknown",
    "not available", "no info", "no information", "not applicable",
    "לא ידוע", "לא זמין", "אין מידע",
})

_TRUE = frozenset({"yes", "y", "true", "1", "included", "with", "ja", "כן", "יש"})
_FALSE = frozenset({"no", "n", "false", "0", "not included", "without", "nein", "לא", "אין"})

# Strip a trailing unit token glued to a number ("155mm", "1.4V", "25.6 dB",
# "6000MT/s", "2.5\""). The number itself comes first.
_UNIT_TAIL = re.compile(
    r"(?i)\s*(mm|cm|kg|gb|tb|mb|kb|ghz|mhz|khz|hz|rpm|dba|db|volts?|v|watts?|w|"
    r"amps?|a|cfm|mmh2o|liters?|litres?|l|inch(es)?|in|ns|ms|mt/s|bps|gb/s|"
    r"dimm|slots?|pins?)\b\.?$"
)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_PURE_NUMBER = re.compile(r"\s*\d+(?:[.,]\d+)?\s*")


def is_placeholder(value) -> bool:
    """True for vendor 'no data' cells and empty values."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in PLACEHOLDERS
    return False


def strip_unit(text: str) -> str:
    """Remove trailing unit tokens and 'Label: ' prefixes from a value.

    Units are declared in the field NAME, so a unit suffix is noise here.
    """
    text = str(text).strip().replace("\u00a0", " ")
    head, sep, tail = text.partition(":")
    if sep and tail.strip():
        text = tail.strip()
    elif sep and head.strip():
        text = head.strip()
    for _ in range(3):
        stripped = _UNIT_TAIL.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text


def first_number(value) -> float | None:
    """First numeric token in `value`, or None when there is none."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    text = str(value)
    if _PURE_NUMBER.fullmatch(text):
        text = text.replace(",", ".")
    match = _NUM.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


# Storage/memory sizes arrive with the unit glued on ("2TB", "1.92TB"). The
# field name declares the unit, so strip_unit() removes the token — but the
# magnitude must be scaled FIRST, or a 2TB drive ships as 2GB (the Sep 2026
# audit found ~800 storage capacities dropped by the <16GB sanity rule for
# exactly this reason).
_TB_RE = re.compile(r"(?i)\d(?:[.,]\d+)?\s*tb\b")
_GB_FIELD_RE = re.compile(r"_gb$")
TB_IN_GB = 1000


def gb_magnitude(value) -> float | None:
    """Gigabytes in a size value: '2TB' -> 2000.0, '512GB' -> None (already GB)."""
    if not isinstance(value, str):
        return None
    if not _TB_RE.search(str(value)):
        return None
    number = first_number(str(value))
    return None if number is None else number * TB_IN_GB


def _number_to_float(token: str) -> float | None:
    try:
        return float(token.replace(",", "."))
    except ValueError:
        return None


def to_int(value, lo: float | None = None, hi: float | None = None) -> int:
    """Integer coercion. 12.0 -> 12, 2.5 -> invalid (never silently halved)."""
    if isinstance(value, bool):
        raise InvalidValue(f"bool is not an int: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        number = first_number(strip_unit(value))
    if number is None or math.isnan(number):
        raise InvalidValue(f"no number in {value!r}")
    rounded = round(number)
    if abs(number - rounded) > 0.01:
        raise InvalidValue(f"not an integer: {value!r}")
    result = int(rounded)
    if lo is not None and result < lo:
        raise InvalidValue(f"{result} below minimum {lo}")
    if hi is not None and result > hi:
        raise InvalidValue(f"{result} above maximum {hi}")
    return result


def to_float(value, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise InvalidValue(f"bool is not a float: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        number = first_number(strip_unit(value))
    if number is None or math.isnan(number):
        raise InvalidValue(f"no number in {value!r}")
    if lo is not None and number < lo:
        raise InvalidValue(f"{number} below minimum {lo}")
    if hi is not None and number > hi:
        raise InvalidValue(f"{number} above maximum {hi}")
    return round(float(number), 3)


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        raise InvalidValue(f"non-boolean number {value!r}")
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if re.search(r"\b(yes|true|included|includes)\b", text):
        return True
    if re.search(r"\b(no|false|none)\b", text):
        return False
    raise InvalidValue(f"not a boolean: {value!r}")


MAX_STR = 120


def to_str(value) -> str:
    text = re.sub(r"\s+", " ", str(value).replace("\ufffd", " ")).strip(" ,;")
    if not text or text.lower() in PLACEHOLDERS:
        raise InvalidValue(f"empty string: {value!r}")
    if len(text) > MAX_STR:
        raise InvalidValue(f"string too long ({len(text)}): {value!r}")
    return text


# Shape of a manufacturer part number rather than a model name —
# "100-1000001084WOF", "MZ-V9P2T0BW", "SR3XW". Deliberately narrow, because
# a false positive demotes a real model name:
#   - no spaces (vendor names are written with spaces: "Ryzen 7 9800X3D");
#   - either a separated code whose later groups are 4+ characters (so
#     "100-1000001084WOF" matches while board-style names like "B650M-A"
#     survive: the trailing group is 1 character) or one unbroken run of 10+.
_PART_NUMBER_SEP_RE = re.compile(r"^[A-Z0-9]{2,}(?:[-/][A-Z0-9]{4,}){1,3}$", re.I)
_PART_NUMBER_LONG_RE = re.compile(r"^[A-Z0-9]{10,}$", re.I)


def looks_like_part_number(value) -> bool:
    """True when a `model`-shaped string is really a manufacturer code.

    Why this exists (Sep 2026): Ivory's product pages put the manufacturer
    part number in their "דגם" (model) row — a Ryzen 7 9800X3D page carries
    "100-1000001084WOF". That vendor-tier fact outranked the title-derived
    lineup name, so the site showed "model: 100-1000001084WOF", and the
    product's identity key flipped from model:cpu:ryzen79800x3d-tray to
    sku:cpu:100000001084-tray (the golden fixture caught exactly that).
    Used by merge.py to order a name ahead of a code for the `model` field.

    Errs toward False: a value that could plausibly be a name is left alone.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or " " in text:
        return False
    if _PART_NUMBER_SEP_RE.match(text):
        return True
    return bool(_PART_NUMBER_LONG_RE.match(text))


def _split_list(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for v in value:
            # One vendor ships the list as tokens, another comma-glues it
            # into a single cell ("ATX, Micro ATX, Mini ITX"); splitting
            # inside elements makes both spellings converge instead of
            # recording 500 phantom conflicts per run (Sep 2026).
            parts.extend(re.split(r"\s*[,;|]\s*|\s{2,}", str(v)))
    else:
        parts = re.split(r"\s*[,;|]\s*|\s{2,}", str(value))
    return [p.strip() for p in parts if p and p.strip()]


def to_list_str(value) -> list[str]:
    items: list[str] = []
    for part in _split_list(value):
        try:
            cleaned = to_str(part)
        except InvalidValue:
            continue
        if cleaned not in items:
            items.append(cleaned)
    if not items:
        raise InvalidValue(f"empty list: {value!r}")
    return items[:16]


def to_dict_int(value) -> dict[str, int]:
    """GPU-style output maps: {'DisplayPort 1.4a': 3} from a dict or from
    '3x DisplayPort 1.4a, 1x HDMI 2.1'."""
    out: dict[str, int] = {}
    if isinstance(value, dict):
        for key, raw in value.items():
            try:
                out[str(key).strip()] = int(to_int(raw, 0, 99))
            except InvalidValue:
                continue
    else:
        for part in _split_list(value):
            match = re.match(r"(?i)^(\d+)\s*x\s*(.+)$", part.strip())
            if match:
                out[match.group(2).strip()] = int(match.group(1))
                continue
            try:
                out[to_str(part)] = 1
            except InvalidValue:
                continue
    if not out:
        raise InvalidValue(f"empty output map: {value!r}")
    return out


def parse_range(value) -> tuple[float, float] | None:
    """'600-1500 RPM' / '650 - 2000' / [650, 2000] -> (min, max)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    tokens = _NUM.findall(str(value or ""))
    numbers = [n for n in (_number_to_float(t) for t in tokens)
               if n is not None and n > 0]
    if len(numbers) >= 2:
        return min(numbers[0], numbers[-1]), max(numbers[0], numbers[-1])
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return None


def coerce(field: FieldSpec, value, category: str | None = None):
    """Convert `value` to the field's declared type, applying canonical
    forms and enum checks. Raises InvalidValue so callers drop + count."""
    from .canon import canonicalize

    if is_placeholder(value):
        raise InvalidValue(f"placeholder value: {value!r}")
    value = canonicalize(field, value, category)
    if is_placeholder(value):
        raise InvalidValue(f"placeholder after canonicalization: {value!r}")

    # A TB value in a _gb field is a unit conversion, not a parse: 2TB -> 2000.
    if _GB_FIELD_RE.search(field.name):
        scaled = gb_magnitude(value)
        if scaled is not None:
            return to_int(scaled, field.lo, field.hi) if field.type == "int" \
                else to_float(scaled, field.lo, field.hi)
    if field.type == "int":
        return to_int(value, field.lo, field.hi)
    if field.type == "float":
        return to_float(value, field.lo, field.hi)
    if field.type == "bool":
        return to_bool(value)
    if field.type == "list_str":
        return to_list_str(value)
    if field.type == "dict_int":
        return to_dict_int(value)

    text = to_str(value)
    if field.type == "enum" and field.enum:
        for allowed in field.enum:
            if text.lower() == allowed.lower():
                return allowed
        raise InvalidValue(f"{text!r} not in enum {field.enum}")
    return text
