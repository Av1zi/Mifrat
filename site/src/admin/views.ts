// Admin console views. Each view is a pure (data, now) -> Html function; the
// shell in main.ts owns routing, loading and filters.

import { allVendorHealth, evaluate, nightStart, type Finding, type VendorHealth } from "../ops/rules";
import type { OpsAbsent, OpsChanges, OpsCrawl, OpsEvent, OpsStatus } from "../ops/types";
import { html, type Html } from "../ui/html";
import { safeUrl } from "../utils";
import type { AlertRow, RunRow } from "./data";
import { ago, ilDateKey, ilDateTime, ilDay, ilTime, ils, n, pct } from "./format";

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

/**
 * The two most recent nights side by side, each on its own night-only axis
 * (21:00 UTC - 1h to + 13h, i.e. 22:00-10:00 Israel in winter). A crawl is a
 * pill at its start time carrying its own label, a thin tick marks when the
 * vendor's run is due, and a night without a crawl says so in place:
 * "not scraped" once the due time passed, "due HH:MM" while it can still run.
 */
const HOUR = 3_600_000;
const NIGHT_BEFORE_H = 1;
const NIGHT_AFTER_H = 13;

function dueOf(h: VendorHealth, night: Date): Date {
  const [dh, dm] = h.vendor.due_utc.split(":").map(Number);
  const due = new Date(night.getTime());
  due.setUTCHours(dh || 0, dm || 0, 0, 0);
  if (due.getTime() <= night.getTime()) due.setUTCDate(due.getUTCDate() + 1);
  return due;
}

function nightPanel(health: VendorHealth[], crawls: Record<string, OpsCrawl[]>, night: Date, now: Date, title: string): Html {
  const start = night.getTime() - NIGHT_BEFORE_H * HOUR;
  const end = night.getTime() + NIGHT_AFTER_H * HOUR;
  const pos = (t: number) => Math.max(0, Math.min(100, ((t - start) / (end - start)) * 100));
  // In progress until the latest vendor due time has passed.
  const lastDue = Math.max(...health.map((h) => dueOf(h, night).getTime()));
  const live = now.getTime() >= night.getTime() && now.getTime() < lastDue;
  const ticks: Html[] = [];
  for (let t = start; t <= end; t += 2 * HOUR) {
    const edge = t === start ? " nb__tick--first" : t + 2 * HOUR > end ? " nb__tick--last" : "";
    ticks.push(html`<span class="${`nb__tick${edge}`}" style="${`inset-inline-start:${pos(t)}%`}">${ilTime(new Date(t).toISOString())}</span>`);
  }
  const rows = health.map((h) => {
    const mine = (crawls[h.vendor.id] ?? []).filter((c) => {
      const t = new Date(c.start).getTime();
      return t >= start && t < end;
    });
    const due = dueOf(h, night);
    const dueAt = pos(due.getTime());
    const pills = mine.map((c) => {
      const at = pos(new Date(c.start).getTime());
      const tone = c.suspect ? "partial" : mine.length > 1 || c.crawls_in_file > 1 ? "double" : "ok";
      const anchor = at > 62 ? "end" : "start";
      const tip = `${ilDateTime(c.start)}${c.start.slice(0, 16) === c.end.slice(0, 16) ? "" : `–${ilTime(c.end)}`} · ${n(c.keys)} items · +${c.new} new −${c.gone} gone${c.suspect ? ` · partial: ${c.suspect}` : ""}`;
      return html`<span class="nb__pill nb__pill--${tone} nb__pill--${anchor}" style="${`--at:${at}%`}" title="${tip}">
        <span class="nb__dot" aria-hidden="true"></span><strong>${ilTime(c.start)}</strong><span class="nb__n">${n(c.keys)}</span>
      </span>`;
    });
    let empty: Html = html``;
    if (!mine.length) {
      if (now.getTime() < due.getTime()) {
        empty = html`<span class="nb__pill nb__pill--pending nb__pill--${dueAt > 62 ? "end" : "start"}" style="${`--at:${dueAt}%`}">due ${ilTime(due.toISOString())}</span>`;
      } else {
        empty = html`<span class="nb__miss">Not scraped</span>`;
      }
    }
    return html`<div class="nb__row">
      <span class="nb__name">${h.vendor.label}</span>
      <span class="nb__track">
        <span class="nb__due" style="${`--at:${dueAt}%`}" title="${`Due by ${ilTime(due.toISOString())}`}" aria-hidden="true"></span>
        ${pills}${empty}
      </span>
    </div>`;
  });
  const nowLine = live ? html`<span class="nb__now" style="${`--at:${pos(now.getTime())}%`}" aria-hidden="true"></span>` : "";
  // Name the night by its evening: 18:00 UTC is 20:00/21:00 Israel, the same
  // calendar date in both seasons (21:00 UTC is already midnight in summer).
  const label = ilDay(new Date(night.getTime() - 3 * HOUR).toISOString());
  return html`<section class="nb${live ? " nb--live" : ""}" aria-label="${`Night of ${label}`}">
    <header class="nb__head">
      <h3>${title}</h3>
      <span>${label} evening${live ? " · in progress" : ""}</span>
    </header>
    <div class="nb__plot">
      <span class="nb__name" aria-hidden="true"></span>
      <span class="nb__axis">${ticks}${nowLine}</span>
    </div>
    ${rows}
  </section>`;
}

function nightBoard(health: VendorHealth[], crawls: Record<string, OpsCrawl[]>, now: Date): Html {
  // The newest night that has started, and the one before it. During the
  // night the newer one is "Tonight"; by morning it is "Last night".
  const current = nightStart(now);
  const lastDue = Math.max(...health.map((h) => dueOf(h, current).getTime()));
  const running = now.getTime() < lastDue;
  const previous = new Date(current.getTime() - 24 * HOUR);
  return html`<div class="nboard">
      ${nightPanel(health, crawls, previous, now, running ? "Last night" : "Night before")}
      ${nightPanel(health, crawls, current, now, running ? "Tonight" : "Last night")}
    </div>
    <p class="tl__caption">Israel time. A pill is one crawl (start time · items; hover for details). The thin mark is when that vendor's run is due.</p>`;
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
      <h2 class="panel__title">Nights</h2>
      ${nightBoard(activeHealth, d.status.crawls, now)}
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
// A month grid (Sun-Sat weeks, like a wall calendar): each day is one NIGHT,
// the evening of that date; a crawl after midnight counts for the evening
// before (the Israel date of start - 12h). Each day shows one chip per
// vendor; clicking a day opens its crawls below the grid.

type CellState = "ok" | "partial" | "double" | "none";

/** The night (Israel date, YYYY-MM-DD) a crawl belongs to. */
export function nightKey(iso: string): string {
  return ilDateKey(new Date(new Date(iso).getTime() - 12 * 3_600_000));
}

function cellState(crawls: OpsCrawl[]): CellState {
  if (!crawls.length) return "none";
  const c = crawls[crawls.length - 1];
  if (crawls.length > 1 || c.crawls_in_file > 1) return "double";
  return c.suspect ? "partial" : "ok";
}

function crawlsByNight(d: Data): Map<string, Map<string, OpsCrawl[]>> {
  const out = new Map<string, Map<string, OpsCrawl[]>>();
  for (const [vendor, list] of Object.entries(d.status.crawls)) {
    for (const c of list) {
      const k = nightKey(c.start);
      const day = out.get(k) ?? new Map<string, OpsCrawl[]>();
      day.set(vendor, [...(day.get(vendor) ?? []), c]);
      out.set(k, day);
    }
  }
  return out;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function ymd(y: number, m: number, day: number): string {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export interface CalendarState {
  /** "YYYY-MM" shown; default = the current Israel month. */
  month: string;
  /** Selected night "YYYY-MM-DD", or "". */
  day: string;
}

function dayDetail(d: Data, key: string, nights: Map<string, Map<string, OpsCrawl[]>>): Html {
  const day = nights.get(key);
  const vendors = d.status.vendors.filter((v) => v.active || day?.has(v.id));
  const date = new Date(`${key}T12:00:00Z`);
  const rows = vendors.map((v) => {
    const crawls = day?.get(v.id) ?? [];
    if (!crawls.length) {
      return html`<tr><th scope="row">${v.label}</th><td colspan="6"><span class="down">Not scraped</span></td></tr>`;
    }
    return crawls.map((c, i) => html`<tr>
      <th scope="row">${i === 0 ? v.label : ""}</th>
      <td class="nowrap">${ilTime(c.start)}${c.start.slice(0, 16) === c.end.slice(0, 16) ? "" : `–${ilTime(c.end)}`}</td>
      <td class="num">${n(c.keys)}</td>
      <td class="num up">${c.baseline ? "–" : `+${c.new}`}</td>
      <td class="num down">${c.baseline ? "–" : `−${c.gone}`}</td>
      <td class="num">${c.baseline ? "–" : c.missing}</td>
      <td>${[
        c.suspect ? `partial: ${c.suspect}` : "",
        c.crawls_in_file > 1 ? `${c.crawls_in_file} crawls in ${c.file_day} file` : "",
        c.misfiled ? `in the ${c.file_day} file` : "",
        c.outside_window ? "late start" : "",
        c.baseline ? "first crawl in the window" : "",
      ].filter(Boolean).join(" · ")}</td>
    </tr>`);
  });
  return html`<section class="panel" id="cal-day">
    <h2 class="panel__title">Night of ${ilDay(date.toISOString())}</h2>
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Vendor</th><th>Time (Israel)</th><th class="num">Items</th><th class="num">New</th><th class="num">Gone</th><th class="num">Missing</th><th>Notes</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </section>`;
}

export function calendarView(d: Data, now: Date, state: CalendarState): Html {
  const nights = crawlsByNight(d);
  const today = nightKey(now.toISOString());
  const [y, m] = (state.month || today.slice(0, 7)).split("-").map(Number);
  const month = m - 1;
  const first = new Date(Date.UTC(y, month, 1));
  const daysIn = new Date(Date.UTC(y, month + 1, 0)).getUTCDate();
  const lead = first.getUTCDay(); // Sunday-first weeks, like an Israeli calendar
  const vendors = d.status.vendors.filter((v) => v.active);
  const windowStart = nightKey(new Date(now.getTime() - d.status.window_days * 86_400_000).toISOString());

  const prev = month === 0 ? `${y - 1}-12` : `${y}-${String(month).padStart(2, "0")}`;
  const next = month === 11 ? `${y + 1}-01` : `${y}-${String(month + 2).padStart(2, "0")}`;
  // Months before the report window hold no data; months after today none yet.
  const canPrev = ymd(y, month, 1) > windowStart;
  const canNext = next <= today.slice(0, 7);

  let okNights = 0;
  let badNights = 0;
  const cells: Html[] = [];
  for (let i = 0; i < lead; i++) cells.push(html`<div class="mcal__day mcal__day--pad" aria-hidden="true"></div>`);
  for (let day = 1; day <= daysIn; day++) {
    const key = ymd(y, month, day);
    const future = key > today;
    const outside = key < windowStart;
    const night = nights.get(key);
    // Tonight is still running: a vendor with no crawl yet is pending, not missing.
    const inProgress = key === today;
    const stateOf = (id: string): CellState | "pending" => {
      const s = cellState(night?.get(id) ?? []);
      return s === "none" && inProgress ? "pending" : s;
    };
    const chips = vendors.map((v) => {
      const s = stateOf(v.id);
      const c = night?.get(v.id)?.at(-1);
      const tip = c ? `${v.label}: ${n(c.keys)} items at ${ilTime(c.start)}` : `${v.label}: ${s === "pending" ? "not run yet tonight" : "not scraped"}`;
      return html`<span class="mchip mchip--${s}" title="${tip}"><span>${v.label}</span></span>`;
    });
    const states = vendors.map((v) => stateOf(v.id));
    if (!future && !outside && !(inProgress && states.includes("pending"))) {
      if (states.every((s) => s === "ok")) okNights++;
      else badNights++;
    }
    const allOk = states.every((s) => s === "ok");
    const missing = states.filter((s) => s === "none").length;
    const pending = states.filter((s) => s === "pending").length;
    const summary = future ? "" : outside ? "before the report window" : allOk ? "all scraped"
      : missing ? `${missing} not scraped` : pending ? `in progress, ${pending} still to run` : "check";
    const cls = `mcal__day${key === today ? " is-today" : ""}${key === state.day ? " is-selected" : ""}${future ? " is-future" : ""}${outside ? " is-outside" : ""}`;
    const body = html`<span class="mcal__num">${day}</span>
      ${future || outside ? "" : html`<span class="mcal__chips">${chips}</span>`}
      <span class="visually-hidden">${summary}</span>`;
    cells.push(future || outside
      ? html`<div class="${cls}">${body}</div>`
      : html`<a class="${cls}" href="${`#calendar?month=${y}-${String(month + 1).padStart(2, "0")}&day=${key}`}" aria-label="${`${day} ${MONTHS[month]}: ${summary}`}">${body}</a>`);
  }

  return html`<section class="panel mcal">
    <header class="mcal__head">
      <h2 class="mcal__title">${MONTHS[month]} ${y}</h2>
      <p class="mcal__sum">${okNights} night${okNights === 1 ? "" : "s"} all scraped${badNights ? html`, <span class="warn">${badNights} with a problem</span>` : ""}</p>
      <nav class="mcal__nav" aria-label="Month">
        ${canPrev ? html`<a class="mcal__btn" href="${`#calendar?month=${prev}`}" aria-label="Previous month">‹</a>` : html`<span class="mcal__btn is-off" aria-hidden="true">‹</span>`}
        <a class="mcal__btn mcal__btn--today" href="#calendar">Today</a>
        ${canNext ? html`<a class="mcal__btn" href="${`#calendar?month=${next}`}" aria-label="Next month">›</a>` : html`<span class="mcal__btn is-off" aria-hidden="true">›</span>`}
      </nav>
    </header>
    <div class="mcal__grid" role="grid">
      ${WEEKDAYS.map((w) => html`<div class="mcal__wd" role="columnheader">${w}</div>`)}
      ${cells}
    </div>
    <p class="legend">
      <span class="legend__item"><span class="cal__swatch mchip--ok"></span>Scraped</span>
      <span class="legend__item"><span class="cal__swatch mchip--partial"></span>Partial crawl</span>
      <span class="legend__item"><span class="cal__swatch mchip--double"></span>Two crawls in one night or file</span>
      <span class="legend__item"><span class="cal__swatch mchip--none"></span>Not scraped</span>
      <span class="legend__item"><span class="cal__swatch mchip--pending"></span>Tonight, not run yet</span>
      <span class="legend__item">Each day is one night (a crawl after midnight counts for the evening before). Click a day for its crawls.</span>
    </p>
  </section>
  ${state.day ? dayDetail(d, state.day, nights) : ""}`;
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
// What the published catalog holds: per vendor (how much it contributes,
// stale offers), per category (size, how many vendors sell each product -
// the comparison value of the site - and the price range), and the quality
// queue. Bars, not tables of numbers.

const CATEGORY_NAMES: Record<string, string> = {
  cpu: "Processors", motherboard: "Motherboards", memory: "Memory", gpu: "Graphics cards",
  storage: "Storage", psu: "Power supplies", case: "Cases", case_fan: "Case fans",
  cooler_air: "Air coolers", aio: "Liquid coolers", accessories: "Accessories", other: "Other (review bucket)",
};

const QA_NAMES: Record<string, string> = {
  variant_conflict: "Variant conflicts", spec_conflict: "Spec conflicts", identity_merge: "Identity merges",
  packaging_conflict: "Box / tray conflicts", duplicate_vendor: "Vendor listed twice", core_gap: "Core spec gaps",
  split_candidate: "Split candidates", unflagged_deal: "Unflagged deals",
};

function categoryName(id: string): string {
  return CATEGORY_NAMES[id] ?? id.replace(/_/g, " ");
}

function bar(parts: { value: number; cls: string; label: string }[], total: number): Html {
  return html`<span class="sbar" role="img" aria-label="${parts.map((p) => `${p.label}: ${n(p.value)}`).join(", ")}">${parts
    .filter((p) => p.value > 0)
    .map((p) => html`<span class="sbar__seg ${p.cls}" style="${`width:${(100 * p.value) / (total || 1)}%`}" title="${`${p.label}: ${n(p.value)}`}"></span>`)}</span>`;
}

export function catalogView(d: Data): Html {
  const cat = d.status.catalog;
  const vendors = d.status.vendors.filter((v) => v.active);
  const detail = cat.category_detail ?? {};
  const multi = Object.values(detail).reduce((s, c) => s + c.sellers["2"] + c.sellers["3+"], 0);
  const qaTotal = Object.values(cat.qa).reduce((a, b) => a + b, 0);
  const stale = Object.values(cat.vendors).reduce((a, v) => a + v.stale, 0);

  const tiles = html`<section class="tiles">
    <div class="tile"><span class="tile__v">${n(cat.products)}</span><span class="tile__k">products</span></div>
    <div class="tile"><span class="tile__v">${n(cat.listings)}</span><span class="tile__k">offers from ${vendors.length} vendors</span></div>
    <div class="tile"><span class="tile__v">${cat.products ? Math.round((100 * multi) / cat.products) : 0}%</span><span class="tile__k">sold by 2+ vendors (comparable)</span></div>
    <div class="tile${stale ? " tile--warn" : ""}"><span class="tile__v">${n(stale)}</span><span class="tile__k">stale offers</span></div>
    <div class="tile"><span class="tile__v">${n(qaTotal)}</span><span class="tile__k">open quality cases</span></div>
  </section>`;

  const maxListings = Math.max(1, ...vendors.map((v) => cat.vendors[v.id]?.listings ?? 0));
  const vendorRows = vendors.map((v) => {
    const cv = cat.vendors[v.id];
    const listings = cv?.listings ?? 0;
    const staleN = cv?.stale ?? 0;
    return html`<li class="hrow">
      <span class="hrow__name">${v.label}</span>
      <span class="hrow__bar">${bar([
        { value: listings - staleN, cls: "sbar__seg--ok", label: "fresh" },
        { value: staleN, cls: "sbar__seg--warn", label: "stale" },
      ], maxListings)}</span>
      <span class="hrow__v">${n(listings)}</span>
      <span class="hrow__note">${staleN ? html`<span class="warn">${n(staleN)} stale · snapshot ${cv?.last_seen}</span>` : html`snapshot ${cv?.last_seen ?? "–"}`}</span>
    </li>`;
  });

  const cats = Object.entries(cat.categories).sort((a, b) => b[1] - a[1]);
  const maxCat = Math.max(1, ...cats.map(([, v]) => v));
  const catCards = cats.map(([id, count]) => {
    const c = detail[id];
    const warn = id === "other" && count > 25;
    return html`<article class="ccard${warn ? " ccard--warn" : ""}">
      <header class="ccard__head">
        <h3>${categoryName(id)}</h3>
        <span class="ccard__count">${n(count)}</span>
      </header>
      <span class="ccard__size" style="${`width:${(100 * count) / maxCat}%`}" aria-hidden="true"></span>
      ${c ? html`
        <p class="ccard__k">Sold by</p>
        ${bar([
          { value: c.sellers["3+"], cls: "sbar__seg--s3", label: "3+ vendors" },
          { value: c.sellers["2"], cls: "sbar__seg--s2", label: "2 vendors" },
          { value: c.sellers["1"], cls: "sbar__seg--s1", label: "1 vendor" },
        ], c.products)}
        <p class="ccard__legend"><span>${n(c.sellers["3+"])} by 3+</span><span>${n(c.sellers["2"])} by 2</span><span>${n(c.sellers["1"])} by 1</span></p>
        <p class="ccard__k">Vendors</p>
        <p class="ccard__vendors">${vendors.filter((v) => c.by_vendor[v.id]).map((v) => html`<span class="vchip"><span class="vdot vdot--${v.id}"></span>${v.label} ${n(c.by_vendor[v.id])}</span>`)}</p>
        <p class="ccard__price">${c.min_price != null ? `${ils(c.min_price)} – ${ils(c.max_price)}` : ""} · ${Math.round((100 * c.in_stock) / (c.products || 1))}% in stock</p>`
        : ""}
      ${warn ? html`<p class="warn ccard__price">Should stay near-empty: the classifier needs a rule.</p>` : ""}
    </article>`;
  });

  const qa = Object.entries(cat.qa).sort((a, b) => b[1] - a[1]);
  const maxQa = Math.max(1, ...qa.map(([, v]) => v));
  const qaRows = qa.map(([k, v]) => html`<li class="hrow">
    <span class="hrow__name">${QA_NAMES[k] ?? k.replace(/_/g, " ")}</span>
    <span class="hrow__bar">${bar([{ value: v, cls: "sbar__seg--brand", label: k }], maxQa)}</span>
    <span class="hrow__v">${n(v)}</span>
  </li>`);

  return html`
    ${tiles}
    <section class="panel">
      <h2 class="panel__title">Offers per vendor</h2>
      <p class="panel__lede">Stale offers (amber) are reused from an earlier snapshot because the vendor had none for the latest build; the site shows them as stale for up to 14 days.</p>
      <ul class="hbars">${vendorRows}</ul>
    </section>
    <section class="panel">
      <h2 class="panel__title">Categories</h2>
      <p class="panel__lede">The grey bar is the category's size. "Sold by" is how many vendors offer each product: the darker the bar, the more parts a visitor can actually compare.</p>
      <div class="ccards">${catCards}</div>
    </section>
    <section class="panel">
      <h2 class="panel__title">Quality queue</h2>
      <p class="panel__lede"><a href="/#/qa" target="_blank" rel="noopener">Open the QA page</a>, or run <code>python -m scraper.qa_tool</code> locally to fix cases.</p>
      <ul class="hbars">${qaRows}</ul>
    </section>`;
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
