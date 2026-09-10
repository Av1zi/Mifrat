import { t } from "../i18n";
import { homeHash, privacyHash, termsHash } from "../state";
import { setPageTitle } from "../titles";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Cookie Policy. The short version is the whole story: this site sets zero
 * cookies of its own, keeps only functional localStorage, and shows no
 * consent banner because there is nothing to consent to. If any
 * non essential storage ever appears, this page gains a banner section.
 */
export function renderCookies(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  setPageTitle(lang, he ? "מדיניות עוגיות" : "Cookie Policy");

  const body = he
    ? `
      <h2 class="pdp-card-title">התשובה הקצרה. אין עוגיות ואין באנר</h2>
      <p>האתר אינו מציב עוגיות משלו כלל. לא מעקב, לא פרסום ולא העדפות. לכן אין באנר הסכמה. דיני הפרטיות דורשים הסכמה לעוגיות ולמעקבים שאינם הכרחיים, וכאן אין כאלה. אם זה ישתנה אי פעם, נוסיף באנר לפני, לא אחרי.</p>

      <h2 class="pdp-card-title">מה כן נשמר. אחסון מקומי תפקודי</h2>
      <p>רק אחסון מקומי בדפדפן שלך. הוא נשאר במכשיר ולא נשלח אלינו. הוא הכרחי לתפקוד האתר:</p>
      <ul>
        <li><code>mifrat:lang</code> שפה</li>
        <li><code>mifrat:currency</code> מטבע</li>
        <li><code>mifrat:build</code> טיוטה</li>
        <li><code>mifrat:theme</code> ערכת נושא</li>
        <li><code>mifrat:fx:ils-usd</code> שער ליום, רק במצב דולרים</li>
      </ul>
      <p>אחסון מסוג זה אינו דורש הסכמה. אפשר למחוק אותו בכל עת דרך הגדרות הדפדפן, בניקוי נתוני האתר. האתר ימשיך לעבוד. רק ההעדפות יתאפסו.</p>

      <h2 class="pdp-card-title">עוגיות של התשתית</h2>
      <p>האתר מתארח אצל Cloudflare, שעשויה להציב עוגיות אבטחה טכניות כמו <code>__cf_bm</code> לצורך הגנה מפני בוטים. אלו עוגיות אבטחה הכרחיות, ולכן אינן דורשות הסכמה. אין לנו גישה לתוכנן ואין לנו שליטה עליהן מעבר לבחירת הספק.</p>

      <h2 class="pdp-card-title">צדדים שלישיים ומדידות</h2>
      <p>אין מדידות מכל סוג, אין פיקסלים ואין הטמעות חוץ. הבקשה החיצונית היחידה היא שער החליפין במצב דולרים. פרטים נוספים ב<a href="${privacyHash()}">מדיניות הפרטיות</a>. הכללים המלאים ב<a href="${termsHash()}">תנאי השימוש</a>.</p>`
    : `
      <h2 class="pdp-card-title">Short version. No cookies and no banner</h2>
      <p>This site sets zero cookies of its own. No tracking, no ads and no preferences. That is why there is no consent banner. Privacy law asks for consent for cookies and trackers that are not essential, and there are none here. If that ever changes, a banner will come first, not after.</p>

      <h2 class="pdp-card-title">What is stored. Functional local storage</h2>
      <p>Only local storage in your browser. It stays on your device and is never sent to us. It is strictly needed for the site to work:</p>
      <ul>
        <li><code>mifrat:lang</code> language</li>
        <li><code>mifrat:currency</code> currency</li>
        <li><code>mifrat:build</code> draft</li>
        <li><code>mifrat:theme</code> theme</li>
        <li><code>mifrat:fx:ils-usd</code> daily rate, USD mode only</li>
      </ul>
      <p>Storage of this kind does not need consent. You can delete it at any time in browser settings by clearing site data. The site will keep working. Only preferences will reset.</p>

      <h2 class="pdp-card-title">Infrastructure cookies</h2>
      <p>The site runs on Cloudflare, which may set technical security cookies such as <code>__cf_bm</code> for bot protection. These are security cookies that are strictly needed, so they do not need consent. We cannot read their content and we control them only through our choice of provider.</p>

      <h2 class="pdp-card-title">Third parties and analytics</h2>
      <p>There is no analytics of any kind, no pixels and no outside embeds. The only outside request is the exchange rate in USD mode. You can read more in the <a href="${privacyHash()}">Privacy Policy</a>. The full rules are in the <a href="${termsHash()}">Terms of Use</a>.</p>`;

  container.innerHTML = `
    <div class="legal-wrap">
      <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
      <div class="title-band title-band--center">
        <h1>${esc(t(lang, "cookiesTitle"))}</h1>
        <p>${he ? "כל הסיפור בשפה פשוטה. אין מה לאשר" : "The full story in plain language. There is nothing to consent to"}</p>
      </div>
      <div class="pdp-card legal-card">${body}</div>
    </div>`;
}
