"""Print the top unmapped vendor labels per category.

Evidence queue for `scraper/specs/labels.py`: every vendor detail-page label
that mapped to no schema field is counted by the last normalize run. This
script groups those gaps by category so the next mapping decision is made
from real pages (frequency first), never a guess.

Run: python -m scraper.specs.report_gaps [--top 30]
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GAPS_PATH = ROOT / "data" / "spec_gaps.json"
REPORT_PATH = ROOT / "data" / "site" / "spec_report.json"


def _load_gaps() -> list[dict]:
    if GAPS_PATH.is_file():
        try:
            data = json.loads(GAPS_PATH.read_text(encoding="utf-8"))
            gaps = data.get("gaps") if isinstance(data, dict) else data
            if isinstance(gaps, list) and gaps:
                return gaps
        except (OSError, ValueError):
            pass
    # Fallback: the compacted site report carries the same rows (capped).
    if REPORT_PATH.is_file():
        try:
            data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            return list(data.get("label_gaps") or [])
        except (OSError, ValueError):
            pass
    return []


def main() -> int:
    try:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    top = 30
    if "--top" in sys.argv:
        try:
            top = int(sys.argv[sys.argv.index("--top") + 1])
        except (IndexError, ValueError):
            pass
    gaps = _load_gaps()
    if not gaps:
        print("[gaps] no label gaps found — run normalize_and_match.py first "
              "(it writes data/spec_gaps.json)")
        return 0
    by_category: dict[str, list[dict]] = {}
    for gap in gaps:
        by_category.setdefault(str(gap.get("category") or ""), []).append(gap)
    print(f"[gaps] {len(gaps)} unmapped label rows across {len(by_category)} "
          "categories")
    for category in sorted(by_category):
        rows = sorted(by_category[category], key=lambda g: -int(g.get("count") or 0))
        total = sum(int(g.get("count") or 0) for g in rows)
        print(f"\n== {category} ({len(rows)} labels, {total} rows) ==")
        for gap in rows[:top]:
            sample = ", ".join((gap.get("products") or [])[:2])
            print(f"  {int(gap.get('count') or 0):>5}  {gap.get('label')}"
                  + (f"   [{sample}]" if sample else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
