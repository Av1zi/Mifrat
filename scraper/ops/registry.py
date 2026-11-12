"""Which vendors are scraped, from where, and what a healthy crawl looks like.

The one place these expectations live: `run_spider.py` warns below
`min_rows`, the ops report flags a crawl under it as suspect, and the admin
page / Worker alert rules read the same values from data/ops/status.json.

`min_rows` are the run_spider warning floors (~75-80% of each vendor's steady
state). `due_utc` is when the night's crawl should have landed: home vendors
finish by ~02:30 UTC (KSP last), cloud vendors by the scrape-cloud fallback
(02:47 UTC + up to 3h of spread).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Night window (decisions.md, 2026-11-09): every scheduled scrape lands
# 23:00-07:00 Israel time = 21:00-04:00 UTC in both seasons.
NIGHT_START_UTC_HOUR = 21
NIGHT_END_UTC_HOUR = 4


@dataclass(frozen=True)
class Vendor:
    id: str            # spider name = raw file stem (data/raw/<day>/<id>.jsonl)
    label: str
    host: str          # "home" (Nano) or "cloud" (GitHub Actions)
    active: bool
    min_rows: int
    due_utc: str       # HH:MM UTC by which the night's crawl should exist
    dropped: str | None = None


VENDORS: dict[str, Vendor] = {
    v.id: v
    for v in (
        Vendor("tms", "TMS", "home", True, 1800, "04:00"),
        Vendor("onepc", "1PC", "home", True, 1600, "04:00"),
        Vendor("ksp", "KSP", "home", True, 800, "04:00"),
        Vendor("ivory", "Ivory", "cloud", True, 500, "06:00"),
        Vendor("yahav", "YahavPC", "cloud", True, 800, "06:00"),
        Vendor("plonter", "Plonter", "cloud", False, 1800, "06:00", dropped="2026-09-29"),
    )
}

# Raw `vendor_id` -> spider name (1PC rows say "1pc", the file is onepc.jsonl).
VENDOR_OF_ID = {"1pc": "onepc", "onepc": "onepc"}


def min_counts() -> dict[str, int]:
    """Per-spider minimum-item warning floors (run_spider.py)."""
    return {v.id: v.min_rows for v in VENDORS.values()}


def as_json() -> list[dict]:
    return [asdict(v) for v in VENDORS.values()]
