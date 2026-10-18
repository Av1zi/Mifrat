import { isPartRef, onStoreChange, readJson, writeJson, type PartRef } from "./storage";

const SAVED_KEY = "mifrat:saved";

export type SavedPart = PartRef & { savedAt: number };

/** Newest first. */
export function getSaved(): SavedPart[] {
  const raw = readJson<unknown>(SAVED_KEY, []);
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(isPartRef)
    .map((p) => ({ ...p, savedAt: Number((p as { savedAt?: unknown }).savedAt) || 0 }))
    .sort((a, b) => b.savedAt - a.savedAt);
}

export function savedCount(): number {
  return getSaved().length;
}

export function isSaved(id: string): boolean {
  return getSaved().some((p) => p.id === id);
}

/** Returns true when the part is now saved. */
export function toggleSaved(part: PartRef): boolean {
  const list = getSaved();
  if (list.some((p) => p.id === part.id)) {
    writeJson(SAVED_KEY, list.filter((p) => p.id !== part.id));
    return false;
  }
  writeJson(SAVED_KEY, [{ ...part, savedAt: Date.now() }, ...list]);
  return true;
}

export function removeSaved(id: string): void {
  writeJson(SAVED_KEY, getSaved().filter((p) => p.id !== id));
}

export const onSavedChange = onStoreChange;
