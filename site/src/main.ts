import "./style.css";
import "@fontsource/ibm-plex-sans-hebrew/400.css";
import "@fontsource/ibm-plex-sans-hebrew/500.css";
import "@fontsource/ibm-plex-sans-hebrew/600.css";
import "@fontsource/ibm-plex-sans-hebrew/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import { loadCategory, loadMeta } from "./api";
import { ensureFxRate, formatPrice } from "./format";
import { categoryLabel, t } from "./i18n";
import { icon, type IconName } from "./icons";
import {
  applyStoredTheme,
  categoryHash,
  cookiesHash,
  categoriesHash,
  getCurrency,
  getLang,
  getTheme,
  homeHash,
  parseRoute,
  privacyHash,
  productHash,
  qaHash,
  setCurrency,
  setLang,
  setTheme,
  termsHash,
  type Theme,
} from "./state";
import type { Currency, Lang, Product } from "./types";
import { displayName, errorPanel, esc, safeImageUrl } from "./utils";
import { renderBuilder, renderListRoute } from "./views/builder";
import { renderCategory } from "./views/category";
import { renderCategories } from "./views/categories";
import { renderCookies } from "./views/cookies";
import { renderHome } from "./views/home";
import { renderNotFound } from "./views/notfound";
import { renderPrivacy } from "./views/privacy";
import { renderProduct } from "./views/product";
import { renderQa } from "./views/qa";
import { renderTerms } from "./views/terms";
import { setPageTitle } from "./titles";

let lang: Lang = getLang();
let currency: Currency = getCurrency();
let theme: Theme = applyStoredTheme();
const app = document.getElementById("app")!;

function applyDocumentLang(): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
}

// Mirrors PCPP's browse-products dropdown: 8 popular tiles + grouped links.
// Popular tiles are core shortcuts; groups cover core + cooling + extras
// with no duplicated ids between tiles and groups.
const POPULAR_CATS = [
  "cpu",
  "motherboard",
  "memory",
  "gpu",
  "storage",
  "psu",
  "case",
  "cooler_air",
];
const CORE_CATS = [
  "cpu",
  "motherboard",
  "memory",
  "gpu",
  "storage",
  "psu",
  "case",
];
const COOLING_CATS = ["aio", "cooling_other", "case_fan"];
const ACCESSORY_CATS = ["accessories", "other"];

const TILE_ICONS: Record<string, IconName> = {
  cpu: "chip",
  cooler_air: "fan",
  motherboard: "board",
  memory: "memory",
  storage: "drive",
  gpu: "graphics",
  psu: "power",
  case: "tower",
};

function catTile(id: string, current: string | null): string {
  const label = categoryLabel(id, lang);
  const here = current === id ? " current" : "";
  const hereAttr = current === id ? ' aria-current="page"' : "";
  return `<a class="mega-tile${here}" href="${categoryHash(id)}"${hereAttr}><span class="mega-tile-mark" aria-hidden="true">${icon(TILE_ICONS[id] ?? "chip", 22)}</span><span>${esc(label)}</span></a>`;
}

function catLink(id: string): string {
  return `<a href="${categoryHash(id)}">${esc(categoryLabel(id, lang))}</a>`;
}

function renderShell(): void {
  applyDocumentLang();
  document.documentElement.dataset.theme = theme;
  const route = parseRoute();
  const isBuild = route.view === "build";
  const isHome = route.view === "home";
  const isProducts = route.view === "categories" || route.view === "category" || route.view === "product";
  const currentCategory =
    route.view === "category"
      ? route.category
      : route.view === "product"
        ? route.category
        : null;

  app.innerHTML = `
    <header class="site-header">
      <div class="header-top">
        <a class="brand" href="${homeHash()}">
          <span class="brand-mark">${icon("chip", 16)}</span>
          ${t(lang, "appName")}
          <small>${esc(lang === "he" ? t("en", "appName") : t("he", "appName"))}</small>
        </a>
        <div class="header-spacer"></div>
        <div class="header-actions">
          <label class="nav-select" title="${t(lang, "currencyToggle")}">
            ${icon("coin", 14)}
            <select id="currency-select" aria-label="${t(lang, "currencyToggle")}">
              <option value="ILS" ${currency === "ILS" ? "selected" : ""}>ILS (₪)</option>
              <option value="USD" ${currency === "USD" ? "selected" : ""}>USD ($)</option>
            </select>
          </label>
          <label class="nav-select" title="${t(lang, "langToggle")}">
            ${icon("globe", 14)}
            <select id="lang-select" aria-label="${t(lang, "langToggle")}">
              <option value="he" ${lang === "he" ? "selected" : ""}>עברית</option>
              <option value="en" ${lang === "en" ? "selected" : ""}>English</option>
            </select>
          </label>
          <button class="icon-toggle theme-btn" id="theme-toggle" type="button" title="${theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight")}" aria-label="${theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight")}">
            ${icon(theme === "light" ? "moon" : "sun", 14)}
            <span>${theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight")}</span>
          </button>
        </div>
      </div>
      <nav class="header-nav" aria-label="main">
        <div class="header-nav-inner">
          <a class="nav-build ${isBuild ? "active" : ""}" data-nav="build" href="#/build"${isBuild ? ' aria-current="page"' : ""}>${icon("wrench", 15)}<span>${t(lang, "builderNav")}</span></a>
          <div class="nav-products">
            <button class="nav-link nav-products-btn ${isProducts ? "active" : ""}" data-nav="products" id="products-btn" type="button" aria-expanded="false" aria-haspopup="true" aria-controls="mega-menu"${isProducts ? ' aria-current="page"' : ""}>
              ${icon("chip", 15)}<span>${t(lang, "productsMenu")}</span>${icon("chevron", 13)}
            </button>
          </div>
          <a class="nav-link ${isHome ? "active" : ""}" data-nav="home" href="${homeHash()}"${isHome ? ' aria-current="page"' : ""}>${t(lang, "home")}</a>
          <span class="nav-search-spacer"></span>
          <button class="nav-link nav-search-btn" id="search-btn" type="button" aria-label="${t(lang, "searchLabel")}" aria-expanded="false" aria-controls="search-panel">
            ${icon("search", 15)}
          </button>
        </div>
        <div class="mega-menu" id="mega-menu" hidden role="menu" aria-label="${esc(t(lang, "productsMenu"))}">
          <div class="mega-inner">
            <a class="mega-all-link" href="${categoriesHash()}">${esc(t(lang, "browseAllCategories"))} ${icon("arrow-right", 14)}</a>
            <div class="mega-popular">
              ${POPULAR_CATS.map((id) => catTile(id, currentCategory)).join("")}
            </div>
            <div class="mega-groups">
              <div class="mega-col">
                <h3>${t(lang, "componentHeading")}</h3>
                ${CORE_CATS.map(catLink).join("")}
              </div>
              <div class="mega-col">
                <h3>${t(lang, "coolingHeading")}</h3>
                ${COOLING_CATS.map(catLink).join("")}
              </div>
              <div class="mega-col">
                <h3>${t(lang, "accessoriesHeading")}</h3>
                ${ACCESSORY_CATS.map(catLink).join("")}
              </div>
            </div>
          </div>
        </div>
        <div class="nav-search-panel" id="search-panel" hidden>
          <div class="nav-search-inner">
            ${icon("search", 15)}
            <input id="global-search" type="search" placeholder="${esc(t(lang, "searchLabel"))}" autocomplete="off" aria-label="${t(lang, "searchLabel")}" role="combobox" aria-expanded="false" aria-controls="global-results" aria-autocomplete="list">
          </div>
          <div class="global-results" id="global-results" role="listbox" aria-live="polite"></div>
        </div>
      </nav>
    </header>
    <main id="main-content"></main>
    <footer class="site-footer">
      <p>${t(lang, "disclaimer")}</p>
      <a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">${t(lang, "sourceLinkLabel")}</a>
      <span aria-hidden="true"> · </span><a href="${privacyHash()}">${t(lang, "privacyTitle")}</a>
      <span aria-hidden="true"> · </span><a href="${termsHash()}">${t(lang, "termsTitle")}</a>
      <span aria-hidden="true"> · </span><a href="${cookiesHash()}">${t(lang, "cookiesTitle")}</a>
      <span aria-hidden="true"> · </span><a href="${qaHash()}">${t(lang, "qaTitle")}</a>
    </footer>`;

  (document.getElementById("lang-select") as HTMLSelectElement).addEventListener("change", (e) => {
    lang = (e.target as HTMLSelectElement).value as Lang;
    setLang(lang);
    renderShell();
  });
  (document.getElementById("currency-select") as HTMLSelectElement).addEventListener("change", (e) => {
    currency = (e.target as HTMLSelectElement).value as Currency;
    setCurrency(currency);
    // FX fetch is opt-in via currency selection (audit §3.1): ILS mode
    // makes zero external requests; USD fetches at most once per day.
    if (currency === "USD") void ensureFxRate();
    renderShell();
  });
  document.getElementById("theme-toggle")!.addEventListener("click", () => {
    theme = theme === "light" ? "dark" : "light";
    setTheme(theme);
    renderShell();
  });

  const mega = document.getElementById("mega-menu")!;
  const productsBtn = document.getElementById("products-btn")!;
  const panel = document.getElementById("search-panel")!;
  const searchBtn = document.getElementById("search-btn")!;
  const searchInput = document.getElementById("global-search") as HTMLInputElement;

  const closeMenus = () => {
    mega.hidden = true;
    panel.hidden = true;
    productsBtn.setAttribute("aria-expanded", "false");
    searchBtn.setAttribute("aria-expanded", "false");
  };

  productsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = mega.hidden;
    closeMenus();
    if (willOpen) {
      mega.hidden = false;
      productsBtn.setAttribute("aria-expanded", "true");
    }
  });

  searchBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    closeMenus();
    if (willOpen) {
      panel.hidden = false;
      searchBtn.setAttribute("aria-expanded", "true");
      searchInput.focus();
    }
  });

  let debounce: number | undefined;
  let searchSeq = 0;
  searchInput.addEventListener("input", () => {
    window.clearTimeout(debounce);
    const q = searchInput.value.trim();
    searchInput.setAttribute("aria-expanded", q.length >= 2 ? "true" : "false");
    debounce = window.setTimeout(() => {
      const mySeq = ++searchSeq;
      void runGlobalSearch(q, mySeq);
    }, 220);
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenus();
    else if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter") {
      const box = document.getElementById("global-results");
      const hits = box ? Array.from(box.querySelectorAll<HTMLElement>(".global-hit")) : [];
      if (hits.length === 0) return;
      e.preventDefault();
      let idx = hits.findIndex((h) => h.classList.contains("is-active"));
      if (e.key === "ArrowDown") idx = idx < hits.length - 1 ? idx + 1 : 0;
      else if (e.key === "ArrowUp") idx = idx > 0 ? idx - 1 : hits.length - 1;
      else if (e.key === "Enter") {
        const target = idx >= 0 ? hits[idx] : hits[0];
        (target as HTMLAnchorElement).click();
        return;
      }
      hits.forEach((h, i) => {
        const on = i === idx;
        h.classList.toggle("is-active", on);
        h.setAttribute("aria-selected", on ? "true" : "false");
        if (on) h.scrollIntoView({ block: "nearest" });
      });
    }
  });

  renderRoute();
  updateNavActive();
}

export function updateNavActive(): void {
  const route = parseRoute();
  const isBuild = route.view === "build";
  const isHome = route.view === "home";
  const isProducts =
    route.view === "categories" ||
    route.view === "category" ||
    route.view === "product";
  const buildLink = document.querySelector('[data-nav="build"]');
  const homeLink = document.querySelector('[data-nav="home"]');
  const productsBtn = document.getElementById("products-btn");
  buildLink?.classList.toggle("active", isBuild);
  homeLink?.classList.toggle("active", isHome);
  productsBtn?.classList.toggle("active", isProducts);
  if (isBuild) buildLink?.setAttribute("aria-current", "page");
  else buildLink?.removeAttribute("aria-current");
  if (isHome) homeLink?.setAttribute("aria-current", "page");
  else homeLink?.removeAttribute("aria-current");
  if (isProducts) productsBtn?.setAttribute("aria-current", "page");
  else productsBtn?.removeAttribute("aria-current");
}

interface SearchEntry {
  product: Product;
  haystack: string;
}

let searchIndex: SearchEntry[] | null = null;
let searchSeqLive = 0;

function normHay(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFKC")
    .replace(/["'`׳״־–—]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function ensureSearchIndex(mySeq: number): Promise<SearchEntry[]> {
  if (searchIndex) return searchIndex;
  const meta = await loadMeta();
  const ids = meta.categories
    .filter((c) => c.count > 0)
    .map((c) => c.id);
  const out: SearchEntry[] = [];
  // Sequential lazy load (no Promise.all spike); abortable via seq.
  for (const id of ids) {
    if (mySeq !== searchSeqLive) throw new Error("aborted");
    try {
      const list = await loadCategory(id);
      for (const product of list) {
        const sku = (product as { sku?: unknown }).sku;
        out.push({
          product,
          haystack: normHay(
            `${product.name} ${product.brand ?? ""} ${product.model ?? ""} ${typeof sku === "string" ? sku : ""} ${product.category} ${categoryLabel(product.category, lang)}`
          ),
        });
      }
      // Publish partial index progressively so first hits appear fast.
      searchIndex = out.slice();
    } catch {
      // Ignore per-category failures.
    }
    // Yield to keep typing responsive while backfilling.
    await new Promise((r) => setTimeout(r, 0));
  }
  searchIndex = out;
  return out;
}

async function runGlobalSearch(query: string, mySeq: number): Promise<void> {
  searchSeqLive = mySeq;
  const box = document.getElementById("global-results");
  if (!box) return;
  if (query.length < 2) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `<div class="global-status" role="status">${t(lang, "loading")}</div>`;
  try {
    const index = await ensureSearchIndex(mySeq);
    if (mySeq !== searchSeqLive) return;
    const q = normHay(query);
    const hits = index.filter((e) => e.haystack.includes(q)).slice(0, 8);
    if (hits.length === 0) {
      box.innerHTML = `<div class="global-status" role="status">${t(lang, "noResults")}</div>`;
      return;
    }
    box.innerHTML = hits
      .map(({ product }) => {
        const img = safeImageUrl(product.image);
        const name = displayName(product);
        const thumb = img
          ? `<img src="${esc(img)}" alt="${esc(name)}" loading="lazy" width="40" height="40">`
          : `<span class="plThumb" aria-hidden="true">${esc((product.brand ?? product.name).slice(0, 2).toUpperCase())}</span>`;
        const price =
          product.min_price === null || product.min_price === undefined
            ? "-"
            : formatPrice(product.min_price, currency, lang);
        return `
          <a class="global-hit" role="option" aria-selected="false" href="${productHash(product.category, product.id)}">
            ${thumb}
            <span class="global-hit-name">${esc(name)}<span class="global-hit-cat"> · ${esc(categoryLabel(product.category, lang))}</span></span>
            <span class="global-hit-price">${esc(price)}</span>
          </a>`;
      })
      .join("");
  } catch (err) {
    if ((err as Error)?.message === "aborted") return;
    box.innerHTML = `<div class="global-status" role="status">${t(lang, "loadError")}</div>`;
  }
}

function closeOpenMenus(): void {
  const mega = document.getElementById("mega-menu");
  const panel = document.getElementById("search-panel");
  const productsBtn = document.getElementById("products-btn");
  const searchBtn = document.getElementById("search-btn");
  if (mega) mega.hidden = true;
  if (panel) panel.hidden = true;
  productsBtn?.setAttribute("aria-expanded", "false");
  searchBtn?.setAttribute("aria-expanded", "false");
}

// Registered once: menus are re-created by renderShell, so these
// query the live DOM instead of holding stale references.
document.addEventListener("click", (e) => {
  const target = e.target as HTMLElement;
  if (!target.closest(".header-nav")) closeOpenMenus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeOpenMenus();
});
window.addEventListener("hashchange", () => {
  closeOpenMenus();
  renderRoute();
  updateNavActive();
});

function routeError(main: HTMLElement, err: unknown): void {
  main.innerHTML = errorPanel(t(lang, "loadError"), t(lang, "retry"), err);
}

function renderRoute(): void {
  const main = document.getElementById("main-content")!;
  const route = parseRoute();
  // Any failure after the loading state (stalled fetch, corrupt data,
  // unexpected shape) lands here instead of hanging on "loading" forever.
  if (route.view === "privacy") {
    try {
      renderPrivacy(main, lang);
    } catch (err) {
      console.error("[route]", err);
      routeError(main, err);
    }
    updateNavActive();
    return;
  }
  if (route.view === "terms" || route.view === "cookies") {
    try {
      if (route.view === "terms") renderTerms(main, lang);
      else renderCookies(main, lang);
    } catch (err) {
      console.error("[route]", err);
      routeError(main, err);
    }
    updateNavActive();
    return;
  }
  if (route.view === "qa") {
    setPageTitle(lang, t(lang, "qaTitle"));
    renderQa(main, lang, currency).catch((err) => {
      console.error("[route]", err);
      routeError(main, err);
    });
    updateNavActive();
    return;
  }
  if (route.view === "categories") {
    setPageTitle(lang, t(lang, "allCategoriesTitle"));
    renderCategories(main, lang, currency).catch((err) => {
      console.error("[route]", err);
      routeError(main, err);
    });
    updateNavActive();
    return;
  }
  if (route.view === "notfound") {
    try {
      renderNotFound(main, lang);
    } catch (err) {
      console.error("[route]", err);
      routeError(main, err);
    }
    updateNavActive();
    return;
  }
  if (route.view === "build") {
    const shared = route.listId !== null || route.shared !== null;
    setPageTitle(lang, shared ? t(lang, "sharedBuildTitle") : t(lang, "builderPageTitle"));
  } else if (route.view === "category") {
    setPageTitle(lang, categoryLabel(route.category, lang));
  } else if (route.view === "product") {
    setPageTitle(lang, t(lang, "productPageTitle"));
  }
  const task =
    route.view === "home"
      ? renderHome(main, lang, currency)
      : route.view === "build"
        ? route.listId
          ? renderListRoute(main, lang, currency, route.listId)
          : renderBuilder(main, lang, currency, route.shared, null)
        : route.view === "product"
          ? renderProduct(main, lang, currency, route.category, route.productId)
          : renderCategory(main, lang, currency, route.category, route.params);
  task.catch((err) => {
    console.error("[route]", err);
    routeError(main, err);
  });
  updateNavActive();
}

void (async () => {
  // FX is opt-in: only USD display needs the frankfurter rate (audit
  // §3.1). ILS-default visitors make zero third-party requests on load.
  if (getCurrency() === "USD") await ensureFxRate();
})();
// Keep theme in sync if OS preference changes and user never picked one.
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
  if (!localStorage.getItem("mifrat:theme")) {
    theme = getTheme();
    renderShell();
  }
});
renderShell();
