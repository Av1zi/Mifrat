/**
 * Ops side of the Worker: alert cron, 10:00 daily report, Nano run events
 * and the admin API. worker.ts routes here; all decisions come from
 * src/ops/rules.ts (shared with the admin page) and every push goes through
 * `push()`, the single ntfy sender.
 *
 * Storage: the existing `mifrat-lists` D1 database (binding LISTS_DB), tables `ops_alerts` (one row per open/closed finding key),
 * `ops_runs` (Nano run reports) and `ops_meta` (daily-report date, abuse
 * window). See migrations/0002_ops.sql. All writes are bounded: one upsert
 * per changed finding per cron tick, one row per Nano run (pruned at 60
 * days), never per visitor request.
 *
 * Secrets (Worker secrets, never in git): NTFY_TOPIC_URL (https://ntfy.sh/
 * <long random topic>), NTFY_TOKEN (ntfy access token, optional but
 * recommended: ntfy.sh limits anonymous publishers per IP and Workers share
 * egress IPs), OPS_INGEST_TOKEN (the Nano's bearer token), HEALTHCHECK_URL
 * (optional heartbeat pinged after each daily report), ADMIN_PASSWORD (the
 * console login; without it /admin/ stays locked).
 */

import { alertMessage, dailyReport, type PushMessage } from "./src/ops/report";
import { evaluate, israelParts, type Finding, type LiveFacts, type NanoRun } from "./src/ops/rules";
import type { OpsStatus } from "./src/ops/types";
import { OPS_SCHEMA } from "./src/ops/types";

interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T>(): Promise<T | null>;
  run(): Promise<unknown>;
  all<T>(): Promise<{ results: T[] }>;
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
}

interface AssetBinding {
  fetch(request: Request): Promise<Response>;
}

export interface OpsEnv {
  ASSETS: AssetBinding;
  LISTS_DB?: D1Database;
  NTFY_TOPIC_URL?: string;
  NTFY_TOKEN?: string;
  OPS_INGEST_TOKEN?: string;
  HEALTHCHECK_URL?: string;
  /** Password for /admin/ and /api/admin/* (HTTP Basic, any username). */
  ADMIN_PASSWORD?: string;
  /** Fine-grained GitHub token (this repo, Actions: write) for "Rebuild report". */
  GH_DISPATCH_TOKEN?: string;
  /** Public origin for notification links (default: the request/asset origin). */
  SITE_ORIGIN?: string;
}

export const DEFAULT_ORIGIN = "https://mifrat.avizi.workers.dev";
/** The daily report goes out on the first cron tick in this Israel hour. */
export const REPORT_HOUR_ISRAEL = 10;
/** An open alert is pushed again after this long. */
export const REMIND_AFTER_MS = 24 * 3_600_000;
/** Quiet hours (Israel): only urgent alerts push; the rest wait. */
export const QUIET_START_HOUR = 23;
export const QUIET_END_HOUR = 7;
const RUN_RETENTION_DAYS = 60;
const MAX_EVENT_BYTES = 2048;
const VENDOR_RE = /^[a-z0-9]{2,16}$/;
const OUTCOMES = new Set(["ok", "blocked", "failed", "partial"]);

// ---- abuse counter ----------------------------------------------------------
// Rate-limited /api requests, counted in memory per isolate (no D1 write per
// request: a flood must not be able to spend the D1 quota). The cron reads
// the counter of whichever isolate runs it, so it is a lower bound; a real
// flood hits every isolate and shows up anyway.
let abuseHits = 0;
let abuseSince = Date.now();

export function recordAbuse(): void {
  abuseHits++;
}

export function takeAbuseHits(now = Date.now()): number {
  const n = abuseHits;
  abuseHits = 0;
  abuseSince = now;
  return n;
}

export function abuseWindowStart(): number {
  return abuseSince;
}

// ---- helpers -----------------------------------------------------------------

function origin(env: OpsEnv): string {
  return (env.SITE_ORIGIN || DEFAULT_ORIGIN).replace(/\/+$/, "");
}

export function isQuietHour(now: Date): boolean {
  const { hour } = israelParts(now);
  return hour >= QUIET_START_HOUR || hour < QUIET_END_HOUR;
}

/** Constant-time string compare (token check). */
function sameToken(a: string, b: string): boolean {
  if (a.length !== b.length || a.length === 0) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function json(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...headers },
  });
}

/** One ntfy publish (JSON to the server root). Returns whether it was accepted. */
export async function push(env: OpsEnv, msg: PushMessage, fetcher: typeof fetch = fetch): Promise<boolean> {
  if (!env.NTFY_TOPIC_URL) return false;
  let url: URL;
  try {
    url = new URL(env.NTFY_TOPIC_URL);
  } catch {
    return false;
  }
  if (url.protocol !== "https:") return false;
  const topic = url.pathname.replace(/^\/+|\/+$/g, "");
  if (!topic || topic.includes("/")) return false;
  const site = origin(env);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (env.NTFY_TOKEN) headers.authorization = `Bearer ${env.NTFY_TOKEN}`;
  const body = {
    topic,
    title: msg.title,
    message: msg.message,
    priority: msg.priority,
    tags: msg.tags,
    click: site + msg.click,
    actions: [{ action: "view", label: "Open panel", url: `${site}/admin/`, clear: true }],
  };
  try {
    const res = await fetcher(`${url.origin}/`, { method: "POST", headers, body: JSON.stringify(body) });
    return res.ok;
  } catch {
    return false;
  }
}

async function readStatus(env: OpsEnv): Promise<OpsStatus | null> {
  try {
    const res = await env.ASSETS.fetch(new Request(`${origin(env)}/admin/data/status.json`));
    if (!res.ok) return null;
    const status = (await res.json()) as OpsStatus;
    return status && status.schema === OPS_SCHEMA ? status : null;
  } catch {
    return null;
  }
}

async function liveFacts(env: OpsEnv, fetcher: typeof fetch): Promise<LiveFacts> {
  const facts: LiveFacts = { abuseHits: takeAbuseHits() };
  // The public site, over the network: the same path a visitor takes.
  try {
    const res = await fetcher(`${origin(env)}/data/site/meta.json`, { cf: { cacheTtl: 0 } } as RequestInit);
    facts.siteOk = res.ok;
    if (res.ok) {
      const meta = (await res.json()) as { generated_at?: string };
      facts.deployedCatalogAt = meta.generated_at ?? null;
    }
  } catch {
    facts.siteOk = false;
  }
  if (env.LISTS_DB) {
    try {
      const { results } = await env.LISTS_DB.prepare(
        "SELECT vendor, at, ok, outcome, detail FROM ops_runs WHERE id IN " +
          "(SELECT MAX(id) FROM ops_runs GROUP BY vendor)"
      ).all<{ vendor: string; at: string; ok: number; outcome: string; detail: string | null }>();
      facts.nanoRuns = {};
      for (const r of results) {
        facts.nanoRuns[r.vendor] = { vendor: r.vendor, at: r.at, ok: !!r.ok, outcome: r.outcome, detail: r.detail ?? undefined };
      }
    } catch {
      // A D1 hiccup only drops the Nano facts for one tick.
    }
  }
  return facts;
}

interface AlertRow {
  key: string;
  severity: string;
  title: string;
  detail: string;
  opened_at: string;
  last_push: string | null;
  closed_at: string | null;
}

/**
 * Open, remind and resolve alerts for this tick's findings. Returns the
 * pushes it sent (tests read this).
 */
export async function syncAlerts(
  env: OpsEnv,
  findings: Finding[],
  now: Date,
  fetcher: typeof fetch = fetch
): Promise<PushMessage[]> {
  const sent: PushMessage[] = [];
  if (!env.LISTS_DB) return sent;
  const db = env.LISTS_DB;
  const { results: open } = await db
    .prepare("SELECT key, severity, title, detail, opened_at, last_push, closed_at FROM ops_alerts WHERE closed_at IS NULL")
    .all<AlertRow>();
  const openByKey = new Map(open.map((r) => [r.key, r]));
  const quiet = isQuietHour(now);
  const at = now.toISOString();

  for (const f of findings) {
    const row = openByKey.get(f.key);
    openByKey.delete(f.key);
    const mayPush = f.severity === "urgent" || !quiet;
    if (!row) {
      let pushedAt: string | null = null;
      if (mayPush) {
        const msg = alertMessage(f, "open");
        if (await push(env, msg, fetcher)) {
          sent.push(msg);
          pushedAt = at;
        }
      }
      await db
        .prepare(
          "INSERT INTO ops_alerts (key, severity, title, detail, opened_at, last_push, closed_at) " +
            "VALUES (?, ?, ?, ?, ?, ?, NULL) ON CONFLICT(key) DO UPDATE SET severity = excluded.severity, " +
            "title = excluded.title, detail = excluded.detail, opened_at = excluded.opened_at, " +
            "last_push = excluded.last_push, closed_at = NULL"
        )
        .bind(f.key, f.severity, f.title, f.detail, at, pushedAt)
        .run();
      continue;
    }
    const lastPush = row.last_push ? Date.parse(row.last_push) : 0;
    const due = !row.last_push || now.getTime() - lastPush >= REMIND_AFTER_MS;
    if (due && mayPush) {
      const msg = alertMessage(f, row.last_push ? "remind" : "open");
      if (await push(env, msg, fetcher)) {
        sent.push(msg);
        await db
          .prepare("UPDATE ops_alerts SET last_push = ?, severity = ?, title = ?, detail = ? WHERE key = ?")
          .bind(at, f.severity, f.title, f.detail, f.key)
          .run();
      }
    }
  }

  // Whatever is still open was not found this tick: resolved.
  for (const row of openByKey.values()) {
    if (row.last_push && !quiet) {
      const msg = alertMessage(
        { key: row.key, severity: row.severity as Finding["severity"], title: row.title, detail: "" },
        "resolved"
      );
      if (await push(env, msg, fetcher)) sent.push(msg);
    }
    // A quiet-hours resolve closes silently; one that was never pushed too.
    await db.prepare("UPDATE ops_alerts SET closed_at = ? WHERE key = ?").bind(at, row.key).run();
  }
  return sent;
}

/** The 10:00 report: once per Israel date, on the first tick in that hour. */
export async function maybeDailyReport(
  env: OpsEnv,
  status: OpsStatus,
  findings: Finding[],
  now: Date,
  fetcher: typeof fetch = fetch
): Promise<PushMessage | null> {
  const { date, hour } = israelParts(now);
  if (hour !== REPORT_HOUR_ISRAEL || !env.LISTS_DB) return null;
  const done = await env.LISTS_DB.prepare("SELECT value FROM ops_meta WHERE name = 'daily_report'")
    .first<{ value: string }>();
  if (done?.value === date) return null;
  const msg = dailyReport(status, findings, now);
  if (!(await push(env, msg, fetcher))) return null;
  await env.LISTS_DB.prepare(
    "INSERT INTO ops_meta (name, value) VALUES ('daily_report', ?) " +
      "ON CONFLICT(name) DO UPDATE SET value = excluded.value"
  )
    .bind(date)
    .run();
  if (env.HEALTHCHECK_URL) {
    try {
      await fetcher(env.HEALTHCHECK_URL, { method: "POST", body: date });
    } catch {
      // The heartbeat's absence is what alerts; nothing to do here.
    }
  }
  return msg;
}

/** Report a pipeline that has no status file at all (first deploy, broken copy). */
const NO_STATUS: Finding = {
  key: "report-missing",
  severity: "high",
  title: "Ops report missing on the site",
  detail: "/admin/data/status.json did not load: copy-data or the ops report step may be broken.",
};

export async function runCron(env: OpsEnv, now: Date, fetcher: typeof fetch = fetch): Promise<{
  findings: Finding[];
  sent: PushMessage[];
  report: PushMessage | null;
}> {
  const status = await readStatus(env);
  const live = await liveFacts(env, fetcher);
  const findings = status ? evaluate(status, now, live) : [NO_STATUS];
  const sent = await syncAlerts(env, findings, now, fetcher);
  const report = status ? await maybeDailyReport(env, status, findings, now, fetcher) : null;
  if (env.LISTS_DB) {
    const cutoff = new Date(now.getTime() - RUN_RETENTION_DAYS * 86_400_000).toISOString();
    try {
      await env.LISTS_DB.prepare("DELETE FROM ops_runs WHERE at < ?").bind(cutoff).run();
    } catch {
      // Retention is best-effort.
    }
  }
  return { findings, sent, report };
}

// ---- HTTP: Nano run events + admin API ----------------------------------------

/** POST /api/ops/event from the Nano: {vendor, ok, outcome, detail?, items?}. */
export async function handleEvent(request: Request, env: OpsEnv, now: Date, fetcher: typeof fetch = fetch): Promise<Response> {
  if (request.method !== "POST") return json({ error: "method not allowed" }, 405);
  const token = env.OPS_INGEST_TOKEN || "";
  const auth = request.headers.get("authorization") || "";
  if (!token || !sameToken(auth, `Bearer ${token}`)) return json({ error: "unauthorized" }, 401);
  if (!env.LISTS_DB) return json({ error: "storage unavailable" }, 500);
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_EVENT_BYTES) return json({ error: "too large" }, 413);
  let body: Record<string, unknown>;
  try {
    const text = await request.text();
    if (text.length > MAX_EVENT_BYTES) return json({ error: "too large" }, 413);
    body = JSON.parse(text);
  } catch {
    return json({ error: "body must be JSON" }, 400);
  }
  const vendor = String(body.vendor ?? "");
  const outcome = String(body.outcome ?? "");
  if (!VENDOR_RE.test(vendor) || !OUTCOMES.has(outcome)) return json({ error: "bad event" }, 400);
  const ok = outcome === "ok";
  const detail = typeof body.detail === "string" ? body.detail.slice(0, 500) : null;
  const items = Number.isFinite(Number(body.items)) ? Math.trunc(Number(body.items)) : null;
  const at = now.toISOString();
  await env.LISTS_DB.prepare(
    "INSERT INTO ops_runs (vendor, at, ok, outcome, detail, items) VALUES (?, ?, ?, ?, ?, ?)"
  )
    .bind(vendor, at, ok ? 1 : 0, outcome, detail, items)
    .run();
  // A block is urgent and should not wait for the next cron tick.
  if (outcome === "blocked") {
    const run: NanoRun = { vendor, at, ok, outcome, detail: detail ?? undefined };
    const finding: Finding = {
      key: `blocked:${vendor}`,
      severity: "urgent",
      vendor,
      title: `${vendor.toUpperCase()} blocked the scraper`,
      detail: `${run.detail || "HTTP 403/429 or a challenge page"} at ${at}. A block is a stop signal; decide before the next run.`,
    };
    await syncAlerts(env, [finding], now, fetcher).catch(() => []);
  }
  return json({ ok: true }, 201);
}

// ---- admin login (HTTP Basic, no Cloudflare Access) ---------------------------
// Owner 2026-11-12: Zero Trust asks for a card, so the Worker guards /admin/*
// and /api/admin/* itself. The browser asks for the password once and
// remembers it for the session. No ADMIN_PASSWORD secret = everything
// refused (locked by default). Wrong guesses are rate-limited per IP.

const REALM = 'Basic realm="Mifrat scrape console", charset="UTF-8"';
const MAX_FAILS_PER_10_MIN = 10;
const failures = new Map<string, number[]>();

function tooManyFailures(ip: string, now: number): boolean {
  const recent = (failures.get(ip) ?? []).filter((t) => t > now - 600_000);
  failures.set(ip, recent);
  if (failures.size > 5000) failures.clear();
  return recent.length >= MAX_FAILS_PER_10_MIN;
}

/** null = authorized; otherwise the refusal to send. */
export function adminAuth(request: Request, env: OpsEnv, now = Date.now()): Response | null {
  const password = env.ADMIN_PASSWORD || "";
  const ip = request.headers.get("cf-connecting-ip") ?? "unknown";
  if (!password) return new Response("Admin is locked: set the ADMIN_PASSWORD Worker secret.", { status: 403, headers: { "cache-control": "no-store" } });
  if (tooManyFailures(ip, now)) return new Response("Too many attempts, try again in 10 minutes.", { status: 429, headers: { "cache-control": "no-store", "retry-after": "600" } });
  const header = request.headers.get("authorization") || "";
  let given = "";
  if (header.startsWith("Basic ")) {
    try {
      const decoded = atob(header.slice(6).trim());
      given = decoded.slice(decoded.indexOf(":") + 1); // any username
    } catch {
      given = "";
    }
  }
  if (sameToken(given, password)) return null;
  if (header) failures.set(ip, [...(failures.get(ip) ?? []), now]);
  return new Response("Password required.", {
    status: 401,
    headers: { "www-authenticate": REALM, "cache-control": "no-store" },
  });
}

/** GET /admin/* (the console page + its data): password, then the static asset. */
export async function handleAdminPage(request: Request, url: URL, env: OpsEnv): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") return json({ error: "method not allowed" }, 405);
  const refused = adminAuth(request, env);
  if (refused) return refused;
  // Never hand memory/other files out: only the page, its two data files.
  const path = url.pathname;
  const allowed = path === "/admin" || path === "/admin/" || path === "/admin/index.html" ||
    path === "/admin/data/status.json" || path === "/admin/data/changes.json";
  if (!allowed) return new Response("Not found", { status: 404 });
  const target = path === "/admin" ? new URL("/admin/", url) : url;
  const res = await env.ASSETS.fetch(new Request(target.toString(), { method: request.method }));
  const headers = new Headers(res.headers);
  headers.set("cache-control", "private, no-store");
  headers.set("x-robots-tag", "noindex, nofollow");
  return new Response(res.body, { status: res.status, headers });
}

// ---- "Rebuild report" button --------------------------------------------------
export const GH_REPO = "Av1zi/Mifrat";
export const GH_WORKFLOW = "ops-report.yml";
/** One rebuild per this long (a run takes ~2 min, the deploy after it ~2). */
export const REBUILD_COOLDOWN_MS = 5 * 60_000;
let lastRebuild = 0;

/** Test hook: forget the cooldown. */
export function resetRebuildCooldown(): void {
  lastRebuild = 0;
}

/**
 * POST /api/admin/rebuild: dispatch ops-report.yml (it regenerates data/ops
 * and pushes; the push redeploys the site). Needs GH_DISPATCH_TOKEN, a
 * fine-grained token for this repo only with "Actions: Read and write".
 */
async function handleRebuild(request: Request, env: OpsEnv, fetcher: typeof fetch): Promise<Response> {
  const origin = request.headers.get("origin");
  const site = request.headers.get("sec-fetch-site");
  if ((site !== null && site !== "same-origin") || (origin !== null && origin !== new URL(request.url).origin)) {
    return json({ error: "cross-site request" }, 403);
  }
  if (!env.GH_DISPATCH_TOKEN) {
    return json({ error: "Set the GH_DISPATCH_TOKEN Worker secret to enable this button (docs/ops-alerts.md)." }, 501);
  }
  const now = Date.now();
  if (now - lastRebuild < REBUILD_COOLDOWN_MS) {
    return json({ error: "A rebuild was started less than 5 minutes ago.", retry_in_s: Math.ceil((REBUILD_COOLDOWN_MS - (now - lastRebuild)) / 1000) }, 429);
  }
  let res: Response;
  try {
    res = await fetcher(`https://api.github.com/repos/${GH_REPO}/actions/workflows/${GH_WORKFLOW}/dispatches`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
        accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "mifrat-worker",
        "content-type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    });
  } catch {
    return json({ error: "GitHub did not answer." }, 502);
  }
  if (res.status !== 204 && res.status !== 200) {
    return json({ error: `GitHub refused the dispatch (HTTP ${res.status}). Check the token's repository and Actions permission.` }, 502);
  }
  lastRebuild = now;
  return json({ ok: true, started_at: new Date(now).toISOString() }, 202);
}

/** /api/admin/{runs,alerts} (GET) and /api/admin/rebuild (POST), same password as the page. */
export async function handleAdmin(path: string, request: Request, env: OpsEnv, fetcher: typeof fetch = fetch): Promise<Response> {
  if (path === "/api/admin/rebuild") {
    if (request.method !== "POST") return json({ error: "method not allowed" }, 405);
    const refused = adminAuth(request, env);
    if (refused) return refused;
    return handleRebuild(request, env, fetcher);
  }
  if (request.method !== "GET") return json({ error: "method not allowed" }, 405);
  const refused = adminAuth(request, env);
  if (refused) return refused;
  if (!env.LISTS_DB) return json({ error: "storage unavailable" }, 500);
  if (path === "/api/admin/runs") {
    const { results } = await env.LISTS_DB.prepare(
      "SELECT vendor, at, ok, outcome, detail, items FROM ops_runs ORDER BY id DESC LIMIT 200"
    ).all();
    return json({ runs: results });
  }
  if (path === "/api/admin/alerts") {
    const { results } = await env.LISTS_DB.prepare(
      "SELECT key, severity, title, detail, opened_at, last_push, closed_at FROM ops_alerts " +
        "ORDER BY COALESCE(closed_at, '9999') DESC, opened_at DESC LIMIT 200"
    ).all();
    return json({ alerts: results });
  }
  return json({ error: "not found" }, 404);
}
