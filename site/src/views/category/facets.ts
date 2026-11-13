/**
 * Derived filters: rail groups computed from one or more typed spec fields
 * instead of read off a single one. They exist where the raw field is too
 * messy or too fine-grained to filter on directly (case board support spelled
 * a dozen ways, storage capacity in exact GB, interface strings per vendor).
 * The selected values ride in the URL like any other filter (`f.<key>=...`).
 */

import { BOARD_LABEL, boardSize, caseType, supportedBoardSizes } from "../../formFactors";
import { categoryLabel } from "../../i18n";
import type { Lang, Product } from "../../types";

type Text = { he: string; en: string };

export interface Facet {
  key: string;
  label: Text;
  /** Values one product contributes (none = the product never matches). */
  values(p: Product): string[];
  /** Fixed option order; values outside it sort last. */
  order?: readonly string[];
  /** Display text for a stored value (defaults to the value itself). */
  optionLabel?(value: string, lang: Lang): string;
  /** Schema fields this facet replaces in the rail. */
  replaces?: readonly string[];
}

const spec = (p: Product, field: string): unknown => p.specs?.[field];

const num = (p: Product, field: string): number | null => {
  const value = spec(p, field);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

const text = (p: Product, field: string): string => {
  const value = spec(p, field);
  return typeof value === "string" ? value : "";
};

// ---- case -----------------------------------------------------------------

/** PCPartPicker's case-type list, in its order. */
const CASE_TYPES = [
  "ATX Desktop",
  "ATX Full Tower",
  "ATX Mid Tower",
  "ATX Mini Tower",
  "HTPC",
  "MicroATX Desktop",
  "MicroATX Mid Tower",
  "MicroATX Mini Tower",
  "Mini ITX Desktop",
  "Mini ITX Tower",
  "Rackmount 1U",
  "Rackmount 2U",
  "Rackmount 3U",
  "Rackmount 4U",
  "Rackmount 5U",
];

/** Replaces the raw `type` ("Mid Tower", "SFF", "ATX") with board family + body. */
const caseTypeFacet: Facet = {
  key: "case_type",
  label: { he: "סוג", en: "Type" },
  values: (p) => {
    const value = caseType(spec(p, "type"), spec(p, "mb_form_factors"), p.name);
    return value ? [value] : [];
  },
  order: CASE_TYPES,
  replaces: ["type", "rackmount"],
};

/** Every board the case takes; an ATX case also takes Micro ATX and Mini ITX. */
const caseBoards: Facet = {
  key: "board_support",
  label: { he: "לוחות אם נתמכים", en: "Supported motherboards" },
  values: (p) => supportedBoardSizes(spec(p, "mb_form_factors")).map((size) => BOARD_LABEL[size]),
};

/** The board's own size, in the same spelling the case filter uses. */
const boardForm: Facet = {
  key: "board_form",
  label: { he: "פורמט", en: "Form factor" },
  values: (p) => {
    const size = boardSize(spec(p, "form_factor"));
    return size ? [BOARD_LABEL[size]] : [];
  },
  replaces: ["form_factor"],
};

/** {"360 mm": 1, "240 mm": 2} -> ["240 mm", "360 mm"]. */
const radiatorSupport: Facet = {
  key: "radiator_support",
  label: { he: "רדיאטור נתמך", en: "Radiator support" },
  values: (p) => {
    const value = spec(p, "radiator_support");
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const sizes = new Set<string>();
    for (const key of Object.keys(value)) {
      const match = key.match(/(\d{3})/);
      if (match && [120, 140, 240, 280, 360, 420, 480].includes(Number(match[1]))) sizes.add(`${match[1]} mm`);
    }
    return [...sizes];
  },
  order: ["120 mm", "140 mm", "240 mm", "280 mm", "360 mm", "420 mm", "480 mm"],
};

// ---- storage --------------------------------------------------------------

/** Marketing capacities, so "960 GB" and "1 TB" land in one box. */
const CAPACITY_BUCKETS: Array<{ id: string; max: number; label: Text }> = [
  { id: "256", max: 300, label: { he: "עד 256GB", en: "Up to 256 GB" } },
  { id: "512", max: 700, label: { he: "480–512GB", en: "480–512 GB" } },
  { id: "1000", max: 1500, label: { he: "1TB", en: "1 TB" } },
  { id: "2000", max: 2600, label: { he: "2TB", en: "2 TB" } },
  { id: "4000", max: 5000, label: { he: "3–4TB", en: "3–4 TB" } },
  { id: "8000", max: 9000, label: { he: "6–8TB", en: "6–8 TB" } },
  { id: "16000", max: 17000, label: { he: "10–16TB", en: "10–16 TB" } },
  { id: "max", max: Infinity, label: { he: "18TB ומעלה", en: "18 TB and up" } },
];

const storageCapacity: Facet = {
  key: "capacity",
  label: { he: "נפח", en: "Capacity" },
  values: (p) => {
    const gb = num(p, "capacity_gb");
    if (gb === null) return [];
    const bucket = CAPACITY_BUCKETS.find((b) => gb <= b.max);
    return bucket ? [bucket.id] : [];
  },
  order: CAPACITY_BUCKETS.map((b) => b.id),
  optionLabel: (value, lang) => CAPACITY_BUCKETS.find((b) => b.id === value)?.label[lang] ?? value,
  replaces: ["capacity_gb"],
};

/** One connection value from nvme + pcie_gen + the vendor interface text. */
export function driveConnection(p: Product): string | null {
  const nvme = spec(p, "nvme");
  const gen = num(p, "pcie_gen");
  const raw = text(p, "interface").toUpperCase();
  if (nvme === true || /NVME/.test(raw)) {
    const fromText = raw.match(/(?:GEN\s*|PCIE\s*|PCI EXPRESS\s*)([345])(?:\.0)?/);
    const g = gen ?? (fromText ? Number(fromText[1]) : null);
    return g ? `NVMe PCIe ${g}.0` : "NVMe";
  }
  if (/USB|TYPE-C/.test(raw)) return "USB";
  if (/SAS/.test(raw)) return "SAS";
  if (/U\.2/.test(raw)) return "U.2";
  if (/SATA/.test(raw) || spec(p, "type") === "HDD") return "SATA";
  if (nvme === false && /M\.2/.test(text(p, "form_factor").toUpperCase())) return "SATA";
  return null;
}

const storageConnection: Facet = {
  key: "connection",
  label: { he: "חיבור", en: "Connection" },
  values: (p) => {
    const value = driveConnection(p);
    return value ? [value] : [];
  },
  order: ["NVMe PCIe 5.0", "NVMe PCIe 4.0", "NVMe PCIe 3.0", "NVMe", "SATA", "SAS", "U.2", "USB"],
  replaces: ["interface", "nvme", "pcie_gen"],
};

/** "M.2-2280", "M.2 2280", '2.5"', "2.5''", "2.5-inch" -> one spelling each. */
export function driveForm(p: Product): string | null {
  const raw = text(p, "form_factor").toUpperCase();
  if (!raw) return null;
  const m2 = raw.match(/M\.?2[\s-]*(22(?:30|42|60|80|110))/);
  if (m2) return `M.2 ${m2[1]}`;
  if (/M\.?2/.test(raw)) return "M.2";
  if (/3\.5/.test(raw)) return '3.5"';
  if (/2\.5/.test(raw)) return '2.5"';
  if (/PCI/.test(raw)) return "PCIe";
  return null;
}

const storageForm: Facet = {
  key: "drive_form",
  label: { he: "פורמט", en: "Form factor" },
  values: (p) => {
    const value = driveForm(p);
    return value ? [value] : [];
  },
  order: ["M.2 2280", "M.2 2230", "M.2 2242", "M.2 2260", "M.2 22110", "M.2", '2.5"', '3.5"', "PCIe"],
  replaces: ["form_factor"],
};

// ---- memory ---------------------------------------------------------------

/** "2 x 16GB": the kit as PCPartPicker lists it, grouped by total size. */
const memoryKit: Facet = {
  key: "kit",
  label: { he: "ערכה", en: "Modules" },
  values: (p) => {
    const count = num(p, "module_count");
    const size = num(p, "module_size_gb");
    return count && size ? [`${count} x ${size}GB`] : [];
  },
};

/** Order for "2 x 16GB" strings: kits of one stick size together, then by stick count. */
export function kitOrder(a: string, b: string): number {
  const parse = (s: string): [number, number] => {
    const m = s.match(/^(\d+) x (\d+)GB$/);
    return m ? [Number(m[2]), Number(m[1])] : [Infinity, Infinity];
  };
  const [sa, ca] = parse(a);
  const [sb, cb] = parse(b);
  return sa - sb || ca - cb;
}

// ---- motherboard ----------------------------------------------------------

/** "Realtek RTL8125BG 2.5G LAN", "LAN 2.5 Gb/s", "2.5GbE" -> "2.5 Gb/s". */
export function lanSpeed(p: Product): string | null {
  const raw = text(p, "ethernet");
  if (!raw) return null;
  const gig = raw.match(/(?:^|[^\d.])(\d+(?:\.\d+)?)\s*G(?:b|bps|bit|be|\b|\s*LAN|\s*ETH)/i);
  if (gig) return `${Number(gig[1])} Gb/s`;
  const megs = [...raw.matchAll(/(\d+)\s*M(?:b|bit|bps)/gi)].map((m) => Number(m[1]));
  if (megs.length > 0) {
    const top = Math.max(...megs);
    return top >= 1000 ? `${top / 1000} Gb/s` : `${top} Mb/s`;
  }
  if (/gigabit|\bgbe\b/i.test(raw)) return "1 Gb/s";
  return null;
}

const LAN_SPEEDS = ["100 Mb/s", "1 Gb/s", "2.5 Gb/s", "5 Gb/s", "10 Gb/s"];

const motherboardLan: Facet = {
  key: "lan",
  label: { he: "מהירות רשת", en: "Ethernet speed" },
  // Speeds no consumer board ships ("2 Gb/s", "25 Gb/s") are misread cells.
  values: (p) => {
    const value = lanSpeed(p);
    return value && LAN_SPEEDS.includes(value) ? [value] : [];
  },
  order: LAN_SPEEDS,
  replaces: ["ethernet"],
};

// ---------------------------------------------------------------------------

const FACETS: Record<string, Facet[]> = {
  case: [caseTypeFacet, caseBoards, radiatorSupport],
  storage: [storageCapacity, storageConnection, storageForm],
  memory: [memoryKit],
  motherboard: [boardForm, motherboardLan],
};

/**
 * Rail order per category, after stores, manufacturer and price (always the
 * first three). Most decisive first, and related filters stay neighbours so
 * the rail reads as one train of thought: socket → chipset, memory type →
 * slots → max memory, case type → board size → clearances. Keys are schema
 * fields or derived-filter keys; anything filterable but unlisted follows in
 * schema order, so a new schema field still shows up.
 */
const RAIL_ORDER: Record<string, string[]> = {
  cpu: [
    // platform
    "socket", "series", "microarchitecture",
    // performance
    "core_count", "thread_count", "boost_clock_ghz", "l3_cache_mb", "smt", "unlocked",
    // power and the box
    "tdp_w", "integrated_graphics", "includes_cooler", "packaging",
    "ecc_support",
  ],
  motherboard: [
    // fit and platform
    "board_form", "socket", "chipset",
    // memory
    "memory_type", "memory_slots", "memory_max_gb", "ecc_support",
    // expansion and connectivity
    "pcie_x16_slots", "sata_ports", "wireless", "lan",
    // looks
    "color", "lighting",
  ],
  memory: [
    // compatibility
    "memory_type", "form_factor",
    // size
    "kit", "total_gb", "module_count",
    // speed
    "speed_mhz", "cas_latency", "first_word_latency_ns",
    "ecc",
    // looks
    "color", "lighting",
  ],
  storage: [
    "capacity", "type",
    // how it connects
    "connection", "drive_form",
    "rpm",
  ],
  gpu: [
    // which GPU
    "chip_manufacturer", "chipset",
    // memory
    "memory_gb", "memory_type",
    // fit and power
    "length_mm", "tdp_w", "interface",
    // cooling and looks
    "cooling", "color",
  ],
  case: [
    // what it is and what it holds
    "case_type", "board_support",
    // what fits inside
    "max_gpu_length_mm", "max_cooler_height_mm", "radiator_support",
    // storage
    "drive_bays_35", "drive_bays_25",
    // size and looks
    "volume_l", "side_panel", "color", "lighting",
  ],
  psu: [
    // capacity and quality
    "wattage_w", "efficiency", "modular",
    // fit
    "type", "length_mm",
    // connectors
    "pcie16_connectors", "pcie8_connectors", "sata_connectors",
    // noise and looks
    "fanless", "color",
  ],
  cpu_cooler: [
    // kind and fit
    "cooler_type", "sockets",
    // size
    "radiator_size_mm", "height_mm", "fan_size_mm",
    // capacity and noise
    "tdp_w", "noise_db", "fanless",
    // looks
    "lighting", "color",
  ],
  case_fan: [
    "size_mm", "quantity",
    // control and noise
    "pwm", "noise_db",
    // looks
    "led", "color",
  ],
};

/** Every rail key for a category (derived and schema), in rail order, manufacturer first. */
export function railKeys(category: string, schemaKeys: readonly string[]): string[] {
  const replaced = replacedFields(category);
  const all = [...facetsFor(category).map((facet) => facet.key), ...schemaKeys.filter((key) => !replaced.has(key))];
  const order = ["manufacturer", ...(RAIL_ORDER[category] ?? [])];
  const rank = (key: string): number => {
    const i = order.indexOf(key);
    return i < 0 ? order.length + all.indexOf(key) : i;
  };
  return [...new Set(all)].sort((a, b) => rank(a) - rank(b));
}

export function facetsFor(category: string): Facet[] {
  return FACETS[category] ?? [];
}

export function facetFor(category: string, key: string): Facet | undefined {
  return facetsFor(category).find((facet) => facet.key === key);
}

/** Schema fields a derived filter stands in for (kept off the rail). */
export function replacedFields(category: string): Set<string> {
  return new Set(facetsFor(category).flatMap((facet) => facet.replaces ?? []));
}

// ---- option values: one spelling per meaning --------------------------------

const COLORS = [
  "Black", "White", "Gray", "Silver", "Titanium", "Gunmetal", "Red", "Orange", "Yellow", "Gold",
  "Green", "Olive Drab", "Teal", "Cyan", "Blue", "Purple", "Pink", "Brown", "Beige", "Wood",
  "Bronze", "Copper", "Clear", "Camo", "Multicolor",
];
const COLOR_ALIASES: Record<string, string> = {
  grey: "Gray", wt: "White", wh: "White", bk: "Black", blk: "Black", multicolour: "Multicolor", transparent: "Clear",
};

/**
 * "Silver / Black" and "Black / Silver" are one choice, so the parts are put
 * in one fixed order. Words that are not colours ("ARGB", product names) drop.
 */
function normColor(value: string): string[] {
  const parts = new Set<string>();
  for (const raw of value.split("/")) {
    const word = raw.trim();
    const color = COLOR_ALIASES[word.toLowerCase()] ?? COLORS.find((c) => c.toLowerCase() === word.toLowerCase());
    if (color) parts.add(color);
  }
  if (parts.size === 0) return [];
  return [[...parts].sort((a, b) => COLORS.indexOf(a) - COLORS.indexOf(b)).join(" / ")];
}

/**
 * Lighting is a set of features: "ARGB | LCD", "LCD | ARGB" and "ARGB, LCD" are
 * one product with two features, so each feature is its own option.
 */
function normLighting(value: string): string[] {
  const found = new Set<string>();
  for (const raw of value.split(/[|,/+]/)) {
    const word = raw.trim();
    if (/argb|addressable|5\s*v/i.test(word)) found.add("ARGB");
    else if (/\brgb\b/i.test(word)) found.add("RGB");
    else if (/lcd|screen|display/i.test(word)) found.add("LCD");
    else if (/^led$/i.test(word)) found.add("LED");
    else if (/^(no|none)$/i.test(word)) found.add("No");
  }
  if (found.size > 1) found.delete("No");
  return [...found];
}

/** PCPartPicker's series names: brand first, one name per line-up. */
function normCpuSeries(value: string, p: Product): string[] {
  let s = value.trim().replace(/\s+-\s+.*$/, "");
  s = s.replace(/^(AMD|Intel)\s+/i, "");
  if (/threadripper/i.test(s)) s = s.replace(/^Ryzen\s+/i, "");
  if (/^Ultra\s+\d/i.test(s)) s = `Core ${s}`;
  if (/^A\s*Series$/i.test(s)) s = "A-Series";
  const brand = /intel/i.test(String(p.brand ?? spec(p, "manufacturer"))) ? "Intel" : /amd/i.test(String(p.brand ?? spec(p, "manufacturer"))) ? "AMD" : "";
  return s ? [brand ? `${brand} ${s}` : s] : [];
}

/** "Radeon", "Radeon Graphics" and "AMD Radeon Graphics" are one iGPU. */
function normIgpu(value: string): string[] {
  const v = value.trim();
  if (/^(no|none)$/i.test(v)) return ["None"];
  if (/radeon/i.test(v)) {
    const model = v.replace(/^(amd\s+)?radeon\s*/i, "").replace(/\s*graphics$/i, "").trim();
    return [model ? `AMD Radeon ${model}` : "AMD Radeon Graphics"];
  }
  if (/intel|uhd|hd graphics|iris|^xe$/i.test(v)) {
    const model = v.replace(/^intel\s*/i, "").trim();
    return [model === "UHD" ? "Intel UHD Graphics" : model ? `Intel ${model}` : "Intel Graphics"];
  }
  return [v];
}

/** Every AMD desktop/workstation chipset name; the rest of the B/H/Z/W/C/X line is Intel. */
const AMD_CHIPSETS = new Set([
  "A320", "A520", "A620", "A620A", "B350", "B450", "B550", "B650", "B650E", "B840", "B850",
  "X370", "X399", "X470", "X570", "X670", "X670E", "X870", "X870E", "TRX40", "TRX50", "WRX80", "WRX90",
]);

/** The board's chipset with its platform: "AMD B650", "Intel Z790" (as PCPartPicker lists them). */
function normChipset(value: string): string[] {
  const v = value.trim().toUpperCase();
  if (v === "SOC") return ["SoC"];
  if (AMD_CHIPSETS.has(v)) return [`AMD ${v}`];
  if (/^(B|H|Z|Q|W|C|X|HM|QM)\d{2,3}[A-Z]?$/.test(v)) return [`Intel ${v}`];
  return [value];
}

/** "PCIe 5.0 x16" from "PCI Express x16 5.0", "PCIe Gen5"...; connector lists drop. */
function normGpuInterface(value: string): string[] {
  const raw = value.toUpperCase();
  if (!/PCI/.test(raw)) return [];
  if (raw.trim() === "PCI") return ["PCI"];
  const gen = raw.match(/(?:PCI[\s-]*E(?:XPRESS)?|GEN)\s*([1-5])(?:\.0)?\b/) ?? raw.match(/\b([1-5])\.0\b/);
  if (!gen) return [];
  const lanes = raw.match(/[X×]\s*(16|8|4|1)\b/);
  return [lanes ? `PCIe ${gen[1]}.0 x${lanes[1]}` : `PCIe ${gen[1]}.0`];
}

/**
 * The option values one raw spec value stands for, after folding spellings.
 * An empty result keeps the product out of that filter (unknown, not a guess).
 */
export function normalizeOption(category: string, key: string, value: string, p: Product): string[] {
  if (key === "color") return normColor(value);
  if (key === "lighting" || key === "led") return normLighting(value);
  if (category === "cpu" && key === "series") return normCpuSeries(value, p);
  if (category === "cpu" && key === "integrated_graphics") return normIgpu(value);
  if (category === "motherboard" && key === "chipset") return normChipset(value);
  if (category === "gpu" && key === "interface") return normGpuInterface(value);
  return [value];
}

// ---- option order --------------------------------------------------------------

const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
const NONE_VALUES = new Set(["None", "No", "No Window"]);

/**
 * PCPartPicker order: alphabetical with numbers in numeric order, so one
 * line-up stays together (Core i3, i5, i7, i9; Zen, Zen+, Zen 2 ... Zen 5;
 * B650, B650E). "None" leads. "+" sorts as a half step (AM3, AM3+, AM4).
 */
function natural(a: string, b: string): number {
  const none = Number(!NONE_VALUES.has(a)) - Number(!NONE_VALUES.has(b));
  const key = (s: string): string => s.replace(/\+$/, " 1.5").replace(/\+/g, " 1.5 ");
  return none || collator.compare(key(a), key(b));
}

const AMD_ARCH = /^(zen|bulldozer|excavator|jaguar|k\d+|lynx|piledriver|puma|steamroller|llano|trinity|richland|kaveri|carrizo|bristol|stoney)/i;

/** Fixed orders where alphabetical would be wrong (best first, or a known scale). */
const FIXED_ORDER: Record<string, string[]> = {
  "psu.efficiency": ["80+ Titanium", "80+ Platinum", "80+ Gold", "80+ Silver", "80+ Bronze", "80+ White"],
  "psu.modular": ["Full-Modular", "Semi-Modular", "No"],
  "psu.type": ["ATX", "SFX", "SFX-L", "Flex ATX", "TFX", "Micro ATX", "Mini ITX", "1U", "2U"],
  "motherboard.wireless": ["Wi-Fi 7", "Wi-Fi 6E", "Wi-Fi 6", "Wi-Fi 5", "Yes", "No"],
  "storage.type": ["SSD", "HDD", "Hybrid"],
};

function byList(order: readonly string[]): (a: string, b: string) => number {
  const rank = (v: string): number => {
    const i = order.indexOf(v);
    return i < 0 ? order.length : i;
  };
  return (a, b) => rank(a) - rank(b) || natural(a, b);
}

function gpuInterfaceOrder(a: string, b: string): number {
  const parse = (s: string): [number, number] => {
    const m = s.match(/PCIe (\d)\.0(?: x(\d+))?/);
    return m ? [Number(m[1]), Number(m[2] ?? 0)] : [0, 0];
  };
  const [ga, la] = parse(a);
  const [gb, lb] = parse(b);
  return gb - ga || lb - la;
}

/** Comparator for one rail key's options. */
export function optionComparator(category: string, key: string, type: string | undefined): (a: string, b: string) => number {
  const facet = facetFor(category, key);
  if (facet?.key === "kit") return kitOrder;
  if (facet?.order) return byList(facet.order);
  if (facet) return natural;
  if (type === "int" || type === "float") return (a, b) => Number(a) - Number(b);
  if (type === "bool") return byList(["Yes", "No"]);
  const fixed = FIXED_ORDER[`${category}.${key}`];
  if (fixed) return byList(fixed);
  if (key === "microarchitecture") return (a, b) => Number(!AMD_ARCH.test(a)) - Number(!AMD_ARCH.test(b)) || natural(a, b);
  if (category === "gpu" && key === "interface") return gpuInterfaceOrder;
  return natural;
}

/** Display text for a cleaned-up option, when it is not the value itself. */
export function optionDisplay(category: string, key: string, value: string, lang: Lang): string | null {
  if (key === "accessory_type") return categoryLabel(value, lang);
  if (category === "motherboard" && key === "wireless" && value === "Yes") {
    return lang === "he" ? "כן, תקן לא צוין" : "Yes, standard not listed";
  }
  if (value === "No" || value === "None") return lang === "he" ? "ללא" : "None";
  return null;
}
