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
  "cooler_accessory",
  "rgb_lighting",
  "fan_controller",
  "thermal_paste",
  "other",
] as const;

export const CATEGORY_LABELS: Record<string, { he: string; en: string }> = {
  cpu: { he: "מעבדים", en: "Processors" },
  motherboard: { he: "לוחות אם", en: "Motherboards" },
  memory: { he: "זיכרון", en: "Memory" },
  gpu: { he: "כרטיסי מסך", en: "Graphics Cards" },
  storage: { he: "אחסון", en: "Storage" },
  psu: { he: "ספקי כוח", en: "Power Supplies" },
  case: { he: "מארזים", en: "Cases" },
  case_fan: { he: "מאווררים למארז", en: "Case Fans" },
  aio: { he: "קירור נוזלי", en: "Liquid Coolers" },
  cooler_air: { he: "קירור אוויר", en: "Air Coolers" },
  cooling_other: { he: "קירור אחר", en: "Other Cooling" },
  cooler_accessory: { he: "אביזרי קירור", en: "Cooler Accessories" },
  rgb_lighting: { he: "תאורת RGB", en: "RGB Lighting" },
  fan_controller: { he: "בקרי מאווררים", en: "Fan Controllers" },
  thermal_paste: { he: "משחת תרמית", en: "Thermal Paste" },
  other: { he: "רכיבים אחרים", en: "Other Components" },
};

export const VENDOR_LABELS: Record<string, string> = {
  tms: "TMS",
  onepc: "1PC",
  "1pc": "1PC",
  plonter: "Plonter",
  ivory: "Ivory",
};

export const ATTRIBUTE_LABELS: Record<string, { he: string; en: string }> = {
  socket: { he: "סוקט", en: "Socket" },
  chipset: { he: "ערכת שבבים", en: "Chipset" },
  memory_type: { he: "סוג זיכרון", en: "Memory Type" },
  form_factor: { he: "פורמט", en: "Form Factor" },
  wifi: { he: "Wi-Fi", en: "Wi-Fi" },
  color: { he: "צבע", en: "Color" },
  brand: { he: "מותג", en: "Brand" },
  model: { he: "דגם", en: "Model" },
  vendor: { he: "חנות", en: "Shop" },

  // pcpartdb reference specs (site/src/types.ts's PcPartDbRef) — shown in
  // detail.ts's separate "reference specs" section, so these only ever
  // need labels, never merge into the vendor-attribute filter rail above.
  core_count: { he: "מספר ליבות", en: "Cores" },
  core_clock: { he: "תדר בסיס", en: "Base Clock" },
  boost_clock: { he: "תדר מוגבר", en: "Boost Clock" },
  microarchitecture: { he: "ארכיטקטורה", en: "Microarchitecture" },
  tdp: { he: "צריכת חשמל (TDP)", en: "TDP" },
  graphics: { he: "גרפיקה משולבת", en: "Integrated Graphics" },
  length: { he: "אורך", en: "Length" },
  memory: { he: "זיכרון וידאו", en: "Video Memory" },
  external_volume: { he: "נפח חיצוני", en: "External Volume" },
  internal_35_bays: { he: "תאי 3.5 אינץ'", en: "3.5\" Bays" },
  side_panel: { he: "פאנל צד", en: "Side Panel" },
  type: { he: "סוג", en: "Type" },
  rpm: { he: "סל\"ד", en: "RPM" },
  noise_level: { he: "רמת רעש", en: "Noise Level" },
  airflow: { he: "ספיקת אוויר", en: "Airflow" },
  pwm: { he: "PWM", en: "PWM" },
  channels: { he: "ערוצים", en: "Channels" },
  amount: { he: "כמות", en: "Amount" },

  // Numeric filter attributes
  price: { he: "מחיר", en: "Price" },
  cores: { he: "ליבות", en: "Cores" },
  threads: { he: "נימים", en: "Threads" },
  cache_mb: { he: "זיכרון מטמון (MB)", en: "Cache (MB)" },
  base_clock_ghz: { he: "תדר בסיס (GHz)", en: "Base Clock (GHz)" },
  boost_clock_ghz: { he: "תדר מוגבר (GHz)", en: "Boost Clock (GHz)" },
  vram_gb: { he: "זיכרון וידאו (GB)", en: "VRAM (GB)" },
  wattage_w: { he: "הספק (W)", en: "Wattage (W)" },
  capacity_gb: { he: "נפח (GB)", en: "Capacity (GB)" },
  speed_mhz: { he: "מהירות (MHz)", en: "Speed (MHz)" },
  cas_latency: { he: "זמן השהיה (CL)", en: "CAS Latency" },
  pcie_gen: { he: "דור PCIe", en: "PCIe Gen" },
  cooler_height_mm: { he: "גובה קירור (ממ)", en: "Cooler Height (mm)" },
  radiator_size_mm: { he: "גודל רדיאטור (ממ)", en: "Radiator Size (mm)" },
  fan_size_mm: { he: "גודל מאוורר (ממ)", en: "Fan Size (mm)" },
};

export function categoryLabel(id: string, lang: Lang): string {
  return CATEGORY_LABELS[id]?.[lang] ?? id;
}

export function vendorLabel(id: string): string {
  return VENDOR_LABELS[id] ?? id;
}

export function attributeLabel(key: string, lang: Lang): string {
  return ATTRIBUTE_LABELS[key]?.[lang] ?? key;
}

const STRINGS = {
  he: {
    referenceSpecsHeading: "מפרט לדוגמה",
    referenceSpecsNote: "מבוסס על מאגר נתונים אחר, המוצר עלול להיות מדגם שונה",
    configurePrice: "התאמת מחיר",
    selectMerchant: "בחירת חנות",
    cheapest: "הזול ביותר",
    customPrice: "מחיר מותאם אישית",
    enterPrice: "הכנס מחיר",
    save: "שמור",
    cancel: "ביטול",
    availability: "זמין",
    priceHeading: "מחיר",
    builderNav: "בניית מחשב",
    builderTitle: "בחרו את החלקים",
    totalLabel: "סה״כ:",
    estimatedWattage: "צריכה משוערת:",
    compatibilityOk: "תאימות: לא נמצאו בעיות.",
    compatibilityIdle: "בחרו רכיבים כדי לבדוק תאימות.",
    copyLink: "העתקת קישור",
    copied: "הועתק!",
    addToBuild: "הוספה לבנייה",
    removePart: "הסרה",
    componentHeading: "רכיב",
    selectionHeading: "בחירה",
    skuLabel: "מק״ט",
    appName: "מפרט",
    tagline: "השוואת מחירים לרכיבי מחשב מהחנויות המובילות בישראל",
    searchPlaceholder: "חיפוש לפי שם או מותג…",
    home: "כל הקטגוריות",
    backToCategories: "חזרה לקטגוריות",
    inStockOnly: "במלאי בלבד",
    sortLabel: "מיון",
    sortPriceAsc: "מחיר: מהזול ליקר",
    sortPriceDesc: "מחיר: מהיקר לזול",
    sortVendorsDesc: "הכי הרבה חנויות",
    sortName: "שם",
    noResults: "לא נמצאו תוצאות",
    viewOffers: "השוואת מחירים",
    offersHeading: "מחירים בחנויות",
    outOfStock: "אזל מהמלאי",
    inStock: "במלאי",
    staleData: "מחיר לא עודכן היום",
    close: "סגירה",
    filtersHeading: "סינון",
    clearFilters: "איפוס סינון",
    currencyToggle: "$",
    langToggle: "EN",
    loading: "טוען…",
    loadError: "שגיאה בטעינת הנתונים. נסו לרענן את הדף.",
    sourceLinkLabel: "קוד המקור בגיטהאב",
    min: "מינימום",
    max: "מקסימום",
    priceRange: "טווח מחירים",
    disclaimer:
      "המחירים נאספים אוטומטית מדי יום מאתרי הספקים. הקישורים מובילים לאתר הספק לרכישה - מפרט אינו מוכר דבר בעצמו.",
  },
  en: {
        referenceSpecsHeading: "Reference specs",
    referenceSpecsNote:"Based on a similar product in an external dataset, the exact model sold here may differ slightly.",
    configurePrice: "Configure Price",
    selectMerchant: "Select Merchant",
    cheapest: "Cheapest",
    customPrice: "Custom Price",
    enterPrice: "Enter Price",
    save: "Save",
    cancel: "Cancel",
    availability: "Availability",
    priceHeading: "Price",
    builderNav: "Builder",
    builderTitle: "Choose Your Parts",
    totalLabel: "Total:",
    estimatedWattage: "Estimated Wattage:",
    compatibilityOk: "Compatibility: No issues detected.",
    compatibilityIdle: "Pick parts to check compatibility.",
    copyLink: "Copy link",
    copied: "Copied!",
    addToBuild: "Add to build",
    removePart: "Remove",
    componentHeading: "Component",
    selectionHeading: "Selection",
    skuLabel: "SKU",
    appName: "Mifrat",
    tagline: "Price comparison for PC parts across Israeli vendors",
    searchPlaceholder: "Search by name or brand…",
    home: "All categories",
    backToCategories: "Back to categories",
    inStockOnly: "In stock only",
    sortLabel: "Sort",
    sortPriceAsc: "Price: low to high",
    sortPriceDesc: "Price: high to low",
    sortVendorsDesc: "Most vendors",
    sortName: "Name",
    noResults: "No results found",
    viewOffers: "Compare prices",
    offersHeading: "Vendor prices",
    outOfStock: "Out of stock",
    inStock: "In stock",
    staleData: "Price not refreshed today",
    close: "Close",
    filtersHeading: "Filters",
    clearFilters: "Clear filters",
    currencyToggle: "₪",
    langToggle: "עברית",
    loading: "Loading…",
    loadError: "Couldn't load data. Try refreshing the page.",
    sourceLinkLabel: "Source on GitHub",
    min: "Min",
    max: "Max",
    priceRange: "Price Range",
    disclaimer:
      "Prices are scraped daily from each vendor's site. Links go to the vendor to buy — Mifrat doesn't sell anything itself.",
  },
} satisfies Record<Lang, Record<string, string>>;

export type StringKey = keyof (typeof STRINGS)["he"];

export function t(lang: Lang, key: StringKey): string {
  return STRINGS[lang][key];
}

export function resultsCount(lang: Lang, n: number): string {
  return lang === "he" ? `${n} תוצאות` : `${n} results`;
}

export function vendorsCount(lang: Lang, n: number): string {
  if (lang === "he") return n === 1 ? "חנות אחת" : `${n} חנויות`;
  return n === 1 ? "1 vendor" : `${n} vendors`;
}

export function lastUpdated(lang: Lang, isoDate: string): string {
  const d = new Date(isoDate);
  const formatted = d.toLocaleDateString(lang === "he" ? "he-IL" : "en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  return lang === "he" ? `עודכן לאחרונה: ${formatted}` : `Last updated: ${formatted}`;
}
