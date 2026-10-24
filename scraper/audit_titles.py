"""Report title-quality problems in data/site/<category>.json.

Read-only; run after normalize_and_match.py. Not wired into CI.
    python scraper/audit_titles.py [--verbose]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "data" / "site"

CHECKS = {
    "trademark": lambda n: bool(re.search("[™®©]", n)),
    "processor_word": lambda n: bool(re.search(r"\bprocessor\b", n, re.I)),
    "series_word": lambda n: bool(re.search(r"\bseries\b", n, re.I)),
    "repeated_word": lambda n: bool(re.search(r"\b(\w{2,})\s+\1\b", n, re.I)),
    "too_short": lambda n: len(n) < 12,
    "too_long": lambda n: len(n) > 70,
    "upper_ti": lambda n: bool(re.search(r"\bTI\b", n)),
}


def main() -> int:
    verbose = "--verbose" in sys.argv
    total = Counter()
    for path in sorted(SITE.glob("*.json")):
        if path.name == "meta.json":
            continue
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(items, list) or not all(
                isinstance(i, dict) for i in items):
            continue
        cat = path.stem
        hits: dict[str, list[str]] = defaultdict(list)
        names: dict[str, list[str]] = defaultdict(list)
        for it in items:
            name = it.get("name") or ""
            names[name.lower()].append(it.get("id", ""))
            for key, fn in CHECKS.items():
                if fn(name):
                    hits[key].append(name)
            specs = it.get("specs") or {}
            if cat == "gpu" and not specs.get("chip_manufacturer"):
                hits["gpu_no_chip_maker"].append(name)
        dupes = {n: ids for n, ids in names.items() if len(ids) > 1 and n}
        if dupes:
            hits["duplicate_name"] = [f"{n} x{len(i)}" for n, i in dupes.items()]
        if hits:
            print(f"[{cat}] {len(items)} products")
            for key, rows in hits.items():
                total[key] += len(rows)
                print(f"  {key}: {len(rows)}")
                if verbose:
                    for r in rows[:15]:
                        print(f"      {r}")
    print("TOTAL", dict(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
