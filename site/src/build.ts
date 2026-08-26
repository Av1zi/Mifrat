import type { Lang, Product } from "./types";

export interface BuildSlot {
  id: string;
  categories: string[];
  label: { he: string; en: string };
  choose: { he: string; en: string };
}

// Mirrors PCPartPicker's builder rows, mapped onto our data categories.
export const BUILD_SLOTS: BuildSlot[] = [
  { id: "cpu", categories: ["cpu"], label: { he: "מעבד", en: "CPU" }, choose: { he: "בחירת מעבד", en: "Choose A CPU" } },
  { id: "cooler", categories: ["aio", "cooler_air"], label: { he: "קירור מעבד", en: "CPU Cooler" }, choose: { he: "בחירת קירור מעבד", en: "Choose A CPU Cooler" } },
  { id: "motherboard", categories: ["motherboard"], label: { he: "לוח אם", en: "Motherboard" }, choose: { he: "בחירת לוח אם", en: "Choose A Motherboard" } },
  { id: "memory", categories: ["memory"], label: { he: "זיכרון", en: "Memory" }, choose: { he: "בחירת זיכרון", en: "Choose Memory" } },
  { id: "storage", categories: ["storage"], label: { he: "אחסון", en: "Storage" }, choose: { he: "בחירת אחסון", en: "Choose Storage" } },
  { id: "gpu", categories: ["gpu"], label: { he: "כרטיס מסך", en: "Video Card" }, choose: { he: "בחירת כרטיס מסך", en: "Choose A Video Card" } },
  { id: "case", categories: ["case"], label: { he: "מארז", en: "Case" }, choose: { he: "בחירת מארז", en: "Choose A Case" } },
  { id: "psu", categories: ["psu"], label: { he: "ספק כוח", en: "Power Supply" }, choose: { he: "בחירת ספק כוח", en: "Choose A Power Supply" } },
];

export function slotForCategory(category: string): BuildSlot | null {
  return BUILD_SLOTS.find((s) => s.categories.includes(category)) ?? null;
}

/** First number found in any of the given attributes ("650W" -> 650). */
export function numAttr(p: Product, keys: string[]): number | null {
  for (const key of keys) {
    const raw = p.attributes[key];
    if (!raw) continue;
    const m = /(\d+(\.\d+)?)/.exec(raw);
    if (m) return parseFloat(m[1]);
  }
  return null;
}

/** Rough per-part draw: real TDP/wattage attr when scraped, sane defaults otherwise. */
function partWattage(slotId: string, p: Product): number {
  if (slotId === "psu") return 0; // the PSU supplies, it doesn't consume
  const tdp = numAttr(p, ["tdp", "power", "power_consumption", "wattage"]);
  if (tdp !== null && (slotId === "cpu" || slotId === "gpu")) return Math.round(tdp);
  switch (slotId) {
    case "cpu": return 95;
    case "gpu": return 220;
    case "cooler": return 12;
    case "motherboard": return 60;
    case "memory": return 10;
    case "storage": return 8;
    case "case": return 15;
    default: return 10;
  }
}

export function estimateWattage(parts: Record<string, Product>): number {
  let total = 0;
  for (const [slotId, p] of Object.entries(parts)) total += partWattage(slotId, p);
  return total;
}

/** Plain client-side rules over `attributes` — no backend, per decisions.md. */
export function checkCompatibility(parts: Record<string, Product>, estWatts: number, lang: Lang): string[] {
  const issues: string[] = [];
  const cpu = parts.cpu;
  const mobo = parts.motherboard;
  if (cpu && mobo) {
    const cs = cpu.attributes.socket ?? "";
    const ms = mobo.attributes.socket ?? "";
    if (cs && ms && cs !== ms) {
      issues.push(
        lang === "he"
          ? `סוקט המעבד (${cs}) אינו תואם לסוקט לוח האם (${ms})`
          : `CPU socket (${cs}) doesn't match the motherboard socket (${ms})`
      );
    }
  }
  const mem = parts.memory;
  if (mem && mobo) {
    const mt = mem.attributes.memory_type ?? "";
    const mmt = mobo.attributes.memory_type ?? "";
    if (mt && mmt && !mmt.includes(mt)) {
      issues.push(
        lang === "he"
          ? `סוג הזיכרון (${mt}) אינו נתמך על ידי לוח האם (${mmt})`
          : `Memory type (${mt}) isn't supported by the motherboard (${mmt})`
      );
    }
  }
  const psu = parts.psu;
  if (psu && estWatts > 0) {
    const capacity = numAttr(psu, ["wattage", "power", "total_power", "max_power"]);
    if (capacity !== null && capacity < estWatts) {
      issues.push(
        lang === "he"
          ? `הספק (${capacity}W) חלש מהצריכה המשוערת (${estWatts}W)`
          : `The PSU (${capacity}W) can't cover the estimated ${estWatts}W draw`
      );
    }
  }
  return issues;
}