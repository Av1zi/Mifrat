"""python -m scraper.xref <site> [--limit N] [--dry-run] [--offline] [--trust]"""

from __future__ import annotations

import argparse
import sys

from .runner import SITES, run


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scraper.xref",
                                     description="Foreign retailer spec tables (polite, cached).")
    parser.add_argument("site", choices=SITES)
    parser.add_argument("--limit", type=int, help="at most N searches this run")
    parser.add_argument("--dry-run", action="store_true", help="count products; fetch nothing")
    parser.add_argument("--offline", action="store_true", help="re-parse the cache only")
    parser.add_argument("--trust", action="store_true",
                        help="compare the site's values with sourced catalog values; fetch nothing")
    args = parser.parse_args()
    if args.trust:
        from ..icecat.trust import report
        from .store import DATA_ROOT

        return report(DATA_ROOT / args.site, label=f"xref:{args.site}", disabled={}, reviewed={})
    summary = run(args.site, limit=args.limit, dry_run=args.dry_run, offline=args.offline)
    return 1 if summary.get("blocked") else 0


if __name__ == "__main__":
    sys.exit(main())
