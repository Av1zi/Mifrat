"""
Collapse old per-day raw snapshots so the working tree stops growing.

Retention policy (matches pc-parts-il-plan.md §11 "90-day raw retention
plus later downsampling"):
  - Day-dirs newer than --keep-daily (default 90) days: untouched.
  - Older than that: keep the LATEST day-dir of each ISO week, remove the
    rest of that week's day-dirs.
  - Older than --keep-weekly (default 365) days: keep the latest
    week-representative of each calendar month, remove the rest.

Only data/raw/YYYY-MM-DD/ dirs are candidates. data/raw/detail/ and any
non-date entries are never touched. The normalizer only reads the last
STALE_LOOKBACK_DAYS (14), so nothing removed here was ever read by it.

Note on what this actually saves: git history keeps every blob, so this
does NOT shrink clone size (that would need history rewriting). It caps
the CHECKOUT size (~2.3MB/day -> unbounded without this) and keeps the
raw listing manageable.

Usage (repo root):
  python scraper/downsample.py [--dry-run] [--keep-daily N] [--keep-weekly M]
"""

import argparse
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SKIP_NAMES = {"detail"}


def _day_dirs() -> list[date]:
    days = []
    if not RAW_DIR.is_dir():
        return days
    for child in RAW_DIR.iterdir():
        if child.name in SKIP_NAMES or not child.is_dir():
            continue
        if not DAY_RE.match(child.name):
            continue
        try:
            days.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return sorted(days)


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def plan_removals(today: date, keep_daily: int, keep_weekly: int) -> tuple[list[date], list[date]]:
    """Return (keep, remove) day lists."""
    days = _day_dirs()
    daily_cutoff = today - timedelta(days=keep_daily)
    weekly_cutoff = today - timedelta(days=keep_weekly)

    keep: set[date] = set()
    remove: set[date] = set()

    # Recent history: keep everything.
    recent = [d for d in days if d > daily_cutoff]
    keep.update(recent)

    # Weekly tier: one (latest) day per ISO week.
    by_week: dict[tuple[int, int], list[date]] = {}
    for d in days:
        if d <= daily_cutoff and d > weekly_cutoff:
            by_week.setdefault(d.isocalendar()[:2], []).append(d)
    for week_days in by_week.values():
        week_days.sort()
        keep.add(week_days[-1])
        remove.update(week_days[:-1])

    # Monthly tier: one (latest) day per calendar month.
    by_month: dict[tuple[int, int], list[date]] = {}
    for d in days:
        if d <= weekly_cutoff:
            by_month.setdefault((d.year, d.month), []).append(d)
    for month_days in by_month.values():
        month_days.sort()
        keep.add(month_days[-1])
        remove.update(month_days[:-1])

    return sorted(keep), sorted(remove)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be removed without deleting")
    ap.add_argument("--keep-daily", type=int, default=90)
    ap.add_argument("--keep-weekly", type=int, default=365)
    args = ap.parse_args()

    today = date.today()
    keep, remove = plan_removals(today, args.keep_daily, args.keep_weekly)

    freed = sum(_dir_size(RAW_DIR / d.isoformat()) for d in remove)
    print(f"[downsample] today={today} day-dirs={len(keep) + len(remove)} "
          f"keep={len(keep)} remove={len(remove)} (~{freed / 1e6:.1f} MB)")

    if not remove:
        print("[downsample] nothing to remove")
        return 0

    for d in remove:
        print(f"  rm data/raw/{d.isoformat()}/")

    if args.dry_run:
        print("[downsample] dry run — no changes made")
        return 0

    for d in remove:
        target = RAW_DIR / d.isoformat()
        # git rm stages the deletion; plain rmtree fallback for untracked dirs.
        r = subprocess.run(["git", "rm", "-r", "-q", str(target)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            import shutil
            shutil.rmtree(target, ignore_errors=True)
            print(f"  [warn] {target} not tracked, removed from worktree only")

    # Print surviving day-dirs so the workflow can pass them (or nothing)
    # to git_commit_push.sh — it only needs the REMOVED paths.
    print("[downsample] removed paths:")
    for d in remove:
        print(f"data/raw/{d.isoformat()}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
