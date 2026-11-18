import schedule from "../../../scraper/ksp_schedule.json";
import type { Lang } from "../types";
import { html, type Html } from "./html";

export function kspNotice(lang: Lang, updatedAt?: string, now = new Date()): Html {
  const recovered = updatedAt && Date.parse(updatedAt) >= Date.parse(schedule.resume_after);
  if (!schedule.notice || recovered) return html``;
  const date = new Intl.DateTimeFormat(lang === "he" ? "he-IL" : "en-GB", {
    timeZone: "Asia/Jerusalem", day: "numeric", month: "short",
  }).format(new Date(schedule.resume_after));
  const due = now.getTime() >= Date.parse(schedule.resume_after);
  const plan = lang === "he"
    ? (due ? "העדכונים יחזרו לאחר ניסיון חידוש מוצלח." : `ניסיון חידוש מתוכנן ל־${date}.`)
    : (due ? "Updates will return after a successful restart." : `A restart is planned for ${date}.`);
  const message = lang === "he"
    ? `עדכוני המחירים של KSP מופסקים זמנית. ${plan} מחירים קודמים עשויים להיות לא מעודכנים.`
    : `KSP price updates are temporarily paused. ${plan} Previous prices may be out of date.`;
  return html`<aside class="vendor-notice" aria-label="KSP"><div class="bleed__inner">${message}</div></aside>`;
}
