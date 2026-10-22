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

   A derivation may also READ another derivation: storage's `nvme`/`type` follow
   from `interface`, and CPU's node/L2 follow from the microarchitecture the
   model number just implied. Each `_infer_*` helper re-reads the dict between
   steps for exactly that reason.
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
# server or exotic socket is left alone rather than guessed. AM5 and LGA1700
# are NOT one number: the maker states it per generation (below), and the old
# flat AM5=192 disagreed with 49 of 54 AMD product pages (backtest, Oct 2026).
_SOCKET_MAX_MEMORY_GB: dict[str, int] = {
    "AM4": 128, "LGA1155": 32, "LGA1151": 64,
    "LGA1200": 128, "LGA1851": 192, "LGA2066": 256,
}
# (socket, generation) -> maximum, as each maker's spec page prints it: AMD
# lists 128GB for Ryzen 7000 and 256GB for Ryzen 8000/9000; Intel lists 128GB
# for 12th gen and 192GB for 13th/14th gen on LGA1700.
_GENERATION_MAX_MEMORY_GB: dict[tuple[str, int], int] = {
    ("AM5", 7): 128, ("AM5", 8): 256, ("AM5", 9): 256,
    ("LGA1700", 12): 128, ("LGA1700", 13): 192, ("LGA1700", 14): 192,
}
# Ryzen 5 3500 / 3500X are the Ryzen 5 parts without SMT (6C/6T).
_AMD_NO_SMT_MODELS = re.compile(r"\bRyzen\s?5\s?3500X?\b", re.I)
# Ryzen 8000 desktop (Phoenix, 8300G-8700G and the F parts) is Zen 4 on 4nm,
# not the 5nm of the Raphael / Zen 4 desktop chiplets.
_AMD_PHOENIX_DESKTOP = re.compile(r"\bRyzen\s?[3579]\s?(?:PRO\s?)?8\d{2}0(?:G|GE|F)?\b", re.I)

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


def _box_cooler(model: str, packaging: str | None) -> bool | None:
    """Whether a retail box ships a cooler, for lineups where AMD / Intel state
    it for every SKU (their "Thermal solution (PIB)" spec row):

    - no cooler: every Threadripper and X3D part; AMD X-suffix Ryzen 7000/9000
      and 5700X/5800X/5900X/5950X; Intel K / KF / KS / X; EPYC and Xeon.
    - cooler: Ryzen 7000 non-X (7600/7700/7900), Ryzen 8000G and 8400F/8700F,
      Ryzen 5500/5600/5600G/5600X; Intel Core i3/i5/i7/i9 10th-14th gen non-K.

    Anything else (Ryzen 9000 non-X, Core Ultra non-K) stays unknown: the
    makers changed the bundle within those lineups. Only boxed or unstated
    packaging: tray is handled above.
    """
    if packaging not in (None, "boxed"):
        return None
    text = re.sub(r"[-_]+", " ", model)
    if re.search(r"\bThreadripper\b|\bEPYC\b|\bXeon\b|X3D", text, re.I):
        return False
    alnum = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    if re.search(r"\bRyzen\b", text, re.I):
        if re.search(r"\b[79]\d{2}0X\b", text, re.I) or re.search(
                r"\b5(?:700|800|900|950)X\b", text, re.I):
            return False
        if re.search(r"\b7[679]00\b(?!\s?X)", text, re.I) or re.search(
                r"\b8\d00(?:G|F)\b", text, re.I) or re.search(
                r"\b5(?:500|600|600G|600X)\b", text, re.I):
            return True
        return None
    if _INTEL_PREFIX.search(text) or re.search(r"\bCore\b", text, re.I):
        if re.search(r"\d{4,5}(?:K|KF|KS|X|XE)$", alnum) or re.search(
                r"\bUltra\b.*\d{3}KF?\b", text, re.I):
            return False
        if re.search(r"\bi[3579]\b", text, re.I) and (_generation_number(text) or 0) in range(10, 15):
            return True
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
        if _AMD_SMT_SERIES.search(model_text) and not _AMD_NO_SMT_MODELS.search(model_text):
            fill("smt", True, "cpu.lineup_smt")
            if isinstance(cores, int) and cores > 0:
                fill("thread_count", cores * 2, "cpu.smt_core_math")
        # PRO APUs are the locked exception (AMD: 5755G "Unlocked: No").
        if re.search(r"\bRyzen\b|\bThreadripper\b", model_text, re.I) and not re.search(
                r"\bPRO\s?\d{4}G", model_text, re.I):
            fill("unlocked", True, "cpu.amd_lineup_unlocked")
    elif is_intel and _INTEL_UNLOCKED_SUFFIX.search(re.sub(r"[^A-Za-z0-9]", "", model_text)):
        fill("unlocked", True, "cpu.intel_unlocked_suffix")

    amd_uarch = _amd_uarch(microarch)
    if is_amd and amd_uarch:
        node = 4 if _AMD_PHOENIX_DESKTOP.search(model_text) else amd_uarch[0]
        fill("lithography_nm", node, "cpu.architecture_node")
        if isinstance(cores, int) and cores > 0:
            l2 = cores * amd_uarch[1]
            fill("l2_cache_mb", int(l2) if float(l2).is_integer() else round(l2, 3),
                 "cpu.architecture_l2_math")

    intel_uarch = _intel_uarch(microarch)
    if intel_uarch and not is_amd:
        fill("core_family", intel_uarch[0], "cpu.architecture_family")
        fill("lithography_nm", intel_uarch[1], "cpu.architecture_node")

    # SMT from the core/thread arithmetic, when the vendor printed counts
    # but no SMT flag. 2 threads/core IS SMT on x86; a hybrid part can
    # never land exactly on 2x (P-cores take 2 threads each, E-cores 1,
    # so 2P+E != 2(P+E) whenever E > 0); threads == cores is a part
    # without it. Hybrid 10C/16T shapes match neither and stay null.
    threads = specs.get("thread_count")
    model_alnum = re.sub(r"[^A-Za-z0-9]", "", model_text).upper()
    if isinstance(cores, int) and isinstance(threads, int) and cores > 0:
        if threads == cores:
            fill("smt", False, "cpu.thread_math_no_smt")
        elif threads == 2 * cores:
            fill("smt", True, "cpu.thread_math_smt")
    if re.search(r"\bCore\s?(i[3579]|Ultra\s?[3579])\b", model_text, re.I):
        # Every desktop Core 12th-14th gen ships Hyper-Threading (the
        # E-cores never take it away: T/S/F power and KS bins keep HT;
        # HX rides along as desktop silicon in BGA, all of it HT).
        # Mobile tails stay out — a generation number never pinned those.
        if (not _INTEL_MOBILE_SUFFIX.search(model_alnum)
                and _generation_number(model_text) in (12, 13, 14)):
            fill("smt", True, "cpu.intel_gen_ht")
        # Arrow Lake dropped SMT from the architecture itself (Lion Cove
        # / Skymont have no Hyper-Threading on any SKU), so a desktop
        # Ultra 200 part is False by definition, counts or no counts.
        if (_ULTRA_ARROW_LAKE.search(model_text)
                and not _INTEL_MOBILE_SUFFIX.search(model_alnum)):
            fill("smt", False, "cpu.arrow_lake_no_ht")

    # No SMT means one thread per core: the thread count is the core count.
    if specs.get("smt") is False and isinstance(cores, int) and cores > 0:
        fill("thread_count", cores, "cpu.no_smt_threads_equal_cores")

    # AMD's family facet is the Zen generation itself (there is no
    # separate lake-style codename in the data): "Zen 4" microarch means
    # "Zen 4" family. EPYC/mobile stay out — their microarch is None.
    if _ZEN_TOKEN.match(str(microarch or "").strip()):
        fill("core_family", str(microarch).strip(), "cpu.amd_family_is_uarch")

    # Multiplier lock from the model suffix, when no source printed it.
    # Server parts are locked (EPYC, Xeon — except workstation W...X,
    # which Intel ships unlocked); Intel client is unlocked only on
    # K/KF/KS/X/XE/HX/HK tails; the whole FX line is unlocked, A-series
    # only on a K tail. Anything unparseable (order codes like BX807...,
    # bare "Pentium G2030" is covered, opaque tray codes are not) stays
    # null rather than guessed.
    brand = str(specs.get("manufacturer") or "")
    if _EPYC.search(model_text):
        fill("unlocked", False, "cpu.server_locked")
        # Every EPYC supports ECC memory (server platform requirement).
        fill("ecc_support", True, "cpu.epyc_ecc")
    elif re.search(r"\bXeon\b", model_text, re.I):
        if re.search(r"\bW[\d\s]*\dX\b", model_text, re.I):
            fill("unlocked", True, "cpu.xeon_w_x_unlocked")
        else:
            fill("unlocked", False, "cpu.server_locked")
        # Every Xeon supports ECC memory (server platform requirement).
        fill("ecc_support", True, "cpu.xeon_ecc")
    elif re.search(r"\bFX\b", model_text):
        fill("unlocked", True, "cpu.fx_line_unlocked")
    elif re.search(r"\bA\d+\b", model_text) and not _AMD_PREFIX.search(model_text):
        if re.search(r"K$", model_alnum):
            fill("unlocked", True, "cpu.a_series_k_unlocked")
        else:
            fill("unlocked", False, "cpu.a_series_locked")
    elif brand == "Intel" or _INTEL_PREFIX.search(model_text):
        if _INTEL_UNLOCKED_SUFFIX.search(model_alnum) or re.search(
                r"(HX|HK)$", model_alnum):
            fill("unlocked", True, "cpu.intel_suffix_unlocked")
        elif re.search(r"\b(Celeron|Pentium|Atom)\b", model_text, re.I):
            fill("unlocked", False, "cpu.value_line_locked")
        elif re.search(r"\b(Core|Ultra)\b", model_text, re.I):
            fill("unlocked", False, "cpu.intel_locked_suffix")


    # A tray CPU ships without a cooler by definition.
    if specs.get("packaging") == "tray":
        fill("includes_cooler", False, "cpu.tray_packaging")
    fill("includes_cooler", _box_cooler(model_text, specs.get("packaging")),
         "cpu.lineup_box_cooler")

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
    generation = _generation_number(model)
    fill("max_memory_gb", _SOCKET_MAX_MEMORY_GB.get(socket)
         or _GENERATION_MAX_MEMORY_GB.get((socket, generation or 0)),
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
    # A spinning disk is never NVMe, and neither is a drive whose only bus is
    # SATA (NVMe is a PCIe protocol). USB enclosures stay unknown: the drive
    # inside may be either.
    if specs.get("type") == "HDD" or (
            re.search(r"\bsata\b", interface, re.I)
            and not re.search(r"nvme|pcie|usb|thunderbolt", interface, re.I)):
        filled += _fill(specs, sources, "nvme", False, "storage.sata_or_hdd_not_nvme")
    if not interface:
        return filled
    if re.search(r"\bnvme\b", interface, re.I) or re.search(r"pcie", interface, re.I):
        filled += _fill(specs, sources, "nvme", True, "storage.interface_nvme")
        filled += _fill(specs, sources, "type", "SSD", "storage.interface_ssd")
        if re.match(r"\s*m\.?2", interface, re.I):
            filled += _fill(specs, sources, "form_factor", "M.2",
                            "storage.interface_form_factor")
    generation = re.search(r"pcie\s?([345])(?:\.0)?\b", interface, re.I)
    if generation:
        filled += _fill(specs, sources, "pcie_gen", int(generation.group(1)),
                        "storage.interface_pcie_generation")
    return filled


# Chip-name prefixes that name their maker. This is chip-LINE knowledge, not
# per-SKU knowledge: every "GeForce …" is NVIDIA silicon, whoever sells the
# card (the board partner is already in `manufacturer`).
_GPU_CHIP_MAKERS = (
    (re.compile(r"^geforce\b|^rtx\b|^gtx\b|^quadro\b|^tesla\b", re.I), "NVIDIA"),
    (re.compile(r"^radeon\b|^rx\b|^firepro\b|^firegl\b|^vega\b", re.I), "AMD"),
    (re.compile(r"^arc\b|^iris\b", re.I), "Intel"),
)


def _infer_gpu(specs: dict, sources: dict) -> list[str]:
    """The GPU field that follows from the chip name it already carries."""
    filled: list[str] = []
    filled.extend(_fill(specs, sources, "chip_manufacturer",
                        _gpu_chip_maker(specs.get("chipset")),
                        "gpu.chipset_maker"))
    return filled


def _gpu_chip_maker(chipset) -> str | None:
    text = str(chipset or "").strip()
    if not text:
        return None
    for pattern, maker in _GPU_CHIP_MAKERS:
        if pattern.search(text):
            return maker
    return None


def _fill(specs: dict, sources: dict, field: str, value, rule: str) -> list[str]:
    """Fill one null from a derivation (used by the storage/GPU helpers)."""
    if value in (None, "") or specs.get(field) is not None:
        return []
    specs[field] = value
    sources[field] = f"derived:{rule}"
    return [field]


# --------------------------------------------------------------------------
# Table-driven and rule-driven fills (plan Phase 1c). Every one only fills a
# null and tags `derived:<rule>`.
# --------------------------------------------------------------------------


def _table_fill(specs: dict, sources: dict, row: dict | None, rule: str) -> list[str]:
    filled: list[str] = []
    row = row or {}
    for field, allowed in (row.get("_requires") or {}).items():
        if specs.get(field) not in allowed:
            return filled
    for field, value in row.items():
        if field.startswith("_"):
            continue
        filled += _fill(specs, sources, field, value, rule)
    return filled


def cpu_table_key(specs: dict) -> str | None:
    """'amd:7800X3D' / 'intel:14400F' for tables/cpu_models.json, else None.

    The token is the model number with its suffix. A bare 3-digit token only
    counts for Core Ultra (225/245/265/285): "225" on its own is not a CPU.
    """
    text = str(specs.get("model") or "")
    maker = str(specs.get("manufacturer") or "").upper()
    is_amd = bool(re.search(r"\bRyzen\b|\bThreadripper\b", text, re.I))
    is_intel = bool(re.search(r"\bCore\b|\bUltra\b|\bPentium\b|\bi[3579]\b", text, re.I))
    if is_amd and not is_intel:
        match = (re.search(r"\b(?:Ryzen(?:\s*[3579])?|Threadripper)(?:\s*PRO)?[\s-]*(\d{4}[A-Z0-9]*)\b",
                           text, re.I)
                 or re.search(r"^\s*(\d{4}[A-Z0-9]*)\b", text))
        return f"amd:{match.group(1).upper()}" if match else None
    if is_amd is False and maker == "AMD":
        match = re.search(r"^\s*(\d{4}[A-Z0-9]*)\b", text)
        return f"amd:{match.group(1).upper()}" if match else None
    if is_intel:
        match = re.search(r"\bUltra\s*[3579]\s*(\d{3}[A-Z]{0,2})\b", text, re.I)
        if match:
            return f"intel:{match.group(1).upper()}"
        match = re.search(r"^\s*(\d{3}[A-Z]{0,2})\b.*\bUltra\b", text, re.I)
        if match:
            return f"intel:{match.group(1).upper()}"
        match = re.search(r"\bPentium\s+(G\d{4})\b", text, re.I)
        if match:
            return f"intel:{match.group(1).upper()}"
        match = (re.search(r"\b(?:i[3579]|Core)[\s-]+(\d{4,5}[A-Z]{0,2})\b", text, re.I)
                 or re.search(r"^\s*(\d{4,5}[A-Z]{0,2})\b", text))
        if match:
            return f"intel:{match.group(1).upper()}"
    return None


def cpu_family(specs: dict) -> str | None:
    """The family label tables/mb_cpu_support.json uses for this CPU, or None.

    'Ryzen 7 9700X' -> 'AMD Ryzen 9000', 'Ryzen 5 3400G' -> 'AMD Ryzen 3000G'
    (AMD lists 2000/3000 APUs separately on AM4), 'Core i5 14400' ->
    'Intel Core 14th Gen', 'Core Ultra 5 225' -> 'Intel Core Ultra 200S
    (Series 2)'. Threadripper/EPYC/Athlon: None (the table has no rows).
    """
    key = cpu_table_key(specs)
    if not key:
        return None
    maker, token = key.split(":", 1)
    model = str(specs.get("model") or "")
    if maker == "amd":
        if re.search(r"Threadripper|EPYC|Athlon", model, re.I):
            return None
        match = re.match(r"([1-9])\d{3}([A-Z0-9]*)$", token)
        if not match:
            return None
        series, suffix = match.group(1), match.group(2)
        apu = suffix.startswith("G") and series in ("2", "3")
        return f"AMD Ryzen {series}000{'G' if apu else ''}"
    if re.search(r"\bUltra\b", model, re.I) and re.fullmatch(r"2\d{2}[A-Z]{0,2}", token):
        return "Intel Core Ultra 200S (Series 2)"
    match = re.fullmatch(r"(1\d|[6-9])\d{3}[A-Z]{0,2}", token)
    if match:
        gen = int(match.group(1))
        return f"Intel Core {gen}th Gen"
    return None


def _infer_cpu_chipsets(specs: dict, sources: dict) -> list[str]:
    """chipset_support = every chipset whose official list names this family."""
    from .tables import load

    family = cpu_family(specs)
    if not family:
        return []
    vendor = family.split()[0]
    chipsets = [f"{vendor} {chipset}" for chipset, row in sorted(load("mb_cpu_support").items())
                if family in (row.get("_families") or [])]
    if not chipsets:
        return []
    return _fill(specs, sources, "chipset_support", chipsets, "cpu.chipset_cpu_table")


def _infer_cpu_table(specs: dict, sources: dict) -> list[str]:
    from .tables import load

    key = cpu_table_key(specs)
    row = load("cpu_models").get(key) if key else None
    filled = _table_fill(specs, sources, row, "cpu.model_table")
    filled += _infer_cpu_chipsets(specs, sources)

    model = str(specs.get("model") or "")
    # ECC: a lineup-wide platform fact (vendor-published per family).
    if re.search(r"\bThreadripper\b", model, re.I):
        filled += _fill(specs, sources, "ecc_support", True, "cpu.threadripper_ecc")
    elif re.search(r"\bRyzen\b", model, re.I):
        # Desktop Ryzen takes unbuffered ECC on AM4/AM5; consumer APUs
        # (G/GE/GT without PRO) do not, PRO APUs do.
        if re.search(r"\bPRO\b", model, re.I):
            filled += _fill(specs, sources, "ecc_support", True, "cpu.ryzen_pro_ecc")
        elif re.search(r"\b[2-5]\d{3}(?:G|GE|GT)\b", model, re.I):
            # Only through Ryzen 5000: AMD lists ECC for the 8000G APUs.
            filled += _fill(specs, sources, "ecc_support", False, "cpu.ryzen_apu_no_ecc")
        elif str(specs.get("socket") or "") in ("AM4", "AM5") and re.search(r"\b\d{4}", model):
            filled += _fill(specs, sources, "ecc_support", True, "cpu.ryzen_desktop_ecc")
    elif re.search(r"\bCore\s?i[579]\b|\bi[579]\b", model, re.I):
        filled += _fill(specs, sources, "ecc_support", False, "cpu.intel_core_i5_i9_no_ecc")
    elif re.search(r"\bCore\s?i3\b|\bi3\b|\bPentium\b|\bCeleron\b", model, re.I):
        filled += _fill(specs, sources, "ecc_support", True, "cpu.intel_i3_pentium_ecc")
    return filled


def _infer_gpu_table(specs: dict, sources: dict) -> list[str]:
    from .tables import load

    key = str(specs.get("chipset") or "").strip()
    if not key:
        return []
    rows = load("gpu_chipsets")
    row = rows.get(key)
    if row is None:
        row = {k.lower(): v for k, v in rows.items()}.get(key.lower())
    return _table_fill(specs, sources, row, "gpu.chipset_table")


_GPU_LIQUID_MENTION = re.compile(r"waterforce|hybrid|liquid|water\s?block|aio\b|קירור\s?נוזלי",
                                 re.I)


def _infer_gpu_board_line(specs: dict, sources: dict, context: dict | None) -> list[str]:
    """fan_count from tables/gpu_board_lines.json: the board partner's line
    name fixes it (ASUS Dual = 2, MSI VENTUS 3X = 3, Gigabyte WF3 = 3).

    Read off every title and part number of the product; a row only applies to
    its brands (and chips, for lines that change with the chip), and when rows
    with different counts match, nothing is filled."""
    from .tables import load

    if specs.get("fan_count") is not None:
        return []
    title = str((context or {}).get("title") or "")
    if not title or _GPU_LIQUID_MENTION.search(title):
        return []
    haystack = " ".join([title, *map(str, specs.get("part_numbers") or [])])
    brand = str(specs.get("manufacturer") or "").lower()
    chip = str(specs.get("chipset") or "").lower()
    counts = set()
    for row in load("gpu_board_lines").values():
        brands = [b.lower() for b in row.get("brands") or []]
        if "*" not in brands and brand not in brands:
            continue
        chips = [c.lower() for c in row.get("chips") or []]
        if chips and chip not in chips:
            continue
        if re.search(row["pattern"], haystack, re.I):
            counts.add(int(row["fan_count"]))
    if len(counts) != 1:
        return []
    return _fill(specs, sources, "fan_count", counts.pop(), "gpu.board_line_table")


def _infer_gpu_extras(specs: dict, sources: dict, context: dict | None = None) -> list[str]:
    fans = specs.get("fan_count")
    # A hybrid card (AORUS XTREME WATERFORCE) has radiator fans too.
    if _GPU_LIQUID_MENTION.search(str((context or {}).get("title") or "")):
        return []
    if isinstance(fans, int) and fans > 0:
        return _fill(specs, sources, "cooling", "Air", "gpu.fans_mean_air")
    return []


_INTEL_CONSUMER_PCH = re.compile(r"^[HBZ]\d{2,3}$")
_WIFI_MENTION = re.compile(r"wi-?fi|wlan|wireless|אלחוט|bluetooth|\bbt\s?\d", re.I)
_THUNDERBOLT_MENTION = re.compile(r"thunderbolt|\btb[345]\b|usb\s?4\b", re.I)


# Tiers the chipset table may replace for cpu_support (see below).
_RETAILER_TIERS = ("vendor", "title", "weak")


def _infer_mb_cpu_support(specs: dict, sources: dict) -> list[str]:
    """cpu_support from tables/mb_cpu_support.json (chipset -> CPU families).

    The one table rule that may REPLACE a sourced value: retailers print CPU
    support as free prose that is routinely incomplete (Ivory's B550 rows
    said only "Ryzen 3000"), while the table is AMD's / Intel's own list for
    the chipset. Overrides and manufacturer pages still win. Built by
    scripts/build_mb_cpu_support.py.
    """
    from .tables import load

    chipset = str(specs.get("chipset") or "").strip().upper()
    row = load("mb_cpu_support").get(chipset) if chipset else None
    value = (row or {}).get("cpu_support")
    if not value:
        return []
    current = sources.get("cpu_support")
    if specs.get("cpu_support") is not None and current not in _RETAILER_TIERS:
        return []
    if specs.get("cpu_support") == value:
        return []
    specs["cpu_support"] = value
    sources["cpu_support"] = "derived:motherboard.chipset_cpu_table"
    return ["cpu_support"]


def _infer_motherboard(specs: dict, sources: dict, context: dict | None) -> list[str]:
    filled: list[str] = _infer_mb_cpu_support(specs, sources)
    chipset = str(specs.get("chipset") or "").upper()
    socket = str(specs.get("socket") or "").upper()
    if _INTEL_CONSUMER_PCH.match(chipset) and (socket.startswith("LGA") or not socket):
        # Intel enables ECC only on W/C/Q-series PCHs; the H/B/Z desktop line
        # does not support it (a board vendor cannot add it back).
        filled += _fill(specs, sources, "ecc_support", False,
                        "motherboard.intel_consumer_pch_no_ecc")

    if specs.get("form_factor") == "Mini-ITX" and re.match(r"(LGA|AM|FM)\d", socket):
        # The Mini-ITX specification defines exactly one expansion slot, and
        # every socketed desktop board in the catalog that states a count
        # (22/22) lists one x16 slot.
        filled += _fill(specs, sources, "pcie_x16_slots", 1,
                        "motherboard.mini_itx_single_slot")
        if specs.get("pcie_x16_slots") == 1:
            # ... and that one slot is the x16 slot: no x1 / x4 slot beside it.
            for field in ("pcie_x1_slots", "pcie_x4_slots"):
                filled += _fill(specs, sources, field, 0, "motherboard.mini_itx_single_slot")

    text = (context or {}).get("text", "")
    if text and (context or {}).get("detail_rows", 0) >= 8:
        # Absence from a FULL spec table and the title. Validated on the
        # catalog: every board that has Wi-Fi / Thunderbolt mentions it in its
        # title, a row key or a row value (473/473 and 74/74), so a rich page
        # that never says it is a board without it.
        if not _WIFI_MENTION.search(text):
            filled += _fill(specs, sources, "wireless", "No",
                            "motherboard.no_wifi_in_rich_table")
        if not _THUNDERBOLT_MENTION.search(text):
            filled += _fill(specs, sources, "thunderbolt_ports", 0,
                            "motherboard.no_thunderbolt_in_rich_table")
        filled += _no_lighting(specs, sources, context, "motherboard.no_lighting_mention")
    if specs.get("wireless") == "No":
        # Bluetooth rides on the same M.2 Key-E combo card as the Wi-Fi radio.
        filled += _fill(specs, sources, "bluetooth", "No", "motherboard.no_wifi_no_bluetooth")
    return filled


_LAPTOP_MARKER = re.compile(r"so-?dimm|laptop|notebook|נייד|לפטופ|camm|sodimm", re.I)
_SERVER_MEMORY_MARKER = re.compile(
    r"\becc\b|\breg(?:istered)?\b|\brdimm\b|\blrdimm\b|buffered|server|שרת", re.I)
_NAS_MEMORY_BRANDS = frozenset({"synology", "qnap"})


def _infer_memory_text(specs: dict, sources: dict, context: dict | None) -> list[str]:
    """Memory facts the titles prove by ABSENCE of a marker.

    Validated on the catalog: all 26 SO-DIMM kits announce it (title, row key
    or row value), as do all 25 ECC / 24 registered kits; none of the 67
    desktop DIMM kits carry a laptop marker. Retailers must label laptop and
    server memory, so an unmarked kit with a known DDR generation is desktop,
    unbuffered, non-ECC. NAS brands (Synology/QNAP sell SO-DIMM ECC) are
    excluded.
    """
    filled: list[str] = []
    text = (context or {}).get("text", "")
    brand = str(specs.get("manufacturer") or "").lower()
    if specs.get("lighting") in ("RGB", "ARGB"):
        filled += _fill(specs, sources, "heat_spreader", True, "memory.rgb_kit_has_spreader")
    if not text or not specs.get("memory_type") or brand in _NAS_MEMORY_BRANDS:
        return filled
    if not _LAPTOP_MARKER.search(text):
        filled += _fill(specs, sources, "form_factor", "DIMM", "memory.no_laptop_marker")
    if not _SERVER_MEMORY_MARKER.search(text) and specs.get("form_factor") in ("DIMM", "SO-DIMM"):
        filled += _fill(specs, sources, "ecc", False, "memory.no_ecc_marker")
        filled += _fill(specs, sources, "registered", False, "memory.no_registered_marker")
    filled += _no_lighting(specs, sources, context, "memory.no_lighting_mention")
    return filled


# Lighting is a selling point: every lit memory kit (175/175) and board
# (52/52) in the catalog names it somewhere in its titles or spec rows, so a
# FULL spec page plus titles that never mention any lighting word mean the
# product has none. Cases and coolers are left out: lit ones that never say so
# exist (Antec NX200M per its maker page; 2 of 108 coolers).
_LIGHTING_MENTION = re.compile(
    r"rgb|argb|\bled\b|aura|mystic|polychrome|fusion|spectra|lighting|light\b|"
    r"תאורה|תאורת|מואר|לד\b", re.I)


def _no_lighting(specs: dict, sources: dict, context: dict | None, rule: str) -> list[str]:
    text = (context or {}).get("text", "")
    if text and (context or {}).get("detail_rows", 0) >= 8 and not _LIGHTING_MENTION.search(text):
        return _fill(specs, sources, "lighting", "No", rule)
    return []


_PSU_SMALL_MARKER = re.compile(r"\bsfx|\btfx|flex|\b1u\b|\b2u\b|rack|server|redundant|שרת|\bmini\b|\bslim\b",
                               re.I)


def _infer_psu(specs: dict, sources: dict, context: dict | None = None) -> list[str]:
    filled: list[str] = []
    text = (context or {}).get("text", "")
    if (text and specs.get("type") is None and isinstance(specs.get("wattage_w"), int)
            and not _PSU_SMALL_MARKER.search(text)):
        # SFX / TFX / Flex / 1U units are always labelled as such; an unmarked
        # desktop PSU is full-size ATX.
        filled += _fill(specs, sources, "type", "ATX", "psu.no_small_form_marker")
    if specs.get("type") in ("ATX", "SFX", "SFX-L", "TFX", "Flex ATX"):
        # Every desktop PSU form factor has exactly one 24-pin main connector.
        filled += _fill(specs, sources, "atx4_connectors", 1, "psu.single_24pin_main")
    if isinstance(specs.get("fan_size_mm"), int):
        filled += _fill(specs, sources, "fanless", False, "psu.has_fan")
    if text and not _PSU_FANLESS_MARKER.search(text):
        # A fanless PSU sells on being fanless: every one names it ("Fanless",
        # "Passive", "ללא מאוורר"). Semi-passive "0dB / Zero RPM" units have a
        # fan, so they are not markers. Same shape as the SFX rule above.
        filled += _fill(specs, sources, "fanless", False, "psu.no_fanless_marker")
    return filled


_PSU_FANLESS_MARKER = re.compile(r"fanless|passive|ללא\s*מאוורר|פסיבי", re.I)


# A radiator is sold under the fan size times the fan count it takes (120 /
# 240 / 360 mm carry 120 mm fans, 140 / 280 / 420 mm carry 140 mm fans): the
# nominal size IS the mounting pattern. 146/146 catalog AIOs with both values
# agree.
_RADIATOR_FAN_MM = {120: 120, 240: 120, 360: 120, 140: 140, 280: 140, 420: 140}


# ... and the fan count is the size over the fan size: a 360 takes three
# 120 mm fans, a 280 two 140s. 135/135 catalog AIOs with a sourced fan count
# agree (Oct 2026). A kit sold WITHOUT its fans says so in the title, and is
# left alone.
_RADIATOR_FAN_COUNT = {120: 1, 140: 1, 240: 2, 280: 2, 360: 3, 420: 3}
_AIO_NO_FANS = re.compile(r"without\s+fans?|no\s+fans?|fans?\s+not\s+included|fanless|"
                          r"ללא\s*מאווררים?", re.I)


def _infer_cooler(category: str, specs: dict, sources: dict,
                  context: dict | None = None) -> list[str]:
    if category == "aio" and isinstance(specs.get("radiator_size_mm"), int):
        filled = _fill(specs, sources, "fan_size_mm",
                       _RADIATOR_FAN_MM.get(specs["radiator_size_mm"]),
                       "aio.radiator_fan_size")
        title = str((context or {}).get("title") or "")
        if title and not _AIO_NO_FANS.search(title):
            filled += _fill(specs, sources, "fan_count",
                            _RADIATOR_FAN_COUNT.get(specs["radiator_size_mm"]),
                            "aio.radiator_fan_count")
        return filled
    if category == "cooler_air" and (
            (isinstance(specs.get("fan_count"), int) and specs["fan_count"] > 0)
            or isinstance(specs.get("fan_size_mm"), int)
            or isinstance(specs.get("fan_rpm_max"), int)):
        return _fill(specs, sources, "fanless", False, "cooler.has_fan")
    return []


_RACK_TYPE = re.compile(r"rack|server|\b[1-9]U\b", re.I)


_PSU_MENTION = re.compile(r"\b(?:psu|power supply)\b|ספק|\b\d{3,4}\s?w\b", re.I)
_SERVER_CASE_BRANDS = frozenset({"supermicro", "silverstone rm", "tyan"})


def _infer_case(specs: dict, sources: dict, context: dict | None = None) -> list[str]:
    filled: list[str] = []
    kind = specs.get("type")
    rack = bool(kind and _RACK_TYPE.search(str(kind)))
    if kind:
        filled += _fill(specs, sources, "rackmount", rack, "case.type_rack")
    title = (context or {}).get("title", "")
    brand = str(specs.get("manufacturer") or "").lower()
    if (title and not rack and specs.get("rackmount") is not True
            and brand not in _SERVER_CASE_BRANDS and not _RACK_TYPE.search(title)
            and not _PSU_MENTION.search(title)):
        # Retailers always announce a bundled PSU in the title ("with 650W
        # PSU", "כולל ספק"); 251 of 255 titles without a mention are recorded
        # "Not included" (the 4 exceptions are rack / server chassis, excluded).
        filled += _fill(specs, sources, "psu_included", "Not included",
                        "case.no_psu_in_title")
    return filled


def infer_specs(category: str | None, specs: dict, sources: dict,
                context: dict | None = None) -> list[str]:
    """Fill nulls from derivable facts; never override a real value.

    Mutates `specs`/`sources` in place and returns the filled field names so the
    run can report how much of the sheet is derived rather than sourced.
    `context` is optional per-product raw evidence the caller assembles
    ({"text": lowercase title + row text, "detail_rows": best table size});
    only the explicit-negative rules read it.
    """
    if category == "cpu":
        filled = _infer_cpu_table(specs, sources)
        # the table supplies facts (iGPU, memory ceiling) the rules also read
        return filled + _infer_cpu(specs, sources)
    if category == "memory":
        return _infer_memory(specs, sources) + _infer_memory_text(specs, sources, context)
    if category == "storage":
        return _infer_storage(specs, sources)
    if category == "gpu":
        return (_infer_gpu(specs, sources) + _infer_gpu_table(specs, sources)
                + _infer_gpu_board_line(specs, sources, context)
                + _infer_gpu_extras(specs, sources, context))
    if category == "motherboard":
        return _infer_motherboard(specs, sources, context)
    if category == "psu":
        return _infer_psu(specs, sources, context)
    if category in ("cooler_air", "aio", "cooling_other"):
        return _infer_cooler(category, specs, sources, context)
    if category == "case":
        return _infer_case(specs, sources, context)
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
