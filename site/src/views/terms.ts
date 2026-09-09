import { t } from "../i18n";
import { cookiesHash, homeHash, privacyHash } from "../state";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Terms of Use. Plain-language, honest about what this site is: a free,
 * no-account, no-checkout price-comparison hobby project. Nothing is sold
 * here, so there is no cart, no payment, and no refund process of our own
 * — vendor transactions are governed by the vendors' terms. Must stay
 * accurate: no invented company details, no promises the scraper can't keep.
 */
export function renderTerms(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  const contact = `<a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">GitHub — Av1zi/Mifrat</a>`;

  const body = he
    ? `
      <div class="pdp-card" style="max-width:780px">
        <h2 class="pdp-card-title">מהו האתר</h2>
        <p>מפרט הוא כלי חינמי, אישי ולא מסחרי להשוואת מחירי רכיבי מחשב בין חנויות ישראליות. אין צורך בחשבון, אין עגלה, אין תשלום — והשימוש חופשי.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">רכישות והחזרים</h2>
        <p><b>באתר זה לא ניתן לקנות דבר — ולכן אין כאן החזרים.</b> כפתורי הקנייה מובילים לאתרי הספקים, וכל עסקה מתבצעת מולם בלבד, בכפוף לתנאים ולמדיניות ההחזרים שלהם (כולל זכויות הביטול לפי חוק הגנת הצרכן, שחלות על העסקה מול הספק — לא מולנו).</p>

        <h2 class="pdp-card-title" style="margin-top:18px">מחירים וזמינות — להתייחס בערבון מוגבל</h2>
        <p>המחירים נאספים אוטומטית מאתרי הספקים, בדרך כלל פעם ביום. מחיר או זמינות עשויים להיות לא מעודכנים או שגויים; מוצרים המסומנים כ״לא עודכן היום״ מבוססים על נתוני אתמול. <b>יש לוודא את המחיר הסופי באתר הספק לפני הקנייה</b> — המחיר המחייב הוא תמיד שלו.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">בדיקת תאימות — עזרה, לא אחריות</h2>
        <p>בדיקת התאימות מבוססת על נתונים ידועים בלבד ואינה בודקת אילוצים פיזיים (גובה קירור, אורך כרטיס, מרווחי זיכרון). יש לוודא התאמה פיזית ידנית לפני הרכישה — איננו אחראים לרכיבים שאינם מתאימים.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">קישורי שיתוף</h2>
        <p>קישורי <code>/list/…</code> הם צילומים קבועים של בנייה (מזהי מוצרים אנונימיים בלבד) ונשמרים לצמיתות. אין להעלות תוכן אישי — טכנית ניתן לשמור רק מזהי מוצרים מהקטלוג. שימוש לרעה בממשק (הצפה, סריקה אגרסיבית) יחסם — ראה הגבלות הקצב.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">קניין רוחני</h2>
        <p>קוד האתר מפורסם ברישיון GPLv3 (ראה קובץ LICENSE במאגר הציבורי). שמות החנויות והמותגים שייכים לבעליהם. תמונות המוצרים שייכות לספקים ומוצגות לצורך זיהוי המוצר בלבד, ברזולוציה מוקטנת, עם קישור לחנות — אם אתה בעל זכויות וסבור שתמונה מסוימת צריכה לרדת, פנה דרך ${contact} ונסיר אותה.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">שימוש הוגן</h2>
        <p>מותר להשתמש באתר לצרכים אישיים. אסור לשבש את פעילותו, לעקוף הגבלות קצב, או להציג את התוכן כאילו הוא שלך או כהמלצה מקצועית מטעמנו.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">אחריות</h2>
        <p>האתר ניתן כמות שהוא (AS-IS), ללא אחריות מכל סוג, במידה המותרת בחוק. לא נישא באחריות לנזקים עקיפים, להחלטות קנייה, או לטעויות בנתונים — תקרת האחריות, ככל שקיימת, מוגבלת לאפס, שכן השירות חינמי. אין בכך לגרוע מזכויות צרכניות שאינן ניתנות לשלילה לפי דין.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">מי מפעיל ואיך פונים</h2>
        <p>פרויקט אישי לא מסחרי, ללא חברה רשומה וללא מוקד תמיכה. פניות: ${contact} — מענה כמיטב היכולת. פרטיות: <a href="${privacyHash()}">מדיניות הפרטיות</a>. עוגיות: <a href="${cookiesHash()}">מדיניות העוגיות</a>.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">דין חל</h2>
        <p>על תנאים אלה יחולו דיני מדינת ישראל.</p>
      </div>`
    : `
      <div class="pdp-card" style="max-width:780px">
        <h2 class="pdp-card-title">What this site is</h2>
        <p>Mifrat is a free, personal, non-commercial tool for comparing PC-part prices across Israeli vendors. No account, no cart, no payment — use is free.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Purchases and refunds</h2>
        <p><b>Nothing can be bought on this site — so there are no refunds from us.</b> Buy buttons lead to vendor sites, and every transaction happens with them alone, under their terms and refund policies (including statutory cancellation rights under consumer-protection law, which apply to the transaction with the vendor — not with us).</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Prices and availability — treat as indicative</h2>
        <p>Prices are collected automatically from vendor sites, usually once a day. A price or stock status may be outdated or wrong; items tagged as not refreshed today rely on yesterday's data. <b>Always verify the final price on the vendor's site before buying</b> — their price is the binding one.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Compatibility check — guidance, not a guarantee</h2>
        <p>The check covers known data only and does not verify physical constraints (cooler height, card length, RAM clearance). Verify physical fit manually before purchase — we are not responsible for incompatible parts.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Share links</h2>
        <p><code>/list/…</code> links are permanent snapshots of a build (anonymous product IDs only) and are kept indefinitely. No personal content can be stored — technically only catalog product IDs. API abuse (flooding, aggressive scraping) will be blocked — see the rate limits.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Intellectual property</h2>
        <p>The site's code is published under GPLv3 (see the LICENSE file in the public repository). Shop and brand names belong to their owners. Product photos belong to the vendors and are shown for product identification only, downscaled, with a link to the shop — if you are a rights holder and believe an image should come down, contact us via ${contact} and we will remove it.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Fair use</h2>
        <p>Personal use is welcome. Do not disrupt the service, circumvent rate limits, or present the content as your own or as our professional advice.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Liability</h2>
        <p>The site is provided as-is, without warranties of any kind, to the extent permitted by law. We are not liable for indirect damages, purchase decisions, or data errors — any liability cap is zero since the service is free. This does not detract from non-waivable statutory consumer rights.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Operator and contact</h2>
        <p>A non-commercial personal project, no registered company, no support desk. Contact: ${contact} — best-effort replies. Privacy: <a href="${privacyHash()}">Privacy Policy</a>. Cookies: <a href="${cookiesHash()}">Cookie Policy</a>.</p>

        <h2 class="pdp-card-title" style="margin-top:18px">Governing law</h2>
        <p>These terms are governed by the laws of the State of Israel.</p>
      </div>`;

  container.innerHTML = `
    <div class="crumbs"><a href="${homeHash()}">← ${esc(t(lang, "backToCategories"))}</a></div>
    <div class="title-band"><h1>${esc(t(lang, "termsTitle"))}</h1></div>
    ${body}`;
}
