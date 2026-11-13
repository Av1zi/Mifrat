"""python -m scraper.extract [--dry-run] [--limit N] [--offline] [--audit N] [--sweep]"""

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
    parser.add_argument("--sweep", action="store_true",
                        help="stamp entries no product reaches, drop those unreached for 14+ days")
    args = parser.parse_args()
    if args.sweep:
        from .store import sweep_store

        result = sweep_store()
        print("[extract] sweep: " + ", ".join(f"{k}={v}" for k, v in result.items()
                                               if k != "dropped_keys"))
        for key in result["dropped_keys"]:
            print(f"[extract] dropped unreached entry {key}")
        return 0
    summary = run(limit=args.limit, dry_run=args.dry_run, offline=args.offline, audit=args.audit)
    if summary.get("daily_quota"):
        return 3                   # per-day quota spent: nothing more to ask today
    return 1 if summary.get("stopped") else 0


if __name__ == "__main__":
    sys.exit(main())
