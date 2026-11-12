import { describe, expect, it } from "vitest";
import {
  handleAdmin,
  handleAdminPage,
  handleEvent,
  isQuietHour,
  push,
  recordAbuse,
  resetRebuildCooldown,
  runCron,
  takeAbuseHits,
  type OpsEnv,
} from "../ops-worker";
import type { OpsCrawl, OpsStatus } from "../src/ops/types";
import worker from "../worker";

// ---- fakes -----------------------------------------------------------------

interface AlertRow {
  key: string;
  severity: string;
  title: string;
  detail: string;
  opened_at: string;
  last_push: string | null;
  closed_at: string | null;
}

/** In-memory D1 implementing exactly the statements ops-worker issues. */
function fakeDb() {
  const alerts = new Map<string, AlertRow>();
  const runs: { id: number; vendor: string; at: string; ok: number; outcome: string; detail: string | null; items: number | null }[] = [];
  const meta = new Map<string, string>();
  const sql: string[] = [];

  function exec(query: string, args: unknown[]): { first?: unknown; all?: unknown[] } {
    if (query.startsWith("SELECT key, severity, title, detail, opened_at, last_push, closed_at FROM ops_alerts WHERE closed_at IS NULL")) {
      return { all: [...alerts.values()].filter((a) => a.closed_at === null) };
    }
    if (query.startsWith("INSERT INTO ops_alerts")) {
      const [key, severity, title, detail, opened_at, last_push] = args as string[];
      alerts.set(key, { key, severity, title, detail, opened_at, last_push: last_push ?? null, closed_at: null });
      return {};
    }
    if (query.startsWith("UPDATE ops_alerts SET last_push")) {
      const [at, severity, title, detail, key] = args as string[];
      Object.assign(alerts.get(key)!, { last_push: at, severity, title, detail });
      return {};
    }
    if (query.startsWith("UPDATE ops_alerts SET closed_at")) {
      const [at, key] = args as string[];
      alerts.get(key)!.closed_at = at;
      return {};
    }
    if (query.startsWith("SELECT vendor, at, ok, outcome, detail FROM ops_runs WHERE id IN")) {
      const latest = new Map<string, (typeof runs)[number]>();
      for (const r of runs) latest.set(r.vendor, r);
      return { all: [...latest.values()] };
    }
    if (query.startsWith("INSERT INTO ops_runs")) {
      const [vendor, at, ok, outcome, detail, items] = args as [string, string, number, string, string | null, number | null];
      runs.push({ id: runs.length + 1, vendor, at, ok, outcome, detail, items });
      return {};
    }
    if (query.startsWith("DELETE FROM ops_runs WHERE at < ?")) {
      const cutoff = args[0] as string;
      for (let i = runs.length - 1; i >= 0; i--) if (runs[i].at < cutoff) runs.splice(i, 1);
      return {};
    }
    if (query === "SELECT value FROM ops_meta WHERE name = 'daily_report'") {
      const value = meta.get("daily_report");
      return { first: value === undefined ? null : { value } };
    }
    if (query.startsWith("INSERT INTO ops_meta")) {
      meta.set("daily_report", args[0] as string);
      return {};
    }
    if (query.startsWith("SELECT vendor, at, ok, outcome, detail, items FROM ops_runs ORDER BY")) {
      return { all: [...runs].reverse() };
    }
    if (query.startsWith("SELECT key, severity, title, detail, opened_at, last_push, closed_at FROM ops_alerts ORDER BY")) {
      return { all: [...alerts.values()] };
    }
    throw new Error(`unexpected SQL: ${query}`);
  }

  return {
    alerts,
    runs,
    meta,
    sql,
    prepare(query: string) {
      sql.push(query);
      let args: unknown[] = [];
      const stmt = {
        bind(...values: unknown[]) {
          args = values;
          return stmt;
        },
        async first<T>() {
          return (exec(query, args).first ?? null) as T | null;
        },
        async run() {
          exec(query, args);
          return { success: true };
        },
        async all<T>() {
          return { results: (exec(query, args).all ?? []) as T[] };
        },
      };
      return stmt;
    },
  };
}

function crawl(vendor: string, start: string, extra: Partial<OpsCrawl> = {}): OpsCrawl {
  return {
    vendor, file_day: start.slice(0, 10), start, end: start, rows: 2000, keys: 2000,
    crawls_in_file: 1, misfiled: false, outside_window: false, suspect: null, baseline: false,
    onboarding: false, new: 1, missing: 0, gone: 0, returned: 0, price_changes: 0, ...extra,
  };
}

function healthyStatus(overrides: Partial<Record<string, OpsCrawl[]>> = {}): OpsStatus {
  return {
    schema: 1,
    generated_at: "2026-11-12T05:30:00+00:00",
    window_days: 60,
    vendors: [
      { id: "tms", label: "TMS", host: "home", active: true, min_rows: 1800, due_utc: "04:00", dropped: null },
      { id: "ivory", label: "Ivory", host: "cloud", active: true, min_rows: 500, due_utc: "06:00", dropped: null },
    ],
    first_snapshot: {},
    crawls: {
      tms: [crawl("tms", "2026-11-11T21:40:00+00:00")],
      ivory: [crawl("ivory", "2026-11-12T02:10:00+00:00", { keys: 620 })],
      ...overrides,
    } as Record<string, OpsCrawl[]>,
    catalog: {
      generated_at: "2026-11-12T05:25:00+00:00", products: 4396, listings: 7075, skipped_vendors: [],
      review_queue: 0, vendors: {}, categories: {}, qa: {}, spec_counts: {},
    },
  };
}

interface Sent {
  url: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}

function setup(status: OpsStatus | null = healthyStatus(), opts: { siteOk?: boolean } = {}) {
  const db = fakeDb();
  const pushes: Sent[] = [];
  const pings: string[] = [];
  let currentStatus = status;
  const env: OpsEnv = {
    LISTS_DB: db,
    NTFY_TOPIC_URL: "https://ntfy.sh/mifrat-test-topic-0123456789",
    NTFY_TOKEN: "tk_test",
    OPS_INGEST_TOKEN: "nano-secret-token",
    HEALTHCHECK_URL: "https://hc-ping.example/abc",
    ASSETS: {
      async fetch(request: Request) {
        if (new URL(request.url).pathname === "/admin/data/status.json" && currentStatus) {
          return new Response(JSON.stringify(currentStatus));
        }
        return new Response("not found", { status: 404 });
      },
    },
  };
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "https://ntfy.sh/") {
      pushes.push({
        url,
        headers: Object.fromEntries(new Headers(init?.headers).entries()),
        body: JSON.parse(String(init?.body)),
      });
      return new Response("{}", { status: 200 });
    }
    if (url.endsWith("/data/site/meta.json")) {
      if (opts.siteOk === false) return new Response("down", { status: 503 });
      return new Response(JSON.stringify({ generated_at: "2026-11-12T05:25:00+00:00" }));
    }
    if (url === "https://hc-ping.example/abc") {
      pings.push(String(init?.body));
      return new Response("OK");
    }
    throw new Error(`unexpected fetch ${url}`);
  }) as typeof fetch;
  return {
    db, env, pushes, pings, fetcher,
    setStatus(s: OpsStatus | null) {
      currentStatus = s;
    },
    cron(at: string) {
      return runCron(env, new Date(at), fetcher);
    },
  };
}

// 2026-11-12 is winter time (UTC+2): 08:00 UTC = 10:00 Israel.
const TEN_AM = "2026-11-12T08:00:00Z";

describe("ops cron: daily report", () => {
  it("sends once at 10:00 Israel, silent when all OK, and pings the heartbeat", async () => {
    const t = setup();
    const first = await t.cron(TEN_AM);
    expect(first.report?.priority).toBe(2);
    expect(t.pushes).toHaveLength(1);
    expect(t.pushes[0].body).toMatchObject({ topic: "mifrat-test-topic-0123456789", priority: 2 });
    expect(t.pushes[0].headers.authorization).toBe("Bearer tk_test");
    expect(String(t.pushes[0].body.click)).toBe("https://mifrat.avizi.workers.dev/admin/");
    expect(t.pings).toEqual(["2026-11-12"]);

    // The 10:30 tick (same Israel date) does not repeat it.
    await t.cron("2026-11-12T08:30:00Z");
    expect(t.pushes).toHaveLength(1);
  });

  it("does not send outside 10:xx Israel time", async () => {
    const t = setup();
    await t.cron("2026-11-12T07:30:00Z"); // 09:30 Israel
    await t.cron("2026-11-12T09:00:00Z"); // 11:00 Israel
    expect(t.pushes).toHaveLength(0);
  });

  it("summer time: 07:00 UTC is 10:00 Israel", async () => {
    const summer = healthyStatus({
      tms: [crawl("tms", "2026-07-11T21:40:00+00:00")],
      ivory: [crawl("ivory", "2026-07-12T02:10:00+00:00", { keys: 620 })],
    });
    summer.generated_at = "2026-07-12T05:30:00+00:00";
    summer.catalog.generated_at = "2026-07-12T05:25:00+00:00";
    const t = setup(summer);
    await t.cron("2026-07-12T06:30:00Z"); // 09:30 Israel
    expect(t.pushes).toHaveLength(0);
    const r = await t.cron("2026-07-12T07:00:00Z");
    expect(r.report).not.toBeNull();
  });

  it("a missing scrape makes the report buzz (priority 3)", async () => {
    const t = setup(healthyStatus({ ivory: [crawl("ivory", "2026-11-09T02:10:00+00:00", { keys: 620 })] }));
    const r = await t.cron(TEN_AM);
    expect(r.report?.priority).toBe(3);
    expect(String(r.report?.message)).toContain("❌ Ivory");
  });
});

describe("ops cron: alerts", () => {
  const missingIvory = () =>
    healthyStatus({ ivory: [crawl("ivory", "2026-11-09T02:10:00+00:00", { keys: 620 })] });

  it("opens an alert once, reminds after 24h, resolves when fixed", async () => {
    const t = setup(missingIvory());
    await t.cron("2026-11-12T07:00:00Z"); // 09:00 Israel, not quiet
    const opened = t.pushes.filter((p) => String(p.body.title).includes("Ivory was not scraped"));
    expect(opened).toHaveLength(1);
    expect(opened[0].body.priority).toBe(4);

    await t.cron("2026-11-12T07:30:00Z");
    expect(t.pushes.filter((p) => String(p.body.title).includes("Ivory"))).toHaveLength(1);

    await t.cron("2026-11-13T07:00:00Z");
    expect(t.pushes.map((p) => p.body.title)).toContain("Still open: Ivory was not scraped last night");

    expect(t.db.alerts.get("missing:ivory")!.closed_at).toBeNull();
    // Ivory scraped again; the report was rebuilt today.
    const fresh = healthyStatus({ ivory: [crawl("ivory", "2026-11-14T02:10:00+00:00", { keys: 620 })],
      tms: [crawl("tms", "2026-11-13T21:40:00+00:00")] });
    fresh.generated_at = "2026-11-14T05:30:00+00:00";
    t.setStatus(fresh);
    await t.cron("2026-11-14T07:00:00Z");
    expect(t.pushes.map((p) => p.body.title)).toContain("Resolved: Ivory was not scraped last night");
    expect(t.db.alerts.get("missing:ivory")!.closed_at).not.toBeNull();
  });

  it("quiet hours hold non-urgent alerts, urgent ones push", async () => {
    expect(isQuietHour(new Date("2026-11-12T22:00:00Z"))).toBe(true); // 00:00 Israel
    expect(isQuietHour(new Date("2026-11-12T08:00:00Z"))).toBe(false);
    const t = setup(missingIvory(), { siteOk: false });
    await t.cron("2026-11-12T01:00:00Z"); // 03:00 Israel
    const titles = t.pushes.map((p) => String(p.body.title));
    expect(titles).toEqual(["Site is down"]);
    expect(t.pushes[0].body.priority).toBe(5);
    // The held alert goes out on the first tick after quiet hours.
    await t.cron("2026-11-12T05:30:00Z"); // 07:30 Israel
    expect(t.pushes.map((p) => String(p.body.title))).toContain("Ivory was not scraped last night");
  });

  it("an API flood is urgent", async () => {
    const t = setup();
    takeAbuseHits();
    for (let i = 0; i < 300; i++) recordAbuse();
    await t.cron("2026-11-12T12:00:00Z");
    expect(t.pushes.map((p) => p.body.title)).toContain("API flood (possible attack)");
    expect(takeAbuseHits()).toBe(0);
  });

  it("no status file on the site is itself an alert", async () => {
    const t = setup(null);
    const r = await t.cron("2026-11-12T12:00:00Z");
    expect(r.findings.map((f) => f.key)).toEqual(["report-missing"]);
    expect(r.report).toBeNull();
  });

  it("sends nothing without an ntfy topic, and refuses a non-https one", async () => {
    const t = setup(missingIvory());
    t.env.NTFY_TOPIC_URL = undefined;
    await t.cron("2026-11-12T07:00:00Z");
    expect(t.pushes).toHaveLength(0);
    expect(await push({ ...t.env, NTFY_TOPIC_URL: "http://ntfy.sh/x" }, { title: "t", message: "m", priority: 3, tags: [], click: "/" }, t.fetcher)).toBe(false);
    expect(await push({ ...t.env, NTFY_TOPIC_URL: "https://ntfy.sh/a/b" }, { title: "t", message: "m", priority: 3, tags: [], click: "/" }, t.fetcher)).toBe(false);
  });
});

describe("POST /api/ops/event", () => {
  const event = (body: unknown, token = "nano-secret-token") =>
    new Request("https://mifrat.example/api/ops/event", {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify(body),
    });

  it("needs the bearer token", async () => {
    const t = setup();
    expect((await handleEvent(event({ vendor: "tms", outcome: "ok" }, "wrong"), t.env, new Date(), t.fetcher)).status).toBe(401);
    expect((await handleEvent(event({ vendor: "tms", outcome: "ok" }, ""), t.env, new Date(), t.fetcher)).status).toBe(401);
    const noToken = { ...t.env, OPS_INGEST_TOKEN: undefined };
    expect((await handleEvent(event({ vendor: "tms", outcome: "ok" }), noToken, new Date(), t.fetcher)).status).toBe(401);
    expect(t.db.runs).toHaveLength(0);
  });

  it("validates vendor and outcome", async () => {
    const t = setup();
    expect((await handleEvent(event({ vendor: "TMS!", outcome: "ok" }), t.env, new Date(), t.fetcher)).status).toBe(400);
    expect((await handleEvent(event({ vendor: "tms", outcome: "exploded" }), t.env, new Date(), t.fetcher)).status).toBe(400);
    const big = event({ vendor: "tms", outcome: "failed", detail: "x".repeat(5000) });
    expect((await handleEvent(big, t.env, new Date(), t.fetcher)).status).toBe(413);
  });

  it("records a run; a block pushes an urgent alert at once", async () => {
    const t = setup();
    const at = new Date("2026-11-12T01:00:00Z"); // quiet hours: urgent still goes
    const res = await handleEvent(event({ vendor: "ksp", outcome: "blocked", detail: "HTTP 403 cf-mitigated" }), t.env, at, t.fetcher);
    expect(res.status).toBe(201);
    expect(t.db.runs[0]).toMatchObject({ vendor: "ksp", ok: 0, outcome: "blocked" });
    expect(t.pushes).toHaveLength(1);
    expect(t.pushes[0].body).toMatchObject({ priority: 5, title: "KSP blocked the scraper" });
    // The next cron keeps it open (same key) instead of re-pushing.
    await runCron(t.env, new Date("2026-11-12T01:30:00Z"), t.fetcher);
    expect(t.pushes.filter((p) => String(p.body.title).includes("blocked"))).toHaveLength(1);
  });
});

describe("admin password", () => {
  let ipSeq = 0;
  const basic = (password: string) => `Basic ${btoa(`admin:${password}`)}`;
  const req = (path: string, auth?: string, ip = `198.51.100.${++ipSeq}`) =>
    new Request(`https://x${path}`, {
      headers: { "cf-connecting-ip": ip, ...(auth ? { authorization: auth } : {}) },
    });
  const withPassword = () => {
    const t = setup();
    t.env.ADMIN_PASSWORD = "correct horse battery";
    return t;
  };

  it("is locked (403) when no ADMIN_PASSWORD is set", async () => {
    const t = setup();
    expect((await handleAdmin("/api/admin/runs", req("/api/admin/runs", basic("x")), t.env)).status).toBe(403);
    const page = await handleAdminPage(req("/admin/"), new URL("https://x/admin/"), t.env);
    expect(page.status).toBe(403);
  });

  it("asks for the password (401 + Basic challenge), then serves", async () => {
    const t = withPassword();
    const none = await handleAdmin("/api/admin/runs", req("/api/admin/runs"), t.env);
    expect(none.status).toBe(401);
    expect(none.headers.get("www-authenticate")).toContain("Basic");
    expect((await handleAdmin("/api/admin/runs", req("/api/admin/runs", basic("wrong")), t.env)).status).toBe(401);
    expect((await handleAdmin("/api/admin/runs", req("/api/admin/runs", basic("correct horse battery")), t.env)).status).toBe(200);
    expect((await handleAdmin("/api/admin/alerts", req("/api/admin/alerts", basic("correct horse battery")), t.env)).status).toBe(200);
    expect((await handleAdmin("/api/admin/nope", req("/api/admin/nope", basic("correct horse battery")), t.env)).status).toBe(404);
  });

  it("serves only the page and its two data files", async () => {
    const t = withPassword();
    const ok = basic("correct horse battery");
    const page = (p: string) => handleAdminPage(req(p, ok), new URL(`https://x${p}`), t.env);
    expect((await page("/admin/data/status.json")).status).toBe(200);
    expect((await page("/admin/data/status.json")).headers.get("cache-control")).toBe("private, no-store");
    expect((await page("/admin/data/memory.json")).status).toBe(404);
    expect((await page("/admin/../wrangler.jsonc")).status).toBe(404);
    expect((await handleAdminPage(req("/admin/data/status.json"), new URL("https://x/admin/data/status.json"), t.env)).status).toBe(401);
  });

  it("Rebuild report dispatches ops-report.yml once per 5 minutes", async () => {
    const t = withPassword();
    resetRebuildCooldown();
    const calls: { url: string; init?: RequestInit }[] = [];
    const gh = (async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response(null, { status: 204 });
    }) as typeof fetch;
    const post = (headers: Record<string, string> = {}) =>
      new Request("https://x/api/admin/rebuild", {
        method: "POST",
        headers: { "cf-connecting-ip": `198.51.100.${++ipSeq}`, authorization: basic("correct horse battery"), ...headers },
      });
    // No token configured: a clear 501, nothing sent.
    expect((await handleAdmin("/api/admin/rebuild", post(), t.env, gh)).status).toBe(501);
    t.env.GH_DISPATCH_TOKEN = "github_pat_test";
    // Cross-site POST refused before anything is sent.
    expect((await handleAdmin("/api/admin/rebuild", post({ "sec-fetch-site": "cross-site" }), t.env, gh)).status).toBe(403);
    expect(calls).toHaveLength(0);
    const ok = await handleAdmin("/api/admin/rebuild", post({ "sec-fetch-site": "same-origin" }), t.env, gh);
    expect(ok.status).toBe(202);
    expect(calls[0].url).toBe("https://api.github.com/repos/Av1zi/Mifrat/actions/workflows/ops-report.yml/dispatches");
    expect(new Headers(calls[0].init?.headers).get("authorization")).toBe("Bearer github_pat_test");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ ref: "main" });
    expect((await handleAdmin("/api/admin/rebuild", post(), t.env, gh)).status).toBe(429);
    expect(calls).toHaveLength(1);
    // Needs the password and POST.
    resetRebuildCooldown();
    const noAuth = new Request("https://x/api/admin/rebuild", { method: "POST", headers: { "cf-connecting-ip": "198.51.100.250" } });
    expect((await handleAdmin("/api/admin/rebuild", noAuth, t.env, gh)).status).toBe(401);
    expect((await handleAdmin("/api/admin/rebuild", req("/api/admin/rebuild", basic("correct horse battery")), t.env, gh)).status).toBe(405);
    expect(calls).toHaveLength(1);
  });

  it("reports a GitHub refusal instead of pretending", async () => {
    const t = withPassword();
    t.env.GH_DISPATCH_TOKEN = "github_pat_test";
    resetRebuildCooldown();
    const gh = (async () => new Response("{}", { status: 403 })) as unknown as typeof fetch;
    const res = await handleAdmin("/api/admin/rebuild", new Request("https://x/api/admin/rebuild", {
      method: "POST", headers: { "cf-connecting-ip": "198.51.100.251", authorization: basic("correct horse battery") },
    }), t.env, gh);
    expect(res.status).toBe(502);
    expect(((await res.json()) as { error: string }).error).toContain("HTTP 403");
  });

  it("locks an IP out after 10 wrong passwords", async () => {
    const t = withPassword();
    const ip = "203.0.113.77";
    for (let i = 0; i < 10; i++) {
      expect((await handleAdmin("/api/admin/runs", req("/api/admin/runs", basic(`guess${i}`), ip), t.env)).status).toBe(401);
    }
    const locked = await handleAdmin("/api/admin/runs", req("/api/admin/runs", basic("correct horse battery"), ip), t.env);
    expect(locked.status).toBe(429);
  });

  it("routes /admin/ and /api/admin/* through the Worker with security headers", async () => {
    const t = withPassword();
    const env = { ...t.env, LISTS_DB: t.db } as Parameters<typeof worker.fetch>[1];
    for (const p of ["/admin/", "/admin", "/admin/data/changes.json", "/api/admin/runs"]) {
      const res = await worker.fetch(req(p), env, { waitUntil() {} });
      expect(res.status).toBe(401);
      expect(res.headers.get("x-frame-options")).toBe("DENY");
    }
  });
});
