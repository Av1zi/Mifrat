"""
mfr/common.py - shared helpers for manufacturer fetchers.

- `html_rows(html)`: every (label, value) pair from two-cell table rows, with
  nested-table wrappers (Antec) ignored so a layout row never swallows its
  children; `html_section_rows(html)` adds the heading of the one-cell row
  above each pair (Antec's "Fan Support" / "Radiator Support" blocks repeat
  the same Front / Top / Rear labels);
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
    """Collects the cells of every <tr> that has no nested <table>.

    A label cell with rowspan="N" (Antec's "Connector" / "UPC#" lists) is
    carried onto the one-cell rows it spans, so each list item reads as its
    own (label, value) row instead of a bare one-cell row.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._stack: list[dict] = []     # one frame per open <tr>
        self._cell: list[str] | None = None
        self._skip = 0                   # inside <script>/<style>
        self._carry: list = []           # [label, rows left] of a rowspan label

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self._stack.append({"cells": [], "nested": False, "span": 1})
        elif tag == "table" and self._stack:
            self._stack[-1]["nested"] = True
        elif tag in ("td", "th") and self._stack:
            self._cell = []
            if not self._stack[-1]["cells"]:
                span = dict(attrs).get("rowspan") or "1"
                self._stack[-1]["span"] = int(span) if span.isdigit() else 1
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
            if frame["nested"] or not frame["cells"]:
                return
            cells = frame["cells"]
            if self._carry:
                if len(cells) == 1:
                    cells = [self._carry[0], *cells]
                self._carry[1] -= 1
                if self._carry[1] <= 0:
                    self._carry = []
            elif frame["span"] > 1 and len(cells) >= 2:
                self._carry = [cells[0], frame["span"] - 1]
            self.rows.append(cells)

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def html_rows(page: str) -> list[tuple[str, str]]:
    """(label, value) for each two-cell table row, in page order."""
    parser = _RowParser()
    parser.feed(page)
    out = []
    for cells in parser.rows:
        if len(cells) < 2:
            continue
        label, value = cells[0], cells[1]
        if label and value:
            out.append((label, value))
    return out


def html_section_rows(page: str) -> list[tuple[str, str, str]]:
    """(section, label, value) per two-cell row; the section is the text of the
    last one-cell row above it, lower-cased ("" before the first heading)."""
    parser = _RowParser()
    parser.feed(page)
    out = []
    section = ""
    for cells in parser.rows:
        if len(cells) == 1:
            section = re.sub(r"\s+", " ", cells[0]).strip().lower()
            continue
        label, value = cells[0], cells[1]
        if label and value:
            out.append((section, label, value))
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


_TOLERANCE = re.compile(r"(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?\s*%?")


def spec_range(text) -> tuple[float, float] | None:
    """'800±200 ~ 1800±10% RPM' / '420 – 2100 RPM ±10%' -> (800, 1800).

    Tolerances are dropped before the numbers are read (`number_range` alone
    took the "10" of "±10%" as the minimum), and so are unit suffixes that
    carry a digit ("mm-H2O", "mmH₂O")."""
    text = _TOLERANCE.sub(" ", str(text or ""))
    text = re.sub(r"H\s*[2₂]\s*[0O]", " ", text, flags=re.I)
    text = re.sub(r"\([^)]*\)", " ", text)
    return number_range(text)


_FAN_SIZES = r"(?:40|50|60|70|80|92|120|140|160|170|180|200|220|230)"


def fan_mounts(text) -> str | None:
    """'3 x 140 / 3 x 120mm (Remove HDD Cage)' -> '3 x 140 mm, 3 x 120 mm';
    '1x 120mm' -> '1 x 120 mm'; 'None' / 'N/A' -> 'No' (the page states the
    position takes no fan; "No" because values.coerce reads "None" as
    unknown, like canon_lighting). Anything else -> None."""
    raw = str(text or "").strip()
    if re.fullmatch(r"(?:none|n/?a|no|not supported)\b.*|[-－—]", raw, re.I):
        return "No"
    body = re.sub(r"\([^)]*\)", " ", raw)
    pairs = []
    # "2 x 120/140mm": one count, alternative sizes.
    for count, sizes in re.findall(rf"(\d{{1,2}})\s*[x×*]\s*({_FAN_SIZES}(?:\s*/\s*{_FAN_SIZES}(?!\d|\s*[x×*]))*)(?!\d)",
                                   body, re.I):
        pairs += [(count, size) for size in re.findall(r"\d+", sizes)]
    # "120mm x 2" (size first)
    pairs += [(count, size) for size, count in
              re.findall(rf"(?<!\d)({_FAN_SIZES})\s*mm\s*[x×]\s*(\d{{1,2}})(?!\d)", body, re.I)]
    if pairs:
        out: list[str] = []
        for count, size in pairs:
            item = f"{int(count)} x {size} mm"
            if item not in out:
                out.append(item)
        return ", ".join(out)
    single = re.fullmatch(rf"\s*({_FAN_SIZES})\s*mm\s*", body, re.I)
    return f"{single.group(1)} mm" if single else None


def radiator_sizes(text) -> set[int]:
    """'120 / 140 / 240 / 280 / 360mm (52mm thickness)' -> {120, 140, 240, 280, 360}."""
    body = re.sub(r"\([^)]*\)", " ", str(text or ""))
    return {int(n) for n in re.findall(r"(?<!\d)(120|140|240|280|360|420|480)(?!\d)", body)}


def psu_length(text) -> int | None:
    """Depth of a PSU from its dimension cell.

    '140(L) x 150(W) x 86(H)' -> 140 (the L figure); unlabeled triples are
    read only when the two standard faces are present (ATX 150 x 86, SFX
    125 x 63.5, SFX-L 125 x 63.5), so the remaining figure IS the depth."""
    text = str(text or "")
    labeled = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:mm)?\s*\(\s*L\s*\)", text, re.I)
    if labeled:
        return int(round(float(labeled.group(1))))
    numbers = [float(n) for n in re.findall(r"\d{2,3}(?:\.\d+)?", text)][:3]
    if len(numbers) != 3:
        return None
    for faces in ((150.0, 86.0), (125.0, 63.5), (125.0, 63.0), (125.0, 64.0)):
        rest = list(numbers)
        if all(face in rest and not rest.remove(face) for face in faces):
            return int(round(rest[0]))
    return None


# PSU connector line -> schema field. Order matters: the first pattern that
# matches a line wins ("12V-2x6 (12+4) pin" must not read as an 8-pin).
_PSU_CONNECTORS = (
    ("pcie16_connectors", r"12\s*V[\s\-–]*2\s*[x×]\s*6|\b16[\s-]*pin\b.*pci|pci.*\b16[\s-]*pin\b|12\+4"),
    ("pcie12_connectors", r"12\s*VHPWR"),
    ("pcie62_connectors", r"6\s*\+\s*2"),
    ("pcie6_connectors", r"pci[\s-]*e?.*\b6[\s-]*pin|\b6[\s-]*pin\b.*pci"),
    ("pcie8_connectors", r"pci[\s-]*e?.*\b8[\s-]*pin|\b8[\s-]*pin\b.*pci"),
    ("eps8_connectors", r"\beps\b|\bcpu\b|4\s*\+\s*4"),
    ("atx4_connectors", r"\b24\b|\bmb\b|\batx\b.*\b(?:20\+4|24)"),
    ("sata_connectors", r"\bsata\b"),
    ("molex4_connectors", r"molex|pata|peripheral"),
)


def psu_connector_counts(lines) -> dict[str, int]:
    """['1 x MB 24(20+4) Pin', '6 x 8(6+2) Pin PCI-E', '10 x SATA'] -> counts.

    Only called on a manufacturer's complete connector list, so the PCIe
    kinds the list does not name are 0 (the PSU has none of them), not
    unknown. A line with no leading count is skipped."""
    counts: dict[str, int] = {}
    for line in lines:
        line = str(line or "")
        count = re.match(r"\s*(\d{1,2})\s*(?:x|pcs?\b|×)", line, re.I)
        if not count:
            continue
        for field, pattern in _PSU_CONNECTORS:
            if re.search(pattern, line, re.I):
                counts[field] = counts.get(field, 0) + int(count.group(1))
                break
    if counts:
        for field in ("pcie62_connectors", "pcie6_connectors"):
            counts.setdefault(field, 0)
        # 12V-2x6 is the revised 12VHPWR plug and retailers file one under
        # the other's name, so neither is zeroed while the other is present.
        if not counts.get("pcie12_connectors"):
            counts.setdefault("pcie16_connectors", 0)
        if not counts.get("pcie16_connectors"):
            counts.setdefault("pcie12_connectors", 0)
    return counts
