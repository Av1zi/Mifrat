"""python -m scraper.extract [--dry-run] [--limit N] [--offline] [--audit N]"""

from __future__ import annotations

import argparse
import sys

from .runner import run


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper.extract",
                                     description="Verified AI extraction of still-empty spec fields.")
    parser.add_argument("--dry-run", action="store_true",
                        help="count products / fields and estimate the cost; no requests")
    parser.add_argument("--limit", type=int, help="at most N products this run")
    parser.add_argument("--offline", action="store_true", help="answers from the cache only")
    parser.add_argument("--audit", type=int, metavar="N",
                        help="measure precision on N products' already-sourced fields")
    args = parser.parse_args()
    summary = run(limit=args.limit, dry_run=args.dry_run, offline=args.offline, audit=args.audit)
    return 1 if summary.get("stopped") else 0


if __name__ == "__main__":
    sys.exit(main())
