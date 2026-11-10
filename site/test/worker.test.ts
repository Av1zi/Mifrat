import { afterEach, describe, expect, it, vi } from "vitest";
import headersFile from "../public/_headers?raw";
import { isValidListId } from "../src/lists";
import worker from "../worker";

type Env = Parameters<typeof worker.fetch>[1];
type Ctx = Parameters<typeof worker.fetch>[2];
type RateLimiter = NonNullable<Env["LISTS_RATE_LIMITER"]>;

const ORIGIN = "https://mifrat.example";
const HOUR = 60 * 60 * 1000;
const OLD = "2020-01-01T00:00:00.000Z";

interface Row {
  rowid: number;
  id: string;
  build: string;
  build_hash: string;
  created_at: string;
}

interface FakeStatement {
  bind(...values: unknown[]): FakeStatement;
  first<T>(): Promise<T | null>;
  run(): Promise<unknown>;
}

/**
 * In-memory D1 stand-in: records every statement and implements exactly
 * the ones the Worker issues, so unexpected SQL fails the test loudly.
 */
function fakeDb() {
  const rows: Row[] = [];
  const sql: string[] = [];
  const maxRowid = (): number | null =>
    rows.length ? Math.max(...rows.map((r) => r.rowid)) : null;

  function select(query: string, args: unknown[]): unknown {
    if (query === "SELECT id FROM lists WHERE build_hash = ?") {
      const row = rows.find((r) => r.build_hash === args[0]);
      return row ? { id: row.id } : null;
    }
    if (query === "SELECT build FROM lists WHERE id = ?") {
      const row = rows.find((r) => r.id === args[0]);
      return row ? { build: row.build } : null;
    }
    if (query.startsWith("SELECT (SELECT MAX(rowid) FROM lists) AS n")) {
      const n = maxRowid();
      const below = n === null ? [] : rows.filter((r) => r.rowid <= n - (args[0] as number));
      below.sort((a, b) => b.rowid - a.rowid);
      return { n, boundary: below[0]?.created_at ?? null };
    }
    throw new Error(`unexpected SQL: ${query}`);
  }

  function insert(query: string, args: unknown[]): void {
    if (!query.startsWith("INSERT INTO lists (id, build, build_hash, created_at)")) {
      throw new Error(`unexpected SQL: ${query}`);
    }
    const [id, build, build_hash, created_at] = args as string[];
    if (rows.some((r) => r.id === id)) throw new Error("UNIQUE constraint failed: lists.id");
    if (rows.some((r) => r.build_hash === build_hash)) {
      throw new Error("UNIQUE constraint failed: lists.build_hash");
    }
    rows.push({ rowid: (maxRowid() ?? 0) + 1, id, build, build_hash, created_at });
  }

  return {
    rows,
    sql,
    seed(row: Pick<Row, "rowid" | "created_at">): void {
      rows.push({ ...row, id: `seed${row.rowid}`, build: "{}", build_hash: `seed-${row.rowid}` });
    },
    prepare(query: string): FakeStatement {
      sql.push(query);
      let args: unknown[] = [];
      const stmt: FakeStatement = {
        bind(...values: unknown[]) {
          args = values;
          return stmt;
        },
        async first<T>(): Promise<T | null> {
          return select(query, args) as T | null;
        },
        async run(): Promise<unknown> {
          insert(query, args);
          return { success: true };
        },
      };
      return stmt;
    },
  };
}

function setup(limiter?: RateLimiter) {
  const db = fakeDb();
  const assetUrls: string[] = [];
  const pending: Promise<unknown>[] = [];
  const env: Env = {
    LISTS_DB: db,
    ASSETS: {
      async fetch(request: Request) {
        assetUrls.push(request.url);
        return new Response("<!doctype html>", { headers: { "content-type": "text/html" } });
      },
    },
    LISTS_RATE_LIMITER: limiter,
  };
  const ctx: Ctx = { waitUntil: (p) => void pending.push(p) };
  const send = (request: Request) => worker.fetch(request, env, ctx);
  return { db, env, assetUrls, pending, send };
}

// The rate limiter is module-level state: every request gets its own
// address unless a test pins one on purpose.
let ipSeq = 0;
function freshIp(): string {
  ipSeq++;
  return `203.0.${Math.floor(ipSeq / 250)}.${(ipSeq % 250) + 1}`;
}

let buildSeq = 0;
function newBuild(): Record<string, string[]> {
  buildSeq++;
  return { cpu: [`tms:cpu-${buildSeq}`], gpu: [`ksp:gpu.${buildSeq}`] };
}

/** A same-origin browser POST; `null` header values drop a default. */
function post(
  body: BodyInit | null,
  headers: Record<string, string | null> = {},
  init: RequestInit = {}
): Request {
  const merged: Record<string, string | null> = {
    "content-type": "application/json",
    origin: ORIGIN,
    "sec-fetch-site": "same-origin",
    "cf-connecting-ip": freshIp(),
    ...headers,
  };
  const sent = Object.entries(merged).filter((e): e is [string, string] => e[1] !== null);
  return new Request(`${ORIGIN}/api/lists`, {
    method: "POST",
    headers: sent,
    body,
    ...init,
  });
}

const postBuild = (build: unknown, headers: Record<string, string | null> = {}) =>
  post(JSON.stringify(build), headers);

function get(path: string, method = "GET"): Request {
  return new Request(`${ORIGIN}${path}`, { method });
}

async function created(res: Response): Promise<string> {
  expect(res.status).toBe(201);
  const { id } = (await res.json()) as { id: string };
  expect(isValidListId(id)).toBe(true);
  return id;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("POST /api/lists: storage", () => {
  it("stores a build once; a repeat returns the same id with one lookup and no write", async () => {
    const { db, send } = setup();
    const id = await created(await send(postBuild({ cpu: ["tms:1"], gpu: ["a.b-c:9"] })));
    expect(db.rows).toHaveLength(1);

    const before = db.sql.length;
    const again = await send(postBuild({ gpu: ["a.b-c:9", "a.b-c:9"], cpu: ["tms:1"] }));
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ id });
    expect(db.sql.slice(before)).toEqual(["SELECT id FROM lists WHERE build_hash = ?"]);
    expect(db.rows).toHaveLength(1);
  });

  it("never issues a COUNT on the POST path", async () => {
    const { db, send } = setup();
    const build = newBuild();
    await send(postBuild(build));
    await send(postBuild(build));
    await send(postBuild(newBuild()));
    await send(postBuild({ cpu: ["bad/id"] }));
    expect(db.sql.length).toBeGreaterThan(0);
    for (const statement of db.sql) expect(statement.toUpperCase()).not.toContain("COUNT(");
  });

  it("rejects invalid JSON and invalid builds with 400 before touching D1", async () => {
    const { db, send } = setup();
    expect((await send(post("{not json"))).status).toBe(400);
    expect((await send(postBuild({ monitor: ["x"] }))).status).toBe(400);
    expect((await send(postBuild({ cpu: ["a<b"] }))).status).toBe(400);
    expect(db.sql).toEqual([]);
  });
});

describe("POST /api/lists: request checks", () => {
  it("accepts JSON with parameters and any media-type case", async () => {
    const { send } = setup();
    await created(
      await send(postBuild(newBuild(), { "content-type": "application/json; charset=utf-8" }))
    );
    await created(await send(postBuild(newBuild(), { "content-type": "Application/JSON" })));
  });

  it.each([
    ["text/plain", { "content-type": "text/plain;charset=UTF-8" }],
    ["form", { "content-type": "application/x-www-form-urlencoded" }],
    ["missing", { "content-type": null }],
    ["json lookalike", { "content-type": "application/jsonp" }],
  ])("returns 415 for a %s content type", async (_name, headers) => {
    const { db, send } = setup();
    const res = await send(postBuild(newBuild(), headers));
    expect(res.status).toBe(415);
    expect(db.sql).toEqual([]);
  });

  it.each([
    ["Sec-Fetch-Site: cross-site", { "sec-fetch-site": "cross-site" }],
    ["Sec-Fetch-Site: same-site", { "sec-fetch-site": "same-site" }],
    ["a foreign Origin", { origin: "https://evil.example" }],
    ["Origin: null", { origin: "null" }],
    ["a foreign Origin without Sec-Fetch-Site", { "sec-fetch-site": null, origin: "https://x.y" }],
  ])("returns 403 for %s", async (_name, headers) => {
    const { db, send } = setup();
    const res = await send(postBuild(newBuild(), headers));
    expect(res.status).toBe(403);
    expect(db.sql).toEqual([]);
  });

  it("lets clients that send neither Origin nor Sec-Fetch-Site through (curl)", async () => {
    const { send } = setup();
    await created(await send(postBuild(newBuild(), { origin: null, "sec-fetch-site": null })));
  });
});

describe("POST /api/lists: body size", () => {
  it("refuses an oversized Content-Length without reading the body", async () => {
    const { db, send } = setup();
    let pulled = false;
    const stream = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          pulled = true;
          controller.enqueue(new TextEncoder().encode("{}"));
          controller.close();
        },
      },
      { highWaterMark: 0 }
    );
    const req = post(stream, { "content-length": "9000" }, { duplex: "half" } as RequestInit);
    const res = await send(req);
    expect(res.status).toBe(413);
    expect(pulled).toBe(false);
    expect(req.bodyUsed).toBe(false);
    expect(db.sql).toEqual([]);
  });

  it("stops reading a streamed body as soon as it passes the cap", async () => {
    const { db, send } = setup();
    let pulls = 0;
    const chunk = new TextEncoder().encode(" ".repeat(4096));
    const stream = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          pulls++;
          controller.enqueue(chunk);
        },
      },
      { highWaterMark: 0 }
    );
    const res = await send(post(stream, {}, { duplex: "half" } as RequestInit));
    expect(res.status).toBe(413);
    expect(pulls).toBeLessThanOrEqual(4);
    expect(db.sql).toEqual([]);
  });

  it("accepts a body of exactly 8192 bytes and refuses 8193 or an empty one", async () => {
    const { send } = setup();
    const json = JSON.stringify(newBuild());
    await created(await send(post(json.padEnd(8192, " "))));
    expect((await send(post(JSON.stringify(newBuild()).padEnd(8193, " ")))).status).toBe(413);
    expect((await send(post(""))).status).toBe(413);
    expect((await send(post(null))).status).toBe(413);
  });
});

describe("POST /api/lists: growth caps", () => {
  it("at the lifetime cap still returns stored builds but refuses new ones", async () => {
    const { db, send } = setup();
    const build = newBuild();
    const id = await created(await send(postBuild(build)));
    db.rows[0].created_at = OLD;
    db.seed({ rowid: 50000, created_at: OLD });

    const again = await send(postBuild(build));
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ id });

    const before = db.sql.length;
    expect((await send(postBuild(newBuild()))).status).toBe(429);
    expect(db.sql.slice(before).some((s) => s.startsWith("INSERT"))).toBe(false);
  });

  it("lets a new build in one row below the lifetime cap", async () => {
    const { db, send } = setup();
    db.seed({ rowid: 1, created_at: OLD });
    db.seed({ rowid: 49999, created_at: OLD });
    await created(await send(postBuild(newBuild())));
  });

  it("refuses a new build when the 2000th-newest row is under 24 h old", async () => {
    const { db, send } = setup();
    const build = newBuild();
    const id = await created(await send(postBuild(build)));
    db.rows[0].created_at = new Date(Date.now() - HOUR).toISOString();
    db.seed({ rowid: 2000, created_at: new Date().toISOString() });

    expect((await send(postBuild(newBuild()))).status).toBe(429);
    const again = await send(postBuild(build));
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ id });
  });

  it("lets a new build in when the 2000th-newest row is older than 24 h", async () => {
    const { db, send } = setup();
    db.seed({ rowid: 1, created_at: new Date(Date.now() - 25 * HOUR).toISOString() });
    db.seed({ rowid: 2000, created_at: new Date().toISOString() });
    await created(await send(postBuild(newBuild())));
  });

  it("returns the winner's id when an identical build is inserted between lookup and insert", async () => {
    const { db, send } = setup();
    const prepare = db.prepare;
    db.prepare = (query: string): FakeStatement => {
      const stmt = prepare(query);
      if (!query.startsWith("INSERT")) return stmt;
      return {
        ...stmt,
        bind(...values: unknown[]) {
          // A concurrent request stores the same build_hash first.
          const hash = values[2] as string;
          db.rows.push({ rowid: 0, id: "Winner", build: "{}", build_hash: hash, created_at: OLD });
          return stmt.bind(...values);
        },
      };
    };
    const res = await send(postBuild(newBuild()));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ id: "Winner" });
  });
});

describe("POST /api/lists: rate limiting", () => {
  const statusesFrom = async (send: (r: Request) => Promise<Response>, ips: string[]) => {
    const build = newBuild();
    const codes: number[] = [];
    for (const ip of ips) {
      codes.push((await send(postBuild(build, { "cf-connecting-ip": ip }))).status);
    }
    return codes;
  };

  it("buckets IPv6 by /64, however the address is written", async () => {
    const { send } = setup();
    const sameNet = [
      ...Array.from({ length: 17 }, (_, i) => `2001:db8:a:b::${(i + 1).toString(16)}`),
      "2001:0DB8:000A:000B:0000:0000:0000:00ff",
      "2001:db8:a:b:1:2:3:4",
      "2001:db8:a:b:ffff::",
      "2001:db8:a:b:ffff:ffff:ffff:ffff",
    ];
    const codes = await statusesFrom(send, sameNet);
    expect(codes.slice(0, 20).every((c) => c === 200 || c === 201)).toBe(true);
    expect(codes[20]).toBe(429);
    await created(await send(postBuild(newBuild(), { "cf-connecting-ip": "2001:db8:a:c::1" })));
    await created(await send(postBuild(newBuild(), { "cf-connecting-ip": "2001:db8:a::b:0:0" })));
  });

  it("keeps IPv4 on the full address (IPv4-mapped IPv6 counts as the same host)", async () => {
    const { send } = setup();
    const ips = [...Array.from({ length: 20 }, () => "192.0.2.10"), "::ffff:192.0.2.10"];
    const codes = await statusesFrom(send, ips);
    expect(codes.slice(0, 20).every((c) => c === 200 || c === 201)).toBe(true);
    expect(codes[20]).toBe(429);
    await created(await send(postBuild(newBuild(), { "cf-connecting-ip": "192.0.2.11" })));
  });

  it("ignores X-Forwarded-For", async () => {
    const { send } = setup();
    const build = newBuild();
    const codes: number[] = [];
    for (let i = 0; i < 21; i++) {
      const headers = { "cf-connecting-ip": "192.0.2.50", "x-forwarded-for": `10.0.0.${i}` };
      codes.push((await send(postBuild(build, headers))).status);
    }
    expect(codes[20]).toBe(429);
  });

  it("returns 429 when the rate-limit binding says no, keyed like the fallback", async () => {
    const keys: string[] = [];
    const { db, send } = setup({
      async limit({ key }) {
        keys.push(key);
        return { success: false };
      },
    });
    const res = await send(postBuild(newBuild(), { "cf-connecting-ip": "2001:db8:5:6::7" }));
    expect(res.status).toBe(429);
    expect(keys).toEqual(["2001:db8:5:6::/64"]);
    expect(db.sql).toEqual([]);
  });

  it("falls back to the in-memory limiter when the binding throws", async () => {
    const { send } = setup({
      async limit() {
        throw new Error("binding down");
      },
    });
    await created(await send(postBuild(newBuild())));
  });

  it("allows the request when the binding says yes", async () => {
    const { send } = setup({ limit: async () => ({ success: true }) });
    await created(await send(postBuild(newBuild())));
  });
});

describe("GET /api/lists/:id", () => {
  it("returns a stored build as immutable JSON", async () => {
    const { send } = setup();
    const id = await created(await send(postBuild({ gpu: ["g2", "g1"], cpu: ["c"] })));
    const res = await send(get(`/api/lists/${encodeURIComponent(id)}`));
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
    expect(await res.json()).toEqual({ id, build: { cpu: ["c"], gpu: ["g1", "g2"] } });
  });

  it("returns 404 for an unknown id and 400 for malformed ones", async () => {
    const { send } = setup();
    expect((await send(get("/api/lists/AAAAAA"))).status).toBe(404);
    expect((await send(get("/api/lists/%E0%A4%A"))).status).toBe(400);
    expect((await send(get("/api/lists/abc"))).status).toBe(400);
    expect((await send(get("/api/lists/a/bcd"))).status).toBe(400);
  });

  it("serves repeat reads from the edge cache without touching D1", async () => {
    const store = new Map<string, Response>();
    vi.stubGlobal("caches", {
      default: {
        async match(request: Request) {
          return store.get(request.url)?.clone();
        },
        async put(request: Request, response: Response) {
          store.set(request.url, response);
        },
      },
    });
    const { db, pending, send } = setup();
    const id = await created(await send(postBuild(newBuild())));
    const first = await send(get(`/api/lists/${id}?x=1`));
    expect(first.status).toBe(200);
    await Promise.all(pending);
    expect([...store.keys()]).toEqual([`${ORIGIN}/api/lists/${encodeURIComponent(id)}`]);

    const before = db.sql.length;
    const second = await send(get(`/api/lists/${id}`));
    expect(second.status).toBe(200);
    expect(await second.json()).toEqual(await first.json());
    expect(db.sql.length).toBe(before);
  });
});

describe("security headers", () => {
  const staticHeader = (name: string): string => {
    const line = headersFile
      .split(/\r?\n/)
      .find((l) => l.trim().toLowerCase().startsWith(`${name.toLowerCase()}:`));
    if (!line) throw new Error(`${name} missing from public/_headers`);
    return line.slice(line.indexOf(":") + 1).trim();
  };

  const expectSecurityHeaders = (res: Response): void => {
    expect(res.headers.get("content-security-policy")).toBe(
      staticHeader("Content-Security-Policy")
    );
    expect(res.headers.get("strict-transport-security")).toBe(
      staticHeader("Strict-Transport-Security")
    );
    expect(res.headers.get("x-frame-options")).toBe("DENY");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("permissions-policy")).toBe(staticHeader("Permissions-Policy"));
  };

  it("keeps the CSP identical to public/_headers and limits form targets", () => {
    expect(staticHeader("Content-Security-Policy")).toContain("form-action 'self'");
    expect(staticHeader("Strict-Transport-Security")).toBe("max-age=31536000; includeSubDomains");
  });

  it.each([
    ["HEAD /api/lists", "/api/lists", "HEAD", 405],
    ["GET /api/lists", "/api/lists", "GET", 405],
    ["POST /api/lists/:id", "/api/lists/AAAAAA", "POST", 405],
    ["unknown /api path", "/api/other", "GET", 404],
    ["POST /list/:id", "/list/AbC123", "POST", 405],
    ["GET /api/lists/:id (404)", "/api/lists/AAAAAA", "GET", 404],
  ])("are set on %s", async (_name, path, method, status) => {
    const { send } = setup();
    const res = await send(get(path, method));
    expect(res.status).toBe(status);
    expectSecurityHeaders(res);
  });

  it("are set on POST responses, success or refusal", async () => {
    const { send } = setup();
    expectSecurityHeaders(await send(postBuild(newBuild())));
    expectSecurityHeaders(await send(postBuild(newBuild(), { "content-type": "text/plain" })));
  });

  it("are set on the /list/* SPA shell, which is index.html", async () => {
    const { assetUrls, send } = setup();
    const res = await send(get("/list/AbC123"));
    expect(res.status).toBe(200);
    expect(assetUrls).toEqual([`${ORIGIN}/index.html`]);
    expect(res.headers.get("content-type")).toBe("text/html");
    expectSecurityHeaders(res);
  });
});
