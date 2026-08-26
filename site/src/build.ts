import type { Lang, Product } from "./types";

export interface BuildSlot {
  id: string;
  categories: string[];
  label: { he: string; en: string };
  choose: { he: string; en: string };
}

export const BUILD_SLOTS: BuildSlot[] = [
  {
    id: "cpu",
    categories: ["cpu"],
    label: { he: "מעבד", en: "CPU" },
    choose: { he: "בחירת מעבד", en: "Choose A CPU" },
  },
  {
    id: "cooler",
    categories: ["aio", "cooler_air"],
    label: { he: "קירור מעבד", en: "CPU Cooler" },
    choose: { he: "בחירת קירור מעבד", en: "Choose A CPU Cooler" },
  },
  {
    id: "motherboard",
    categories: ["motherboard"],
    label: { he: "לוח אם", en: "Motherboard" },
    choose: { he: "בחירת לוח אם", en: "Choose A Motherboard" },
  },
  {
    id: "memory",
    categories: ["memory"],
    label: { he: "זיכרון", en: "Memory" },
    choose: { he: "בחירת זיכרון", en: "Choose Memory" },
  },
  {
    id: "storage",
    categories: ["storage"],
    label: { he: "אחסון", en: "Storage" },
    choose: { he: "בחירת אחסון", en: "Choose Storage" },
  },
  {
    id: "gpu",
    categories: ["gpu"],
    label: { he: "כרטיס מסך", en: "Video Card" },
    choose: { he: "בחירת כרטיס מסך", en: "Choose A Video Card" },
  },
  {
    id: "case",
    categories: ["case"],
    label: { he: "מארז", en: "Case" },
    choose: { he: "בחירת מארז", en: "Choose A Case" },
  },
  {
    id: "psu",
    categories: ["psu"],
    label: { he: "ספק כוח", en: "Power Supply" },
    choose: { he: "בחירת ספק כוח", en: "Choose A Power Supply" },
  },
];

export function slotForCategory(category: string): BuildSlot | null {
  return BUILD_SLOTS.find((s) => s.categories.includes(category)) ?? null;
}

/** First number found in any of the given attributes ("650W" -> 650). */
export function numAttr(p: Product, keys: string[]): number | null {
  for (const key of keys) {
    const raw = p.attributes[key];
    if (!raw) continue;

    const m = /(\d+(?:\.\d+)?)/.exec(raw);
    if (m) return parseFloat(m[1]);
  }

  return null;
}

/*
============================================================================
Compatibility helpers.

These are intentionally forgiving:
- If we know both sides and they conflict, hide/warn.
- If data is missing, do NOT pretend we know better.
Once the scrape pipeline improves, we can make this stricter.
============================================================================
*/

const SOCKET_TOKENS = [
  "LGA2011V3",
  "LGA20113",
  "LGA2011",
  "LGA1851",
  "LGA1700",
  "LGA1200",
  "LGA1151",
  "LGA1150",
  "LGA1155",
  "LGA1156",
  "LGA1366",
  "LGA2066",
  "AM5",
  "AM4",
  "AM3",
  "AM2",
  "AM1",
  "STR5",
  "STRX4",
  "TR4",
  "SP5",
  "SP3",
];

const CHIPSET_SOCKET: Record<string, string> = {
  // AMD AM4
  A320: "AM4",
  B450: "AM4",
  X470: "AM4",
  A520: "AM4",
  B550: "AM4",
  X570: "AM4",

  // AMD AM5
  A620: "AM5",
  B650: "AM5",
  X670: "AM5",
  X670E: "AM5",
  B840: "AM5",
  B850: "AM5",
  X870: "AM5",
  X870E: "AM5",

  // Intel LGA1700
  H610: "LGA1700",
  B660: "LGA1700",
  H670: "LGA1700",
  Z690: "LGA1700",
  B760: "LGA1700",
  H770: "LGA1700",
  Z790: "LGA1700",

  // Intel LGA1851
  H810: "LGA1851",
  B860: "LGA1851",
  Z890: "LGA1851",

  // Intel LGA1200
  Z490: "LGA1200",
  B460: "LGA1200",
  H470: "LGA1200",
  B560: "LGA1200",
  H570: "LGA1200",
  Z590: "LGA1200",

  // Intel LGA1151
  Z390: "LGA1151",
  B360: "LGA1151",
  H310: "LGA1151",
  Z370: "LGA1151",
  B250: "LGA1151",
  H270: "LGA1151",
  Z270: "LGA1151",
  Z170: "LGA1151",
  H170: "LGA1151",
  B150: "LGA1151",
  H110: "LGA1151",

  // HEDT / older
  X299: "LGA2066",
};

const CHIPSET_TOKENS = Object.keys(CHIPSET_SOCKET).sort(
  (a, b) => b.length - a.length
);

function upperCompact(value?: string | null): string {
  return (value ?? "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}

function socketTokensFromText(text?: string | null): string[] {
  let v = upperCompact(text);
  if (!v) return [];

  const found: string[] = [];

  for (const token of SOCKET_TOKENS) {
    if (v.includes(token)) {
      found.push(token);

      // Remove it so shorter overlapping tokens do not also match.
      v = v.split(token).join("");
    }
  }

  return found;
}

function chipsetSocketFromText(text?: string | null): string | null {
  const v = upperCompact(text);
  if (!v) return null;

  for (const token of CHIPSET_TOKENS) {
    if (v.includes(token)) {
      return CHIPSET_SOCKET[token];
    }
  }

  return null;
}

function socketTokensFromAttributes(
  p: Product,
  keys: string[]
): string[] {
  const values: string[] = [];

  for (const key of keys) {
    values.push(...socketTokensFromText(p.attributes[key]));
  }

  return unique(values);
}

function inferCpuSockets(p: Product): string[] {
  const text = `${p.brand ?? ""} ${p.model ?? ""} ${p.name}`.toUpperCase();

  if (text.includes("THREADRIPPER")) {
    const m = text.match(/THREADRIPPER\s?(?:\d\s?)?(\d{4})/);
    if (m) {
      const first = m[1][0];

      if (first === "7") return ["STR5"];
      if (first === "5") return ["STRX4"];
      if (first === "3") return ["TR4"];
    }

    return [];
  }

  if (text.includes("RYZEN")) {
    const m = text.match(/RYZEN\s?(?:\d\s?)?(\d{4})/);
    if (m) {
      const first = m[1][0];

      if (["7", "8", "9"].includes(first)) return ["AM5"];
      if (["1", "2", "3", "4", "5"].includes(first)) return ["AM4"];
    }

    return [];
  }

  if (text.includes("CORE ULTRA")) {
    return ["LGA1851"];
  }

  const intel = text.match(/I[3579][- ]?(\d{2})\d{3}/);
  if (intel) {
    const gen = parseInt(intel[1], 10);

    if (gen >= 12 && gen <= 14) return ["LGA1700"];
    if (gen === 10 || gen === 11) return ["LGA1200"];
    if (gen >= 6 && gen <= 9) return ["LGA1151"];
    if (gen === 4 || gen === 5) return ["LGA1150"];
    if (gen === 2 || gen === 3) return ["LGA1155"];
  }

  return [];
}

function cpuSocketsForProduct(p: Product): string[] {
  const fromAttrs = socketTokensFromAttributes(p, [
    "socket",
    "cpu_socket",
    "sockets",
  ]);

  if (fromAttrs.length > 0) return fromAttrs;

  const fromText = socketTokensFromText(`${p.name} ${p.model ?? ""}`);
  if (fromText.length > 0) return fromText;

  return inferCpuSockets(p);
}

function motherboardSocketsForProduct(p: Product): string[] {
  const fromAttrs = socketTokensFromAttributes(p, [
    "socket",
    "cpu_socket",
    "sockets",
  ]);

  if (fromAttrs.length > 0) return fromAttrs;

  const fromChipsetAttr = chipsetSocketFromText(p.attributes.chipset);
  if (fromChipsetAttr) return [fromChipsetAttr];

  const fromTextChipset = chipsetSocketFromText(
    `${p.name} ${p.model ?? ""}`
  );

  if (fromTextChipset) return [fromTextChipset];

  return socketTokensFromText(`${p.name} ${p.model ?? ""}`);
}

function coolerSocketsForProduct(p: Product): string[] {
  const fromAttrs = socketTokensFromAttributes(p, [
    "socket",
    "socket_compat",
    "sockets",
    "cpu_socket",
  ]);

  const fromText = socketTokensFromText(`${p.name} ${p.model ?? ""}`);

  return unique([...fromAttrs, ...fromText]);
}

function memoryTypeForProduct(p: Product): string | null {
  const source = [
    p.attributes.memory_type ?? "",
    p.attributes.memory ?? "",
    p.name,
    p.model ?? "",
  ]
    .join(" ")
    .toUpperCase();

  const m = source.match(/DDR\s?([345])/);
  return m ? `DDR${m[1]}` : null;
}

function hasCommonValue(a: string[], b: string[]): boolean {
  return a.some((value) => b.includes(value));
}

/*
============================================================================
Wattage.

No defaults. Only use real scraped attributes.
If nothing is known, estimated wattage is 0.
============================================================================
*/

function knownPartWattage(slotId: string, p: Product): number {
  // PSU supplies power; it does not consume system wattage.
  if (slotId === "psu") return 0;

  const watts = numAttr(p, [
    "tdp",
    "power",
    "power_consumption",
    "wattage",
    "wattage_w",
    "max_power",
    "rated_power",
  ]);

  if (watts === null) return 0;

  return Math.round(watts);
}

export function estimateWattage(parts: Record<string, Product>): number {
  return Object.entries(parts).reduce((sum, [slotId, product]) => {
    return sum + knownPartWattage(slotId, product);
  }, 0);
}

/*
============================================================================
Compatibility issues for already-selected build parts.
============================================================================
*/

export function checkCompatibility(
  parts: Record<string, Product>,
  estWatts: number,
  lang: Lang
): string[] {
  const issues: string[] = [];

  const cpu = parts.cpu;
  const motherboard = parts.motherboard;
  const memory = parts.memory;
  const cooler = parts.cooler;
  const psu = parts.psu;

  if (cpu && motherboard) {
    const cpuSockets = cpuSocketsForProduct(cpu);
    const boardSockets = motherboardSocketsForProduct(motherboard);

    if (
      cpuSockets.length > 0 &&
      boardSockets.length > 0 &&
      !hasCommonValue(cpuSockets, boardSockets)
    ) {
      issues.push(
        lang === "he"
          ? `סוקט המעבד (${cpuSockets.join("/")}) אינו תואם ללוח האם (${boardSockets.join("/")})`
          : `CPU socket (${cpuSockets.join("/")}) does not match motherboard socket (${boardSockets.join("/")})`
      );
    }
  }

  if (memory && motherboard) {
    const boardMemory = memoryTypeForProduct(motherboard);
    const memMemory = memoryTypeForProduct(memory);

    if (boardMemory && memMemory && boardMemory !== memMemory) {
      issues.push(
        lang === "he"
          ? `סוג הזיכרון (${memMemory}) אינו תואם ללוח האם (${boardMemory})`
          : `Memory type (${memMemory}) does not match motherboard memory type (${boardMemory})`
      );
    }
  }

  if (cpu && cooler) {
    const cpuSockets = cpuSocketsForProduct(cpu);
    const coolerSockets = coolerSocketsForProduct(cooler);

    if (
      cpuSockets.length > 0 &&
      coolerSockets.length > 0 &&
      !hasCommonValue(cpuSockets, coolerSockets)
    ) {
      issues.push(
        lang === "he"
          ? `הקירור עשוי שלא להתאים לסוקט המעבד (${cpuSockets.join("/")})`
          : `Cooler may not support CPU socket (${cpuSockets.join("/")})`
      );
    }
  }

  if (psu && estWatts > 0) {
    const capacity = numAttr(psu, [
      "wattage_w",
      "wattage",
      "power",
      "total_power",
      "max_power",
      "rated_power",
    ]);

    if (capacity !== null && capacity < estWatts) {
      issues.push(
        lang === "he"
          ? `הספק (${capacity}W) חלש מהצריכה הידועה (${estWatts}W)`
          : `PSU (${capacity}W) is below known system wattage (${estWatts}W)`
      );
    }
  }

  return issues;
}

/*
============================================================================
Picker compatibility filtering.

This is used by the category page when opened from the builder.
It filters products based on the currently selected build parts.
============================================================================
*/

export function isProductCompatibleWithBuild(
  product: Product,
  slotId: string,
  parts: Record<string, Product>
): boolean {
  if (slotId === "cpu") {
    const motherboard = parts.motherboard;

    if (motherboard) {
      const boardSockets = motherboardSocketsForProduct(motherboard);
      const cpuSockets = cpuSocketsForProduct(product);

      if (
        boardSockets.length > 0 &&
        cpuSockets.length > 0 &&
        !hasCommonValue(boardSockets, cpuSockets)
      ) {
        return false;
      }
    }
  }

  if (slotId === "motherboard") {
    const cpu = parts.cpu;

    if (cpu) {
      const cpuSockets = cpuSocketsForProduct(cpu);
      const boardSockets = motherboardSocketsForProduct(product);

      if (
        cpuSockets.length > 0 &&
        boardSockets.length > 0 &&
        !hasCommonValue(cpuSockets, boardSockets)
      ) {
        return false;
      }
    }
  }

  if (slotId === "memory") {
    const motherboard = parts.motherboard;

    if (motherboard) {
      const boardMemory = memoryTypeForProduct(motherboard);
      const productMemory = memoryTypeForProduct(product);

      if (boardMemory && productMemory && boardMemory !== productMemory) {
        return false;
      }
    }
  }

  if (slotId === "cooler") {
    const cpu = parts.cpu;

    if (cpu) {
      const cpuSockets = cpuSocketsForProduct(cpu);
      const coolerSockets = coolerSocketsForProduct(product);

      if (
        cpuSockets.length > 0 &&
        coolerSockets.length > 0 &&
        !hasCommonValue(cpuSockets, coolerSockets)
      ) {
        return false;
      }
    }
  }

  if (slotId === "psu") {
    const estWatts = estimateWattage(parts);

    if (estWatts > 0) {
      const capacity = numAttr(product, [
        "wattage_w",
        "wattage",
        "power",
        "total_power",
        "max_power",
        "rated_power",
      ]);

      if (capacity !== null && capacity < estWatts) {
        return false;
      }
    }
  }

  return true;
}