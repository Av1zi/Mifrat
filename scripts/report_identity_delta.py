"""Per-category before/after delta vs git HEAD (docs/merge-identity-plan.md P0/P7).

Compares the working-tree catalogue against ``git show HEAD:data/catalog.json``
— per-category product counts, the "245" CPU family rows, and QA identity-case
counts. This is the report the owner reviews before the identity merge is
committed/pushed; it exists so the delta is reproducible, not ad-hoc.

    python scripts/report_identity_delta.py

Exit 0 always (it is a report, not a gate).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CPU_245 = (
    "model:cpu:245-tray",
    "model:cpu:245k",
    "model:cpu:245k-tray",
    "model:cpu:245kf",
    "model:cpu:245kf-tray",
)


def _git_catalog() -> dict:
    out = subprocess.run(
        ["git", "show", "HEAD:data/catalog.json"],
        capture_output=True, cwd=str(ROOT),
    )
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError("git show HEAD:data/catalog.json failed: "
                           + out.stderr.decode("utf-8", "replace").strip())
    return json.loads(out.stdout.decode("utf-8"))


def _per_category(catalog: dict) -> Counter:
    return Counter(str(p.get("category") or "other")
                   for p in catalog.get("products") or [])


def main() -> int:
    current = json.loads(
        (ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    before = _git_catalog()
    cur, old = _per_category(current), _per_category(before)
    cur_n = sum(len(p.get("offers") or []) for p in current["products"])

    print("category          before   after   delta")
    print("-" * 46)
    for cat in sorted(set(cur) | set(old)):
        b, a = old.get(cat, 0), cur.get(cat, 0)
        delta = a - b
        sign = "+" if delta > 0 else ""
        print(f"{cat:<16} {b:>7} {a:>8} {sign}{delta:>6}")
    print(f"{'products':<16} {sum(old.values()):>7} {sum(cur.values()):>8} "
          f"{sum(cur.values()) - sum(old.values()):>+7}")
    print(f"listings: {cur_n} (unchanged)")

    tiers = Counter(str(p.get("matched_by") or "auto")
                    for p in current.get("products") or [])
    print("\nmatched_by:", ", ".join(f"{k} {v}" for k, v in
                                      sorted(tiers.items(), key=lambda kv: -kv[1])))

    print("\n245 family (must be exactly 5 rows):")
    found = 0
    for p in current.get("products") or []:
        if p.get("product_id") in CPU_245:
            found += 1
            print(f"  {p['product_id']:<22} n={len(p.get('offers') or [])} "
                  f"{p.get('canonical_name')}")
    print(f"  -> {found} row(s)")
    if found != 5:
        print("  [warn] 245 family is not 5 rows")

    qa = Counter(str(case.get("kind") or "?")
                 for case in current.get("identity_cases") or [])
    print("\nidentity_cases:", len(current.get("identity_cases") or []),
          "aliases:", len(current.get("pid_aliases") or {}),
          "|", ", ".join(f"{k} {v}" for k, v in sorted(qa.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
