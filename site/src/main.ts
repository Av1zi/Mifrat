import "./style.css";
import { loadCategory, loadMeta } from "./api";
import { ensureFxRate, formatPrice } from "./format";
import { categoryLabel, t } from "./i18n";
import { icon, type IconName } from "./icons";
import {
  applyStoredTheme,
  getCurrency,
  getLang,
  getTheme,
  homeHash,
  parseRoute,
  productHash,
  setCurrency,
  setLang,
  setTheme,
  type Theme,
} from "./state";
import type { Currency, Lang, Product } from "./types";
import { displayName, errorPanel, esc } from "./utils";
import { renderBuilder } from "./views/builder";
import { renderCategory } from "./views/category";
import { renderHome } from "./views/home";
import { renderProduct } from "./views/product";

let lang: Lang = getLang();
let currency: Currency = getCurrency();
let theme: Theme = applyStoredTheme();
const app = document.getElementById("app")!;

function applyDocumentLang(): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
}

// Mirrors PCPP's browse-products dropdown: 8 popular tiles + grouped links.
const POPULAR_CATS = [
  "cpu",
  "cooler_air",
  "motherboard",
  "memory",
  "storage",
  "gpu",
  "psu",
  "case",
];
const COOLING_CATS = ["aio", "cooler_air", "cooling_other", "case_fan", "fan_controller"];
const ACCESSORY_CATS = ["cooler_accessory", "thermal_paste", "rgb_lighting", "other"];

const TILE_ICONS: Record<string, IconName> = {
  cpu: "chip",
  cooler_air: "cooler",
  motherboard: "motherboard",
  memory: "memory",
  storage: "storage",
  gpu: "gpu",
  psu: "psu",
  case: "case",
};

function catTile(id: string, current: string | null): string {
  const label = categoryLabel(id, lang);
  const here = current === id ? " current" : "";
  const hereAttr = current === id ? ' aria-current="page"' : "";
  return `<a class="mega-tile${here}" href="#/c/${id}"${hereAttr}><span class="mega-tile-mark" aria-hidden="true">${icon(TILE_ICONS[id] ?? "chip", 22)}</span><span>${esc(label)}</span></a>`;
}

function catLink(id: string): string {
  return `<a href="#/c/${id}">${esc(categoryLabel(id, lang))}</a>`;
}

function renderShell(): void {
  applyDocumentLang();
  document.documentElement.dataset.theme = theme;
  const route = parseRoute();
  const isBuild = route.view === "build";
  const isHome = route.view === "home";
  const isProducts = route.view === "category" || route.view === "product";
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
          <span class="brand-mark">◈</span>
          ${t(lang, "appName")}
          <small>${lang === "he" ? "Mifrat" : "מפרט"}</small>
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
          <button class="icon-toggle theme-btn" id="theme-toggle" type="button" title="${theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight")}">
            ${icon(theme === "light" ? "moon" : "sun", 14)}
            <span>${theme === "light" ? (lang === "he" ? "כהה" : "Dark") : (lang === "he" ? "בהיר" : "Light")}</span>
          </button>
        </div>
      </div>
      <nav class="header-nav" aria-label="main">
        <div class="header-nav-inner">
          <a class="nav-build ${isBuild ? "active" : ""}" href="#/build"${isBuild ? ' aria-current="page"' : ""}>${icon("wrench", 15)}<span>${t(lang, "builderNav")}</span></a>
          <div class="nav-products">
            <button class="nav-link nav-products-btn ${isProducts ? "active" : ""}" id="products-btn" type="button" aria-expanded="false" aria-haspopup="true"${isProducts ? ' aria-current="true"' : ""}>
              ${icon("chip", 15)}<span>${t(lang, "productsMenu")}</span>${icon("chevron", 13)}
            </button>
          </div>
          <a class="nav-link ${isHome ? "active" : ""}" href="${homeHash()}"${isHome ? ' aria-current="page"' : ""}>${t(lang, "home")}</a>
          <span class="nav-search-spacer"></span>
          <button class="nav-link nav-search-btn" id="search-btn" type="button" aria-label="${t(lang, "searchLabel")}" aria-expanded="false">
            ${icon("search", 15)}
          </button>
        </div>
        <div class="mega-menu" id="mega-menu" hidden>
          <div class="mega-inner">
            <div class="mega-popular">
              ${POPULAR_CATS.map((id) => catTile(id, currentCategory)).join("")}
            </div>
            <div class="mega-groups">
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
            <input id="global-search" type="search" placeholder="${esc(t(lang, "searchLabel"))}" autocomplete="off" aria-label="${t(lang, "searchLabel")}">
          </div>
          <div class="global-results" id="global-results"></div>
        </div>
      </nav>
    </header>
    <main id="main-content"></main>
    <footer class="site-footer">
      <p>${t(lang, "disclaimer")}</p>
      <a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">${t(lang, "sourceLinkLabel")}</a>
    </footer>`;

  (document.getElementById("lang-select") as HTMLSelectElement).addEventListener("change", (e) => {
    lang = (e.target as HTMLSelectElement).value as Lang;
    setLang(lang);
    renderShell();
  });
  (document.getElementById("currency-select") as HTMLSelectElement).addEventListener("change", (e) => {
    currency = (e.target as HTMLSelectElement).value as Currency;
    setCurrency(currency);
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
  searchInput.addEventListener("input", () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(() => {
      void runGlobalSearch(searchInput.value.trim());
    }, 220);
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenus();
  });

  renderRoute();
}

interface SearchEntry {
  product: Product;
  haystack: string;
}

let searchIndex: SearchEntry[] | null = null;

async function ensureSearchIndex(): Promise<SearchEntry[]> {
  if (searchIndex) return searchIndex;
  const meta = await loadMeta();
  const lists = await Promise.all(
    meta.categories.map((c) =>
      loadCategory(c.id).catch(() => [] as Product[])
    )
  );
  searchIndex = lists.flat().map((product) => ({
    product,
    haystack: `${product.name} ${product.brand ?? ""} ${product.model ?? ""}`.toLowerCase(),
  }));
  return searchIndex;
}

async function runGlobalSearch(query: string): Promise<void> {
  const box = document.getElementById("global-results");
  if (!box) return;
  if (query.length < 2) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `<div class="global-status">${t(lang, "loading")}</div>`;
  try {
    const index = await ensureSearchIndex();
    const q = query.toLowerCase();
    const hits = index.filter((e) => e.haystack.includes(q)).slice(0, 8);
    if (hits.length === 0) {
      box.innerHTML = `<div class="global-status">${t(lang, "noResults")}</div>`;
      return;
    }
    box.innerHTML = hits
      .map(({ product }) => {
        const thumb = product.image
          ? `<img src="${esc(product.image)}" alt="" loading="lazy">`
          : `<span class="plThumb" aria-hidden="true">${esc((product.brand ?? product.name).slice(0, 2).toUpperCase())}</span>`;
        return `
          <a class="global-hit" href="${productHash(product.category, product.id)}">
            ${thumb}
            <span class="global-hit-name">${esc(displayName(product))}</span>
            <span class="global-hit-price">${formatPrice(product.min_price, currency, lang)}</span>
          </a>`;
      })
      .join("");
  } catch {
    box.innerHTML = `<div class="global-status">${t(lang, "loadError")}</div>`;
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
});

function routeError(main: HTMLElement, err: unknown): void {
  main.innerHTML = errorPanel(t(lang, "loadError"), t(lang, "retry"), err);
}

function renderRoute(): void {
  const main = document.getElementById("main-content")!;
  const route = parseRoute();
  // Any failure after the loading state (stalled fetch, corrupt data,
  // unexpected shape) lands here instead of hanging on "loading" forever.
  const task =
    route.view === "home"
      ? renderHome(main, lang, currency)
      : route.view === "build"
        ? renderBuilder(main, lang, currency, route.shared)
        : route.view === "product"
          ? renderProduct(main, lang, currency, route.category, route.productId)
          : renderCategory(main, lang, currency, route.category, route.params);
  task.catch((err) => {
    console.error("[route]", err);
    routeError(main, err);
  });
}

void ensureFxRate();
// Keep theme in sync if OS preference changes and user never picked one.
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
  if (!localStorage.getItem("mifrat:theme")) {
    theme = getTheme();
    renderShell();
  }
});
renderShell();
