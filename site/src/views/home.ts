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
  setPageTitle(lang, t(lang, "homePageTitle"));

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

  container.innerHTML = `
    <section class="hero hero--landing">
      <p class="hero-eyebrow">${t(lang, "homeEyebrow")}</p>
      <h1>${t(lang, "heroTitle")}</h1>
      <p>${t(lang, "heroSub")}</p>
      <div class="hero-cta">
        <a class="btn-primary btn-icon" href="${buildHash({})}">${icon("wrench", 15)}<span>${t(lang, "startBuild")}</span></a>
        <a class="btn-ghost" href="${categoriesHash()}">${t(lang, "homeBrowseCta")}</a>
      </div>
      <dl class="hero-stats">
        <div><dt>${totalParts.toLocaleString(he ? "he-IL" : "en-US")}</dt><dd>${t(lang, "homeStatsParts")}</dd></div>
        <div><dt>${categoryCount}</dt><dd>${t(lang, "homeStatsCats")}</dd></div>
        <div><dt>${t(lang, "homeStatsDaily")}</dt><dd>${t(lang, "homeStatsRefresh")}</dd></div>
      </dl>
    </section>

    <section class="landing-section">
      <h2 class="section-title section-title--center">${t(lang, "homeHowTitle")}</h2>
      <div class="landing-steps">
        <div class="landing-step"><span class="step-num" aria-hidden="true">1</span><h3>${t(lang, "homeStep1Title")}</h3><p>${t(lang, "homeStep1Body")}</p></div>
        <div class="landing-step"><span class="step-num" aria-hidden="true">2</span><h3>${t(lang, "homeStep2Title")}</h3><p>${t(lang, "homeStep2Body")}</p></div>
        <div class="landing-step"><span class="step-num" aria-hidden="true">3</span><h3>${t(lang, "homeStep3Title")}</h3><p>${t(lang, "homeStep3Body")}</p></div>
      </div>
    </section>

    <section class="landing-section">
      <h2 class="section-title section-title--center">${t(lang, "homeFeatTitle")}</h2>
      <div class="landing-features">
        <div class="landing-feature"><span class="feat-mark" aria-hidden="true">${icon("coin", 18)}</span><h3>${t(lang, "homeFeat1Title")}</h3><p>${t(lang, "homeFeat1Body")}</p></div>
        <div class="landing-feature"><span class="feat-mark" aria-hidden="true">${icon("check", 18)}</span><h3>${t(lang, "homeFeat2Title")}</h3><p>${t(lang, "homeFeat2Body")}</p></div>
        <div class="landing-feature"><span class="feat-mark" aria-hidden="true">${icon("copy", 18)}</span><h3>${t(lang, "homeFeat3Title")}</h3><p>${t(lang, "homeFeat3Body")}</p></div>
        <div class="landing-feature"><span class="feat-mark" aria-hidden="true">${icon("chip", 18)}</span><h3>${t(lang, "homeFeat4Title")}</h3><p>${t(lang, "homeFeat4Body")}</p></div>
      </div>
    </section>
  `;
}