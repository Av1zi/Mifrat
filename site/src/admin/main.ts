// Admin console entry (site/admin/index.html, served at /admin/ by the
// Worker after the ADMIN_PASSWORD check). Tabs are hash routes so a push notification or a
// bookmark can open one directly: /admin/#gone?vendor=ksp&days=7.

import "../styles/index.css";
import "./admin.css";
import "@fontsource/ibm-plex-sans-hebrew/400.css";
import "@fontsource/ibm-plex-sans-hebrew/600.css";
import "@fontsource/jetbrains-mono/400.css";
import { applyStoredTheme, setTheme } from "../state";
import { html, mount, type Html } from "../ui/html";
import { loadAlerts, loadChanges, loadRuns, loadStatus } from "./data";
import { ago } from "./format";
import {
  calendarView,
  catalogView,
  goneView,
  logView,
  newView,
  pricesView,
  tonightView,
  type Data,
  type Filters,
} from "./views";

const TABS = [
  { id: "tonight", label: "Tonight" },
  { id: "calendar", label: "Calendar" },
  { id: "new", label: "New" },
  { id: "gone", label: "No longer sold" },
  { id: "prices", label: "Prices" },
  { id: "catalog", label: "Catalog" },
  { id: "log", label: "Alerts & runs" },
] as const;
type Tab = (typeof TABS)[number]["id"];
const FILTERED: ReadonlySet<Tab> = new Set(["new", "gone", "prices"]);

const root = document.getElementById("admin")!;
let data: Data | null = null;
let loadError: string | null = null;

function parseHash(): { tab: Tab; filters: Filters } {
  const [name, query = ""] = location.hash.replace(/^#/, "").split("?");
  const tab = (TABS.find((t) => t.id === name)?.id ?? "tonight") as Tab;
  const params = new URLSearchParams(query);
  const days = Number(params.get("days"));
  return {
    tab,
    filters: {
      vendor: params.get("vendor") ?? "",
      category: params.get("category") ?? "",
      q: params.get("q") ?? "",
      days: [1, 3, 7, 14, 30].includes(days) ? days : 7,
    },
  };
}

function hashFor(tab: Tab, f: Filters): string {
  const params = new URLSearchParams();
  if (f.vendor) params.set("vendor", f.vendor);
  if (f.category) params.set("category", f.category);
  if (f.q) params.set("q", f.q);
  if (f.days !== 7) params.set("days", String(f.days));
  const q = params.toString();
  return `#${tab}${q ? `?${q}` : ""}`;
}

function filterBar(tab: Tab, f: Filters): Html {
  if (!data || !FILTERED.has(tab)) return html``;
  const vendors = data.status.vendors.filter((v) => v.active);
  const categories = Object.keys(data.status.catalog.categories).sort();
  const opt = (value: string, label: string, current: string) =>
    html`<option value="${value}"${value === current ? " selected" : ""}>${label}</option>`;
  return html`<form class="filters" id="filters" role="search">
    <label>Vendor <select name="vendor">${opt("", "All", f.vendor)}${vendors.map((v) => opt(v.id, v.label, f.vendor))}</select></label>
    <label>Category <select name="category">${opt("", "All", f.category)}${categories.map((c) => opt(c, c, f.category))}</select></label>
    <label>Period <select name="days">${[1, 3, 7, 14, 30].map((d) => opt(String(d), d === 1 ? "Last day" : `Last ${d} days`, String(f.days)))}</select></label>
    <label class="filters__q">Search <input type="search" name="q" value="${f.q}" placeholder="Title, product or key" /></label>
  </form>`;
}

function body(tab: Tab, f: Filters, now: Date): Html {
  if (loadError) {
    return html`<section class="panel"><h2 class="panel__title">The ops report did not load</h2>
      <p>${loadError}</p>
      <p class="panel__lede">The normalize-and-deploy workflow writes data/ops/ with <code>python -m scraper.ops.report</code>, and the site build copies it here. Locally, run that command and then <code>npm run dev</code>.</p></section>`;
  }
  if (!data) return html`<div class="state"><span class="state__spinner" aria-hidden="true"></span><p>Loading the scrape report…</p></div>`;
  switch (tab) {
    case "calendar": {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
      const month = /^\d{4}-\d{2}$/.test(params.get("month") ?? "") ? params.get("month")! : "";
      const day = /^\d{4}-\d{2}-\d{2}$/.test(params.get("day") ?? "") ? params.get("day")! : "";
      return calendarView(data, now, { month, day });
    }
    case "new": return newView(data, f, now);
    case "gone": return goneView(data, f, now);
    case "prices": return pricesView(data, f, now);
    case "catalog": return catalogView(data);
    case "log": return logView(data, now);
    default: return tonightView(data, now);
  }
}

// ---- "Rebuild report" -------------------------------------------------------
// The report is a file the pipeline writes; a new one exists only after
// GitHub reruns scraper.ops.report and the site redeploys (~3-5 min). The
// button asks the Worker to start that run, then this page polls
// status.json until its generated_at changes and reloads in place.
type Rebuild = { state: "idle" } | { state: "running"; since: number; from: string } | { state: "error"; message: string };
let rebuild: Rebuild = { state: "idle" };
const REBUILD_KEY = "mifrat:ops-rebuild";
const POLL_MS = 20_000;
const GIVE_UP_MS = 12 * 60_000;

function rebuildLabel(now: Date): Html {
  if (rebuild.state === "running") {
    const s = Math.round((now.getTime() - rebuild.since) / 1000);
    return html`<span class="ahead__meta ahead__meta--busy" role="status"><span class="state__spinner state__spinner--sm" aria-hidden="true"></span>Rebuilding… ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}</span>`;
  }
  if (rebuild.state === "error") return html`<span class="ahead__meta ahead__meta--err" role="alert">${rebuild.message}</span>`;
  return html`<span class="ahead__meta">${data ? `Report built ${ago(data.status.generated_at, now)}` : ""}</span>`;
}

async function startRebuild(): Promise<void> {
  if (!data || rebuild.state === "running") return;
  const from = data.status.generated_at;
  let res: Response;
  try {
    res = await fetch("/api/admin/rebuild", { method: "POST", credentials: "same-origin" });
  } catch {
    rebuild = { state: "error", message: "Could not reach the Worker." };
    render();
    return;
  }
  if (res.status === 202 || res.status === 429) {
    // 429 = one already started in the last 5 minutes: wait for that one.
    rebuild = { state: "running", since: Date.now(), from };
    sessionStorage.setItem(REBUILD_KEY, JSON.stringify(rebuild));
    render();
    void pollRebuild();
    return;
  }
  const body = (await res.json().catch(() => ({}))) as { error?: string };
  rebuild = { state: "error", message: body.error ?? `Rebuild refused (HTTP ${res.status}).` };
  render();
}

async function pollRebuild(): Promise<void> {
  while (rebuild.state === "running") {
    await new Promise((r) => window.setTimeout(r, POLL_MS));
    if (rebuild.state !== "running") return;
    const started = rebuild.since;
    try {
      const status = await loadStatus();
      if (status.generated_at !== rebuild.from) {
        rebuild = { state: "idle" };
        sessionStorage.removeItem(REBUILD_KEY);
        await load();
        return;
      }
    } catch {
      // Mid-deploy 404/5xx: keep waiting.
    }
    if (Date.now() - started > GIVE_UP_MS) {
      rebuild = { state: "error", message: "No new report after 12 minutes: check the ops-report run on GitHub (Alerts & runs → Links)." };
      sessionStorage.removeItem(REBUILD_KEY);
    }
    render();
  }
}

function render(): void {
  const { tab, filters } = parseHash();
  const now = new Date();
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  mount(root, html`
    <header class="ahead">
      <div class="ahead__inner">
        <a class="ahead__brand" href="/admin/"><span class="ahead__mark" aria-hidden="true"></span>Mifrat <span>scrape console</span></a>
        ${rebuildLabel(now)}
        <button type="button" class="ahead__btn" id="reload" title="Load the newest deployed report">Reload</button>
        <button type="button" class="ahead__btn ahead__btn--primary" id="rebuild" title="Regenerate the report from the latest scrapes (about 3-5 minutes)"${rebuild.state === "running" ? " disabled" : ""}>Rebuild report</button>
        <button type="button" class="ahead__btn" id="theme" aria-pressed="${theme === "dark" ? "true" : "false"}">${theme === "dark" ? "Light" : "Dark"}</button>
        <a class="ahead__btn" href="/">Site</a>
      </div>
      <nav class="atabs" aria-label="Console sections">
        ${TABS.map((t) => html`<a class="atabs__tab" href="${hashFor(t.id, filters)}"${t.id === tab ? html` aria-current="page"` : ""}>${t.label}</a>`)}
      </nav>
    </header>
    <main class="amain" id="main">
      ${filterBar(tab, filters)}
      ${body(tab, filters, now)}
    </main>`);
  bind(tab);
}

function bind(tab: Tab): void {
  document.getElementById("reload")?.addEventListener("click", () => void load());
  document.getElementById("rebuild")?.addEventListener("click", () => void startRebuild());
  document.getElementById("theme")?.addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    render();
  });
  const form = document.getElementById("filters") as HTMLFormElement | null;
  if (!form) return;
  const apply = () => {
    const fd = new FormData(form);
    const next: Filters = {
      vendor: String(fd.get("vendor") ?? ""),
      category: String(fd.get("category") ?? ""),
      q: String(fd.get("q") ?? "").trim(),
      days: Number(fd.get("days") ?? 7),
    };
    history.replaceState(null, "", hashFor(tab, next));
    const focused = document.activeElement as HTMLInputElement | null;
    const caret = focused?.name === "q" ? focused.selectionStart : null;
    render();
    if (caret !== null) {
      const input = document.querySelector<HTMLInputElement>('#filters input[name="q"]');
      input?.focus();
      input?.setSelectionRange(caret, caret);
    }
  };
  form.addEventListener("change", apply);
  let timer: number | undefined;
  form.addEventListener("input", (e) => {
    if ((e.target as HTMLElement).tagName !== "INPUT") return;
    window.clearTimeout(timer);
    timer = window.setTimeout(apply, 200);
  });
  form.addEventListener("submit", (e) => e.preventDefault());
}

async function load(): Promise<void> {
  loadError = null;
  // Keep showing the current data while the new one loads.
  if (!data) render();
  const btn = document.getElementById("reload") as HTMLButtonElement | null;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Loading…";
  }
  try {
    const [status, changes, runs, alerts] = await Promise.all([
      loadStatus(),
      loadChanges().catch(() => null),
      loadRuns(),
      loadAlerts(),
    ]);
    data = { status, changes, runs, alerts };
  } catch (err) {
    data = null;
    loadError = err instanceof Error ? err.message : String(err);
  }
  render();
}

applyStoredTheme();
window.addEventListener("hashchange", render);
// A rebuild started before a page reload keeps being waited for.
try {
  const saved = JSON.parse(sessionStorage.getItem(REBUILD_KEY) ?? "null") as Rebuild | null;
  if (saved?.state === "running" && Date.now() - saved.since < GIVE_UP_MS) rebuild = saved;
} catch {
  // ignore a corrupt entry
}
void load().then(() => {
  if (rebuild.state === "running") void pollRebuild();
});
