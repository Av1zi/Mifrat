import schedule from "../../../scraper/ksp_schedule.json";
import type { Lang, SiteMeta } from "../types";
import { html, type Html } from "./html";

export function kspNotice(
  lang: Lang,
  meta?: Pick<SiteMeta, "vendor_updated_at" | "skipped_vendors">,
  now = new Date()
): Html {
  const updatedAt = Date.parse(meta?.vendor_updated_at?.ksp ?? "");
  const resumeAfter = Date.parse(schedule.resume_after);
  if (!schedule.notice || updatedAt >= resumeAfter) return html``;

  const he = lang === "he";
  const date = new Intl.DateTimeFormat(he ? "he-IL" : "en-GB", {
    timeZone: "Asia/Jerusalem", day: "numeric", month: "short",
  });
  const message = [he ? "עדכוני המחירים של KSP מופסקים זמנית." : "KSP price updates are temporarily paused."];
  if (now.getTime() < resumeAfter) {
    const next = date.format(resumeAfter);
    message.push(he ? `ניסיון חידוש מתוכנן ל־${next}.` : `A restart is planned for ${next}.`);
  }
  if (meta?.skipped_vendors?.includes("ksp")) {
    message.push(he ? "מחירי KSP אינם זמינים כרגע." : "KSP prices are currently unavailable.");
  } else if (Number.isFinite(updatedAt)) {
    const last = date.format(updatedAt);
    message.push(he ? `עדכון מחיר אחרון: ${last}. ייתכן שהמחירים השתנו.` : `Last price update: ${last}. Prices may have changed.`);
  } else {
    message.push(he ? "מחירים קודמים עשויים להיות לא מעודכנים." : "Previous prices may be out of date.");
  }
  return html`<aside class="vendor-notice" aria-label="KSP"><div class="bleed__inner">${message.join(" ")}</div></aside>`;
}
