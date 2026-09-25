"""
specs/derive.py — deterministic facets derived from typed specs.

Three things live here:

1. UI facets that the site filters on but that are NOT specs in the sheet and
   are NOT worth storing per product: CPU `tier` ("Ryzen 7", "I5") and
   `generation` ("Ryzen 7000", "Gen 14", "Ultra Series"). They are pure
   functions of the CPU model number, so they are derived on demand instead of
   being scraped, merged and validated as if they were facts.
   (The retired extractors emitted both as attributes; matching.py's
   `normalize_cpu_legacy_attrs` consumed them, and the CPU filter rail offers
   them as checkboxes.)

2. Presentation formatting for the transitional `attributes` view
   (specs/legacy.py imports these helpers).

3. `infer_specs()` — fills SCHEMA fields from facts we can DERIVE with certainty,
   never from a guess about a specific SKU. The distinction matters: a rule that
   holds for a whole architecture or platform is a derivation ("every Zen 5 part
   is 4nm", "a tray CPU ships without a cooler"); "this model has 96MB of L3" is
   a per-SKU fact and stays null unless a real source supplies it. Inferred
   values are marked `derived:<rule>` and only ever fill nulls, so any real value from
   any tier always wins. It runs AFTER cross_check (build.py) so a rule can also
   answer for a field a consistency check just emptied.
"""

from __future__ import annotations

import re


def cpu_tier(model: str | None) -> str | None:
    """PCPP-style CPU tier/lineup from the model string."""
    text = str(model or "")
    match = re.search(r"\bRyzen\s?([3-9])\b", text, re.I)
    if match:
        return f"Ryzen {match.group(1)}"
    match = re.search(r"\b(Xeon)\s?([A-Z]{1,3})\b", text, re.I)
    if match:
        return f"Xeon {match.group(2).upper()}"
    match = re.search(r"\b(Ultra\s?\d|I[3579])\b", text, re.I)
    if match:
        return re.sub(r"\s+", "", match.group(1).upper())
    if re.search(r"\bThreadripper\b", text, re.I):
        return "Threadripper"
    if re.search(r"\bEPYC\b", text, re.I):
        return "EPYC"
    if re.search(r"\bCeleron\b", text, re.I):
        return "Celeron"
    if re.search(r"\bPentium\b", text, re.I):
        return "Pentium"
    return None


def cpu_generation(model: str | None) -> str | None:
    """Sibling-group label for a CPU model (Ryzen 7000 / Gen 14 / ...)."""
    text = str(model or "")
    match = re.search(r"\bRyzen\s?[3-9]\s?(?:PRO\s?)?(\d)\d{3}", text, re.I)
    if match:
        return f"Ryzen {match.group(1)}000"
    match = re.search(r"\bXeon\s?([A-Z]{1,3})\s?(\d{4})", text, re.I)
    if match:
        return f"Xeon Gen {int(match.group(2)[0])}"
    match = re.search(r"\bI[3579]\s?(\d{4,5})", text, re.I)
    if match:
        digits = re.sub(r"[^0-9]", "", match.group(1))
        generation = int(digits[:2]) if len(digits) >= 5 else int(digits[0])
        return f"Gen {generation}"
    match = re.search(r"\bThreadripper\s?(?:PRO\s?)?(\d)\d{3}", text, re.I)
    if match:
        return f"Threadripper {match.group(1)}000"
    if re.search(r"\bUltra\s?\d\s?\d{3}", text, re.I):
        # Ultra parts carry no numeric generation: the 3-digit model is not a
        # generation (reading "265" as "Gen 26" split one chip line into
        # Gen 22-28 before this was fixed).
        return "Ultra Series"
    return None


# ---------------------------------------------------------------------------
# Inference (rule-based fills) — plan §6 "fill_derived", extended
# ---------------------------------------------------------------------------

# microarchitecture -> (Intel codename, lithography nm, L2 MB per core).
# The node and the per-core L2 are architecture-wide facts (Vermeer and
# Cezanne are both Zen 3 / 7nm / 0.5MB-per-core), which is what makes them
# derivable while the L3 size is per-SKU.
_AMD_UARCH: dict[str, tuple[int, float]] = {
    "zen": (14, 0.5),
    "zen+": (12, 0.5),
    "zen 2": (7, 0.5),
    "zen 3": (7, 0.5),
    "zen 4": (5, 1.0),
    "zen 5": (4, 1.0),
}

_INTEL_UARCH: dict[str, tuple[str, int]] = {
    "sandy bridge": ("Sandy Bridge", 32),
    "ivy bridge": ("Ivy Bridge", 22),
    "haswell": ("Haswell", 22),
    "haswell refresh": ("Haswell", 22),
    "broadwell": ("Broadwell", 14),
    "skylake": ("Skylake", 14),
    "kaby lake": ("Kaby Lake", 14),
    "coffee lake": ("Coffee Lake", 14),
    "coffee lake refresh": ("Coffee Lake", 14),
    "comet lake": ("Comet Lake", 14),
    "rocket lake": ("Rocket Lake", 14),
    "ice lake": ("Ice Lake", 10),
    "tiger lake": ("Tiger Lake", 10),
    "alder lake": ("Alder Lake", 10),
    "raptor lake": ("Raptor Lake", 10),
    "raptor lake refresh": ("Raptor Lake", 10),
    "meteor lake": ("Meteor Lake", 7),
    "arrow lake": ("Arrow Lake", 3),
    "lunar lake": ("Lunar Lake", 3),
}

# Platform memory maximum by socket (GB). Consumer/desktop sockets only; a
# server or exotic socket is left alone rather than guessed.
_SOCKET_MAX_MEMORY_GB: dict[str, int] = {
    "AM4": 128, "AM5": 192, "LGA1155": 32, "LGA1151": 64,
    "LGA1200": 128, "LGA1700": 192, "LGA1851": 192, "LGA2066": 256,
}

# Unlocked-by-suffix Intel model tails (K/KF/KS desktop, X/XE HEDT).
_INTEL_UNLOCKED_SUFFIX = re.compile(r"\d{4,5}(K|KF|KS|X|XE)$", re.I)

# Ryzen/Threadripper generation (first digit of the 4-digit model) ->
# microarchitecture. A lineup fact: every Ryzen 7000 desktop part is Zen 4,
# every Ryzen 5000 part Zen 3. EPYC is NOT uniform this way (7002 is Zen 2,
# 7003 Zen 3), so server parts stay for a real source to answer.
_AMD_GEN_UARCH: dict[str, str] = {
    "1000": "Zen", "2000": "Zen+", "3000": "Zen 2", "4000": "Zen 2",
    "5000": "Zen 3", "7000": "Zen 4", "8000": "Zen 4", "9000": "Zen 5",
}

# Intel DESKTOP generation -> (codename, lithography nm). Mobile parts are
# deliberately excluded: 8th-gen U is Kaby Lake R and 10th-gen U is Ice Lake,
# so a generation number only pins the codename for desktop suffixes.
_INTEL_GEN_DESKTOP: dict[int, tuple[str, int]] = {
    6: ("Skylake", 14), 7: ("Kaby Lake", 14), 8: ("Coffee Lake", 14),
    9: ("Coffee Lake Refresh", 14), 10: ("Comet Lake", 14),
    11: ("Rocket Lake", 14), 12: ("Alder Lake", 10),
    13: ("Raptor Lake", 10), 14: ("Raptor Lake Refresh", 10),
}
_INTEL_MOBILE_SUFFIX = re.compile(r"\d{3,5}(?:U|H|HK|HS|HQ|Y|P|G\d)$", re.I)
_ULTRA_ARROW_LAKE = re.compile(r"\bUltra\s?[579]\s?2\d{2}(?![0-9])", re.I)
# AMD parts whose SMT is per-SKU (Ryzen 3 1200/2200G/3200G ship 4 cores/4
# threads while 3100/3300X/4100 ship 4/8), so they are never inferred.
_AMD_SMT_SERIES = re.compile(r"\bRyzen\s?[579]\b|\bThreadripper\b|\bEPYC\b", re.I)
_EPYC = re.compile(r"\bEPYC\b", re.I)

# APUs whose architecture contradicts their own series: the 2000-series
# 2200G/2400G are Zen (Raven Ridge), not Zen+, and the 3000-series 3200G/3400G
# are Zen+ (Picasso), not Zen 2. Model numbers beat series names here.
_AMD_APU_UARCH: dict[str, str] = {
    "200GE": "Zen", "220GE": "Zen", "240GE": "Zen", "3000G": "Zen",
    "2200G": "Zen", "2400G": "Zen",
    "3200G": "Zen+", "3400G": "Zen+",
}
# Laptop parts mix architectures inside one model number (7520U is Zen 2 in
# the 7000 series), so no microarchitecture is inferred for them.
_AMD_MOBILE_SUFFIX = re.compile(r"\d{3,4}(?:U|H|HS|HX|HQ|C)$", re.I)
_INTEL_PREFIX = re.compile(r"\bI[3579]\b|\bCore\b|\bUltra\b", re.I)
_AMD_PREFIX = re.compile(r"\bRyzen\b|\bThreadripper\b", re.I)
_ZEN_TOKEN = re.compile(r"^Zen\s?(\+|[1-5])?$", re.I)


def _amd_uarch(microarch: str | None) -> tuple[int, float] | None:
    return _AMD_UARCH.get(str(microarch or "").strip().lower())


def _intel_uarch(microarch: str | None) -> tuple[str, int] | None:
    return _INTEL_UARCH.get(str(microarch or "").strip().lower())


def cpu_series(model: str | None) -> str | None:
    """Product line from the model:"Ryzen 7 9800X3D" -> "Ryzen 7"."""
    text = str(model or "")
    if re.search(r"\bThreadripper\b", text, re.I):
        return "Ryzen Threadripper"
    match = re.search(r"\bRyzen\s?PRO\s?([3579])\b", text, re.I)
    if not match:
        match = re.search(r"\bRyzen\s?([3579])\b", text, re.I)
    if match:
        return f"Ryzen {match.group(1)}"
    match = re.search(r"\bCore\s?Ultra\s?([3579])\b", text, re.I)
    if match:
        return f"Core Ultra {match.group(1)}"
    match = re.search(r"\bI([3579])\b", text, re.I)
    if match:
        return f"Core i{match.group(1)}"
    match = re.search(
        r"\bXeon\s?(Gold|Silver|Bronze|Platinum|[A-Z]{1,3}\d{0,4})\b", text, re.I
    )
    if match:
        return f"Xeon {match.group(1).upper()}"
    for word in ("EPYC", "Threadripper", "Celeron", "Pentium"):
        if re.search(rf"\b{word}\b", text, re.I):
            return word
    return None


def _generation_number(model: str | None) -> int | None:
    """Generation as an integer, read off `cpu_generation`'s label.

    "Ryzen 7 9800X3D" -> 7, "i5-13600K" -> 13, "Ultra 7 265K" -> None (Ultra
    parts carry no numeric generation).
    """
    # Vendors hyphenate Intel models ("Core i5-13600K"); the generation regexes
    # want a space, so normalize the separator here.
    label = cpu_generation(re.sub(r"[-_]+", " ", str(model or ""))) or ""
    match = re.search(r"(\d+)000$", label)
    if match:
        return int(match.group(1))
    match = re.search(r"^Gen (\d+)$", label)
    if match:
        return int(match.group(1))
    return None


def zen_generation(value: str | None) -> str | None:
    """'Zen 4' -> '4', 'Zen+' -> '+', 'Zen' -> '1', anything else -> None.

    Used to compare two claims about the same part; a codename ("Raphael") and
    another vocabulary are not contradictions, so they return None.
    """
    match = _ZEN_TOKEN.match(str(value or "").strip())
    if not match:
        return None
    return match.group(1) or "1"


def expected_microarchitecture(model: str | None) -> str | None:
    """The microarchitecture a model number implies, or None when the lineup
    is genuinely mixed (mobile parts, EPYC, 4-core APUs).

    This is the one place that decides what a model number implies; inference
    fills from it and cross_check audits other sources against it.
    """
    text = str(model or "")
    if not text or _EPYC.search(text):
        return None
    for token, uarch in _AMD_APU_UARCH.items():
        if re.search(rf"\b{token}\b", text, re.I):
            return uarch
    if _AMD_PREFIX.search(text):
        if _AMD_MOBILE_SUFFIX.search(text):
            return None
        generation = _generation_number(text)
        return _AMD_GEN_UARCH.get(f"{generation}000") if generation else None
    if _INTEL_PREFIX.search(text):
        if _INTEL_MOBILE_SUFFIX.search(text):
            return None
        if _ULTRA_ARROW_LAKE.search(text):
            return "Arrow Lake"
        desktop = _INTEL_GEN_DESKTOP.get(_generation_number(text) or 0)
        return desktop[0] if desktop else None
    return None


def _infer_cpu(specs: dict, sources: dict) -> list[str]:
    """Rule-based fills for CPU fields. Returns the filled field names."""
    filled: list[str] = []
    model = specs.get("model")
    model_text = str(model or "")

    def fill(field: str, value, rule: str) -> None:
        if value in (None, "") or specs.get(field) is not None:
            return
        specs[field] = value
        sources[field] = f"derived:{rule}"
        filled.append(field)

    fill("series", cpu_series(model), "cpu.model_series")

    is_amd = bool(re.search(r"\bRyzen\b|\bThreadripper\b|\bEPYC\b", model_text, re.I))
    is_intel = bool(_INTEL_PREFIX.search(model_text))

    # -- microarchitecture, when no source supplied it ----------------------
    fill("microarchitecture", expected_microarchitecture(model),
         "cpu.model_microarchitecture")

    # Read it back: the fill above is itself a valid source for the
    # architecture-wide facts below (node, per-core L2).
    microarch = specs.get("microarchitecture")

    cores = specs.get("core_count")
    if is_amd:
        # SMT is all-or-nothing per lineup for Ryzen 5/7/9, Threadripper and
        # EPYC; Ryzen 3 mixes 4C/4T (3200G) with 4C/8T (3300X), so it is left
        # to a real source rather than assumed.
        if _AMD_SMT_SERIES.search(model_text):
            fill("smt", True, "cpu.lineup_smt")
            if isinstance(cores, int) and cores > 0:
                fill("thread_count", cores * 2, "cpu.smt_core_math")
        if re.search(r"\bRyzen\b|\bThreadripper\b", model_text, re.I):
            fill("unlocked", True, "cpu.amd_lineup_unlocked")
    elif is_intel and _INTEL_UNLOCKED_SUFFIX.search(re.sub(r"[^A-Za-z0-9]", "", model_text)):
        fill("unlocked", True, "cpu.intel_unlocked_suffix")

    amd_uarch = _amd_uarch(microarch)
    if is_amd and amd_uarch:
        fill("lithography_nm", amd_uarch[0], "cpu.architecture_node")
        if isinstance(cores, int) and cores > 0:
            l2 = cores * amd_uarch[1]
            fill("l2_cache_mb", int(l2) if float(l2).is_integer() else round(l2, 3),
                 "cpu.architecture_l2_math")

    intel_uarch = _intel_uarch(microarch)
    if intel_uarch and not is_amd:
        fill("core_family", intel_uarch[0], "cpu.architecture_family")
        fill("lithography_nm", intel_uarch[1], "cpu.architecture_node")

    # A tray CPU ships without a cooler by definition.
    if specs.get("packaging") == "tray":
        fill("includes_cooler", False, "cpu.tray_packaging")

    socket = str(specs.get("socket") or "").upper()

    # Desktop platform facts are safe only for model families with a
    # one-to-one socket relationship.  Mobile suffixes and EPYC are excluded;
    # no SKU-specific chipset or board compatibility is guessed here.
    if not socket and not _EPYC.search(model_text) and not _AMD_MOBILE_SUFFIX.search(model_text):
        generation = _generation_number(model)
        platform_socket = None
        if is_amd and not re.search(r"\bThreadripper\b", model_text, re.I) and generation in {1, 2, 3, 4, 5}:
            platform_socket = "AM4"
        elif is_amd and not re.search(r"\bThreadripper\b", model_text, re.I) and generation in {7, 8, 9}:
            platform_socket = "AM5"
        elif is_intel and generation in {6, 7, 8, 9}:
            platform_socket = "LGA1151"
        elif is_intel and generation in {10, 11}:
            platform_socket = "LGA1200"
        elif is_intel and generation in {12, 13, 14}:
            platform_socket = "LGA1700"
        fill("socket", platform_socket, "cpu.desktop_platform_socket")

    socket = str(specs.get("socket") or "").upper()
    fill("max_memory_gb", _SOCKET_MAX_MEMORY_GB.get(socket),
         "cpu.socket_memory_platform")

    return filled


def _infer_memory(specs: dict, sources: dict) -> list[str]:
    """Complete only unambiguous RAM kit arithmetic.

    A product may expose any two of count, per-module size and total size.
    Division must be exact; we never invent a kit layout from a single total.
    """
    filled: list[str] = []

    def fill(field: str, value, rule: str) -> None:
        if value in (None, "") or specs.get(field) is not None:
            return
        if not isinstance(value, int) or value <= 0:
            return
        specs[field] = value
        sources[field] = f"derived:{rule}"
        filled.append(field)

    count, size, total = (specs.get("module_count"), specs.get("module_size_gb"),
                          specs.get("total_gb"))
    if isinstance(count, int) and isinstance(size, int):
        fill("total_gb", count * size, "memory.module_arithmetic")
    elif isinstance(total, int) and isinstance(count, int) and count and total % count == 0:
        fill("module_size_gb", total // count, "memory.module_arithmetic")
    elif isinstance(total, int) and isinstance(size, int) and size and total % size == 0:
        fill("module_count", total // size, "memory.module_arithmetic")
    return filled


def _infer_storage(specs: dict, sources: dict) -> list[str]:
    """Storage fields that follow from the interface the drive already has.

    All of these are readings of one given spec, not new knowledge: a drive
    whose interface is "M.2 PCIe 4.0 x4" is an NVMe SSD on M.2 at gen 4.
    """
    filled: list[str] = []
    interface = str(specs.get("interface") or "")

    def fill(field: str, value, rule: str) -> None:
        if value in (None, "") or specs.get(field) is not None:
            return
        specs[field] = value
        sources[field] = f"derived:{rule}"
        filled.append(field)

    if not interface:
        return filled
    if re.search(r"\bnvme\b", interface, re.I) or re.search(r"pcie", interface, re.I):
        fill("nvme", True, "storage.interface_nvme")
        fill("type", "SSD", "storage.interface_ssd")
        if re.match(r"\s*m\.?2", interface, re.I):
            fill("form_factor", "M.2", "storage.interface_form_factor")
    generation = re.search(r"pcie\s?([345])(?:\.0)?\b", interface, re.I)
    if generation:
        fill("pcie_gen", int(generation.group(1)), "storage.interface_pcie_generation")
    return filled


def infer_specs(category: str | None, specs: dict, sources: dict) -> list[str]:
    """Fill nulls from derivable facts; never override a real value.

    Mutates `specs`/`sources` in place and returns the filled field names so the
    run can report how much of the sheet is derived rather than sourced.
    """
    if category == "cpu":
        return _infer_cpu(specs, sources)
    if category == "memory":
        return _infer_memory(specs, sources)
    if category == "storage":
        return _infer_storage(specs, sources)
    return []


def derived_extras(category: str | None, specs: dict) -> dict:
    """Legacy-only facets (not schema fields) for the transitional view."""
    extras: dict = {}
    if category == "cpu":
        tier = cpu_tier(specs.get("model"))
        generation = cpu_generation(specs.get("model"))
        if tier:
            extras["tier"] = tier
            extras["cpu_tier"] = tier
        if generation:
            extras["generation"] = generation
            extras["cpu_generation"] = generation
    return extras
