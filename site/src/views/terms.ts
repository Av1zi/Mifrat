import { t } from "../i18n";
import { cookiesHash, homeHash, privacyHash } from "../state";
import { setPageTitle } from "../titles";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Terms of Use. Plain language, honest about what this site is: a free,
 * no account, no checkout price comparison hobby project. Nothing is sold
 * here, so there is no cart, no payment, and no refund process of our own.
 * Vendor transactions are governed by the vendors terms. This file must
 * stay accurate: no invented company details, no promises the scraper
 * cannot keep.
 */
export function renderTerms(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  setPageTitle(lang, he ? "תנאי שימוש" : "Terms of Use");

  const contact = `<a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">GitHub Av1zi Mifrat</a>`;

  const body = he
    ? `
      <h2 class="pdp-card-title">מהו האתר</h2>
      <p>מפרט הוא כלי חינמי ועצמאי להשוואת מחירי רכיבי מחשב בין חנויות בישראל. אין חשבון, אין עגלה ואין תשלום. השימוש חופשי ופתוח לכולם.</p>

      <h2 class="pdp-card-title">רכישות והחזרים</h2>
      <p><b>באתר זה לא ניתן לקנות דבר, ולכן אין החזרים מאיתנו.</b> כפתורי הקנייה מובילים לאתרי הספקים וכל רכישה מתבצעת מולם בלבד, בכפוף לתנאים ולמדיניות ההחזרים שלהם. זכויות הביטול חלות על הרכישה מול הספק, לא מולנו.</p>

      <h2 class="pdp-card-title">מחירים וזמינות</h2>
      <p>המחירים נאספים אוטומטית מאתרי הספקים, בדרך כלל פעם ביום. מחיר או זמינות עלולים להיות לא מעודכנים או שגויים. מוצרים שלא עודכנו היום מבוססים על נתוני אתמול. <b>מומלץ לוודא את המחיר הסופי באתר הספק לפני הקנייה.</b> המחיר המחייב הוא תמיד שלו.</p>

      <h2 class="pdp-card-title">בדיקת תאימות</h2>
      <p>בדיקת התאימות מבוססת על נתונים ידועים בלבד. היא אינה בודקת מגבלות פיזיות כמו גובה קירור, אורך כרטיס או מרווחי זיכרון. מומלץ לוודא התאמה פיזית לפני הרכישה. איננו אחראים לרכיבים שאינם מתאימים.</p>

      <h2 class="pdp-card-title">קישורי שיתוף</h2>
      <p>קישורי השיתוף הם צילומים קבועים של בנייה. הם מכילים מזהי מוצרים אנונימיים בלבד. לא ניתן לשמור בהם תוכן אישי, כי טכנית נכנסים רק מזהי מוצרים מהקטלוג. הצפה או סריקה אגרסיבית ייחסמו.</p>

      <h2 class="pdp-card-title">קניין רוחני</h2>
      <p>קוד האתר מפורסם ברישיון GPLv3. את קובץ הרישיון אפשר למצוא במאגר הציבורי. שמות החנויות והמותגים שייכים לבעליהם. תמונות המוצרים שייכות לספקים ומוצגות כאן מוקטנות לצורך זיהוי בלבד, עם קישור לחנות. אם אתה בעל זכויות וסבור שתמונה צריכה לרדת, פנה דרך ${contact} ונסיר אותה.</p>

      <h2 class="pdp-card-title">שימוש הוגן</h2>
      <p>שימוש אישי מתקבל בברכה. נא לא לשבש את פעילות האתר, לא לעקוף הגבלות קצב, ולא להציג את התוכן כאילו הוא שלך או כהמלצה מקצועית מטעמנו.</p>

      <h2 class="pdp-card-title">אחריות</h2>
      <p>האתר ניתן כמות שהוא, ללא אחריות מכל סוג, במידה שהחוק מאפשר. איננו אחראים לנזקים עקיפים, להחלטות קנייה או לטעויות בנתונים. מכיוון שהשירות חינמי, תקרת האחריות היא אפס. אין בכך לגרוע מזכויות שהחוק אינו מאפשר לשלול.</p>

      <h2 class="pdp-card-title">יצירת קשר</h2>
      <p>זהו פרויקט עצמאי ללא חברה רשומה וללא מוקד תמיכה. הדרך לפנות היא דרך ${contact}. המענה נעשה כמיטב היכולת. פרטי הפרטיות נמצאים ב<a href="${privacyHash()}">מדיניות הפרטיות</a> ופרטי העוגיות ב<a href="${cookiesHash()}">מדיניות העוגיות</a>.</p>

      <h2 class="pdp-card-title">דין חל</h2>
      <p>על תנאים אלה חלים דיני מדינת ישראל.</p>`
    : `
      <h2 class="pdp-card-title">What this site is</h2>
      <p>Mifrat is a free independent tool for comparing PC part prices across Israeli vendors. There is no account, no cart and no payment. Use is free and open to everyone.</p>

      <h2 class="pdp-card-title">Buying and refunds</h2>
      <p><b>Nothing can be bought on this site, so there are no refunds from us.</b> Buy buttons lead to vendor sites and every purchase happens with them alone, under their terms and refund policies. Consumer cancellation rights apply to the purchase from the vendor, not to us.</p>

      <h2 class="pdp-card-title">Prices and availability</h2>
      <p>Prices are collected automatically from vendor sites, usually once a day. A price or stock status can be outdated or wrong. Items marked as not refreshed today rely on yesterday's data. <b>Please verify the final price on the vendor site before buying.</b> Their price is the binding one.</p>

      <h2 class="pdp-card-title">Compatibility guidance</h2>
      <p>The compatibility check covers known data only. It does not verify physical limits such as cooler height, card length or memory clearance. Please verify physical fit yourself before buying. We are not responsible for parts that do not fit together.</p>

      <h2 class="pdp-card-title">Share links</h2>
      <p>Share links are permanent snapshots of a build. They hold anonymous product IDs only. No personal content can be stored there, because technically only catalog product IDs fit. Flooding or aggressive scanning will be blocked.</p>

      <h2 class="pdp-card-title">Intellectual property</h2>
      <p>The site code is published under GPLv3. You can find the license file in the public repository. Shop and brand names belong to their owners. Product photos belong to the vendors and appear here in reduced size for identification only, with a link to the shop. If you own rights to an image and think it should come down, contact us on ${contact} and we will remove it.</p>

      <h2 class="pdp-card-title">Fair use</h2>
      <p>Personal use is welcome. Please do not disrupt the service, work around rate limits, or present the content as your own or as our professional advice.</p>

      <h2 class="pdp-card-title">Liability</h2>
      <p>The site is provided as is, without warranties of any kind, to the extent the law allows. We are not liable for indirect damages, purchase decisions or data errors. Since the service is free, any liability cap is zero. This does not take away from consumer rights that the law does not allow to waive.</p>

      <h2 class="pdp-card-title">Contact</h2>
      <p>This is an independent project with no registered company and no support desk. Contact is on ${contact}. Replies are on a best effort basis. Privacy details are in the <a href="${privacyHash()}">Privacy Policy</a> and cookie details are in the <a href="${cookiesHash()}">Cookie Policy</a>.</p>

      <h2 class="pdp-card-title">Governing law</h2>
      <p>These terms are governed by the laws of the State of Israel.</p>`;

  container.innerHTML = `
    <div class="legal-wrap">
      <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
      <div class="title-band title-band--center">
        <h1>${esc(t(lang, "termsTitle"))}</h1>
        <p>${he ? "כללים פשוטים לשימוש חופשי ובטוח באתר" : "Simple rules for using the site freely and safely"}</p>
      </div>
      <div class="pdp-card legal-card">${body}</div>
    </div>`;
}
