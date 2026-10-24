"""Offline regression for category assignment (Oct 2026).

A product in the wrong category can never reach full spec coverage: its
schema asks the wrong questions. These real vendor titles pin the cases the
coverage pass found misfiled - AIOs shipped as case fans because the
product-level re-vote ignored the Hebrew liquid word, and 1PC's laptops,
mini PCs and NAS units shipped as storage.

Run: python scripts/check_categories.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.matching import canonical_category, title_category  # noqa: E402

# (vendor category_guess, raw title, expected canonical category)
LISTINGS = [
    ("storage", "מחשב נייד לגיימרים ASUS ROG Strix G16 G615LM-TS275 בצבע Eclipse Gray", "other"),
    ("storage", "מחשב מיני MinisForum M1 Pro Ultra-9-285H 32GB 1TB SSD", "other"),
    ("storage", "Minis Forum מיני מחשב MinisForum NAB9 Plus i9-12900HK 32GB 1TB SSD", "other"),
    ("storage", "נאס ASUSTOR 8Bay AS6508T בצבע שחור", "other"),
    ("storage", "שרת NAS Asustor Lockerstor 16 Pro AS7116RDX - 16 Bay AS7116RDX", "other"),
    # Drives made for a NAS, and portable SSDs, stay storage.
    ("storage", "דיסק קשיח פנימי Seagate IronWolf 4TB ל-NAS דגם ST4000VN006", "storage"),
    ("storage", "כונן קשיח פנימי Western Digital WD Red 4TB SATA III 256MB Cache", "storage"),
    ("storage", "כונן SSD נייד Samsung T9 1TB USB3.2 Gen2x2", "storage"),
    ("cpu_cooling", "קירור למעבד Coolleo Tulong Warrior W360 Black Water Cooler", "aio"),
    ("cpu_cooling", "קירור נוזלי GAMDIAS AURA GL360 V2", "aio"),
]

# Product-level re-vote input: every offer title of one product must argue
# for the same family (the vote that used to drop the Hebrew hint).
TITLES = [
    ("קירור נוזלי למעבד חברת Corsair דגם Corsair iCUE H150i Elite Capellix XT 360mm RGB 75CFM 37dBA",
     "aio"),
    ("קירור נוזלי למעבד חברת Zalman דגם Alpha 24 Black ARGB 60MM 1800RPM צבע שחור", "aio"),
    ("קירור נוזלי למעבד חברת DeepCool דגם LE520 240MM 85.85CFM 2250RPM 17.2DBA", "aio"),
    ("משחה טרמית חברת Cooler Master דגם MasterGel 1.5G", "thermal_paste"),
]


def main() -> int:
    failures = []
    for guess, title, expected in LISTINGS:
        got = canonical_category(guess, title)
        if got != expected:
            failures.append(f"listing {title[:60]!r}: {got!r}, want {expected!r}")
    for title, expected in TITLES:
        got = title_category(title)
        if got != expected:
            failures.append(f"title vote {title[:60]!r}: {got!r}, want {expected!r}")
    count = len(LISTINGS) + len(TITLES)
    if failures:
        print(f"[categories] FAIL - {len(failures)} of {count}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[categories] pass - {count} titles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
