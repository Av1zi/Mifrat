"""
specs/resolvers/vendor_struct.py — Tier 1: structured vendor payloads.

Sources handled here:
- `vendor_meta` scalar fields (TMS/Ivory builder payloads);
- `detail_specs` rows from the detail-enrichment spiders (Ivory/1PC/Plonter
  spec tables) — keys go through schema.field_for_key(), which owns the
  vendor spelling aliases, so the old 70-entry key table is gone;
- Ivory's opaque builder `cuts` ids, decoded from the committed ground-truth
  table data/ivory_cut_labels.json (never inferred at runtime);
- the post-match bridge: `specs.ingest_computed_attributes()` promotes keys
  matching.py computes from the listing (brand, model, mpn, accessory_type)
  into Tier-1 facts so they are part of the spec sheet instead of a parallel
  blob. This is the ONLY place matching feeds the spec system.

Guards kept from the old code (they prevented real, visible bugs):
- Hebrew / mojibake keys or values are dropped (validate.py enforces this a
  second time) — Plonter's poisoned nav tables and Ivory promo paragraphs;
- Ivory promo/marketing labels ("לחץ/י לרכישה...") are never a spec;
- opaque parent ids / category ids are never exposed as specs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import canon, labels, schema
from ..merge import TIER_VENDOR, Fact, add_fact
from ..values import InvalidValue, coerce, first_number, parse_range, to_int

SOURCE_DETAIL = "vendor:detail"
SOURCE_META = "vendor:meta"
SOURCE_CUTS = "ivory:cut-label"
SOURCE_COMPUTED = "matching:computed"

# Detail rows nobody filters on / that merely echo the title.
DETAIL_KEY_BLACKLIST = frozenset({
    "name", "sku", "segment", "scalability", "remote_management",
    "remote_manageability", "not_available", "warranty", "upc",
})

_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_MOJIBAKE_RE = re.compile(r"[\ufffd\u05f3]")
_PROMO_RE = re.compile(r"\u05dc\u05d7\u05e5/\u05d9|\u05dc\u05e8\u05db\u05d9\u05e9\u05d4|"
                       r"\u05de\u05d5\u05de\u05dc\u05e5|\u05dc\u05e7\u05e8\u05e8")
_CLOCK_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*ghz\s*-\s*(\d+(?:\.\d+)?)\s*ghz?", re.I)

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CUT_LABELS_PATH = _ROOT / "data" / "ivory_cut_labels.json"

_LABELS_CACHE: dict | None = None


def is_junk_text(value) -> bool:
    """Hebrew prose, mojibake or Ivory promo copy — never a spec value."""
    if not isinstance(value, str):
        return False
    if _HEBREW_RE.search(value) or _MOJIBAKE_RE.search(value):
        return True
    return bool(_PROMO_RE.search(value))


def is_promo_label(value) -> bool:
    """Ivory occasionally uses a whole marketing paragraph as a filter label."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return len(stripped) > 40 or bool(_PROMO_RE.search(stripped))


def _emit(facts: dict, category: str, name: str, value, source: str,
          confidence: float = 0.9) -> None:
    field = schema.field_map(category).get(name)
    if field is None or value is None:
        return
    try:
        typed = coerce(field, value, category)
    except InvalidValue:
        return
    add_fact(facts, name, Fact(value=typed, tier=TIER_VENDOR, source=source,
                               confidence=confidence))


def _emit_by_key(facts: dict, category: str, key: str, value, source: str,
                 confidence: float = 0.9, gaps=None) -> None:
    """Emit one vendor (key, value) row through the schema alias map.

    A key that resolves to no field is recorded in `gaps` (coverage evidence)
    instead of vanishing silently.
    """
    if key is None or value is None:
        return
    normalized = schema.normalize_key(key)
    if not normalized or normalized in DETAIL_KEY_BLACKLIST:
        return
    # Hebrew unit words / color words / "ללא" are cleaned here; a value that is
    # still Hebrew prose afterwards is dropped (never half-read).
    value = labels.clean_detail_value(value)
    if value is None or is_junk_text(str(value)):
        return
    field = schema.field_for_key(category, key)
    if field is None:
        _record_gap(gaps, key)
        return
    if field.type == "list_str" and isinstance(value, str) and "|" in value:
        # "DDR5 ECC REG | DDR5 ECC REG 3DS" / "USB Type-C | USB 3.2": a list
        # field keeps every token, a scalar field keeps the whole string and
        # lets canon pick the meaningful part.
        value = [part.strip() for part in value.split("|") if part.strip()]
    if field.name.endswith("_w"):
        value = _range_max(value)
    _emit(facts, category, field.name, value, source, confidence)


def _record_gap(gaps, raw_key) -> None:
    """Count one vendor label that mapped to no schema field.

    Unmapped labels are coverage evidence, not errors: the frequency table
    (`spec_report.json` -> `label_gaps`) is how the vocabulary in
    `specs/labels.py` grows from real pages instead of guesses.
    """
    if gaps is None:
        return
    key = str(raw_key or "").strip()
    if key:
        gaps[key] = gaps.get(key, 0) + 1


# A vendor power figure printed as a range ("450-500W") is stored as the
# upper bound: peaks are what a cooler or a PSU has to survive.
_W_RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:[.,]\d+)?)",
                         re.IGNORECASE)

# "Base 2.7GHz | Max. 4.1GHz", "600MHz - 1200MHz"
_NAMED_BASE_RE = re.compile(r"(?i)base[^0-9]{0,12}(\d+(?:[.,]\d+)?)\s*g?hz")
_NAMED_BOOST_RE = re.compile(
    r"(?i)(?:max|boost|turbo)[^0-9]{0,12}(\d+(?:[.,]\d+)?)\s*g?hz")
_ANY_GHZ_RE = re.compile(r"(?i)(\d+(?:[.,]\d+)?)\s*g?hz")
_TIER_RE = re.compile(r"(?i)\bL\s?([123])\b")
# One tier of a combined CPU cache cell: "L2 16MB", "L3 - 128MB",
# "L1 Cache 512KB", "Total L3 96MB". The tier token is mandatory — a bare
# number is read by the fallback in _emit_cache_tier, never tiered here.
_CACHE_SEGMENT_RE = re.compile(
    r"(?i)\bL\s?([123])\b\s*(?:Cache\s*)?[-:]?\s*(\d+(?:[.,]\d+)?)\s*(KB|MB|GB)?\b"
)
# Intel's name for its shared L3 bucket ('6 MB SmartCache',
# '36MB ... Intel Smart Cache'). Only consulted when no L3 segment
# printed, so 'SmartCache 36MB | L2 32MB' still fills both tiers.
_SMART_CACHE_RE = re.compile(r"(?i)smart\s*cache")
_KIT_RE = re.compile(r"(?i)(\d{1,2})\s*[x×*]\s*(\d{1,4})\s*gb")
_LENGTH_RE = re.compile(r"(?i)\bL\s*=\s*(\d+(?:[.,]\d+)?)")

# SATA port counts as vendor cells print them: '4x SATA 6Gb/s ports' (TMS /
# Gigabyte) and '4 חיבורי SATA' (Ivory's Hebrew spelling, 116 rows on disk).
# The count always LEADS the word 'SATA' — 'SATA 6Gb/s' has the number after
# it and a junk-drawer cell prints 'PCIe 4.0 x4 / SATA mode', so neither is
# guessed. Both patterns are searched in order of specificity.
_SATA_PORTS_RE = re.compile(r"(\d{1,2})\s*x\s*SATA", re.I)
_SATA_PORTS_HE_RE = re.compile(r"(\d{1,2})\s*(?:x\s*)?חיבורי\s*SATA")
# (display label, regex the vendor spelling must match, field). The regex
# form lets "DisplayPort"/"Display Port"/"Mini DisplayPort" all resolve to
# the one port type (see _emit_gpu_outputs).
_GPU_OUTPUTS = (("DisplayPort", r"display\s?port", "dp_outputs"),
                ("HDMI", r"hdmi", "hdmi_outputs"))


def _sata_port_count(text) -> int | None:
    """'4x SATA 6Gb/s ports' / '4 חיבורי SATA' -> 4, else None."""
    for pattern in (_SATA_PORTS_RE, _SATA_PORTS_HE_RE):
        match = pattern.search(str(text or ""))
        if match:
            return int(match.group(1))
    return None


def _range_max(value):
    """"450-500W" -> 500.0, everything else unchanged."""
    if not isinstance(value, str):
        return value
    match = _W_RANGE_RE.search(value)
    if not match:
        return value
    try:
        return max(float(match.group(1).replace(",", ".")),
                   float(match.group(2).replace(",", ".")))
    except ValueError:
        return value


def _emit_clock_range(facts: dict, category: str, value, source: str) -> None:
    """'Base 2.7GHz | Max. 4.1GHz' / '3.6GHz - 4GHz' -> base + boost."""
    text = str(value or "")
    base = _NAMED_BASE_RE.search(text)
    boost = _NAMED_BOOST_RE.search(text)
    if base:
        _emit(facts, category, "base_clock_ghz",
              float(base.group(1).replace(",", ".")), source, 0.85)
    if boost:
        _emit(facts, category, "boost_clock_ghz",
              float(boost.group(1).replace(",", ".")), source, 0.85)
    if base or boost:
        return
    dashed = _CLOCK_RANGE_RE.search(text)
    numbers = ([dashed.group(1), dashed.group(2)] if dashed
               else _ANY_GHZ_RE.findall(text))
    if not numbers:
        return
    if len(numbers) == 1:
        _emit(facts, category, "base_clock_ghz",
              float(numbers[0].replace(",", ".")), source, 0.8)
        return
    # No keywords to anchor on (Ivory's '5.7GHz ~ 4.3GHz' prints MAX
    # first): base is definitionally the smaller figure, boost the
    # larger, whatever order the vendor printed them in. Reading them
    # positionally shipped swapped clocks (9950X3D showed base 5.7).
    ordered = sorted(float(n.replace(",", ".")) for n in numbers[:2])
    _emit(facts, category, "base_clock_ghz", ordered[0], source, 0.8)
    _emit(facts, category, "boost_clock_ghz", ordered[1], source, 0.8)


def _cache_mb(number_text, unit_text):
    """'16' + 'MB' -> 16.0; KB/GB units are converted, unitless stays MB."""
    try:
        size = float(str(number_text).replace(",", "."))
    except (TypeError, ValueError):
        return None
    unit = str(unit_text or "MB").upper()
    if unit == "KB":
        size /= 1024
    elif unit == "GB":
        size *= 1024
    return round(size, 3)


# ECC / registered hide inside memory_type strings. POS before NEG is
# wrong here — "Non-ECC" contains "ECC", so negatives are tested first
# and an explicit positive anywhere beats a negative (a server kit never
# un-prints its ECC because one generic row exists).
_ECC_POS_RE = re.compile(r"\bECC\b|ECC\s*REG|R-DIMM|RDIMM|LRDIMM|LR-DIMM", re.I)
_ECC_NEG_RE = re.compile(r"Non[-\s]?ECC|ללא\s*ECC|\bNO\s*ECC\b", re.I)
_REG_POS_RE = re.compile(r"\bREG\b|RDIMM|LRDIMM|LR-DIMM|R-DIMM\b|Registered", re.I)
_REG_NEG_RE = re.compile(r"Unbuffered|UDIMM|Non[-\s]?ECC", re.I)


def _emit_memory_ecc(facts: dict, category: str, value, source: str) -> None:
    """ECC/registered hide inside memory value strings ("DDR5 ECC REG",
    "Non-ECC Unbuffered") — no vendor prints them as standalone rows.

    Runs on the RAW row value (not the merged memory_type fact, which
    coercion already trimmed to the generation): one row, one vote, so a
    generic "DDR5" row never cancels an explicit one. Genuine vendor
    self-contradictions surface as merge conflicts, as they should.
    """
    text = str(value or "")
    if _ECC_NEG_RE.search(text):
        _emit(facts, category, "ecc", False, source, 0.8)
    elif _ECC_POS_RE.search(text):
        _emit(facts, category, "ecc", True, source, 0.8)
    if _REG_NEG_RE.search(text):
        _emit(facts, category, "registered", False, source, 0.8)
    elif _REG_POS_RE.search(text):
        _emit(facts, category, "registered", True, source, 0.8)


def _emit_cache_tier(facts: dict, category: str, value, source: str) -> None:
    """'L1 1280KB | L2 16MB | L3 128MB' -> l2_cache_mb + l3_cache_mb.

    Every tier segment is read independently. The old code read only the
    FIRST tier token in the cell, so a combined cell either lost all three
    tiers ('L1 ...' fell through to cache_mb, which cpu has no field for)
    or kept only L2 (Ivory's 'L2 - 16MB L3 - 128MB' never reached L3).
    L1 segments are skipped, not misfiled — the schema has no L1 field.

    A bare number with no tier ('36MB') stays on the old fallback path:
    vendors mix L3-only and L2+L3-total figures there (144MB total vs
    128MB L3 on the same X3D class), so tiering it would invent facts.
    """
    text = str(value or "")
    l3_done = False
    for match in _CACHE_SEGMENT_RE.finditer(text):
        if match.group(1) not in ("2", "3"):
            continue
        size = _cache_mb(match.group(2), match.group(3))
        if size is None:
            continue
        _emit(facts, category,
              "l2_cache_mb" if match.group(1) == "2" else "l3_cache_mb",
              size, source, 0.85)
        if match.group(1) == "3":
            l3_done = True
    if l3_done:
        return
    if _SMART_CACHE_RE.search(text):
        number = re.search(r"(\d+(?:[.,]\d+)?)\s*(KB|MB|GB)?\b", text)
        if number:
            size = _cache_mb(number.group(1), number.group(2))
            if size is not None:
                _emit(facts, category, "l3_cache_mb", size, source, 0.85)
                return
    # No tier printed: only a category that HAS a plain cache_mb field (a
    # storage buffer) can take this without guessing which CPU cache it is.
    number = first_number(_TIER_RE.sub(" ", text))
    if number is None:
        return
    _emit(facts, category, "cache_mb", number, source, 0.8)


def _emit_psu_conn_string(facts: dict, category: str, value, source: str) -> None:
    """'350W with Power Connector 3x8-pin' -> external_power ['3x8-pin'].

    Only connector mentions are read; the wattage is a PSU recommendation
    for the buyer's power supply, never the card's draw. Spacing variants
    ("3 x 8-pin") render into the canonical "NxM-pin" shape the direct
    rows already ship; 12VHPWR/12V-2x6 render as "1x16-pin" (same).
    """
    text = str(value or "")
    conns: list[str] = []
    for match in re.finditer(r"(\d+)\s*x\s*(\d+)\s*-?pin", text, re.I):
        rendered = f"{int(match.group(1))}x{int(match.group(2))}-pin"
        if rendered not in conns:
            conns.append(rendered)
    if re.search(r"12VHPWR|12V-2x6", text, re.I) and "1x16-pin" not in conns:
        conns.append("1x16-pin")
    if conns:
        _emit(facts, category, "external_power", conns, source, 0.75)
    # The wattage IS the PSU recommendation, which has its own column since
    # the Oct 2026 completeness pass (recommended_psu_w).
    watts = re.search(r"(\d{3,4})\s*W\b", text, re.I)
    if watts:
        _emit(facts, category, "recommended_psu_w", int(watts.group(1)), source, 0.7)


def _emit_memory_kit(facts: dict, category: str, value, source: str) -> None:
    """'2x16GB' -> module_count 2 + module_size_gb 16 + total_gb 32."""
    text = str(value or "")
    match = _KIT_RE.search(text)
    if not match:
        total = first_number(text)
        if total is not None:
            _emit(facts, category, "total_gb", total, source, 0.8)
        return
    count = int(match.group(1))
    module = int(match.group(2))
    _emit(facts, category, "module_count", count, source, 0.85)
    _emit(facts, category, "module_size_gb", module, source, 0.85)
    _emit(facts, category, "total_gb", count * module, source, 0.85)


def _emit_rpm_range(facts: dict, category: str, value, source: str) -> None:
    """'600-1500 RPM' -> the fan speed fields; '_emit' skips what the
    category does not have (cooler vs case fan spell them differently).

    A degenerate span ('2200 RPM', which parse_range reports as
    (2200, 2200)) is a lone maximum, not a min==max part — filing it as
    min shipped inverted pairs once a second source supplied the real
    max (be quiet! BL070: min 2200 over reference max 1500). Same lone-
    as-max convention as _emit_fan_rpm_cell below.
    """
    span = parse_range(value)
    if not span:
        return
    low, high = span
    if low == high:
        for name in ("fan_rpm_max", "rpm_max"):
            _emit(facts, category, name, high, source, 0.75)
        return
    for name in ("fan_rpm_min", "rpm_min"):
        _emit(facts, category, name, low, source, 0.85)
    for name in ("fan_rpm_max", "rpm_max"):
        _emit(facts, category, name, high, source, 0.85)


def _emit_gpu_dimensions(facts: dict, category: str, value, source: str) -> None:
    """'L=170mm W=69mm' -> length_mm (width has no field, so it is not read)."""
    text = str(value or "")
    match = _LENGTH_RE.search(text)
    number = float(match.group(1).replace(",", ".")) if match else first_number(text)
    if number is not None:
        _emit(facts, category, "length_mm", number, source, 0.8)


def _emit_gpu_outputs(facts: dict, category: str, value, source: str) -> None:
    """'DisplayPort | HDMI' -> dp_outputs / hdmi_outputs (VGA and DVI have no field).

    Counts are read when the vendor prints them ('1x HDMI 2.1b 3x DisplayPort
    2.1b' is three DisplayPorts, not one); without a count each mention is
    one port.
    """
    text = str(value or "")
    tokens = [part.strip() for part in re.split(r"[|,;]", text) if part.strip()]
    for display, needle, field in _GPU_OUTPUTS:
        # `needle` is a regex now: YahavPC spells the same port "Display
        # Port" and prefixes it ("4X Mini Display Port"), which a literal
        # "displayport" substring match never saw (Oct 2026).
        counts = [int(match.group(1)) for match in re.finditer(
            r"(\d{1,2})\s*[x×]?\s*(?:mini\s+|micro\s+)?" + needle, text, re.I)]
        if counts:
            count = sum(counts)
        else:
            count = sum(1 for token in tokens if re.search(needle, token, re.I))
        if count:
            _emit(facts, category, field, {display: count}, source, 0.7)


def _emit_raid(facts: dict, category: str, value, source: str) -> None:
    """'0,1,10' -> True, 'No' -> False. Levels mean the board supports it."""
    text = str(value or "").strip()
    if not text:
        return
    low = text.lower()
    if re.search(r"\d", text) or "yes" in low:
        _emit(facts, category, "raid_support", True, source, 0.8)
    elif low in ("no", "none", "n/a", "not supported"):
        _emit(facts, category, "raid_support", False, source, 0.8)


_LAN_RE = re.compile(r"\bLAN\s*([\d.]+)\s*Gb/s", re.I)
_WIFI_RE = re.compile(r"\bWi-?Fi\s*([67])\s?(E)?\b", re.I)
_BT_RE = re.compile(r"\bBluetooth(?:®)?\s*(?:v(?:ersion)?\s*)?(\d(?:\.\d)?)\b", re.I)
_BT_SHORT_RE = re.compile(r"\bBT\s?(\d\.\d)\b", re.I)


def _emit_connectivity(facts: dict, category: str, value, source: str) -> None:
    """Split a combined networking cell into its radios.

    TMS prints one cell per board: 'Bluetooth 5.4 | Wi-Fi 7 (802.11be) |
    LAN 5 Gb/s'. Emitting that string into `ethernet` whole is a mis-mapping
    the validator then rejects (935 facts/run in Sep 2026); each radio gets
    its own field instead. Bluetooth has no schema field (a board's Bluetooth
    version is not a compatibility fact) so it is noted only.
    """
    text = str(value or "").strip()
    if not text:
        return
    lan = _LAN_RE.search(text)
    wifi = _WIFI_RE.search(text)
    if lan:
        # Keep the vendor's own "LAN 5 Gb/s" token: other paths (title parse,
        # raw cells) ship the same shape, so the field stays uniform.
        _emit(facts, category, "ethernet", lan.group(0), source, 0.85)
    if wifi:
        _emit(facts, category, "wireless", f"Wi-Fi {wifi.group(1)}"
              f"{(wifi.group(2) or '').upper()}", source, 0.85)
    bluetooth = _BT_RE.search(text)
    if bluetooth:
        _emit(facts, category, "bluetooth", f"Bluetooth {bluetooth.group(1)}",
              source, 0.85)
    if not lan and not wifi and not bluetooth:
        # Nothing recognized: keep the raw row so it is not silently lost.
        _emit(facts, category, "ethernet", text, source, 0.6)


def _emit_bluetooth_note(state: dict, value) -> None:
    """Record the Bluetooth version from a split connectivity row (evidence)."""
    match = _BT_RE.search(str(value or ""))
    if match:
        state["bluetooth"] = match.group(1)


# --------------------------------------------------------------------------
# Oct 2026 coverage pass — cells the exact vocabulary could not reach
#
# Every emitter here fills fields that ALREADY exist in the schema; none of
# them invents a fact. The vendor prints the value inside a prose cell or in
# a unit the field does not carry ("12 ס\"מ" for a mm field), which is a
# parsing/shape problem, not a new spec. Unparseable cells emit nothing and
# stay visible in the coverage report.
# --------------------------------------------------------------------------

_HE_NUMBERS = {
    "אחד": 1, "אחת": 1, "שני": 2, "שניים": 2, "שתי": 2, "שתיים": 2,
    "שלושה": 3, "שלוש": 3, "ארבעה": 4, "ארבע": 4, "חמישה": 5, "חמש": 5,
    "שישה": 6, "שש": 6, "שבעה": 7, "שבע": 7, "שמונה": 8, "תשעה": 9,
    "עשרה": 10, "עשר": 10,
}
_CM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:ס\"מ|סמ|cm)", re.I)
_MM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:מ\"מ|ממ|mm)", re.I)
_RPM_RANGE_RE = re.compile(r"(\d{2,5})\s*(?:rpm)?\s*(?:~|-|–|—|to)\s*(\d{2,5})", re.I)
_RPM_TOLERANCE_RE = re.compile(r"[±+]\s*\d{1,3}\s*%|\b\d{1,3}\s*%\b")
_FAN_WORD_RE = re.compile(r"(\d{1,2})\s*[x×]?\s*מאוורר|מאווררים?\s*(\d{1,2})|(\d{1,2})\s*[-\s]?pack\b", re.I)


def _number_to_mm(number, unit: str | None = None) -> int | None:
    """A measuring cell in cm/mm -> int mm (the schema's unit)."""
    try:
        value = float(str(number).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if unit and unit.lower() in ("ס\"מ", "סמ", "cm"):
        value *= 10
    if not (1 <= value <= 2000):
        return None
    return int(round(value))


def _mm_from_text(text, lo: int = 40, hi: int = 300) -> int | None:
    """'12 ס"מ' -> 120, '160 מ"מ' -> 160, '120mm' -> 120; bare '120' -> 120.

    The default window fits fans; length fields (GPU / cooler clearance,
    up to ~600mm) pass their own window. A bare number outside the window
    is not a measurement in this field — never a guess.
    """
    raw = str(text or "")
    match = _MM_RE.search(raw)
    if match:
        size = _number_to_mm(match.group(1), "mm")
        return size if size is not None and lo <= size <= hi else None
    match = _CM_RE.search(raw)
    if match:
        size = _number_to_mm(match.group(1), "cm")
        return size if size is not None and lo <= size <= hi else None
    number = first_number(raw)
    if number is not None and lo <= number <= hi:
        return int(round(number))
    return None


def _fan_count_from_text(text) -> int | None:
    """'2 מאווררי 16 ס"מ' -> 2, 'מאוורר אחד' -> 1, '3-Pack' -> 3."""
    raw = str(text or "")
    match = _FAN_WORD_RE.search(raw)
    if match:
        number = next((g for g in match.groups() if g), None)
        if number:
            return int(number)
    # "3x 140mm" is three fans (the mount convention is count x size); the
    # leading digit must be small or a dimension like "120x120" would read
    # as 120 fans. No trailing word boundary: the size may glue straight
    # onto its unit ("140mm").
    match = re.search(r"\b([1-9])\s*[x×]\s*\d{2,3}(?!\d)", raw)
    if match:
        return int(match.group(1))
    for word in re.split(r"[\s,;:.()]+", raw):
        if word in _HE_NUMBERS:
            return _HE_NUMBERS[word]
    return None


def _emit_sockets_cell(facts: dict, category: str, value, source: str,
                       state: dict) -> None:
    """Accumulate cooler socket rows; the union is emitted after the loop.

    Ivory splits Intel and AMD compatibility into two rows; merging them at
    emit time is the product's real socket list, while a plain mapping would
    let the merge keep one row and drop the other.
    """
    sockets = canon.canon_socket_list(value)
    if not sockets:
        return
    current = state.setdefault("sockets", [])
    for socket in sockets:
        if socket and socket not in current:
            current.append(socket)


def _emit_fan_size(facts: dict, category: str, value, source: str,
                   state: dict | None = None) -> None:
    """'12 ס\"מ' / '120' / 'שני מאווררי 14 ס\"מ' -> fan_size_mm (+count)."""
    size = _mm_from_text(value)
    if size is not None:
        _emit(facts, category, "fan_size_mm", size, source, 0.85)
        _emit(facts, category, "size_mm", size, source, 0.85)
        if state is not None:
            state["aio_fan_size"] = size
    count = _fan_count_from_text(value)
    if count is not None:
        _emit(facts, category, "fan_count", count, source, 0.8)


def _emit_aio_radiator_count(facts: dict, category: str, value, source: str,
                             state: dict) -> None:
    """'3' radiators of 120mm -> fan_count, plus the size arithmetic later."""
    number = first_number(value)
    if number is None:
        return
    count = int(number)
    if not 1 <= count <= 4:
        return
    state["aio_radiator_count"] = count
    _emit(facts, category, "fan_count", count, source, 0.8)


def _emit_cooling_medium(facts: dict, category: str, value, source: str) -> None:
    """'קירור מים' / 'קירור אוויר' -> water_cooled."""
    text = str(value or "")
    if re.search(r"מים|נוזל|liquid|water", text, re.I):
        _emit(facts, category, "water_cooled", True, source, 0.85)
    elif re.search(r"אוויר|\bair\b", text, re.I):
        _emit(facts, category, "water_cooled", False, source, 0.85)


def _emit_fan_rpm_cell(facts: dict, category: str, value, source: str) -> None:
    """'400RPM ~ 1850RPM ±10%' / 'עד 1500RPM' -> the fan speed fields.

    Tolerances are stripped FIRST: reading '1500 ± 10%' as a range would
    ship min=10, which the schema happily accepts and no human would.
    """
    text = _RPM_TOLERANCE_RE.sub(" ", str(value or ""))
    span = _RPM_RANGE_RE.search(text)
    if span:
        low, high = float(span.group(1)), float(span.group(2))
        if low <= high:
            for name in ("fan_rpm_min", "rpm_min"):
                _emit(facts, category, name, low, source, 0.8)
            for name in ("fan_rpm_max", "rpm_max"):
                _emit(facts, category, name, high, source, 0.8)
            return
    number = first_number(text)
    if number is not None and 100 <= number <= 20000:
        for name in ("fan_rpm_max", "rpm_max"):
            _emit(facts, category, name, number, source, 0.75)


def _dims_from_text(text) -> dict[str, int]:
    """Height/width/depth from Hebrew or 'W=220 H=486 D=467mm' cells."""
    raw = str(text or "")
    out: dict[str, int] = {}
    words = (("גובה", "H"), ("height", "H"), ("רוחב", "W"), ("width", "W"),
             ("עומק", "D"), ("depth", "D"), ("אורך", "D"), ("length", "D"))
    for word, axis in words:
        match = re.search(re.escape(word) + r"\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(ס\"מ|cm|מ\"מ|mm)?",
                          raw, re.I)
        if match and axis not in out:
            mm = _number_to_mm(match.group(1), match.group(2))
            if mm:
                out[axis] = mm
    for match in re.finditer(r"\b([WHD])\s*=\s*(\d+(?:[.,]\d+)?)\s*(mm|cm)?", raw):
        axis = match.group(1)
        mm = _number_to_mm(match.group(2), match.group(3) or "mm")
        if mm and axis not in out:
            out[axis] = mm
    return out


def _emit_dims_cell(facts: dict, category: str, value, source: str) -> None:
    """Case cells -> 'W=.. H=.. D=..mm'; cooler cells -> height_mm."""
    dims = _dims_from_text(value)
    if not dims:
        return
    if category == "case":
        parts = [f"{axis}={dims[axis]}" for axis in ("W", "H", "D") if axis in dims]
        if parts:
            _emit(facts, category, "dimensions_mm", " ".join(parts) + "mm", source, 0.8)
        return
    if "H" in dims:
        _emit(facts, category, "height_mm", dims["H"], source, 0.8)


def _emit_length_mm(facts: dict, category: str, field: str, value, source: str) -> None:
    """'31 ס"מ' / '160 מ"מ' / '400' -> int mm in the named field."""
    size = _mm_from_text(value, lo=50, hi=800)
    if size is not None:
        _emit(facts, category, field, size, source, 0.85)


def _emit_fan_mount_cell(facts: dict, category: str, field: str, value, source: str) -> None:
    """'2 מאווררי 12 ס\"מ ARGB' -> '2 x 120 mm'; 'ללא' -> 'None'."""
    text = str(value or "").strip()
    if not text:
        return
    count = _fan_count_from_text(text)
    size = _mm_from_text(text)
    if re.search(r"ללא|אין|not supported|no fans?", text, re.I):
        # "ללא - ניתן להוסיף 2 מאווררי 12 ס\"מ" still names the mount
        # capacity, so it is read as 2 x 120 mm; a flat "none, cannot add"
        # is recorded as None rather than dropped.
        if count is None or size is None:
            _emit(facts, category, field, "None", source, 0.75)
            return
    if count is None and size is None:
        return
    if count and size:
        rendered = f"{count} x {size} mm"
    elif size:
        rendered = f"{size} mm"
    else:
        rendered = f"{count} fans"
    if re.search(r"ARGB|RGB", text, re.I) and "RGB" not in rendered:
        rendered += " ARGB" if "argb" in text.lower() else " RGB"
    _emit(facts, category, field, rendered, source, 0.75)


def _emit_radiator_support(facts: dict, category: str, value, source: str) -> None:
    """'עליון: 120 / 240 מ\"מ' -> {'120 mm': 1, '240 mm': 1} (sizes only)."""
    text = str(value or "")
    if re.search(r"לא נתמך|none", text, re.I):
        return
    sizes = []
    for match in re.finditer(r"(\d{2,3})\s*(?:מ\"מ|mm)?", text):
        size = int(match.group(1))
        if 90 <= size <= 480 and size not in sizes:
            sizes.append(size)
    if sizes:
        _emit(facts, category, "radiator_support",
              {f"{size} mm": 1 for size in sorted(sizes)}, source, 0.7)


def _emit_drive_bays(facts: dict, category: str, value, source: str) -> None:
    """'• כונן אחד HDD (3.5\") • כונן אחד SSD (2.5\")' -> 35/25 counts."""
    text = str(value or "")
    for pattern, field in ((r"3\.5", "drive_bays_35"), (r"2\.5", "drive_bays_25")):
        total = 0
        found = False
        for match in re.finditer(r"(\d{1,2})\s*(?:[x×]\s*)?[^0-9\n]{0,16}?" + pattern, text, re.I):
            total += int(match.group(1))
            found = True
        if not found:
            mentions = len(re.findall(pattern, text))
            if mentions:
                total = mentions
                found = True
        if found and 0 <= total <= 20:
            _emit(facts, category, field, total, source, 0.75)


def _emit_front_io(facts: dict, category: str, value, source: str) -> None:
    """Case front-panel cell -> front_usb list of port tokens."""
    text = re.sub(r"\bUSB\s*-?\s*Type\s*-?\s*([AC])\b", r"USB (Type-\1)",
                  str(value or ""))
    text = re.sub(r"\bUSB\s*-\s*([AC])\b", r"USB (Type-\1)", text)
    ports: list[str] = []
    for match in re.finditer(r"USB\s*(\d(?:\.\d)?|4)?\s*(?:\((Type-[AC])\))?", text, re.I):
        speed = match.group(1)
        kind = match.group(2)
        label = "USB" + (f" {speed}" if speed else "")
        if kind:
            label += f" ({kind.upper().replace('TYPE-', 'Type-')})"
        if label not in ports:
            ports.append(label)
    for pattern, label in ((r"מיקרופון|microphone", "Microphone"),
                           (r"אוזניות|headphone", "Headphone"),
                           (r"קורא כרטיסים|card reader", "Card Reader"),
                           (r"כפתור|power button", "Power Button")):
        if re.search(pattern, text, re.I) and label not in ports:
            ports.append(label)
    if ports:
        _emit(facts, category, "front_usb", ports, source, 0.75)


def _emit_side_window(facts: dict, category: str, value, source: str) -> None:
    """'כולל' -> side_panel 'Windowed' (material unknown, presence is the fact)."""
    text = str(value or "")
    if re.search(r"כולל|כן|\byes\b|included", text, re.I) and not re.search(r"ללא|\bno\b", text, re.I):
        _emit(facts, category, "side_panel", "Windowed", source, 0.7)


def _emit_psu_included_cell(facts: dict, category: str, value, source: str) -> None:
    """'PS2 (ATX) / Mini Redundant (לא כלול)' -> psu_included string."""
    text = str(value or "").strip()
    if not text:
        return
    # A bare "ללא" is the vendor's shorthand for "none": YahavPC's case slot
    # ("וואט / WATT / אמפר") prints it for the many cases sold without a unit
    # (Oct 2026). Anchored to the whole cell on purpose — "ללא" inside a
    # longer phrase ("ללא הגבלה") must not read as "no PSU".
    if re.fullmatch(r"ללא", text):
        _emit(facts, category, "psu_included", "Not included", source, 0.8)
        return
    if re.search(r"לא כלול|לא נכלל|אינו כלול|not included", text, re.I):
        _emit(facts, category, "psu_included", "Not included", source, 0.8)
        return
    if re.search(r"כלול|מובנה|included|redundant|\d{3,4}\s?W", text, re.I):
        _emit(facts, category, "psu_included", "Included", source, 0.7)


def _emit_mb_form_factors(facts: dict, category: str, value, source: str) -> None:
    """'Mini ITX Micro ATX' -> ['Mini ITX', 'Micro ATX'] (concatenated)."""
    text = str(value or "")
    found: list[str] = []
    # One alternation, longest form first: "Micro ATX" must be consumed as a
    # whole so the trailing "ATX" is not counted as a second form factor.
    pattern = re.compile(r"E-?ATX|Micro-?\s?ATX|Mini-?\s?ITX|Mini-?\s?DTX|"
                         r"\bmATX\b|\bATX\b|\bITX\b", re.I)
    for match in pattern.finditer(text):
        # Keep the vendor/registry spelling ("Micro ATX"): the filter
        # values already in the catalog are printed this way, and a
        # canonical rewrite would fork the same board into two options.
        form = re.sub(r"\s+", " ", match.group(0)).strip()
        if form and form.upper() not in {f.upper() for f in found}:
            found.append(form)
    if found:
        _emit(facts, category, "mb_form_factors", found, source, 0.75)


def _emit_gpu_vram(facts: dict, category: str, value, source: str) -> None:
    """'12GB GDDR7' -> memory_gb + memory_type.

    The size is read ONLY with an explicit GB unit: 1PC grouped rows share
    this token across labels, and a bus-width cell ("512-bit") must not
    become 512 GB of VRAM. A type-only cell ("GDDR7") fills just the type.
    """
    text = str(value or "")
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*GB\b", text, re.I)
    if match:
        try:
            number = float(match.group(1).replace(",", "."))
        except ValueError:
            number = None
        if number is not None:
            _emit(facts, category, "memory_gb", number, source, 0.85)
    type_match = re.search(r"\b(GDDR\d+X?|HBM\d?|LPDDR\d+X?)\b", text, re.I)
    if type_match:
        _emit(facts, category, "memory_type", type_match.group(1).upper(), source, 0.8)


def _emit_expansion_slots(facts: dict, category: str, value, source: str) -> None:
    """'8 חריצי הרחבה אופקיים…' -> expansion_slots 8 (leading count).

    The plain field mapping dies in prose cleaning (Hebrew text returns
    None), so the counted variant takes this token. Only a LEADING number
    counts — anything else stays null.
    """
    match = re.match(r"\s*(\d{1,2})\b", str(value or ""))
    if match and 1 <= int(match.group(1)) <= 20:
        _emit(facts, category, "expansion_slots", int(match.group(1)),
              source, 0.8)


def _emit_memory_speeds(facts: dict, category: str, value, source: str) -> None:
    """Support-list speeds -> memory_speeds ["4800", "8200"].

    Reads 4-digit MHz/MT/s figures plus bare 4-digit numbers — but ONLY
    inside explicitly speeds-labeled cells (the token is only mapped on
    such labels). A bare number elsewhere (model codes, voltages, years)
    never reaches this function.
    """
    speeds: list[str] = []
    for match in re.finditer(r"(\d{4,5})\s*(?:MHz|MT/s)?", str(value or ""), re.I):
        num = int(match.group(1))
        if 800 <= num <= 12000 and str(num) not in speeds:
            speeds.append(str(num))
    if speeds:
        _emit(facts, category, "memory_speeds", speeds, source, 0.7)


def _emit_thermal_design(facts: dict, category: str, value, source: str) -> None:
    """Case thermal-design prose -> per-position fan mounts.

    'Front Fans 2x80x25mm | Rear 1x120mm' -> fan_front '2 fans',
    fan_rear '1 x 120 mm'. Only segments that name a position are read;
    anything else in the cell (dimensions, "Fans Included" totals without
    a position, cooler brand lines) is skipped, never guessed. The whole
    cell must carry a fan word (checked once, not per segment — "Rear
    1x120mm" inherits its fan-ness from "Front Fans"). Count/size come
    from the same helpers as the dedicated mount rows so both row kinds
    render identically and never conflict with each other; the lower
    confidence lets real mount rows win ties.
    """
    text = str(value or "")
    if not re.search(r"fan|מאוורר", text, re.I):
        return
    positions = (("fan_front", r"front"), ("fan_rear", r"rear"),
                 ("fan_top", r"\btop\b"), ("fan_bottom", r"bottom"))
    marks = []
    for field, word in positions:
        for match in re.finditer(word, text, re.I):
            marks.append((match.start(), field))
    marks.sort()
    for i, (start, field) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        segment = text[start:end]
        count = _fan_count_from_text(segment)
        size = _mm_from_text(segment)
        if count is None and size is None:
            continue
        if count and size:
            rendered = f"{count} x {size} mm"
        elif size:
            rendered = f"{size} mm"
        else:
            rendered = f"{count} fans"
        _emit(facts, category, field, rendered, source, 0.7)


def _emit_gpu_cooling(facts: dict, category: str, value, source: str) -> None:
    """'צלעות קירור בלבד (קירור פסיבי)' -> Passive, 'מאווררים...' -> Air."""
    text = str(value or "")
    if re.search(r"פסיבי|צלעות קירור בלבד|passive", text, re.I):
        _emit(facts, category, "cooling", "Passive", source, 0.85)
    elif re.search(r"נוזל|liquid|water", text, re.I):
        _emit(facts, category, "cooling", "Liquid", source, 0.85)
    elif re.search(r"מאוורר|fan|blower|windforce", text, re.I):
        # WINDFORCE is Gigabyte's air-cooler brand (41 rows, all Gigabyte
        # cards) — same reading as an explicit fan mention.
        _emit(facts, category, "cooling", "Air", source, 0.85)


def _emit_memory_support(facts: dict, category: str, value, source: str) -> None:
    """Ivory RAM cell -> slots / type / max / supported speeds."""
    text = str(value or "")
    # The slot count is the number heading the slot word — but never the
    # DDR generation ("2 DDR5 slots" holds two slots, not five). Up to two
    # words may intervene for English word order ("2 DDR5 slots"); Hebrew
    # cells ("4 סלוטים DDR5") match directly.
    match = re.search(
        r"(?<!DDR)(\d{1,2})\s*(?:[A-Za-z0-9.]+\s+){0,2}(?:חריצי|סלוטי|slots?)",
        text)
    if match:
        _emit(facts, category, "memory_slots", int(match.group(1)), source, 0.8)
    match = re.search(r"\b(DDR[45])\b", text, re.I)
    if match:
        _emit(facts, category, "memory_type", match.group(1).upper(), source, 0.8)
    match = re.search(r"(?:עד|up to)\s*(\d{2,4})\s*GB", text)
    if match:
        _emit(facts, category, "memory_max_gb", int(match.group(1)), source, 0.75)
    speeds: list[str] = []
    for match in re.finditer(r"(\d{4,5})\s*MT/s", text, re.I):
        if match.group(1) not in speeds:
            speeds.append(match.group(1))
    if speeds:
        _emit(facts, category, "memory_speeds", speeds, source, 0.7)


# Hebrew connector words Ivory wraps around the CPU families it lists:
# "מעבדי AMD: … מסדרות AMD Ryzen 9000 / 8000" ("processors", "from series").
_CPU_SUPPORT_WORDS = (
    "\u05de\u05e2\u05d1\u05d3\u05d9\u05dd",   # מעבדים
    "\u05de\u05e2\u05d1\u05d3\u05d9",         # מעבדי
    "\u05de\u05e2\u05d1\u05d3",               # מעבד
    "\u05de\u05e1\u05d3\u05e8\u05d5\u05ea",   # מסדרות
    "\u05e1\u05d3\u05e8\u05d5\u05ea",         # סדרות
    "\u05e1\u05d3\u05e8\u05d4",               # סדרה
)


def _emit_cpu_support(facts: dict, category: str, value, source: str) -> None:
    """Ivory's "תמיכה במעבדים (CPU)" prose -> a compact token string.

    The cell names whole CPU families in Hebrew prose ("מעבדי AMD: Ryzen 3 /
    Ryzen 5 / Ryzen 7 / Ryzen 9 מסדרות AMD Ryzen 9000 / 8000 / 7000",
    "Intel Core Ultra 5 / 7 / 9 סדרה Intel Core Ultra Processors (Series 2)
    - Arrow Lake"). Everything factual in it is Latin + digits, so the
    Hebrew connector words are stripped and the remaining tokens are
    compacted ("AMD Ryzen 3 / Ryzen 5 / Ryzen 9 / Ryzen 9000 / 8000 /
    7000"). Nothing is translated or invented — a cell with no Latin/digit
    content at all is refused rather than guessed.
    """
    if category != "motherboard":
        return
    text = str(value or "")
    if not text:
        return
    for word in _CPU_SUPPORT_WORDS:
        text = text.replace(word, " ")
    text = re.sub(r"[\u0590-\u05FF]+", " ", text)   # any leftover Hebrew run
    text = text.replace(":", " ").replace("\ufffd", " ")
    text = re.sub(r"\s+", " ", text).strip(" -/|")
    if not text:
        return

    # The family name repeats mid-cell in two shapes: with no separators at
    # all ("AMD Ryzen 3 AMD Ryzen 5 …") and inside one slot ("Ryzen 9 AMD
    # Ryzen 9000"). Turn every repeat after the first into a separator so
    # each chip/series lands in its own slot.
    for family in ("AMD Ryzen", "Intel Core Ultra"):
        text = re.sub(r"(?<=\S)\s+" + family + r"\s+", f" / {family} ", text)

    parts = [part.strip()
             for part in re.split(r"\s*(?:/|,|\u2022|\||\u00b7)\s*", text)
             if part.strip()]
    out: list[str] = []
    for part in parts:
        if part and part not in out:
            out.append(part)
    text = " / ".join(out)

    # "AMD Ryzen" re-states the family in the series list ("AMD Ryzen 3 /
    # Ryzen 9 / AMD Ryzen 9000"): keep the word, drop the brand repeat.
    if text.count("AMD Ryzen") > 1:
        first = text.find("AMD Ryzen")
        head = text[:first + len("AMD Ryzen")]
        text = head + text[first + len("AMD Ryzen"):].replace("AMD Ryzen", "Ryzen")
    # "(Series 2)" restates "Intel Core Ultra" — keep the first mention.
    while text.count("Intel Core Ultra") > 1:
        first = text.find("Intel Core Ultra")
        second = text.find("Intel Core Ultra", first + len("Intel Core Ultra"))
        before = text[:second].rstrip(" /")
        after = text[second + len("Intel Core Ultra"):].lstrip(" /")
        text = (before + " " + after).strip()

    text = re.sub(r"\bProcessors?\b", " ", text, flags=re.I)
    text = re.sub(r"\s*/\s*", " / ", text).strip(" -/")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return
    _emit(facts, category, "cpu_support", text, source, 0.75)


def _emit_cpu_memory_support(facts: dict, category: str, value, source: str) -> None:
    """CPU "אפשרויות הרחבה וקישוריות" cell -> supported memory capacity.

    "• תומך עד 192GB זכרון DDR5 • תומך PCI Express דור 5.0 • סה"כ 24 PCI
    Express Lane" — only the capacity has a schema field; the PCIe lanes are
    left to the label-gap evidence.
    """
    if category != "cpu":
        return
    match = re.search(r"(?:עד|up to)\s*(\d{2,4})\s*GB", str(value or ""))
    if match:
        _emit(facts, category, "max_memory_gb", int(match.group(1)), source, 0.7)


def _emit_storage_support(facts: dict, category: str, value, source: str) -> None:
    """Ivory storage cell -> M.2 count / SATA ports / RAID."""
    text = str(value or "")
    m2 = 0
    match = re.search(r"(\d{1,2})\s*x\s*M\.2", text, re.I)
    if match:
        m2 = int(match.group(1))
    slots = {slot for slot in re.findall(r"M\.2_(\d{1,2})\b", text)}
    if slots:
        m2 = max(m2, len(slots))
    if m2:
        _emit(facts, category, "m2_slots", m2, source, 0.75)
    sata = _sata_port_count(text)
    if sata is not None:
        _emit(facts, category, "sata_ports", sata, source, 0.75)
    if re.search(r"RAID", text, re.I):
        _emit(facts, category, "raid_support", True, source, 0.7)


def _emit_usb_summary(facts: dict, category: str, value, source: str) -> None:
    """Rear-panel USB cell -> one usb_ports summary string.

    '2 חיבורי USB 10Gbps (Type-A) • חיבור USB 20Gbps (Type-C)' ->
    'USB 10Gbps (Type-A) x2, USB 20Gbps (Type-C) x1'
    """
    text = str(value or "")
    parts: list[str] = []
    for match in re.finditer(
            r"(\d{1,2})?\s*(?:×|x)?\s*חיבורי?\s*USB\s*"
            r"([\d.]+\s*(?:Gbps|Gen\s*\d)?)?\s*(?:\((Type-[AC])\))?",
            text, re.I):
        count = int(match.group(1)) if match.group(1) else 1
        speed = (match.group(2) or "").strip()
        kind = match.group(3)
        label = "USB" + (f" {speed}" if speed else "")
        if kind:
            label += f" ({kind})"
        entry = f"{label} x{count}"
        if entry not in parts:
            parts.append(entry)
    if not parts:
        for match in re.finditer(r"USB\s*([\d.]+)?\s*(?:Gen\s*(\d))?\s*(?:\((Type-[AC])\))?",
                                 text, re.I):
            label = "USB" + (f" {match.group(1)}" if match.group(1) else "")
            if match.group(2):
                label += f" Gen{match.group(2)}"
            if match.group(3):
                label += f" ({match.group(3)})"
            if label not in parts:
                parts.append(label)
    if parts:
        _emit(facts, category, "usb_ports", ", ".join(parts), source, 0.75)


def _emit_rear_outputs(facts: dict, category: str, value, source: str) -> None:
    """Rear video ports -> onboard_video ('HDMI | DisplayPort')."""
    text = str(value or "")
    found: list[str] = []
    # "Display Port" (two words) is YahavPC's spelling of DisplayPort and
    # would otherwise be missed entirely (Oct 2026).
    for pattern, label in ((r"Display\s?Port", "DisplayPort"),
                           (r"HDMI", "HDMI"),
                           (r"DVI", "DVI"), (r"VGA", "VGA")):
        if re.search(pattern, text, re.I) and label not in found:
            found.append(label)
    if found:
        _emit(facts, category, "onboard_video", " | ".join(found), source, 0.75)


def _emit_internal_headers(facts: dict, category: str, value, source: str) -> None:
    """Internal header cell -> sata_ports (fan / USB header counts were pruned
    2026-10-18: 8.5% / 11.2% fill)."""
    sata = _sata_port_count(str(value or ""))
    if sata is not None:
        _emit(facts, category, "sata_ports", sata, source, 0.7)


def _emit_quantity_words(facts: dict, category: str, value, source: str) -> None:
    """'מאוורר אחד' / '3-Pack' -> quantity."""
    count = _fan_count_from_text(value)
    if count is not None and 1 <= count <= 20:
        _emit(facts, category, "quantity", count, source, 0.8)


def _emit_fan_connector(facts: dict, category: str, value, source: str) -> None:
    """'4pin PWM' -> connector '4-pin' + pwm True."""
    text = str(value or "")
    match = re.search(r"(\d)\s*-?\s*pin", text, re.I)
    if match:
        _emit(facts, category, "connector", f"{match.group(1)}-pin", source, 0.75)
    if re.search(r"PWM", text, re.I):
        _emit(facts, category, "pwm", True, source, 0.75)


def _emit_nand(facts: dict, category: str, value, source: str) -> None:
    """'TLC | 3D/V NAND' -> nand '3D NAND' (the most specific token)."""
    text = str(value or "")
    tokens = [token.strip() for token in re.split(r"[|,]", text) if token.strip()]
    if not tokens:
        return
    specific = [token for token in tokens if "nand" in token.lower() and token.lower() != "nand"]
    chosen = (specific[-1] if specific else tokens[0])
    chosen = re.sub(r"3D\s*/\s*V", "3D", chosen, flags=re.I)
    _emit(facts, category, "nand", chosen, source, 0.7)


def _emit_storage_form_factor(facts: dict, category: str, value, source: str) -> None:
    """'M.2 2280' -> form_factor; a dimensions cell is not a form factor."""
    text = str(value or "")
    if re.search(r"M\.2", text, re.I):
        match = re.search(r"M\.2\s*(\d{4})", text, re.I)
        rendered = f"M.2 {match.group(1)}" if match else "M.2"
    elif re.search(r"2\.5", text):
        rendered = '2.5"'
    elif re.search(r"3\.5", text):
        rendered = '3.5"'
    elif re.search(r"1\.8", text):
        rendered = '1.8"'
    elif re.search(r"\bU\.2\b", text, re.I):
        rendered = "U.2"
    else:
        return
    _emit(facts, category, "form_factor", rendered, source, 0.7)


def _emit_network_card(facts: dict, category: str, value, source: str) -> None:
    """1PC's "Spec / Network Card" cell, routed to its radio.

    The schema alias map sends this label to `ethernet` whole, so a
    Wi-Fi-only cell ("Wi-Fi 6") used to ship as the board's LAN at 0.9 and
    beat the vendor-detail ethernet in the merge. Each radio gets its own
    field instead, at 0.85 so a detailed vendor cell still wins ties.
    """
    text = str(value or "").strip()
    if not text:
        return
    wifi = re.search(r"Wi-?Fi\s*([67])\s?(E)?", text, re.I)
    if wifi:
        _emit(facts, category, "wireless", f"Wi-Fi {wifi.group(1)}"
              f"{(wifi.group(2) or '').upper()}", source, 0.85)
    elif re.search(r"Wi-?Fi", text, re.I):
        # A board that names Wi-Fi without a generation (YahavPC's
        # "Wired LAN, Bluetooth, Wi-Fi", Oct 2026). canon_wireless turns
        # the bare name into "Yes", so the board still reads as wireless
        # instead of the whole cell being dropped into `ethernet`.
        _emit(facts, category, "wireless", "Wi-Fi", source, 0.7)
    lan = re.search(r"\b(?:Ethernet|LAN)\b\s*([\d.]+)?\s*(?:Gb?)?", text, re.I)
    if lan:
        if lan.group(1):
            _emit(facts, category, "ethernet", f"LAN {lan.group(1)} Gb/s",
                  source, 0.85)
        else:
            _emit(facts, category, "ethernet", "Ethernet", source, 0.7)


def _emit_interface_connectivity(facts: dict, category: str, value, source: str) -> None:
    """1PC's grouped cell, routed per category (never guessed across one).

    Motherboard: 'USB 2.0, USB 3.2, USB Type-C, Thunderbolt' -> usb_ports (+
    wireless / ethernet when the cell names them). Storage: 'PCIe Gen 4.0 x4'
    -> interface + pcie_gen. GPU: 'PCIe 4.0 x16, HDMI 2.1' -> interface +
    outputs. Case: 'USB 3.2, USB-C' -> front_usb (front-panel ports).
    Fans and coolers: 'iCUE LINK' / 'ARGB' -> connector + led, '4PIN PWM' ->
    the cooler's connector list. PSU / memory / CPU cells ('Modular.',
    '262-pin', 'PCIe 3.0') name no schema field and stay unmapped on purpose.
    """
    text = str(value or "").strip()
    if not text:
        return
    if category == "case":
        parts = [part.strip() for part in re.split(r"[,;]+", text) if part.strip()]
        usb = [part for part in parts
               if re.search(r"USB|Type-[AC]\b", part, re.I)]
        if usb:
            _emit(facts, category, "front_usb", usb[:8], source, 0.7)
        return
    if category == "motherboard":
        parts = [part.strip() for part in re.split(r"[,;]+", text) if part.strip()]
        usb = [part for part in parts if re.search(r"USB|Thunderbolt", part, re.I)]
        if usb:
            _emit(facts, category, "usb_ports", ", ".join(usb[:8]), source, 0.7)
        wifi = re.search(r"Wi-?Fi\s*([67])\s?(E)?", text, re.I)
        if wifi:
            _emit(facts, category, "wireless", f"Wi-Fi {wifi.group(1)}"
                  f"{(wifi.group(2) or '').upper()}", source, 0.75)
        lan = re.search(r"(?:Ethernet|LAN)\s*([\d.]+)?\s*(?:Gb)?", text, re.I)
        if lan and lan.group(1):
            _emit(facts, category, "ethernet", f"LAN {lan.group(1)} Gb/s", source, 0.75)
        return
    if category == "storage":
        match = re.search(r"(PCIe|PCI-?E|SATA|NVMe)[^,;|]*", text, re.I)
        if match:
            _emit(facts, category, "interface", match.group(0).strip(), source, 0.7)
        gen = re.search(r"(?:PCIe|PCI-?E)\s*(?:Gen)?\s*([3-6])(?:\.0)?\b", text, re.I)
        if gen:
            _emit(facts, category, "pcie_gen", int(gen.group(1)), source, 0.7)
        return
    if category in ("aio", "cooler_air", "cooling_other"):
        parts = [part.strip() for part in re.split(r"[,;]+", text) if part.strip()]
        parts = [part for part in parts
                 if re.search(r"pin|PWM|iCUE|USB|ARGB|SATA", part, re.I)]
        if parts:
            _emit(facts, category, "connectors", parts[:8], source, 0.7)
        return
    if category == "case_fan":
        if re.search(r"ARGB", text, re.I):
            _emit(facts, category, "led", "ARGB", source, 0.7)
        elif re.search(r"\bRGB\b", text, re.I):
            _emit(facts, category, "led", "RGB", source, 0.7)
        link = re.search(r"iCUE LINK(?:\s+System\s+Hub)?|4\s*-?\s*pin\s*PWM|3\s*-?\s*pin",
                         text, re.I)
        if link:
            _emit(facts, category, "connector", link.group(0), source, 0.7)
        return
    if category == "gpu":
        _emit_gpu_outputs(facts, category, text, source)
        match = re.search(r"PCI-?e\s*[\d.]*\s*x\d+", text, re.I)
        if match:
            _emit(facts, category, "interface", match.group(0), source, 0.7)
        return


def _emit_slot_count(facts: dict, category: str, field: str, value, source: str,
                     state: dict) -> None:
    """Accumulate x16 / x1 slot counts across rows (TMS prints them per type).

    Two shapes: a bare count ("2") and a lane-annotated list ("1xPCIe 4.0 x8
    | 2xPCIe 4.0 x8" is three slots, not one and not eight — the digit
    before the `x` counts slots, the digit after it counts lanes).
    """
    text = str(value or "")
    counts = [int(m.group(1)) for m in re.finditer(r"(\d{1,2})\s*x(?=\s*[A-Za-z])", text)]
    if counts and sum(counts) <= 12:
        key = f"slot_count_{field}"
        state[key] = state.get(key, 0) + sum(counts)
        return
    if counts:
        return
    number = first_number(text)
    if number is None or not 0 <= number <= 12:
        return
    key = f"slot_count_{field}"
    state[key] = state.get(key, 0) + int(number)


def _emit_connector_count(facts: dict, category: str, field: str, value, source: str) -> None:
    """'2 חיבורי CPU 4+4-pin' -> eps8_connectors 2; 'ללא' -> 0.

    The count is read ONLY in leading position: pin-type digits inside the
    cell ("4+4-pin", "12VHPWR", "24-pin") are the connector SHAPE, and an
    earlier revision shipped them as counts (a single "4+4-pin" CPU cable
    read as 4 EPS connectors). A singular "חיבור ..." with no leading
    number is one connector; a bare number above 24 is not a count.
    """
    text = str(value or "").strip()
    if not text:
        return
    if re.match(r"^(?:ללא|אין|none|no)\b", text, re.I):
        _emit(facts, category, field, 0, source, 0.75)
        return
    match = re.match(r"\s*(\d{1,2})\s*(?:חיבורי|×|x\b)?", text)
    if match and int(match.group(1)) <= 24:
        _emit(facts, category, field, int(match.group(1)), source, 0.8)
        return
    if re.search(r"חיבור\b", text):
        _emit(facts, category, field, 1, source, 0.7)


# --------------------------------------------------------------------------
# Oct 2026 completeness pass
# --------------------------------------------------------------------------

_GBPS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*gbps", re.I)
_BUS_BIT_RE = re.compile(r"(\d{2,4})\s*bits?\b", re.I)
_THICKNESS_RE = re.compile(
    r"(?:עובי|thickness)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(ס\"מ|סמ|cm|מ\"מ|ממ|mm)?",
    re.I)
_SPEED_RE = re.compile(r"(\d[\d,.]*)\s*(gb|mb)", re.I)


def _plain_number(token) -> float | None:
    """'10,000' -> 10000.0, '1.5' -> 1.5. The comma is a thousands mark in a
    vendor table, never a decimal point (first_number would read "10,000" as
    10.0 and ship a 10,000MB/s drive as 10MB/s)."""
    try:
        return float(str(token).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _emit_memory_speed(facts: dict, category: str, value, source: str) -> None:
    """'28Gbps' -> memory_speed_gbps.

    Deliberately narrow: the sibling row prints bandwidth in GB/s
    ("224GB/s") and legacy cards print a clock in MHz, neither of which is a
    GDDR data rate — a value without the Gbps unit stays unmapped.
    """
    match = _GBPS_RE.search(str(value or ""))
    if not match:
        return
    number = _plain_number(match.group(1))
    if number is not None:
        _emit(facts, category, "memory_speed_gbps", round(number), source, 0.8)


def _emit_memory_bus(facts: dict, category: str, value, source: str) -> None:
    """'128bit' / '256bits' -> memory_bus_bit."""
    match = _BUS_BIT_RE.search(str(value or ""))
    if match:
        _emit(facts, category, "memory_bus_bit", int(match.group(1)), source, 0.8)


def _emit_radiator_dims(facts: dict, category: str, value, source: str) -> None:
    """Ivory's radiator block: 'אורך: 403 מ\"מ רוחב: 120 מ\"מ עובי: 27 מ\"מ'.

    The size class (360) is already on the sheet; these are the real
    dimensions that decide whether the radiator clears a tight case.
    """
    text = str(value or "")
    dims = _dims_from_text(text)
    if "D" in dims:
        _emit(facts, category, "radiator_length_mm", dims["D"], source, 0.8)
    match = _THICKNESS_RE.search(text)
    if match:
        mm = _number_to_mm(match.group(1), match.group(2))
        if mm is not None:
            _emit(facts, category, "radiator_thickness_mm", mm, source, 0.8)


def _emit_speed_mbs(facts: dict, category: str, field: str, value, source: str) -> None:
    """'7450MB/s' / '10,000MB לשניה' / '1.5GB/s' -> int MB/s in `field`."""
    match = _SPEED_RE.search(str(value or ""))
    if not match:
        return
    number = _plain_number(match.group(1))
    if number is None:
        return
    if match.group(2).lower() == "gb":
        number *= 1000
    _emit(facts, category, field, round(number), source, 0.8)


_DISPLAY_COUNT_RE = re.compile(r"(\d{1,2})")


def _emit_display_count(facts: dict, category: str, value, source: str) -> None:
    """'4' / 'עד 4 מסכים' -> max_displays 4. The number is the whole fact; the
    Hebrew framing around it made the plain-value path drop the cell."""
    match = _DISPLAY_COUNT_RE.search(str(value or ""))
    if not match:
        return
    count = int(match.group(1))
    if 1 <= count <= 8:
        _emit(facts, category, "max_displays", count, source, 0.8)


_PACKAGING_WORD_RE = re.compile(r"\b(retail|boxed|box|bulk|tray|oem|mpk)\b", re.I)


def _emit_packaging_cell(facts: dict, category: str, value, source: str) -> None:
    """'Retail - קופסה' / 'Bulk - בשקית' / 'גרסת OEM Tray ללא מאוורר' -> packaging.

    The English word is the fact and the Hebrew half is the vendor's gloss;
    as a plain value the whole cell was dropped by the Hebrew-prose rule
    (that is why 126 packing rows on boards, drives, memory and PSUs were
    empty while the CPU's own row was already mapped).
    """
    text = str(value or "")
    # "OEM Tray" is a tray, not an OEM bulk part (canon_packaging's rule).
    if re.search(r"\btray\b", text, re.I):
        word = "tray"
    else:
        match = _PACKAGING_WORD_RE.search(text)
        if not match:
            return
        word = match.group(1)
    _emit(facts, category, "packaging", word, source, 0.8)


_CONNECTORS_CELL = (
    (re.compile(r"(\d)\s*pin\s*pwm", re.I), "{0}-pin PWM"),
    (re.compile(r"(\d)\s*pin\s*argb", re.I), "{0}-pin ARGB"),
    (re.compile(r"(\d)\s*pin\s*rgb", re.I), "{0}-pin RGB"),
    (re.compile(r"(\d)\s*pin\s*usb", re.I), "{0}-pin USB"),
    (re.compile(r"(\d)\s*pin\s*(?:pcie|pci-e)", re.I), "{0}-pin PCIe"),
    (re.compile(r"(\d)\s*pin\s*sata", re.I), "{0}-pin SATA"),
)
_USB_TOKEN_RES = (
    (re.compile(r"usb\s*2\.0", re.I), "USB 2.0"),
    (re.compile(r"usb\s*3\.0", re.I), "USB 3.0"),
    (re.compile(r"usb\s*3\.2", re.I), "USB 3.2"),
    (re.compile(r"\bsata\b", re.I), "SATA"),
)


def _emit_connectors_cell(facts: dict, category: str, value, source: str) -> None:
    """Ivory's cooler wiring cell -> the connector list, not the sentence.

    '• חיבור 4pin PWM ללוח אם או בקר מאווררים • חיבור 3pin ARGB ללוח אם •
    חיבור USB2.0 פנימי' -> ['4-pin PWM', '3-pin ARGB', 'USB 2.0']. The
    plain-prose cell would have been dropped as Hebrew text; what a fitter
    needs is the pins.
    """
    text = str(value or "")
    out: list[str] = []
    for pattern, template in _CONNECTORS_CELL:
        for match in pattern.finditer(text):
            item = template.format(match.group(1))
            if item not in out:
                out.append(item)
    for pattern, label in _USB_TOKEN_RES:
        if pattern.search(text) and label not in out:
            out.append(label)
    if out:
        _emit(facts, category, "connectors", out, source, 0.7)


def _emit_generation(facts: dict, category: str, value, source: str) -> None:
    """'דור 14' / 'Series 2' -> `generation` ('Gen 14' / 'Gen 2').

    The vendor's own word is what makes the cell a generation: a bare number
    is left alone, so the column never holds an unexplained digit.
    """
    text = str(value or "").strip()
    if not re.search(r"(?:\u05d3\u05d5\u05e8|generation|gen|series)\s*\d", text, re.I):
        return
    _emit(facts, category, "generation", text, source, 0.8)


def _emit_storage_type_cell(facts: dict, category: str, value, source: str) -> None:
    """1PC's "Storage / Storage Type" cell, read per category.

    The same English label prints a different fact on each kind of page: a
    board's drive interfaces ("M.2, SATA III"), a drive's type ("NVMe",
    "SSD NVMe") and a GPU's memory ("GDDR6", "512-bit"). Each category keeps
    only the fact its own schema has a column for.
    """
    text = str(value or "").strip()
    if not text:
        return
    if category == "motherboard":
        parts = [part.strip() for part in re.split(r"[,;|]+", text) if part.strip()]
        parts = [part for part in parts
                 if re.search(r"M\.2|SATA|PCI-?e|NVMe|U\.2|SlimSAS", part, re.I)]
        if parts:
            _emit(facts, category, "storage_interface", parts[:6], source, 0.7)
        return
    if category == "storage":
        match = re.search(r"SSHD|Hybrid|HDD|SSD|NVMe", text, re.I)
        if match:
            _emit(facts, category, "type", match.group(0), source, 0.7)
        return
    if category == "gpu":
        # The same cell has carried a VRAM string on some pages ("12GB
        # GDDR7"); GPU_VRAM owns that shape and the type-only one ("GDDR7"),
        # and deliberately ignores the bus-width shape — which is read here.
        _emit_gpu_vram(facts, category, text, source)
        match = re.search(r"(\d{2,4})\s*-?\s*bits?\b", text, re.I)
        if match:
            _emit(facts, category, "memory_bus_bit", int(match.group(1)), source, 0.8)
        return


def _apply_special(facts: dict, category: str, token: str, value, source: str,
                   state: dict) -> bool:
    """One vendor row that expands into several schema fields. True = handled."""
    if token == labels.GENERATION_CELL:
        _emit_generation(facts, category, value, source)
        return True
    if token == labels.STORAGE_TYPE_CELL:
        _emit_storage_type_cell(facts, category, value, source)
        return True
    if token == labels.MEMORY_SPEED_GBPS:
        _emit_memory_speed(facts, category, value, source)
        return True
    if token == labels.MEMORY_BUS_BIT:
        _emit_memory_bus(facts, category, value, source)
        return True
    if token == labels.RADIATOR_DIMS:
        _emit_radiator_dims(facts, category, value, source)
        return True
    if token == labels.CONNECTORS_CELL:
        _emit_connectors_cell(facts, category, value, source)
        return True
    if token == labels.PACKAGING_CELL:
        _emit_packaging_cell(facts, category, value, source)
        return True
    if token == labels.DISPLAY_COUNT:
        _emit_display_count(facts, category, value, source)
        return True
    if token.startswith(labels.SPEED_MBS_PREFIX):
        _emit_speed_mbs(facts, category, token[len(labels.SPEED_MBS_PREFIX):],
                        value, source)
        return True
    if token == labels.CLOCK_RANGE:
        _emit_clock_range(facts, category, value, source)
        return True
    if token == labels.CACHE_TIER:
        _emit_cache_tier(facts, category, value, source)
        return True
    if token == labels.MEMORY_KIT:
        _emit_memory_kit(facts, category, value, source)
        return True
    if token == labels.RPM_RANGE:
        _emit_rpm_range(facts, category, value, source)
        return True
    if token == labels.GPU_DIMENSIONS:
        _emit_gpu_dimensions(facts, category, value, source)
        return True
    if token == labels.GPU_OUTPUTS:
        _emit_gpu_outputs(facts, category, value, source)
        return True
    if token == labels.RAID:
        _emit_raid(facts, category, value, source)
        return True
    if token == labels.CONNECTIVITY_SPLIT:
        _emit_connectivity(facts, category, value, source)
        _emit_bluetooth_note(state, value)
        return True
    if token.startswith(labels.USB_COUNT_PREFIX):
        standard = token[len(labels.USB_COUNT_PREFIX):]
        try:
            count = to_int(value, 0, 24)
        except InvalidValue:
            return True
        state.setdefault("usb", {})[standard] = count
        return True
    if token == labels.SOCKETS_CELL:
        _emit_sockets_cell(facts, category, value, source, state)
        return True
    if token == labels.FAN_SIZE:
        _emit_fan_size(facts, category, value, source, state)
        return True
    if token == labels.AIO_RADIATOR_COUNT:
        _emit_aio_radiator_count(facts, category, value, source, state)
        return True
    if token == labels.COOLING_MEDIUM:
        _emit_cooling_medium(facts, category, value, source)
        return True
    if token == labels.FAN_RPM_CELL:
        _emit_fan_rpm_cell(facts, category, value, source)
        return True
    if token == labels.DIMS_CELL:
        _emit_dims_cell(facts, category, value, source)
        return True
    if token.startswith(labels.LENGTH_MM_PREFIX):
        _emit_length_mm(facts, category, token[len(labels.LENGTH_MM_PREFIX):],
                        value, source)
        return True
    if token.startswith(labels.FAN_MOUNT_PREFIX):
        _emit_fan_mount_cell(facts, category, token[len(labels.FAN_MOUNT_PREFIX):],
                             value, source)
        return True
    if token == labels.RADIATOR_SUPPORT:
        _emit_radiator_support(facts, category, value, source)
        return True
    if token == labels.DRIVE_BAYS:
        _emit_drive_bays(facts, category, value, source)
        return True
    if token == labels.FRONT_IO:
        _emit_front_io(facts, category, value, source)
        return True
    if token == labels.SIDE_WINDOW:
        _emit_side_window(facts, category, value, source)
        return True
    if token == labels.PSU_INCLUDED_CELL:
        _emit_psu_included_cell(facts, category, value, source)
        return True
    if token == labels.MB_FORM_FACTORS:
        _emit_mb_form_factors(facts, category, value, source)
        return True
    if token == labels.GPU_VRAM:
        _emit_gpu_vram(facts, category, value, source)
        return True
    if token == labels.GPU_COOLING:
        _emit_gpu_cooling(facts, category, value, source)
        return True
    if token == labels.MEMORY_SUPPORT:
        _emit_memory_support(facts, category, value, source)
        return True
    if token == labels.CPU_SUPPORT:
        _emit_cpu_support(facts, category, value, source)
        return True
    if token == labels.CPU_MEMORY_SUPPORT:
        _emit_cpu_memory_support(facts, category, value, source)
        return True
    if token == labels.STORAGE_SUPPORT:
        _emit_storage_support(facts, category, value, source)
        return True
    if token == labels.USB_SUMMARY:
        _emit_usb_summary(facts, category, value, source)
        return True
    if token == labels.REAR_OUTPUTS:
        _emit_rear_outputs(facts, category, value, source)
        return True
    if token == labels.INTERNAL_HEADERS:
        _emit_internal_headers(facts, category, value, source)
        return True
    if token == labels.QUANTITY_WORDS:
        _emit_quantity_words(facts, category, value, source)
        return True
    if token == labels.FAN_CONNECTOR:
        _emit_fan_connector(facts, category, value, source)
        return True
    if token == labels.NAND_CELL:
        _emit_nand(facts, category, value, source)
        return True
    if token == labels.STORAGE_FORM_FACTOR:
        _emit_storage_form_factor(facts, category, value, source)
        return True
    if token == labels.INTERFACE_CONNECTIVITY:
        _emit_interface_connectivity(facts, category, value, source)
        return True
    if token == labels.NETWORK_CARD:
        _emit_network_card(facts, category, value, source)
        return True
    if token == labels.PSU_CONN_STRING:
        _emit_psu_conn_string(facts, category, value, source)
        return True
    if token == labels.THERMAL_DESIGN:
        _emit_thermal_design(facts, category, value, source)
        return True
    if token == labels.MEMORY_SPEEDS:
        _emit_memory_speeds(facts, category, value, source)
        return True
    if token == labels.EXPANSION_SLOTS:
        _emit_expansion_slots(facts, category, value, source)
        return True
    if token.startswith(labels.SLOT_COUNT_PREFIX):
        _emit_slot_count(facts, category, token[len(labels.SLOT_COUNT_PREFIX):],
                         value, source, state)
        return True
    if token.startswith(labels.CONNECTOR_COUNT_PREFIX):
        _emit_connector_count(facts, category, token[len(labels.CONNECTOR_COUNT_PREFIX):],
                              value, source)
        return True
    return False


# --------------------------------------------------------------------------
# Detail-spec rows (data/raw/detail/<vendor>.jsonl -> vendor_meta.detail_specs)
# --------------------------------------------------------------------------

_PROSE_KEYS = frozenset({
    "overview_text_raw", "overview", "description", "title", "name",
    "specs_table_raw", "image_url",
})


def _detail_rows(detail_specs):
    """(key, value) pairs from a list payload (vendor-specific row shapes)."""
    for row in detail_specs:
        if not isinstance(row, dict):
            continue
        key = row.get("key") or row.get("label") or row.get("name")
        value = row.get("value") or row.get("spec") or row.get("data")
        yield key, value


def _bluetooth_sweep(facts: dict, category: str, detail_specs) -> None:
    """Bluetooth version from any row of a board page.

    The version rides inside combined cells ("Wi-Fi 7, Bluetooth 5.3",
    "Wi-Fi 6 BT5.2") and in 1PC's one-row-per-claim keys ("Communication
    connections: Bluetooth 5.4 (unpaired)"), so the row KEY is searched too.
    A bare "Bluetooth" mention with no version is deliberately not a value.
    """
    if "bluetooth" in facts:
        return
    rows = (detail_specs.items() if isinstance(detail_specs, dict)
            else _detail_rows(detail_specs))
    for key, value in rows:
        for blob in (str(key or ""), str(value or "")):
            match = _BT_RE.search(blob) or _BT_SHORT_RE.search(blob)
            if match:
                _emit(facts, category, "bluetooth", f"Bluetooth {match.group(1)}",
                      SOURCE_DETAIL, 0.75)
                return


def parse_detail_specs(category: str | None, detail_specs,
                       gaps: dict[str, int] | None = None) -> dict[str, list[Fact]]:
    """Structured spec rows from a vendor product page.

    `gaps` (optional) counts the labels that mapped to no schema field, which
    is how the vocabulary in specs/labels.py grows from real vendor pages.
    """
    facts: dict[str, list[Fact]] = {}
    if not detail_specs:
        return facts
    cat = category or ""
    state: dict = {}

    rows = (detail_specs.items() if isinstance(detail_specs, dict)
            else _detail_rows(detail_specs))
    for key, value in rows:
        if str(key) == "הערות":
            if cat == "case":
                # The notes junk-drawer sometimes carries the one clearance
                # figure ("Max GPU Length ≤ 408mm", 130 rows) — the ONLY
                # thing ever read out of this label. Pattern-gated and lower
                # confidence than a dedicated row, so a real row still wins;
                # the label otherwise stays ignored as before.
                match = re.search(r"Max GPU Length\s*[≤<]?\s*(\d{2,4})\s*mm",
                                  str(value or ""), re.I)
                if match:
                    _emit(facts, cat, "max_gpu_length_mm", int(match.group(1)),
                          SOURCE_DETAIL, 0.7)
        if key is None or str(key) in _PROSE_KEYS or labels.is_ignored_label(key):
            continue
        if cat == "memory":
            _emit_memory_ecc(facts, cat, value, SOURCE_DETAIL)
        token = labels.translate_vendor_label(key, cat)
        if token is None:
            # Unknown Hebrew label: reported, never guessed at (the old code
            # passed it through as a key, where it silently mapped to nothing).
            _record_gap(gaps, key)
            continue
        if _apply_special(facts, cat, token, value, SOURCE_DETAIL, state):
            continue
        _emit_by_key(facts, cat, token, value, SOURCE_DETAIL, gaps=gaps)

    usb = state.get("usb")
    if usb and "usb_ports" not in facts:
        # Per-standard rear-port counts are one spec on the PDP, not four.
        summary = ", ".join(f"{standard} x{count}" for standard, count in usb.items())
        _emit(facts, cat, "usb_ports", summary, SOURCE_DETAIL, 0.75)

    if cat == "motherboard":
        _bluetooth_sweep(facts, cat, detail_specs)

    # Row-crossing arithmetic for the Oct 2026 coverage pass.
    # 0. Cooler sockets: one union regardless of how many rows printed them.
    sockets = state.get("sockets")
    if sockets:
        _emit(facts, cat, "sockets", sockets, SOURCE_DETAIL, 0.85)
    # 1. Slot rows: TMS prints one row per x16 variant (plain, x4-wired,
    #    x8-wired); the field is the total number of x16 slots, so the rows
    #    are summed rather than raced.
    for slot, field in (("x16", "pcie_x16_slots"), ("x4", "pcie_x4_slots"),
                        ("x1", "pcie_x1_slots")):
        total = state.get(f"slot_count_{slot}")
        if total:
            _emit(facts, cat, field, total, SOURCE_DETAIL, 0.75)
    # 2. AIO radiators: 'רדיאטורים: 3' means three 120mm fans, so the size
    #    class is the count x the printed fan size (240/360/420...).
    count = state.get("aio_radiator_count")
    size = state.get("aio_fan_size")
    if (cat in ("aio", "cooling_other") and count and size
            and size in (120, 140) and 1 <= count <= 4):
        _emit(facts, cat, "radiator_size_mm", int(count * size),
              SOURCE_DETAIL, 0.8)
    # 2b. The reverse division: a known radiator + fan size implies the fan
    #    count (360/120 = 3x120mm). Only exact divisions — odd fan/radiator
    #    pairings stay null rather than guessed.
    for fact in facts.get("radiator_size_mm", []):
        try:
            rad = int(float(str(fact.value).split()[0]))
        except (TypeError, ValueError):
            continue
        for fsize in facts.get("fan_size_mm", []):
            try:
                fansz = int(float(str(fsize.value).split()[0]))
            except (TypeError, ValueError):
                continue
            if (fansz in (120, 140) and rad % fansz == 0
                    and 1 <= rad // fansz <= 4):
                _emit(facts, cat, "fan_count", rad // fansz,
                      SOURCE_DETAIL, 0.7)
                break
        else:
            continue
        break
    # 2c. Case volume from full dimensions (W=220 H=486 D=467mm).
    #    Pure arithmetic on three validated numbers.
    dims = facts.get("dimensions_mm", [])
    if cat == "case" and dims:
        whd = re.findall(r"([WHD])=(\d+)", str(dims[0].value))
        axes = {axis: int(num) for axis, num in whd}
        if all(a in axes for a in "WHD"):
            _emit(facts, cat, "volume_l",
                  round(axes["W"] * axes["H"] * axes["D"] / 1e6, 1),
                  SOURCE_DETAIL, 0.8)
    return facts


# --------------------------------------------------------------------------
# vendor_meta scalars + Ivory cuts
# --------------------------------------------------------------------------


def parse_meta_scalars(category: str | None, meta) -> dict[str, list[Fact]]:
    """Scalar keys in the vendor payload (TMS/Ivory builder dicts)."""
    facts: dict[str, list[Fact]] = {}
    if not isinstance(meta, dict):
        return facts
    for key, value in meta.items():
        if key in ("detail_specs", "cuts", "tree", "description", "title",
                   "images", "image_url", "parent_id", "category_id"):
            continue
        if isinstance(value, (dict, list)) or value is None:
            continue
        _emit_by_key(facts, category or "", key, value, SOURCE_META, 0.8)
    return facts


def load_cut_labels() -> dict:
    """Ivory builder cut-id -> spec mapping (committed ground truth)."""
    global _LABELS_CACHE
    if _LABELS_CACHE is None:
        try:
            _LABELS_CACHE = json.loads(CUT_LABELS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LABELS_CACHE = {}
    return _LABELS_CACHE


def parse_cuts(category: str | None, cuts) -> dict[str, list[Fact]]:
    """Decode Ivory's opaque builder filter ids into schema fields."""
    facts: dict[str, list[Fact]] = {}
    if not isinstance(cuts, list):
        return facts
    labels = load_cut_labels().get("cuts") or {}
    for cut in cuts:
        mapping = labels.get(str(cut))
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            if is_promo_label(value):
                continue
            _emit_by_key(facts, category or "", key, value, SOURCE_CUTS, 0.8)
    return facts


# --------------------------------------------------------------------------
# Post-match bridge (matching.py computed attributes -> Tier 1 facts)
# --------------------------------------------------------------------------


def ingest_computed_attributes(category: str | None, attributes) -> dict[str, list[Fact]]:
    """Promote `attributes` keys computed outside the spec system.

    After this overhaul `attributes` is a *derived* view of `specs`
    (specs/legacy.py), so the only genuinely new information in it is what
    matching.py computes from the listing dict itself: canonical `brand`,
    `model`, `mpn`, `accessory_type` and the like. Those enter here as Tier-1
    facts so the same fact stops existing twice in two shapes.

    Idempotent: re-ingesting the legacy view yields identical values.
    """
    facts: dict[str, list[Fact]] = {}
    if not isinstance(attributes, dict):
        return facts
    for key, value in attributes.items():
        if value in (None, "", [], {}):
            continue
        field = schema.field_for_key(category or "", key)
        if field is None:
            continue
        if field.type == "list_str" and not isinstance(value, (list, tuple)):
            value = [value]
        _emit(facts, category or "", field.name, value, SOURCE_COMPUTED, 0.9)
    return facts


def parse_listing_identity(category: str | None, listing: dict) -> dict[str, list[Fact]]:
    """Listing-level identity fields matching.py maintains (mpn/brand)."""
    facts: dict[str, list[Fact]] = {}
    mpn = listing.get("mpn")
    if mpn:
        _emit(facts, category or "", "part_numbers", [str(mpn)], SOURCE_COMPUTED, 0.95)
    brand = listing.get("brand")
    if brand:
        _emit(facts, category or "", "manufacturer", brand, SOURCE_COMPUTED, 0.7)
    return facts


def parse_vendor_struct(category: str | None, listing: dict,
                        gaps: dict[str, int] | None = None) -> dict[str, list[Fact]]:
    """All Tier-1 facts for one listing."""
    meta = listing.get("vendor_meta") or {}
    facts = parse_detail_specs(category, meta.get("detail_specs"), gaps=gaps)
    for key, value in parse_meta_scalars(category, meta).items():
        facts.setdefault(key, []).extend(value)
    for key, value in parse_cuts(category, meta.get("cuts")).items():
        facts.setdefault(key, []).extend(value)
    return facts
