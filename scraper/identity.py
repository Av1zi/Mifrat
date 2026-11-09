"""scraper/identity.py — one product per part.

The single source of truth for *what makes two listings the same physical
product*. Vendors describe the same part in their own words and their own
codes (TMS prints ``C245KFT``, yahav ``AT8076806414``, Ivory
``ULTRA-9-285K``), so the identity is built from the one thing every vendor
does publish — the manufacturer's model text — reduced to a canonical
**model code**, plus the **variant axes** that change the physical part.

Public surface (consumed by ``scraper/matching.py``):

``model_code(category, listing)``
    canonical code for the part, e.g. ``245kf``, ``trident-z5-rgb``.

``variant_axes(category)``
    the spec fields that change the physical part.

``variant_values(category, listing)``
    those fields, read out of the listing's ``attributes`` view and
    normalised so two vendors' spellings compare equal.

``variant_conflict(category, a, b)``
    two known-but-different axis values (never merge).

``variant_subgroups(category, listings)``
    cluster listings that agree on every known axis; an unknown value rides
    with whichever subgroup it does not contradict.

``part_number_class(value, listing=None)``
    ``"manufacturer"`` or ``"vendor"`` — is this a maker part number or a
    retailer's own catalogue code?

``part_number_subgroups(group)``
    split a group when it carries two *different* manufacturer part numbers
    (the same model sold in two variants), never on retailer codes.

Field names come from ``scraper/specs/schema.py``; this module only selects
the ones that matter for identity and normalises their values. Axis
semantics, uniformly applied:

- known vs known and different -> different products, never merged;
- known vs unknown             -> mergeable, the unknown side rides along;
- unknown vs unknown           -> mergeable.

The module is deliberately free of imports from ``matching`` so it can be
unit-checked on its own (``scripts/check_identity_merge.py``).
"""

from __future__ import annotations

import re

__all__ = [
    "IDENTITY_CATEGORIES",
    "model_code",
    "variant_axes",
    "variant_values",
    "variant_conflict",
    "variant_subgroups",
    "part_number_class",
    "part_number_subgroups",
    "part_number_key",
    "code_slug",
]

# --------------------------------------------------------------------------
# Category tables (plan §2.3). Real field names from specs/schema.py.
# --------------------------------------------------------------------------

#: The variant axes that change the physical part, per category. Categories
#: absent from this map do not participate in the identity tier and keep
#: today's MPN/SKU/singleton behaviour.
AXES: dict[str, tuple[str, ...]] = {
    "cpu": ("family", "packaging", "includes_cooler", "socket", "generation"),
    "memory": ("memory_type", "total_gb", "module_count", "speed_mhz",
               "cas_latency", "form_factor", "lighting", "color"),
    "gpu": ("chipset", "memory_gb", "memory_type", "color"),
    "motherboard": ("chipset", "form_factor", "wireless", "memory_type"),
    "storage": ("capacity_gb", "type", "interface", "form_factor",
                "pcie_gen", "rpm"),
    "case": ("type", "color", "rackmount"),
    "psu": ("wattage_w", "efficiency", "modular", "color"),
    "case_fan": ("size_mm", "quantity", "led", "color"),
    "aio": ("radiator_size_mm", "color", "lighting"),
    "cooler_air": ("height_mm", "fan_size_mm", "color", "lighting"),
}

IDENTITY_CATEGORIES = frozenset(AXES)

#: Axes whose values are written into the product id (a stable URL marker).
#: Everything else is part of the merge decision only — a socket or a
#: generation does not describe a separately-sold variant, so it must not
#: fragment the pid.
PID_AXES: dict[str, tuple[str, ...]] = {
    "cpu": ("packaging",),
    "memory": ("total_gb", "module_count", "speed_mhz", "cas_latency",
               "lighting", "color", "form_factor"),
    "gpu": ("memory_gb",),
    "motherboard": ("form_factor",),
    "storage": ("capacity_gb", "interface", "form_factor"),
    "case": ("color",),
    "psu": ("wattage_w", "modular", "color"),
    "case_fan": ("size_mm", "quantity", "led", "color"),
    "aio": ("radiator_size_mm", "color"),
    "cooler_air": ("height_mm", "fan_size_mm", "color"),
}

# --------------------------------------------------------------------------
# Small readers / normalisers
# --------------------------------------------------------------------------

_EMPTY = (None, "", [], {})


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def _attr(listing: dict, *keys):
    attrs = listing.get("attributes") or {}
    for key in keys:
        value = attrs.get(key)
        if value not in _EMPTY:
            return value
    return None


def _number(value) -> str | None:
    """First number in a vendor-formatted value ("2x16GB" -> 16, 750 -> 750)."""
    if value in _EMPTY:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:g}"
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    number = float(match.group(0))
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _bool(value) -> str | None:
    """Tri-state boolean as "yes"/"no", or None when the vendor said nothing."""
    if value in _EMPTY:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = _text(value).lower()
    if text in ("yes", "true", "1", "y"):
        return "yes"
    if text in ("no", "false", "0", "n", "none", "nein"):
        return "no"
    return "yes" if text else None


def _compact(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).lower())


_PACKAGING_BOX = ("box", "boxed", "retail", "ret")
_PACKAGING_TRAY = ("tray", "oem", "bulk", "blister")


def _packaging(value) -> str | None:
    text = _text(value).lower()
    if not text:
        return None
    if any(word in text for word in _PACKAGING_TRAY):
        return "tray"
    if any(word in text for word in _PACKAGING_BOX):
        return "box"
    return None


def _socket(value) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]+", "", _text(value).upper())
    if not text:
        return None
    if text.isdigit():
        return f"LGA{text}"
    return text


# Intel's lineup generation appears either in its own row ("Series 2",
# "דור 14") or inside the series tag ("... Series 2"). Only the marker is
# identity: "225" and "225 series 2" are different parts, "Core Ultra 5" and
# "Intel Core Ultra 5" are not.
_GENERATION_RE = re.compile(r"(?:series|gen(?:eration)?|דור)\s*[-:]?\s*(\d{1,2})",
                            re.I)


def _generation(listing: dict) -> str | None:
    for raw in (_attr(listing, "generation"), _attr(listing, "series")):
        match = _GENERATION_RE.search(_text(raw))
        if match:
            return f"g{int(match.group(1))}"
    return None


# --------------------------------------------------------------------------
# CPU model code (plan §2.2) — the reference implementation
# --------------------------------------------------------------------------

_CPU_FAMILY_RE = re.compile(
    r"\b(?:Ryzen\s+Threadripper(?:\s+PRO)?|Threadripper(?:\s+PRO)?"
    r"|Ryzen\s+AI\s+[3579]|Ryzen\s+[3579]|Core\s+Ultra\s+[3579]"
    r"|Core\s+i[3579]|EPYC|Xeon(?:\s+(?:Platinum|Gold|Silver|Bronze|W|Max))?"
    r"|Athlon(?:\s+(?:Gold|Silver|PRO))?|Pentium(?:\s+Gold)?|Celeron)\b",
    re.I,
)
_CPU_JUNK_RE = re.compile(
    r"\b(?:(?:gaming\s+)?processors?|series|tray|boxed?|retail|cpu"
    r"|desktop|graphics|radeon|unlocked|edition)\b",
    re.I,
)
_TRADEMARK_RE = re.compile(r"[®™©℗ªº]")
_CORE_RE = re.compile(r"(?<![a-z0-9])(\d{3,5})([a-z][a-z0-9]{0,4})?(?![a-z0-9])", re.I)
# Pentium/Celeron/Athlon print a letter before the number ("G2030", "G4400T");
# that letter is part of the model code, not a prefix to drop.
_G_CORE_RE = re.compile(r"(?<![a-z0-9])([a-z]\d{3,5})([a-z]{0,3})(?!\d)", re.I)

#: Suffix words vendors print with a space instead of attached to the code
#: ("245 K" / "9950 X3D" / "250K PLUS").
_SUFFIX_WORDS = frozenset({
    "k", "kf", "ks", "f", "x", "x3d", "x3d2", "g", "gt", "t", "e", "plus", "pro",
    "hx", "h", "u", "p", "c",
})


def _cpu_family(text: str) -> str | None:
    """Canonical family slug ("ultra5", "i7", "ryzen9", "threadripperpro").

    Vendor words are folded so the same lineup compares equal however it is
    printed: "Core Ultra 5" / "Ultra 5" -> ``ultra5``, "Core i7" -> ``i7``,
    "Ryzen Threadripper PRO" / "Threadripper PRO" -> ``threadripperpro``.
    """
    match = _CPU_FAMILY_RE.search(text)
    if not match:
        return None
    slug = "".join(re.sub(r"\s+", " ",
                          match.group(0)).lower().split())
    # "PRO" printed right after the lineup is part of the family: a Ryzen 5
    # PRO is a different part from a Ryzen 5.
    if re.match(r"\s+PRO\b", text[match.end():], re.I):
        slug += "pro"
    if slug.startswith("coreultra"):
        slug = "ultra" + slug[len("coreultra"):]
    elif slug.startswith("corei"):
        slug = "i" + slug[len("corei"):]
    elif slug.startswith("ryzenthreadripper"):
        slug = slug[len("ryzen"):]
    return slug or None


def cpu_model_code(brand, model) -> str | None:
    """``245kf`` from "Intel Core Ultra 5 245KF", "ULTRA-5-245KF", "245KF".

    The code is **core + full trailing letter cluster**: ``245k`` and
    ``245kf`` are two different parts and must never share a code. The family
    ("Core Ultra 5", "Ryzen 9") is an axis, not part of the code, so a vendor
    that prints only "245KF" still lands on the same product as one that
    prints the whole lineup.
    """
    text = _TRADEMARK_RE.sub(" ", _text(model))
    if brand:
        text = re.sub(rf"\b{re.escape(str(brand))}\b", " ", text, flags=re.I)
    text = _CPU_JUNK_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None

    family = _cpu_family(text)
    rest = _CPU_FAMILY_RE.sub(" ", text) if family else text
    rest = re.sub(r"[-_]+", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()

    match = _CORE_RE.search(rest)
    if match:
        core, attached = match.group(1), (match.group(2) or "").lower()
    else:
        match = _G_CORE_RE.search(rest)
        if not match:
            return None
        core, attached = match.group(1).lower(), match.group(2).lower()

    suffix = attached
    if not suffix:
        # "245 K" / "250K PLUS": the next word(s) may carry the suffix.
        tail = rest[match.end():].split()
        for word in tail[:2]:
            key = word.lower().strip("+")
            if key in _SUFFIX_WORDS:
                suffix += key
            else:
                break
    # "PLUS" is a real model suffix ("250K PLUS" != "250K"); keep it attached.
    suffix = re.sub(r"[^a-z0-9]", "", suffix)
    return f"{core}{suffix}"


# --------------------------------------------------------------------------
# Non-CPU model code
# --------------------------------------------------------------------------

# Words that carry no identity for a model code. Brand words are stripped
# separately (from the listing's own brand), because "ASUS ROG Strix B650"
# and "ROG Strix B650" are the same board.
_MODEL_NOISE = frozenset({
    "the", "and", "with", "for", "of", "edition", "version", "new", "gen",
})
_GENERIC_MODELS = frozenset({
    "none", "unknown", "n/a", "na", "no", "yes", "standard", "other", "oem",
    "retail", "box", "tray", "bulk", "default", "generic", "model",
})


def _brand_tokens(listing: dict) -> set[str]:
    tokens: set[str] = set()
    attrs = listing.get("attributes") or {}
    for raw in (listing.get("brand"), attrs.get("brand"),
                attrs.get("manufacturer")):
        text = _text(raw).lower()
        if not text:
            continue
        for part in re.split(r"[^a-z0-9]+", text):
            if len(part) >= 2:
                tokens.add(part)
    return tokens


def _model_code_from(listing: dict, raw) -> str | None:
    """Reduce one candidate model text to a stable code, or None."""
    text = _TRADEMARK_RE.sub(" ", _text(raw))
    text = re.sub(r"[\u0590-\u05FF]+", " ", text)
    if not text:
        return None
    if text.lower().strip() in _GENERIC_MODELS:
        return None

    brands = _brand_tokens(listing)
    tokens: list[str] = []
    for token in re.split(r"[^A-Za-z0-9]+", text):
        key = token.lower()
        if not key or key in brands or key in _MODEL_NOISE:
            continue
        tokens.append(key)
    if not tokens:
        return None

    compact = "".join(tokens)
    has_digit = any(ch.isdigit() for ch in compact)
    # Three-character codes are real when the brand is known ("A3W", "B4X");
    # without a brand they are too ambiguous to identify anything.
    if len(compact) < (3 if brands else 4):
        return None
    # One bare word with no digit is a series/family name, not a model.
    if len(tokens) == 1 and not has_digit:
        return None
    # A model row that is only a brand plus a generic word adds nothing.
    if compact in _GENERIC_MODELS:
        return None
    # Word order is vendor prose, not identity: "Dual RTX 5060 Ti OC GDDR7"
    # (KSP) and "Dual RTX 5060 Ti GDDR7 OC Edition" (TMS) name the same
    # card, but the token order differs and the bare strings compare unequal
    # — which the identity-tier union-find then reads as two models and
    # splits one product across two pids. Sorting makes the code a SET of
    # tokens, so any vendor's word order reduces to the same code.
    return "-".join(sorted(tokens))


def generic_model_code(listing: dict) -> str | None:
    """Model text reduced to a stable code (``o11-dynamic-evo``).

    Conservative on purpose: a single word with no digit ("DELTA", a memory
    series shared by fourteen kits) is not an identity, so it yields None and
    the listing stays on the MPN/SKU tiers.

    The model row wins; when the vendor publishes none, the title's model
    tokens are the last resort — the same fallback the CPU branch already
    uses, because KSP/Yahav routinely ship a title and no model row at all.
    """
    attrs = listing.get("attributes") or {}
    raw = (attrs.get("model") or listing.get("model")
           or attrs.get("product_name") or "")
    code = _model_code_from(listing, raw)
    if code:
        return code
    return _model_code_from(listing, listing.get("title_raw"))


def code_slug(code: str | None) -> str:
    """Filesystem/URL-safe form of a model code."""
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-",
                                        str(code or "").lower())).strip("-")


# --------------------------------------------------------------------------
# Public: model_code
# --------------------------------------------------------------------------

def model_code(category: str | None, listing: dict) -> str | None:
    """Canonical model code for one listing, or None when unknowable."""
    if category not in IDENTITY_CATEGORIES:
        return None
    if category == "cpu":
        attrs = listing.get("attributes") or {}
        brand = attrs.get("brand") or listing.get("brand")
        model = (attrs.get("model") or listing.get("model")
                 or listing.get("name"))
        code = cpu_model_code(brand, model)
        if code:
            return code
        # No usable model row: the title's model tokens are the last resort
        # (KSP's Hebrew title still prints "Intel Core Ultra 5 245KF").
        return cpu_model_code(brand, listing.get("title_raw"))
    return generic_model_code(listing)


# --------------------------------------------------------------------------
# Public: variant axes
# --------------------------------------------------------------------------

def variant_axes(category: str | None) -> tuple[str, ...]:
    return AXES.get(str(category or ""), ())


_STRING_AXES = frozenset({
    "memory_type", "type", "interface", "form_factor", "color", "chipset",
    "efficiency", "modular", "lighting", "led",
})
_BOOL_AXES = frozenset({"includes_cooler", "wireless", "rackmount"})
_NUMBER_AXES = frozenset({
    "total_gb", "module_count", "speed_mhz", "cas_latency", "memory_gb",
    "capacity_gb", "pcie_gen", "rpm", "wattage_w", "size_mm", "quantity",
    "radiator_size_mm", "height_mm", "fan_size_mm",
})


def _color(value) -> str | None:
    text = _compact(value)
    if not text:
        return None
    return {"gray": "grey"}.get(text, text)


def _interface(value) -> str | None:
    text = _compact(value)
    if not text:
        return None
    match = re.search(r"pcie(\d)", text)
    if match:
        return f"pcie{match.group(1)}"
    if "nvme" in text:
        return "nvme"
    if "sata" in text:
        return "sata"
    if "usb" in text:
        return "usb"
    return text


def _efficiency(value) -> str | None:
    text = _compact(value)
    if not text:
        return None
    for grade in ("titanium", "platinum", "gold", "silver", "bronze", "white"):
        if grade in text:
            return grade
    return text


def _lighting(value) -> str | None:
    """RGB presence is the variant; the exact LED count is not."""
    if value in _EMPTY:
        return None
    text = _text(value).lower()
    if text in ("no", "none", "non-rgb", "non rgb", "without", "false", "0"):
        return "no"
    return "yes"


_AXIS_ALIASES: dict[str, tuple[str, ...]] = {
    "total_gb": ("total_gb", "capacity_gb", "capacity", "kit", "memory"),
    "module_count": ("module_count", "modules", "modules_count"),
    "speed_mhz": ("speed_mhz", "speed_rating_mhz", "memory_speed_mhz"),
    "cas_latency": ("cas_latency", "cas", "cl"),
    "memory_gb": ("memory_gb", "vram_gb", "memory", "video_memory"),
    "capacity_gb": ("capacity_gb", "capacity", "drive_capacity"),
    "pcie_gen": ("pcie_gen",),
    "rpm": ("rpm", "spindle_speed"),
    "wattage_w": ("wattage_w", "wattage"),
    "size_mm": ("size_mm", "fan_size_mm", "size"),
    "quantity": ("quantity", "fans_per_pack", "pack"),
    "radiator_size_mm": ("radiator_size_mm", "supported_radiator_mm", "radiator_mm", "size"),
    "height_mm": ("height_mm", "cooler_height_mm"),
    "fan_size_mm": ("fan_size_mm", "fan_size"),
    "packaging": ("packaging", "box_type", "pack"),
    "includes_cooler": ("includes_cooler", "cooler_included", "cooler"),
    "socket": ("socket", "cpu_socket", "socket_type"),
    "family": ("family",),
    "generation": ("generation", "series"),
    "memory_type": ("memory_type", "ram_type", "memory_support", "vram_type", "gddr"),
    "chipset": ("chipset", "gpu_chip", "northbridge"),
    "form_factor": ("form_factor", "motherboard_form_factor", "board_form_factor",
                    "dimm_type", "drive_form_factor"),
    "wireless": ("wireless", "wifi", "wifi_standard"),
    "type": ("type", "drive_type", "case_type"),
    "interface": ("interface", "connection_interface"),
    "color": ("color", "colour"),
    "efficiency": ("efficiency", "efficiency_rating", "80plus"),
    "modular": ("modular", "modularity"),
    "lighting": ("lighting", "rgb_lighting"),
    "led": ("led", "lighting"),
    "rackmount": ("rackmount",),
}


def _family(listing: dict) -> str | None:
    """CPU lineup family ("coreultra5", "ryzen9"), vendor words stripped."""
    attrs = listing.get("attributes") or {}
    text = _text(attrs.get("model") or listing.get("model"))
    family = _cpu_family(_TRADEMARK_RE.sub(" ", text))
    if family:
        return family
    series = _text(attrs.get("series"))
    if not series:
        return None
    # "Intel Core Ultra 5 - 245KF" carries a model number: the family half is
    # still the family, but only when the tag has no digital core of its own.
    family = _cpu_family(series)
    if family:
        return family
    stripped = re.sub(r"[^A-Za-z0-9]+", "", series)
    if stripped and not any(ch.isdigit() for ch in stripped):
        return stripped.lower()
    return None


def _axis_value(category: str, axis: str, listing: dict) -> str | None:
    keys = _AXIS_ALIASES.get(axis, (axis,))
    raw = _attr(listing, *keys)

    if axis == "packaging":
        return _packaging(raw)
    if axis == "socket":
        return _socket(raw)
    if axis == "family":
        return _family(listing)
    if axis == "generation":
        return _generation(listing)
    if axis in _BOOL_AXES:
        return _bool(raw)
    if axis in _NUMBER_AXES:
        return _number(raw)
    if axis == "color":
        return _color(raw)
    if axis == "interface":
        return _interface(raw)
    if axis == "efficiency":
        return _efficiency(raw)
    if axis in ("lighting", "led"):
        return _lighting(raw)
    if axis == "modular":
        text = _compact(raw)
        if not text:
            return None
        if text in ("no", "none", "nonmodular", "false"):
            return "no"
        if text.startswith("semi"):
            return "semi"
        if text.startswith("full"):
            return "full"
        return text
    if axis == "rackmount":
        return _bool(raw)
    if axis in _STRING_AXES:
        text = _compact(raw)
        return text or None
    return _compact(raw) or None


def variant_values(category: str | None, listing: dict) -> dict[str, str | None]:
    """Every variant axis of one listing, normalised for comparison."""
    values: dict[str, str | None] = {}
    for axis in variant_axes(category):
        if axis == "family" and category != "cpu":
            continue
        try:
            values[axis] = _axis_value(str(category), axis, listing)
        except Exception:  # pragma: no cover - a bad value never breaks a build
            values[axis] = None
    return values


def variant_conflict(category: str | None, a: dict, b: dict) -> bool:
    """True when two listings state different values for one physical axis."""
    axes = variant_axes(category)
    if not axes:
        return False
    va = variant_values(category, a)
    vb = variant_values(category, b)
    for axis in axes:
        left, right = va.get(axis), vb.get(axis)
        if left is not None and right is not None and left != right:
            return True
    return False


def _listing_keys(listing: dict) -> set[str]:
    """Part-number keys a listing carries (MPN first, then its vendor SKU)."""
    keys: set[str] = set()
    for raw in (listing.get("mpn"), listing.get("vendor_sku")):
        key = part_number_key(raw)
        if key:
            keys.add(key)
    return keys


def _cluster(category: str | None, listings: list[dict], *,
            seeds: list[list[dict]] = (),
            skip: frozenset[str] = frozenset()) -> list[list[dict]]:
    """Greedy variant clustering on every axis except `skip`.

    `seeds` are clusters that are already known to be one product (each one
    carries a single manufacturer part number); they are never split, they
    only absorb listings that do not contradict them.
    """
    axes = tuple(a for a in variant_axes(category) if a not in skip)
    if not axes:
        groups = [list(seed) for seed in seeds]
        if groups:
            groups[0].extend(listings)
            return groups
        return [list(listings)]

    def _completeness(e: dict) -> tuple:
        values = variant_values(category, e)
        return (-sum(1 for axis in axes if values.get(axis) is not None),
                str(e.get("listing_key") or ""))

    clusters: list[list[dict]] = []
    cluster_values: list[dict[str, str]] = []

    def _values_of(members: list[dict]) -> dict[str, str]:
        values: dict[str, str] = {}
        for member in members:
            for axis, value in variant_values(category, member).items():
                if value is not None:
                    values.setdefault(axis, value)
        return values

    def _conflicts(known: dict[str, str], values: dict[str, str]) -> bool:
        return any(values.get(axis) is not None
                   and known.get(axis) is not None
                   and values[axis] != known[axis]
                   for axis in axes)

    # Seeds are atomic — one seed is one product — and two seeds merge only
    # when no axis contradicts. Two part numbers of one variant (the same
    # tray chip under Intel's and a retailer's code) belong together; two
    # part numbers of two variants (RGB vs non-RGB, box vs tray) do not.
    for seed in seeds:
        seed_values = _values_of(seed)
        target = None
        for index, known in enumerate(cluster_values):
            if not _conflicts(known, seed_values):
                target = index
                break
        if target is None:
            clusters.append(list(seed))
            cluster_values.append(seed_values)
        else:
            clusters[target].extend(seed)
            for axis in axes:
                if seed_values.get(axis) is not None:
                    cluster_values[target].setdefault(axis, seed_values[axis])

    for enriched in sorted(listings, key=_completeness):
        values = variant_values(category, enriched)
        candidates = [
            index for index, known in enumerate(cluster_values)
            if not _conflicts(known, values)
        ]
        if candidates:
            # Agreement on a part code beats the plain first-fit: a listing
            # whose vendor never prints packaging still lands beside the
            # listing that shares its SKU / part number.
            keys = _listing_keys(enriched)
            preferred = [
                index for index in candidates
                if keys & set().union(*(_listing_keys(e)
                                        for e in clusters[index]))
            ]
            target = (preferred or candidates)[0]
        else:
            clusters.append([])
            cluster_values.append({})
            target = len(clusters) - 1
        clusters[target].append(enriched)
        for axis in axes:
            if values.get(axis) is not None:
                cluster_values[target].setdefault(axis, values[axis])
    return clusters


def variant_subgroups(category: str | None,
                      listings: list[dict]) -> list[list[dict]]:
    """Cluster listings that agree on every *known* axis.

    Known-vs-unknown never splits: the unknown side rides with the subgroup
    it does not contradict.

    A **printed part number** is the strongest identity evidence there
    is, so it seeds the clusters: listings that carry the same one are one
    physical product even when the vendors' spec rows disagree (a wrong
    colour or wattage read is extraction noise, not a second SKU). Two
    *different* manufacturer part numbers therefore always stay apart, and
    the remaining listings are placed by axis agreement, then by shared part
    code. Order is deterministic, so a re-run produces the same clusters.
    """
    if len(listings) < 2 or not variant_axes(category):
        return [list(listings)]

    by_part_number: dict[str, list[dict]] = {}
    rest: list[dict] = []
    for enriched in listings:
        mpn = enriched.get("mpn")
        if mpn:
            by_part_number.setdefault(part_number_key(mpn), []).append(enriched)
        else:
            rest.append(enriched)

    if not by_part_number:
        return _cluster(category, listings)

    seeds = [by_part_number[key] for key in sorted(by_part_number)]
    return _cluster(category, rest, seeds=seeds)


# --------------------------------------------------------------------------
# Public: part-number classes (plan §2.4)
# --------------------------------------------------------------------------

# Retailers print their own catalogue codes beside the maker's part number.
# These shapes are retailer codes, never manufacturer part numbers:
#   TMS   C245KFT / C10105FB / C12700FT   (C + digits + packaging letter)
#   Ivory ULTRA-9-285K / ULTRA-5-250KFB
#   1PC / KSP / Yahav numeric database ids
_VENDOR_CODE_RES = (
    re.compile(r"^C\d{4,}[A-Z]{0,3}$"),
    re.compile(r"^ULTRA\d"),
    re.compile(r"^[A-Z]{0,3}\d{1,8}$"),        # bare numbers / "K340404"
)

# Manufacturer part-number prefixes worth naming explicitly. Everything else
# is decided by shape: a long alphanumeric code with letters and digits is a
# part number, a short one is a retailer's.
#
# GX/GZ/GB are Gigabyte board codes ("GX870MAORUSELITEWIFI7" is a 1PC listing
# whose board would otherwise classify as that retailer's own catalogue id
# and over-merge with the ICE white twin "...WIFI7I"); BK/BL are be quiet!
# cooler/fan maker codes (BK043, BL078 used as the listing's own SKU).
_MFR_PREFIXES = (
    "BX", "AT", "CM", "BB", "BC", "PK", "J", "SR",
    "GV", "GP", "GA", "90", "MB", "GX", "GZ", "GB", "BK", "BL",
    "100-", "1000", "KF", "HX", "CMK", "CMH", "MZ", "MZV", "CT", "F4",
    "WD", "ST", "RT", "WD",
)

_MANUFACTURER_MIN_LEN = 8


def part_number_key(value) -> str:
    """Compact comparison key for a part number."""
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if compact.startswith("GV") and len(compact) > 5:
        compact = compact[2:]
    return compact


def sku_part_number_key(vendor_sku, listing: dict | None = None) -> str | None:
    """The part number a vendor's catalogue code is standing in for, if any.

    Shops publish the maker's part number as their own SKU (TMS "GB760DS3HDDR4",
    1PC "90YV0MH6M0NA00"), and the identity tier never looked at it, so those
    listings sat as singletons next to the product they belong to. This is the
    classification these SKUs would get AS part numbers: maker-shaped codes and
    EAN-shaped barcodes bridge; the retailer's own ids (pure digits, TMS C-
    codes, ULTRA-prefixed) do not. It is the same test `part_number_subgroups`
    applies to a printed `mpn`, so a bridged SKU joins exactly the listings a
    printed copy of that code would.
    """
    key = part_number_key(vendor_sku)
    if not key or len(key) < 3:
        return None
    if key.isdigit():
        # A barcode (8/12-14 digits) names one part worldwide; a retailer id
        # is the retailer's own bookkeeping and names nothing here.
        return key if re.fullmatch(r"\d{8}|\d{12,14}", key) else None
    if not re.search(r"[A-Z]", key) or not re.search(r"\d", key):
        return None
    for pattern in _VENDOR_CODE_RES:
        if pattern.match(key):
            return None
    return key


def part_number_class(value, listing: dict | None = None) -> str | None:
    """``"manufacturer"``, ``"vendor"``, or None when there is no value.

    A *manufacturer* part number is the maker's own code and is identity
    evidence. A *vendor* code is the retailer's catalogue id and says nothing
    about the part. The distinction matters: two different manufacturer part
    numbers mean two variants of one model (do not merge), while two retailer
    codes are just two shops' bookkeeping (merge on the model code).
    """
    if value in _EMPTY:
        return None
    printed = _text(value)
    compact = re.sub(r"[^A-Za-z0-9]", "", printed)
    if len(compact) < 3:
        return None
    upper = compact.upper()

    if listing is not None:
        own_sku = re.sub(r"[^A-Za-z0-9]", "",
                         _text(listing.get("vendor_sku"))).upper()
        if own_sku and upper == own_sku:
            # The retailer's own code, unless it also matches a maker pattern
            # the makers really use (Intel "BX...", AMD "100-...").
            if not upper.startswith(_MFR_PREFIXES):
                return "vendor"

    if upper.isdigit():
        return "vendor"
    if not re.search(r"[A-Z]", upper) or not re.search(r"\d", upper):
        return None
    # A known maker prefix wins over the generic retailer shapes below:
    # a Gigabyte board code ("GX870...", "GZ890EAGLE") or a be quiet! fan
    # code ("BL078") is alphanumeric in exactly the shape the retailer
    # patterns catch, so without this order the maker code is read as the
    # retailer's own id and two different parts merge (audit R4).
    if upper.startswith(_MFR_PREFIXES):
        return "manufacturer"
    for pattern in _VENDOR_CODE_RES:
        if pattern.match(upper):
            return "vendor"
    if len(upper) >= _MANUFACTURER_MIN_LEN:
        return "manufacturer"
    return "vendor"


def part_number_subgroups(group: list[dict]) -> list[list[dict]]:
    """Split a group that carries two *different* manufacturer part numbers.

    Same manufacturer PN (in any spelling) is the strongest identity
    evidence, so those listings always merge. Two different manufacturer PNs
    mean two variants of the model (G.Skill's RGB ``...TZ5RK`` vs the
    non-RGB ``...TZ5RS``), so they must stay apart. Listings without a
    manufacturer PN cannot contradict anything and ride with the largest
    cluster (deterministic; ties resolve lexicographically).
    """
    if len(group) < 2:
        return [list(group)]

    clusters: dict[str, list[dict]] = {}
    unclassified: list[dict] = []
    for enriched in group:
        mpn = enriched.get("mpn")
        if part_number_class(mpn, enriched) == "manufacturer":
            clusters.setdefault(part_number_key(mpn), []).append(enriched)
        else:
            unclassified.append(enriched)

    if len(clusters) < 2:
        return [list(group)]

    order = sorted(clusters, key=lambda key: (-len(clusters[key]), key))
    clusters[order[0]].extend(unclassified)
    return [clusters[key] for key in order]
