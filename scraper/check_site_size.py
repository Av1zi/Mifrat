"""CI size guard for data/site/*.json (Phase 8, see decisions.md).

Anti-regression lock for the data-trust + performance phases: fails the
normalize job when any per-category (or index) file exceeds 1MB, or when
category-file bytes grow >15% versus the committed previous run without
proportional product growth (junk prose/remote URLs/duplicate keys
ballooning the payload again).

Pure stdlib. Exit 0 = pass, exit 1 = guard tripped (message on stdout).

Usage (from the repo root, after normalize_and_match.py):
    python scraper/check_site_size.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "data" / "site"

# Absolute per-file ceiling (bytes). Applies to every top-level data/site
# file except meta.json/qa.json (tiny coordination files). index.json is
# covered too — it must stay a compact lookup, not a second catalog.
MAX_FILE_BYTES = 1024 * 1024

# Relative growth tripwire for the category-file total (index.json is
# excluded: its introduction is a one-time sanctioned jump, and its size
# is bounded by the absolute cap above instead).
MAX_GROWTH = 0.15

SKIP_NAMES = {"meta.json", "qa.json"}


def _git_show_head(rel_path: str) -> bytes | None:
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _product_count(meta: dict) -> int:
    try:
        return sum(int(c.get("count", 0)) for c in meta.get("categories", []))
    except (ValueError, TypeError, AttributeError):
        return 0


def main() -> int:
    if not SITE_DIR.is_dir():
        print("[size-guard] FAIL: data/site/ missing — run normalize first")
        return 1

    failures: list[str] = []

    category_files = sorted(
        p for p in SITE_DIR.glob("*.json") if p.name not in SKIP_NAMES
    )
    for path in category_files:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            failures.append(
                f"{path.name} is {size // 1024}KB (>{MAX_FILE_BYTES // 1024}KB)"
            )

    # Growth vs the committed previous run. Files absent from HEAD (e.g.
    # index.json on its rollout run) only get the absolute cap above.
    old_total = 0
    new_total = 0
    compared = 0
    for path in category_files:
        if path.name == "index.json":
            continue
        old = _git_show_head(f"data/site/{path.name}")
        if old is None:
            continue
        old_total += len(old)
        new_total += path.stat().st_size
        compared += 1

    if compared and old_total > 0:
        growth = new_total / old_total - 1
        old_meta_raw = _git_show_head("data/site/meta.json")
        new_meta_raw = None
        try:
            new_meta_raw = (SITE_DIR / "meta.json").read_bytes()
        except OSError:
            pass
        if old_meta_raw is not None and new_meta_raw is not None:
            try:
                old_products = _product_count(json.loads(old_meta_raw))
                new_products = _product_count(json.loads(new_meta_raw))
            except ValueError:
                old_products = new_products = 0
            prod_growth = (
                (new_products / old_products - 1) if old_products > 0 else 0.0
            )
            print(f"[size-guard] category bytes {old_total // 1024}KB -> "
                  f"{new_total // 1024}KB ({growth:+.1%}), products "
                  f"{old_products} -> {new_products} ({prod_growth:+.1%})")
            if growth > MAX_GROWTH and prod_growth < growth:
                failures.append(
                    f"category payload grew {growth:.1%} with only "
                    f"{prod_growth:.1%} product growth"
                )
        else:
            print("[size-guard] no HEAD meta.json to compare; "
                  "absolute caps only")
    else:
        print("[size-guard] no committed baseline to compare; "
              "absolute caps only")

    if failures:
        for failure in failures:
            print(f"[size-guard] FAIL: {failure}")
        return 1
    print("[size-guard] pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
