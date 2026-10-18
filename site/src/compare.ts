import { isPartRef, onStoreChange, readJson, writeJson, type PartRef } from "./storage";

const COMPARE_KEY = "mifrat:compare";

/** Product pages compare like with like, and four columns is what fits a phone. */
export const COMPARE_MAX = 4;

export interface CompareList {
  category: string | null;
  items: PartRef[];
}

export function getCompare(): CompareList {
  const raw = readJson<unknown>(COMPARE_KEY, null);
  if (!raw || typeof raw !== "object") return { category: null, items: [] };
  const list = raw as { category?: unknown; items?: unknown };
  const items = Array.isArray(list.items) ? list.items.filter(isPartRef) : [];
  const category = typeof list.category === "string" && items.length > 0 ? list.category : null;
  return { category, items: items.filter((p) => p.category === category).slice(0, COMPARE_MAX) };
}

export function isCompared(id: string): boolean {
  return getCompare().items.some((p) => p.id === id);
}

export type CompareResult = "added" | "removed" | "full" | "switched";

/**
 * Adds or removes a part. Adding a part of another category starts a fresh
 * list ("switched"): a comparison across categories has no shared spec rows.
 */
export function toggleCompare(part: PartRef): CompareResult {
  const list = getCompare();
  if (list.items.some((p) => p.id === part.id)) {
    removeCompare(part.id);
    return "removed";
  }
  if (list.category !== null && list.category !== part.category) {
    writeJson(COMPARE_KEY, { category: part.category, items: [part] });
    return "switched";
  }
  if (list.items.length >= COMPARE_MAX) return "full";
  writeJson(COMPARE_KEY, { category: part.category, items: [...list.items, part] });
  return "added";
}

export function removeCompare(id: string): void {
  const list = getCompare();
  const items = list.items.filter((p) => p.id !== id);
  writeJson(COMPARE_KEY, { category: items.length > 0 ? list.category : null, items });
}

export function clearCompare(): void {
  writeJson(COMPARE_KEY, { category: null, items: [] });
}

export const onCompareChange = onStoreChange;
