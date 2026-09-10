import { t } from "../i18n";
import { cookiesHash, homeHash, termsHash } from "../state";
import { setPageTitle } from "../titles";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Privacy notice: what leaves the browser and what stays.
 * No accounts, no analytics, no cookies, no forms. Only functional
 * localStorage plus anonymous short link snapshots (D1) created when the
 * builder generates a share link. Every new data collection needs a
 * line here.
 */
export function renderPrivacy(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  setPageTitle(lang, he ? "פרטיות" : "Privacy");

  const contact = `<a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">GitHub Av1zi Mifrat</a>`;

  const body = he
    ? `
      <h2 class="pdp-card-title">מי אנחנו</h2>
      <p>מפרט הוא פרויקט אישי ועצמאי להשוואת מחירי רכיבי מחשב בישראל. אין חברה ואין מוקד תמיכה. לשאלות, כולל שאלות פרטיות, אפשר לפנות דרך ${contact} ונשתדל לענות בהקדם.</p>

      <h2 class="pdp-card-title">מה נשמר בדפדפן שלך</h2>
      <p>כל העבודה בכלי הבנייה נשמרת בדפדפן שלך בלבד, באחסון מקומי תפקודי. דבר לא עוזב את המכשיר אלא אם בחרת לשתף בנייה. אין עוגיות מעקב, אין חשבונות, אין טפסים ואין מדידות.</p>
      <ul>
        <li><code>mifrat:lang</code> שפת הממשק</li>
        <li><code>mifrat:currency</code> מטבע תצוגה, שקלים ודולרים</li>
        <li><code>mifrat:build</code> טיוטת הבנייה שלך</li>
        <li><code>mifrat:theme</code> מראה בהיר או מראה כהה</li>
        <li><code>mifrat:fx:ils-usd</code> שער חליפין שמור ליום אחד, בשימוש רק במצב דולרים</li>
      </ul>

      <h2 class="pdp-card-title">מה נשמר אצלנו</h2>
      <p>רק קישורי שיתוף אנונימיים. כשהכלי יוצר קישור קצר, מזהי המוצרים שבבנייה נשמרים בטבלת <code>lists</code> כדי שהקישור ייפתח גם בהמשך. אין שמות, אין כתובות מייל ואין מזהים מכל סוג. רק מזהי מוצרים. הקישורים קבועים. הם נשמרים לצמיתות ולא ניתן כיום למחוק קישור בודד, לכן מומלץ לשתף רק בנייה שאין בעיה לשמור.</p>

      <h2 class="pdp-card-title">צדדים שלישיים</h2>
      <ul>
        <li><b>גופנים.</b> הגופנים מוגשים מהאתר עצמו, כך שדבר לא נשלח לספק גופנים.</li>
        <li><b>שער חליפין.</b> מצב דולרים מבקש שער לכל היותר פעם ביום מ <code>api.frankfurter.dev</code>. הכתובת שלך נשלחת אליהם כחלק מהבקשה. במצב שקלים אין בקשות חוץ כלל.</li>
        <li><b>כפתורי קנייה.</b> הכפתורים מובילים לאתרי הספקים. מרגע הלחיצה חלות המדיניות שלהם.</li>
        <li><b>אחסון.</b> האתר מתארח אצל Cloudflare, שמעבדת כתובות לצורכי אבטחה ותפעול ועשויה להציב עוגיות אבטחה טכניות. פרטים נוספים ב<a href="${cookiesHash()}">מדיניות העוגיות</a>.</li>
      </ul>

      <h2 class="pdp-card-title">הזכויות שלך</h2>
      <p>כמעט אין מה למסור או למחוק, כי אין חשבונות ואין פרטים אישיים שמורים. לבקשות גישה או מחיקה אפשר לפנות דרך ${contact} ונעזור בהקדם. מגבלה אחת שכדאי להכיר. קישורי שיתוף שנשלחו לא ניתנים כיום למחיקה בודדת, לכן כדאי לקחת זאת בחשבון לפני השיתוף.</p>
      <p>האתר אינו מיועד לילדים ואינו אוסף מהם דבר. אין רישום משתמשים כלל.</p>

      <h2 class="pdp-card-title">שינויים</h2>
      <p>אם נתחיל לאסוף מידע נוסף בעתיד, עמוד זה יעודכן ראשון. הכללים המלאים נמצאים ב<a href="${termsHash()}">תנאי השימוש</a>.</p>`
    : `
      <h2 class="pdp-card-title">Who we are</h2>
      <p>Mifrat is a small independent project for comparing PC part prices in Israel. There is no company behind it and no support desk. If you have a question, including a privacy question, you can reach out on ${contact} and we will get back to you as soon as we can.</p>

      <h2 class="pdp-card-title">What stays in your browser</h2>
      <p>Everything in the builder lives in your own browser, using functional local storage. It never leaves your device unless you choose to share a build. There are no tracking cookies here, no accounts, no forms and no analytics.</p>
      <ul>
        <li><code>mifrat:lang</code> interface language</li>
        <li><code>mifrat:currency</code> display currency, ILS and USD</li>
        <li><code>mifrat:build</code> your builder draft</li>
        <li><code>mifrat:theme</code> light or dark appearance</li>
        <li><code>mifrat:fx:ils-usd</code> cached exchange rate, kept for one day, used only in USD mode</li>
      </ul>

      <h2 class="pdp-card-title">What is stored on our side</h2>
      <p>Only anonymous share links. When the builder creates a short link, the product IDs in that build are saved in the <code>lists</code> table so the link can open later. No names, no emails and no identifiers of any kind. Only product IDs. Links are permanent. They are kept indefinitely and a single link cannot be deleted at this time, so please share only builds you are comfortable keeping.</p>

      <h2 class="pdp-card-title">Third parties</h2>
      <ul>
        <li><b>Fonts.</b> Fonts are served from this site, so nothing is shared with a font provider.</li>
        <li><b>Exchange rate.</b> USD mode requests a rate at most once per day from <code>api.frankfurter.dev</code>. Your address is sent to them as part of that request. ILS mode makes no outside requests.</li>
        <li><b>Buy buttons.</b> The buttons lead to vendor sites. Once you click through, their policies apply.</li>
        <li><b>Hosting.</b> The site runs on Cloudflare, which processes addresses for security and operations and may set technical security cookies. You can read more in the <a href="${cookiesHash()}">Cookie Policy</a>.</li>
      </ul>

      <h2 class="pdp-card-title">Your rights</h2>
      <p>There is almost nothing to provide or erase, because there are no accounts and no personal details stored. For access or deletion requests, contact us on ${contact} and we will help as soon as we can. One limit to know. Shared links cannot be removed individually at this time, so please keep this in mind before sharing.</p>
      <p>This site is not aimed at children and collects nothing from them. There is no registration of any kind.</p>

      <h2 class="pdp-card-title">Changes</h2>
      <p>If we ever collect additional data, this page will be updated first. The full rules are in the <a href="${termsHash()}">Terms of Use</a>.</p>`;

  container.innerHTML = `
    <div class="legal-wrap">
      <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
      <div class="title-band title-band--center">
        <h1>${esc(t(lang, "privacyTitle"))}</h1>
        <p>${he ? "הסבר פשוט על מה נשמר ומה לא" : "A plain language summary of what is stored and what is not"}</p>
      </div>
      <div class="pdp-card legal-card">${body}</div>
    </div>`;
}
