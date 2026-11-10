/**
 * Mifrat Worker: short permanent build links + static site.
 *
 * - POST /api/lists      store a build -> { id } (6-char /list/<id>)
 * - GET  /api/lists/:id  fetch a stored build -> { id, build }
 * - GET  /list/*          serve index.html so the SPA resolves the short id
 * - everything else       never reaches us (run_worker_first, see
 *                         wrangler.jsonc) — static assets serve directly.
 *
 * Storage: D1 table `lists` (site/migrations/0001_lists.sql). Rows are
 * insert-only — never updated or deleted — so links stay permanent and a
 * fetched build is served as immutable (browser cache, plus the edge Cache
 * API, which only takes effect on a custom domain, not on workers.dev).
 * Identical builds dedupe to one row via the build_hash unique column.
 */

import { BUILD_SLOTS } from "./src/build";
import {
  canonicalizeListBuild,
  generateListId,
  isValidListId,
  sha256Hex,
  validateListBuild,
} from "./src/lists";

// Minimal structural typings for the bindings we use, so this file needs
// no @cloudflare/workers-types dependency. test/worker.test.ts imports this
// module, so `tsc -b` typechecks it against the DOM lib like the client.
interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T>(): Promise<T | null>;
  run(): Promise<unknown>;
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
}

interface AssetBinding {
  fetch(request: Request): Promise<Response>;
}

interface RateLimitBinding {
  limit(options: { key: string }): Promise<{ success: boolean }>;
}

interface EdgeCache {
  match(request: Request): Promise<Response | undefined>;
  put(request: Request, response: Response): Promise<void>;
}

interface WorkerContext {
  waitUntil(promise: Promise<unknown>): void;
}

interface Env {
  LISTS_DB: D1Database;
  ASSETS: AssetBinding;
  LISTS_RATE_LIMITER?: RateLimitBinding;
}

const SLOT_ORDER = BUILD_SLOTS.map((s) => s.id);
const VALID_SLOTS = new Set<string>(SLOT_ORDER);
// Valid builds are pure ASCII (slot names + PRODUCT_ID_RE ids), so this
// byte cap admits every build the old 8192-char cap did.
const MAX_BODY_BYTES = 8192;
const ID_ATTEMPTS = 5;
// Abuse guards, cheapest first: header checks, the LISTS_RATE_LIMITER
// binding (approximate, per Cloudflare location) backed by a per-isolate
// limiter, then O(1) D1 growth caps for genuinely new builds. A zone WAF
// rule can sit in front once a custom domain exists; these checks mean
// one missing dashboard rule never means unbounded D1 growth.
const MAX_ROWS = 50000;
const MAX_NEW_ROWS_PER_DAY = 2000;
const DAY_MS = 24 * 60 * 60 * 1000;
const MAX_POSTS_PER_IP_PER_MIN = 20;
const ipHits = new Map<string, number[]>();

// Insert-only rowid table: MAX(rowid) is the row count, and the row
// MAX_NEW_ROWS_PER_DAY - 1 below it is the Nth-newest. Both are single
// b-tree seeks, unlike COUNT(*), which reads every row.
const GROWTH_SQL =
  "SELECT (SELECT MAX(rowid) FROM lists) AS n, " +
  "(SELECT created_at FROM lists WHERE rowid <= (SELECT MAX(rowid) FROM lists) - ? " +
  "ORDER BY rowid DESC LIMIT 1) AS boundary";

// Parity with the static responses (site/public/_headers does not apply
// to Worker-generated responses): same framing policy and CSP. Keep the
// two in sync when either changes.
const SECURITY_HEADERS: Record<string, string> = {
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), geolocation=(), microphone=()",
  "x-frame-options": "DENY",
  "strict-transport-security": "max-age=31536000; includeSubDomains",
  "content-security-policy":
    "default-src 'self'; img-src 'self' data:; font-src 'self' data:; " +
    "style-src 'self' 'unsafe-inline'; connect-src 'self' " +
    "https://api.frankfurter.dev; script-src 'self'; object-src 'none'; " +
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
};

function clientIp(request: Request): string {
  // Cloudflare sets CF-Connecting-IP at the edge and clients cannot forge
  // it. Never fall back to X-Forwarded-For: that header is client-supplied,
  // so an attacker could rotate it and mint a fresh rate-limit budget per
  // request. If the header is missing we are not behind the Cloudflare edge
  // — bucket that traffic together under "unknown" instead of trusting a
  // spoofable header.
  //
  // NOTE: this module must stay free of Node APIs (process.env, require):
  // the Worker runs without nodejs_compat (see site/wrangler.jsonc).
  return request.headers.get("cf-connecting-ip") ?? "unknown";
}

/** Eight lowercase hex groups without leading zeros, or null if malformed. */
function ipv6Groups(ip: string): string[] | null {
  let addr = ip.toLowerCase();
  const zone = addr.indexOf("%");
  if (zone >= 0) addr = addr.slice(0, zone);
  const lastColon = addr.lastIndexOf(":");
  const tail = addr.slice(lastColon + 1);
  if (tail.includes(".")) {
    const octets = tail.split(".").map((o) => (/^\d{1,3}$/.test(o) ? Number(o) : NaN));
    if (octets.length !== 4 || octets.some((o) => !(o <= 255))) return null;
    addr =
      addr.slice(0, lastColon + 1) +
      ((octets[0] << 8) | octets[1]).toString(16) +
      ":" +
      ((octets[2] << 8) | octets[3]).toString(16);
  }
  const halves = addr.split("::");
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(":") : [];
  const rest = halves.length === 2 && halves[1] ? halves[1].split(":") : [];
  const missing = 8 - head.length - rest.length;
  if (halves.length === 2 ? missing < 1 : missing !== 0) return null;
  const groups = [...head, ...Array<string>(halves.length === 2 ? missing : 0).fill("0"), ...rest];
  if (!groups.every((g) => /^[0-9a-f]{1,4}$/.test(g))) return null;
  return groups.map((g) => parseInt(g, 16).toString(16));
}

/**
 * IPv4 keys on the full address; IPv6 on its /64, since one host can
 * rotate through 2^64 source addresses inside a single /64.
 */
function rateLimitKey(ip: string): string {
  if (!ip.includes(":")) return ip;
  const groups = ipv6Groups(ip);
  if (!groups) return ip.toLowerCase();
  if (groups.slice(0, 5).every((g) => g === "0") && groups[5] === "ffff") {
    // IPv4-mapped (::ffff:a.b.c.d): key like the plain IPv4 address.
    const hi = parseInt(groups[6], 16);
    const lo = parseInt(groups[7], 16);
    return [hi >> 8, hi & 255, lo >> 8, lo & 255].join(".");
  }
  return `${groups.slice(0, 4).join(":")}::/64`;
}

function isRateLimited(key: string, now: number): boolean {
  const windowStart = now - 60_000;
  const hits = (ipHits.get(key) ?? []).filter((t) => t > windowStart);
  hits.push(now);
  ipHits.set(key, hits);
  // Bound memory: drop stale entries opportunistically.
  if (ipHits.size > 5000) {
    for (const [k, v] of ipHits) {
      if (v.length === 0 || v[v.length - 1]! <= windowStart) ipHits.delete(k);
    }
  }
  return hits.length > MAX_POSTS_PER_IP_PER_MIN;
}

async function isOverRateLimit(key: string, env: Env): Promise<boolean> {
  if (isRateLimited(key, Date.now())) return true;
  if (!env.LISTS_RATE_LIMITER) return false;
  try {
    const { success } = await env.LISTS_RATE_LIMITER.limit({ key });
    return success === false;
  } catch {
    // Binding unavailable: the per-isolate limiter above still applied.
    return false;
  }
}

function isJsonContentType(value: string | null): boolean {
  return value !== null && value.split(";")[0].trim().toLowerCase() === "application/json";
}

// Browsers send Sec-Fetch-Site and/or Origin on every POST; clients that
// send neither (curl, scripts) are not a cross-site risk and pass through.
function isCrossSite(request: Request, url: URL): boolean {
  const site = request.headers.get("sec-fetch-site");
  if (site !== null && site !== "same-origin") return true;
  const origin = request.headers.get("origin");
  return origin !== null && origin !== url.origin;
}

/** The body as text, or null once it exceeds `maxBytes` (never buffered whole). */
async function readBodyCapped(request: Request, maxBytes: number): Promise<string | null> {
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      void reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function json(data: unknown, status = 200, cacheImmutable = false): Response {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    ...SECURITY_HEADERS,
  };
  if (cacheImmutable) {
    // Rows are insert-only: a stored build never changes, so a fetched one
    // can be cached at the edge (and in the browser) indefinitely.
    headers["cache-control"] = "public, max-age=31536000, immutable";
  }
  return new Response(JSON.stringify(data), { status, headers });
}

function plain(body: string, status: number): Response {
  return new Response(body, { status, headers: SECURITY_HEADERS });
}

function withSecurityHeaders(res: Response): Response {
  const headers = new Headers(res.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  });
}

function edgeCache(): EdgeCache | undefined {
  return (globalThis as { caches?: { default?: EdgeCache } }).caches?.default;
}

function isUniqueViolation(err: unknown): boolean {
  return (
    err instanceof Error && err.message.includes("UNIQUE constraint failed")
  );
}

function cryptoByte(): () => number {
  const buf = new Uint8Array(1);
  return () => {
    globalThis.crypto.getRandomValues(buf);
    return buf[0];
  };
}

async function handleCreate(request: Request, url: URL, env: Env): Promise<Response> {
  if (!env.LISTS_DB) {
    return json({ error: "storage unavailable" }, 500);
  }

  // Everything up to the body read is header-only, so a cross-site or
  // oversized request costs no rate-limit budget, body bytes or D1 reads.
  if (!isJsonContentType(request.headers.get("content-type"))) {
    return json({ error: "content-type must be application/json" }, 415);
  }
  if (isCrossSite(request, url)) {
    return json({ error: "cross-site request" }, 403);
  }
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (declaredLength > MAX_BODY_BYTES) {
    return json({ error: "bad body size" }, 413);
  }

  if (await isOverRateLimit(rateLimitKey(clientIp(request)), env)) {
    return json({ error: "try again later" }, 429);
  }

  let text: string | null;
  try {
    text = await readBodyCapped(request, MAX_BODY_BYTES);
  } catch {
    return json({ error: "cannot read body" }, 400);
  }
  if (!text) {
    return json({ error: "bad body size" }, 413);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return json({ error: "body must be JSON" }, 400);
  }

  const validated = validateListBuild(parsed, VALID_SLOTS);
  if (!validated.ok) return json({ error: validated.error }, 400);

  const canonical = canonicalizeListBuild(validated.build, SLOT_ORDER);
  const canonicalJson = JSON.stringify(canonical);
  const hash = await sha256Hex(canonicalJson);

  // Dedupe first: a build that already has a link always gets it back,
  // whatever the growth caps below say.
  try {
    const existing = await env.LISTS_DB.prepare(
      "SELECT id FROM lists WHERE build_hash = ?"
    )
      .bind(hash)
      .first<{ id: string }>();
    if (existing) return json({ id: existing.id }, 200);
  } catch {
    return json({ error: "storage unavailable" }, 500);
  }

  // Growth guards for new rows only: insert-only table with no TTL, so
  // refuse past a lifetime ceiling or a 24 h burst rather than filling D1.
  try {
    const growth = await env.LISTS_DB.prepare(GROWTH_SQL)
      .bind(MAX_NEW_ROWS_PER_DAY - 1)
      .first<{ n: number | null; boundary: string | null }>();
    if (growth && typeof growth.n === "number" && growth.n >= MAX_ROWS) {
      return json({ error: "try again later" }, 429);
    }
    if (
      growth &&
      typeof growth.boundary === "string" &&
      Date.parse(growth.boundary) > Date.now() - DAY_MS
    ) {
      return json({ error: "try again later" }, 429);
    }
  } catch {
    return json({ error: "storage unavailable" }, 500);
  }

  const nextByte = cryptoByte();
  const createdAt = new Date().toISOString();
  for (let attempt = 0; attempt < ID_ATTEMPTS; attempt++) {
    const id = generateListId(nextByte);
    try {
      await env.LISTS_DB.prepare(
        "INSERT INTO lists (id, build, build_hash, created_at) VALUES (?, ?, ?, ?)"
      )
        .bind(id, canonicalJson, hash, createdAt)
        .run();
      return json({ id }, 201);
    } catch (err) {
      if (!isUniqueViolation(err)) return json({ error: "storage unavailable" }, 500);
      if (
        err instanceof Error &&
        err.message.includes("lists.build_hash")
      ) {
        // Lost a race with an identical build — return the winner's id.
        try {
          const winner = await env.LISTS_DB.prepare(
            "SELECT id FROM lists WHERE build_hash = ?"
          )
            .bind(hash)
            .first<{ id: string }>();
          if (winner) return json({ id: winner.id }, 200);
        } catch {
          // fall through to generic error below
        }
        return json({ error: "storage unavailable" }, 500);
      }
      // Id collision (or hash race without a readable winner) — retry with
      // a fresh random id.
    }
  }
  return json({ error: "could not allocate id, try again" }, 500);
}

async function handleGet(
  id: string,
  url: URL,
  env: Env,
  ctx: WorkerContext
): Promise<Response> {
  if (!isValidListId(id)) return json({ error: "bad list id" }, 400);
  const cache = edgeCache();
  // Normalised key: query strings and request headers never fork entries.
  const cacheKey = new Request(`${url.origin}/api/lists/${encodeURIComponent(id)}`);
  if (cache) {
    try {
      const hit = await cache.match(cacheKey);
      if (hit) return hit;
    } catch {
      // A cache failure is never fatal: fall through to D1.
    }
  }
  if (!env.LISTS_DB) return json({ error: "storage unavailable" }, 500);
  let res: Response;
  try {
    const row = await env.LISTS_DB.prepare(
      "SELECT build FROM lists WHERE id = ?"
    )
      .bind(id)
      .first<{ build: string }>();
    if (!row) return json({ error: "not found" }, 404);
    res = json({ id, build: JSON.parse(row.build) }, 200, true);
  } catch {
    return json({ error: "storage unavailable" }, 500);
  }
  if (cache) ctx.waitUntil(cache.put(cacheKey, res.clone()).catch(() => {}));
  return res;
}

export default {
  async fetch(request: Request, env: Env, ctx: WorkerContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (path === "/api/lists") {
      if (request.method !== "POST") {
        return json({ error: "method not allowed" }, 405);
      }
      return handleCreate(request, url, env);
    }

    if (path.startsWith("/api/lists/")) {
      if (request.method !== "GET") {
        return json({ error: "method not allowed" }, 405);
      }
      const raw = path.slice("/api/lists/".length);
      if (!raw || raw.includes("/")) return json({ error: "bad list id" }, 400);
      let id: string;
      try {
        id = decodeURIComponent(raw);
      } catch {
        // Malformed percent-encoding (e.g. /api/lists/%E0%A4%A) throws a
        // URIError; an unhandled throw would surface as a 500.
        return json({ error: "bad list id" }, 400);
      }
      return handleGet(id, url, env, ctx);
    }

    // /list/* (single id or anything else under it): serve the SPA shell;
    // the client resolves the id and renders an in-app unknown-link panel
    // for garbage/unknown ids.
    if (path === "/list" || path.startsWith("/list/")) {
      if (request.method !== "GET") {
        return plain("Method not allowed", 405);
      }
      const indexUrl = new URL("/index.html", url.origin);
      const res = await env.ASSETS.fetch(
        new Request(indexUrl.toString(), { headers: request.headers })
      );
      return withSecurityHeaders(res);
    }

    return plain("Not found", 404);
  },
};
