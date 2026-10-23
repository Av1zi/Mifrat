import type { BuildMap } from "./state";
import { onStoreChange, readJson, writeJson } from "./storage";

const BUILDS_KEY = "mifrat:builds";

/** Parts lists kept on this device (Saved page), like saved parts: localStorage only. */
export interface SavedBuild {
  id: string;
  /** User-chosen name; empty means "name it after the CPU". */
  name: string;
  build: BuildMap;
  savedAt: number;
}

function isBuildMap(value: unknown): value is BuildMap {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.values(value as Record<string, unknown>).every(
    (ids) => Array.isArray(ids) && ids.every((id) => typeof id === "string")
  );
}

/** Newest first. */
export function getSavedBuilds(): SavedBuild[] {
  const raw = readJson<unknown>(BUILDS_KEY, []);
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((b): b is SavedBuild => {
      const v = b as Partial<SavedBuild> | null;
      return !!v && typeof v.id === "string" && isBuildMap(v.build);
    })
    .map((b) => ({ ...b, name: typeof b.name === "string" ? b.name : "", savedAt: Number(b.savedAt) || 0 }))
    .sort((a, b) => b.savedAt - a.savedAt);
}

/** Same parts, any order: the key that tells "already saved" apart. */
export function buildKey(build: BuildMap): string {
  return Object.keys(build)
    .sort()
    .map((slot) => `${slot}=${[...build[slot]].sort().join(",")}`)
    .join("&");
}

export function findSavedBuild(build: BuildMap): SavedBuild | undefined {
  const key = buildKey(build);
  return getSavedBuilds().find((b) => buildKey(b.build) === key);
}

/** Saves a copy (no-op when the same parts are already saved); returns the entry. */
export function saveBuild(build: BuildMap, name = ""): SavedBuild {
  const existing = findSavedBuild(build);
  if (existing) return existing;
  const entry: SavedBuild = {
    id: `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    name: name.trim().slice(0, 60),
    build: structuredClone(build),
    savedAt: Date.now(),
  };
  writeJson(BUILDS_KEY, [entry, ...getSavedBuilds()]);
  return entry;
}

export function renameSavedBuild(id: string, name: string): void {
  writeJson(
    BUILDS_KEY,
    getSavedBuilds().map((b) => (b.id === id ? { ...b, name: name.trim().slice(0, 60) } : b))
  );
}

export function removeSavedBuild(id: string): void {
  writeJson(BUILDS_KEY, getSavedBuilds().filter((b) => b.id !== id));
}

/** A second, independent copy (named "<name> (2)" style by the caller). */
export function duplicateSavedBuild(id: string, name: string): void {
  const source = getSavedBuilds().find((b) => b.id === id);
  if (!source) return;
  const copy: SavedBuild = {
    id: `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    name: name.trim().slice(0, 60),
    build: structuredClone(source.build),
    savedAt: Date.now(),
  };
  writeJson(BUILDS_KEY, [copy, ...getSavedBuilds()]);
}

export const onSavedBuildsChange = onStoreChange;
