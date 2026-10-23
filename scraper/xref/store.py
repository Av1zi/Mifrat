"""
xref/store.py - reads data/xref/<site>/<brand>.json for the spec merge.

Vendor tier (`vendor`): a foreign retailer's table counts like one of ours;
the brand's page, Open Icecat and the reference rows outrank it. Exact
MPN / EAN keys only, as in mfr/store.py.
"""

from __future__ import annotations

from pathlib import Path

from ..mfr.store import facts_from, load_index
from ..specs.merge import TIER_VENDOR, Fact

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "xref"
SITES = ("overclockers",)

# Fields that disagreed with sourced values on more than 3% of 10+ products
# (`python -m scraper.xref <site> --trust`, catalog built without the site):
# parsed and kept in data/xref, never merged. Overclockers' tables are written
# for its own catalogue (box sizes, shop-defined case types, per-fan rather
# than per-kit figures), so the rate is high for case and cooler geometry.
DISABLED: dict[str, dict[str, frozenset]] = {
    "overclockers": {
    "aio": frozenset({'lighting', 'sockets'}),
        "case": frozenset({'dimensions_mm', 'drive_bays_25', 'drive_bays_35', 'fan_bottom', 'fan_rear', 'fan_side', 'lighting', 'max_cooler_height_mm', 'radiator_support', 'type', 'weight_kg'}),
        "case_fan": frozenset({'airflow_cfm', 'noise_db', 'pwm', 'rpm_max', 'rpm_min', 'static_pressure_mmh2o'}),
        "cooler_air": frozenset({'airflow_cfm', 'color', 'fan_rpm_max', 'fan_rpm_min', 'fan_size_mm', 'height_mm', 'sockets'}),
    },
}


def facts_for(category: str | None, brand: str | None,
              part_numbers) -> dict[str, list[Fact]]:
    facts: dict[str, list[Fact]] = {}
    for site in SITES:
        directory = DATA_ROOT / site
        if not directory.is_dir():
            continue
        off = DISABLED.get(site, {}).get(category or "", frozenset())
        for key, value in facts_from(load_index(directory), category, brand, part_numbers, None,
                                     tier=TIER_VENDOR, source=f"xref:{site}",
                                     confidence=0.8).items():
            if key not in off:
                facts.setdefault(key, []).extend(value)
    return facts
