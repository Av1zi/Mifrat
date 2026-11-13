// Health rules over data/ops/status.json: what is late, missing, partial or
// stale right now. Pure functions of (status, now, live facts) so the admin
// page and the Worker's alert cron reach the same verdicts, and tests pin
// them with a fixed clock.
//
// The report only records facts (crawl times and counts); "missing" depends
// on the clock and is decided here. A report that stopped updating is itself
// a finding, so a dead pipeline cannot look healthy.

import type { OpsCrawl, OpsStatus, OpsVendor } from "./types";

export type Severity = "urgent" | "high" | "warn" | "info";

export interface Finding {
  /** Stable id: an alert opens, reminds and resolves per key. */
  key: string;
  severity: Severity;
  title: string;
  detail: string;
  /** Vendor id, when the finding is about one vendor. */
  vendor?: string;
}

/** Live checks the Worker cron adds; the admin page passes none. */
export interface LiveFacts {
  /** Home page / meta.json fetch result (null = not checked). */
  siteOk?: boolean | null;
  /** generated_at of the DEPLOYED meta.json (null = not checked). */
  deployedCatalogAt?: string | null;
  /** Rate-limited /api requests in the last cron interval. */
  abuseHits?: number | null;
  /** Latest Nano run report per vendor (POST /api/ops/event). */
  nanoRuns?: Record<string, NanoRun>;
}

export interface NanoRun {
  vendor: string;
  at: string;
  ok: boolean;
  /** "blocked" | "failed" | "partial" | "ok" | free text from the script. */
  outcome: string;
  detail?: string;
}

export type VendorState =
  | "fresh"
  | "partial"
  | "late"
  | "missing"
  | "dropped";

export interface VendorHealth {
  vendor: OpsVendor;
  state: VendorState;
  /** The newest crawl in the report, if any. */
  last: OpsCrawl | null;
  /** The newest crawl that counts for tonight (started after the night began). */
  tonight: OpsCrawl | null;
  /** Hours since the last crawl started. */
  ageHours: number | null;
  /** Catalog side: this vendor's offers are stale-forwarded. */
  staleInCatalog: boolean;
  notes: string[];
}

const HOUR = 3_600_000;
/** The report is rebuilt after every normalize; older than this = stuck. */
export const REPORT_MAX_AGE_HOURS = 30;
/** A deployed catalog this far behind the repo's = deploy not running. */
export const DEPLOY_LAG_HOURS = 6;
/** Rate-limited /api requests per cron interval that read as an attack. */
export const ABUSE_THRESHOLD = 300;
/** The night window starts 21:00 UTC (23:00/00:00 Israel). */
export const NIGHT_START_UTC_HOUR = 21;

export const SEVERITY_RANK: Record<Severity, number> = { urgent: 0, high: 1, warn: 2, info: 3 };

function parseHm(hm: string): [number, number] {
  const [h, m] = hm.split(":").map(Number);
  return [h || 0, m || 0];
}

/**
 * The start of the night whose crawl is expected by `now`: the most recent
 * 21:00 UTC at or before `now`... unless we are still before that night's
 * due time, in which case the previous night is the one that must be done.
 */
export function nightStart(now: Date): Date {
  const start = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), NIGHT_START_UTC_HOUR)
  );
  if (start.getTime() > now.getTime()) start.setUTCDate(start.getUTCDate() - 1);
  return start;
}

/** When `vendor`'s crawl for the night starting at `night` is due. */
export function dueAt(vendor: OpsVendor, night: Date): Date {
  const [h, m] = parseHm(vendor.due_utc);
  const due = new Date(night.getTime());
  due.setUTCHours(h, m, 0, 0);
  if (due.getTime() <= night.getTime()) due.setUTCDate(due.getUTCDate() + 1);
  return due;
}

/**
 * The night whose crawl should exist by now: the latest night whose due time
 * has passed. Before tonight's due time that is last night.
 */
export function expectedNight(vendor: OpsVendor, now: Date): Date {
  let night = nightStart(now);
  if (dueAt(vendor, night).getTime() > now.getTime()) {
    night = new Date(night.getTime() - 24 * HOUR);
  }
  return night;
}

function hoursBetween(a: Date, b: Date): number {
  return (b.getTime() - a.getTime()) / HOUR;
}

export function vendorHealth(status: OpsStatus, vendor: OpsVendor, now: Date): VendorHealth {
  const crawls = status.crawls[vendor.id] ?? [];
  const last = crawls.length ? crawls[crawls.length - 1] : null;
  const catalogVendor = status.catalog.vendors[vendor.id];
  // normalize marks offers stale whenever the snapshot day is not the build
  // day, so a 23:50 UTC crawl is "stale" at 03:31 UTC. Only a catalog that is
  // 2+ days behind the vendor is worth a note.
  const builtDay = (status.catalog.generated_at ?? "").slice(0, 10);
  const lagDays = catalogVendor?.last_seen && builtDay
    ? (Date.parse(builtDay) - Date.parse(catalogVendor.last_seen)) / 86_400_000
    : 0;
  const staleInCatalog = !!catalogVendor && catalogVendor.stale > 0 && lagDays >= 2;
  const notes: string[] = [];
  const ageHours = last ? hoursBetween(new Date(last.start), now) : null;

  if (!vendor.active) {
    return { vendor, state: "dropped", last, tonight: null, ageHours, staleInCatalog, notes };
  }

  // The newest crawl since the expected night began. Between 21:00 UTC and
  // a vendor's due time that includes a crawl of the night now running
  // (TMS at 23:19 Israel): it is newer, so it counts; last night's is done.
  const night = expectedNight(vendor, now);
  const tonightCrawls = crawls.filter((c) => new Date(c.start).getTime() >= night.getTime());
  const tonight = tonightCrawls.length ? tonightCrawls[tonightCrawls.length - 1] : null;

  let state: VendorState;
  if (tonight) {
    state = tonight.suspect ? "partial" : "fresh";
    if (tonight.suspect) notes.push(`partial crawl: ${tonight.suspect}`);
  } else {
    // Nothing since the expected night began. "late" while tonight's crawl
    // could still be running (before its due time), "missing" after.
    const currentNight = nightStart(now);
    const runningTonight =
      night.getTime() === currentNight.getTime() &&
      now.getTime() < dueAt(vendor, currentNight).getTime();
    state = runningTonight ? "late" : "missing";
  }

  if (tonight?.crawls_in_file && tonight.crawls_in_file > 1) {
    notes.push(`${tonight.crawls_in_file} crawls in one file (${tonight.file_day})`);
  }
  if (tonight?.misfiled) notes.push(`written to the ${tonight.file_day} file`);
  if (tonight?.outside_window) notes.push("ran outside the night window");
  if (staleInCatalog) notes.push(`catalog still shows the ${catalogVendor!.last_seen} snapshot (${catalogVendor!.stale} stale offers)`);
  return { vendor, state, last, tonight, ageHours, staleInCatalog, notes };
}

export function allVendorHealth(status: OpsStatus, now: Date): VendorHealth[] {
  return status.vendors.map((v) => vendorHealth(status, v, now));
}

function ago(hours: number | null): string {
  if (hours === null) return "never";
  if (hours < 48) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/**
 * Every current problem, most severe first. Missing home vendors are grouped
 * into one "Nano down?" finding when all of them are missing.
 */
export function evaluate(status: OpsStatus, now: Date, live: LiveFacts = {}): Finding[] {
  const findings: Finding[] = [];
  const reportAge = hoursBetween(new Date(status.generated_at), now);
  if (reportAge > REPORT_MAX_AGE_HOURS) {
    findings.push({
      key: "report-stale",
      severity: "high",
      title: "Pipeline report is stale",
      detail: `data/ops was last rebuilt ${ago(reportAge)}: normalize-and-deploy may not be running.`,
    });
  }

  const health = allVendorHealth(status, now).filter((h) => h.vendor.active);
  const home = health.filter((h) => h.vendor.host === "home");
  const homeAllMissing = home.length > 0 && home.every((h) => h.state === "missing");
  if (homeAllMissing) {
    findings.push({
      key: "nano-down",
      severity: "high",
      title: "No home scrapes: is the Nano down?",
      detail: home
        .map((h) => `${h.vendor.label} last ${ago(h.ageHours)}`)
        .join(", "),
    });
  }

  for (const h of health) {
    const label = h.vendor.label;
    const run = live.nanoRuns?.[h.vendor.id];
    if (run && !run.ok && run.outcome === "blocked") {
      findings.push({
        key: `blocked:${h.vendor.id}`,
        severity: "urgent",
        vendor: h.vendor.id,
        title: `${label} blocked the scraper`,
        detail: `${run.detail || "HTTP 403/429 or a challenge page"} at ${run.at}. Scraping rules: a block is a stop signal; decide before the next run.`,
      });
    } else if (run && !run.ok) {
      findings.push({
        key: `run-failed:${h.vendor.id}`,
        severity: "high",
        vendor: h.vendor.id,
        title: `${label} run failed`,
        detail: `${run.outcome}${run.detail ? `: ${run.detail}` : ""} at ${run.at}`,
      });
    }
    if (h.state === "missing" && !(homeAllMissing && h.vendor.host === "home")) {
      findings.push({
        key: `missing:${h.vendor.id}`,
        severity: "high",
        vendor: h.vendor.id,
        title: `${label} was not scraped last night`,
        detail: `Last crawl ${ago(h.ageHours)}${h.last ? ` (${h.last.keys} items)` : ""}; due by ${h.vendor.due_utc} UTC.`,
      });
    }
    if (h.state === "partial") {
      findings.push({
        key: `partial:${h.vendor.id}`,
        severity: "warn",
        vendor: h.vendor.id,
        title: `${label} crawl looks partial`,
        detail: h.tonight?.suspect ?? "",
      });
    }
    if (h.tonight && h.tonight.crawls_in_file > 1) {
      findings.push({
        key: `double:${h.vendor.id}:${h.tonight.file_day}`,
        severity: "warn",
        vendor: h.vendor.id,
        title: `${label}: ${h.tonight.crawls_in_file} crawls in one file`,
        detail: `data/raw/${h.tonight.file_day}/${h.vendor.id}.jsonl holds more than one night (old Nano script?).`,
      });
    }
    const keys = h.tonight?.keys ?? 0;
    if (h.tonight && !h.tonight.suspect && keys > 0 && h.tonight.gone / keys > 0.05) {
      findings.push({
        key: `delist-spike:${h.vendor.id}:${h.tonight.start.slice(0, 10)}`,
        severity: "warn",
        vendor: h.vendor.id,
        title: `${label} delisted ${h.tonight.gone} items at once`,
        detail: `${((100 * h.tonight.gone) / keys).toFixed(1)}% of its ${keys} listings: a catalog change or a broken parser.`,
      });
    }
  }

  const skipped = status.catalog.skipped_vendors.filter((v) =>
    status.vendors.some((x) => x.id === v && x.active)
  );
  if (skipped.length) {
    findings.push({
      key: `skipped:${skipped.join(",")}`,
      severity: "high",
      title: `Catalog skipped ${skipped.join(", ")}`,
      detail: "No snapshot in the 14-day stale-forward window: those offers are off the site.",
    });
  }

  if (live.siteOk === false) {
    findings.push({
      key: "site-down",
      severity: "urgent",
      title: "Site is down",
      detail: "The home page or /data/site/meta.json did not answer 200.",
    });
  }
  if (live.deployedCatalogAt && status.catalog.generated_at) {
    const lag = hoursBetween(new Date(live.deployedCatalogAt), new Date(status.catalog.generated_at));
    if (lag > DEPLOY_LAG_HOURS) {
      findings.push({
        key: "deploy-behind",
        severity: "high",
        title: "Site is serving an old catalog",
        detail: `Deployed catalog is ${Math.round(lag)}h older than the repo's: Workers Builds may be failing.`,
      });
    }
  }
  if (live.abuseHits != null && live.abuseHits >= ABUSE_THRESHOLD) {
    findings.push({
      key: "abuse",
      severity: "urgent",
      title: "API flood (possible attack)",
      detail: `${live.abuseHits} rate-limited /api requests in the last check interval.`,
    });
  }

  findings.sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.key.localeCompare(b.key));
  return findings;
}

/** Israel wall clock for `at` ("HH:MM"), DST-correct. */
export function israelTime(at: Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jerusalem",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(at);
}

/** Israel calendar date + hour, for the 10:00 report gate. */
export function israelParts(at: Date): { date: string; hour: number; weekday: string } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jerusalem",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    weekday: "short",
  }).formatToParts(at);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    hour: Number(get("hour")) % 24,
    weekday: get("weekday"),
  };
}
