import { checkCompatibility, numSpec, type CompatCode, type CompatIssue } from "../../build";
import { formatPrice } from "../../format";
import { compatMessage, compatOkMessage, issuesSummary, partsCount, t, vendorLabel, wattOf } from "../../i18n";
import { icon } from "../../icons";
import { bestOffer, effectivePrice } from "../../offers";
import { buildItemCount } from "../../state";
import type { Product } from "../../types";
import { html, type Html } from "../../ui/html";
import { vendorDot, vendorKey } from "../../ui/vendor";
import { buildWatts, firstPicks, type BuilderCtx } from "./parts";

type StripLevel = "idle" | "ok" | "warn" | "err";

interface Summary {
  issues: CompatIssue[];
  level: StripLevel;
  watts: number;
  hasParts: boolean;
}

export function summarize(ctx: BuilderCtx): Summary {
  const watts = buildWatts(ctx);
  const issues = checkCompatibility(firstPicks(ctx), watts);
  const hasParts = buildItemCount(ctx.build) > 0;
  const level: StripLevel = !hasParts
    ? "idle"
    : issues.some((i) => i.level === "err")
      ? "err"
      : issues.length > 0
        ? "warn"
        : "ok";
  return { issues, level, watts, hasParts };
}

const STRIP_ICON = { idle: "shield", ok: "circle-check", warn: "alert", err: "circle-x" } as const;

/** Verdict bar under the share row: compatibility (links to the checks) and the known wattage. */
export function statusMarkup(ctx: BuilderCtx, summary: Summary): Html {
  const { lang } = ctx;
  const { issues, level, watts, hasParts } = summary;
  const errors = issues.filter((i) => i.level === "err").length;
  const message =
    level === "idle"
      ? t(lang, "compatibilityIdle")
      : level === "ok"
        ? t(lang, "compatStripOk")
        : issuesSummary(lang, errors, issues.length - errors);
  const psu = ctx.parts.get("psu")?.[0];
  const capacity = psu ? numSpec(psu, ["wattage_w"]) : null;
  const meterLevel = capacity === null ? "" : watts > capacity ? " meter--err" : watts > capacity * 0.8 ? " meter--warn" : " meter--ok";
  return html`<div class="build-status" role="status">
    <a class="build-status__compat build-status__compat--${level}" href="#compat" data-jump="compat">
      ${icon(STRIP_ICON[level], 18)}<span>${message}</span>${hasParts ? html`<u>${t(lang, "detailsLink")}</u>` : ""}
    </a>
    ${hasParts
      ? html`<span class="build-status__watts">
          ${icon("bolt", 16)}<span>${t(lang, "wattageEstimate")}: <b class="num">${watts}W</b></span>
          ${capacity !== null
            ? html`<progress class="meter${meterLevel}" max="${capacity}" value="${Math.min(watts, capacity)}" aria-label="${t(lang, "wattageShort")}"></progress><span class="build-status__of">${wattOf(lang, capacity)}</span>`
            : ""}
        </span>`
      : ""}
  </div>`;
}

/** Which pair of parts each check needs; a check runs only when both are picked. */
const CHECKS: Array<{ codes: CompatCode[]; needs: string[]; key: Parameters<typeof compatOkMessage>[1] }> = [
  { codes: ["socket"], needs: ["cpu", "motherboard"], key: "socket" },
  { codes: ["memoryType", "memoryMax"], needs: ["memory", "motherboard"], key: "memoryType" },
  { codes: ["memorySpeed"], needs: ["memory", "motherboard"], key: "memorySpeed" },
  { codes: ["coolerSocket"], needs: ["cpu", "cooler"], key: "coolerSocket" },
  { codes: ["boardForm"], needs: ["motherboard", "case"], key: "boardForm" },
  { codes: ["gpuLength"], needs: ["gpu", "case"], key: "gpuLength" },
  { codes: ["coolerHeight", "radiator"], needs: ["cooler", "case"], key: "coolerFit" },
  { codes: ["psuLow", "psuHeadroom"], needs: ["psu"], key: "psu" },
  { codes: ["psuGpu"], needs: ["psu", "gpu"], key: "psuGpu" },
];

/** Every check that could run on the current picks: passed ones in green, findings in amber/red. */
export function checksMarkup(ctx: BuilderCtx, summary: Summary): Html {
  const { lang } = ctx;
  const picks = firstPicks(ctx);
  const rows: Html[] = [];
  for (const check of CHECKS) {
    if (!check.needs.every((slot) => picks[slot])) continue;
    if (check.key === "psu" && summary.watts === 0) continue;
    const found = summary.issues.filter((i) => check.codes.includes(i.code));
    if (found.length === 0) {
      rows.push(html`<li class="chk chk--ok">${icon("circle-check", 18)}<span>${compatOkMessage(lang, check.key, picks, summary.watts)}</span></li>`);
    } else {
      for (const issue of found) {
        rows.push(html`<li class="chk chk--${issue.level}">${icon(issue.level === "err" ? "circle-x" : "alert", 18)}<span>${compatMessage(lang, issue)}</span></li>`);
      }
    }
  }
  return html`<section class="card build-card" id="compat">
    <h2 class="card__title">${t(lang, "compatChecksTitle")}</h2>
    ${rows.length > 0
      ? html`<ul class="chk-list">${rows}</ul>`
      : html`<p class="build-card__empty">${t(lang, "compatChecksEmpty")}</p>`}
    <p class="fineprint"><b>${t(lang, "compatNoteTitle")}</b> ${t(lang, "compatNoteBody")}</p>
  </section>`;
}

/** Where the money goes: each part bought at its cheapest store, grouped by store. */
export function splitMarkup(ctx: BuilderCtx): Html {
  const { lang, currency } = ctx;
  const groups = new Map<string, { vendor: string; total: number; count: number }>();
  for (const product of [...ctx.parts.values()].flat() as Product[]) {
    const offer = bestOffer(product);
    const price = effectivePrice(product);
    if (!offer || price === null) continue;
    const key = vendorKey(offer.vendor);
    const g = groups.get(key) ?? { vendor: offer.vendor, total: 0, count: 0 };
    g.total += price;
    g.count += 1;
    groups.set(key, g);
  }
  const list = [...groups.entries()].sort((a, b) => b[1].total - a[1].total);
  const sum = list.reduce((n, [, g]) => n + g.total, 0);
  return html`<section class="card build-card" id="split">
    <h2 class="card__title">${t(lang, "splitTitle")}</h2>
    ${list.length === 0
      ? html`<p class="build-card__empty">${t(lang, "splitEmpty")}</p>`
      : html`<div class="split-bar" aria-hidden="true">${list.map(
          ([key, g]) => html`<span class="split-bar__seg split-bar__seg--${key}" style="width: ${((g.total / sum) * 100).toFixed(1)}%"></span>`
        )}</div>
        <ul class="split-list">${list.map(
          ([, g]) => html`<li>${vendorDot(g.vendor)}<b>${vendorLabel(g.vendor)}</b><span>${partsCount(lang, g.count)}</span><span class="split-list__sum">${formatPrice(g.total, currency, lang)}</span></li>`
        )}</ul>
        <p class="fineprint">${t(lang, "splitNote")}</p>`}
  </section>`;
}
