import type { Product, SiteMeta } from "./types";

// Same-origin relative paths — works in `vite dev` and in the built site
// alike, because scripts/copy-data.mjs copies data/site/*.json into
// public/data/site/ before both. No backend, no CORS, no GitHub dependency
// at request time.
const DATA_BASE = "/data/site";

let metaPromise: Promise<SiteMeta> | null = null;
const categoryPromises = new Map<string, Promise<Product[]>>();

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`Failed to fetch ${path}: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function loadMeta(): Promise<SiteMeta> {
  if (!metaPromise) {
    metaPromise = fetchJson<SiteMeta>(`${DATA_BASE}/meta.json`);
  }
  return metaPromise;
}

export function loadCategory(category: string): Promise<Product[]> {
  let promise = categoryPromises.get(category);
  if (!promise) {
    promise = fetchJson<Product[]>(`${DATA_BASE}/${category}.json`);
    categoryPromises.set(category, promise);
  }
  return promise;
}
