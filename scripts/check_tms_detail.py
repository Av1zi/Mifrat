"""
check_tms_detail.py — offline regression for the TMS detail pipeline.

The repo has no test framework by design (see PROJECT_OVERVIEW §11), so this is
a plain script:

    python scripts/check_tms_detail.py

It never touches the network. It exercises two halves of the pipeline against
verifiable data:

1. the spider (`scraper/spiders/detail_pages.py::TmsDetailSpider`) against
   trimmed captures of REAL TMS product pages in
   `scraper/specs/golden/tms_pages/`. This is the regression that matters most:
   the previous selector set matched nothing on any TMS page, so all 1,051
   detail rows ever scraped came back with `specs = {}` while the vendor page
   displayed the spec table. A fixture that stops parsing fails here instead of
   silently emptying the catalog again.
2. the resolver + canonicalization + inference-free mapping
   (`scraper/specs/resolvers/vendor_struct.py::parse_detail_specs`) against the
   label/value pairs those pages really use, per category — including the
   negative cases that must NOT produce a fact ("לא תואם AM5", promo copy,
   mojibake, a CPU label on a GPU).

Exit 0 = every assertion held; exit 1 = at least one mismatch (each printed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapy.http import HtmlResponse, Request  # noqa: E402

from scraper.specs import labels, schema  # noqa: E402
from scraper.specs.resolvers import vendor_struct  # noqa: E402
from scraper.spiders.detail_pages import TmsDetailSpider  # noqa: E402

PAGES_DIR = ROOT / "scraper" / "specs" / "golden" / "tms_pages"

# A definition-list template from an older TMS theme: the fallback path must
# keep working even though the current pages use product-attribute-item rows.
DL_PAGE = (
    "<html><body><div class='product-specification'><dl>"
    "<dt>Socket</dt><dd>AM5</dd><dt>Cores</dt><dd>8</dd>"
    "</dl></div></body></html>"
)

# An "empty" page: no spec block at all (challenge page / template change).
EMPTY_PAGE = (
    "<html><head><title>Access</title></head><body>"
    "<div class='nav'><table><tr><th>a</th><td>b</td></tr></table></div>"
    "<p>Please verify you are human.</p></body></html>"
)

SPIDER_CASES = [
    {
        "fixture": "cpu.html",
        "category": "cpu",
        "selector": "attribute-item",
        "rows": 8,
        "expect_specs": {
            "series": "EPYC",
            "socket": "SP5",
            "core_count": 128,
            "integrated_graphics": "no",
            "thread_count": 256,
            "base_clock_ghz": 2.7,
            "boost_clock_ghz": 4.1,
            "l3_cache_mb": 512,
            "tdp_w": 500,
        },
        "expect_gaps": (),
    },
    {
        "fixture": "gpu.html",
        "category": "gpu",
        "selector": "attribute-item",
        "rows": 12,
        "expect_specs": {
            "chipset": "AMD FirePro",
            "core_clock_mhz": 600,
            "memory_gb": 1,
            "memory_type": "GDDR3",
            "length_mm": 170,
            "dvi_outputs": {"DVI": 1},
            "interface": "PCIe 2.0 x16",
            # Three of the four rows that used to be coverage gaps on this
            # page now have a schema home (Oct 2026 completeness pass).
            # "מהירות זכרון" is mapped but its value here (1200MHz) is a
            # memory CLOCK, so the Gbps parser stays silent — pinned by the
            # pair case below (see "gpu memory speed vs bus width").
            "memory_bus_bit": 64,
            "directx": "11",
            "opengl": "4.4",
        },
        # Fields TMS prints that the schema deliberately has no home for yet —
        # they must show up as evidence, not as invented facts.
        # ("Recommended PSU" left this list when its connector half started
        # feeding external_power; the wattage half stays unread.)
        "expect_gaps": (),
    },
]

# Label/value pairs exactly as the vendor pages print them, per category.
PAIR_CASES = [
    {
        "name": "motherboard (ASRock WRX90 WS EVO page)",
        "category": "motherboard",
        "rows": {
            "ערכת שבבים": "AMD WRX90",
            "תושבת מעבד": "sTR5",
            "סוג זכרון": "DDR5 ECC REG | DDR5 ECC REG 3DS",
            "תצורת לוח": "EEB",
            "חיבורי תקשורת": "LAN 10 Gb/s",
            "חיבור גרפי": "DisplayPort",
            "חיבור USB": "USB Type-C | USB 3.2 | USB 2.0",
            "כרטיס קול משולב": "2 port + S/PDIF",
            "RAID": "0,1,10",
            "סלוטים DDR5": "8",
            "PCI-E x16": "7",
            "USB Type-C": "3",
            "USB 3.2": "8",
            "USB 2.0": "4",
            "חריצי הרחבה": "PCIe 5.0 x16 slot",
            "חיבורי M.2 PCIe": "1",
            "חיבורי SATA3": "4",
        },
        "expect_specs": {
            "chipset": "WRX90",
            "socket": "sTR5",
            "memory_type": "DDR5",
            "form_factor": "SSI-EEB",
            "ethernet": "LAN 10 Gb/s",
            "onboard_video": "DisplayPort",
            "usb_ports": "USB Type-C | USB 3.2 | USB 2.0",
            "audio": "2 port + S/PDIF",
            "raid_support": True,
            "memory_slots": 8,
            "pcie_x16_slots": 7,
            "expansion_slots": "PCIe 5.0 x16 slot",
            "m2_slots": ["1"],
            "sata_ports": 4,
        },
        "expect_gaps": ("ממשק אחסון",),
    },
    {
        "name": "motherboard rear USB counts without a type row",
        "category": "motherboard",
        "rows": {"USB Type-C": "3", "USB 3.2": "8"},
        "expect_specs": {"usb_ports": "USB-C x3, USB 3.2 x8"},
        "expect_gaps": (),
    },
    {
        "name": "storage (WD Ultrastar 8TB page)",
        "category": "storage",
        "rows": {
            "סוג דיסק": '3.5"',
            "נפח דיסק": "8TB",
            "מהירות דיסק": "7200 RPM",
            "באפר": "256MB",
            "סוג חיבור - ממשק": "SATA3",
            "סדרת HDD": "Ultrastar",
        },
        "expect_specs": {
            "form_factor": '3.5"',
            "capacity_gb": 8000,
            "rpm": 7200,
            "cache_mb": 256,
            "interface": "SATA 6.0 Gb/s",
            "model": "Ultrastar",
        },
        "expect_gaps": (),
    },
    {
        "name": "memory (G.Skill 2x16GB page)",
        "category": "memory",
        "rows": {
            "סוג זכרון": "DDR5",
            "גודל זיכרון (RAM)": "32GB",
            "סוג תאורה": "ARGB",
            "ערכת זיכרון": "2x16GB",
            "מהירות זכרון (Max)": "5200",
            "זמן איחזור": "CL40",
            "מתח זכרון": "1.1V",
            "צבע": "שחור | כסוף",
            "סדרה": "Trident Z5 RGB",
        },
        "expect_specs": {
            "memory_type": "DDR5",
            "total_gb": 32,
            "lighting": "ARGB",
            "module_count": 2,
            "module_size_gb": 16,
            "speed_mhz": 5200,
            "cas_latency": 40,
            "voltage_v": 1.1,
            "color": "Black / Silver",
            "model": "Trident Z5 RGB",
        },
        "expect_gaps": (),
    },
    {
        "name": "psu",
        "category": "psu",
        "rows": {
            "הספק": "750W",
            "יעילות": "80+ Gold",
            "מודולרי": "Full Modular",
            "אורך": "160mm",
            "מחברי SATA": "6",
            "ללא מאוורר": "לא",
        },
        "expect_specs": {
            "wattage_w": 750,
            "efficiency": "80+ Gold",
            "modular": "full",
            "length_mm": 160,
            "sata_connectors": 6,
            "fanless": False,
        },
        "expect_gaps": (),
    },
    {
        "name": "psu (Plonter detail rows: certificates + connectors)",
        "category": "psu",
        "rows": {
            "certificates-according to manufacturer":
                "80 PLUS Gold (according to manufacturer, 115V)",
            "certificates-loud 80 PLUS":
                "80 PLUS titanium (115V, loud 80 PLUS certificate)",
            "cable-management": "Full Modular",
            "shape-factor": "ATX12V",
            "SATA": "8",
            "IDE": "4",
            "20/24-Pin": "1",
            "4/8-Pin ATX12V": "2",
            "6/8-Pin PCIe": "4",
            "Certificates": "80 PLUS Platinum (according to manufacturer, voltage unknown)",
        },
        "expect_specs": {
            "efficiency": "80+ Gold",
            "modular": "full",
            "type": "ATX",
            "sata_connectors": 8,
            "molex4_connectors": 4,
            "atx4_connectors": 1,
            "eps8_connectors": 2,
            "pcie62_connectors": 4,
        },
        # The 80-PLUS blob must never reach the brand field again
        # (schema.py suffix-matched 'certificates_according_to_manufacturer'
        # onto the `manufacturer` alias until Sep 2026).
        "expect_absent": ("manufacturer",),
        "expect_gaps": (),
    },
    {
        "name": "motherboard combined connectivity cell splits per radio",
        "category": "motherboard",
        "rows": {
            "חיבורי תקשורת": "Bluetooth 5.3 | LAN 2.5 Gb/s | Wi-Fi 6/6E (802.11ax)",
        },
        "expect_specs": {
            "ethernet": "LAN 2.5 Gb/s",
            "wireless": "Wi-Fi 6",
        },
        "expect_gaps": (),
    },
    {
        "name": "motherboard LAN-only connectivity cell",
        "category": "motherboard",
        "rows": {"חיבורי תקשורת": "LAN 10 Gb/s"},
        "expect_specs": {"ethernet": "LAN 10 Gb/s"},
        "expect_gaps": (),
    },
    {
        "name": "case fan",
        "category": "case_fan",
        "rows": {
            "גודל": "120mm",
            "סל\u05f4ד": "500-1500 RPM",
            "רעש": "25.6 dB",
            "pwm": "כן",
            "כיוון זרימה": "הפוך",
        },
        "expect_specs": {
            "size_mm": 120,
            "rpm_min": 500,
            "rpm_max": 1500,
            "noise_db": 25.6,
            "pwm": True,
            "flow_direction": "reverse",
        },
        "expect_gaps": (),
    },
    {
        "name": "cpu cooler",
        "category": "cooler_air",
        "rows": {
            "סל\u05f4ד": "600-1500 RPM",
            "רעש": "23 dB",
            "גובה": "155mm",
            "פיזור חום": "220W",
            "קירור נוזלי": "לא",
        },
        "expect_specs": {
            "fan_rpm_min": 600,
            "fan_rpm_max": 1500,
            "noise_db": 23.0,
            "height_mm": 155,
            "tdp_w": 220,
            "water_cooled": False,
        },
        "expect_gaps": (),
    },
    # --- Oct 2026 coverage pass: one case per new action token, rows shaped
    # like the real vendor cells in data/raw/detail/*.jsonl. ---
    {
        "name": "psu TMS connector rows (Plan 2026-10-02: all four shipped 0%)",
        "category": "psu",
        "rows": {
            "EPS 12V 8 pin": "2",
            "PCI-E Connectors 8 pin": "2",
            "Molex 4 pin": "3",
            "חיבורי SATA": "5",
            "חיבורי 12VHPWR": "1",
            "חיבור לכרטיס מסך (PCIe)": "4 חיבורי PCIe 6+2-pin",
        },
        "expect_specs": {
            "eps8_connectors": 2,
            "pcie8_connectors": 2,
            "molex4_connectors": 3,
            "sata_connectors": 5,
            "pcie12_connectors": 1,
            "pcie62_connectors": 4,
        },
        "expect_gaps": (),
    },
    {
        # 'קבוצת הספק' is the series family range ("650W - 1100W"), not this
        # unit's wattage. It printed first in the vendor table and its low bound
        # used to win the merge, so 143 PSUs shipped the family minimum (a 750W
        # Antec displayed as 650W). Since Oct 2026 it has its own column, so the
        # invariant is now: it lands THERE and never on the rated wattage.
        "name": "psu series range lands on its own column, never the rated wattage",
        "category": "psu",
        "rows": {"קבוצת הספק": "650W - 1100W", "הספק": "700W"},
        "expect_specs": {"wattage_w": 700, "series_wattage_range": "650-1100W"},
        "expect_no_gap": ("קבוצת הספק",),
    },
    {
        "name": "cooler Ivory Intel+AMD socket rows union",
        "category": "cooler_air",
        "rows": {
            "תאימות תושבות INTEL": "LGA 115X / 1200 / 1700 / 1851",
            "תאימות תושבות AMD": "AM5 / AM4",
            "גודל מאוורר כ-": '12 ס"מ',
            "מהירות מקסימלית עד": "2150RPM ±10%",
            "מידות כ-": 'גובה: 164 מ"מ רוחב: 110 מ"מ עומק: 125 מ"מ',
            "סוג קירור": "קירור אוויר",
        },
        "expect_specs": {
            "sockets": ["LGA115X", "LGA1200", "LGA1700", "LGA1851", "AM5", "AM4"],
            "fan_size_mm": 120,
            "fan_rpm_max": 2150,
            "height_mm": 164,
            "water_cooled": False,
        },
        "expect_gaps": (),
    },
    {
        "name": "aio radiator count x fan size arithmetic",
        "category": "aio",
        "rows": {
            "רדיאטורים": "3",
            "מאוורר מובנה (ממ)": "120",
        },
        "expect_specs": {
            "fan_count": 3,
            "fan_size_mm": 120,
            "radiator_size_mm": 360,
        },
        "expect_gaps": (),
    },
    {
        "name": "case Ivory front-matter rows",
        "category": "case",
        "rows": {
            "מידות כ-": "W=220 H=486 D=467mm",
            "תאימות ללוח": "Mini ITX Micro ATX",
            "מקום לכוננים": '• כונן אחד HDD (3.5") • כונן אחד SSD (2.5")',
            "חיבורים בקדמת המארז": "USB 3.0 x2, USB Type-C, אוזניות, מיקרופון",
            "חלון צד": "כולל",
            "ספק כח": "PS2 (ATX) / Mini Redundant (לא כלול)",
            "גודל כרטיס מסך מקסימלי": '31 ס"מ',
            "גובה קירור למעבד מקסימלי": '175 מ"מ',
            "מאוורר קידמי": '2 מאווררי 12 ס"מ ARGB',
            "מאוורר עליון": "3x 140mm",
            "תאימות קירור נוזלי (רדיאטור)": 'עליון: 120 / 240 מ"מ',
            "סוג תאורה": "ARGB",
        },
        "expect_specs": {
            "dimensions_mm": "W=220 H=486 D=467mm",
            "mb_form_factors": ["Mini ITX", "Micro ATX"],
            "drive_bays_35": 1,
            "drive_bays_25": 1,
            "front_usb": ["USB 3.0", "USB (Type-C)", "Microphone", "Headphone"],
            "side_panel": "Windowed",
            "psu_included": "Not included",
            "max_gpu_length_mm": 310,
            "max_cooler_height_mm": 175,
            "fan_front": "2 x 120 mm ARGB",
            "fan_top": "3 x 140 mm",
            "radiator_support": {"120 mm": 1, "240 mm": 1},
            "lighting": "ARGB",
        },
        "expect_gaps": (),
    },
    {
        "name": "motherboard Ivory support cells expand to four fields",
        "category": "motherboard",
        "rows": {
            "תמיכה בזכרון (RAM)": '4 סלוטים DDR5, תומכים עד 256GB סה"כ מהירות נתמכת עד 9200MT/s',
            "תמיכה באחסון": "4x M.2 slots, 4x SATA 6Gb/s, RAID 0/1",
            "גודל לוח": "ATX",
            "חיבורי USB": "2 חיבורי USB 10Gbps (Type-A)",
            "חיבורים בלוח האם (בגב המחשב)": "HDMI | DisplayPort",
            "חיבורים פנימיים בלוח האם": "2x מחבר מאוורר, 1x מחבר USB 2.0",
            "קישוריות Wi-Fi": "Wi-Fi 7",
            "כרטיס רשת קווי (LAN)": "Realtek 2.5Gb Ethernet",
            "כרטיס קול": "Realtek 7.1",
        },
        "expect_specs": {
            "memory_slots": 4,
            "memory_type": "DDR5",
            "memory_max_gb": 256,
            "memory_speeds": ["9200"],
            "m2_slots": ["4"],
            "sata_ports": 4,
            "raid_support": True,
            "form_factor": "ATX",
            "onboard_video": "DisplayPort | HDMI",
            "wireless": "Wi-Fi 7",
        },
        "expect_gaps": (),
    },
    {
        # Ivory prints SATA ports as '2 חיבורי SATA 6G' (116 rows on disk) —
        # the Hebrew spelling; only the English '4x SATA 6Gb/s' shape was
        # parsed before Oct 2026, so every one of those cells shipped a null.
        "name": "SATA ports in the Hebrew 'N חיבורי SATA' spelling",
        "category": "motherboard",
        "rows": {
            "תמיכה באחסון": "מנוהל לוח אם • M.2_1 – PCIe 4.0 x4 2 חיבורי SATA 6G",
        },
        "expect_specs": {"sata_ports": 2},
        "expect_gaps": (),
    },
    {
        # Some boards list SATA ports in the internal-header cell instead.
        "name": "SATA ports living in the internal-header cell",
        "category": "motherboard",
        "rows": {
            "חיבורים פנימיים בלוח האם":
                "4 חיבורי SATA, 2x מחבר מאוורר, 1x USB 3.2 Gen 1 header",
        },
        "expect_specs": {"sata_ports": 4, "fan_headers": 2, "usb32_gen1_headers": 1},
        "expect_gaps": (),
    },
    {
        # The count leads the word: 'SATA 6Gb/s' puts the number after it and a
        # junk-drawer cell prints 'PCIe 4.0 x4 / SATA mode'. Neither is a count.
        "name": "SATA shapes that are not port counts stay unparsed",
        "category": "motherboard",
        "rows": {"תמיכה באחסון": "SATA 6Gb/s support, M.2 (PCIe 4.0 x4 / SATA mode)"},
        "expect_absent": ("sata_ports",),
        "expect_gaps": (),
    },
    {
        "name": "English-order support cell never reads the DDR generation",
        "category": "motherboard",
        "rows": {
            "תמיכה בזכרון (RAM)": "2 DDR5 slots, up to 128GB, up to 8200MT/s",
        },
        "expect_specs": {
            "memory_slots": 2,
            "memory_type": "DDR5",
            "memory_max_gb": 128,
            "memory_speeds": ["8200"],
        },
        "expect_gaps": (),
    },
    {
        "name": "motherboard x16 slot rows sum, x1 rows sum",
        "category": "motherboard",
        "rows": {
            "PCI-E x16": "2",
            "PCI-E x16 (x4) Slot": "1",
            "PCI-E x1": "2",
        },
        "expect_specs": {
            "pcie_x16_slots": 3,
            "pcie_x1_slots": 2,
        },
        "expect_gaps": (),
    },
    {
        "name": "gpu 1PC grouped VRAM rows + counted outputs",
        "category": "gpu",
        "rows": {
            "RAM / RAM Size": "16GB",
            "RAM / RAM type": "GDDR7",
            "סוג קירור": "3 מאווררים",
            "יציאות תצוגה בכרטיס המסך": "1x HDMI 2.1b 3x DisplayPort 2.1b",
            "חיבורי ספק כח": "1x16-pin",
        },
        "expect_specs": {
            "memory_gb": 16,
            "memory_type": "GDDR7",
            "cooling": "Air",
            "dp_outputs": {"DisplayPort": 3},
            "hdmi_outputs": {"HDMI": 1},
        },
        "expect_gaps": (),
    },
    {
        "name": "case_fan Hebrew counts + connector + tolerance rpm",
        "category": "case_fan",
        "rows": {
            "מספר מאווררים": "3-Pack",
            "סוג חיבור": "4pin PWM",
            "מהירות סיבוב": "400RPM ~ 1850RPM ±10%",
            "גודל כ-": '12 ס"מ',
        },
        "expect_specs": {
            "quantity": 3,
            "connector": "4-pin",
            "pwm": True,
            "rpm_min": 400,
            "rpm_max": 1850,
            "size_mm": 120,
        },
        "expect_gaps": (),
    },
    {
        "name": "storage grouped cells",
        "category": "storage",
        "rows": {
            "Storage memory": "TLC | 3D/V NAND",
            "גודל פיזי": "M.2 2280",
            "Spec / Interface Connectivity": "PCIe Gen 4.0 x4",
        },
        "expect_specs": {
            "nand": "3D NAND",
            "form_factor": "M.2-2280",
            "interface": "PCIe Gen 4.0 x4",
            "pcie_gen": 4,
        },
        "expect_gaps": (),
    },
    {
        "name": "1PC network card cell routes per radio, never to ethernet whole",
        "category": "motherboard",
        "rows": {"Spec / Network Card": "Wi-Fi 6"},
        "expect_specs": {"wireless": "Wi-Fi 6"},
        "expect_absent": ("ethernet",),
        "expect_gaps": (),
    },
    {
        "name": "unseen English spelling still reaches the curated key",
        "category": "psu",
        "rows": {"PCI Express connectors 8pin": "3"},
        "expect_specs": {"pcie8_connectors": 3},
        "expect_gaps": (),
    },
    {
        "name": "case 1PC front-panel USB routes to front_usb",
        "category": "case",
        "rows": {"Spec / Interface Connectivity": "USB 3.2, USB-C"},
        "expect_specs": {"front_usb": ["USB 3.2", "USB-C"]},
        "expect_gaps": (),
    },
    # ----- YahavPC (Oct 2026) -----
    # Its product pages print five-ish Hebrew rows with no spelling overlap
    # with the other vendors, so each one is pinned here against the live
    # values (verified on /product pages 2026-10-14).
    {
        "name": "YahavPC CPU rows (bare-number socket, processor family)",
        "category": "cpu",
        "rows": {"תושבת": "1851", "מספר ליבות": "32", "סוג מעבד": "Ultra 9",
                 "יצרן": "Intel", "משך אחריות": "36 חודשים"},
        "expect_specs": {"socket": "LGA1851", "core_count": 32,
                         "series": "Ultra 9", "manufacturer": "Intel"},
        "expect_no_gap": ("משך אחריות",),
        "expect_gaps": (),
    },
    {
        "name": "YahavPC case fan rows (size in MM, lighting yes/no)",
        "category": "case_fan",
        "rows": {"גודל": "120MM", "תאורה": "ללא", "יצרן": "NZXT"},
        # The negative lighting spelling is canon_lighting's "No" (Oct 2026:
        # it used to be "None", which values.coerce then re-read as the
        # no-data placeholder and dropped).
        "expect_specs": {"size_mm": 120, "led": "No", "manufacturer": "NZXT"},
        "expect_gaps": (),
    },
    {
        "name": "gpu memory rows: data rate and bus width (Oct 2026)",
        "category": "gpu",
        "rows": {"מהירות זכרון": "28Gbps", "רוחב פס זכרון": "256bit"},
        "expect_specs": {"memory_speed_gbps": 28, "memory_bus_bit": 256},
        "expect_gaps": (),
    },
    {
        "name": "gpu memory clock never becomes a data rate (Oct 2026)",
        "category": "gpu",
        # A GDDR3 clock in MHz under the same label as the Gbps rate; the
        # parser is unit-gated, so the fact stays unknown instead of wrong.
        "rows": {"מהירות זכרון": "1200MHz", "רוחב פס זכרון": "64bit"},
        "expect_specs": {"memory_bus_bit": 64},
        "expect_absent": ("memory_speed_gbps",),
        "expect_gaps": (),
    },
    {
        "name": "gpu display count and API rows (Oct 2026)",
        "category": "gpu",
        # Ivory's "עד 4 מסכים" and TMS's bare count are the same fact.
        "rows": {"תמיכה מרבית במסכים": "עד 4 מסכים", "גרסת DirectX": "12 Ultimate",
                 "גרסת OpenGL": "4.6", "הספק מינימלי": "750W"},
        "expect_specs": {"max_displays": 4, "directx": "12 Ultimate",
                         "opengl": "4.6", "recommended_psu_w": 750},
        "expect_gaps": (),
    },
    {
        "name": "drive throughput with separators and units (Oct 2026)",
        "category": "storage",
        # "10,000MB" is ten thousand MB, not 10.0 (the comma is a thousands
        # mark) and "1.5GB/s" is 1500 MB/s.
        "rows": {"מהירות קריאה": "10,000MB לשניה", "מהירות כתיבה": "1.5GB/s"},
        "expect_specs": {"read_speed_mbs": 10000, "write_speed_mbs": 1500},
        "expect_gaps": (),
    },
    {
        "name": "drive random IOPS with the K suffix (Oct 2026)",
        "category": "storage",
        "rows": {"מהירות קריאה אקראית": "(QD32) 1,850K IOPS",
                 "מהירות כתיבה אקראית": "98,000 IOPS"},
        "expect_specs": {"random_read_iops": 1850000, "random_write_iops": 98000},
        "expect_gaps": (),
    },
    {
        "name": "packaging cell carries an English word plus a Hebrew gloss",
        "category": "memory",
        # As a plain value the whole cell was dropped (Hebrew prose); the
        # leading English word is the fact.
        "rows": {"אריזה": "Retail - קופסה"},
        "expect_specs": {"packaging": "boxed"},
        "expect_gaps": (),
    },
    {
        "name": "case bays and rackmount rows (Oct 2026)",
        "category": "case",
        # "2+1" is two dedicated bays plus a shared one (canon_bay_count).
        "rows": {"Bays 5.25": "2+1", "Rackmount": "כן"},
        "expect_specs": {"drive_bays_525": 3, "rackmount": True},
        "expect_gaps": (),
    },
    {
        "name": "aio radiator dimensions and pump block (Oct 2026)",
        "category": "aio",
        "rows": {"מידות רדיאטור": "אורך: 403 מ\"מ רוחב: 120 מ\"מ עובי: 27 מ\"מ",
                 "מידות משאבה": "אורך: 69 מ\"מ רוחב: 92 מ\"מ גובה: 76 מ\"מ"},
        "expect_specs": {"radiator_length_mm": 403, "radiator_thickness_mm": 27,
                         "pump_dimensions_mm": "69 × 92 × 76 mm"},
        "expect_gaps": (),
    },
    {
        "name": "cooler wiring prose reduces to the connector list (Oct 2026)",
        "category": "aio",
        "rows": {"חיבורים": "• חיבור 4pin PWM ללוח אם או בקר מאווררים • חיבור 3pin ARGB "
                            "ללוח אם • חיבור USB2.0 פנימי ללוח אם"},
        "expect_specs": {"connectors": ["4-pin PWM", "3-pin ARGB", "USB 2.0"]},
        "expect_gaps": (),
    },
    {
        "name": "motherboard storage interface + PCIe slot kinds (Oct 2026)",
        "category": "motherboard",
        # The x4 row joins the x16/x1 rows in the slot sum; the interface
        # cell keeps the vendor's names as a list.
        "rows": {"ממשק אחסון": "M.2 PCIe | SATA3", "PCI-E x4": "1",
                 "PCI-E x16": "2", "קישוריות Bluetooth": "Bluetooth 5.3"},
        "expect_specs": {"storage_interface": ["M.2 PCIe", "SATA3"],
                         "pcie_x4_slots": 1, "pcie_x16_slots": 2,
                         "bluetooth": "Bluetooth 5.3"},
        "expect_gaps": (),
    },
    {
        "name": "cpu chipset support list (Oct 2026)",
        "category": "cpu",
        "rows": {"תאימות ערכת שבבים": "Intel Z690 | Intel H610 | Intel B660"},
        "expect_specs": {"chipset_support": ["Intel Z690", "Intel H610", "Intel B660"]},
        "expect_gaps": (),
    },
    {
        "name": "YahavPC motherboard connectivity splits into radios",
        "category": "motherboard",
        "rows": {"קישוריות": "Wired LAN, Bluetooth, Wi-Fi", "תושבת": "AM5",
                 "ערכת שבבים": "AMD X870E", "חיבורי תצוגה": "Display Port"},
        "expect_specs": {"wireless": "Yes", "ethernet": "Ethernet",
                         "socket": "AM5", "chipset": "X870E",
                         "onboard_video": "DisplayPort"},
        # The cell names Bluetooth, so it must never become the LAN string.
        "expect_no_gap": ("קישוריות",),
        "expect_gaps": (),
    },
    {
        "name": "YahavPC GPU display rows count every port",
        "category": "gpu",
        "rows": {"ליבה גראפית": "GeForce RTX 5090",
                 "חיבורי תצוגה": "3X Display Port, HDMI"},
        "expect_specs": {"chipset": "GeForce RTX 5090",
                         "dp_outputs": {"DisplayPort": 3},
                         "hdmi_outputs": {"HDMI": 1}},
        "expect_gaps": (),
    },
    {
        "name": "YahavPC memory capacity row is the kit total",
        "category": "memory",
        "rows": {"זיכרון": "64GB", "מהירות זכרון": "6000Mhz",
                 "סוג זיכרון": "DDR5"},
        "expect_specs": {"total_gb": 64, "speed_mhz": 6000,
                         "memory_type": "DDR5"},
        "expect_gaps": (),
    },
    {
        "name": "YahavPC case rows (size class, PSU slot)",
        "category": "case",
        "rows": {"גודל מארז": "Full Tower", "וואט / WATT / אמפר": "ללא"},
        "expect_specs": {"type": "Full Tower", "psu_included": "Not included"},
        "expect_gaps": (),
    },
    {
        "name": "CPU cache tiers share one cell (TMS combined row)",
        "category": "cpu",
        "rows": {"זכרון מטמון במעבד": "L1 1280KB | L2 16MB | L3 128MB"},
        "expect_specs": {"l2_cache_mb": 16, "l3_cache_mb": 128},
        "expect_absent": ("cache_mb",),
        "expect_gaps": (),
    },
    {
        "name": "CPU cache tiers without pipes (Ivory row)",
        "category": "cpu",
        "rows": {"זכרון מטמון (Cache)": "L2 - 8MB L3 - 96MB"},
        "expect_specs": {"l2_cache_mb": 8, "l3_cache_mb": 96},
        "expect_gaps": (),
    },
    {
        "name": "CPU Intel Smart Cache bucket is L3",
        "category": "cpu",
        "rows": {"זכרון מטמון במעבד": "36MB Intel Smart Cache"},
        "expect_specs": {"l3_cache_mb": 36},
        "expect_absent": ("l2_cache_mb",),
        "expect_gaps": (),
    },
    {
        "name": "CPU bare cache number stays untiered (L3-vs-total ambiguity)",
        "category": "cpu",
        "rows": {"זכרון מטמון במעבד": "144MB"},
        "expect_absent": ("l2_cache_mb", "l3_cache_mb", "cache_mb"),
        "expect_gaps": (),
    },
    {
        "name": "Fan lone RPM figure is a maximum, not a min==max part",
        "category": "case_fan",
        "rows": {"מהירות מאוורר": "2200 RPM"},
        "expect_specs": {"rpm_max": 2200},
        "expect_absent": ("rpm_min",),
        "expect_gaps": (),
    },
    {
        "name": "1PC graphics-model row is the iGPU, not the model (cpu)",
        "category": "cpu",
        "rows": {"GPU / Graphics Card Model": "Intel UHD Graphics 770"},
        "expect_specs": {"integrated_graphics": "Intel UHD Graphics 770"},
        "expect_absent": ("model",),
        "expect_gaps": (),
    },
    {
        "name": "1PC graphics absence row reads as no iGPU (cpu)",
        "category": "cpu",
        "rows": {"GPU / Graphics Card Model": "Without a graphics processor."},
        "expect_specs": {"integrated_graphics": "no"},
        "expect_absent": ("model",),
        "expect_gaps": (),
    },
    {
        "name": "Dedicated USB counts feed the rear summary (motherboard)",
        "category": "motherboard",
        "rows": {"USB 2.0": "5", "USB 3.2": "4", "USB Type-C": "1"},
        "expect_specs": {"usb_ports": "USB 2.0 x5, USB 3.2 x4, USB-C x1"},
        "expect_gaps": (),
    },
    {
        "name": "ECC/registered ride inside memory_type strings (memory)",
        "category": "memory",
        "rows": {"סוג זכרון": "DDR5 ECC REG"},
        "expect_specs": {"ecc": True, "registered": True},
        "expect_gaps": (),
    },
    {
        "name": "Explicit ECC absence is False, not a gap (memory)",
        "category": "memory",
        "rows": {"תאימות ECC": "ללא ECC"},
        "expect_specs": {"ecc": False},
        "expect_gaps": (),
    },
    {
        "name": "Case notes GPU clearance is read, nothing else (case)",
        "category": "case",
        "rows": {"הערות": "Max GPU Length ≤ 408mm"},
        "expect_specs": {"max_gpu_length_mm": 408},
        "expect_gaps": (),
    },
    {
        "name": "Recommended-PSU connector string (gpu)",
        "category": "gpu",
        "rows": {"Recommended PSU": "350W with Power Connector 3x8-pin"},
        "expect_specs": {"external_power": ["3x8-pin"]},
        "expect_gaps": (),
    },
    {
        "name": "12VHPWR reads as one 16-pin (gpu)",
        "category": "gpu",
        "rows": {"Recommended PSU": "750W with Power Cable 12VHPWR"},
        "expect_specs": {"external_power": ["1x16-pin"]},
        "expect_gaps": (),
    },
    {
        "name": "AIO fan count divides out (aio)",
        "category": "aio",
        "rows": {"גודל רדיאטור": "360 מ״מ", "גודל מאוורר": "120 מ״מ"},
        "expect_specs": {"radiator_size_mm": 360, "fan_size_mm": 120,
                         "fan_count": 3},
        "expect_gaps": (),
    },
    {
        "name": "Case volume from full dimensions (case)",
        "category": "case",
        "rows": {"מידות כ-": "W=220 H=486 D=467mm"},
        "expect_specs": {"volume_l": 49.9},
        "expect_gaps": (),
    },
    {
        "name": "Reverse-blade model names the direction (case_fan)",
        "category": "case_fan",
        "rows": {"דגם": "P12 Pro Reverse A-RGB"},
        "expect_specs": {"flow_direction": "reverse"},
        "expect_gaps": (),
    },
    {
        "name": "Memory support speed lists (motherboard)",
        "category": "motherboard",
        "rows": {"תמיכה בזיכרון": "Dual Channel DDR5-7000MHz OC"},
        "expect_specs": {"memory_speeds": ["7000"]},
        "expect_gaps": (),
    },
    {
        "name": "Counted expansion-slot prose (case)",
        "category": "case",
        "rows": {"מספר חריצי הרחבה": "8 חריצי הרחבה אופקיים"},
        "expect_specs": {"expansion_slots": "8"},
        "expect_gaps": (),
    },
    {
        "name": "Thermal-design positions split into mounts (case)",
        "category": "case",
        "rows": {"עיצוב תרמי": "Front Fans 2x80x25mm | Rear 1x120mm"},
        "expect_specs": {"fan_front": "2 fans", "fan_rear": "1 x 120 mm"},
        "expect_gaps": (),
    },
    {
        "name": "WINDFORCE marketing line is air cooling (gpu)",
        "category": "gpu",
        "rows": {"עיצוב תרמי": "WINDFORCE cooling system"},
        "expect_specs": {"cooling": "Air"},
        "expect_gaps": (),
    },
]

NEGATIVE_CASES = [
    {
        "name": "Plonter promo copy is not a spec",
        "category": "memory",
        "rows": {"מפרט זיכרון": "לחץ/י לרכישה עכשיו"},
        "expect_no_facts": True,
    },
    {
        "name": "mojibake is not a spec",
        "category": "memory",
        "rows": {"דגם": "׳™׳¦׳¨׳�"},
        "expect_no_facts": True,
    },
    {
        "name": "a negated Hebrew sentence is dropped, never half-read",
        "category": "motherboard",
        "rows": {"תושבת": "לא תואם AM5"},
        "expect_absent": ("socket",),
    },
    {
        "name": "vendor SKU rows never become part_numbers",
        "category": "storage",
        "rows": {"מק\u05f4ט": "100-000001443", "sku": "ABC-1"},
        "expect_absent": ("part_numbers",),
    },
    {
        "name": "an unknown Hebrew label is reported, not guessed",
        "category": "cpu",
        "rows": {"יכולת מיוחדת": "טכנולוגיה"},
        "expect_absent": ("socket", "core_count"),
        "expect_gap": "יכולת מיוחדת",
    },
    {
        "name": "a novel Hebrew label is never relaxed-guessed",
        "category": "psu",
        "rows": {"חיבורי סאטה": "5"},
        "expect_absent": ("sata_connectors",),
        "expect_gap": "חיבורי סאטה",
    },
    {
        # The grouped cell's three shapes, pinned separately so the VRAM
        # reader can never claim a bus width (it did until Oct 2026): the type
        # only, the capacity+type pair, and the bus width on its own column.
        "name": "a bus-width cell fills the bus, never a VRAM size",
        "category": "gpu",
        "rows": {"Storage / Storage Type": "512-bit"},
        "expect_specs": {"memory_bus_bit": 512},
        "expect_absent": ("memory_gb",),
    },
    {
        "name": "a VRAM cell keeps filling size and type",
        "category": "gpu",
        "rows": {"Storage / Storage Type": "12GB GDDR7"},
        "expect_specs": {"memory_gb": 12, "memory_type": "GDDR7"},
        "expect_absent": ("memory_bus_bit",),
    },
    {
        "name": "an RPM tolerance is stripped, never read as a range",
        "category": "case_fan",
        "rows": {"מהירות סיבוב": "1500RPM ±10%"},
        "expect_specs": {"rpm_max": 1500},
        "expect_absent": ("rpm_min",),
    },
    {
        "name": "warranty rows are bookkeeping, not specs and not gaps",
        "category": "motherboard",
        "rows": {"Warranty / Importer": "3 שנים", "אחריות": "36 חודשים"},
        "expect_no_facts": True,
        "expect_no_gap": ("Warranty / Importer", "אחריות"),
    },
    # Oct 2026 completeness pass (batch 3): generation, drive weight, the
    # grouped "Storage / Storage Type" cell and the cooler/fan wiring cell.
    {
        # Hebrew בניין and Intel's own "Series N" wording name the same fact.
        "name": "a generation row reads whichever way the vendor spells it",
        "category": "cpu",
        "rows": {"דור המעבד": "דור 14"},
        "expect_specs": {"generation": "Gen 14"},
    },
    {
        "name": "Intel's Series N is the same column, same shape",
        "category": "cpu",
        "rows": {"דור המעבד": "Series 2"},
        "expect_specs": {"generation": "Gen 2"},
    },
    {
        # A bare number is not proof of a generation: reading it would put an
        # unexplained digit in the column.
        "name": "a bare number is not a generation",
        "category": "cpu",
        "rows": {"דור המעבד": "14"},
        "expect_absent": ("generation",),
    },
    {
        "name": "a Hebrew drive weight reads in grams",
        "category": "storage",
        "rows": {"משקל": "32.7 גרם"},
        "expect_specs": {"weight_g": 32.7},
    },
    {
        # The unit decides the scale; "כ-" (approximately) is prose.
        "name": "a kilogram drive weight is scaled, not copied",
        "category": "storage",
        "rows": {"משקל המוצר": "כ-2.49 ק\"ג"},
        "expect_specs": {"weight_g": 2490},
    },
    {
        "name": "a weight cell with no number stays unread",
        "category": "storage",
        "rows": {"משקל": "אין נתון"},
        "expect_absent": ("weight_g",),
    },
    {
        # 1PC's English twin of Ivory's Hebrew storage-interface row.
        "name": "the grouped storage-type cell gives a board its drive interfaces",
        "category": "motherboard",
        "rows": {"Storage / Storage Type": "M.2, SATA III"},
        "expect_specs": {"storage_interface": ["M.2", "SATA III"]},
    },
    {
        "name": "the same cell gives a drive its type",
        "category": "storage",
        "rows": {"Storage / Storage Type": "SSD NVMe"},
        "expect_specs": {"type": "SSD"},
    },
    {
        "name": "a fan's grouped cell fills its connector",
        "category": "case_fan",
        "rows": {"Spec / Interface Connectivity": "iCUE LINK"},
        "expect_specs": {"connector": "iCUE LINK"},
        "expect_absent": ("led",),
    },
    {
        "name": "a fan's ARGB is lighting, not a connector",
        "category": "case_fan",
        "rows": {"Spec / Interface Connectivity": "ARGB"},
        "expect_specs": {"led": "ARGB"},
        "expect_absent": ("connector",),
    },
    {
        "name": "a cooler's grouped cell is its connector list",
        "category": "aio",
        "rows": {"Spec / Interface Connectivity": "4PIN PWM"},
        "expect_specs": {"connectors": ["4PIN PWM"]},
    },
    {
        # Deliberate: 1PC's PSU cell carries "Modular.", which is genuinely
        # ambiguous (semi or full — 5 Yahav units prove the vendors lump them),
        # so it stays coverage-gap evidence instead of inventing "full".
        "name": "an ambiguous PSU modularity cell is a gap, not a guess",
        "category": "psu",
        "rows": {"Spec / Interface Connectivity": "Modular."},
        "expect_absent": ("modular",),
        "expect_gap": "Spec / Interface Connectivity",
    },
]


def load_page(path: Path, url: str, sku: str = "TEST-1") -> HtmlResponse:
    request = Request(url=url, meta={"vendor_sku": sku})
    return HtmlResponse(url=url, body=path.read_bytes(), encoding="utf-8",
                        request=request)


def check_spider_cases(failures: list[str]) -> int:
    checked = 0
    spider = TmsDetailSpider()
    for case in SPIDER_CASES:
        path = PAGES_DIR / case["fixture"]
        if not path.exists():
            failures.append(f"{case['fixture']}: fixture missing ({path})")
            continue
        response = load_page(path, f"https://tms.co.il/x/{case['fixture']}")
        items = list(spider.parse_detail(response))
        if not items:
            failures.append(f"{case['fixture']}: spider yielded no item")
            continue
        item = items[0]
        extra = item.get("extra") or {}
        checked += 1
        if extra.get("spec_selector") != case["selector"]:
            failures.append(
                f"{case['fixture']}: selector {extra.get('spec_selector')!r} != "
                f"{case['selector']!r}")
        checked += 1
        if extra.get("spec_rows") != case["rows"]:
            failures.append(
                f"{case['fixture']}: spec_rows {extra.get('spec_rows')!r} != "
                f"{case['rows']!r}")
        checked += 1
        if not item.get("specs"):
            failures.append(f"{case['fixture']}: specs empty — regression")

        gaps: dict[str, int] = {}
        specs = vendor_struct.parse_detail_specs(case["category"],
                                                 item.get("specs"), gaps=gaps)
        for field, expected in case["expect_specs"].items():
            actual = specs.get(field, [None])[0]
            value = actual.value if actual is not None else None
            checked += 1
            if value != expected:
                failures.append(
                    f"{case['fixture']}: {field} = {value!r}, expected {expected!r}")
        for label in case["expect_gaps"]:
            checked += 1
            if label not in gaps:
                failures.append(
                    f"{case['fixture']}: label {label!r} should be reported as a "
                    "coverage gap")
    return checked


def check_pair_cases(failures: list[str]) -> int:
    checked = 0
    for case in PAIR_CASES + NEGATIVE_CASES:
        name = case["name"]
        gaps: dict[str, int] = {}
        facts = vendor_struct.parse_detail_specs(case["category"], case["rows"],
                                                 gaps=gaps)
        values = {field: entries[0].value for field, entries in facts.items()}
        if case.get("expect_no_facts"):
            checked += 1
            if values:
                failures.append(f"{name}: expected no facts, got {values!r}")
            continue
        for field, expected in (case.get("expect_specs") or {}).items():
            checked += 1
            if values.get(field) != expected:
                failures.append(
                    f"{name}: {field} = {values.get(field)!r}, expected {expected!r}")
        for field in case.get("expect_absent") or ():
            checked += 1
            if field in values:
                failures.append(
                    f"{name}: {field} should be absent, got {values[field]!r}")
        if case.get("expect_gap"):
            checked += 1
            if case["expect_gap"] not in gaps:
                failures.append(
                    f"{name}: label {case['expect_gap']!r} should be reported as a "
                    "coverage gap")
        for label in case.get("expect_no_gap") or ():
            checked += 1
            if label in gaps:
                failures.append(
                    f"{name}: label {label!r} is bookkeeping and must not be "
                    "reported as a coverage gap")
    return checked


def check_chipset_and_efficiency(failures: list[str]) -> int:
    """Concatenated vendor chipset cells and certificate blobs (Sep 2026)."""
    from scraper.specs.canon import canon_chipset, canon_efficiency
    checked = 0
    for raw, expected in (
        ("AMDB850AMDX670", "B850"),
        ("AMDX870EAMDX870AMDX670", "X870E"),
        ("INTELH810INTELH610", "H810"),
        ("Z890INTELZ890", "Z890"),
        ("INTELB860INTELB760", "B860"),
        ("AMDB840INTELB760", "B840"),
        ("AMDA620AMDX670", "A620"),
        ("AMDB650AMDB550", "B650"),
        ("B760EXPRESS", "B760"),
        ("AMDWRX80", "WRX80"),
        ("C612PCH", "C612"),
        ("AMD B850", "B850"),
        ("B650", "B650"),
        ("X570S", "X570S"),
        ("B760M", "B760"),
        ("Intel W890", "W890"),
        ("Intel C741", "C741"),
        ("Q670", "Q670"),
        ("SoC (System-on-Chip)", "SoC"),
    ):
        checked += 1
        actual = canon_chipset(raw)
        if actual != expected:
            failures.append(f"canon_chipset({raw!r}) = {actual!r}, expected {expected!r}")
    for raw, expected in (
        ("80 PLUS Gold (according to manufacturer, 115V)", "80+ Gold"),
        ("80 PLUS Gold (115V, loud 80 PLUS certificate)", "80+ Gold"),
        ("80 PLUS titanium (according to manufacturer, voltage unknown)",
         "80+ Titanium"),
        ("80+ Gold", "80+ Gold"),
        ("Gold", "80+ Gold"),
        ("80 PLUS Bronze", "80+ Bronze"),
    ):
        checked += 1
        actual = canon_efficiency(raw)
        if actual != expected:
            failures.append(
                f"canon_efficiency({raw!r}) = {actual!r}, expected {expected!r}")
    return checked


def check_socket_canon(failures: list[str]) -> int:
    """Socket spellings converge; junk never reaches the site (Oct 2026).

    The 115X family shorthand arrives in three spellings and must filter as
    one; cut fragments and typos ('\\\\ 1954') are dropped, never displayed.
    """
    from scraper.specs.canon import canon_socket, canon_socket_list
    checked = 0
    for raw, expected in (
        ("115X", "LGA115X"),
        ("LGA 115X", "LGA115X"),
        ("LGA115X", "LGA115X"),
        ("1851", "LGA1851"),
        ("AM5", "AM5"),
        ("AMD AM5 (LGA1718)", "AM5"),
        ("sTR5", "sTR5"),
        ("LGA2011-3", "LGA2011-3"),
        ("", ""),
    ):
        checked += 1
        actual = canon_socket(raw)
        if actual != expected:
            failures.append(f"canon_socket({raw!r}) = {actual!r}, expected {expected!r}")
    for raw, expected in (
        ("\\ 1954", ""),
        ("1954", ""),
        ("\\ 1851", "LGA1851"),
    ):
        checked += 1
        actual = canon_socket(raw)
        if actual != expected:
            failures.append(f"canon_socket({raw!r}) = {actual!r}, expected {expected!r}")
    checked += 1
    actual = canon_socket_list("Intel LGA 115X/1200/1700/1851, AMD AM4/AM5")
    if actual != ["LGA115X", "LGA1200", "LGA1700", "LGA1851", "AM4", "AM5"]:
        failures.append(f"canon_socket_list group = {actual!r}")
    return checked


def check_template_fallbacks(failures: list[str]) -> int:
    checked = 0
    spider = TmsDetailSpider()
    for name, body, selector, expected in (
        ("definition-list page", DL_PAGE, "definition-list",
         {"Socket": "AM5", "Cores": "8"}),
        ("empty page", EMPTY_PAGE, "none", {}),
    ):
        response = HtmlResponse(url="https://tms.co.il/x", body=body.encode("utf-8"),
                                encoding="utf-8")
        specs, matched, _rows = spider._parse_specs(response)
        checked += 2
        if matched != selector:
            failures.append(f"{name}: selector {matched!r} != {selector!r}")
        if specs != expected:
            failures.append(f"{name}: specs {specs!r} != {expected!r}")
    return checked


def check_category_awareness(failures: list[str]) -> int:
    """The same Hebrew label means different fields per category."""
    checked = 0
    for category, label, expected in (
        ("cpu", "מעבד גרפי", "integrated_graphics"),
        ("gpu", "מעבד גרפי", "chipset"),
        ("gpu", "חיבור גרפי", labels.GPU_OUTPUTS),
        ("motherboard", "חיבור גרפי", "onboard_video"),
        ("memory", "סדרה", "model"),          # memory has no `series`
        ("cpu", "סדרה", "series"),
    ):
        actual = labels.translate_vendor_label(label, category)
        checked += 1
        if actual != expected:
            failures.append(
                f"{category}: {label!r} -> {actual!r}, expected {expected!r}")
    checked += 1
    if not labels.is_ignored_label("מק\u05f4ט"):
        failures.append("the Hebrew SKU label should be ignored")
    return checked


def check_mapped_fields_exist(failures: list[str]) -> int:
    """Every label in the vocabulary must point at a real field or action token."""
    checked = 0
    for category, table in labels.CATEGORY_LABELS.items():
        fields = schema.field_map(category)
        for label, target in table.items():
            if labels._is_token(target):
                continue
            if target not in fields and target not in labels._FIELD_FALLBACKS:
                failures.append(
                    f"{category}: label {label!r} maps to unknown field {target!r}")
            checked += 1
    return checked


def main() -> int:
    failures: list[str] = []
    checked = 0
    checked += check_spider_cases(failures)
    checked += check_pair_cases(failures)
    checked += check_template_fallbacks(failures)
    checked += check_category_awareness(failures)
    checked += check_mapped_fields_exist(failures)
    checked += check_chipset_and_efficiency(failures)
    checked += check_socket_canon(failures)

    if failures:
        print(f"[tms-detail] FAIL — {len(failures)} mismatch(es):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"[tms-detail] pass — {checked} assertions")
    print(json.dumps({"assertions": checked, "fixtures": len(SPIDER_CASES),
                      "pair_cases": len(PAIR_CASES) + len(NEGATIVE_CASES)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
