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

from .. import labels, schema
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
_KIT_RE = re.compile(r"(?i)(\d{1,2})\s*[x×*]\s*(\d{1,4})\s*gb")
_LENGTH_RE = re.compile(r"(?i)\bL\s*=\s*(\d+(?:[.,]\d+)?)")
_GPU_OUTPUTS = (("DisplayPort", "displayport", "dp_outputs"),
                ("HDMI", "hdmi", "hdmi_outputs"),
                ("DVI", "dvi", "dvi_outputs"))


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
    _emit(facts, category, "base_clock_ghz",
          float(numbers[0].replace(",", ".")), source, 0.8)
    _emit(facts, category, "boost_clock_ghz",
          float(numbers[1].replace(",", ".")), source, 0.8)


def _emit_cache_tier(facts: dict, category: str, value, source: str) -> None:
    """'L3 512MB' -> l3_cache_mb (the tier prefix is the only honest signal)."""
    text = str(value or "")
    tier = _TIER_RE.search(text)
    # The tier token itself carries a digit ("L3 512MB") — drop it before
    # reading the size, or every L2/L3 cache would ship as 2/3 MB.
    number = first_number(_TIER_RE.sub(" ", text))
    if number is None:
        return
    if tier and tier.group(1) == "2":
        _emit(facts, category, "l2_cache_mb", number, source, 0.85)
        return
    if tier and tier.group(1) == "3":
        _emit(facts, category, "l3_cache_mb", number, source, 0.85)
        return
    # No tier printed: only a category that HAS a plain cache_mb field (a
    # storage buffer) can take this without guessing which CPU cache it is.
    _emit(facts, category, "cache_mb", number, source, 0.8)


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
    category does not have (cooler vs case fan spell them differently)."""
    span = parse_range(value)
    if not span:
        return
    low, high = span
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
    """'VGA | DVI | DMS-59' -> dvi_outputs {'DVI': 1} (VGA has no field)."""
    tokens = [part.strip() for part in re.split(r"[|,;]", str(value or ""))
              if part.strip()]
    for display, needle, field in _GPU_OUTPUTS:
        count = sum(1 for token in tokens if needle in token.lower())
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
_BT_RE = re.compile(r"\bBluetooth\s*([\d.]+)\b", re.I)


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
    if not lan and not wifi:
        # Nothing recognized: keep the raw row so it is not silently lost.
        _emit(facts, category, "ethernet", text, source, 0.6)


def _emit_bluetooth_note(state: dict, value) -> None:
    """Record the Bluetooth version from a split connectivity row (evidence)."""
    match = _BT_RE.search(str(value or ""))
    if match:
        state["bluetooth"] = match.group(1)


def _apply_special(facts: dict, category: str, token: str, value, source: str,
                   state: dict) -> bool:
    """One vendor row that expands into several schema fields. True = handled."""
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
        if key is None or str(key) in _PROSE_KEYS or labels.is_ignored_label(key):
            continue
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
