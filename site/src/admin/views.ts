// Admin console views. Each view is a pure (data, now) -> Html function; the
// shell in main.ts owns routing, loading and filters.

import { allVendorHealth, evaluate, nightStart, type Finding, type VendorHealth } from "../ops/rules";
import type { OpsAbsent, OpsChanges, OpsCrawl, OpsEvent, OpsStatus } from "../ops/types";
import { html, type Html } from "../ui/html";
import { safeUrl } from "../utils";
import type { AlertRow, RunRow } from "./data";
import { ago, ilDateKey, ilDateTime, ilDay, ilShortDay, ilTime, ils, n, pct } from "./format";

export interface Data {
  status: OpsStatus;
  changes: OpsChanges | null;
  runs: RunRow[] | null;
  alerts: AlertRow[] | null;
}

export interface Filters {
  vendor: string;
  category: string;
  q: string;
  days: number;
}

const STATE_LABEL: Record<string, string> = {
  fresh: "Scraped",
  partial: "Partial",
  late: "Running",
  missing: "Not scraped",
  dropped: "Dropped",
};

const SEVERITY_LABEL: Record<string, string> = { urgent: "Urgent", high: "High", warn: "Check", info: "Info" };

function vendorLabel(status: OpsStatus, id: string | undefined): string {
  return status.vendors.find((v) => v.id === id)?.label ?? id ?? "";
}

function link(url: string | undefined, text: string): Html {
  const safe = url ? safeUrl(url) : null;
  return safe ? html`<a href="${safe}" target="_blank" rel="noopener noreferrer">${text}</a>` : html`${text}`;
}

function productLink(e: { pid?: string | null; product?: string; category?: string }): Html {
  if (!e.pid || !e.product) return html`<span class="text-dim">–</span>`;
  const site = e.category === "aio" || e.category === "cooler_air" ? "cpu_cooler" : e.category;
  const href = `/#/p/${encodeURIComponent(site ?? "")}/${encodeURIComponent(e.pid)}`;
  return html`<a href="${href}" target="_blank" rel="noopener">${e.product}</a>`;
}

// ---- Tonight -------------------------------------------------------------------

/** Night band: 22:00 UTC the evening before (= the axis start) to 07:00 UTC. */
function nightTimeline(health: VendorHealth[], now: Date): Html {
  const night = nightStart(now);
  const start = night.getTime() - 3_600_000; // 20:00 UTC: show early starts too
  const end = night.getTime() + 11 * 3_600_000; // 08:00 UTC
  const span = end - start;
  const pos = (t: number) => Math.max(0, Math.min(100, ((t - start) / span) * 100));
  const windowStart = pos(night.getTime());
  const windowEnd = pos(night.getTime() + 7 * 3_600_000);
  const ticks: Html[] = [];
  for (let t = start; t <= end; t += 2 * 3_600_000) {
    ticks.push(html`<span class="tl__tick" style="${`inset-inline-start:${pos(t)}%`}">${ilTime(new Date(t).toISOString())}</span>`);
  }
  const nowPos = now.getTime() < end ? pos(now.getTime()) : null;
  const lanes = health.filter((h) => h.vendor.active).map((h) => {
    const c = h.tonight;
    let bar: Html;
    if (c) {
      const left = pos(new Date(c.start).getTime());
      const width = Math.max(0.8, pos(new Date(c.end).getTime()) - left);
      bar = html`<span class="tl__bar tl__bar--${h.state}" style="${`inset-inline-start:${left}%;width:${width}%`}" title="${`${ilTime(c.start)}–${ilTime(c.end)} · ${n(c.keys)} items`}"></span>`;
    } else {
      bar = html`<span class="tl__empty">${h.state === "late" ? "waiting for tonight's run" : "no crawl"}</span>`;
    }
    return html`<div class="tl__lane">
      <span class="tl__name">${h.vendor.label}</span>
      <span class="tl__track">${bar}</span>
    </div>`;
  });
  return html`<figure class="tl" aria-label="Last night's crawls on an Israel-time axis">
    <div class="tl__plot">
      <div class="tl__overlay" aria-hidden="true">
        <span class="tl__window" style="${`inset-inline-start:${windowStart}%;width:${windowEnd - windowStart}%`}"></span>
        ${nowPos !== null ? html`<span class="tl__now" style="${`inset-inline-start:${nowPos}%`}"></span>` : ""}
      </div>
      <div class="tl__lane tl__lane--axis"><span></span><span class="tl__axis">${ticks}</span></div>
      ${lanes}
    </div>
    <figcaption class="tl__caption">Shaded band: the 23:00–07:00 scrape window, Israel time (${ilDay(night.toISOString())} night).</figcaption>
  </figure>`;
}

/** Item counts of the last 14 crawls as an inline SVG polyline. */
function sparkline(crawls: OpsCrawl[], floor: number): Html {
  const pts = crawls.slice(-14);
  if (pts.length < 2) return html``;
  const values = pts.map((c) => c.keys);
  const max = Math.max(...values, floor);
  const min = Math.min(...values, floor) * 0.95;
  const w = 140;
  const hgt = 28;
  const x = (i: number) => (i / (pts.length - 1)) * w;
  const y = (v: number) => hgt - ((v - min) / (max - min || 1)) * hgt;
  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const floorY = y(floor).toFixed(1);
  const label = `Last ${pts.length} crawls: ${values.map(n).join(", ")} items (floor ${n(floor)})`;
  return html`<svg class="spark" viewBox="${`0 0 ${w} ${hgt}`}" width="${w}" height="${hgt}" role="img" aria-label="${label}">
    <title>${label}</title>
    <line class="spark__floor" x1="0" x2="${w}" y1="${floorY}" y2="${floorY}"></line>
    <polyline class="spark__line" points="${line}"></polyline>
  </svg>`;
}

function vendorCard(h: VendorHealth, crawls: OpsCrawl[], now: Date): Html {
  const c = h.tonight ?? h.last;
  return html`<article class="vcard vcard--${h.state}">
    <header class="vcard__head">
      <h3 class="vcard__name">${h.vendor.label}</h3>
      <span class="vcard__state">${STATE_LABEL[h.state]}</span>
    </header>
    ${c
      ? html`<p class="vcard__big">${n(c.keys)} <span>items</span></p>
          <p class="vcard__meta">${ilDateTime(c.start)} · ${ago(c.start, now)} · ${h.vendor.host === "home" ? "Nano" : "GitHub"}</p>
          ${!c.baseline
            ? html`<p class="vcard__delta"><span class="up">+${c.new} new</span> <span class="down">−${c.gone} gone</span> <span>${c.missing} missing</span> <span>${c.price_changes} repriced</span></p>`
            : html`<p class="vcard__delta">First crawl in the window</p>`}`
      : html`<p class="vcard__big">–</p><p class="vcard__meta">No crawl in the last 60 days</p>`}
    ${sparkline(crawls, h.vendor.min_rows)}
    ${h.notes.length ? html`<ul class="vcard__notes">${h.notes.map((note) => html`<li>${note}</li>`)}</ul>` : ""}
  </article>`;
}

function findingList(findings: Finding[]): Html {
  if (!findings.length) return html`<p class="allclear">Nothing needs a look. Every vendor was scraped last night and the site is current.</p>`;
  return html`<ul class="findings">${findings.map(
    (f) => html`<li class="finding finding--${f.severity}">
      <span class="finding__sev">${SEVERITY_LABEL[f.severity]}</span>
      <div><strong>${f.title}</strong><p>${f.detail}</p></div>
    </li>`
  )}</ul>`;
}

export function tonightView(d: Data, now: Date): Html {
  const health = allVendorHealth(d.status, now);
  const findings = evaluate(d.status, now);
  const cat = d.status.catalog;
  const activeHealth = health.filter((h) => h.vendor.active);
  return html`
    <section class="panel">
      <h2 class="panel__title">Open problems</h2>
      ${findingList(findings)}
    </section>
    <section class="panel">
      <h2 class="panel__title">Last night</h2>
      ${nightTimeline(activeHealth, now)}
    </section>
    <section class="vcards">${activeHealth.map((h) => vendorCard(h, d.status.crawls[h.vendor.id] ?? [], now))}</section>
    <section class="panel panel--row">
      <div><span class="kv__k">Catalog built</span><span class="kv__v">${cat.generated_at ? ilDateTime(cat.generated_at) : "–"}</span></div>
      <div><span class="kv__k">Products</span><span class="kv__v">${n(cat.products)}</span></div>
      <div><span class="kv__k">Listings</span><span class="kv__v">${n(cat.listings)}</span></div>
      <div><span class="kv__k">Skipped vendors</span><span class="kv__v">${cat.skipped_vendors.length ? cat.skipped_vendors.join(", ") : "none"}</span></div>
      <div><span class="kv__k">Report built</span><span class="kv__v">${ago(d.status.generated_at, now)}</span></div>
    </section>`;
}

// ---- Calendar ------------------------------------------------------------------

type CellState = "ok" | "partial" | "double" | "none" | "future";

function cellFor(crawls: OpsCrawl[]): { state: CellState; title: string; label: string } {
  if (!crawls.length) return { state: "none", title: "no crawl", label: "" };
  const c = crawls[crawls.length - 1];
  const parts = crawls.map((x) => `${ilTime(x.start)} ${n(x.keys)} items${x.suspect ? ` (partial: ${x.suspect})` : ""}`);
  const title = `${parts.join("\n")}\n+${c.new} new −${c.gone} gone`;
  const label = c.keys >= 1000 ? `${(c.keys / 1000).toFixed(1)}k` : String(c.keys);
  if (crawls.length > 1 || c.crawls_in_file > 1) return { state: "double", title, label };
  if (c.suspect) return { state: "partial", title, label };
  return { state: "ok", title, label };
}

export function calendarView(d: Data, now: Date, days = 35): Html {
  // A crawl belongs to the night it started in: the Israel date of
  // (start - 12h) makes a 02:00 crawl count for the evening before.
  const nightKey = (iso: string) => ilDateKey(new Date(new Date(iso).getTime() - 12 * 3_600_000));
  const lastNight = nightKey(now.toISOString());
  const keys: string[] = [];
  for (let i = days - 1; i >= 0; i--) {
    keys.push(nightKey(new Date(now.getTime() - i * 86_400_000).toISOString()));
  }
  const uniqueKeys = [...new Set(keys)];
  const vendors = d.status.vendors.filter((v) => v.active || (d.status.crawls[v.id] ?? []).length);
  const head = html`<tr><th scope="col">Vendor</th>${uniqueKeys.map((k) => {
    const date = new Date(`${k}T12:00:00Z`);
    return html`<th scope="col" class="cal__day${k === lastNight ? " is-today" : ""}" title="${`Night of ${ilDay(date.toISOString())}`}">${ilShortDay(date)}</th>`;
  })}</tr>`;
  const rows = vendors.map((v) => {
    const byNight = new Map<string, OpsCrawl[]>();
    for (const c of d.status.crawls[v.id] ?? []) {
      const k = nightKey(c.start);
      byNight.set(k, [...(byNight.get(k) ?? []), c]);
    }
    return html`<tr><th scope="row">${v.label}${v.active ? "" : html` <span class="text-dim">(dropped)</span>`}</th>${uniqueKeys.map((k) => {
      const cell = cellFor(byNight.get(k) ?? []);
      return html`<td class="cal__cell cal__cell--${cell.state}" title="${cell.title}">${cell.label}</td>`;
    })}</tr>`;
  });
  return html`<section class="panel">
    <h2 class="panel__title">Scrape calendar</h2>
    <p class="panel__lede">One column per night (a crawl after midnight counts for the evening it belongs to). Numbers are items scraped. Hover a cell for the crawl times.</p>
    <div class="table-wrap"><table class="cal">
      <thead>${head}</thead>
      <tbody>${rows}</tbody>
    </table></div>
    <p class="legend">
      <span class="legend__item"><span class="cal__swatch cal__cell--ok"></span>Scraped</span>
      <span class="legend__item"><span class="cal__swatch cal__cell--partial"></span>Partial (under the floor or the vendor's typical size)</span>
      <span class="legend__item"><span class="cal__swatch cal__cell--double"></span>Two crawls in one night</span>
      <span class="legend__item"><span class="cal__swatch cal__cell--none"></span>Not scraped</span>
    </p>
  </section>`;
}

// ---- Event lists (New / No longer sold / Prices) ----------------------------------

function inWindow(e: { at?: string; since?: string }, f: Filters, now: Date): boolean {
  const at = e.at ?? e.since ?? "";
  return now.getTime() - new Date(at).getTime() <= f.days * 86_400_000;
}

function matches(e: OpsEvent | OpsAbsent, f: Filters): boolean {
  if (f.vendor && e.vendor !== f.vendor && !(("vendors" in e) && e.vendors?.includes(f.vendor))) return false;
  if (f.category && e.category !== f.category) return false;
  if (f.q) {
    const hay = `${e.title ?? ""} ${e.product ?? ""} ${e.key ?? ""}`.toLowerCase();
    if (!hay.includes(f.q.toLowerCase())) return false;
  }
  return true;
}

function emptyRow(cols: number, text: string): Html {
  return html`<tr><td colspan="${cols}" class="empty">${text}</td></tr>`;
}

function noChanges(): Html {
  return html`<section class="panel"><p class="allclear">changes.json did not load, so there is no change history to show. Run <code>python -m scraper.ops.report</code> and rebuild the site.</p></section>`;
}

export function newView(d: Data, f: Filters, now: Date): Html {
  if (!d.changes) return noChanges();
  const events = d.changes.events.filter((e) => inWindow(e, f, now) && matches(e, f));
  const products = events.filter((e) => e.type === "new_product");
  const added = events.filter((e) => e.type === "vendor_added");
  const returned = events.filter((e) => e.type === "returned");
  const s = d.status;
  return html`
    <section class="panel">
      <h2 class="panel__title">New products <span class="count">${products.length}</span></h2>
      <p class="panel__lede">Parts the catalog had never seen. A renamed or split product is not counted.</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>First seen</th><th>Product</th><th>Category</th><th>Sold by</th><th class="num">Price</th></tr></thead>
        <tbody>${products.length ? products.map((e) => html`<tr>
          <td class="nowrap">${ilDateTime(e.at)}</td><td>${productLink(e)}</td><td>${e.category}</td>
          <td>${(e.vendors ?? []).map((v) => vendorLabel(s, v)).join(", ")}</td><td class="num">${ils(e.price)}</td>
        </tr>`) : emptyRow(5, "No new products in this period.")}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <h2 class="panel__title">A vendor started selling <span class="count">${added.length}</span></h2>
      <p class="panel__lede">A new listing joined a product other vendors already sell.</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>First seen</th><th>Vendor</th><th>Product</th><th>Listing</th><th class="num">Price</th></tr></thead>
        <tbody>${added.length ? added.map((e) => html`<tr>
          <td class="nowrap">${ilDateTime(e.at)}</td><td>${vendorLabel(s, e.vendor)}</td><td>${productLink(e)}</td>
          <td class="title">${link(e.url, e.title ?? "")}</td><td class="num">${ils(e.price)}</td>
        </tr>`) : emptyRow(5, "No vendor added an existing product in this period.")}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <h2 class="panel__title">Back on sale <span class="count">${returned.length}</span></h2>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Back on</th><th>Vendor</th><th>Listing</th><th class="num">Gone for</th><th class="num">Price</th></tr></thead>
        <tbody>${returned.length ? returned.map((e) => html`<tr>
          <td class="nowrap">${ilDateTime(e.at)}</td><td>${vendorLabel(s, e.vendor)}</td>
          <td class="title">${link(e.url, e.title ?? "")}</td><td class="num">${e.gone_days ?? "–"} d</td><td class="num">${ils(e.price)}</td>
        </tr>`) : emptyRow(5, "Nothing came back in this period.")}</tbody>
      </table></div>
    </section>`;
}

export function goneView(d: Data, f: Filters, now: Date): Html {
  if (!d.changes) return noChanges();
  const events = d.changes.events.filter((e) => inWindow(e, f, now) && matches(e, f));
  const products = events.filter((e) => e.type === "product_gone");
  const lost = events.filter((e) => e.type === "vendor_lost");
  const missing = d.changes.absent.filter((a) => a.state === "missing" && matches(a, f));
  const s = d.status;
  return html`
    <section class="panel">
      <h2 class="panel__title">No longer sold anywhere <span class="count">${products.length}</span></h2>
      <p class="panel__lede">Every listing of the product has been missing from two crawls, at least 36 hours apart, and the product is gone from the catalog.</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Gone since</th><th>Product</th><th>Category</th><th>Last sold by</th><th class="num">Last price</th></tr></thead>
        <tbody>${products.length ? products.map((e) => html`<tr>
          <td class="nowrap">${ilDateTime(e.at)}</td><td>${e.product || html`<span class="text-dim">${e.pid}</span>`}</td><td>${e.category}</td>
          <td>${(e.vendors ?? []).map((v) => vendorLabel(s, v)).join(", ")}</td><td class="num">${ils(e.price)}</td>
        </tr>`) : emptyRow(5, "No product disappeared in this period.")}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <h2 class="panel__title">A vendor stopped selling <span class="count">${lost.length}</span></h2>
      <p class="panel__lede">The product is still on the site through other vendors.</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Gone since</th><th>Vendor</th><th>Product</th><th>Listing</th><th class="num">Last price</th></tr></thead>
        <tbody>${lost.length ? lost.map((e) => html`<tr>
          <td class="nowrap">${ilDateTime(e.at)}</td><td>${vendorLabel(s, e.vendor)}</td><td>${productLink(e)}</td>
          <td class="title">${link(e.url, e.title ?? "")}</td><td class="num">${ils(e.price)}</td>
        </tr>`) : emptyRow(5, "No vendor dropped a product in this period.")}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <h2 class="panel__title">Missing from the latest crawl <span class="count">${missing.length}</span></h2>
      <p class="panel__lede">Absent once so far. One absence is often noise (1PC drops and re-adds dozens of rows a day); a second absence 36 hours later moves it up.</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Last seen</th><th>Vendor</th><th>Listing</th><th>Product</th><th class="num">Price</th></tr></thead>
        <tbody>${missing.length ? missing.map((a) => html`<tr>
          <td class="nowrap">${ilDateTime(a.last_seen)}</td><td>${vendorLabel(s, a.vendor)}</td>
          <td class="title">${link(a.url, a.title)}</td><td>${productLink(a)}</td><td class="num">${ils(a.price)}</td>
        </tr>`) : emptyRow(5, "Every listing from the previous crawl was seen again.")}</tbody>
      </table></div>
    </section>`;
}

export function pricesView(d: Data, f: Filters, now: Date): Html {
  if (!d.changes) return noChanges();
  const moves = d.changes.events
    .filter((e) => e.type === "price" && inWindow(e, f, now) && matches(e, f) && e.old && e.price)
    .map((e) => ({ e, delta: (e.price as number) - (e.old as number) }));
  const drops = moves.filter((m) => m.delta < 0).sort((a, b) => a.delta / (a.e.old as number) - b.delta / (b.e.old as number));
  const rises = moves.filter((m) => m.delta > 0).sort((a, b) => b.delta / (b.e.old as number) - a.delta / (a.e.old as number));
  const s = d.status;
  const table = (rows: typeof moves, empty: string) => html`<div class="table-wrap"><table class="table">
    <thead><tr><th>When</th><th>Vendor</th><th>Listing</th><th class="num">Was</th><th class="num">Now</th><th class="num">Change</th></tr></thead>
    <tbody>${rows.length ? rows.slice(0, 200).map(({ e, delta }) => html`<tr>
      <td class="nowrap">${ilDateTime(e.at)}</td><td>${vendorLabel(s, e.vendor)}</td>
      <td class="title">${link(e.url, e.title ?? "")}</td>
      <td class="num">${ils(e.old)}</td><td class="num">${ils(e.price)}</td>
      <td class="num ${delta < 0 ? "down" : "up"}">${pct(delta, e.old as number)}</td>
    </tr>`) : emptyRow(6, empty)}</tbody>
  </table></div>`;
  return html`
    <section class="panel">
      <h2 class="panel__title">Biggest drops <span class="count">${drops.length}</span></h2>
      <p class="panel__lede">Moves of 5% or more, last 14 days. Smaller moves are counted on each crawl (Calendar, hover) but not listed.</p>
      ${table(drops, "No price drops of 5% or more.")}
    </section>
    <section class="panel">
      <h2 class="panel__title">Biggest rises <span class="count">${rises.length}</span></h2>
      ${table(rises, "No price rises of 5% or more.")}
    </section>`;
}

// ---- Catalog ---------------------------------------------------------------------

export function catalogView(d: Data): Html {
  const cat = d.status.catalog;
  const vendorRows = d.status.vendors.filter((v) => v.active).map((v) => {
    const cv = cat.vendors[v.id];
    return html`<tr><th scope="row">${v.label}</th><td class="num">${n(cv?.listings)}</td>
      <td class="num">${cv?.stale ? html`<span class="warn">${n(cv.stale)}</span>` : "0"}</td><td>${cv?.last_seen ?? "–"}</td></tr>`;
  });
  const categories = Object.entries(cat.categories).sort((a, b) => b[1] - a[1]);
  const qa = Object.entries(cat.qa).sort((a, b) => b[1] - a[1]);
  const spec = Object.entries(cat.spec_counts);
  return html`
    <section class="panel">
      <h2 class="panel__title">Offers per vendor in the published catalog</h2>
      <p class="panel__lede">Stale offers are reused from an earlier snapshot because the vendor had none for the latest build (14-day limit).</p>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Vendor</th><th class="num">Listings</th><th class="num">Stale</th><th>Snapshot day</th></tr></thead>
        <tbody>${vendorRows}</tbody>
      </table></div>
    </section>
    <div class="grid2">
      <section class="panel">
        <h2 class="panel__title">Products per category</h2>
        <table class="table"><tbody>${categories.map(([k, v]) => html`<tr><th scope="row">${k}${k === "other" && v > 25 ? html` <span class="warn">(review bucket is growing)</span>` : ""}</th><td class="num">${n(v)}</td></tr>`)}</tbody></table>
      </section>
      <section class="panel">
        <h2 class="panel__title">Quality cases</h2>
        <p class="panel__lede"><a href="/#/qa" target="_blank" rel="noopener">Open the QA page</a>, or run <code>python -m scraper.qa_tool</code> to fix them.</p>
        <table class="table"><tbody>${qa.map(([k, v]) => html`<tr><th scope="row">${k.replace(/_/g, " ")}</th><td class="num">${n(v)}</td></tr>`)}</tbody></table>
        ${spec.length ? html`<h3 class="panel__sub">Spec report</h3><table class="table"><tbody>${spec.map(([k, v]) => html`<tr><th scope="row">${k.replace(/_/g, " ")}</th><td class="num">${n(v)}</td></tr>`)}</tbody></table>` : ""}
      </section>
    </div>`;
}

// ---- Log -------------------------------------------------------------------------

export function logView(d: Data, now: Date): Html {
  const runs = d.runs;
  const alerts = d.alerts;
  const unavailable = html`<p class="panel__lede">Not available here. Alerts and Nano runs come from the Worker on the deployed site (after the D1 migration in docs/ops-alerts.md).</p>`;
  return html`
    <section class="panel">
      <h2 class="panel__title">Alerts</h2>
      ${alerts === null ? unavailable : html`<div class="table-wrap"><table class="table">
        <thead><tr><th>Opened</th><th>Severity</th><th>Alert</th><th>Last pushed</th><th>Closed</th></tr></thead>
        <tbody>${alerts.length ? alerts.map((a) => html`<tr class="${a.closed_at ? "is-out" : ""}">
          <td class="nowrap">${ilDateTime(a.opened_at)}</td><td>${SEVERITY_LABEL[a.severity] ?? a.severity}</td>
          <td><strong>${a.title}</strong><br /><span class="text-dim">${a.detail}</span></td>
          <td class="nowrap">${a.last_push ? ago(a.last_push, now) : "held (quiet hours)"}</td>
          <td class="nowrap">${a.closed_at ? ilDateTime(a.closed_at) : html`<span class="warn">open</span>`}</td>
        </tr>`) : emptyRow(5, "No alerts yet.")}</tbody>
      </table></div>`}
    </section>
    <section class="panel">
      <h2 class="panel__title">Nano runs</h2>
      ${runs === null ? unavailable : html`<div class="table-wrap"><table class="table">
        <thead><tr><th>When</th><th>Vendor</th><th>Outcome</th><th class="num">Items</th><th>Detail</th></tr></thead>
        <tbody>${runs.length ? runs.map((r) => html`<tr>
          <td class="nowrap">${ilDateTime(r.at)}</td><td>${vendorLabel(d.status, r.vendor)}</td>
          <td><span class="${r.ok ? "up" : "down"}">${r.outcome}</span></td><td class="num">${n(r.items)}</td>
          <td class="text-dim">${r.detail ?? ""}</td>
        </tr>`) : emptyRow(5, "No Nano run reported yet. Install nano/ops_notify.sh on the Nano.")}</tbody>
      </table></div>`}
    </section>
    <section class="panel">
      <h2 class="panel__title">Links</h2>
      <ul class="links">
        <li><a href="https://github.com/Av1zi/Mifrat/actions" target="_blank" rel="noopener noreferrer">GitHub Actions runs</a></li>
        <li><a href="https://dash.cloudflare.com/" target="_blank" rel="noopener noreferrer">Cloudflare dashboard (Worker logs, analytics, secrets)</a></li>
        <li><a href="/#/qa" target="_blank" rel="noopener">Public QA page</a></li>
      </ul>
    </section>`;
}
