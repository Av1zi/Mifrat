import { loadMeta } from "../api";
import { CATEGORY_ORDER, categoryLabel, homeCatsSub, t } from "../i18n";
import { CATEGORY_ICONS, icon } from "../icons";
import { bindSearch } from "../search";
import { categoriesHash, categoryHash, navigate, searchHash } from "../state";
import { setPageTitle } from "../titles";
import type { CategoryMeta, Currency, Lang } from "../types";
import { html, mount, type Html } from "../ui/html";
import { errorState, loadingState } from "../ui/state";
import { safeImageUrl } from "../utils";
import { fillDropsStrip } from "./drops";
import { fillHomeBuild, homeBuildSkeleton } from "./homeBuild";

/** Decorative circuit rings behind the hero (pure SVG, no request). */
const HERO_DECO = html`<svg class="home-hero__deco" viewBox="0 0 640 796" fill="none" aria-hidden="true" focusable="false">
  <g stroke="currentColor" stroke-width="2" opacity="0.18"><circle cx="520" cy="400" r="120"/><circle cx="520" cy="400" r="200"/><circle cx="520" cy="400" r="280"/><circle cx="520" cy="400" r="360"/></g>
  <g stroke="currentColor" stroke-width="2" opacity="0.22"><path d="M520 400H640M520 400V0M520 400L300 180M520 400L300 620"/><rect x="460" y="340" width="120" height="120" rx="14" fill="currentColor" fill-opacity="0.08"/></g>
  <g fill="currentColor" opacity="0.3"><circle cx="300" cy="180" r="8"/><circle cx="300" cy="620" r="8"/><circle cx="520" cy="40" r="8"/><circle cx="620" cy="400" r="8"/></g>
</svg>`;

function catCard(cat: CategoryMeta, lang: Lang): Html {
  const cover = safeImageUrl(cat.cover);
  return html`<a class="card ccat" href="${categoryHash(cat.id)}">
    <span class="ccat__img">${cover
      ? html`<img src="${cover}" alt="" loading="lazy" decoding="async" width="256" height="256">`
      : icon(CATEGORY_ICONS[cat.id] ?? "grid", 44)}</span>
    <span class="ccat__body">
      <span class="ccat__name">${categoryLabel(cat.id, lang)}</span>
      <span class="ccat__count">${cat.count.toLocaleString(lang === "he" ? "he-IL" : "en-US")} ${t(lang, "homeTileProducts")}</span>
    </span>
  </a>`;
}

/** Category rail: native horizontal scroll with snap; the arrows page it in the reading direction. */
function bindRail(root: HTMLElement): void {
  const rail = root.querySelector<HTMLElement>('[data-role="cat-rail"]');
  const prev = root.querySelector<HTMLButtonElement>('[data-role="rail-prev"]');
  const next = root.querySelector<HTMLButtonElement>('[data-role="rail-next"]');
  if (!rail || !prev || !next) return;
  const rtl = getComputedStyle(rail).direction === "rtl";
  const sync = (): void => {
    // scrollLeft runs negative in RTL; compare magnitudes.
    const max = rail.scrollWidth - rail.clientWidth;
    const pos = Math.abs(rail.scrollLeft);
    prev.disabled = pos <= 2;
    next.disabled = pos >= max - 2;
  };
  const page = (dir: 1 | -1): void => {
    const step = Math.max(rail.clientWidth * 0.8, 240) * dir;
    rail.scrollBy({ left: rtl ? -step : step, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };
  prev.addEventListener("click", () => page(-1));
  next.addEventListener("click", () => page(1));
  rail.addEventListener("scroll", sync, { passive: true });
  new ResizeObserver(sync).observe(rail);
  sync();
}

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
    <section class="bleed home-hero">
      ${HERO_DECO}
      <div class="bleed__inner home-hero__inner">
        <div class="home-hero__copy">
          <h1>${t(lang, "homeHeroLine1")}<br>${t(lang, "homeHeroLine2")}</h1>
          <p class="home-hero__sub">${t(lang, "homeHeroSub")}</p>
          <div class="home-hero__search" data-search>
            <label class="search-field search-field--hero">
              ${icon("search", 18)}
              <input data-search-input type="search" placeholder="${t(lang, "homeSearchPlaceholder")}" autocomplete="off" aria-label="${t(lang, "searchLabel")}" role="combobox" aria-expanded="false" aria-autocomplete="list">
              <button type="button" class="btn btn--primary" data-role="hero-search">${t(lang, "searchButton")}</button>
            </label>
            <div class="search-results" data-search-results role="listbox" aria-live="polite" hidden></div>
          </div>
          <div class="home-hero__cta">
            <a class="btn btn--dark btn--lg" href="#/build">${t(lang, "startBuild")}${icon("forward", 16)}</a>
            <a class="btn btn--outline btn--lg" href="${categoriesHash()}">${t(lang, "homeBrowseCta")}</a>
          </div>
        </div>
        <div class="home-build card" data-role="home-build">${homeBuildSkeleton(lang)}</div>
      </div>
    </section>

    <section class="home-sec" aria-labelledby="home-cats">
      <header class="sec-head">
        <div>
          <h2 id="home-cats">${t(lang, "homeCatsTitle")}</h2>
          <p>${homeCatsSub(lang, cats.length, totalParts.toLocaleString(locale))}</p>
        </div>
        <div class="sec-head__end">
          <a class="sec-head__link" href="${categoriesHash()}">${t(lang, "browseAllCategories")}</a>
          <button type="button" class="round-btn" data-role="rail-prev" aria-label="${t(lang, "prevLabel")}">${icon(lang === "he" ? "chevron-right" : "chevron-left", 16)}</button>
          <button type="button" class="round-btn" data-role="rail-next" aria-label="${t(lang, "nextLabel")}">${icon(lang === "he" ? "chevron-left" : "chevron-right", 16)}</button>
        </div>
      </header>
      <div class="cat-rail" data-role="cat-rail">${ordered.map((c) => catCard(c, lang))}</div>
    </section>

    <section class="home-sec" id="home-drops" aria-label="${t(lang, "dropsTitle")}" hidden></section>`
  );

  const search = container.querySelector<HTMLElement>("[data-search]");
  if (search) {
    bindSearch(search, lang, currency);
    const input = search.querySelector<HTMLInputElement>("[data-search-input]");
    search.querySelector('[data-role="hero-search"]')?.addEventListener("click", () => {
      if (!input) return;
      const query = input.value.trim();
      if (query) navigate(searchHash(query));
      else input.focus();
    });
  }
  bindRail(container);

  const build = container.querySelector<HTMLElement>('[data-role="home-build"]');
  if (build) void fillHomeBuild(build, lang, currency);

  const drops = container.querySelector<HTMLElement>("#home-drops");
  if (drops) void fillDropsStrip(drops, cats, lang, currency);
}
