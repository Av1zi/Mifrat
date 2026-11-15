"""The scrape night: which night a moment belongs to (see GLOSSARY.md).

A night runs from 21:00 UTC to the next 21:00 UTC (the night window opens at
23:00/00:00 Israel), and is named by the UTC date it ends on:

    scrape_night(2026-11-11 21:40 UTC) == 2026-11-12
    scrape_night(2026-11-12 02:10 UTC) == 2026-11-12
    scrape_night(2026-11-12 20:59 UTC) == 2026-11-12

so a crawl that starts before midnight UTC and one after it share one date.
A crawl's night is the night of its START.

Stdlib only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

NIGHT_START_UTC_HOUR = 21
NIGHT_OFFSET = timedelta(hours=24 - NIGHT_START_UTC_HOUR)


def scrape_night(at: datetime) -> date:
    """The scrape night `at` falls in. A naive datetime is read as UTC."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (at.astimezone(timezone.utc) + NIGHT_OFFSET).date()


def nights_between(first: datetime, last: datetime) -> int:
    """Nights from `first` to `last`, both counted: same night = 1."""
    return (scrape_night(last) - scrape_night(first)).days + 1
