"""Migrate the committed manufacturer files (data/mfr/*.json) to the current schema.

scraper/mfr/store.py ignores a file whose `schema_version` differs from the
schema's, so a version bump without this step silently drops every
manufacturer fact. The raw page cache is gitignored, so re-parsing with
`python -m scraper.mfr <brand> --offline` is only possible on the machine that
fetched; this rewrites the extracted JSON instead.

v2 -> v3 (Oct 2026): `pcie12_connectors` (12VHPWR) folds into
`pcie16_connectors` (12V-2x6 / 12VHPWR, one plug), and the free-text
`pcie_power_connectors` column is gone. When a page stated both plug names
the larger count is kept: they are one connector filed under two names.

Run: python scripts/migrate_mfr_schema.py [--check]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs import schema  # noqa: E402

DATA_DIR = ROOT / "data" / "mfr"


def migrate_v2_specs(specs: dict) -> dict:
    out = dict(specs)
    hpwr = out.pop("pcie12_connectors", None)
    out.pop("pcie_power_connectors", None)
    if hpwr is not None:
        current = out.get("pcie16_connectors")
        out["pcie16_connectors"] = hpwr if current is None else max(int(current), int(hpwr))
    return out


MIGRATIONS = {2: migrate_v2_specs}


def migrate_file(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = int(data.get("schema_version") or 0)
    if version == schema.SCHEMA_VERSION:
        return False
    while version < schema.SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise SystemExit(f"[mfr-migrate] {path.name}: no migration from v{version}")
        for entry in (data.get("entries") or {}).values():
            entry["specs"] = step(entry.get("specs") or {})
        version += 1
    data["schema_version"] = version
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when a file is not at the current schema version")
    args = ap.parse_args()
    stale = []
    for path in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != schema.SCHEMA_VERSION:
            stale.append(path)
    if args.check:
        for path in stale:
            print(f"[mfr-migrate] {path.name} is not at schema v{schema.SCHEMA_VERSION}")
        return 1 if stale else 0
    for path in stale:
        migrate_file(path)
        print(f"[mfr-migrate] {path.name} -> v{schema.SCHEMA_VERSION}")
    if not stale:
        print(f"[mfr-migrate] every file is at v{schema.SCHEMA_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
