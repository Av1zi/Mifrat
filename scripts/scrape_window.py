"""Night window for scheduled cloud scrapes (owner 2026-11-09, extended 2026-11-13).

Aim for 23:00-07:00 Israel time. GitHub starts crons hours late, so a late
run may still start until the HARD cutoff at 09:00 Israel; from 09:00 to 23:00
a scheduled run skips and the vendor shows yesterday's prices (stale-forward).

    python scripts/scrape_window.py allowed     exit 0 inside 23:00-09:00 Israel
    python scripts/scrape_window.py sleep-cap   seconds until 06:00 Israel (0 past
                                                it): the random start delay ends
                                                there, so the scrape is done by 07:00
    python scripts/scrape_window.py --self-test

Stdlib only (the schedule gate has no setup-python). MIFRAT_NOW (ISO) fakes the clock.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ISRAEL = ZoneInfo("Asia/Jerusalem")
NIGHT_START_HOUR = 23
TARGET_HOUR = 6        # soft: the random delay ends by 06:00
CUTOFF_HOUR = 9        # hard: no scheduled scrape starts at or after 09:00


def _daytime(local: datetime, end_hour: int) -> bool:
    return end_hour <= local.hour < NIGHT_START_HOUR


def allowed(now: datetime) -> bool:
    return not _daytime(now.astimezone(ISRAEL), CUTOFF_HOUR)


def sleep_cap(now: datetime) -> int:
    local = now.astimezone(ISRAEL)
    if _daytime(local, TARGET_HOUR):
        return 0
    day = local.date() + timedelta(days=1) if local.hour >= NIGHT_START_HOUR else local.date()
    target = datetime(day.year, day.month, day.day, TARGET_HOUR, tzinfo=ISRAEL)
    return max(0, int((target - now).total_seconds()))


def _now() -> datetime:
    raw = os.environ.get("MIFRAT_NOW")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(timezone.utc)


def self_test() -> int:
    def at(iso: str) -> datetime:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))

    cases = [
        # Winter, UTC+2.
        ("23:07 runs", allowed(at("2026-11-13T21:07:00Z")), True),
        ("03:46 runs (2026-11-13 late cron)", allowed(at("2026-11-13T01:46:00Z")), True),
        ("08:59 still runs", allowed(at("2026-11-13T06:59:00Z")), True),
        ("09:00 skips", allowed(at("2026-11-13T07:00:00Z")), False),
        ("12:20 skips (2026-11-12 fallback)", allowed(at("2026-11-12T10:20:00Z")), False),
        ("22:59 skips", allowed(at("2026-11-13T20:59:00Z")), False),
        ("23:07 delay ends 06:00", sleep_cap(at("2026-11-13T21:07:00Z")), 24780),
        ("03:46 delay ends 06:00", sleep_cap(at("2026-11-13T01:46:00Z")), 8040),
        ("06:30 no delay", sleep_cap(at("2026-11-13T04:30:00Z")), 0),
        # Summer, UTC+3: 21:07 UTC = 00:07 Israel.
        ("summer 00:07 runs", allowed(at("2026-07-12T21:07:00Z")), True),
        ("summer 09:00 skips", allowed(at("2026-07-13T06:00:00Z")), False),
        ("summer 00:07 delay", sleep_cap(at("2026-07-12T21:07:00Z")), 21180),
    ]
    fails = [(label, got, want) for label, got, want in cases if got != want]
    for label, got, want in fails:
        print(f"FAIL {label}: got {got!r}, want {want!r}")
    print(f"[scrape-window] self-test {'pass' if not fails else 'FAILED'} ({len(cases)} cases)")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode == "--self-test":
        return self_test()
    if mode == "allowed":
        return 0 if allowed(_now()) else 1
    if mode == "sleep-cap":
        print(sleep_cap(_now()))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
