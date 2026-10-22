"""python -m scraper.icecat [--brand B ...] [--limit N] [--dry-run] [--offline] [--trust]"""

from __future__ import annotations

import argparse
import sys

from .runner import run
from .trust import report


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper.icecat",
                                     description="Fetch Open Icecat sheets (polite, cached).")
    parser.add_argument("--brand", action="append",
                        help="only this catalog brand (repeatable, case-insensitive)")
    parser.add_argument("--limit", type=int, help="ask at most N lookups this run")
    parser.add_argument("--dry-run", action="store_true", help="count lookups; fetch nothing")
    parser.add_argument("--offline", action="store_true",
                        help="re-parse cached answers only; fetch nothing")
    parser.add_argument("--trust", action="store_true",
                        help="per-field agreement of data/icecat with sourced catalog values")
    args = parser.parse_args()
    if args.trust:
        return report()
    brands = {b.lower() for b in args.brand} if args.brand else None
    summary = run(brands=brands, limit=args.limit, dry_run=args.dry_run, offline=args.offline)
    return 1 if summary.get("blocked") else 0


if __name__ == "__main__":
    sys.exit(main())
