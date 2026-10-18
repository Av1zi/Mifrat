import { loadMeta } from "../api";
import { ACTIVE_VENDORS, CATEGORY_ORDER, categoryLabel, t, vendorLabel } from "../i18n";
import { icon } from "../icons";
import { bindSearch } from "../search";
import { buildHash, categoriesHash, categoryHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { button } from "../ui/button";
import { categoryTile, fillCategoryPhotos } from "../ui/categoryTile";
import { chip } from "../ui/chip";
import { html, mount } from "../ui/html";
import { errorState, loadingState } from "../ui/state";
import { fillDropsStrip } from "./drops";

const QUICK_CATEGORIES = ["cpu", "gpu", "motherboard", "memory", "storage", "psu"];

export async function renderHome(container: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
  setPageTitle(lang, t(lang, "homePageTitle"));
  mount(container, loadingState(lang));

  let meta;
  try {
    meta = await loadMeta();
  } catch (err) {
    mount(container, errorState(lang, err));
    return;
  }

  const locale = lang === "he" ? "he-IL" : "en-US";
  const cats = meta.categories.filter((c) => c.count > 0);
  const totalParts = cats.reduce((n, c) => n + c.count, 0);
  const order = CATEGORY_ORDER as readonly string[];
  const ordered = [...cats].sort((a, b) => {
    const ia = order.indexOf(a.id);
    const ib = order.indexOf(b.id);
    return (ia === -1 ? order.length : ia) - (ib === -1 ? order.length : ib);
  });

  mount(
    container,
    html`
    <section class="hero">
      <p class="eyebrow">${t(lang, "homeEyebrow")}</p>
      <h1>${t(lang, "homeHeroTitle")}</h1>
      <p class="hero__sub">${t(lang, "homeHeroSub")}</p>
      <div class="hero__search" data-search>
        <label class="search-field search-field--lg">
          ${icon("search", 20)}
          <input data-search-input type="search" placeholder="${t(lang, "homeSearchPlaceholder")}" autocomplete="off" aria-label="${t(lang, "searchLabel")}" role="combobox" aria-expanded="false" aria-autocomplete="list">
        </label>
        <div class="search-results" data-search-results role="listbox" aria-live="polite" hidden></div>
      </div>
      <div class="hero__quick">
        <span class="text-dim">${t(lang, "homePopular")}</span>
        ${QUICK_CATEGORIES.map((id) => chip(categoryLabel(id, lang), { href: categoryHash(id) }))}
      </div>
      <div class="hero__cta">
        ${button({ label: t(lang, "startBuild"), icon: icon("wrench", 16), variant: "primary", href: buildHash({}) })}
        ${button({ label: t(lang, "homeBrowseCta"), href: categoriesHash() })}
      </div>
      <dl class="hero__stats">
        <div><dt>${totalParts.toLocaleString(locale)}</dt><dd>${t(lang, "homeStatsParts")}</dd></div>
        <div><dt>${cats.length}</dt><dd>${t(lang, "homeStatsCats")}</dd></div>
        <div><dt>${ACTIVE_VENDORS.length}</dt><dd>${t(lang, "homeStatsVendors")}</dd></div>
        <div><dt>${t(lang, "homeStatsDaily")}</dt><dd>${t(lang, "homeStatsRefresh")}</dd></div>
      </dl>
    </section>

    <section class="section" id="home-drops" hidden></section>

    <section class="section">
      <header class="section__head">
        <h2>${t(lang, "homeCatsTitle")}</h2>
        <a href="${categoriesHash()}">${t(lang, "browseAllCategories")}</a>
      </header>
      <div class="cat-grid">${ordered.map((c) => categoryTile(c, currency, lang))}</div>
    </section>

    <section class="vendor-strip" aria-label="${t(lang, "homeVendorsTitle")}">
      <p>${t(lang, "homeVendorsTitle")}</p>
      <ul>${ACTIVE_VENDORS.map((v) => html`<li>${vendorLabel(v)}</li>`)}</ul>
    </section>

    <section class="section">
      <header class="section__head"><h2>${t(lang, "homeHowTitle")}</h2></header>
      <ol class="steps">
        ${[1, 2, 3].map(
          (n) => html`<li class="step">
            <span class="step__num" aria-hidden="true">${n}</span>
            <h3>${t(lang, `homeStep${n}Title` as "homeStep1Title")}</h3>
            <p>${t(lang, `homeStep${n}Body` as "homeStep1Body")}</p>
          </li>`
        )}
      </ol>
    </section>`
  );

  const search = container.querySelector<HTMLElement>("[data-search]");
  if (search) bindSearch(search, lang, currency);
  fillCategoryPhotos(container);

  const drops = container.querySelector<HTMLElement>("#home-drops");
  if (drops) void fillDropsStrip(drops, cats, lang, currency);
}
