"""Archive stale QA dismissals after owner approval; dry-run unless --apply.

Run only after normalizing. Current cases (including dismissed ones), aliases,
inactive entries and fuzzy decisions are preserved. No current case is dismissed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_ledgers import ROOT, stale_dismissals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="requires owner approval")
    parser.add_argument("--archive", type=Path, help="new archive file; required with --apply")
    args = parser.parse_args()
    if args.apply and (not args.archive or args.archive.exists()):
        parser.error("--apply needs a new --archive path (never overwrites an archive)")
    path = ROOT / "data/matching/qa_dismissed.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    qa = json.loads((ROOT / "data/site/qa.json").read_text(encoding="utf-8"))
    if not catalog.get("generated_at") or qa.get("generated_at") != catalog["generated_at"]:
        parser.error("catalog and QA must be from the same normalize run")
    stale = stale_dismissals(ledger, qa.get("cases") or [], catalog.get("pid_aliases"))
    print(f"[qa-dismissals] {len(stale)} stale active entries; "
          f"{len(ledger) - len(stale)} entries preserved")
    for key in stale:
        print(f"  {key}")
    if not args.apply or not stale:
        return 0
    archive = {"catalog_generated_at": catalog["generated_at"],
               "reason": "Owner-approved removal: no current case after following pid aliases",
               "entries": {key: ledger[key] for key in stale}}
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    # Archive first; if that fails the human decisions remain unchanged.
    with args.archive.open("x", encoding="utf-8") as handle:
        json.dump(archive, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    for key in stale:
        del ledger[key]
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[qa-dismissals] archived to {args.archive}; removed {len(stale)} stale entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
