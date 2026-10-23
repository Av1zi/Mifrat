#!/usr/bin/env python
"""
check_xref_fixtures.py - offline parser checks on real pages saved from the Nano
(scraper/fixtures/<site>/; the cloud cannot reach these sites).

A parser that stops reading a saved page, or starts joining on the wrong key,
fails here before it can write a wrong value into data/.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.xref import ldlc  # noqa: E402

FIXTURES = ROOT / "scraper" / "fixtures"
failures = 0


def check(label: str, got, want) -> None:
    global failures
    if got != want:
        failures += 1
        print(f"FAIL {label}: got {got!r}, want {want!r}")


def page(site: str, name: str) -> str:
    return (FIXTURES / site / name).read_text(encoding="utf-8", errors="replace")


# LDLC: Noctua NH-U12A (EAN 9010018000160; the "Model" row is "NOCTUA NH-U12A").
parsed = ldlc.parse_page(page("ldlc", "product_NH-U12A.html"))
check("ldlc ean", parsed["ean"], "9010018000160")
check("ldlc model code", parsed["mpn"], "NH-U12A")
check("ldlc join keys", ldlc.page_keys(parsed), {"9010018000160", "NHU12A"})
check("ldlc cooler specs", ldlc.specs_for("cooler_air", parsed["rows"]), {
    "color": "Beige", "lighting": "No", "fan_size_mm": 120, "fan_rpm_min": 450,
    "fan_rpm_max": 2000, "noise_db": 22.6, "airflow_cfm": 60.1, "height_mm": 158,
    "fanless": False})
check("ldlc sockets are never read (one socket printed for many)",
      "sockets" in ldlc.specs_for("cooler_air", parsed["rows"]), False)
check("ldlc search tiles", ldlc.tile_urls(page("ldlc", "search_NH-U12A.html")),
      ["https://www.ldlc.com/en/product/PB00272562.html",
       "https://www.ldlc.com/en/product/PB00467328.html"])
check("ldlc search with no product is a miss", ldlc.tile_urls(page("ldlc", "search_CP-9020247-EU.html")), [])
check("ldlc search url", ldlc.search_url("NH-U12A"), "https://www.ldlc.com/en/search/NH-U12A/")

if failures:
    print(f"[xref-fixtures] {failures} failure(s)")
    sys.exit(1)
print("[xref-fixtures] saved pages parse as expected")
