"""
mfr/common.py - shared helpers for manufacturer fetchers.

- `html_rows(html)`: every (label, value) pair from two-cell table rows, with
  nested-table wrappers (Antec) ignored so a layout row never swallows its
  children;
- `norm_mpn` / `norm_upc`: the identity keys products are matched on;
- `typed(category, field, raw)`: raw page text -> a schema-typed, canonical,
  VALIDATED value (or None). Nothing leaves a fetcher that the spec pipeline
  would have dropped as invalid.
"""

from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

from ..specs import schema
from ..specs.validate import validate_fact
from ..specs.values import InvalidValue, coerce


class _RowParser(HTMLParser):
    """Collects the cells of every <tr> that has no nested <table>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._stack: list[dict] = []     # one frame per open <tr>
        self._cell: list[str] | None = None
        self._skip = 0                   # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self._stack.append({"cells": [], "nested": False})
        elif tag == "table" and self._stack:
            self._stack[-1]["nested"] = True
        elif tag in ("td", "th") and self._stack:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" / ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._stack and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip(" / ")
            self._stack[-1]["cells"].append(text)
            self._cell = None
        elif tag == "tr" and self._stack:
            frame = self._stack.pop()
            if not frame["nested"] and len(frame["cells"]) >= 2:
                self.rows.append(frame["cells"])

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def html_rows(page: str) -> list[tuple[str, str]]:
    """(label, value) for each two-cell table row, in page order."""
    parser = _RowParser()
    parser.feed(page)
    out = []
    for cells in parser.rows:
        label, value = cells[0], cells[1]
        if label and value:
            out.append((label, value))
    return out


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(text or "")).strip()


def norm_mpn(value) -> str:
    """CO-9050111-WW -> CO9050111WW (case/punctuation-insensitive identity)."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


_REGION_SUFFIX = {"NA", "EU", "UK", "WW", "AU", "CN", "JP", "AP", "BR", "RU", "IN", "KR", "TW"}


def base_mpn(value) -> str:
    """Region-independent MPN: CP-9020292-EU / CP-9020292-NA -> CP9020292.

    Corsair files one product under a different region suffix per market (the
    Israeli importer sells -EU codes; the US sitemap lists -NA / -WW). Only a
    trailing two-letter region segment is dropped.
    """
    parts = [p for p in re.split(r"[-\s]+", str(value or "").strip()) if p]
    if len(parts) >= 2 and parts[-1].upper() in _REGION_SUFFIX:
        parts = parts[:-1]
    return re.sub(r"[^A-Za-z0-9]", "", "".join(parts)).upper()


def norm_upc(value) -> str:
    """0-761345-80050-1 -> 0761345800501 (digits only, 8+ long or empty)."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) >= 8 else ""


def norm_name(value, brand: str = "") -> str:
    """Brand-stripped alphanumeric name used for slug-prefix matching."""
    text = str(value or "").lower()
    if brand:
        text = re.sub(rf"\b{re.escape(brand.lower())}\b", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)


def typed(category: str, field: str, raw):
    """A schema-typed, canonical, validated value - or None when unusable."""
    spec = schema.field_map(category).get(field)
    if spec is None or raw is None:
        return None
    try:
        value = coerce(spec, raw, category)
    except InvalidValue:
        return None
    if validate_fact(category, spec, value):
        return None
    return value


def number_range(text) -> tuple[float, float] | None:
    """'23.07 - 68.11 CFM' / '300-1,200' / '1500' -> (min, max)."""
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(text or ""))
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", cleaned)]
    if not numbers:
        return None
    return min(numbers), max(numbers)


_FORM_PATTERN = re.compile(
    r"XL-?\s?ATX|E-?\s?ATX|Micro-?\s?ATX|\bm-?ATX\b|Mini-?\s?DTX|Mini-?\s?ITX|\bATX\b|\bITX\b",
    re.I)


def mb_form_factor_list(text: str) -> list[str]:
    """'Mini-ITX | MicroATX | ATX | E-ATX (305mm x 277mm)' ->
    ['Mini ITX', 'Micro ATX', 'ATX', 'E-ATX'] - the spellings the catalog's
    filter already uses, so a manufacturer row never forks a facet."""
    text = re.sub(r"\([^)]*\)", " ", str(text or ""))
    out: list[str] = []
    for match in _FORM_PATTERN.finditer(text):
        raw = re.sub(r"[\s-]+", "", match.group(0)).upper()
        label = {"XLATX": "XL-ATX", "EATX": "E-ATX", "MICROATX": "Micro ATX",
                 "MATX": "Micro ATX", "MINIDTX": "Mini-DTX", "MINIITX": "Mini ITX",
                 "ITX": "Mini ITX", "ATX": "ATX"}.get(raw)
        if label and label not in out:
            out.append(label)
    order = ["Mini-DTX", "Mini ITX", "Micro ATX", "ATX", "E-ATX", "XL-ATX"]
    return sorted(out, key=order.index)       # smallest first, like the retailer lists


def spaced_mm(text: str) -> str:
    """'3x120mm; 2 x 140mm' -> '3 x 120 mm, 2 x 140 mm' (catalog fan-mount style)."""
    text = re.sub(r"(\d)\s*x\s*(\d)", r"\1 x \2", str(text or ""), flags=re.I)
    text = re.sub(r"(\d)\s*mm", r"\1 mm", text, flags=re.I)
    return re.sub(r"\s*[;/]\s*", ", ", text).strip()


def strict_name(value, brand: str = "") -> str:
    """Name key for exact store matching.

    Unlike `norm_name` (separators dropped, used for slug-prefix matching) this
    keeps hyphens and word breaks: "B650-E" (B650 chipset, E variant) and
    "B650E" (B650E chipset) are different boards and must not share a key.
    """
    text = str(value or "").lower()
    if brand:
        text = re.sub(rf"\b{re.escape(brand.lower())}\b", " ", text)
    text = re.sub(r"[^a-z0-9-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def front_io_ports(text) -> list[str] | None:
    """'Power, USB3.0 x 2, Type-C 3.2 Gen 2, Mic/HD-AUDIO' -> the catalog's
    front_usb tokens, by the SAME reader the retailer cells go through
    (vendor_struct._emit_front_io), so a manufacturer row never forks the
    facet vocabulary."""
    from ..specs.resolvers import vendor_struct

    text = re.sub(r"\bUSB\s*(\d)(?=\.\d)", r"USB \1", str(text or ""))   # USB3.0 -> USB 3.0
    text = re.sub(r"\bUSB(\d)\b", r"USB \1", text)
    text = re.sub(r"\bUSB\s*\d(?:\.\d)?\s*(?:Gen\s*\w+)?\s*Type-?\s*C\b", "USB Type-C", text, flags=re.I)
    text = re.sub(r"(?<![\w-])(?<!USB )Type-?\s*C\b", "USB Type-C", text, flags=re.I)
    text = re.sub(r"\b(?:Mic|Microphone)\b[^,]*", "microphone", text, flags=re.I)
    facts: dict = {}
    vendor_struct._emit_front_io(facts, "case", text, "manufacturer")
    found = facts.get("front_usb")
    ports = list(found[0].value) if found else []
    # The retailer vocabulary the case facet already uses: "USB Type-C" (not
    # "USB (Type-C)"), bare "USB" is no information, one audio token.
    out: list[str] = []
    for port in ports:
        port = {"USB (Type-C)": "USB Type-C", "Microphone": "Earphone/Mic",
                "Headphone": "Earphone/Mic"}.get(port, port)
        if port not in ("USB", "Power Button") and port not in out:
            out.append(port)
    if re.search(r"\b(?:mic|headset|headphone|earphone|audio)\b", text, re.I) \
            and "Earphone/Mic" not in out:
        out.append("Earphone/Mic")
    return out or None


def efficiency_tier(text) -> str | None:
    """'80 Plus Platinum' / '80+ Gold' / 'Cybenetics Gold' -> '80+ Gold'."""
    match = re.search(r"\b(White|Bronze|Silver|Gold|Platinum|Titanium)\b", str(text or ""), re.I)
    if match and re.search(r"80\s*(?:\+|plus)|cybenetics", str(text or ""), re.I):
        return f"80+ {match.group(1).title()}"
    return None
