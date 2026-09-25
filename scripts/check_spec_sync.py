#!/usr/bin/env python
"""
check_spec_sync.py — fail CI when the frontend drifts from the spec schema.

`scraper/specs/schema.py` is the single source of truth for spec field names,
types and units. This script proves the two directions of the contract:

1. GENERATED OUTPUT IS FRESH — `site/src/specSchema.generated.ts` must equal
   what `python -m scraper.specs.export_site` renders right now. Editing the
   schema without regenerating fails here.

2. HAND-WRITTEN FRONTEND KEYS EXIST IN THE SCHEMA — the two lists the UI still
   maintains by hand (`VARIANT_IDENTITY_KEYS`, `VARIANT_KEY_PRIORITY` in
   site/src/specs.ts) may only name real schema fields. A rename in the schema
   that leaves a stale name behind fails here instead of silently dropping a
   variant pill at runtime.

Exit 0 = in sync, exit 1 = drift (message on stdout). Run from the repo root:

    python scripts/check_spec_sync.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs import export_site, schema

SPECS_TS = ROOT / "site" / "src" / "specs.ts"


def check_generated_file() -> list[str]:
    """The committed generated TS must match a fresh render."""
    rendered = export_site.render()
    current = (
        export_site.OUT_PATH.read_text(encoding="utf-8")
        if export_site.OUT_PATH.exists()
        else None
    )
    if current is None:
        return [
            (
                f"{export_site.OUT_PATH.relative_to(ROOT)} is missing — "
                "run: python -m scraper.specs.export_site"
            )
        ]
    if current != rendered:
        return [
            (
                f"{export_site.OUT_PATH.relative_to(ROOT)} is stale — "
                "run: python -m scraper.specs.export_site"
            )
        ]
    return []


def _all_schema_names() -> set[str]:
    names: set[str] = set()
    for fields in schema.SCHEMA.values():
        names.update(f.name for f in fields)
    return names


def _parse_variant_keys(source: str) -> tuple[set[str], dict[str, list[str]]]:
    """Pull the two hand-maintained lists out of site/src/specs.ts."""
    priority: set[str] = set()
    identity: dict[str, list[str]] = {}

    match = re.search(r"VARIANT_KEY_PRIORITY\s*=\s*\[(.*?)\]", source, re.DOTALL)
    if match:
        priority = {
            token.strip().strip('"').strip("'")
            for token in match.group(1).split(",")
            if token.strip()
        }

    match = re.search(r"VARIANT_IDENTITY_KEYS[^{]*\{(.*?)\n\};", source, re.DOTALL)
    if match:
        for entry in re.finditer(
            r"(\w+)\s*:\s*\[(.*?)\]", match.group(1), re.DOTALL
        ):
            keys = [
                token.strip().strip('"').strip("'")
                for token in entry.group(2).split(",")
                if token.strip()
            ]
            identity[entry.group(1)] = keys
    return priority, identity


def check_frontend_keys() -> list[str]:
    """Every hand-written frontend spec key must be a real schema field."""
    if not SPECS_TS.exists():
        return [f"{SPECS_TS.relative_to(ROOT)} is missing"]
    source = SPECS_TS.read_text(encoding="utf-8")
    if "VARIANT_KEY_PRIORITY" not in source or "VARIANT_IDENTITY_KEYS" not in source:
        return [
            (
                f"{SPECS_TS.relative_to(ROOT)} no longer declares "
                "VARIANT_KEY_PRIORITY / VARIANT_IDENTITY_KEYS — update "
                "scripts/check_spec_sync.py"
            )
        ]
    names = _all_schema_names()
    problems: list[str] = []
    priority, identity = _parse_variant_keys(source)

    for field in sorted(priority - names):
        problems.append(f"VARIANT_KEY_PRIORITY names unknown schema field {field!r}")

    for category, keys in identity.items():
        known = schema.field_map(category)
        if not known:
            problems.append(
                f"VARIANT_IDENTITY_KEYS references unknown category {category!r}")
            continue
        for field in keys:
            if field not in known:
                problems.append(
                    f"VARIANT_IDENTITY_KEYS[{category!r}] names {field!r}, which is "
                    f"not a {category} schema field")
    return problems


def main() -> int:
    problems = check_generated_file() + check_frontend_keys()
    if problems:
        print("[spec-sync] FAIL:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"[spec-sync] pass — schema v{schema.SCHEMA_VERSION}, "
          f"{len(schema.SCHEMA)} categories, generated TS fresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
