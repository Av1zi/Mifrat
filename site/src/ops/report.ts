// The 10:00 daily scrape report (owner, 2026-11-12): one ntfy message with a
// line per vendor. Silent (priority 2) when every line is OK, priority 3 when
// something needs a look. Pure: (status, findings, now) -> message.

import { allVendorHealth, israelParts, israelTime, type Finding, type VendorHealth } from "./rules";
import type { OpsStatus } from "./types";

export interface PushMessage {
  title: string;
  message: string;
  /** ntfy priority: 1 min, 2 low (silent), 3 default, 4 high, 5 urgent. */
  priority: 1 | 2 | 3 | 4 | 5;
  tags: string[];
  /** Path on the site the notification opens (joined to the origin). */
  click: string;
}

/** ntfy caps a message at 4096 bytes; stay well under with room for UTF-8. */
export const MAX_MESSAGE_CHARS = 3500;

function count(n: number): string {
  return n.toLocaleString("en-US");
}

function crawlTime(iso: string): string {
  return israelTime(new Date(iso));
}

function vendorLine(h: VendorHealth): { ok: boolean; text: string } {
  const label = h.vendor.label.padEnd(7);
  const c = h.tonight;
  if (h.state === "missing" || h.state === "late") {
    const last = h.last
      ? `last ${israelParts(new Date(h.last.start)).date.slice(5)} ${crawlTime(h.last.start)} (${count(h.last.keys)})`
      : "never scraped";
    return { ok: false, text: `❌ ${label} not scraped · ${last}` };
  }
  if (!c) return { ok: false, text: `❌ ${label} no crawl` };
  const span = c.start.slice(0, 16) === c.end.slice(0, 16)
    ? crawlTime(c.start)
    : `${crawlTime(c.start)}–${crawlTime(c.end)}`;
  const delta = c.baseline ? "baseline" : `+${c.new} new −${c.gone} gone`;
  const flags = [...h.notes];
  // GitHub fires the cloud scrape crons up to ~5h late (2026-11-12: the
  // 21:07 UTC run started 02:13, the 02:47 fallback 10:20), so a cloud crawl
  // after 04:00 UTC is common and not the vendor's fault: shown, not counted.
  const informational = new Set(["ran outside the night window"]);
  const ok = h.state === "fresh" && flags.every((f) => informational.has(f));
  const mark = ok ? "✅" : "⚠️";
  if (ok && flags.length) {
    return {
      ok,
      text: `${mark} ${label} ${count(c.keys).padStart(5)} · ${span} · ${delta} · late start`,
    };
  }
  return {
    ok,
    text: `${mark} ${label} ${count(c.keys).padStart(5)} · ${span} · ${delta}` +
      (flags.length ? `\n     ${flags.join("; ")}` : ""),
  };
}

export function dailyReport(status: OpsStatus, findings: Finding[], now: Date): PushMessage {
  const day = israelParts(now);
  const health = allVendorHealth(status, now).filter((h) => h.vendor.active);
  const lines = health.map(vendorLine);
  const cat = status.catalog;

  const body: string[] = ["Scrapes last night (Israel time)", ...lines.map((l) => l.text), ""];
  if (cat.generated_at) {
    const built = new Date(cat.generated_at);
    body.push(
      `Catalog: ${count(cat.products)} products, built ${israelParts(built).date.slice(5)} ${israelTime(built)}` +
        (cat.skipped_vendors.length ? ` · skipped ${cat.skipped_vendors.join(", ")}` : "")
    );
  }
  const tonight = health.map((h) => h.tonight).filter((c) => c && !c.baseline);
  const added = tonight.reduce((n, c) => n + (c?.new ?? 0), 0);
  const gone = tonight.reduce((n, c) => n + (c?.gone ?? 0), 0);
  body.push(`Listings: +${added} new, −${gone} gone`);
  const qa = Object.values(cat.qa).reduce((a, b) => a + b, 0);
  if (qa) body.push(`QA cases: ${count(qa)}`);

  // Findings that are not already a vendor line (site, deploy, pipeline).
  const vendorKeys = new Set(health.map((h) => h.vendor.id));
  const other = findings.filter((f) => !f.vendor || !vendorKeys.has(f.vendor));
  if (other.length) {
    body.push("", "Open problems:");
    for (const f of other) body.push(`• ${f.title}`);
  }

  const allOk = lines.every((l) => l.ok) && findings.length === 0;
  let message = body.join("\n");
  if (message.length > MAX_MESSAGE_CHARS) message = message.slice(0, MAX_MESSAGE_CHARS - 1) + "…";
  return {
    title: `Mifrat daily report · ${day.weekday} ${day.date.slice(8)}/${day.date.slice(5, 7)}` +
      (allOk ? " · all OK" : ` · ${lines.filter((l) => !l.ok).length + other.length} need a look`),
    message,
    priority: allOk ? 2 : 3,
    tags: [allOk ? "white_check_mark" : "warning"],
    click: "/admin/",
  };
}

/** A push for one alert opening, reminding or resolving. */
export function alertMessage(f: Finding, kind: "open" | "remind" | "resolved"): PushMessage {
  if (kind === "resolved") {
    return {
      title: `Resolved: ${f.title}`,
      message: f.detail || "Back to normal.",
      priority: 2,
      tags: ["white_check_mark"],
      click: "/admin/",
    };
  }
  const priority = f.severity === "urgent" ? 5 : f.severity === "high" ? 4 : 3;
  return {
    title: (kind === "remind" ? "Still open: " : "") + f.title,
    message: f.detail || f.title,
    priority,
    tags: [f.severity === "urgent" ? "rotating_light" : "warning"],
    click: "/admin/",
  };
}
