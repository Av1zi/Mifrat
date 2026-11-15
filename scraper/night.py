"""The scrape night: which night a moment belongs to (see GLOSSARY.md).

A night runs from 21:00 UTC to the next 21:00 UTC (the night window opens at
23:00/00:00 Israel), and is named by the UTC date it ends on:

    scrape_night(2026-11-11 21:40 UTC) == 2026-11-12
    scrape_night(2026-11-12 02:10 UTC) == 2026-11-12
    scrape_night(2026-11-12 20:59 UTC) == 2026-11-12

so a crawl that starts before midnight UTC and one after it share one date,
and a snapshot folder data/raw/<night>/ holds one night. A crawl's night is
the night of its START: every runner computes it once, before crawling.

Until 2026-11-15 folders were named by the UTC date a run started, so 1PC's
23:20 UTC (+1 h) timer put two nights in one folder and the second overwrote
the first. Folders from before the switch keep their UTC names.

One snapshot per vendor-night: a second run in the same night (a fallback
timer, a forced re-run) replaces the night's file only when it holds at
least as many rows; it never appends. A thinner second crawl is dropped.

    python scraper/night.py                      # tonight's date, YYYY-MM-DD
    python scraper/night.py install PART FINAL   # PART -> FINAL if not thinner
    python scraper/night.py --self-test

MIFRAT_NIGHT (YYYY-MM-DD) pins the night, so a wrapper script and the
run_spider.py it calls can never disagree; MIFRAT_NOW (ISO) fakes the clock.
Stdlib only.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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


def _now() -> datetime:
    raw = os.environ.get("MIFRAT_NOW")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(timezone.utc)


def tonight() -> str:
    """This run's night as YYYY-MM-DD: MIFRAT_NIGHT if set, else from the clock."""
    pinned = os.environ.get("MIFRAT_NIGHT", "").strip()
    if pinned:
        return date.fromisoformat(pinned).isoformat()
    return scrape_night(_now()).isoformat()


def _rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("rb") as f:
        return sum(1 for line in f if line.strip())


def install(part: Path, final: Path) -> tuple[str, int, int]:
    """Move a finished crawl's `part` file onto the night's `final` file.

    Returns (action, part rows, final rows before): "installed" (no file yet,
    or the new crawl is at least as complete), "kept" (the night already has
    a fuller crawl: `part` is deleted) or "empty" (no rows: `part` deleted,
    `final` untouched).
    """
    new, old = _rows(part), _rows(final)
    if new == 0:
        part.unlink(missing_ok=True)
        return "empty", new, old
    if old > new:
        part.unlink()
        return "kept", new, old
    part.replace(final)
    return "installed", new, old


def self_test() -> int:
    def at(iso: str) -> datetime:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))

    cases = [
        # 1PC 2026-11-14: two runs, two nights, used to share one folder.
        ("1PC 00:17 UTC 11-14", scrape_night(at("2026-11-14T00:17:00Z")), date(2026, 11, 14)),
        ("1PC 23:51 UTC 11-14", scrape_night(at("2026-11-14T23:51:00Z")), date(2026, 11, 15)),
        # One night: TMS before midnight, KSP and the cloud fallback after.
        ("TMS 21:15 UTC", scrape_night(at("2026-11-14T21:15:00Z")), date(2026, 11, 15)),
        ("KSP 01:30 UTC", scrape_night(at("2026-11-15T01:30:00Z")), date(2026, 11, 15)),
        ("cloud fallback 05:47", scrape_night(at("2026-11-15T05:47:00Z")), date(2026, 11, 15)),
        ("20:59 is still that night", scrape_night(at("2026-11-15T20:59:59Z")), date(2026, 11, 15)),
        ("21:00 starts the next", scrape_night(at("2026-11-15T21:00:00Z")), date(2026, 11, 16)),
        ("naive is UTC", scrape_night(datetime(2026, 11, 15, 22, 0)), date(2026, 11, 16)),
        ("Israel offset", scrape_night(at("2026-11-15T23:30:00+02:00")), date(2026, 11, 16)),
        ("same night = 1", nights_between(at("2026-11-15T01:00:00Z"), at("2026-11-15T20:00:00Z")), 1),
        ("3 nights", nights_between(at("2026-11-13T05:00:00Z"), at("2026-11-15T05:00:00Z")), 3),
    ]
    os.environ.pop("MIFRAT_NIGHT", None)
    os.environ["MIFRAT_NOW"] = "2026-11-15T22:10:00Z"
    cases.append(("tonight() from MIFRAT_NOW", tonight(), "2026-11-16"))
    os.environ["MIFRAT_NIGHT"] = "2026-11-15"
    cases.append(("MIFRAT_NIGHT pins it", tonight(), "2026-11-15"))
    for name in ("MIFRAT_NOW", "MIFRAT_NIGHT"):
        os.environ.pop(name, None)

    with tempfile.TemporaryDirectory() as tmp:
        final, part = Path(tmp) / "onepc.jsonl", Path(tmp) / "onepc.jsonl.part"

        def crawl(path: Path, rows: int) -> None:
            path.write_text("".join(f'{{"n": {i}}}\n' for i in range(rows)), encoding="utf-8")

        crawl(part, 2000)
        cases.append(("first crawl of the night", install(part, final), ("installed", 2000, 0)))
        crawl(part, 1400)
        cases.append(("thinner second crawl is dropped", install(part, final), ("kept", 1400, 2000)))
        cases.append(("night file untouched", _rows(final), 2000))
        cases.append(("part removed", part.exists(), False))
        crawl(part, 2000)
        cases.append(("equal second crawl replaces", install(part, final), ("installed", 2000, 2000)))
        crawl(part, 2100)
        cases.append(("fuller second crawl replaces", install(part, final), ("installed", 2100, 2000)))
        part.write_text("\n\n", encoding="utf-8")
        cases.append(("empty crawl", install(part, final), ("empty", 0, 2100)))
        cases.append(("never appends", _rows(final), 2100))

    failed = [f"{name}: got {got!r}, want {want!r}" for name, got, want in cases if got != want]
    for line in failed:
        print(f"[night] FAIL {line}")
    if failed:
        return 1
    print(f"[night] self-test passed ({len(cases)} cases)")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return self_test()
    if argv[:1] == ["install"] and len(argv) == 3:
        action, new, old = install(Path(argv[1]), Path(argv[2]))
        if action == "kept":
            print(f"[night] kept {argv[2]}: tonight's earlier crawl has {old} rows, "
                  f"this one {new}", file=sys.stderr)
        elif action == "empty":
            print(f"[night] {argv[1]} has no rows; {argv[2]} untouched", file=sys.stderr)
            return 1
        else:
            print(f"[night] {argv[2]}: {new} rows" + (f" (replaced {old})" if old else ""))
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    print(tonight())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
