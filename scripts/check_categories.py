"""Offline regression for category assignment (Oct 2026).

A product in the wrong category can never reach full spec coverage: its
schema asks the wrong questions. These real vendor titles pin the cases the
coverage pass found misfiled - AIOs shipped as case fans because the
product-level re-vote ignored the Hebrew liquid word, 1PC's laptops, mini PCs
and NAS units shipped as storage, and KSP's whole "קירור" (cooling) tree
landed in CPU Cooling because each tag handed its entire leaf to one guess.

Run: python scripts/check_categories.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.matching import canonical_category, title_category  # noqa: E402
from scraper.spiders.ksp import KspSpider  # noqa: E402

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
    # KSP cooling accessories are Hebrew-only titles: without the Hebrew
    # accessory hints they fell through to the cooler/fan leaf they fit, or
    # to `other`.
    ("accessories", "פד תרמי Arctic TP-3 100x100mm 1.0mm Thickness", "accessories"),
    ("accessories", "בקר רכזת מאוורר PWM 10 יציאות עם כוח Arctic SATA", "accessories"),
    ("accessories", "שני כבלים Corsair iCUE LINK Cable 2x100mm", "accessories"),
    ("case_fans", "סט 3 כבלי Y למאוורר NA-SYC1 Chromax Blue מבית Noctua - צבע כחול", "accessories"),
    ("case_fans", "סט 20 תושבות מונעות זעזועים למאווררי מארז Noctua NA-SAV2 - צבע שחור", "accessories"),
    ("case_fans", "סט 2 מתאמי התקנה NA-SFMA1 למאוורר מארז NF-A12x25 מבית Noctua", "accessories"),
    ("cpu_cooler_air", "ערכת הרחבה רשמית NA-FK1 למערכת קירור-NH-U12S redux עם מאוורר NF-P12 PWM מבית Noctua", "accessories"),
    # A fan bundle that merely ships with a controller is still a fan.
    ("case_fans", "מאוורר למארז עם בקר תאורה Corsair iCUE LINK LX140 RGB 140mm PWM - צבע לבן", "case_fan"),
    # ...and so is a fan that ships with anti-vibration pads, and a multi-pack
    # ("ערכת מאווררים ... Triple Pack"). Only the accessory ITSELF moves.
    ("case_fan", "מאוורר למארז 14 ס\"מ Noctua NF-A14 chromax.black.swap PWM בצבע שחור עם רפידות נגד ויברציות בצבעים להחלפה", "case_fan"),
    ("case_fan", "ערכת מאווררים Corsair RS120 ARGB 120mm PWM - Triple Pack", "case_fan"),
    ("case_fan", "מפצל מאוררים Yahav PC BXAT-XS-BC מחיבור מאוורר 4 PIN PWM FAN ל3 חיבורי 4 PIN PWM FAN", "accessories"),
    ("case_fan", "בקר LED ARGB קטן Cooler Master MFX-ACBN-NNUNN-R1 בצבע שחור", "accessories"),
]

# Product-level re-vote input: every offer title of one product must argue
# for the same family (the vote that used to drop the Hebrew hint).
TITLES = [
    ("קירור נוזלי למעבד חברת Corsair דגם Corsair iCUE H150i Elite Capellix XT 360mm RGB 75CFM 37dBA",
     "aio"),
    ("קירור נוזלי למעבד חברת Zalman דגם Alpha 24 Black ARGB 60MM 1800RPM צבע שחור", "aio"),
    ("קירור נוזלי למעבד חברת DeepCool דגם LE520 240MM 85.85CFM 2250RPM 17.2DBA", "aio"),
    ("משחה טרמית חברת Cooler Master דגם MasterGel 1.5G", "thermal_paste"),
    # KSP files every cooling row under one of two overlapping CPU-cooler
    # leaves, so the row itself decides air vs liquid vs accessory.
    ("קירור נוזלי למעבד Arctic Liquid Freezer III Pro 360 A-RGB - צבע שחור", "aio"),
    ("קירור למעבד Arctic Freezer 36 - שחור", "cooler_air"),
]

# Spider-level placement: KSP's cooling tags are a hint, so each row is
# re-guessed from its own title and `סוג` tag. None = the row is dropped.
# (raw title, category_guess from the tag, tags dict, expected guess or None)
KSP_ROWS = [
    # Tag 182 (מאווררים למעבדים) also contains liquid coolers.
    ("קירור נוזלי למעבד Asus ROG STRIX LC III 360 ARGB LCD - לבן", "cpu_cooler_air", {}, "cpu_cooler_aio"),
    ("קירור נוזלי למעבד MSI MAG CORELIQUID A13 240 - שחור", "cpu_cooler_air", {"סוג": "מאווררים למעבדים"}, "cpu_cooler_aio"),
    ("קירור למעבד Noctua NH-L9I-17XX LGA1700", "cpu_cooler_air", {"סוג": "מאווררים למעבדים"}, "cpu_cooler_air"),
    # ...and AIOs filed under the liquid leaf stay liquid.
    ("קירור נוזלי למעבד Corsair NAUTILUS 360 RS", "cpu_cooler_aio", {"סוג": "קירור נוזלי"}, "cpu_cooler_aio"),
    # Accessories inside the part leaves.
    ("סט 16 פדים מונעי רעידות NOCTUA NA-SAVP6 Chromax.Black", "case_fans", {}, "accessories"),
    ("סט 16 רפידות נגד-רעידות NA-SAVP3 Chromax Blue מבית Noctua", "case_fans", {}, "accessories"),
    ("סט 2 מתאמי התקנה NA-SFMA1 למאוורר מארז NF-A12x25", "case_fans", {}, "accessories"),
    ("ערכת הסטה לשיפור יעילות קירור בסדרת MSI CORELIQUID LGA1851", "cpu_cooler_air", {}, "accessories"),
    ("ערכת תעלת אוויר מתכוונת NA-FD1 לשיפור קירור למעבדים", "cpu_cooler_air", {}, "accessories"),
    # A real fan in the fan leaf stays a fan, even when the bundle mentions
    # pads or a mounting kit it ships with.
    ("מאוורר למארז ARCTIC P12 Slim PST 120mm PWM - צבע שחור", "case_fans", {}, "case_fans"),
    ("מאוורר למארז Arctic P14 140mm כולל רפידות נגד רעידות", "case_fans", {}, "case_fans"),
    # Not desktop cooling at all: dropped before the normalizer.
    ("קירור למחשבים ניידים 15.6 inch - צבע שחור", "cpu_cooler_air", {}, None),
    ("מאוורר USB 120mm שולחני", "cpu_cooler_air", {}, None),
    ("קירור לכונני אחסון M.2 NVMe גוף קירור אלומיניום", "cpu_cooler_air", {}, None),
    # A decorative shroud is the one cooling row group still dropped.
    ("כיסוי עיצובי למאוורר Noctua NF-A12x25 Chromax Black", "cpu_cooler_air", {}, None),
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
    for title, guess, tags, expected in KSP_ROWS:
        got_guess, in_scope = KspSpider._refine_guess(title, tags, guess)
        got = got_guess if in_scope else None
        if got != expected:
            failures.append(f"ksp row {title[:60]!r}: {got!r}, want {expected!r}")
    count = len(LISTINGS) + len(TITLES) + len(KSP_ROWS)
    if failures:
        print(f"[categories] FAIL - {len(failures)} of {count}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[categories] pass - {count} titles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
