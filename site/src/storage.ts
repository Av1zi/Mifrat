import type { Product } from "./types";

/**
 * A product reduced to what the compare tray and the saved list need to
 * draw themselves without fetching a category file.
 */
export interface PartRef {
  id: string;
  category: string;
  name: string;
  brand: string | null;
  thumb: string | null;
}

export function partRef(p: Product, name: string): PartRef {
  return {
    id: p.id,
    category: p.category,
    name,
    brand: p.brand,
    thumb: p.thumb ?? p.image ?? null,
  };
}

/** Narrowing guard for entries read back from storage (it may hold anything). */
export function isPartRef(value: unknown): value is PartRef {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  const optionalText = (x: unknown): boolean => x == null || typeof x === "string";
  return (
    typeof v.id === "string" &&
    v.id !== "" &&
    typeof v.category === "string" &&
    typeof v.name === "string" &&
    optionalText(v.brand) &&
    optionalText(v.thumb)
  );
}

const CHANGE_EVENT = "mifrat:storage";

// Storage can be missing (private windows, blocked site data) or throw on
// write (quota). A failed write is kept in memory so the features keep
// working for the session; every other read goes to storage, so other tabs'
// writes stay visible.
const memory = new Map<string, string>();

/** localStorage.getItem that never throws. */
export function readItem(key: string): string | null {
  const kept = memory.get(key);
  if (kept !== undefined) return kept;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** localStorage.setItem that never throws. */
export function writeItem(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
    memory.delete(key);
  } catch {
    memory.set(key, value);
  }
}

export function readJson<T>(key: string, fallback: T): T {
  const raw = readItem(key);
  if (raw === null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  writeItem(key, JSON.stringify(value));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Fires after any write here, and when another tab writes. Returns an unsubscribe. */
export function onStoreChange(listener: () => void): () => void {
  const onStorage = (e: StorageEvent): void => {
    if (e.key === null || e.key.startsWith("mifrat:")) {
      if (e.key === null) memory.clear();
      else memory.delete(e.key);
      listener();
    }
  };
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", onStorage);
  };
}
