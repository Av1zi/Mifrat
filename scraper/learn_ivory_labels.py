"""
Bootstrap labels for Ivory's opaque builder IDs.

Ivory's ws/get payload tags products with numeric `cuts` (compatibility
tags) and a `parent` category id, but the IDs are opaque. This script
learns what they mean by correlation: if >=90% of listings carrying
cut 5838 have title-derived socket=AM5, then 5838 := socket AM5.

Two-pass flow:
    python -m scraper.normalize_and_match   # builds catalog with ivory_cuts
    python -m scraper.learn_ivory_labels    # writes data/ivory_cut_labels.json
    python -m scraper.normalize_and_match   # second pass applies the labels
"""

import json
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"
OUT_PATH = DATA_DIR / "ivory_cut_labels.json"

# Attributes we trust enough to teach from (title/MPN-derived).
LABEL_SOURCE_KEYS = [
    "socket", "chipset", "memory_type", "form_factor", "packaging",
    "wifi_standard", "efficiency", "vram_gb", "wattage_w", "size_mm",
]

MIN_N = 2        # a cut must appear on >=2 listings with a known value
MIN_SHARE = 0.9  # >=90% must agree on one value


def dominant(tallies: dict) -> dict:
    out: dict = {}
    for key, attrs in tallies.items():
        labeled: dict = {}
        for attr, values in attrs.items():
            total = sum(values.values())
            if total < MIN_N:
                continue
            best, n = max(values.items(), key=lambda kv: kv[1])
            if n / total >= MIN_SHARE:
                labeled[attr] = best
        if labeled:
            out[key] = labeled
    return out


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    cut_tallies: dict = defaultdict(lambda: defaultdict(dict))
    parent_tallies: dict = defaultdict(dict)

    for listing in catalog.get("listings", []):
        attrs = listing.get("attributes") or {}
        cuts = attrs.get("ivory_cuts") or []
        parent = attrs.get("ivory_parent")

        known = {
            k: attrs[k]
            for k in LABEL_SOURCE_KEYS
            if attrs.get(k) not in (None, "")
        }

        for cut in cuts:
            for attr, value in known.items():
                t = cut_tallies[cut].setdefault(attr, {})
                t[str(value)] = t.get(str(value), 0) + 1

        if parent is not None:
            cat = listing.get("category_normalized")
            t = parent_tallies[str(parent)].setdefault("category", {})
            t[str(cat)] = t.get(str(cat), 0) + 1

    result = {
        "cuts": dominant(cut_tallies),
        "parents": dominant(parent_tallies),
    }

    OUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[ok] wrote {OUT_PATH}: "
        f"{len(result['cuts'])} labeled cuts, "
        f"{len(result['parents'])} labeled parents"
    )


if __name__ == "__main__":
    main()