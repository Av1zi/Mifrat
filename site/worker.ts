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
 * insert-only — never updated or deleted — so GETs are edge-cacheable as
 * immutable and links stay permanent. Identical builds dedupe to one row
 * via the build_hash unique column.
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
// no @cloudflare/workers-types dependency (and tsconfig `include: [src]`
// keeps `tsc -b` for the client build unaffected by this file).
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

interface Env {
  LISTS_DB: D1Database;
  ASSETS: AssetBinding;
}

const SLOT_ORDER = BUILD_SLOTS.map((s) => s.id);
const VALID_SLOTS = new Set<string>(SLOT_ORDER);
const MAX_BODY_CHARS = 8192;
const ID_ATTEMPTS = 5;

function json(data: unknown, status = 200, cacheImmutable = false): Response {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (cacheImmutable) {
    // Rows are insert-only: a stored build never changes, so a fetched one
    // can be cached at the edge (and in the browser) indefinitely.
    headers["cache-control"] = "public, max-age=31536000, immutable";
  }
  return new Response(JSON.stringify(data), { status, headers });
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

async function handleCreate(request: Request, env: Env): Promise<Response> {
  if (!env.LISTS_DB) {
    return json({ error: "storage unavailable" }, 500);
  }

  let text: string;
  try {
    text = await request.text();
  } catch {
    return json({ error: "cannot read body" }, 400);
  }
  if (text.length === 0 || text.length > MAX_BODY_CHARS) {
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

async function handleGet(id: string, env: Env): Promise<Response> {
  if (!isValidListId(id)) return json({ error: "bad list id" }, 400);
  if (!env.LISTS_DB) return json({ error: "storage unavailable" }, 500);
  try {
    const row = await env.LISTS_DB.prepare(
      "SELECT build FROM lists WHERE id = ?"
    )
      .bind(id)
      .first<{ build: string }>();
    if (!row) return json({ error: "not found" }, 404);
    return json({ id, build: JSON.parse(row.build) }, 200, true);
  } catch {
    return json({ error: "storage unavailable" }, 500);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (path === "/api/lists") {
      if (request.method !== "POST") {
        return json({ error: "method not allowed" }, 405);
      }
      return handleCreate(request, env);
    }

    if (path.startsWith("/api/lists/")) {
      if (request.method !== "GET") {
        return json({ error: "method not allowed" }, 405);
      }
      const raw = path.slice("/api/lists/".length);
      if (!raw || raw.includes("/")) return json({ error: "bad list id" }, 400);
      return handleGet(decodeURIComponent(raw), env);
    }

    // /list/* (single id or anything else under it): serve the SPA shell;
    // the client resolves the id and renders an in-app unknown-link panel
    // for garbage/unknown ids.
    if (path === "/list" || path.startsWith("/list/")) {
      if (request.method !== "GET") {
        return new Response("Method not allowed", { status: 405 });
      }
      const indexUrl = new URL("/index.html", url.origin);
      return env.ASSETS.fetch(
        new Request(indexUrl.toString(), { headers: request.headers })
      );
    }

    return new Response("Not found", { status: 404 });
  },
};
