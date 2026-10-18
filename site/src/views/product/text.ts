import type { SpecValue } from "../../types";

/** Schema fields with no discriminating power for similarity scoring. */
export const NOISE_KEYS = new Set(["manufacturer", "model", "part_numbers", "packaging"]);

/** Lang-independent text form of a typed spec value (for comparisons). */
export function rawText(value: SpecValue | undefined): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function normEcho(s: string): string {
  return s.toLowerCase().replace(/[\s\-–—_.,:;'"()[\]|/\\+*#]+/g, "");
}

/**
 * Echo guard: scraped descriptions and "SKUs" often just repeat the title.
 * Containment alone is too eager (a short title would hide a description
 * with real information), so it only counts when the sizes are close.
 */
export function makeEchoOf(name: string): (s: string) => boolean {
  const nameNorm = normEcho(name);
  return (s: string): boolean => {
    const n = normEcho(s);
    if (n === "") return false;
    if (n === nameNorm) return true;
    if (!nameNorm.includes(n) && !n.includes(nameNorm)) return false;
    const shorter = Math.min(n.length, nameNorm.length);
    const longer = Math.max(n.length, nameNorm.length);
    return longer > 0 && shorter / longer >= 0.6;
  };
}
