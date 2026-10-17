import { loadCategoryRepImage, loadMeta } from "../api";
import { formatPrice } from "../format";
import { CATEGORY_LABELS, t } from "../i18n";
import { icon, type IconName } from "../icons";
import { buildHash, categoriesHash, categoryHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { esc, errorPanel, safeImageUrl } from "../utils";

const PORTAL_ICONS: Record<string, IconName> = {
  cpu: "chip",
  motherboard: "board",
  memory: "memory",
  gpu: "graphics",
  storage: "drive",
  psu: "power",
  case: "tower",
  cooler_air: "fan",
  aio: "fan",
  case_fan: "fan",
  cooling_other: "fan",
  accessories: "copy",
  other: "chip",
};

export async function renderHome(container: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
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
  const catsWithParts = meta.categories.filter((c) => c.count > 0);

  // Portal tiles: icon + label + count + price range, one per category.
  const portalTiles = catsWithParts
    .map((c) => {
      const label = CATEGORY_LABELS[c.id]?.[lang] ?? c.id;
      const price =
        c.min_price !== null && c.min_price > 0
          ? `${formatPrice(c.min_price, currency, lang)}${c.max_price !== null && c.max_price > c.min_price ? ` – ${formatPrice(c.max_price, currency, lang)}` : ""}`
          : "";
      return `
        <a class="portal-tile" href="${categoryHash(c.id)}">
          <span class="portal-photo" data-portal-photo="${esc(c.id)}" aria-hidden="true">
            <img alt="" loading="lazy" width="160" height="96" hidden>
            <span class="portal-fallback">${icon(PORTAL_ICONS[c.id] ?? "chip", 30)}</span>
          </span>
          <span class="portal-body">
            <span class="portal-name">${esc(label)}</span>
            <span class="portal-count">${c.count.toLocaleString(he ? "he-IL" : "en-US")} · ${t(lang, "homeTileProducts")}</span>
            ${price ? `<span class="portal-price">${esc(price)}</span>` : ""}
          </span>
        </a>`;
    })
    .join("");

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

    <section class="landing-section portal-section">
      <h2 class="section-title section-title--center">${t(lang, "homeCatsTitle")}</h2>
      <div class="portal-grid">${portalTiles}</div>
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

  // Lazy-fill portal tile photos (same pattern as the mega menu).
  for (const el of container.querySelectorAll<HTMLElement>("[data-portal-photo]")) {
    const id = el.dataset.portalPhoto!;
    void loadCategoryRepImage(id).then((src) => {
      const url = safeImageUrl(src);
      if (!url) return;
      const img = el.querySelector("img");
      if (!img) return;
      img.src = url;
      img.hidden = false;
      const fb = el.querySelector(".portal-fallback");
      if (fb) fb.remove();
    });
  }
}
