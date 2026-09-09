import { t } from "../i18n";
import { cookiesHash, homeHash, termsHash } from "../state";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Privacy notice: what leaves the browser and what stays.
 * No accounts, no analytics, no cookies, no forms — only functional
 * localStorage plus anonymous short-link snapshots (D1) created when the
 * builder auto-generates a share link. Must stay accurate: every new
 * data collection needs a line here.
 */
export function renderPrivacy(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  const contact = `<a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">GitHub — Av1zi/Mifrat</a>`;

  const body = he
    ? `
      <div class="pdp-card" style="max-width:780px">
        <h2 class="pdp-card-title">מי אנחנו</h2>
        <p>מפרט הוא פרויקט אישי לא מסחרי להשוואת מחירי רכיבי מחשב. אין חברה, אין שירות לקוחות — פניות (כולל בקשות פרטיות) דרך ${contact}, ונענה כמיטב יכולתנו.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">מה נשמר אצלך בדפדפן (לא עוזב את המכשיר)</h2>
        <p>אחסון מקומי תפקודי בלבד (<code>localStorage</code>) — אין עוגיות מעקב, אין חשבונות, אין טפסים, אין אנליטיקה:</p>
        <ul>
          <li><code>mifrat:lang</code> — שפת הממשק</li>
          <li><code>mifrat:currency</code> — מטבע תצוגה (ILS/USD)</li>
          <li><code>mifrat:build</code> — טיוטת הבנייה שלך</li>
          <li><code>mifrat:theme</code> — ערכת נושא בהיר/כהה</li>
          <li><code>mifrat:fx:ils-usd</code> — שער חליפין שמור ליום אחד (רק אם בחרת USD)</li>
        </ul>

        <h2 class="pdp-card-title" style="margin-top:18px">מה נשמר אצלנו (קישורי שיתוף בלבד)</h2>
        <p>כשמחולל הקישורים יוצר קישור קצר (<code>/list/xxxxxx</code>), מזהי המוצרים האנונימיים שבבנייה נשמרים בטבלת <code>lists</code> כדי שהקישור יעבוד. אין שמות, מיילים או פרטים מזהים — רק מזהי מוצרים. שים לב: הקישורים <b>קבועים</b> — שורות נשמרות לצמיתות ולא ניתן למחוק קישור בודד כיום. אל תצפה למחיקה; פשוט אל תשתף בנייה שאינך רוצה שתישמר.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">צדדים שלישיים</h2>
        <ul>
          <li><b>גופנים:</b> מוגשים מהאתר עצמו — אין מסירת IP לצד שלישי עבור גופנים.</li>
          <li><b>שער חליפין:</b> בחירת USD מפעילה לכל היותר בקשה אחת ביום ל־<code>api.frankfurter.dev</code> (ה־IP שלך נשלח אליהם כחלק מהבקשה). במצב ILS אין שום קריאה חיצונית.</li>
          <li><b>קישורי קנייה:</b> מובילים לאתרי הספקים — לחיצה מעבירה אותך אליהם, בכפוף למדיניות שלהם.</li>
          <li><b>תשתית:</b> האתר מתארח אצל Cloudflare, שמעבדת IP לצורכי אבטחה ותפעול, ועשויה להציב עוגיות אבטחה טכניות — פרטים ב<a href="${cookiesHash()}">מדיניות העוגיות</a>.</li>
        </ul>

        <h2 class="pdp-card-title" style="margin-top:18px">הזכויות שלך</h2>
        <p>אין לנו כמעט מה למסור או למחוק (אין חשבונות ואין PII). לבקשות גישה או מחיקה פנה דרך ${contact}. מגבלה ידועה: קישורי <code>/list/…</code> ששותפו אינם ניתנים למחיקה פרטנית כיום — קח זאת בחשבון לפני השיתוף.</p>
        <p>האתר אינו מיועד לילדים ואינו אוסף מהם מידע — אין רישום משתמשים בכלל.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">שינויים</h2>
        <p>אם נתחיל לאסוף מידע נוסף בעתיד, נעדכן עמוד זה. התנאים המלאים ב<a href="${termsHash()}">תנאי השימוש</a>.</p>
      </div>`
    : `
      <div class="pdp-card" style="max-width:780px">
        <h2 class="pdp-card-title">Who we are</h2>
        <p>Mifrat is a non-commercial personal project for comparing PC-part prices. No company, no support desk — requests (including privacy requests) via ${contact}, answered on a best-effort basis.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">What stays in your browser (never leaves your device)</h2>
        <p>Functional <code>localStorage</code> only — no tracking cookies, no accounts, no forms, no analytics:</p>
        <ul>
          <li><code>mifrat:lang</code> — UI language</li>
          <li><code>mifrat:currency</code> — display currency (ILS/USD)</li>
          <li><code>mifrat:build</code> — your builder draft</li>
          <li><code>mifrat:theme</code> — light/dark theme</li>
          <li><code>mifrat:fx:ils-usd</code> — cached FX rate for one day (only if you picked USD)</li>
        </ul>

        <h2 class="pdp-card-title" style="margin-top:18px">What is stored with us (share links only)</h2>
        <p>When the builder generates a short link (<code>/list/xxxxxx</code>), the anonymous product IDs in the build are stored in the <code>lists</code> table so the link resolves. No names, emails, or identifiers — product IDs only. Note: links are <b>permanent</b> — rows are kept indefinitely and a single link cannot currently be deleted. Expect permanence; simply don't share a build you don't want kept.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Third parties</h2>
        <ul>
          <li><b>Fonts:</b> served from this site itself — no IP shared with a third party for fonts.</li>
          <li><b>Exchange rate:</b> selecting USD triggers at most one request per day to <code>api.frankfurter.dev</code> (your IP is sent to them as part of that request). ILS mode makes no external requests.</li>
          <li><b>Buy links:</b> lead to vendor sites — clicking takes you to them under their own policies.</li>
          <li><b>Infrastructure:</b> the site is hosted on Cloudflare, which processes IPs for security/operations and may set technical security cookies — see the <a href="${cookiesHash()}">Cookie Policy</a>.</li>
        </ul>

        <h2 class="pdp-card-title" style="margin-top:18px">Your rights</h2>
        <p>There is almost nothing to hand over or erase (no accounts, no PII). For access or deletion requests contact us via ${contact}. Known limitation: shared <code>/list/…</code> links cannot currently be deleted individually — factor that in before sharing.</p>
        <p>The site is not directed at children and collects nothing from them — there is no user registration at all.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Changes</h2>
        <p>If we ever start collecting additional data, this page will be updated. Full terms in the <a href="${termsHash()}">Terms of Use</a>.</p>
      </div>`;

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
    <div class="title-band"><h1>${esc(t(lang, "privacyTitle"))}</h1></div>
    ${body}`;
}
