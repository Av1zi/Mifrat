"""
scraper/mfr - manufacturer spec pages as a Tier-0.5 source (plan Phase 1d).

The retailers we scrape publish thin spec tables; the brand's own product page
usually states the numbers a buyer needs (case clearances, fan airflow, PSU
connectors). This package fetches those pages politely, extracts schema fields
and writes them to data/mfr/<brand>.json. specs/build.py merges that JSON as
the `manufacturer` tier: above the retailer's vendor payload, below the
hand-edited override file and the PCPartPicker reference rows.

Only brands that pass the feasibility checklist have a module here (see
mfr/README.md for the per-brand verdicts, including the ones that failed).

    python -m scraper.mfr <brand> [--limit N] [--dry-run]
    python -m scraper.mfr --list

Layout:
    client.py    PoliteClient (robots, 1 req/s, browser headers, 403/429 = stop)
    common.py    HTML row extraction, typed-value helpers, product identity keys
    runner.py    brand-independent loop: match catalog products -> fetch -> write
    <brand>.py   index() + parse() for one brand
    store.py     reads data/mfr/*.json for the spec merge
"""

from __future__ import annotations

BRANDS = ("amd", "antec", "asus", "coolermaster", "corsair", "nzxt", "thermalright", "bequiet", "lianli")
