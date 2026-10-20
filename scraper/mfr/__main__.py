"""python -m scraper.mfr <brand> [--limit N] [--dry-run] [--offline] | --list"""

from __future__ import annotations

import argparse
import sys

from . import BRANDS
from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper.mfr",
                                     description="Fetch manufacturer spec pages (polite, cached).")
    parser.add_argument("brand", nargs="?", choices=BRANDS)
    parser.add_argument("--limit", type=int, help="fetch at most N pages this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="match catalog products to pages; fetch nothing")
    parser.add_argument("--offline", action="store_true",
                        help="re-parse cached pages only (any age); fetch nothing")
    parser.add_argument("--list", action="store_true", help="list supported brands")
    args = parser.parse_args()
    if args.list or not args.brand:
        print("supported brands:", ", ".join(BRANDS))
        return 0
    summary = run(args.brand, limit=args.limit, dry_run=args.dry_run, offline=args.offline)
    return 1 if summary.get("blocked") else 0


if __name__ == "__main__":
    sys.exit(main())
