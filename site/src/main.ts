import "./style.css";
import "@fontsource/ibm-plex-sans-hebrew/400.css";
import "@fontsource/ibm-plex-sans-hebrew/500.css";
import "@fontsource/ibm-plex-sans-hebrew/600.css";
import "@fontsource/ibm-plex-sans-hebrew/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import { loadCategory, loadCategoryRepImage, loadIndex } from "./api";
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
import type { Currency, IndexRow, Lang, Product } from "./types";
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
  // Photo band fills in async via fillMegaPhotos(); the icon fallback
  // keeps a fixed-size, no-shift placeholder until the photo arrives.
  return `<a class="mega-tile${here}" href="${categoryHash(id)}"${hereAttr}><span class="mega-tile-photo" data-mega-photo="${esc(id)}" aria-hidden="true"><img alt="" loading="lazy" width="192" height="112" hidden><span class="mega-tile-fallback">${icon(TILE_ICONS[id] ?? "chip", 26)}</span></span><span class="mega-tile-label">${esc(label)}</span></a>`;
}

/**
 * Upgrade mega-menu tiles from icon fallback to real product photos.
 * Idempotent per tile (dataset.filled); failed/missing photos simply
 * keep the icon. Safe to call on every renderShell — resolved promises
 * settle instantly thanks to the api.ts cache.
 */
function fillMegaPhotos(): void {
  const slots = document.querySelectorAll<HTMLElement>("[data-mega-photo]");
  for (const slot of slots) {
    if (slot.dataset.filled) continue;
    slot.dataset.filled = "1";
    const id = slot.dataset.megaPhoto;
    if (!id) continue;
    void loadCategoryRepImage(id).then((src) => {
      if (!src || !slot.isConnected) return;
      const img = slot.querySelector("img");
      if (!img) return;
      img.addEventListener("error", () => img.remove(), { once: true });
      img.src = src;
      img.hidden = false;
      slot.querySelector(".mega-tile-fallback")?.remove();
    });
  }
}

function catLink(id: string): string {
  return `<a href="${categoryHash(id)}">${esc(categoryLabel(id, lang))}</a>`;
}

// The currently expanded header dropdown (currency/lang), if any. Module
// level so the once-registered document handlers below can close it after
// renderShell() has replaced the header DOM.
let openDropdownRoot: HTMLElement | null = null;

function closeDropdown(root: HTMLElement): void {
  const btn = root.querySelector(".nav-select-btn");
  const list = root.querySelector(".nav-select-list");
  if (list instanceof HTMLElement) list.hidden = true;
  btn?.setAttribute("aria-expanded", "false");
  root.querySelectorAll(".is-active").forEach((el) => el.classList.remove("is-active"));
  if (openDropdownRoot === root) openDropdownRoot = null;
}

/**
 * Custom listbox dropdown (currency / language). The whole button is the
 * hitbox — icon, value and chevron all toggle it — so there is no dead
 * padding and no chevron-over-text overlap in either direction: the
 * chevron is a trailing flex icon, not an absolutely-positioned glyph.
 */
function wireDropdown(root: HTMLElement, onPick: (value: string) => void): void {
  const btn = root.querySelector<HTMLButtonElement>(".nav-select-btn")!;
  const list = root.querySelector<HTMLElement>(".nav-select-list")!;
  const options = Array.from(list.querySelectorAll<HTMLElement>('[role="option"]'));
  if (options.length === 0) return;
  let hl = Math.max(
    0,
    options.findIndex((o) => o.getAttribute("aria-selected") === "true")
  );

  const paint = (): void => {
    options.forEach((o, i) => o.classList.toggle("is-active", i === hl));
  };
  const isOpen = (): boolean => !list.hidden;
  const setOpen = (open: boolean): void => {
    if (open && openDropdownRoot && openDropdownRoot !== root) {
      closeDropdown(openDropdownRoot);
    }
    if (open) openDropdownRoot = root;
    else if (openDropdownRoot === root) openDropdownRoot = null;
    list.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) paint();
  };
  const focusOpt = (i: number): void => {
    hl = ((i % options.length) + options.length) % options.length;
    paint();
    options[hl].focus();
  };
  const pick = (i: number): void => {
    const value = options[i]?.dataset.value;
    if (value) onPick(value);
  };

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(!isOpen());
  });

  btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!isOpen()) {
        setOpen(true);
        focusOpt(hl);
      } else {
        focusOpt(hl + 1);
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!isOpen()) {
        setOpen(true);
        focusOpt(hl);
      } else {
        focusOpt(hl - 1);
      }
    } else if ((e.key === "Enter" || e.key === " ") && isOpen()) {
      e.preventDefault();
      pick(hl);
    } else if (e.key === "Escape" && isOpen()) {
      e.stopPropagation();
      setOpen(false);
    } else if (e.key === "Tab" && isOpen()) {
      setOpen(false);
    }
  });

  options.forEach((opt, i) => {
    opt.tabIndex = -1;
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      pick(i);
    });
    opt.addEventListener("mouseenter", () => {
      hl = i;
      paint();
    });
    opt.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        focusOpt(i + 1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        focusOpt(i - 1);
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        pick(i);
      } else if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        btn.focus();
      } else if (e.key === "Tab") {
        setOpen(false);
      }
    });
  });
}

function renderShell(): void {
  applyDocumentLang();
  openDropdownRoot = null;
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
          <div class="nav-select" data-dropdown="currency">
            <button type="button" class="nav-select-btn" id="currency-btn" aria-haspopup="listbox" aria-expanded="false" aria-label="${esc(t(lang, "currencyToggle"))}" title="${esc(t(lang, "currencyToggle"))}">
              ${icon("coin", 14)}
              <span class="nav-select-value">${currency === "ILS" ? "ILS (₪)" : "USD ($)"}</span>
              ${icon("chevron", 13)}
            </button>
            <ul class="nav-select-list" role="listbox" aria-label="${esc(t(lang, "currencyToggle"))}" hidden>
              <li role="option" id="currency-opt-ils" data-value="ILS" aria-selected="${currency === "ILS" ? "true" : "false"}">ILS (₪)</li>
              <li role="option" id="currency-opt-usd" data-value="USD" aria-selected="${currency === "USD" ? "true" : "false"}">USD ($)</li>
            </ul>
          </div>
          <div class="nav-select" data-dropdown="lang">
            <button type="button" class="nav-select-btn" id="lang-btn" aria-haspopup="listbox" aria-expanded="false" aria-label="${esc(t(lang, "langToggle"))}" title="${esc(t(lang, "langToggle"))}">
              ${icon("globe", 14)}
              <span class="nav-select-value">${lang === "he" ? "עברית" : "English"}</span>
              ${icon("chevron", 13)}
            </button>
            <ul class="nav-select-list" role="listbox" aria-label="${esc(t(lang, "langToggle"))}" hidden>
              <li role="option" id="lang-opt-he" data-value="he" aria-selected="${lang === "he" ? "true" : "false"}">עברית</li>
              <li role="option" id="lang-opt-en" data-value="en" aria-selected="${lang === "en" ? "true" : "false"}">English</li>
            </ul>
          </div>
          <button class="theme-btn" id="theme-toggle" type="button" title="${theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight")}" aria-label="${theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight")}">
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

  wireDropdown(
    document.querySelector('[data-dropdown="lang"]')!,
    (value) => {
      lang = value as Lang;
      setLang(lang);
      renderShell();
    }
  );
  wireDropdown(
    document.querySelector('[data-dropdown="currency"]')!,
    (value) => {
      currency = value as Currency;
      setCurrency(currency);
      // FX fetch is opt-in via currency selection (audit §3.1): ILS mode
      // makes zero external requests; USD fetches at most once per day.
      if (currency === "USD") void ensureFxRate();
      renderShell();
    }
  );
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
    if (openDropdownRoot) closeDropdown(openDropdownRoot);
    if (willOpen) {
      mega.hidden = false;
      productsBtn.setAttribute("aria-expanded", "true");
      fillMegaPhotos();
    }
  });

  searchBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    closeMenus();
    if (openDropdownRoot) closeDropdown(openDropdownRoot);
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

  // Mega-menu photos load on first menu open (fillMegaPhotos) and on
  // the categories page (one rep image per card) — never prefetched on
  // landing. Warming every category JSON (~4MB) on the homepage just to
  // pre-fill hover tiles burned the very first impression for zero
  // visible gain; the icon fallback covers the brief load on open.

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

interface IndexHit {
  row: IndexRow;
  haystack: string;
}

let indexHaystacks: IndexHit[] | null = null;
let searchSeqLive = 0;

function normHay(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFKC")
    .replace(/["'`׳״־–—]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Global search over index.json (~500KB, one cached fetch) instead of
 * every category file (~4.4MB on first keystroke). Matching covers
 * name/brand/category/id; the displayed hits are then lazy-enriched
 * with their full products (photos) by fetching only their categories.
 * Abortable via seq; the 220ms debounce on the input is untouched.
 */
async function ensureSearchIndex(mySeq: number): Promise<IndexHit[]> {
  if (indexHaystacks) return indexHaystacks;
  const rows = await loadIndex();
  if (mySeq !== searchSeqLive) throw new Error("aborted");
  indexHaystacks = rows.map((row) => ({
    row,
    haystack: normHay(
      `${row[4] ?? ""} ${row[3] ?? ""} ${row[0]} ${row[1]} ${categoryLabel(row[1], lang)}`
    ),
  }));
  return indexHaystacks;
}

function interimHitHtml(row: IndexRow): string {
  const name = row[4] ?? row[0];
  const brand = row[3] ?? "";
  const price =
    row[2] === null || row[2] === undefined
      ? "-"
      : formatPrice(row[2], currency, lang);
  return `
    <a class="global-hit" role="option" aria-selected="false" href="${productHash(row[1], row[0])}">
      <span class="plThumb" aria-hidden="true">${esc((brand || name).slice(0, 2).toUpperCase())}</span>
      <span class="global-hit-name">${esc(name)}<span class="global-hit-cat"> · ${esc(categoryLabel(row[1], lang))}</span></span>
      <span class="global-hit-price">${esc(price)}</span>
    </a>`;
}

function fullHitHtml(product: Product): string {
  const img = safeImageUrl(product.thumb ?? product.image);
  const name = displayName(product);
  const thumb = img
    ? `<img src="${esc(img)}" alt="${esc(name)}" loading="lazy" decoding="async" width="40" height="40">`
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
    box.innerHTML = hits.map((h) => interimHitHtml(h.row)).join("");
    // Lazy-enrich the displayed hits with their full products (photos):
    // only their categories are fetched (all cached after first use).
    const byCategory = new Map<string, IndexRow[]>();
    for (const h of hits) {
      const list = byCategory.get(h.row[1]) ?? [];
      list.push(h.row);
      byCategory.set(h.row[1], list);
    }
    const found = new Map<string, Product>();
    await Promise.all(
      [...byCategory].map(async ([category, rows]) => {
        if (mySeq !== searchSeqLive) return;
        try {
          const products = await loadCategory(category);
          for (const row of rows) {
            const p = products.find((x) => x.id === row[0]);
            if (p) found.set(row[0], p);
          }
        } catch {
          // Keep the interim rows on per-category failure.
        }
      })
    );
    if (mySeq !== searchSeqLive) return;
    box.innerHTML = hits
      .map((h) => {
        const p = found.get(h.row[0]);
        return p ? fullHitHtml(p) : interimHitHtml(h.row);
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
  if (openDropdownRoot && !target.closest(".nav-select")) {
    closeDropdown(openDropdownRoot);
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeOpenMenus();
    if (openDropdownRoot) closeDropdown(openDropdownRoot);
  }
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
