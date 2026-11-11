"""Offline regression for category assignment (Oct 2026).

A product in the wrong category can never reach full spec coverage: its
schema asks the wrong questions. These real vendor titles pin the cases the
coverage pass found misfiled - AIOs shipped as case fans because the
product-level re-vote ignored the Hebrew liquid word, 1PC's laptops, mini PCs
and NAS units shipped as storage, and KSP's whole "קירור" (cooling) tree
landed in CPU Cooling because each tag handed its entire leaf to one guess.

Since the 2026-11-10 audit it also gates data/catalog.json: one maker part
number sits in one category (I-1), and no product's titles say it is
something its category is not (I-3r: panel only, fan kit, module, bracket,
drive cage, water block, barebone, controller, water-cooling words).

Run: python scripts/check_categories.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.matching import _accessory_type, canonical_category, title_category  # noqa: E402
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
    # Audit 2026-11-10 I: the category of what the title says the item IS.
    ("cpu cooler", "קירור מים למעבד CoolerMaster ML360 Illusion", "aio"),
    ("cpu_cooling", "קירור למעבד COOLER MASTER MLW-D36M-A18PA-R1", "aio"),
    ("cpu_cooling", "קירור למעבד COOLER MASTER ELW-D36M-A21DA-R1", "aio"),
    ("case_fans", "ערכת מאווררים Corsair iCUE LINK RX360 II Unified Frame RGB PWM CO-9051059-WW", "case_fan"),
    ("case_fans", "יחידת מאווררים Corsair iCUE LINK RX360 II Unified Frame RGB PWM Expansion", "case_fan"),
    ("case", "זכוכית למארז חברת Antec מותאמת לדגם Antec NX410 RGB Tempered Glass Only צבע שחור - פאנל זכוכית בלבד", "accessories"),
    ("case", "פאנל זכוכית צד שמאל למארז חברת Antec מותאמת לדגם Performance 1 FT צבע שחור - פאנל בלבד", "accessories"),
    ("case:bundle-only", "Supermicro SYS-420GP-TNR GPU Barebone", "other"),
    ("case:bundle-only", "SuperMicro SuperServer SYS-740GP-TNRT", "other"),
    ("case", "LIAN-LI O11D EVO Upright GPU Black Kit 011DE-2X", "accessories"),
    ("cpu_cooler_aio", "בלוק מעבד למערכת קירור לולאה מותאמת אישית (Custom Loop) Asus ROG RYUJIN III - צבע שחור", "accessories"),
    ("cpu_cooling", "מודול מסך LCD Corsair NAUTILUS RS בצבע שחור", "accessories"),
    ("case_fans", "תושבת מתאם חברת Noctua לקירורים Noctua (רשימת תאימות לקירורים מצורפת בתמונות המוצר) לתושבת LGA 1700 גרסא Chromax Black שחורה", "accessories"),
    ("case_fans", "קורסייר לייטינג נוד פרו CL-9011109-WW צבע לבן", "accessories"),
    ("storage", "כלוב כוננים SilverStone FS204-US ל-4 כונני U.2 בגודל 2.5 אינץ'", "accessories"),
    # ...while a fan kit that ships with a Lighting Node stays fans, and a
    # liquid cooler named "קירור מים" already in aio stays there.
    ("case_fans", "ערכת מאווררים Corsairi CUE SP140 RGB PRO 140ממ עם Lighting Node CORE CO-9050096-WW", "case_fan"),
    ("cpu_cooling", "קירור מים Corsair iCUE H115i RGB PRO XT צבע שחור", "aio"),
]

# Accessory subtype for rows routed to `accessories` (raw title, guess, subtype).
ACCESSORY_TYPES = [
    ("זכוכית למארז חברת Corsair דגם Crystal 680X Tempered Glass Only צבע שחור - פאנל זכוכית בלבד", "case", "case_accessory"),
    ("LIAN-LI O11D EVO Front Mesh Black Kit 011DE-4X", "case", "case_accessory"),
    ("מודול מסך LCD Corsair NAUTILUS RS בצבע לבן", "cpu_cooling", "cooler_accessory"),
    ("קורסייר לייטינג נוד פרו CL-9011109-WW צבע לבן", "case_fans", "rgb_lighting"),
    ("תושבת מתאם חברת Noctua לקירורים Noctua לתושבת LGA 1700", "case_fans", "cooler_accessory"),
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


def _norm_pn(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


# Catalog pass (audit 2026-11-10 I). (name, title pattern, categories the
# word is wrong in). Prototype: tmp/data-audit/00-consolidation/rules/rule_i2.py.
# A bare 120/140 is a fan size too ("Antec Prizm 120 ARGB 5+C 5in1 With
# Controller" is five fans plus their hub).
_FAN_WORD = re.compile(r"מאוורר|fans?\b|\d{2,3}\s*mm|\b(?:120|140)\b(?!\s*w)", re.I)
_IS_A_WORDS = [
    ("panel_only", r"(?:panel|glass|זכוכית|פאנל)[^|]*(?:\bonly\b|בלבד)", {"case"}),
    ("kit_no_fan", r"\bkit\b|ערכת", {"case"}),
    ("module", r"מודול|\bmodule\b", {"aio", "case_fan", "case"}),
    ("bracket", r"(?<!תאימות ל)תושבת|\bbracket\b|mounting\s+kit", {"case_fan", "aio", "cooler_air"}),
    ("cage", r"כלוב|\bcage\b", {"storage", "case"}),
    ("block", r"בלוק\s+מעבד|water\s*block|custom\s+loop", {"aio"}),
    ("server", r"\bbarebone\b|superserver|\bSYS-\d", {"case", "motherboard"}),
    ("controller", r"lighting\s+node|לייטינג\s+נוד|\bcontroller\b|בקר", {"case_fan"}),
    ("water_word", r"קירור\s+מים|קירור\s+נוזלי|\bliquid\b|\baio\b", {"other", "cooler_air", "accessories"}),
    ("fan_kit", r"ערכת\s+מאווררים|יחידת\s+מאווררים|\bfan\s+kit\b", {"accessories"}),
]
_SKIP_WHEN_FAN = {"controller", "kit_no_fan", "bracket"}


def catalog_violations(products: list[dict]) -> list[str]:
    """I-1 (one maker PN, one category) + I-3r (is-a words vs category)."""
    out: list[str] = []
    pn_cats: dict[str, set] = defaultdict(set)
    pn_pids: dict[str, set] = defaultdict(set)
    for p in products:
        for o in p.get("offers") or []:
            pn = _norm_pn(o.get("mpn"))
            # Short all-digit values are retailer numbers, not maker PNs.
            if len(pn) >= 6 and not (pn.isdigit() and len(pn) < 8):
                pn_cats[pn].add(p.get("category"))
                pn_pids[pn].add(p.get("product_id"))
    for pn, cats in sorted(pn_cats.items()):
        if len(cats) > 1:
            out.append(f"I-1 maker PN {pn} in {sorted(cats)}: {sorted(pn_pids[pn])}")
    for p in products:
        titles = [str(o.get("title_raw") or "") for o in p.get("offers") or []]
        if not titles:
            continue
        any_fan = any(_FAN_WORD.search(t) for t in titles)
        category = p.get("category")
        for name, pattern, wrong_in in _IS_A_WORDS:
            if category not in wrong_in:
                continue
            if name in _SKIP_WHEN_FAN and any_fan and not (
                    name == "bracket" and category != "case_fan"):
                continue
            hits = [t for t in titles if re.search(pattern, t, re.I)]
            if name == "water_word" and category == "accessories":
                hits = [t for t in hits
                        if not re.search(r"משחה|paste|thermal|bracket|תושבת", t, re.I)]
            # One spare-panel listing is enough to be wrong; the other words
            # need half the product's titles.
            if hits and (name == "panel_only" or len(hits) * 2 >= len(titles)):
                out.append(f"I-3r {name}: {p.get('product_id')} in {category!r}: {hits[0][:80]!r}")
    return out


def main() -> int:
    failures = []
    for guess, title, expected in LISTINGS:
        got = canonical_category(guess, title)
        if got != expected:
            failures.append(f"listing {title[:60]!r}: {got!r}, want {expected!r}")
    for title, guess, expected in ACCESSORY_TYPES:
        got = _accessory_type(title, guess)
        if got != expected:
            failures.append(f"accessory_type {title[:60]!r}: {got!r}, want {expected!r}")
    for title, expected in TITLES:
        got = title_category(title)
        if got != expected:
            failures.append(f"title vote {title[:60]!r}: {got!r}, want {expected!r}")
    for title, guess, tags, expected in KSP_ROWS:
        got_guess, in_scope = KspSpider._refine_guess(title, tags, guess)
        got = got_guess if in_scope else None
        if got != expected:
            failures.append(f"ksp row {title[:60]!r}: {got!r}, want {expected!r}")
    count = len(LISTINGS) + len(ACCESSORY_TYPES) + len(TITLES) + len(KSP_ROWS)

    # The catalog pass must fire on a known-bad product before it is trusted.
    probe = [{"product_id": "self-test", "category": "case", "offers": [
        {"title_raw": "Antec NX410 Tempered Glass Only - פאנל זכוכית בלבד", "mpn": "0-761345-81041-8"}]},
        {"product_id": "self-test-2", "category": "accessories", "offers": [
        {"title_raw": "Antec NX410 side panel", "mpn": "0-761345-81041-8"}]}]
    if len(catalog_violations(probe)) != 2:
        failures.append("catalog pass self-test: expected 2 violations (I-1 + I-3r)")
    catalog_path = ROOT / "data" / "catalog.json"
    catalog_failures: list[str] = []
    if catalog_path.exists():
        products = json.loads(catalog_path.read_text(encoding="utf-8")).get("products") or []
        catalog_failures = catalog_violations(products)

    if failures or catalog_failures:
        print(f"[categories] FAIL - {len(failures)} of {count} fixtures, "
              f"{len(catalog_failures)} catalog violation(s)")
        for failure in failures + catalog_failures:
            print(f"  - {failure}")
        return 1
    print(f"[categories] pass - {count} titles; catalog clean (I-1 one PN one category, I-3r is-a words)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
