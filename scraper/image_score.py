"""
Automatic best-photo picking: score image candidates, choose one, keep it stable.

Why this exists (Sep 2026):

Before this module the product's photo was "the first offer that carries any
image URL" (matching.py, product build loop). Two consequences, both measured
by scripts/audit_images.py:

- Resolution was accidental. 657 TMS covers sat at 228px (a listing tile)
  while the same product page serves a 1500x1500 original, because the tile
  was written first and every later download skipped the existing file.
- The shot was accidental too: whichever vendor happened to be first in the
  offer list decided the picture, with no look at the URL's shape (original
  vs. cache tile vs. site furniture), at stock, or at which vendor's photos
  are actually usable in a category.

Scoring is deliberately heuristic, cheap and explainable — no ML, no network,
no disk reads beyond an optional metrics index. Signals:

- URL shape (scraper.image_urls.url_shape_score): originals beat resized
  derivatives, furniture can never win.
- Kind: a detail-page photo beats a listing tile (detail pages carry the
  vendor's own hero shot; listing tiles are 74-290px thumbnails).
- Stock: prefer the photo of something a visitor can actually buy.
- Vendor priority per category (data/matching/image_vendor_priority.json,
  committed, human-editable) — the calibration knob. Defaults come from the
  audit's achievable-resolution and matting-suitability numbers.
- Local metrics when the file already exists: a 5KB "photo" is a placeholder,
  a 40KB+ one is a real image.

Stability matters more than the last point of score: covers that flip between
runs look broken, so `pick_image` keeps the incumbent unless a challenger
beats it by `HYSTERESIS` (relative). Same spirit as the spec pipeline's
"wrong is worse than missing".
"""
from __future__ import annotations

import json
from pathlib import Path

from scraper.image_urls import is_probably_not_a_photo, url_shape_score

PRIORITY_PATH = Path("data/matching/image_vendor_priority.json")
META_PATH = Path("data/images/meta.json")

# Fallback order when the priority file has no entry for a category. Measured
# basis (audit, Sep 2026): TMS serves 1500px originals (its covers only look
# tiny until the upgrade pass runs), Plonter averages 663px with 35% at 800+,
# 1PC's native files are ~500px, and Ivory's 500px shots are the least
# white-backdrop-friendly (0.65 border-white vs 0.94+ for everyone else,
# i.e. more boxed/lifestyle art that mattes badly).
DEFAULT_ORDER = ("tms", "plonter", "onepc", "ivory")

# Vendor ids on offers use "1pc"; image folders use "onepc".
_VENDOR_FOLDER = {"1pc": "onepc", "onepc": "onepc"}

_KIND_BONUS = {
    "detail": 3.0,         # detail-page main image (og:image)
    "detail_gallery": 1.5,  # a gallery sibling on the detail page
    "listing": 0.0,        # listing tile
}

# Relative margin a challenger must clear to displace the incumbent.
HYSTERESIS = 0.05

# Priority rank -> score bonus, best vendor first. The spread (3.6 points) is
# deliberately larger than the halved shape gap between a vendor original and
# its own render (0.5 * ~4), so the committed table decides CROSS-vendor
# choices while the URL shape decides WITHIN a vendor (original vs. tile).
_PRIORITY_WEIGHTS = (2.4, 1.2, 0.0, -1.2, -2.4)

# URL shape contributes at half weight for the same reason: within a vendor a
# 7.5-shape original beats a 1.0-shape 228px tile (3.25 points apart), but a
# vendor's mediocre native URL (1PC, shape 5.5) must not outrank the calmer
# table order by itself.
_SHAPE_WEIGHT = 0.5

# Below this many bytes a "photo" is a placeholder or a 74x74 tile; above it
# the file is plausibly a real image (the audited corpus runs 3-50KB).
PLACEHOLDER_BYTES = 6000
REAL_BYTES = 25_000

# An on-disk long edge under this is a resized derivative as far as the
# upgrade pass is concerned — vendor originals are 500px and up.
UPGRADE_EDGE = 600

# Tile territory: listing thumbnails live here (TMS 74/100/228/290px, 1PC
# 160/200/510). A file this small is worth refetching from its stored URL
# even when no better-shaped URL is derivable, because the stored URL is
# usually the detail page's original while the file came from a listing tile.
# 300..600px files are NOT refetched on that basis — their stored URL is
# normally the same URL that produced them (Ivory 500px originals, Plonter
# 450-500px), so re-downloading would be a no-op with a network cost.
TILE_EDGE = 300

# How much better a derived URL's shape must look before download_images
# re-fetches over an existing file. 4.0 is deliberately a big gap: it is
# cleared by a cache tile (-228x228, score ~2) to its vendor original
# (score ~13) and by nothing smaller. In particular 1PC's "_510 ->
# unsuffixed" sidegrade scores the same on both sides and is ignored —
# re-downloading it would replace a 510px file with a 496px one.
UPGRADE_GAP = 4.0

_priority_cache: dict | None = None
_meta_cache: dict | None = None


def vendor_folder(vendor_id: str | None) -> str:
    return _VENDOR_FOLDER.get(str(vendor_id or ""), str(vendor_id or ""))


def priority_table(reload: bool = False) -> dict:
    """category -> ordered vendor folders, best first.

    Committed JSON so the ordering can be recalibrated without a code deploy
    (same escape-hatch idea as specs/overrides.json). A missing or broken file
    falls back to DEFAULT_ORDER — a bad priority file must never break the
    build.
    """
    global _priority_cache
    if _priority_cache is not None and not reload:
        return _priority_cache
    table: dict = {}
    try:
        if PRIORITY_PATH.is_file():
            with PRIORITY_PATH.open(encoding="utf-8") as f:
                raw = json.load(f)
            for category, order in (raw.get("priority") or {}).items():
                if isinstance(order, list) and order:
                    table[str(category)] = [str(v) for v in order]
    except Exception as exc:
        print(f"[image_score] ignoring {PRIORITY_PATH}: {exc}")
    _priority_cache = table
    return table


def load_meta(reload: bool = False) -> dict:
    """Local file metrics index: {"<vendor>/<file>": {edge, bytes, ...}}.

    Written by download_images.py and process_images.py. Optional — every
    metric is a bonus, never a requirement.
    """
    global _meta_cache
    if _meta_cache is not None and not reload:
        return _meta_cache
    index: dict = {}
    try:
        if META_PATH.is_file():
            with META_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                index = data.get("covers") if isinstance(data.get("covers"), dict) else data
    except Exception:
        index = {}
    _meta_cache = index
    return index


def _vendor_rank(vendor: str, category: str, table: dict) -> int:
    """Rank in the category's priority order; unknown vendors sort last."""
    order = table.get(category) or DEFAULT_ORDER
    try:
        return order.index(vendor)
    except ValueError:
        return len(order)


def score_candidate(candidate: dict, *, category: str = "",
                    table: dict | None = None) -> float:
    """One candidate's score. Higher wins. See module docstring for signals.

    `candidate` keys: url (required), kind, vendor, in_stock, local_bytes,
    local_edge. Unknown keys are ignored so callers can pass offer dicts
    through unchanged.
    """
    url = str(candidate.get("url") or "")
    if not url or is_probably_not_a_photo(url):
        return -100.0

    shape = url_shape_score(url)
    if shape <= -10:
        return -100.0
    score = _SHAPE_WEIGHT * shape

    kind = str(candidate.get("kind") or "listing")
    score += _KIND_BONUS.get(kind, 0.0)

    if candidate.get("in_stock"):
        score += 1.0

    vendor = vendor_folder(candidate.get("vendor"))
    if vendor:
        table = table if table is not None else priority_table()
        rank = _vendor_rank(vendor, category, table)
        weight = _PRIORITY_WEIGHTS[min(rank, len(_PRIORITY_WEIGHTS) - 1)]
        score += weight

    local_bytes = candidate.get("local_bytes")
    if isinstance(local_bytes, (int, float)) and local_bytes > 0:
        if local_bytes < PLACEHOLDER_BYTES:
            score -= 1.5
        elif local_bytes >= REAL_BYTES:
            score += 0.5

    local_edge = candidate.get("local_edge")
    if isinstance(local_edge, (int, float)) and local_edge > 0:
        if local_edge >= 800:
            score += 1.0
        elif local_edge < 350:
            score -= 1.0

    return score


def pick_image(candidates: list[dict], *, category: str = "",
               table: dict | None = None,
               incumbent_url: str | None = None) -> dict | None:
    """Best candidate, with the incumbent kept unless clearly beaten.

    Returns the winning candidate dict (the caller's own object, so extra
    keys survive), or None when nothing is usable.
    """
    if not candidates:
        return None
    table = table if table is not None else priority_table()

    best: dict | None = None
    best_score = float("-inf")
    incumbent: dict | None = None
    incumbent_score = float("-inf")
    for candidate in candidates:
        score = score_candidate(candidate, category=category, table=table)
        if score <= -100:
            continue
        if best is None or score > best_score:
            best, best_score = candidate, score
        if incumbent_url and str(candidate.get("url")) == str(incumbent_url):
            incumbent, incumbent_score = candidate, score

    if best is None:
        return None
    if incumbent is not None and incumbent is not best:
        # Relative margin so a tiny score drift never reshuffles covers; a
        # genuinely better shot (shape/kind/vendor) clears it comfortably.
        margin = abs(incumbent_score) * HYSTERESIS if incumbent_score else HYSTERESIS
        if best_score - incumbent_score <= margin:
            return incumbent
    return best


def should_refetch(incoming_url: str, *, existing_edge: int | None = None,
                   existing_bytes: int | None = None) -> bool:
    """Is re-downloading this URL an upgrade over the file already on disk?

    This is the fix for the audited bug: download_images() used to skip any
    existing destination, so the first writer (a 228px listing tile) beat the
    vendor's 1500px original forever. An upgrade is re-fetched only when

    - the file is missing (trivially an upgrade), or
    - the file is a resized derivative (long edge < UPGRADE_EDGE) or
      suspiciously small, AND the incoming URL looks like a real original.

    A same-sized but *different* photo is NOT re-fetched here — switching
    shots is the picker's decision (pick_image), not the downloader's.
    """
    if not incoming_url or is_probably_not_a_photo(incoming_url):
        return False
    if existing_edge is None and existing_bytes is None:
        return True
    if existing_edge is not None and existing_edge >= UPGRADE_EDGE:
        return False
    if existing_edge is None and (existing_bytes or 0) >= REAL_BYTES:
        return False
    return url_shape_score(incoming_url) >= 7.0


if __name__ == "__main__":  # tiny self-check: python -m scraper.image_score
    samples = [
        ("https://tms.co.il/image/catalog/products/ST28000NM003K/D9kz8CXkiv.jpg",
         {"kind": "detail", "vendor": "tms", "in_stock": True}),
        ("https://tms.co.il/image/cache/catalog/products/ST28000NM003K/D9kz8CXkiv-1000x1000.jpg",
         {"kind": "detail", "vendor": "tms", "in_stock": True}),
        ("https://tms.co.il/image/cache/catalog/products/ST28000NM003K/D9kz8CXkiv-74x74.jpg",
         {"kind": "listing", "vendor": "tms", "in_stock": True}),
        ("https://1pc.co.il/images/thumbs/0063041_antec-p20ce-case_510.jpeg",
         {"kind": "detail", "vendor": "1pc", "in_stock": True}),
        ("https://1pc.co.il/images/thumbs/0076482_logo.e8a255e0.png",
         {"kind": "listing", "vendor": "1pc", "in_stock": True}),
    ]
    for url, extra in samples:
        cand = {"url": url, **extra}
        print(f"{score_candidate(cand, category='case'):6.2f}  {url}")
