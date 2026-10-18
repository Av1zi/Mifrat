import { checkCompatibility, type CompatIssue } from "../../build";
import { formatPrice } from "../../format";
import { compatMessage, issuesSummary, t, wattOf } from "../../i18n";
import { icon } from "../../icons";
import { buildItemCount } from "../../state";
import { html, type Html } from "../../ui/html";
import { numSpec } from "../../build";
import { buildTotal, buildWatts, firstPicks, type BuilderCtx } from "./parts";

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

/** Sticky strip: compatibility verdict, wattage meter against the chosen PSU, and the total. */
export function stripMarkup(ctx: BuilderCtx, summary: Summary): Html {
  const { lang, currency } = ctx;
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
  return html`<div class="strip strip--${level}" role="status">
    <div class="strip__verdict">${icon(STRIP_ICON[level], 20)}<span>${message}</span></div>
    ${hasParts
      ? html`<div class="strip__watts">
          ${icon("bolt", 15)}<span>${t(lang, "wattageShort")}</span><b class="num">${watts}W</b>
          ${capacity !== null
            ? html`<progress class="meter${meterLevel}" max="${capacity}" value="${Math.min(watts, capacity)}" aria-label="${t(lang, "wattageShort")}"></progress><span class="strip__of">${wattOf(lang, capacity)}</span>`
            : ""}
        </div>`
      : ""}
    <div class="strip__total"><span>${t(lang, "totalShort")}</span><b class="num">${formatPrice(buildTotal(ctx), currency, lang)}</b></div>
  </div>`;
}

/** Issue list (hidden when there is nothing to report). */
export function issuesMarkup(ctx: BuilderCtx, summary: Summary): Html {
  if (summary.issues.length === 0) return html``;
  return html`<ul class="issues">${summary.issues.map(
    (issue) => html`<li class="issue issue--${issue.level}">${icon(issue.level === "err" ? "circle-x" : "alert", 16)}<span>${compatMessage(ctx.lang, issue)}</span></li>`
  )}</ul>`;
}
