import { t } from "../i18n";
import { homeHash, privacyHash, termsHash } from "../state";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Cookie Policy. The short version is the whole story: this site sets zero
 * cookies of its own (verified — no document.cookie, no Set-Cookie
 * anywhere), keeps only functional localStorage, and shows no consent
 * banner because there is nothing to consent to. Must stay accurate: the
 * day any non-essential storage appears, this page gains a banner section.
 */
export function renderCookies(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";

  const body = he
    ? `
      <div class="pdp-card" style="max-width:780px">
        <h2 class="pdp-card-title">התשובה הקצרה: אין עוגיות, אין באנר</h2>
        <p>האתר <b>אינו מציב עוגיות משלו כלל</b> — לא מעקב, לא פרסום, לא העדפות. לכן אין באנר הסכמה: לפי דיני הפרטיות (ישראל וה־GDPR האירופי) הסכמה נדרשת לעוגיות/מעקבים לא־הכרחיים, וכאן אין כאלה. אם זה ישתנה אי־פעם — נוסיף באנר לפני, לא אחרי.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">מה כן נשמר: אחסון מקומי תפקודי</h2>
        <p>רק <code>localStorage</code> בדפדפן שלך (נשאר במכשיר, לא נשלח אלינו), החיוני לתפקוד:</p>
        <ul>
          <li><code>mifrat:lang</code> — שפה · <code>mifrat:currency</code> — מטבע · <code>mifrat:build</code> — טיוטה · <code>mifrat:theme</code> — ערכת נושא · <code>mifrat:fx:ils-usd</code> — שער ליום (רק ב־USD)</li>
        </ul>
        <p>אחסון תפקודי כזה פטור מהסכמה. ניתן למחוק אותו בכל עת דרך הגדרות הדפדפן (ניקוי נתוני אתר) — האתר ימשיך לעבוד, רק ההעדפות יתאפסו.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">עוגיות של התשתית (Cloudflare)</h2>
        <p>האתר מתארח אצל Cloudflare, שעשויה להציב עוגיות אבטחה טכניות (כגון <code>__cf_bm</code>) לצורך הגנה מפני בוטים — אלה עוגיות הכרחיות לאבטחה, הפטורות מהסכמה. אין לנו גישה לתוכנן ואין לנו שליטה עליהן מעבר לבחירת הספק.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">צדדים שלישיים ואנליטיקה</h2>
        <p>אין אנליטיקה (לא Google Analytics ולא אחרת), אין פיקסלים, אין הטמעות חיצוניות. הבקשה החיצונית היחידה היא שער החליפין (USD בלבד) — פרטים ב<a href="${privacyHash()}">מדיניות הפרטיות</a>. התנאים: <a href="${termsHash()}">תנאי השימוש</a>.</p>
      </div>`
    : `
      <div class="pdp-card" style="max-width:780px">
        <h2 class="pdp-card-title">Short version: no cookies, no banner</h2>
        <p>This site sets <b>zero cookies of its own</b> — no tracking, no ads, no preferences. Hence no consent banner: under privacy law (Israel and EU GDPR alike) consent is required for non-essential cookies/trackers, and there are none here. If that ever changes, a banner comes first — not after.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">What is stored: functional local storage</h2>
        <p>Only <code>localStorage</code> in your browser (stays on your device, never sent to us), strictly necessary for the site to function:</p>
        <ul>
          <li><code>mifrat:lang</code> — language · <code>mifrat:currency</code> — currency · <code>mifrat:build</code> — draft · <code>mifrat:theme</code> — theme · <code>mifrat:fx:ils-usd</code> — daily rate (USD only)</li>
        </ul>
        <p>Such functional storage is consent-exempt. You can delete it anytime via browser settings (clear site data) — the site keeps working, only preferences reset.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Infrastructure cookies (Cloudflare)</h2>
        <p>The site is hosted on Cloudflare, which may set technical security cookies (such as <code>__cf_bm</code>) for bot protection — strictly-necessary security cookies, exempt from consent. We cannot read their content and control them only via our choice of provider.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Third parties and analytics</h2>
        <p>No analytics (neither Google Analytics nor any other), no pixels, no third-party embeds. The only external request is the exchange rate (USD only) — see the <a href="${privacyHash()}">Privacy Policy</a>. Terms: <a href="${termsHash()}">Terms of Use</a>.</p>
      </div>`;

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
    <div class="title-band"><h1>${esc(t(lang, "cookiesTitle"))}</h1></div>
    ${body}`;
}
