"""
specs/witness.py — a shipped spec value against the product's own titles.

Audit 2026-11-10 clusters F/G, owner answer Q4. A title that STATES a field is
evidence about it; a title that states nothing is never evidence. After the
merge, every witnessed field is compared with what the product's titles say:

- the shipped value matches some title (or no title states the field): kept;
- the titles contradict it and at least two INDEPENDENT sources agree on one
  other value: the value is replaced (source label `witness`). A source is a
  vendor — counted once, through its titles or its own spec attribute — or a
  non-retailer tier (reference, manufacturer page, catalog sheet);
- the contradiction has one source behind it: kept, and a `spec_conflict`
  issue goes to the QA page. One vendor's title alone is not enough (Lexar
  Thor: Yahav's title says DDR4 on a DDR5 kit).

Runs between the merge and `cross_check`, so a corrected chipset feeds the
chipset <-> socket rule, and the fields a title supports tell `cross_check`
which side of a socket/chipset fight to drop.
"""

from __future__ import annotations

import re
from dataclasses import replace

from . import schema
from . import text as text_module
from .merge import TIER_CATALOG, TIER_TITLE, TIER_VENDOR, TIER_WEAK, Fact

WITNESS_SOURCE = "witness"
# QA issue tag: site_data lifts these cases ahead of the spec_conflict cap.
RULE = "title_witness"

_CHIP_RE = re.compile(
    r"(?<![A-Z0-9])([ABHZQWXC]\d{3}E?S?|TRX\d{2}|WRX\d{2})(?=[A-Z]{0,3}\b|-|\b)", re.I)
_SOCK_RE = re.compile(
    r"\b(AM4|AM5|TR4|sTRX4|sTR5|LGA\s?-?\d{4}|s?(?:1150|1151|1155|1200|1700|1851|2011|2066"
    r"|3647|4189|4677))\b", re.I)
_DDR_RE = re.compile(r"\b(DDR[345])\b", re.I)
_GPU_MEM_RE = re.compile(r"\b(G?DDR\d+X?|HBM\d?E?)\b", re.I)
_GPU_MEM_SHORT_RE = re.compile(r"\d+G(?:B)?D(\d)\b|\bD(\d)\b")
_CAPACITY_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(TB|GB)\b", re.I)
_NO_COOLER_RE = re.compile(
    r"ללא\s+(?:קירור|מאוורר|קולר)|without\s+(?:cooler|fan)|no\s+cooler|\bWOF\b", re.I)
_WITH_COOLER_RE = re.compile(r"כולל\s+(?:קירור|מאוורר|קולר)|with\s+(?:cooler|fan)|wraith", re.I)
_TRAY_RE = re.compile(r"\btray\b|\boem\b|טריי", re.I)
_BOX_RE = re.compile(r"\bbox\b|\bboxed\b|קופסה|\bretail\b", re.I)

# GPU memory standards a card can carry (cross-field invariant, cluster G).
GPU_MEMORY_TYPES = frozenset({
    "GDDR3", "GDDR5", "GDDR5X", "GDDR6", "GDDR6X", "GDDR7",
    "HBM", "HBM2", "HBM2E", "HBM3", "HBM3E", "DDR3", "DDR4", "DDR5",
})


def refine_chipset_suffix(category: str | None, facts: dict) -> None:
    """One listing: a vendor label that prints the base chipset (B650, X870)
    while the listing's own title prints its E variant is the coarser name of
    the same board, not a contradiction, so it takes the E (audit 2026-11-10
    F09: 1PC, TMS, Yahav and KSP labels say B650 on B650E boards). Owner Q5:
    B650E/X870E stay distinct. Mutates `facts`."""
    if category != "motherboard":
        return
    chipsets = facts.get("chipset") or []
    titled = {str(fact.value).upper() for fact in chipsets if fact.tier == TIER_TITLE}
    for index, fact in enumerate(chipsets):
        if fact.tier >= TIER_TITLE or not isinstance(fact.value, str):
            continue
        refined = fact.value.upper() + "E"
        if refined in titled and refined in schema.CHIPSET_INFO:
            chipsets[index] = replace(fact, value=refined)


# CPU packaging, one listing (audit 2026-11-10 D, owner Q3 "code decides, flag
# it"). Order: the listing's own title label, then its vendor attribute, then
# the maker's part number, then the retailer's catalogue-code letter (weak);
# nothing at all = basis "default" (identity reads it as Box, never a spec).
_INTEL_BOX_PN = re.compile(r"^BX8\d")
_INTEL_TRAY_PN = re.compile(r"^CM8\d")
_AMD_BOX_PN = re.compile(r"^100-\d{9,10}(?:BOX|WOF|WOZ|POF)$")
_AMD_TRAY_PN = re.compile(r"^100-\d{9,10}(?:MPK|TRAY)?$")
# TMS "C245KFT" / "C10700KB-A" / "C7500T-P" / "C250KFPLUST": the last letter
# before an optional one-letter tail is the packaging (T = Tray, B = Box).
_RETAILER_CODE = re.compile(r"^C\d{3,5}[A-Z]{0,7}?([TB])(?:-[A-Z])?$")
PACKAGING_BASES = ("title", "title_over_attribute", "attribute", "part_number",
                   "retailer_code", "default")


def _pack_key(value) -> str | None:
    text = str(value or "").strip().lower()
    if text in ("tray", "oem", "bulk"):
        return "tray"
    if text in ("boxed", "box"):
        return "boxed"
    return None


def listing_title_packaging(title: str) -> str | None:
    """"tray" / "boxed" when the title states exactly one packaging."""
    title = title or ""
    tray = bool(text_module.CPU_PACKAGING_TRAY_RE.search(title) or _TRAY_RE.search(title))
    box = bool(text_module.CPU_PACKAGING_BOX_RE.search(title) or _BOX_RE.search(title))
    if tray != box:
        return "tray" if tray else "boxed"
    return None


def part_number_packaging(value) -> str | None:
    """The maker's ordering code: Intel BX = Box, CM = Tray; AMD 100-...BOX/WOF
    = Box, 100-... bare or MPK = Tray."""
    key = re.sub(r"\s+", "", str(value or "").upper())
    if _INTEL_BOX_PN.match(key) or _AMD_BOX_PN.match(key):
        return "boxed"
    if _INTEL_TRAY_PN.match(key) or _AMD_TRAY_PN.match(key):
        return "tray"
    return None


def retailer_code_packaging(value) -> str | None:
    match = _RETAILER_CODE.match(re.sub(r"\s+", "", str(value or "").upper()))
    if not match:
        return None
    return "tray" if match.group(1) == "T" else "boxed"


def resolve_cpu_packaging(category: str | None, listing: dict, facts: dict) -> None:
    """Pick one listing's packaging by the owner's order; mutates `facts` and
    sets `listing["packaging_basis"]` (one of PACKAGING_BASES)."""
    if category != "cpu":
        return
    current = list(facts.get("packaging") or [])
    stated = listing_title_packaging(str(listing.get("title_raw") or ""))
    if stated:
        kept = [fact for fact in current if _pack_key(fact.value) == stated]
        overridden = any(fact.tier < TIER_TITLE for fact in current
                         if _pack_key(fact.value) != stated)
        if not any(fact.tier <= TIER_TITLE for fact in kept):
            kept.append(Fact(value=stated, tier=TIER_TITLE, source="title:packaging",
                             confidence=0.9))
        facts["packaging"] = kept
        listing["packaging_basis"] = "title_over_attribute" if overridden else "title"
        return
    if any(_pack_key(fact.value) for fact in current):
        listing["packaging_basis"] = "attribute"
        return
    codes = (listing.get("mpn"), listing.get("vendor_sku"))
    for value in codes:
        pack = part_number_packaging(value)
        if pack:
            facts["packaging"] = current + [Fact(
                value=pack, tier=TIER_VENDOR, source="vendor_struct:part_number",
                confidence=0.85)]
            listing["packaging_basis"] = "part_number"
            return
    for value in codes:
        pack = retailer_code_packaging(value)
        if pack:
            facts["packaging"] = current + [Fact(
                value=pack, tier=TIER_WEAK, source="weak:retailer_code", confidence=0.6)]
            listing["packaging_basis"] = "retailer_code"
            return
    listing["packaging_basis"] = "default"


def socket_key(value) -> str:
    key = re.sub(r"[\s-]", "", str(value or "").upper())
    if key[:1] == "S" and key[1:].isdigit():
        key = key[1:]
    if key == "TR5":
        key = "STR5"
    if key.isdigit():
        key = "LGA" + key
    return key


def _socket_value(key: str) -> str:
    """Schema spelling of a socket key ("STR5" -> "sTR5")."""
    return {"STR5": "sTR5", "STRX4": "sTRX4"}.get(key, key)


def title_chipsets(title: str) -> set[str]:
    return {m.upper() for m in _CHIP_RE.findall(title or "")
            if m.upper() in schema.CHIPSET_INFO}


def title_sockets(title: str) -> set[str]:
    """Socket keys a board title states: through its chipset first, a socket
    word otherwise (a chipset in the title outranks a socket word)."""
    via_chipset = {socket_key(schema.CHIPSET_INFO[chip][0])
                   for chip in title_chipsets(title) if schema.CHIPSET_INFO[chip][0]}
    if via_chipset:
        return via_chipset
    return {socket_key(m) for m in _SOCK_RE.findall(title or "")}


def title_ddr(title: str) -> set[str]:
    return {m.upper() for m in _DDR_RE.findall(title or "")}


def title_gpu_memory(title: str) -> set[str]:
    match = _GPU_MEM_RE.search(title or "")
    if match:
        return {match.group(1).upper()}
    match = _GPU_MEM_SHORT_RE.search(title or "")
    if match:
        digit = match.group(1) or match.group(2)
        value = {"4": "DDR4", "5": "GDDR5", "6": "GDDR6", "7": "GDDR7"}.get(digit)
        return {value} if value else set()
    return set()


def gpu_memory_family(value) -> str:
    """GDDR6 and DDR6 compare equal: titles drop the G freely."""
    return re.sub(r"^G", "", str(value or "").upper())


def title_capacity_gb(title: str) -> set[int]:
    match = _CAPACITY_RE.search(title or "")
    if not match:
        return set()
    number = float(match.group(1))
    return {int(round(number * 1000)) if match.group(2).upper() == "TB" else int(number)}


def capacity_agrees(shipped, stated: int) -> bool:
    """A 1.024x binary/decimal gap and rounding are the same drive."""
    return (abs(shipped - stated) <= max(1, 0.002 * stated)
            or abs(shipped - stated * 1.024) <= 1)


def title_includes_cooler(title: str) -> set[bool]:
    if _NO_COOLER_RE.search(title or ""):
        return {False}
    if _WITH_COOLER_RE.search(title or ""):
        return {True}
    return set()


def title_packaging(title: str) -> set[str]:
    tray, box = bool(_TRAY_RE.search(title or "")), bool(_BOX_RE.search(title or ""))
    if tray and not box:
        return {"tray"}
    if box and not tray:
        return {"boxed"}
    return set()


# field -> (title reader, value -> comparison key, unanimous titles required)
def _readers(category: str | None) -> dict:
    same = lambda value: str(value).upper()  # noqa: E731
    if category == "motherboard":
        return {"chipset": (title_chipsets, same, False),
                "socket": (title_sockets, socket_key, False),
                "memory_type": (title_ddr, same, False)}
    if category == "memory":
        return {"memory_type": (title_ddr, same, False)}
    if category == "gpu":
        return {"memory_type": (title_gpu_memory, gpu_memory_family, False)}
    if category == "storage":
        return {"capacity_gb": (title_capacity_gb, None, False)}
    if category == "cpu":
        return {"includes_cooler": (title_includes_cooler, lambda value: bool(value), True),
                "packaging": (title_packaging, lambda value: str(value).lower(), True)}
    return {}


def _agrees(field: str, key, shipped, stated) -> bool:
    if key is None:  # capacity: a tolerance, not a key
        return capacity_agrees(shipped, stated)
    return key(shipped) == key(stated)


def _schema_value(field: str, category: str | None, stated):
    if field == "socket":
        return _socket_value(stated)
    return stated


def apply_title_witness(category: str | None, specs: dict, sources: dict,
                        listing_facts: list[tuple[dict, dict]],
                        facts: dict) -> tuple[list[dict], set[str]]:
    """Check every witnessed field; mutate `specs`/`sources` on a 2-source fix.

    `listing_facts` is one (listing, tier 1-3 facts) pair per offer; `facts`
    the product's full fact lists (for the non-retailer tiers). Returns the
    QA issues and the fields a title supports after the pass.
    """
    from .validate import validate_fact  # validate imports this module

    issues: list[dict] = []
    supported: set[str] = set()
    fields = schema.field_map(category)
    for field, (reader, key, unanimous) in _readers(category).items():
        shipped = specs.get(field)
        stated_by: dict[str, set] = {}  # vendor -> stated values
        for listing, _ in listing_facts:
            values = reader(str(listing.get("title_raw") or ""))
            if values:
                vendor = str(listing.get("vendor_id") or listing.get("listing_key") or "")
                stated_by.setdefault(vendor, set()).update(values)
        stated = set().union(*stated_by.values()) if stated_by else set()
        if not stated or shipped is None:
            continue
        if unanimous and len(stated) != 1:
            continue
        if any(_agrees(field, key, shipped, value) for value in stated):
            supported.add(field)
            continue

        # Contradicted. Who stands behind each stated alternative?
        support: dict = {}
        for value in stated:
            backers: set[str] = set()
            for vendor, values in stated_by.items():
                if value in values and not any(_agrees(field, key, shipped, v) for v in values):
                    backers.add(f"vendor:{vendor}")
            for listing, own in listing_facts:
                vendor = str(listing.get("vendor_id") or "")
                for fact in own.get(field) or []:
                    if fact.tier == TIER_VENDOR and fact.value is not None and _agrees(
                            field, key, fact.value, value):
                        backers.add(f"vendor:{vendor}")
            for fact in facts.get(field) or []:
                if fact.tier <= TIER_CATALOG and fact.value is not None and _agrees(
                        field, key, fact.value, value):
                    backers.add(fact.tier_name)
            support[value] = backers
        ranked = sorted(support.items(), key=lambda item: (-len(item[1]), str(item[0])))
        best, backers = ranked[0]
        unique = len(ranked) == 1 or len(ranked[1][1]) < len(backers)
        replacement = _schema_value(field, category, best)
        spec = fields.get(field)
        valid = spec is not None and validate_fact(category, spec, replacement) is None
        origin = sources.get(field) or "unknown"
        if len(backers) >= 2 and unique and valid and origin != "override":
            issues.append({
                "kind": "spec_conflict", "rule": RULE, "field": field, "kept": replacement,
                "dropped": shipped,
                "detail": f"title witness: {len(backers)} independent sources "
                          f"({', '.join(sorted(backers))}) state {replacement} against "
                          f"the {origin} value {shipped}",
            })
            specs[field] = replacement
            sources[field] = WITNESS_SOURCE
            supported.add(field)
        else:
            issues.append({
                "kind": "spec_conflict", "rule": RULE, "field": field, "kept": shipped,
                "detail": f"title witness: {', '.join(sorted(backers)) or 'a title'} "
                          f"states {replacement} against the {origin} value {shipped}; "
                          + ("a manual override, not changed" if origin == "override"
                             else "one source, not changed"),
            })
    return issues, supported
