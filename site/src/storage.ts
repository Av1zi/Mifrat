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
  return typeof v.id === "string" && v.id !== "" && typeof v.category === "string" && typeof v.name === "string";
}

const CHANGE_EVENT = "mifrat:storage";

// Storage can be missing (private windows, blocked site data) or throw on
// write (quota). The memory map keeps the features working for the session.
const memory = new Map<string, string>();

export function readJson<T>(key: string, fallback: T): T {
  let raw: string | null = memory.get(key) ?? null;
  if (raw === null) {
    try {
      raw = localStorage.getItem(key);
    } catch {
      raw = null;
    }
  }
  if (raw === null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  const raw = JSON.stringify(value);
  memory.set(key, raw);
  try {
    localStorage.setItem(key, raw);
  } catch {
    // memory copy above still serves this session
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Fires after any write here, and when another tab writes. Returns an unsubscribe. */
export function onStoreChange(listener: () => void): () => void {
  const onStorage = (e: StorageEvent): void => {
    if (e.key === null || e.key.startsWith("mifrat:")) {
      memory.delete(e.key ?? "");
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
