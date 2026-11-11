"""Gate: no shipped string holds an HTML entity, a bidi mark or NBSP (audit 2026-11-10 J).

Vendor feeds carry `&#34;` / `&#39;&#39;` (often without the `;`), U+200E/U+200F
marks and NBSP inside titles, SKUs and detail specs. Before the fix they
reached 27 catalog products as entities and 13 as bidi marks, and from there
model names (`NL-LC1-36 360 &#34`), part numbers (`\u200eCO-9050082-WW`, which
no other vendor's code can equal) and the site files.
`scraper/text_hygiene.clean_text` decodes them where raw rows enter normalize;
this gate walks every string in `data/catalog.json` and `data/site/*.json`
(link fields excepted, as in `clean_tree`) with the same patterns.

    python scripts/check_text_hygiene.py --self-test
    python scripts/check_text_hygiene.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper.text_hygiene import (  # noqa: E402
    _SKIP_KEY_RE,
    BIDI_RE,
    ENTITY_RE,
    NBSP_RE,
    clean_text,
    clean_tree,
)

DATA = ROOT / "data"
PATTERNS = (("entity", ENTITY_RE), ("bidi", BIDI_RE), ("nbsp", NBSP_RE))


def scan(value, path: str, hits: Counter, samples: dict, key: str = "") -> None:
    if isinstance(value, str):
        if _SKIP_KEY_RE.search(key):
            return
        for name, rx in PATTERNS:
            match = rx.search(value)
            if match:
                where = (name, re.sub(r"\[\d+\]", "[]", path))
                hits[where] += 1
                samples.setdefault(where, value[max(0, match.start() - 30): match.end() + 20])
    elif isinstance(value, dict):
        for k, v in value.items():
            scan(v, f"{path}.{k}", hits, samples, str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            scan(v, f"{path}[{i}]", hits, samples, key)


def self_test() -> list[str]:
    errors: list[str] = []
    cases = {
        'רדיאטור 360 מ&#34;מ': 'רדיאטור 360 מ"מ',
        "NL-LC1-36 360 &#34": 'NL-LC1-36 360 "',
        "12 ס&#39;&#39;מ": "12 ס''מ",
        "Fan &amp;amp; Hub": "Fan & Hub",
        "\u200eCO-9050082-WW": "CO-9050082-WW",
        "Solidigm D3-S4520 \u200e \u200e \u200e": "Solidigm D3-S4520",
        "Intel\xa0Xeon Gold 6530": "Intel Xeon Gold 6530",
        "Be Quiet! Pure Rock & Co": "Be Quiet! Pure Rock & Co",
    }
    for raw, want in cases.items():
        got = clean_text(raw)
        if got != want:
            errors.append(f"clean_text({raw!r}) = {got!r}, want {want!r}")
    tree = clean_tree({"title_raw": "a&#34;b", "url": "https://x/?a=1&lt=2",
                       "specs": {"Size": ["\u200f120 מ״מ"]}})
    if tree != {"title_raw": 'a"b', "url": "https://x/?a=1&lt=2", "specs": {"Size": ["120 מ״מ"]}}:
        errors.append(f"clean_tree = {tree!r}")
    hits: Counter = Counter()
    scan({"products": [{"model": "x &#34", "image": "a&amp;b"}]}, "catalog", hits, {})
    if dict(hits) != {("entity", "catalog.products[].model"): 1}:
        errors.append(f"scan = {dict(hits)!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    errors = self_test()
    if errors:
        print("[text-hygiene] FAIL - self-test")
        for error in errors:
            print(f"  - {error}")
        return 1
    if args.self_test:
        print("[text-hygiene] self-test pass")
        return 0

    files = [DATA / "catalog.json", *sorted((DATA / "site").glob("*.json"))]
    missing = [f for f in files[:1] if not f.exists()]
    if missing:
        print(f"[error] {missing[0]} not found - run the normalizer first", file=sys.stderr)
        return 1
    hits: Counter = Counter()
    samples: dict = {}
    for path in files:
        scan(json.loads(path.read_text(encoding="utf-8")), path.name, hits, samples)
    if hits:
        print(f"[text-hygiene] FAIL - {sum(hits.values())} shipped string(s) hold an entity, "
              "bidi mark or NBSP (scraper/text_hygiene.clean_text must run on their source)")
        for (name, where), count in hits.most_common(40):
            print(f"  - {count} {name} {where}: {samples[(name, where)]!r}")
        return 1
    print(f"[text-hygiene] pass - {len(files)} files, no entity, bidi mark or NBSP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
