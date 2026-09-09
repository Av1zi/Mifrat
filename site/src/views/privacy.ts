import { t } from "../i18n";
import { homeHash } from "../state";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Privacy notice (audit §3.1): what leaves the browser and what stays.
 * No tracking cookies, no accounts, no analytics identifiers — only
 * functional localStorage, self-hosted fonts (no third-party transfer),
 * and an opt-in FX fetch when USD is selected.
 */
export function renderPrivacy(container: HTMLElement, lang: Lang): void {
  const rowsHe = `
    <li><code>mifrat:lang</code> — שפת הממשק</li>
    <li><code>mifrat:currency</code> — מטבע תצוגה (ILS/USD)</li>
    <li><code>mifrat:build</code> — טיוטת הבנייה שלך</li>
    <li><code>mifrat:theme</code> — ערכת נושא בהיר/כהה</li>
    <li><code>mifrat:fx:ils-usd</code> — שער חליפין שמור ליום אחד (רק אם בחרת USD)</li>`;
  const rowsEn = `
    <li><code>mifrat:lang</code> — UI language</li>
    <li><code>mifrat:currency</code> — display currency (ILS/USD)</li>
    <li><code>mifrat:build</code> — your builder draft</li>
    <li><code>mifrat:theme</code> — light/dark theme</li>
    <li><code>mifrat:fx:ils-usd</code> — cached FX rate for one day (only if you picked USD)</li>`;

  const thirdHe = `
    <p>הגופנים מוגשים מהאתר עצמו (self-hosted) — אין קריאה ל־Google Fonts ואין מסירת IP לצד שלישי עבור גופנים.</p>
    <p>בחירת USD מפעילה קריאה חד־פעמית ביום ל־<code>api.frankfurter.dev</code> לקבלת שער ILS→USD (ה־IP שלך נשלח אליהם כחלק מהבקשה, כמו בכל בקשת רשת). ב־ILS לא מתבצעת שום קריאה חיצונית.</p>
    <p>קישורי קנייה מובילים לאתרי הספקים; לחיצה עליהם מעבירה אותך אליהם בכפוף למדיניות שלהם.</p>`;
  const thirdEn = `
    <p>Fonts are served from this site itself (self-hosted) — no Google Fonts request, no IP shared with a third party for fonts.</p>
    <p>Selecting USD triggers at most one request per day to <code>api.frankfurter.dev</code> for the ILS→USD rate (your IP is sent to them as part of that request, like any network fetch). ILS mode makes no external requests.</p>
    <p>Buy links lead to vendor sites; clicking one takes you to them under their own policies.</p>`;

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
    <div class="title-band"><h1>${esc(t(lang, "privacyTitle"))}</h1></div>
    <div class="pdp-card" style="max-width:760px">
      <h2 class="pdp-card-title">${esc(t(lang, "privacyLocalTitle"))}</h2>
      <p>${esc(t(lang, "privacyLocalBody"))}</p>
      <ul>${lang === "he" ? rowsHe : rowsEn}</ul>
      <h2 class="pdp-card-title" style="margin-top:18px">${esc(t(lang, "privacyThirdTitle"))}</h2>
      ${lang === "he" ? thirdHe : thirdEn}
    </div>`;
}
