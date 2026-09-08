import type { BuildMap } from "./state";

/**
 * Short permanent build links: https://mifrat.net/list/<id>.
 *
 * A full build (~9 part picks from ~5k products) carries ~110 bits of
 * entropy, so no stateless encoding can squeeze it into <=8 characters —
 * the id is a random key into a server-side table (Cloudflare D1, see
 * site/worker.ts + site/migrations/), exactly like PCPartPicker's 6-char
 * list ids. Opening a link resolves the stored part ids against *today's*
 * catalog (live lookup): unknown ids are pruned, prices stay current.
 *
 * Alphabet: A-Za-z0-9 everywhere, plus !$& in middle positions only.
 * The other requested symbols (# ? %) cannot appear raw in a URL path
 * (# = fragment, ? = query, % = escape) and would force percent-encoding,
 * making links longer — so they are excluded. First/last chars are always
 * alphanumeric. Fixed length 6 (62^2 x 65^4 ~= 6.9e10 ids).
 *
 * This module is shared by the browser client (bundled by Vite) and the
 * Worker (bundled by wrangler/esbuild): no DOM or Node APIs here, only
 * Web-standard globals (fetch, crypto) used through injectable seams so
 * both runtimes — and plain node tests — can use it.
 */

export const LIST_ID_LENGTH = 6;
export const LIST_ID_MIN_LENGTH = 4;
export const LIST_ID_MAX_LENGTH = 8;

/** Usable anywhere in the id, including first/last positions. */
export const LIST_ID_CORE_ALPHABET =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

/** Extra symbols, middle positions only (all URL-path-safe raw chars). */
export const LIST_ID_EXTRA_SYMBOLS = "!$&";

const MID_ALPHABET = LIST_ID_CORE_ALPHABET + LIST_ID_EXTRA_SYMBOLS;

const ID_FORMAT = new RegExp(
  `^[A-Za-z0-9][A-Za-z0-9${escapeRegExp(LIST_ID_EXTRA_SYMBOLS)}]` +
    `{${LIST_ID_MIN_LENGTH - 2},${LIST_ID_MAX_LENGTH - 2}}[A-Za-z0-9]$`
);

function escapeRegExp(s: string): string {
  return s.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
}

/** True for ids this system could have issued (format only, not existence). */
export function isValidListId(id: string): boolean {
  return ID_FORMAT.test(id);
}

/**
 * Random fixed-6-char id. `nextByte` must return a uniform 0-255 int
 * (pass crypto-backed randomness); rejection sampling keeps the draw
 * unbiased across the 62/65-char alphabets.
 */
export function generateListId(nextByte: () => number): string {
  const pick = (alphabet: string): string => {
    const n = alphabet.length;
    const limit = Math.floor(256 / n) * n;
    for (;;) {
      const b = nextByte();
      if (b < limit) return alphabet[b % n];
    }
  };
  let id = pick(LIST_ID_CORE_ALPHABET);
  for (let i = 0; i < LIST_ID_LENGTH - 2; i++) id += pick(MID_ALPHABET);
  return id + pick(LIST_ID_CORE_ALPHABET);
}

// ---------------------------------------------------------------------------
// Validation + canonical form (used by the Worker on POST; the client only
// ever sends builds it already rendered, but validating server-side keeps
// junk/abuse out of the table).
// ---------------------------------------------------------------------------

export const MAX_LIST_SLOTS = 16;
export const MAX_IDS_PER_SLOT = 16;
export const MAX_PRODUCT_ID_LENGTH = 80;

export type ValidateResult =
  | { ok: true; build: BuildMap }
  | { ok: false; error: string };

export function validateListBuild(
  input: unknown,
  validSlots: ReadonlySet<string>
): ValidateResult {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const entries = Object.entries(input as Record<string, unknown>);
  if (entries.length === 0) return { ok: false, error: "build is empty" };
  if (entries.length > MAX_LIST_SLOTS) {
    return { ok: false, error: "too many slots" };
  }
  const build: BuildMap = {};
  for (const [slot, value] of entries) {
    if (!validSlots.has(slot)) return { ok: false, error: `unknown slot: ${slot}` };
    if (!Array.isArray(value) || value.length === 0) {
      return { ok: false, error: `empty slot: ${slot}` };
    }
    if (value.length > MAX_IDS_PER_SLOT) {
      return { ok: false, error: `too many items in slot: ${slot}` };
    }
    const ids: string[] = [];
    for (const id of value) {
      if (typeof id !== "string" || id.length === 0) {
        return { ok: false, error: `bad product id in slot: ${slot}` };
      }
      if (id.length > MAX_PRODUCT_ID_LENGTH) {
        return { ok: false, error: `product id too long in slot: ${slot}` };
      }
      ids.push(id);
    }
    build[slot] = ids;
  }
  return { ok: true, build };
}

/**
 * Deterministic form for storage + dedup: slots in `slotOrder`, ids
 * de-duplicated and sorted (twin-drive order carries no meaning).
 */
export function canonicalizeListBuild(
  build: BuildMap,
  slotOrder: readonly string[]
): BuildMap {
  const out: BuildMap = {};
  for (const slot of slotOrder) {
    const ids = build[slot];
    if (ids && ids.length > 0) out[slot] = [...new Set(ids)].sort();
  }
  // Slots outside the known order (shouldn't happen post-validation, but
  // belt-and-braces for forward compatibility) come last, sorted by name.
  for (const slot of Object.keys(build).sort()) {
    if (!(slot in out) && build[slot].length > 0) {
      out[slot] = [...new Set(build[slot])].sort();
    }
  }
  return out;
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text)
  );
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ---------------------------------------------------------------------------
// Browser API client (same-origin; falls back to long URLs when the Worker
// is absent, e.g. `vite dev` without `wrangler dev`, or offline).
// ---------------------------------------------------------------------------

export class ListNotFoundError extends Error {
  constructor(id: string) {
    super(`list not found: ${id}`);
    this.name = "ListNotFoundError";
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: unknown };
    if (typeof body.error === "string" && body.error) return body.error;
  } catch {
    // non-JSON error body — fall through to status text
  }
  return res.statusText || `HTTP ${res.status}`;
}

/** POST the build, resolve with the short id (deduped server-side). */
export async function createListLink(build: BuildMap): Promise<string> {
  const res = await fetch("/api/lists", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(build),
  });
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as { id?: unknown };
  if (typeof body.id !== "string" || !isValidListId(body.id)) {
    throw new Error("bad list id from server");
  }
  return body.id;
}

/** GET the stored build for a short id. Throws ListNotFoundError on 404. */
export async function fetchListBuild(id: string): Promise<BuildMap> {
  const res = await fetch(`/api/lists/${encodeURIComponent(id)}`);
  if (res.status === 404) throw new ListNotFoundError(id);
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as { build?: unknown };
  if (!body || typeof body.build !== "object" || body.build === null) {
    throw new Error("bad list payload from server");
  }
  const build: BuildMap = {};
  for (const [slot, value] of Object.entries(
    body.build as Record<string, unknown>
  )) {
    if (Array.isArray(value)) {
      const ids = value.filter(
        (v): v is string => typeof v === "string" && v.length > 0
      );
      if (ids.length > 0) build[slot] = ids;
    }
  }
  return build;
}

/** Absolute short URL for display/copy, e.g. https://mifrat.net/list/aB3!xQ9 */
export function listUrl(id: string): string {
  return `${location.origin}/list/${id}`;
}
