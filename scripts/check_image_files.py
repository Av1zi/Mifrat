"""Gate for the cover corpus in data/images/ (Oct 2026).

Fails (exit 1) when the committed covers regress on any of:

- format: every file under data/images/<vendor>/ is a `.webp` cover — no
  legacy `.jpg`, no committed `thumbs/` tree (thumbnails are derived at site
  build time by site/scripts/copy-data.mjs)
- size: long edge <= 640px and file <= COVER_MAX_BYTES; total corpus <=
  TOTAL_BUDGET_MB (the prune keeps ~5k covers; an un-pruned archive is 5x)
- black borders: a cover whose border is (almost) all near-black is the
  signature of the alpha bug (transparent sources run through
  `.convert("RGB")`). Genuinely dark-backdrop studio shots and covers waiting
  for a refetch are listed in data/matching/image_dark_ok.json
  ({"covers": {"<vendor>/<file>": "<reason>"}}); anything else fails.

Run: python scripts/check_image_files.py [--report]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.download_images import COVER_EXT, COVER_MAX_BYTES, MAX_DIMENSION  # noqa: E402
from scraper.image_pixels import load_pixels, rgb_at  # noqa: E402

IMAGES_DIR = ROOT / "data" / "images"
ALLOWLIST = ROOT / "data" / "matching" / "image_dark_ok.json"

TOTAL_BUDGET_MB = 160
# A border pixel is "black" when every channel is under this; a cover is
# black-bordered when at least DARK_SHARE of its sampled border is black.
BLACK_CUTOFF = 40
DARK_SHARE = 0.85


def border_black_share(img: Image.Image) -> float:
    """Share of sampled border pixels (2px frame) that are near-black."""
    rgb = img.convert("RGB")
    width, height = rgb.size
    if width < 8 or height < 8:
        return 0.0
    px = load_pixels(rgb)
    step_x = max(1, width // 100)
    step_y = max(1, height // 100)
    dark = total = 0
    points = [(x, y) for x in range(0, width, step_x) for y in (0, 1, height - 2, height - 1)]
    points += [(x, y) for y in range(0, height, step_y) for x in (0, 1, width - 2, width - 1)]
    for x, y in points:
        r, g, b = rgb_at(px, x, y)
        total += 1
        if r < BLACK_CUTOFF and g < BLACK_CUTOFF and b < BLACK_CUTOFF:
            dark += 1
    return dark / total if total else 0.0


def load_allowlist() -> dict[str, str]:
    try:
        data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
        covers = data.get("covers") or {}
        return {str(k): str(v) for k, v in covers.items()}
    except FileNotFoundError:
        return {}


def scan() -> dict:
    allow = load_allowlist()
    result = {
        "files": 0, "bytes": 0, "bad_format": [], "oversize": [], "too_wide": [],
        "unreadable": [], "black_border": [], "allowed_dark": [], "stale_allow": [],
    }
    seen: set[str] = set()
    if not IMAGES_DIR.is_dir():
        return result
    for vendor_dir in sorted(p for p in IMAGES_DIR.iterdir() if p.is_dir()):
        for path in sorted(vendor_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(IMAGES_DIR).as_posix()
            result["files"] += 1
            size = path.stat().st_size
            result["bytes"] += size
            if path.suffix.lower() != COVER_EXT or "thumbs" in path.relative_to(vendor_dir).parts:
                result["bad_format"].append(rel)
                continue
            if size > COVER_MAX_BYTES:
                result["oversize"].append(f"{rel} ({size // 1024}KB)")
            try:
                with Image.open(path) as img:
                    if max(img.size) > MAX_DIMENSION:
                        result["too_wide"].append(f"{rel} ({img.size[0]}x{img.size[1]})")
                    share = border_black_share(img)
            except Exception as exc:
                result["unreadable"].append(f"{rel}: {exc}")
                continue
            if share >= DARK_SHARE:
                seen.add(rel)
                if rel in allow:
                    result["allowed_dark"].append(rel)
                else:
                    result["black_border"].append(f"{rel} ({share:.0%})")
    result["stale_allow"] = sorted(k for k in allow if k not in seen)
    return result


def main() -> int:
    report = "--report" in sys.argv
    r = scan()
    total_mb = r["bytes"] / 1e6
    problems = []
    for key, label in (("bad_format", f"not a {COVER_EXT} cover (legacy .jpg / thumbs/)"),
                       ("oversize", f"over {COVER_MAX_BYTES // 1000}KB"),
                       ("too_wide", f"long edge over {MAX_DIMENSION}px"),
                       ("unreadable", "unreadable"),
                       ("black_border", "black-border cover (alpha bug signature; refetch it, or "
                                        "list a genuine dark-backdrop shot in image_dark_ok.json)")):
        if r[key]:
            problems.append((label, r[key]))
    if total_mb > TOTAL_BUDGET_MB:
        problems.append((f"corpus {total_mb:.0f}MB exceeds {TOTAL_BUDGET_MB}MB budget "
                         f"(run: python -m scraper.download_images --prune --apply)", []))
    print(f"[image-files] {r['files']} files, {total_mb:.1f} MB, "
          f"{len(r['allowed_dark'])} allowlisted dark covers")
    if r["stale_allow"] and report:
        print(f"  note: {len(r['stale_allow'])} allowlist entries no longer match a "
              f"black-border cover: {r['stale_allow'][:5]}")
    if problems:
        print("[image-files] FAIL")
        for label, items in problems:
            print(f"  - {len(items) or ''} {label}")
            for item in items[:12]:
                print(f"      {item}")
            if len(items) > 12:
                print(f"      ... {len(items) - 12} more")
        return 1
    print("[image-files] pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
