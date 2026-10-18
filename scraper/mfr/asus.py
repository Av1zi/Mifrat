"""
mfr/asus.py - asus.com "techspec" pages for motherboards (feasibility: PASS).

Verdict (Oct 2026): robots.txt only blocks search / filter URLs; the global
sitemaps (sitemap/global1..16.xml) list every product page including
".../<series>/<slug>/techspec/"; those pages are server-rendered Vue with a
"rowTableTitle" heading followed by <p> value lines per section (CPU, Chipset,
Memory, Storage, Ethernet, Wireless & Bluetooth, Form Factor ...) - no JS
needed. Graphics cards share the layout but their catalog names do not map to
slugs (ASUS sells them under 90YV... order codes), so only motherboards are in
scope; boards join on a token-set comparison of the product name and the slug,
with chipset / "WIFI" decorations the catalog adds being the only tolerated
difference. Ambiguous or partial names are skipped.
"""

from __future__ import annotations

import html as html_lib
import re

from .common import typed

BRAND = "ASUS"
BASE_URL = "https://www.asus.com"
SITEMAPS = [f"{BASE_URL}/sitemap/global{i}.xml" for i in range(1, 17)]
CATEGORIES = ("motherboard",)

_URL_RE = re.compile(
    r"<loc>(https://www\.asus\.com/motherboards-components/motherboards/[^/<]+/([^/<]+)/techspec/)</loc>")
# Retail-title decorations that are not part of ASUS's model name ("LGA", the
# port callouts Yahav appends, the CPU-generation hints). "csm" boards share the
# non-CSM hardware spec.
_NOISE_TOKENS = {"asus", "csm", "micro", "matx", "atx", "itx", "lga", "vga", "gen",
                 "12th", "13th", "14th", "displayport", "1xhdmi", "2xdisplayport",
                 "2xtype", "hdmi"}
_CHIPSET_TOKEN = re.compile(r"^[a-z]\d{3}[a-z]?$")
_WIFI_TOKEN = re.compile(r"^(?:wifi\d?e?|wi|fi)$")


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t]


def _signature(text: str) -> tuple[tuple[str, ...], bool]:
    """(significant tokens, has-wifi). "WIFI6" / "Wi-Fi" / "wifi7" are one flag:
    a board and its WIFI sibling are different products, so the flag must
    agree, but the standard suffix the catalog appends is not in the slug."""
    tokens = _tokens(text)
    wifi = any(_WIFI_TOKEN.match(t) for t in tokens)
    core = tuple(sorted({t for t in tokens
                         if t not in _NOISE_TOKENS and not _WIFI_TOKEN.match(t)}))
    return core, wifi


def index(client) -> list[dict]:
    entries = []
    for sitemap in SITEMAPS:
        page = client.get(sitemap)
        for url, slug in _URL_RE.findall(page or ""):
            core, wifi = _signature(slug)
            entries.append({"url": url, "slug": slug,
                            "key": "|".join(core) + ("#wifi" if wifi else "")})
    return entries


def match(entries_by_key: dict[str, dict], product: dict) -> dict | None:
    """Unique slug with the same significant tokens and the same WIFI flag.

    Chipset tokens the catalog prepends/appends (Z490 ROG Maximus XII Apex)
    are tolerated when absent from the slug; anything else must agree.
    """
    name, wifi = _signature(product.get("canonical_name") or "")
    if not name:
        return None
    suffix = "#wifi" if wifi else ""
    exact = entries_by_key.get("|".join(name) + suffix)
    if exact:
        return exact
    core = tuple(t for t in name if not _CHIPSET_TOKEN.match(t))
    found = []
    for key, entry in entries_by_key.items():
        body, _, flag = key.partition("#")
        if bool(flag) != wifi:
            continue
        slug_parts = body.split("|")
        slug_core = tuple(t for t in slug_parts if not _CHIPSET_TOKEN.match(t))
        # A chipset token may be missing on one side (the catalog prepends
        # "Z490"; ASUS omits it) but two DIFFERENT chipsets are different boards
        # (B650 vs B650E).
        chipsets = {t for t in name if _CHIPSET_TOKEN.match(t)}
        slug_chipsets = {t for t in slug_parts if _CHIPSET_TOKEN.match(t)}
        if chipsets and slug_chipsets and chipsets != slug_chipsets:
            continue
        if core and slug_core == core:
            found.append(entry)
    return found[0] if len(found) == 1 else None


def _sections(page: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    for part in re.split(r'<div class="rowTableTitle">', page)[1:]:
        title, _, body = part.partition("</div>")
        title = html_lib.unescape(re.sub(r"<[^>]+>", "", title)).strip().lower()
        body = body.split("rowTableTitle")[0]
        lines: list[str] = []
        for item in re.findall(r"<p>(.*?)</p>", body, re.S):
            item = re.sub(r"<br\s*/?>", "\n", item)
            text = html_lib.unescape(re.sub(r"<[^>]+>", "", item))
            lines += [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]
        if title and lines:
            sections.setdefault(title, lines)
    return sections


_SLOT_LINE = re.compile(r"^\s*(\d{1,2})\s*x\s*PCIe\s*[\d./]*\s*(?:\(\w+\)\s*)?x(16|4|1)\b", re.I)


def _pcie_slot_counts(lines: list[str]) -> dict[str, int]:
    """Physical PCIe slot counts by length from the "Expansion Slots" block.

    ASUS lists the same physical slots once per CPU generation ("Ryzen 9000:
    1 x PCIe 4.0 x16 (x16 mode) / Ryzen 8000: 1 x PCIe 4.0 x16 (x8 mode)") and
    then the chipset's own slots, so: take the largest CPU-attached group and
    ADD the chipset group. A page with no group headers is one flat list.
    """
    groups: list[tuple[str, dict[str, int]]] = []
    # Some pages print the whole block twice; stop where the first line repeats.
    if lines and lines[0] in lines[1:]:
        lines = lines[:lines.index(lines[0], 1)]
    for line in lines:
        slot = _SLOT_LINE.match(line)
        if slot:
            if not groups:
                groups.append(("flat", {}))
            counts = groups[-1][1]
            key = "x" + slot.group(2)
            counts[key] = counts.get(key, 0) + int(slot.group(1))
        elif not line.startswith(("*", "-")):
            kind = "chipset" if re.search(r"chipset", line, re.I) else "cpu"
            groups.append((kind, {}))
    total: dict[str, int] = {}
    cpu_groups = [counts for kind, counts in groups if kind != "chipset"]
    for key in ("x16", "x4", "x1"):
        best = max((counts.get(key, 0) for counts in cpu_groups), default=0)
        chipset = sum(counts.get(key, 0) for kind, counts in groups if kind == "chipset")
        if best + chipset:
            total[key] = best + chipset
    return total


def parse(page: str, category: str) -> dict:
    sections = _sections(page)
    if category != "motherboard" or len(sections) < 8:
        return {}
    out: dict = {}

    def put(field: str, raw) -> None:
        if raw is None:
            return
        value = typed(category, field, raw)
        if value is not None:
            out[field] = value

    cpu = " ".join(sections.get("cpu", []))
    socket = re.search(r"Socket\s+(LGA\s?\d{3,4}|AM\d|sTR\d|sWRX\d|TR4)", cpu, re.I)
    if socket:
        put("socket", socket.group(1))
    chipset = " ".join(sections.get("chipset", []))
    match = re.search(r"\b([A-Z]\d{3}[A-Z]?|WRX\d{2}|TRX\d{2})\b", chipset)
    if match:
        put("chipset", match.group(1))

    memory = sections.get("memory", [])
    first = memory[0] if memory else ""
    slots = re.match(r"\s*(\d{1,2})\s*x\s*DIMM", first, re.I)
    if slots:
        put("memory_slots", int(slots.group(1)))
    kind = re.search(r"\b(DDR[345])\b", first)
    if kind:
        put("memory_type", kind.group(1))
    ceiling = re.search(r"\bmax\.?\s*(\d{2,4})\s*GB\b", first, re.I)
    if ceiling:
        put("memory_max_gb", int(ceiling.group(1)))
    slot_counts = _pcie_slot_counts(sections.get("expansion slots", []))
    if slot_counts:
        put("pcie_x16_slots", slot_counts.get("x16"))
        put("pcie_x1_slots", slot_counts.get("x1"))
    if re.search(r"ECC and Non-ECC", first, re.I):
        put("ecc_support", True)
    elif re.search(r"\bNon-ECC\b", first, re.I):
        put("ecc_support", False)

    storage = " ".join(sections.get("storage", []))
    m2 = re.search(r"supports\s+(\d{1,2})\s*x\s*M\.2", storage, re.I)
    if m2:
        put("m2_slots", [m2.group(1)])
    sata = re.search(r"(\d{1,2})\s*x\s*SATA\s*6", storage, re.I)
    if sata:
        put("sata_ports", int(sata.group(1)))

    lan = " ".join(sections.get("ethernet", []))
    speed = re.search(r"(\d+(?:\.\d+)?)\s*(?:Gb|G)\b", lan, re.I)
    if speed:
        number = speed.group(1)
        put("ethernet", f"LAN {number.rstrip('0').rstrip('.') if '.' in number else number} Gb/s")

    wireless = " ".join(sections.get("wireless & bluetooth", []))
    if wireless:
        wifi = re.search(r"Wi-?Fi\s*([67])\s?(E)?", wireless, re.I)
        put("wireless", f"Wi-Fi {wifi.group(1)}{(wifi.group(2) or '').upper()}" if wifi else None)
        bluetooth = re.search(r"Bluetooth\W*v?\s*(\d(?:\.\d)?)", wireless, re.I)
        if bluetooth:
            put("bluetooth", f"Bluetooth {bluetooth.group(1)}")
    elif "usb" in sections and not re.search(
            r"wi-?fi|wlan|wireless|bluetooth",
            " ".join(" ".join(lines) for lines in sections.values()), re.I):
        # A complete spec sheet (USB, Ethernet ... all present) without a
        # wireless section is a board without a radio: the manufacturer's own
        # statement, not an inference from a retailer's gaps.
        put("wireless", "No")
        put("bluetooth", "No")

    bios = (sections.get("bios") or [""])[0]
    if bios and len(bios) < 80:
        put("bios", bios)

    form = " ".join(sections.get("form factor", [])[:1])
    if re.search(r"\bmATX\b|micro", form, re.I):
        put("form_factor", "Micro-ATX")
    elif re.search(r"mini[- ]?ITX", form, re.I):
        put("form_factor", "Mini-ITX")
    elif re.search(r"E-?ATX", form, re.I):
        put("form_factor", "EATX")
    elif re.search(r"\bATX\b", form):
        put("form_factor", "ATX")
    return out
