import type { CompatCode, CompatIssue } from "./build";
import { SPEC_FIELDS, SPEC_LABELS } from "./specSchema.generated";
import type { Lang } from "./types";

// Fixed build order (not alphabetical) — mirrors how someone actually plans
// a build: brain first, then the board it plugs into, then everything else.
export const CATEGORY_ORDER = [
  "cpu",
  "motherboard",
  "memory",
  "gpu",
  "storage",
  "psu",
  "case",
  "case_fan",
  "aio",
  "cooler_air",
  "cooling_other",
  "accessories",
  "other",
] as const;

const CATEGORY_LABELS: Record<string, { he: string; en: string }> = {
  cpu: { he: "מעבדים", en: "Processors" },
  motherboard: { he: "לוחות אם", en: "Motherboards" },
  memory: { he: "זיכרון", en: "Memory" },
  gpu: { he: "כרטיסי מסך", en: "Graphics Cards" },
  storage: { he: "אחסון", en: "Storage" },
  psu: { he: "ספקי כוח", en: "Power Supplies" },
  case: { he: "מארזים", en: "Cases" },
  case_fan: { he: "מאווררים למארז", en: "Case Fans" },
  fan: { he: "מאווררים", en: "Fans" },
  fan_controller: { he: "בקרי מאווררים", en: "Fan Controllers" },
  aio: { he: "קירור נוזלי", en: "Liquid Coolers" },
  cooler_air: { he: "קירור אוויר", en: "Air Coolers" },
  cooling_other: { he: "קירור אחר", en: "Other Cooling" },
  cooler_accessory: { he: "אביזרי קירור", en: "Cooler Accessories" },
  thermal_paste: { he: "משחות תרמיות", en: "Thermal Paste" },
  thermal: { he: "משחות תרמיות", en: "Thermal" },
  rgb_lighting: { he: "תאורת RGB", en: "RGB Lighting" },
  rgb: { he: "תאורת RGB", en: "RGB" },
  accessories: { he: "אביזרים", en: "Accessories" },
  other: { he: "רכיבים אחרים", en: "Other Components" },
};

/** Vendors currently scraped (Plonter stays labelled for old history only). */
export const ACTIVE_VENDORS = ["tms", "yahav", "onepc", "ivory"] as const;

const VENDOR_LABELS: Record<string, string> = {
  tms: "TMS",
  onepc: "1PC",
  "1pc": "1PC",
  plonter: "Plonter",
  ivory: "Ivory",
  yahav: "YahavPC",
};

const ATTRIBUTE_LABELS: Record<string, { he: string; en: string }> = {
  wifi: { he: "Wi-Fi", en: "Wi-Fi" },
  brand: { he: "מותג", en: "Brand" },
  vendor: { he: "חנות", en: "Shop" },

  // Reference-spec keys: labels only, they never become filters.
  core_clock: { he: "תדר בסיס", en: "Base Clock" },
  boost_clock: { he: "תדר מוגבר", en: "Boost Clock" },
  tdp: { he: "צריכת חשמל (TDP)", en: "TDP" },
  graphics: { he: "גרפיקה משולבת", en: "Integrated Graphics" },
  length: { he: "אורך", en: "Length" },
  memory: { he: "זיכרון וידאו", en: "Video Memory" },
  external_volume: { he: "נפח חיצוני", en: "External Volume" },
  internal_35_bays: { he: "תאי 3.5 אינץ'", en: "3.5\" Bays" },
  noise_level: { he: "רמת רעש", en: "Noise Level" },
  airflow: { he: "ספיקת אוויר", en: "Airflow" },
  channels: { he: "ערוצים", en: "Channels" },
  amount: { he: "כמות", en: "Amount" },

  // Numeric filter attributes
  price: { he: "מחיר", en: "Price" },
  cores: { he: "ליבות", en: "Cores" },
  threads: { he: "נימים", en: "Threads" },
  vram_gb: { he: "זיכרון וידאו (GB)", en: "VRAM (GB)" },
  cooler_height_mm: { he: "גובה קירור (ממ)", en: "Cooler Height (mm)" },
  gpu_length_mm: { he: "אורך כרטיס מסך (ממ)", en: "GPU Length (mm)" },
  memory_clock_mhz: { he: "תדר זיכרון (MHz)", en: "Memory Clock (MHz)" },
  timings: { he: "תזמונים", en: "Timings" },

  // CPU generation / tier (extractors.py)
  tier: { he: "דרגה", en: "Tier" },
  // Legacy ivory aliases (kept just in case any survive normalization)
  cpu_generation: { he: "דור", en: "Generation" },
  cpu_tier: { he: "דרגה", en: "Tier" },

  // Labels so every attribute renders with a readable name instead of its raw key.
  capacity_label: { he: "נפח", en: "Capacity" },
  clearance_item: { he: "פריט מיקוח", en: "Clearance item" },
  external_volume_l: { he: "נפח חיצוני (ליטר)", en: "External Volume (L)" },
  revision: { he: "גרסה", en: "Revision" },
  slots: { he: "עובי חריצים", en: "Slot Width" },
  mpn: { he: "מק\"ט יצרן", en: "MPN" },
  upc: { he: "ברקוד (UPC)", en: "UPC" },
  bundle_only: { he: "נמכר כמארז", en: "Bundle only" },
  cooler_included: { he: "כולל קירור", en: "Cooler included" },

  // CPU core specs (detail-scraped canonical keys)
  l2_cache: { he: "מטמון L2", en: "L2 Cache" },
  l3_cache: { he: "מטמון L3", en: "L3 Cache" },
  codename: { he: "שם קוד", en: "Codename" },
  manufacturing_process: { he: "ליטוגרפיה", en: "Lithography" },
  launch: { he: "השקה", en: "Launch" },
  stepping: { he: "סטפינג", en: "Stepping" },
  memory_controller: { he: "בקר זיכרון", en: "Memory Controller" },
  memory_max: { he: "זיכרון מקסימלי", en: "Max Memory" },
  memory_bandwidth: { he: "רוחב פס זיכרון", en: "Memory Bandwidth" },
  memory_compatibility: { he: "תאימות זיכרון", en: "Memory Compatibility" },
  pcie_lanes: { he: "ערוצי PCIe", en: "PCIe Lanes" },
  chipset_suitability: { he: "ערכות שבבים תואמות", en: "Chipset Support" },
  chipset_interface: { he: "ממשק ערכת שבבים", en: "Chipset Interface" },
  scope_of_delivery: { he: "תכולת האריזה", en: "Box Contents" },
  max_temperature: { he: "טמפרטורה מקסימלית", en: "Max Temperature" },
  thermal_interface_material: { he: "משחה תרמית", en: "Thermal Interface" },
  cpu_features: { he: "תכונות CPU", en: "CPU Features" },
  cpu_compatibility: { he: "תאימות CPU", en: "CPU Compatibility" },
  clock: { he: "תדר שעון", en: "Clock" },
  base_clock: { he: "תדר בסיס", en: "Base Clock" },
  turbo_clock: { he: "תדר מוגבר", en: "Turbo Clock" },
  tdp_tgp: { he: "צריכת חשמל (W)", en: "TDP (W)" },

  // GPU
  gpu_chip: { he: "שבב", en: "GPU Chip" },
  gpu_vendor: { he: "יצרן שבב", en: "GPU Vendor" },
  cooling_type: { he: "סוג קירור", en: "Cooling Type" },
  hdmi_ports: { he: "יציאות HDMI", en: "HDMI Ports" },
  displayport_ports: { he: "יציאות DisplayPort", en: "DisplayPort Ports" },
  dvi_ports: { he: "יציאות DVI", en: "DVI Ports" },
  mini_displayport_ports: { he: "יציאות Mini DP", en: "Mini DisplayPort" },
  vga_ports: { he: "יציאות VGA", en: "VGA Ports" },
  total_slot_width: { he: "רוחב חריצים", en: "Slot Width" },
  gpu_features: { he: "תכונות", en: "GPU Features" },
  blade_design: { he: "עיצוב להבים", en: "Blade Design" },

  // PSU / power
  wattage: { he: "הספק (W)", en: "Wattage (W)" },
  pcie_connectors: { he: "מחברי PCIe", en: "PCIe Connectors" },
  pcie_8pin_connectors: { he: "מחברי 8-pin", en: "8-pin Connectors" },
  eps_connectors: { he: "מחברי EPS", en: "EPS Connectors" },
  pcie_16pin_connectors: { he: "מחברי 16-pin", en: "16-pin Connectors" },
  pcie_12vhpwr_connectors: { he: "מחברי 12VHPWR", en: "12VHPWR Connectors" },
  audio_connectors: { he: "מחברי שמע", en: "Audio Connectors" },
  cpu_power_connectors: { he: "מחברי חשמל CPU", en: "CPU Power Connectors" },

  // Storage
  capacity: { he: "נפח", en: "Capacity" },
  drive_type: { he: "סוג כונן", en: "Drive Type" },
  drive_form_factor: { he: "פורמט כונן", en: "Drive Form Factor" },
  drive_use_case: { he: "שימוש", en: "Use Case" },
  nvme_flag: { he: "NVMe", en: "NVMe" },
  cache: { he: "זיכרון מטמון", en: "Cache" },
  spindle_speed: { he: "מהירות ציר", en: "Spindle Speed" },

  // Memory
  kit: { he: "ערכת זיכרון", en: "Kit" },
  modules: { he: "מודולים", en: "Modules" },
  cas: { he: "CAS", en: "CAS" },
  voltage: { he: "מתח", en: "Voltage" },
  first_word_latency: { he: "השהיית מילה ראשונה", en: "First Word Latency" },
  ecc_registered: { he: "ECC", en: "ECC" },

  // Motherboard
  lan: { he: "רשת", en: "LAN" },
  lan_chip: { he: "שבב רשת", en: "LAN Chip" },
  wireless_std: { he: "תקן אלחוטי", en: "Wireless" },
  usb_a_ports: { he: "יציאות USB-A (אחוריות)", en: "USB-A Ports (rear)" },
  usb_c_ports: { he: "יציאות USB-C (אחוריות)", en: "USB-C Ports (rear)" },
  video_outputs: { he: "יציאות תצוגה", en: "Video Outputs" },
  rgb_headers: { he: "מחברי RGB", en: "RGB Headers" },
  pump_headers: { he: "מחברי משאבה", en: "Pump Headers" },
  usb_headers: { he: "מחברי USB פנימיים", en: "USB Headers" },
  cpu_support: { he: "מעבדים נתמכים", en: "CPU Support" },
  memory_speed_oc: { he: "מהירות זיכרון מקס' (OC)", en: "Max Memory Speed (OC)" },
  power_supply_position: { he: "מיקום ספק כוח", en: "PSU Position" },
  wifi_standard: { he: "תקן Wi-Fi", en: "Wi-Fi Standard" },
  overclock_support: { he: "תמיכת OC", en: "Overclock Support" },
  front_io: { he: "מחברים קדמיים", en: "Front I/O" },
  connectivity: { he: "קישוריות", en: "Connectivity" },
  display_outputs: { he: "יציאות תצוגה", en: "Display Outputs" },
  raid_level: { he: "RAID", en: "RAID" },
  buttons_switches: { he: "כפתורים", en: "Buttons" },

  // Case
  internal_25_bays: { he: "תאי 2.5 אינץ'", en: "2.5\" Bays" },
  maximum_video_card_length: { he: "אורך כרטיס מסך (ממ)", en: "Max Video Card Length" },
  supported_radiator_mm: { he: "רדיאטור נתמך (ממ)", en: "Radiator Support (mm)" },
  optical_drive_support: { he: "תמיכת כונן אופטי", en: "Optical Drive Support" },
  window: { he: "חלון", en: "Window" },

  // Fans / coolers
  argb: { he: "ARGB", en: "ARGB" },
  rgb: { he: "RGB", en: "RGB" },
  fans_per_pack: { he: "מאווררים לערכה", en: "Fans per Pack" },
  fan_features: { he: "תכונות מאוורר", en: "Fan Features" },
  cooler_display: { he: "תצוגה", en: "Display" },
  socket_compat: { he: "תאימות סוקט", en: "Socket Compat" },
  special_features: { he: "תכונות מיוחדות", en: "Special Features" },
  miscellaneous_interfaces: { he: "ממשקים נוספים", en: "Misc Interfaces" },
  power_consumption: { he: "צריכת חשמל", en: "Power Consumption" },
  power_supply: { he: "ספק כוח", en: "Power Supply" },
  total_height: { he: "גובה כולל", en: "Total Height" },
  modules_height: { he: "גובה מודולים", en: "Module Height" },
};

export function categoryLabel(id: string, lang: Lang): string {
  return CATEGORY_LABELS[id]?.[lang] ?? id;
}

export function vendorLabel(id: string): string {
  return VENDOR_LABELS[id] ?? id;
}

export function attributeLabel(key: string, lang: Lang, category?: string): string {
  // The category's own schema label first: SPEC_LABELS is flat, so a field
  // name shared across categories carries ONE category's wording ("type" read
  // "סוג כונן" - drive type - on PSU, case and cooler pages).
  const field = category ? SPEC_FIELDS[category]?.find((f) => f.name === key) : undefined;
  if (field) return field[lang];
  // Schema labels next (one entry per field, generated from
  // scraper/specs/schema.py); the hand list below still covers the
  // transitional derived/alias keys the filter rail reads from attributes.
  return SPEC_LABELS[key]?.[lang] ?? ATTRIBUTE_LABELS[key]?.[lang] ?? key;
}

const STRINGS = {
  he: {
    notListed: "לא מצוין",
    compareTitle: "השוואת מוצרים",
    compareAction: "השוואה",
    compareAdd: "הוספה להשוואה",
    compareRemove: "הסרה מההשוואה",
    compareTrayLabel: "המוצרים להשוואה",
    compareNow: "השוואה",
    compareNeedMore: "בחרו עוד מוצר",
    compareClear: "ניקוי",
    compareFull: "אפשר להשוות עד 4 מוצרים",
    compareSwitched: "ההשוואה התחילה מחדש: משווים מוצרים מקטגוריה אחת בלבד",
    compareEmpty: "לא נבחרו מוצרים להשוואה. סמנו “השוואה” בשורות המוצרים כדי להתחיל.",
    compareMissing: "חלק מהמוצרים לא נמצאו או שייכים לקטגוריה אחרת והוסרו מההשוואה.",
    compareOnlyDiffs: "הצגת הבדלים בלבד",
    compareDiffNote: "ערכים שונים מסומנים",
    compareSame: "כל הערכים המוצגים זהים.",
    compareSpecs: "מפרט",
    compareGeneral: "כללי",
    compareRemoveItem: "הסרה",
    savedNav: "שמורים",
    savedTitle: "מוצרים שמורים",
    savedAdd: "שמירה",
    savedRemove: "הסרה מהשמורים",
    savedEmpty: "לחצו על הלב בדף מוצר כדי לשמור אותו כאן.",
    savedHint: "השמורים נשמרים בדפדפן הזה בלבד ולא נשלחים לשום מקום.",
    savedBrowse: "לעיון בקטגוריות",
    signalLowest: "הנמוך ב-30 יום",
    signalTypicalTitle: "בהשוואה לחציון המחיר ב-30 הימים האחרונים",
    dropsTitle: "הירידות הגדולות במחיר",
    dropsSub: "לפי היסטוריית המחירים של 30 הימים האחרונים",
    metaCategoriesDesc: "כל קטגוריות רכיבי המחשב: מעבדים, כרטיסי מסך, לוחות אם, זיכרון ועוד. השוואת מחירים בין חנויות בישראל.",
    metaBuilderDesc: "בניית מחשב עם בדיקת תאימות אוטומטית והשוואת מחירים בין החנויות בישראל.",
    metaCompareDesc: "השוואה צד לצד של מפרט ומחירים בין רכיבי מחשב.",
    metaSavedDesc: "רכיבי המחשב ששמרתם, עם המחיר העדכני ביותר.",
    details: "פרטים",
    homeHeroTitle: "כל רכיבי המחשב. המחיר הכי טוב בישראל.",
    homeHeroSub: "אותו רכיב, ארבע חנויות, מחירים שונים. אנחנו מראים לכם את הזול ביותר.",
    homeSearchPlaceholder: "חפשו מעבד, כרטיס מסך, לוח אם…",
    homePopular: "פופולרי:",
    homeStatsVendors: "חנויות נסרקות",
    homeVendorsTitle: "המחירים נאספים מ",
    viewCards: "תצוגת כרטיסים",
    viewTable: "תצוגת טבלה",
    viewLabel: "תצוגת הרשימה",
    atVendor: "אצל",
    photoLabel: "תמונה",
    compatStripOk: "תאימות: לא נמצאו בעיות בין הרכיבים.",
    shareTitle: "שיתוף",
    exportTitle: "ייצוא",
    buildEmptySlot: "עוד לא נבחר",
    cheapest: "הזול ביותר",
    cancel: "ביטול",
    availability: "זמין",
    priceHeading: "מחיר",
    builderNav: "בניית מחשב",
    builderTitle: "בניית מחשב",
    totalLabel: "סה״כ:",
    compatibilityIdle: "בחרו רכיבים כדי לבדוק תאימות.",
    copyLink: "העתקת קישור",
    unknownList: "הקישור הזה לא נמצא. ייתכן שהוא שגוי או נמחק.",
    backToBuilder: "חזרה לבניית מחשב",
    addToBuild: "הוספה לבנייה",
    removePart: "הסרה",
    componentHeading: "רכיב",
    skuLabel: "מק״ט",
    appName: "מפרט",
    searchPlaceholder: "חיפוש לפי שם או מותג…",
    home: "דף הבית",
    backToCategories: "חזרה לקטגוריות",
    inStockOnly: "במלאי בלבד",
    sortLabel: "מיון",
    sortPriceAsc: "מחיר: מהזול ליקר",
    sortPriceDesc: "מחיר: מהיקר לזול",
    sortVendorsDesc: "הכי הרבה חנויות",
    sortName: "שם",
    sortNameDesc: "שם (יורד)",
    sortRelevance: "רלוונטיות",
    toggleSeries: "הצגה או הסתרה של קו המחיר של החנות",
    noResults: "לא נמצאו תוצאות",
    outOfStock: "אזל מהמלאי",
    inStock: "במלאי",
    staleData: "מחיר לא עודכן היום",
    close: "סגירה",
    filtersHeading: "סינון",
    filtersShowResults: "הצגת תוצאות",
    upTo: "עד",
    clearFilters: "איפוס סינון",
    currencyToggle: "₪",
    langToggle: "EN",
    yesLabel: "כן",
    noLabel: "לא",
    merchantsTitle: "חנויות",
    partsShort: "חלקים",
    totalShort: "סה״כ",
    wattageShort: "צריכה משוערת",
    compatFilterLabel: "רק מוצרים שתואמים לבנייה",
    compatFilterHint: "מסתיר אפשרויות שמתנגשות עם החלקים שכבר בחרת",
    linkCopied: "הקישור הועתק!",
    markupTableCopied: "הטבלה הועתקה!",
    markupTextCopied: "הטקסט הועתק!",
    shorteningLabel: "מקצר…",
    tableLabel: "טבלה",
    textLabel: "טקסט",
    markdownItem: "פריט",
    addAdditionalLabel: "הוספת",
    compatNoteTitle: "הערת תאימות:",
    compatNoteBody: "בדיקת התאימות מבוססת על נתונים ידועים בלבד. אישורים פיזיים כמו מרווח לקירור לא נבדקים אוטומטית.",
    sharedBuildTitle: "רשימת חלקים",
    builderPageTitle: "בניית מחשב",
    allCategoriesTitle: "כל הקטגוריות",
    productPageTitle: "מוצר",
    backToHome: "חזרה לדף הבית",
    categoriesEyebrow: "קטלוג רכיבי מחשב",
    categoriesIntro: "בחרו קטגוריה כדי להשוות מחירים, מפרטים וזמינות.",
    browseAllCategories: "עיון בכל הקטגוריות",
    homeEyebrow: "השוואת מחירים לרכיבי מחשב בישראל",
    homeBrowseCta: "לכל הקטגוריות",
    homeStatsParts: "מוצרים בקטלוג",
    homeTileProducts: "מוצרים",
    homeStatsCats: "קטגוריות פעילות",
    homeStatsRefresh: "רענון מחירים יומי",
    homeStatsDaily: "כל יום",
    homeHowTitle: "איך זה עובד",
    homeCatsTitle: "קטגוריות",
    homeStep1Title: "בוחרים חלקים",
    homeStep1Body: "מסננים לפי חנות, מחיר ומפרט, ומוסיפים כל חלק לבנייה.",
    homeStep2Title: "בודקים תאימות וסכום",
    homeStep2Body: "הכלי מסכם את המחיר, מעריך צריכה ובודק התאמה בין החלקים.",
    homeStep3Title: "משתפים ושומרים",
    homeStep3Body: "מקבלים קישור קצר לבנייה ושולחים לחבר או שומרים להמשך.",
    hiddenIncompatible: "לא תואמים הוסתרו",
    sortAriaLabel: "מיון תוצאות",
    searchAriaLabel: "חיפוש בקטגוריה",
    priceMinAria: "מחיר מינימום",
    priceMaxAria: "מחיר מקסימום",
    shareLinkAria: "קישור לשיתוף הבנייה",
    buyHeaderLabel: "קנייה",
    quickAddStatus: "נוסף לבנייה",
    homePageTitle: "השוואת מחירי רכיבי מחשב",
    pickMismatch: "לא ניתן להוסיף לחריץ זה",
    navMain: "ניווט ראשי",
    metaDescription: "השוואת מחירים בין TMS, ‏1PC, Ivory ויהב מחשבים לרכיבי מחשב בישראל.",
    themeDark: "מצב כהה",
    themeLight: "מצב בהיר",
    startBuild: "התחילו לבנות",
    loading: "טוען…",
    loadError: "שגיאה בטעינת הנתונים. נסו לרענן את הדף.",
    sourceLinkLabel: "קוד המקור בגיטהאב",
    min: "מינימום",
    max: "מקסימום",
    priceRange: "טווח מחירים",
    pricesHeading: "מחירים",
    merchantHeading: "חנות",
    baseHeading: "בסיס",
    shippingHeading: "משלוח",
    totalHeading: "סה״כ",
    buyLabel: "קנייה",
    specsHeading: "מפרט",
    qaKindSpec: "סתירת מפרט",
    qaSpecKept: "נשמר",
    qaSpecDropped: "נפסל",
    similarHeading: "מוצרים דומים",
    variantsHeading: "דגמים קרובים",
    addToPartList: "הוספה לבנייה",
    productNotFound: "המוצר לא נמצא",
    freeShipping: "משלוח חינם",
    productsMenu: "מוצרים",
    searchLabel: "חיפוש מוצרים…",
    coolingHeading: "קירור ומאווררים",
    accessoriesHeading: "אביזרים",
    copyMarkdown: "העתקה כטבלה",
    copyText: "העתקה כטקסט",
    startNew: "בנייה חדשה",
    showMore: "הצג עוד",
    showLess: "הצג פחות",
    quickAdd: "הוספה",
    addedLabel: "נוסף",
    compatLocked: "נעול על ידי מסנן התאימות",
    priceHistory: "היסטוריית מחירים",
    historyAll: "הכל",
    historyDays: "ימים",
    retry: "נסה שוב",
    privacyTitle: "פרטיות",
    termsTitle: "תנאי שימוש",
    cookiesTitle: "מדיניות עוגיות",
    disclaimer:
      "המחירים נאספים אוטומטית מדי יום מאתרי הספקים. הקישורים מובילים לאתר הספק לרכישה - מפרט אינו מוכר דבר בעצמו.",
    qaTitle: "בקרת איכות",
    qaEmpty: "אין רישומים כפולים בבדיקה כרגע.",
    qaHeading: "רישומים כפולים בבדיקה",
    qaKindDuplicate: "רישום כפול",
    qaKindNaming: "סתירת שמות",
    qaKindCore: "חסרי מפרט ליבה",
    qaMissingFields: "שדות חסרים",
    footerDesc: "השוואת מחירים ובנייה של מחשבים בישראל — נתונים נאספים אוטומטית מאתרי הספקים.",
    footerProductsHead: "מוצרים",
    footerBuildHead: "בנייה",
    footerLegalHead: "משפטי",
    megaMainHead: "קטגוריות עיקריות",
    megaCooling: "קירור מעבד",
    megaCoolingSub: "אוויר ונוזלי",
    megaMoreHead: "עוד קטגוריות",
    megaClose: "סגירת תפריט המוצרים",
    dropsNav: "ירידות מחיר",
    skipToContent: "דילוג לתוכן",
    homeCrumb: "דף הבית",
    breadcrumbs: "פירורי לחם",
    sectionsNav: "חלקי העמוד",
    allPrices: "לכל המחירים",
    dropsHomeSub: "ב-30 הימים האחרונים: המחיר היום מול המחיר הרגיל בתקופה",
    allDrops: "לכל הירידות",
    dropsPageSub: "המוצרים שהמחיר שלהם ירד הכי הרבה, לפי היסטוריית המחירים היומית מכל החנויות",
    periodLabel: "תקופה",
    days7: "7 ימים",
    days30: "30 ימים",
    filterByCategory: "סינון לפי קטגוריה",
    allLabel: "הכל",
    dropsSortPct: "הירידה הגדולה באחוזים",
    dropsSortAmount: "הירידה הגדולה בשקלים",
    dropsEmpty: "לא נמצאו ירידות מחיר בתקופה הזו.",
    homeHeroLine1: "מחשב חדש.",
    homeHeroLine2: "בלי לשלם יותר מדי.",
    searchButton: "חיפוש",
    prevLabel: "הקודם",
    nextLabel: "הבא",
    sampleBuildTitle: "בנייה לדוגמה",
    sampleBuildSub: "נבנתה אוטומטית ממחירי היום, רכיבים תואמים",
    yourBuildTitle: "הבנייה שלך",
    yourBuildSub: "במחירים של היום",
    andMoreParts: "ועוד {n} רכיבים",
    openBuild: "פתיחת הבנייה",
    fromStores: "מ-{n} חנויות",
    tabOverview: "סקירה",
    tabSpecs: "מפרט מלא",
    tabHistory: "היסטוריית מחירים",
    toStore: "לחנות",
    lastUpdated: "עדכון אחרון",
    todayLabel: "היום",
    historyLow: "הנמוך",
    historyHigh: "הגבוה",
    historyChange7: "שינוי ב-7 ימים",
    noChange: "ללא שינוי",
    fromPrice: "מ-",
    toBuild: "לבנייה",
    searchInCategory: "חיפוש ב{c}",
    pricesFrom: "מחירים מ-",
    resetLabel: "איפוס",
    pickHeroSub: "מוצגים רק חלקים שמתאימים לרכיבים שכבר בחרת",
    pagesLabel: "עמודים",
    nameHeading: "שם",
    storesHeading: "חנויות",
    prevPage: "העמוד הקודם",
    nextPage: "העמוד הבא",
    builderSub: "בחרו רכיב לכל שורה. נבדוק תאימות ונמצא את המחיר הזול ביותר לכל חלק.",
    splitTitle: "חלוקה לפי חנות",
    splitEmpty: "בחרו רכיבים כדי לראות איפה הם הכי זולים.",
    splitNote: "כל רכיב נספר בחנות שבה הוא הכי זול כרגע.",
    compatChecksTitle: "בדיקות תאימות",
    compatChecksEmpty: "בחרו לפחות שני רכיבים שקשורים זה לזה (למשל מעבד ולוח אם) כדי להריץ בדיקות.",
    buildSaved: "נשמרה",
    saveBuild: "שמירה",
    selectionHeading: "בחירה",
    storeHeading: "חנות",
    buildEmptyNote: "עוד לא נבחרו רכיבים",
    detailsLink: "פרטים",
    wattageEstimate: "צריכה משוערת",
    compareHeroSub: "השוואה צד לצד של המפרט והמחירים. הערך הטוב ביותר בכל שורה מסומן בירוק.",
    compareAddProduct: "הוספת מוצר",
    compareUpTo: "עד 4 מוצרים",
    priceRangeLabel: "טווח מחירים",
    productLabel: "מוצר",
    compareBestLegend: "הערך הטוב ביותר",
    copyCompareLink: "העתקת קישור להשוואה",
    savedHeroSub: "המוצרים ורשימות החלקים ששמרת, עם המחירים המעודכנים מכל החנויות.",
    savedFilter: "סינון שמורים",
    savedProducts: "מוצרים",
    savedBuilds: "רשימות חלקים",
    savedProductsSub: "המחיר הזול ביותר כרגע מכל החנויות",
    savedBuildsSub: "הבניות ששמרת מדף בניית המחשב, עם המחיר המעודכן של כל רכיב",
    savedEmptyTitle: "אין מוצרים שמורים",
    savedBuildsEmptyTitle: "אין רשימות חלקים שמורות",
    savedBuildsEmpty: "בדף בניית המחשב לחצו על \"שמירה\" כדי לשמור את הרשימה במכשיר הזה.",
    compareSaved: "השוואת המוצרים השמורים",
    localOnlyTitle: "נשמר רק במכשיר הזה.",
    localOnlyBody: "אין צורך בחשבון: השמורים נשמרים בדפדפן שלך. ניקוי נתוני הדפדפן או מעבר למכשיר אחר לא יציגו אותם.",
    savedGone: "לא נמצא בקטלוג היום",
    untitledBuild: "בנייה ללא שם",
    withLabel: "עם",
    renameBuild: "שינוי שם הרשימה",
    deleteBuild: "מחיקת הרשימה",
    duplicateBuild: "שכפול",
    copyLabel: "עותק",
    allCompatible: "כל הרכיבים תואמים",
    hasConflicts: "יש התנגשויות",
    hasWarnings: "יש הערות תאימות",
  },
  en: {
    notListed: "Not listed",
    compareTitle: "Compare parts",
    compareAction: "Compare",
    compareAdd: "Add to compare",
    compareRemove: "Remove from compare",
    compareTrayLabel: "Parts to compare",
    compareNow: "Compare",
    compareNeedMore: "Pick one more part",
    compareClear: "Clear",
    compareFull: "You can compare up to 4 parts",
    compareSwitched: "Compare list restarted: one category at a time",
    compareEmpty: "No parts to compare yet. Tick “Compare” on product rows to start.",
    compareMissing: "Some parts were not found or belong to another category and were left out.",
    compareOnlyDiffs: "Show differences only",
    compareDiffNote: "Differing values are highlighted",
    compareSame: "All the values shown are identical.",
    compareSpecs: "Specifications",
    compareGeneral: "Overview",
    compareRemoveItem: "Remove",
    savedNav: "Saved",
    savedTitle: "Saved parts",
    savedAdd: "Save",
    savedRemove: "Remove from saved",
    savedEmpty: "Tap the heart on any part to keep it here.",
    savedHint: "Saved parts live in this browser only and are never sent anywhere.",
    savedBrowse: "Browse categories",
    signalLowest: "Lowest in 30 days",
    signalTypicalTitle: "Compared with the median price over the last 30 days",
    dropsTitle: "Biggest price drops",
    dropsSub: "Based on the last 30 days of recorded prices",
    metaCategoriesDesc: "Every PC part category: processors, graphics cards, motherboards, memory and more. Price comparison across Israeli stores.",
    metaBuilderDesc: "Build a PC with automatic compatibility checks and price comparison across Israeli stores.",
    metaCompareDesc: "Side-by-side specs and prices for PC parts.",
    metaSavedDesc: "The PC parts you saved, with their latest prices.",
    details: "Details",
    homeHeroTitle: "Every PC part. The best price in Israel.",
    homeHeroSub: "Same part, four stores, different prices. We show you the cheapest.",
    homeSearchPlaceholder: "Search a CPU, graphics card, motherboard…",
    homePopular: "Popular:",
    homeStatsVendors: "Shops tracked",
    homeVendorsTitle: "Prices collected from",
    viewCards: "Card view",
    viewTable: "Table view",
    viewLabel: "List layout",
    atVendor: "at",
    photoLabel: "Photo",
    compatStripOk: "Compatibility: no issues found between the parts.",
    shareTitle: "Share",
    exportTitle: "Export",
    buildEmptySlot: "Nothing chosen yet",
    cheapest: "Cheapest",
    cancel: "Cancel",
    availability: "Availability",
    priceHeading: "Price",
    builderNav: "Builder",
    builderTitle: "Build a PC",
    totalLabel: "Total:",
    compatibilityIdle: "Pick parts to check compatibility.",
    copyLink: "Copy link",
    unknownList: "This list link wasn't found. It may be mistyped or deleted.",
    backToBuilder: "Back to builder",
    addToBuild: "Add to build",
    removePart: "Remove",
    componentHeading: "Component",
    skuLabel: "SKU",
    appName: "Mifrat",
    searchPlaceholder: "Search by name or brand…",
    home: "Home",
    backToCategories: "Back to categories",
    inStockOnly: "In stock only",
    sortLabel: "Sort",
    sortPriceAsc: "Price: low to high",
    sortPriceDesc: "Price: high to low",
    sortVendorsDesc: "Most vendors",
    sortName: "Name",
    sortNameDesc: "Name (Z–A)",
    sortRelevance: "Relevance",
    toggleSeries: "Show or hide this vendor's price line",
    noResults: "No results found",
    outOfStock: "Out of stock",
    inStock: "In stock",
    staleData: "Price not refreshed today",
    close: "Close",
    filtersHeading: "Filters",
    filtersShowResults: "Show results",
    upTo: "Up to",
    clearFilters: "Clear filters",
    currencyToggle: "$",
    langToggle: "עברית",
    yesLabel: "Yes",
    noLabel: "No",
    merchantsTitle: "Merchants",
    partsShort: "Parts",
    totalShort: "Total",
    wattageShort: "Est. wattage",
    compatFilterLabel: "Only parts that fit my build",
    compatFilterHint: "Hides options that conflict with the parts you picked",
    linkCopied: "Link copied!",
    markupTableCopied: "Table copied!",
    markupTextCopied: "Text copied!",
    shorteningLabel: "Shortening…",
    tableLabel: "Table",
    textLabel: "Text",
    markdownItem: "Item",
    addAdditionalLabel: "Add Additional",
    compatNoteTitle: "Compatibility note:",
    compatNoteBody: "Some physical constraints (RAM clearance, cooler height, GPU length) are not automatically checked. Verify case fit manually.",
    sharedBuildTitle: "Shared Build",
    builderPageTitle: "PC Builder",
    allCategoriesTitle: "All categories",
    productPageTitle: "Product",
    backToHome: "Back to home",
    categoriesEyebrow: "PC component catalog",
    categoriesIntro: "Choose a category to compare prices, specifications, and availability.",
    browseAllCategories: "Browse all categories",
    homeEyebrow: "Price comparison for PC parts in Israel",
    homeBrowseCta: "All categories",
    homeStatsParts: "Products in the catalog",
    homeTileProducts: "Products",
    homeStatsCats: "Active categories",
    homeStatsRefresh: "Prices refreshed daily",
    homeStatsDaily: "Daily",
    homeHowTitle: "How it works",
    homeCatsTitle: "Categories",
    homeStep1Title: "Pick your parts",
    homeStep1Body: "Filter by shop, price and specs, then add each part to your build.",
    homeStep2Title: "Check fit and total",
    homeStep2Body: "The builder totals the price, estimates power draw and flags mismatches.",
    homeStep3Title: "Share and keep",
    homeStep3Body: "Every build gets a short permanent link you can send to anyone.",
    hiddenIncompatible: "known-incompatible hidden",
    sortAriaLabel: "Sort results",
    searchAriaLabel: "Search in category",
    priceMinAria: "Minimum price",
    priceMaxAria: "Maximum price",
    shareLinkAria: "Share link for this build",
    buyHeaderLabel: "Buy",
    quickAddStatus: "Added to build",
    homePageTitle: "Compare PC Part Prices in Israel",
    pickMismatch: "Cannot add to this slot",
    navMain: "Main navigation",
    metaDescription: "Compare prices for PC parts from TMS, 1PC, Ivory and YahavPC in Israel.",
    themeDark: "Dark mode",
    themeLight: "Light mode",
    startBuild: "Start Your Build",
    loading: "Loading…",
    loadError: "Couldn't load data. Try refreshing the page.",
    sourceLinkLabel: "Source on GitHub",
    min: "Min",
    max: "Max",
    priceRange: "Price Range",
    pricesHeading: "Prices",
    merchantHeading: "Merchant",
    baseHeading: "Base",
    shippingHeading: "Shipping",
    totalHeading: "Total",
    buyLabel: "Buy",
    specsHeading: "Specifications",
    qaKindSpec: "Spec conflict",
    qaSpecKept: "Kept",
    qaSpecDropped: "Dropped",
    similarHeading: "Similar products",
    variantsHeading: "Close variants",
    addToPartList: "Add to build",
    productNotFound: "Product not found",
    freeShipping: "FREE shipping",
    productsMenu: "Products",
    searchLabel: "Search products…",
    coolingHeading: "Cooling & Fans",
    accessoriesHeading: "Accessories",
    copyMarkdown: "Copy as table",
    copyText: "Copy as text",
    startNew: "New build",
    showMore: "Show more",
    showLess: "Show less",
    quickAdd: "Add",
    addedLabel: "Added",
    compatLocked: "Locked by Compatibility Filter",
    priceHistory: "Price History",
    historyAll: "All",
    historyDays: "days",
    retry: "Retry",
    privacyTitle: "Privacy",
    termsTitle: "Terms of Use",
    cookiesTitle: "Cookie Policy",
    disclaimer:
      "Prices are scraped daily from each vendor's site. Links go to the vendor to buy. Mifrat doesn't sell anything itself.",
    qaTitle: "Quality Review",
    qaEmpty: "No duplicate listings under review right now.",
    qaHeading: "Duplicate listings under review",
    qaKindDuplicate: "Duplicate listing",
    qaKindNaming: "Naming conflict",
    qaKindCore: "Missing core specs",
    qaMissingFields: "Missing fields",
    footerDesc: "Price comparison and PC building for Israel — data scraped automatically from vendor sites.",
    footerProductsHead: "Products",
    footerBuildHead: "Build",
    footerLegalHead: "Legal",
    megaMainHead: "Main categories",
    megaCooling: "CPU cooling",
    megaCoolingSub: "Air and liquid",
    megaMoreHead: "More categories",
    megaClose: "Close the products menu",
    dropsNav: "Price drops",
    skipToContent: "Skip to content",
    homeCrumb: "Home",
    breadcrumbs: "Breadcrumbs",
    sectionsNav: "Page sections",
    allPrices: "See all prices",
    dropsHomeSub: "Last 30 days: today's price against the usual price over the period",
    allDrops: "All price drops",
    dropsPageSub: "The parts whose price fell the most, from the daily price history of every store",
    periodLabel: "Period",
    days7: "7 days",
    days30: "30 days",
    filterByCategory: "Filter by category",
    allLabel: "All",
    dropsSortPct: "Biggest drop (%)",
    dropsSortAmount: "Biggest drop (amount)",
    dropsEmpty: "No price drops recorded in this period.",
    homeHeroLine1: "A new PC.",
    homeHeroLine2: "Without overpaying.",
    searchButton: "Search",
    prevLabel: "Previous",
    nextLabel: "Next",
    sampleBuildTitle: "Sample build",
    sampleBuildSub: "Assembled from today's prices, compatible parts",
    yourBuildTitle: "Your build",
    yourBuildSub: "At today's prices",
    andMoreParts: "and {n} more parts",
    openBuild: "Open the build",
    fromStores: "from {n} stores",
    tabOverview: "Overview",
    tabSpecs: "Full specs",
    tabHistory: "Price history",
    toStore: "To store",
    lastUpdated: "Last updated",
    todayLabel: "today",
    historyLow: "Lowest",
    historyHigh: "Highest",
    historyChange7: "7-day change",
    noChange: "No change",
    fromPrice: "from ",
    toBuild: "To build",
    searchInCategory: "Search {c}",
    pricesFrom: "prices from ",
    resetLabel: "Reset",
    pickHeroSub: "Only parts that fit the components you already picked are shown",
    pagesLabel: "Pages",
    nameHeading: "Name",
    storesHeading: "Stores",
    prevPage: "Previous page",
    nextPage: "Next page",
    builderSub: "Pick a part for each row. We check compatibility and find the cheapest price for every part.",
    splitTitle: "Split by store",
    splitEmpty: "Pick parts to see where each is cheapest.",
    splitNote: "Each part counts at the store where it is cheapest right now.",
    compatChecksTitle: "Compatibility checks",
    compatChecksEmpty: "Pick at least two related parts (say a CPU and a motherboard) to run checks.",
    buildSaved: "Saved",
    saveBuild: "Save",
    selectionHeading: "Selection",
    storeHeading: "Store",
    buildEmptyNote: "No parts picked yet",
    detailsLink: "Details",
    wattageEstimate: "Estimated draw",
    compareHeroSub: "Specs and prices side by side. The best value in each row is marked green.",
    compareAddProduct: "Add a part",
    compareUpTo: "Up to 4 parts",
    priceRangeLabel: "Price range",
    productLabel: "Part",
    compareBestLegend: "Best value",
    copyCompareLink: "Copy compare link",
    savedHeroSub: "The parts and parts lists you saved, with today's prices from every store.",
    savedFilter: "Filter saved items",
    savedProducts: "Parts",
    savedBuilds: "Parts lists",
    savedProductsSub: "The cheapest price right now across all stores",
    savedBuildsSub: "Builds you saved from the builder, with each part's current price",
    savedEmptyTitle: "No saved parts",
    savedBuildsEmptyTitle: "No saved parts lists",
    savedBuildsEmpty: "In the builder, press \"Save\" to keep the list on this device.",
    compareSaved: "Compare saved parts",
    localOnlyTitle: "Saved on this device only.",
    localOnlyBody: "No account needed: saved items live in your browser. Clearing browser data or switching devices will not show them.",
    savedGone: "Not in today's catalog",
    untitledBuild: "Untitled build",
    withLabel: "with",
    renameBuild: "Rename the list",
    deleteBuild: "Delete the list",
    duplicateBuild: "Duplicate",
    copyLabel: "copy",
    allCompatible: "All parts compatible",
    hasConflicts: "Has conflicts",
    hasWarnings: "Has compatibility notes",
  },
} satisfies Record<Lang, Record<string, string>>;

type StringKey = keyof (typeof STRINGS)["he"];

export function t(lang: Lang, key: StringKey): string {
  return STRINGS[lang][key];
}

export function resultsCount(lang: Lang, n: number): string {
  return lang === "he" ? `${n} תוצאות` : `${n} results`;
}

export function compareCount(lang: Lang, n: number, max: number): string {
  return lang === "he" ? `${n} מתוך ${max}` : `${n} of ${max}`;
}

export function signalDown(lang: Lang, pct: number): string {
  return lang === "he" ? `ירידה של ${pct}%` : `Down ${pct}%`;
}

/** Meta description for a category page. */
export function categoryMetaDesc(lang: Lang, label: string, count: number): string {
  const n = count.toLocaleString(lang === "he" ? "he-IL" : "en-US");
  return lang === "he"
    ? `השוואת מחירים ל${label} בחנויות בישראל: ${n} מוצרים, עם סינון לפי מפרט.`
    : `Compare ${label.toLowerCase()} prices across Israeli stores: ${n} products with spec filters.`;
}

/** Meta description for a product page. */
export function productMetaDesc(lang: Lang, name: string, vendors: number, price: string | null): string {
  if (lang === "he") {
    return price
      ? `${name} — החל מ-${price}, ${vendorsCount(lang, vendors)}. מפרט והיסטוריית מחירים.`
      : `${name} — מפרט והשוואת חנויות.`;
  }
  return price
    ? `${name} — from ${price}, ${vendorsCount(lang, vendors)}. Specs and price history.`
    : `${name} — specs and store comparison.`;
}

export function vendorsCount(lang: Lang, n: number): string {
  if (lang === "he") return n === 1 ? "חנות אחת" : `${n} חנויות`;
  return n === 1 ? "1 vendor" : `${n} vendors`;
}

/** Spec-sheet group heading (the schema's own `group` ids). */
export function specGroupLabel(group: string, lang: Lang): string {
  const labels: Record<string, { he: string; en: string }> = {
    identity: { he: "זיהוי", en: "Identity" },
    core: { he: "ליבה", en: "Core" },
    memory: { he: "זיכרון", en: "Memory" },
    storage: { he: "אחסון", en: "Storage" },
    power: { he: "הספק", en: "Power" },
    physical: { he: "פיזי", en: "Physical" },
    io: { he: "חיבורים", en: "Connectivity" },
    other: { he: "נוסף", en: "Other" },
  };
  return labels[group]?.[lang] ?? group;
}

/** "2 problems · 1 warning" for the builder's compatibility strip. */
export function issuesSummary(lang: Lang, errors: number, warnings: number): string {
  const parts: string[] = [];
  if (lang === "he") {
    if (errors > 0) parts.push(errors === 1 ? "בעיית תאימות אחת" : `${errors} בעיות תאימות`);
    if (warnings > 0) parts.push(warnings === 1 ? "אזהרה אחת" : `${warnings} אזהרות`);
  } else {
    if (errors > 0) parts.push(errors === 1 ? "1 problem" : `${errors} problems`);
    if (warnings > 0) parts.push(warnings === 1 ? "1 warning" : `${warnings} warnings`);
  }
  return parts.join(" · ");
}

/** "of 750W" next to the wattage meter. */
export function wattOf(lang: Lang, capacity: number): string {
  return lang === "he" ? `מתוך ${capacity}W` : `of ${capacity}W`;
}

type CompatParams = CompatIssue["params"];

const COMPAT_MESSAGES: Record<CompatCode, Record<Lang, (p: CompatParams) => string>> = {
  socket: {
    he: (p) => `סוקט המעבד (${p.cpu}) אינו תואם ללוח האם (${p.board})`,
    en: (p) => `CPU socket (${p.cpu}) does not match motherboard socket (${p.board})`,
  },
  memoryType: {
    he: (p) => `סוג הזיכרון (${p.memory}) אינו תואם ללוח האם (${p.board})`,
    en: (p) => `Memory type (${p.memory}) does not match motherboard memory type (${p.board})`,
  },
  memoryMax: {
    he: () => "נפח הזיכרון חורג מהמקסימום של לוח האם",
    en: () => "Memory kit exceeds the motherboard maximum capacity",
  },
  memorySpeed: {
    he: (p) => `מהירות הזיכרון (${p.speed}MHz) גבוהה ממה שלוח האם מצהיר עליו`,
    en: (p) => `Memory speed (${p.speed}MHz) is above what the motherboard lists`,
  },
  gpuLength: {
    he: () => "כרטיס המסך ארוך מדי למארז הנבחר",
    en: () => "Graphics card is longer than the selected case supports",
  },
  boardForm: {
    he: (p) => `לוח האם (${p.form}) אינו נכנס למארז`,
    en: (p) => `Motherboard (${p.form}) does not fit the case`,
  },
  coolerHeight: {
    he: (p) => `גובה הקירור (${p.height}mm) עולה על המרווח במארז (${p.max}mm)`,
    en: (p) => `Cooler height (${p.height}mm) exceeds the case clearance (${p.max}mm)`,
  },
  radiator: {
    he: (p) => `המארז לא מצהיר על תמיכה ברדיאטור ${p.size}mm`,
    en: (p) => `The case does not list support for a ${p.size}mm radiator`,
  },
  coolerSocket: {
    he: (p) => `הקירור עשוי שלא להתאים לסוקט המעבד (${p.cpu})`,
    en: (p) => `Cooler may not support CPU socket (${p.cpu})`,
  },
  psuLow: {
    he: (p) => `הספק (${p.capacity}W) חלש מהצריכה הידועה (${p.watts}W)`,
    en: (p) => `PSU (${p.capacity}W) is below known system wattage (${p.watts}W)`,
  },
  psuHeadroom: {
    he: (p) => `מרווח הספק קטן: ${p.capacity}W מול צריכה ידועה ${p.watts}W`,
    en: (p) => `Little wattage headroom: ${p.capacity}W against a known ${p.watts}W draw`,
  },
  psuGpu: {
    he: (p) => `כרטיס המסך ממליץ על ספק ${p.recommended}W לפחות (נבחר ${p.capacity}W)`,
    en: (p) => `The card recommends at least ${p.recommended}W (selected ${p.capacity}W)`,
  },
};

export function compatMessage(lang: Lang, issue: CompatIssue): string {
  return COMPAT_MESSAGES[issue.code][lang](issue.params);
}

export function storesCount(lang: Lang, n: number): string {
  return lang === "he" ? `${n} חנויות` : `${n} stores`;
}

/** "Prices updated today at 06:51" (local time), or a date when older. */
export function updatedText(lang: Lang, iso: string): string | null {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return null;
  const locale = lang === "he" ? "he-IL" : "en-GB";
  const time = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(when);
  const dayKey = (d: Date): string => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(when) === dayKey(now)) return lang === "he" ? `המחירים עודכנו היום ב-${time}` : `Prices updated today at ${time}`;
  if (dayKey(when) === dayKey(yesterday)) return lang === "he" ? `המחירים עודכנו אתמול ב-${time}` : `Prices updated yesterday at ${time}`;
  const date = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(when);
  return lang === "he" ? `המחירים עודכנו ב-${date}` : `Prices updated ${date}`;
}

export function homeCatsSub(lang: Lang, cats: number, parts: string): string {
  return lang === "he"
    ? `${cats} קטגוריות, ${parts} מוצרים מ-${ACTIVE_VENDORS.length} חנויות`
    : `${cats} categories, ${parts} parts from ${ACTIVE_VENDORS.length} stores`;
}

export function dropsCount(lang: Lang, n: number, days: number): string {
  return lang === "he" ? `${n} מוצרים ירדו במחיר ב-${days} הימים האחרונים` : `${n} parts dropped in price over the last ${days} days`;
}

export function savingText(lang: Lang, amount: string): string {
  return lang === "he" ? `חוסכים ${amount}` : `Save ${amount}`;
}

/** When a store last listed the price: today / yesterday / N days ago. */
export function lastSeenText(lang: Lang, isoDay: string): string {
  const seen = Date.parse(`${isoDay.slice(0, 10)}T00:00:00`);
  if (!Number.isFinite(seen)) return isoDay;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((today.getTime() - seen) / 86_400_000);
  if (days <= 0) return lang === "he" ? "היום" : "Today";
  if (days === 1) return lang === "he" ? "אתמול" : "Yesterday";
  return lang === "he" ? `לפני ${days} ימים` : `${days} days ago`;
}

export function inStockCount(lang: Lang, n: string): string {
  return lang === "he" ? `${n} במלאי` : `${n} in stock`;
}

export function showingText(lang: Lang, from: string, to: string, total: string): string {
  return lang === "he" ? `מציג ${from}–${to} מתוך ${total}` : `Showing ${from}–${to} of ${total}`;
}

export function partsCount(lang: Lang, n: number): string {
  if (lang === "he") return n === 1 ? "רכיב אחד" : `${n} רכיבים`;
  return n === 1 ? "1 part" : `${n} parts`;
}

/** Builder table foot: "8 parts · cheapest price per part, from 3 stores". */
export function buildFootNote(lang: Lang, parts: number, stores: number): string {
  return lang === "he"
    ? `${partsCount(lang, parts)} · המחיר הזול ביותר לכל רכיב, מ-${stores === 1 ? "חנות אחת" : `${stores} חנויות`}`
    : `${partsCount(lang, parts)} · cheapest price per part, from ${stores === 1 ? "1 store" : `${stores} stores`}`;
}

type OkCheck = "socket" | "memoryType" | "memorySpeed" | "coolerSocket" | "boardForm" | "gpuLength" | "coolerFit" | "psu" | "psuGpu";

/** A compatibility check that passed, with the value it matched on when the specs carry it. */
export function compatOkMessage(
  lang: Lang,
  check: OkCheck,
  parts: Record<string, { specs?: Record<string, unknown> }>,
  watts: number
): string {
  const spec = (slot: string, field: string): string => {
    const value = parts[slot]?.specs?.[field];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  };
  const detail = (value: string): string => (value ? ` (${value})` : "");
  const he = lang === "he";
  switch (check) {
    case "socket":
      return (he ? "שקע המעבד תואם ללוח האם" : "CPU socket matches the motherboard") + detail(spec("motherboard", "socket") || spec("cpu", "socket"));
    case "memoryType":
      return (he ? "סוג הזיכרון ונפחו מתאימים ללוח האם" : "Memory type and capacity suit the motherboard") + detail(spec("motherboard", "memory_type") || spec("memory", "memory_type"));
    case "memorySpeed":
      return (he ? "מהירות הזיכרון בטווח שהלוח מצהיר עליו" : "Memory speed is within what the board lists") + detail(spec("memory", "speed_mhz") ? `${spec("memory", "speed_mhz")}MHz` : "");
    case "coolerSocket":
      return he ? "הקירור תומך בשקע המעבד" : "The cooler supports the CPU socket";
    case "boardForm":
      return (he ? "לוח האם נכנס למארז" : "The motherboard fits the case") + detail(spec("motherboard", "form_factor"));
    case "gpuLength":
      return he ? "כרטיס המסך נכנס לאורך המארז" : "The graphics card fits the case length";
    case "coolerFit":
      return he ? "הקירור נכנס למארז" : "The cooler fits the case";
    case "psu": {
      const cap = spec("psu", "wattage_w");
      return (he ? "ספק הכוח מספיק" : "The power supply is sufficient") + detail(cap ? (he ? `${cap}W מול ${watts}W משוערים` : `${cap}W against ~${watts}W`) : "");
    }
    case "psuGpu":
      return he ? "ספק הכוח עומד בהמלצת כרטיס המסך" : "The PSU meets the graphics card's recommendation";
  }
}
