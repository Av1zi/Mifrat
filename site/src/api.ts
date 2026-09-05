import type { PriceHistoryFile, Product, SiteMeta } from "./types";

// Same-origin relative paths — works in `vite dev` and in the built site
// alike, because scripts/copy-data.mjs copies data/site/*.json into
// public/data/site/ before both. No backend, no CORS, no GitHub dependency
// at request time.
const DATA_BASE = "/data/site";

// fetch() has no built-in timeout: on a stalled connection the promise
// pends forever and the page sits on its loading state. Bound every
// request so a stuck network becomes an error with a retry instead.
const FETCH_TIMEOUT_MS = 20000;

async function fetchJson<T>(path: string): Promise<T> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(path, { signal: ctrl.signal });
    if (!res.ok) {
      throw new Error(`Failed to fetch ${path}: ${res.status}`);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`Timed out fetching ${path}`);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

let metaPromise: Promise<SiteMeta> | null = null;
const categoryPromises = new Map<string, Promise<Product[]>>();
const historyPromises = new Map<string, Promise<PriceHistoryFile | null>>();

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

/**
 * Per-category price history (data/site/history/<category>.json).
 * Resolves null when the file is absent (fresh category, old deploy) so
 * the product page simply hides the chart instead of erroring.
 */
export function loadHistory(category: string): Promise<PriceHistoryFile | null> {
  const cached = historyPromises.get(category);
  if (cached) return cached;
  // Absence is sticky-ish but not forever: only successful loads are
  // cached, so a deploy that publishes history later is picked up, and a
  // transient failure retries on the next product page instead of hiding
  // the chart for the whole session.
  const promise = fetchJson<PriceHistoryFile>(
    `${DATA_BASE}/history/${category}.json`
  )
    .then((file) => {
      historyPromises.set(category, Promise.resolve(file));
      return file;
    })
    .catch(() => null);
  return promise;
}
