"""Build scraper/specs/tables/mb_cpu_support.json: chipset -> CPU families.

A board's CPU support follows from its socket + chipset, which ~98% of our
boards already carry; retailers rarely print it (cpu_support was 15% filled,
Ivory only, and inconsistent: B550 boards said just "Ryzen 3000").

AMD side: read from AMD's own CPU pages, which list "Supporting Chipsets".
One representative CPU per family is fetched through scraper/mfr's polite
client (robots obeyed, 1 req/s, cached, first 403/429 stops) and the lists
are inverted to chipset -> families. A family whose page is missing or lists
no chipsets is simply absent - never typed in from memory.

Intel side: intel.com / ARK answer 403 to automated clients (stop signal,
scraper/mfr/README.md), so the per-chipset generations come from the
INTEL_CHIPSETS block below, each row citing the published source it was
copied from.

Run: python scripts/build_mb_cpu_support.py   (writes the table; normalize
then fills `cpu_support` via derive.py's motherboard.chipset_table rule)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.mfr import amd  # noqa: E402
from scraper.mfr.client import Blocked, PoliteClient  # noqa: E402

OUT = ROOT / "scraper" / "specs" / "tables" / "mb_cpu_support.json"

# (family label, slug of one representative CPU page). Ordered newest first
# within a socket so the joined string reads like vendor spec sheets.
AMD_FAMILIES = [
    ("Ryzen 9000", "amd-ryzen-7-9700x"),
    ("Ryzen 8000", "amd-ryzen-7-8700g"),
    ("Ryzen 7000", "amd-ryzen-7-7700x"),
]
# AM4 CPU pages print no chipset list; AM4 rows come from the chipset page's
# compatibility matrix instead (build_am4). Threadripper is left out: the
# sitemap only has the PRO 9000WX pages, and a TRX50 row listing only
# "PRO 9000WX" would present a partial list as complete. Older Ryzen pages
# are not in AMD's sitemap any more, so those chipsets stay out of the table.

_SOURCE_LGA1700 = "https://en.wikipedia.org/wiki/LGA_1700 (CPU support row; Intel 14th Gen = Raptor Lake Refresh)"
_SOURCE_LGA1200 = "https://en.wikipedia.org/wiki/LGA_1200 (chipset table)"
_SOURCE_LGA1151 = "https://en.wikipedia.org/wiki/List_of_Intel_chipsets (100/200/300 Series introductions)"
_SOURCE_LGA1851 = "https://en.wikipedia.org/wiki/LGA_1851"

# chipset -> (families, BIOS note or None, source). Copied from the cited
# pages on 2026-10-20; extend only from a published source.
INTEL_CHIPSETS: dict[str, tuple[list[str], str | None, str]] = {
    **{c: (["Core Ultra 200S (Series 2)"], None, _SOURCE_LGA1851)
       for c in ("Z890", "B860", "H810", "W880", "Q870")},
    **{c: (["Core 14th Gen", "Core 13th Gen", "Core 12th Gen"], None, _SOURCE_LGA1700)
       for c in ("Z790", "H770", "B760")},
    **{c: (["Core 14th Gen", "Core 13th Gen", "Core 12th Gen"],
           "13th/14th Gen may need a BIOS update", _SOURCE_LGA1700)
       for c in ("Z690", "H670", "B660", "H610", "W680", "Q670")},
    **{c: (["Core 11th Gen", "Core 10th Gen"], None, _SOURCE_LGA1200)
       for c in ("Z590", "H570", "B560", "H510", "Q570")},
    **{c: (["Core 11th Gen", "Core 10th Gen"], "11th Gen needs a BIOS update", _SOURCE_LGA1200)
       for c in ("Z490", "H470", "Q470", "W480")},
    **{c: (["Core 10th Gen"], None, _SOURCE_LGA1200) for c in ("B460", "H410")},
    **{c: (["Core 9th Gen", "Core 8th Gen"], None, _SOURCE_LGA1151)
       for c in ("Z390", "Z370", "H370", "B365", "B360", "H310", "Q370")},
    **{c: (["Core 7th Gen", "Core 6th Gen"], None, _SOURCE_LGA1151)
       for c in ("Z270", "H270", "B250", "Q270")},
    **{c: (["Core 6th Gen", "Core 7th Gen"], "7th Gen may need a BIOS update", _SOURCE_LGA1151)
       for c in ("Z170", "H170", "B150", "H110", "Q170")},
}


AM4_PAGE = "https://www.amd.com/en/products/processors/chipsets/am4.html"
# Column order of AMD's AM4 "which Ryzen processor is compatible" matrix.
AM4_COLUMNS = ["Athlon (Radeon Graphics)", "Ryzen 1000", "Ryzen 2000G", "Ryzen 2000",
               "Ryzen 3000G", "Ryzen 3000", "Ryzen 4000", "Ryzen 5000"]
_AM4_CHIPSETS = ("X570", "B550", "A520", "X470", "B450", "X370", "B350", "A320")
_AM4_CELL = re.compile(r"✓|\bX\b|Selective Beta BIOS update needed")


def build_am4(client) -> dict[str, dict]:
    """AMD's AM4 chipset x CPU-family matrix, parsed from the chipset page."""
    page = client.get(AM4_PAGE) or ""
    text = " ".join(re.sub(r"<[^>]+>", " ", page).split())
    start = text.rfind("Compatible with")
    end = text.find("Additional hardware", start)
    if start < 0 or end < 0:
        print("[am4] compatibility matrix not found - skipped")
        return {}
    body = text[start + len("Compatible with"):end]
    pattern = r"\b(" + "|".join(_AM4_CHIPSETS) + r")\b"
    parts = re.split(pattern, body)
    rows: dict[str, dict] = {}
    for name, cells_text in zip(parts[1::2], parts[2::2]):
        cells = _AM4_CELL.findall(cells_text)
        if len(cells) != len(AM4_COLUMNS):
            print(f"[am4] {name}: {len(cells)} cells, expected {len(AM4_COLUMNS)} - skipped")
            continue
        families, beta = [], []
        for family, cell in zip(AM4_COLUMNS, cells):
            if cell == "X":
                continue
            families.append(f"AMD {family}")
            if cell != "✓":
                beta.append(family)
        families.reverse()  # newest first, like the other rows
        rows[name] = {"families": families,
                      "bios_note": (f"{' / '.join(beta)} only with a beta BIOS on selected boards"
                                    if beta else None),
                      "sources": [AM4_PAGE]}
        print(f"[am4] {name}: {', '.join(families)}")
    return rows


def _amd_url_index(client) -> dict[str, str]:
    page = client.get(amd.SITEMAP) or ""
    return {slug: url for url, slug in amd._URL_RE.findall(page)}


def _supporting_chipsets(page: str) -> list[str]:
    for label, value in amd._pairs(page).items():
        if "chipset" in label:
            return [c.strip() for c in re.split(r"[,/]", value) if c.strip()]
    return []


def build_amd(client) -> dict[str, dict]:
    urls = _amd_url_index(client)
    by_chipset: dict[str, dict] = {}
    for family, slug in AMD_FAMILIES:
        url = urls.get(slug)
        if not url:
            print(f"[amd] {family}: no page for {slug} in the sitemap - skipped")
            continue
        page = client.get(url) or ""
        chipsets = _supporting_chipsets(page)
        print(f"[amd] {family}: {', '.join(chipsets) or 'no chipset list'}")
        for chipset in chipsets:
            row = by_chipset.setdefault(chipset, {"families": [], "sources": []})
            row["families"].append(f"AMD {family}")
            row["sources"].append(url)
    return by_chipset


def main() -> int:
    client = PoliteClient(amd.BRAND, amd.BASE_URL)
    try:
        amd_rows = build_amd(client)
        am4_rows = build_am4(client)
    except Blocked as exc:
        print(f"[amd] blocked: {exc} - stopping, table not written")
        return 1
    merged: dict[str, tuple[list[str], str | None, list[str]]] = {}
    for chipset, row in amd_rows.items():
        merged[chipset] = (row["families"], None, sorted(set(row["sources"])))
    for chipset, row in am4_rows.items():
        merged[chipset] = (row["families"], row["bios_note"], row["sources"])
    for chipset, (families, note, source) in INTEL_CHIPSETS.items():
        merged[chipset] = ([f"Intel {f}" for f in families], note, [source])

    rows = {}
    for chipset, (families, note, sources) in sorted(merged.items()):
        rows[chipset] = {"cpu_support": support_text(families, note),
                         "_families": families, "_source": sources}
    table = {
        "_source": "AMD CPU pages ('Supporting Chipsets') + AMD AM4 chipset matrix; "
                   "Intel rows cite their page",
        "_built": date.today().isoformat(),
        "rows": rows,
    }
    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} chipsets)")
    return 0


def support_text(families: list[str], note: str | None) -> str:
    """'AMD Ryzen 9000 / 8000 / 7000' - the shared vendor+line prefix said once."""
    parts: list[str] = []
    previous_prefix = None
    for family in families:
        match = re.match(r"^(.*?)(\d[\w ()]*)$", family)
        prefix, rest = (match.group(1), match.group(2)) if match else (family, "")
        if prefix == previous_prefix and rest:
            parts.append(rest.strip())
        else:
            parts.append(family)
        previous_prefix = prefix
    text = " / ".join(parts)
    return f"{text} ({note})" if note else text


if __name__ == "__main__":
    raise SystemExit(main())
