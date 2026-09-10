import { loadMeta } from "../api";
import { t } from "../i18n";
import { icon } from "../icons";
import { buildHash, categoriesHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { errorPanel } from "../utils";

export async function renderHome(container: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
  void currency;
  const he = lang === "he";
  setPageTitle(lang, he ? "השוואת מחירי רכיבי מחשב" : "Compare PC Part Prices in Israel");

  container.innerHTML = `<div class="empty-state">${t(lang, "loading")}</div>`;

  let meta;
  try {
    meta = await loadMeta();
  } catch (err) {
    container.innerHTML = errorPanel(
      t(lang, "loadError"),
      t(lang, "retry"),
      err
    );
    return;
  }

  const totalParts = meta.categories.reduce((n, c) => n + c.count, 0);
  const categoryCount = meta.categories.filter((c) => c.count > 0).length;

  const copy = he
    ? {
        eyebrow: "השוואת מחירים לרכיבי מחשב בישראל",
        browseCta: "עיון בקטגוריות",
        statsPartsLabel: "מוצרים בקטלוג",
        statsCatsLabel: "קטגוריות פעילות",
        statsRefreshLabel: "רענון מחירים יומי",
        howTitle: "איך זה עובד",
        step1Title: "בוחרים חלקים",
        step1Body: "מסננים לפי חנות, מחיר ומפרט, ומוסיפים כל חלק לבנייה.",
        step2Title: "בודקים תאימות וסכום",
        step2Body: "הכלי מסכם את המחיר, מעריך צריכה ובודק התאמה בין החלקים.",
        step3Title: "משתפים ושומרים",
        step3Body: "מקבלים קישור קצר לבנייה ושולחים לחבר או שומרים להמשך.",
        featTitle: "למה לבנות כאן",
        feat1Title: "מחירים מחנויות מובילות",
        feat1Body: "המחירים נאספים מאתרי הספקים ומתעדכנים מדי יום.",
        feat2Title: "בדיקת תאימות",
        feat2Body: "התראות על שילובים בעייתיים לפני שמוציאים כסף.",
        feat3Title: "שיתוף בקישור קצר",
        feat3Body: "כל בנייה מקבלת קישור קבוע שאפשר לשלוח לכל אחד.",
        feat4Title: "בלי חשבון ובלי עוגיות",
        feat4Body: "אין הרשמה, אין מעקב ואין באנרים. פשוט בונים.",
      }
    : {
        eyebrow: "Price comparison for PC parts in Israel",
        browseCta: "Browse categories",
        statsPartsLabel: "Products in the catalog",
        statsCatsLabel: "Active categories",
        statsRefreshLabel: "Prices refreshed daily",
        howTitle: "How it works",
        step1Title: "Pick your parts",
        step1Body: "Filter by shop, price and specs, then add each part to your build.",
        step2Title: "Check fit and total",
        step2Body: "The builder totals the price, estimates power draw and flags mismatches.",
        step3Title: "Share and keep",
        step3Body: "Every build gets a short permanent link you can send to anyone.",
        featTitle: "Why build here",
        feat1Title: "Prices from leading shops",
        feat1Body: "Prices are collected from vendor sites and refreshed every day.",
        feat2Title: "Compatibility guidance",
        feat2Body: "Warnings about problem pairings before you spend money.",
        feat3Title: "Short share links",
        feat3Body: "Every build gets a permanent link you can send to anyone.",
        feat4Title: "No account and no cookies",
        feat4Body: "No signup, no tracking and no banners. Just build.",
      };

  container.innerHTML = `
    <section class="hero hero--landing">
      <p class="hero-eyebrow">${copy.eyebrow}</p>
      <h1>${t(lang, "heroTitle")}</h1>
      <p>${t(lang, "heroSub")}</p>
      <div class="hero-cta">
        <a class="btn-primary btn-icon" href="${buildHash({})}">${icon("wrench", 15)}<span>${t(lang, "startBuild")}</span></a>
        <a class="btn-ghost" href="${categoriesHash()}">${copy.browseCta}</a>
      </div>
      <dl class="hero-stats">
        <div><dt>${totalParts.toLocaleString(he ? "he-IL" : "en-US")}</dt><dd>${copy.statsPartsLabel}</dd></div>
        <div><dt>${categoryCount}</dt><dd>${copy.statsCatsLabel}</dd></div>
        <div><dt>${he ? "כל יום" : "Daily"}</dt><dd>${copy.statsRefreshLabel}</dd></div>
      </dl>
    </section>

    <section class="landing-section">
      <h2 class="section-title section-title--center">${copy.howTitle}</h2>
      <div class="landing-steps">
        <div class="landing-step"><span class="step-num">1</span><h3>${copy.step1Title}</h3><p>${copy.step1Body}</p></div>
        <div class="landing-step"><span class="step-num">2</span><h3>${copy.step2Title}</h3><p>${copy.step2Body}</p></div>
        <div class="landing-step"><span class="step-num">3</span><h3>${copy.step3Title}</h3><p>${copy.step3Body}</p></div>
      </div>
    </section>

    <section class="landing-section">
      <h2 class="section-title section-title--center">${copy.featTitle}</h2>
      <div class="landing-features">
        <div class="landing-feature"><span class="feat-mark">${icon("coin", 18)}</span><h3>${copy.feat1Title}</h3><p>${copy.feat1Body}</p></div>
        <div class="landing-feature"><span class="feat-mark">${icon("check", 18)}</span><h3>${copy.feat2Title}</h3><p>${copy.feat2Body}</p></div>
        <div class="landing-feature"><span class="feat-mark">${icon("copy", 18)}</span><h3>${copy.feat3Title}</h3><p>${copy.feat3Body}</p></div>
        <div class="landing-feature"><span class="feat-mark">${icon("chip", 18)}</span><h3>${copy.feat4Title}</h3><p>${copy.feat4Body}</p></div>
      </div>
    </section>
  `;
}