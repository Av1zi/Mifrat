"""Audit which KSP listing tags `parse_ksp_tags` reads, per category.

Offline: reads one saved `data/raw/<date>/ksp.jsonl`, no network. Categories
are the normalized ones `parse_ksp_tags` really receives. A tag counts
as READ for a category when deleting it from a listing changes the facts the
parser emits for that listing. Everything else is DROPPED, shown with sample
values so a mapping decision can be made against `scraper/specs/schema.py`.

Usage:
    python scripts/audit_ksp_tags.py [path/to/ksp.jsonl] [--dropped-only]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.matching import canonical_category  # noqa: E402
from scraper.specs.resolvers.vendor_struct import parse_ksp_tags  # noqa: E402

SAMPLES = 3


def _latest() -> Path:
    files = sorted((ROOT / "data" / "raw").glob("*/ksp.jsonl"))
    if not files:
        sys.exit("no data/raw/*/ksp.jsonl snapshot found")
    return files[-1]


def _signature(facts) -> str:
    return repr(sorted((k, repr(v)) for k, v in facts.items()))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dropped_only = "--dropped-only" in sys.argv
    path = Path(args[0]) if args else _latest()

    present: dict[str, Counter] = defaultdict(Counter)
    read: dict[str, Counter] = defaultdict(Counter)
    samples: dict[tuple[str, str], list[str]] = defaultdict(list)
    listings = Counter()

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            category = canonical_category(
                row.get("category_guess"), row.get("title_raw", ""),
                str(row.get("url") or ""), str(row.get("vendor_sku") or ""))
            meta = row.get("vendor_meta") or {}
            tags = meta.get("tags")
            if not isinstance(tags, dict):
                continue
            listings[category] += 1
            base = _signature(parse_ksp_tags(category, meta))
            for tag, value in tags.items():
                present[category][tag] += 1
                trimmed = {k: v for k, v in tags.items() if k != tag}
                probe = _signature(parse_ksp_tags(category, {**meta, "tags": trimmed}))
                if probe != base:
                    read[category][tag] += 1
                bucket = samples[(category, tag)]
                text = str(value)
                if text not in bucket and len(bucket) < SAMPLES:
                    bucket.append(text)

    print(f"# KSP tag audit: {path.relative_to(ROOT)}")
    print(f"{sum(listings.values())} listings, {len(listings)} categories\n")
    print("| category | tag | listings | read | status | samples |")
    print("|---|---|---:|---:|---|---|")
    for category in sorted(present, key=lambda c: str(c)):
        for tag, n in present[category].most_common():
            r = read[category][tag]
            status = "READ" if r else "dropped"
            if dropped_only and r:
                continue
            sample = "; ".join(samples[(category, tag)])
            print(f"| {category} | {tag} | {n} | {r} | {status} | {sample} |")


if __name__ == "__main__":
    main()
