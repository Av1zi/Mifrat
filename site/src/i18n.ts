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
    availability: "זמינות",
    priceHeading: "מחיר",
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
    disclaimer:
      "המחירים נאספים אוטומטית מדי יום מאתרי הספקים. הקישורים מובילים לאתר הספק לרכישה - מפרט אינו מוכר דבר בעצמו.",
  },
  en: {
    availability: "Availability",
    priceHeading: "Price",
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
