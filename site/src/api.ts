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

    // A transient failure (offline, a slow deploy mid-fetch) would
    // otherwise cache the *rejected* promise forever — every future call
    // for this category would keep re-throwing the same stale error for
    // the rest of the session, even once the network recovers. Evict on
    // failure so the next call retries instead.
    promise.catch(() => {
      if (categoryPromises.get(category) === promise) {
        categoryPromises.delete(category);
      }
    });
  }
  return promise;
}
