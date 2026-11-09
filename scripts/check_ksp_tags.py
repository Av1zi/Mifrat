"""Offline regression for the KSP Hebrew listing-tag mapper (Nov 2026).

`parse_ksp_tags` is the only structured spec source KSP has (the detail
endpoint is WAF-blocked). These cases are real tag dicts from
data/raw/2026-11-07/ksp.jsonl. They pin the rule that matters most: a tag that
does not type cleanly becomes NO fact, never a guessed one.

Run: python scripts/check_ksp_tags.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs.resolvers.vendor_struct import (  # noqa: E402
    _ksp_generation,
    _ksp_warranty_years,
    parse_ksp_tags,
)

GENERATION = [
    ("מעבד Intel Raptor Lake Refresh 14th Gen", "Gen 14"),
    ("מעבד - Intel Arrow Lake Series 2", "Gen 2"),
    ("מעבד Intel 12th Gen", "Gen 12"),
    # A codename or a bare number is not a generation.
    ("מעבד AMD Zen 5", None),
    ("14", None),
    ("", None),
    (None, None),
]

WARRANTY = [
    ("5 שנים", 5),
    ("10 שנים", 10),
    ("3 שנים", 3),
    ("שנתיים", 2),
    ("שנה", 1),
    # Not a number of years: stay unknown.
    ("חודש", None),
    ("ללא", None),
    ("לכל חיי המוצר", None),
    ("", None),
    (None, None),
]

# (category, tags, {field: expected value}, fields that must be absent)
TAG_CASES = [
    ("cpu",
     {"יצרן": "Intel", "דור המעבד": "מעבד Intel Raptor Lake Refresh 14th Gen",
      "תושבת": "LGA1700", "משך אחריות": "3 שנים"},
     {"generation": "Gen 14", "socket": "LGA1700"},
     ["warranty_years"]),
    ("cpu",
     {"יצרן": "AMD", "תושבת": "AM5"},
     {"socket": "AM5"},
     ["generation"]),
    ("storage",
     {"נפח אחסון": "1TB", "משך אחריות": "5 שנים"},
     {"capacity_gb": 1000, "warranty_years": 5},
     []),
    ("storage",
     {"נפח אחסון": "1TB", "משך אחריות": "שנתיים"},
     {"warranty_years": 2},
     []),
    ("storage",
     {"נפח אחסון": "1TB", "משך אחריות": "חודש"},
     {"capacity_gb": 1000},
     ["warranty_years"]),
]


def main() -> int:
    failures: list[str] = []

    for raw, want in GENERATION:
        got = _ksp_generation(raw)
        if got != want:
            failures.append(f"generation {raw!r}: {got!r}, want {want!r}")

    for raw, want in WARRANTY:
        got = _ksp_warranty_years(raw)
        if got != want:
            failures.append(f"warranty {raw!r}: {got!r}, want {want!r}")

    for category, tags, want, absent in TAG_CASES:
        facts = parse_ksp_tags(category, {"tags": tags})
        for name, value in want.items():
            got = [fact.value for fact in facts.get(name, [])]
            if value not in got:
                failures.append(f"{category} {tags!r}: {name} = {got!r}, want {value!r}")
        for name in absent:
            if facts.get(name):
                failures.append(f"{category} {tags!r}: {name} must be absent, "
                                f"got {[fact.value for fact in facts[name]]!r}")

    count = len(GENERATION) + len(WARRANTY) + len(TAG_CASES)
    if failures:
        print(f"[ksp-tags] FAIL - {len(failures)} of {count}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[ksp-tags] pass - {count} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
