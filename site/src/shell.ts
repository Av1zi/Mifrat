import { loadMeta } from "./api";
import { ACTIVE_VENDORS, categoryLabel, storesCount, t, updatedText } from "./i18n";
import { CATEGORY_ICONS, icon } from "./icons";
import { bindSearch, closeSearchResults } from "./search";
import {
  categoriesHash,
  categoryHash,
  cookiesHash,
  dropsHash,
  homeHash,
  parseRoute,
  privacyHash,
  qaHash,
  savedHash,
  termsHash,
  type Theme,
} from "./state";
import type { Currency, Lang } from "./types";
import { button } from "./ui/button";
import { syncCompareTray } from "./ui/compareTray";
import { html, type Html } from "./ui/html";
import { syncPickControls } from "./ui/pick";
import { safeImageUrl } from "./utils";

/** Big photo tiles in the products menu; the cooling tile spans air + liquid. */
const MEGA_TILES: Array<{ id: string; cats: string[] }> = [
  { id: "cpu", cats: ["cpu"] },
  { id: "cooler", cats: ["cpu_cooler"] },
  { id: "gpu", cats: ["gpu"] },
  { id: "motherboard", cats: ["motherboard"] },
  { id: "memory", cats: ["memory"] },
  { id: "storage", cats: ["storage"] },
  { id: "psu", cats: ["psu"] },
  { id: "case", cats: ["case"] },
];

/** Smaller categories, listed beside the tiles. */
const MEGA_SIDE = ["case_fan", "accessories", "other"];

interface ShellState {
  lang: Lang;
  currency: Currency;
  theme: Theme;
}

interface ShellHandlers {
  onLang(lang: Lang): void;
  onCurrency(currency: Currency): void;
  onTheme(theme: Theme): void;
}

function dropdown(
  id: "currency" | "lang",
  label: string,
  glyph: Html,
  current: string,
  options: Array<{ value: string; text: string }>
): Html {
  return html`<div class="select-menu" data-dropdown="${id}">
    <button type="button" class="select-menu__btn" id="${id}-btn" aria-haspopup="listbox" aria-expanded="false" aria-label="${label}" title="${label}">
      ${glyph}<span class="select-menu__value">${options.find((o) => o.value === current)?.text}</span>${icon("chevron", 13)}
    </button>
    <ul class="select-menu__list" role="listbox" aria-label="${label}" hidden>
      ${options.map((o) => html`<li role="option" data-value="${o.value}" aria-selected="${o.value === current ? "true" : "false"}">${o.text}</li>`)}
    </ul>
  </div>`;
}

function megaMarkup(lang: Lang): Html {
  return html`<div class="mega" id="mega-menu" role="menu" aria-label="${t(lang, "productsMenu")}" inert>
    <div class="bleed__inner mega__inner">
      <div class="mega__main">
        <p class="mega__head">${t(lang, "megaMainHead")}</p>
        <div class="mega__grid">
          ${MEGA_TILES.map((tile) => {
            const label = tile.id === "cooler" ? t(lang, "megaCooling") : categoryLabel(tile.id, lang);
            return html`<a class="mtile" role="menuitem" href="${categoryHash(tile.cats[0])}">
              <span class="mtile__img" data-cover-cat="${tile.cats[0]}">${icon(CATEGORY_ICONS[tile.cats[0]] ?? "grid", 30)}</span>
              <span class="mtile__name">${label}</span>
              <span class="mtile__meta" data-count-cats="${tile.cats.join(",")}"${""}></span>
            </a>`;
          })}
        </div>
      </div>
      <div class="mega__side">
        <p class="mega__head">${t(lang, "megaMoreHead")}</p>
        ${MEGA_SIDE.map(
          (id) => html`<a class="mega__link" role="menuitem" href="${categoryHash(id)}"><span>${categoryLabel(id, lang)}</span><span class="mega__count" data-count-cats="${id}" data-count-bare="1"></span></a>`
        )}
        <a class="mega__all" role="menuitem" href="${categoriesHash()}">${t(lang, "browseAllCategories")}${icon("forward", 14)}</a>
      </div>
    </div>
  </div>
  <button type="button" class="mega-scrim" tabindex="-1" aria-label="${t(lang, "megaClose")}" data-role="mega-scrim"></button>`;
}

function headerMarkup(state: ShellState): Html {
  const { lang, currency, theme } = state;
  const route = parseRoute();
  const isBuild = route.view === "build";
  const isProducts = route.view === "categories" || route.view === "category" || route.view === "product";
  const themeLabel = theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight");
  const navLink = (key: string, href: string, glyph: Html, label: string, on: boolean): Html =>
    html`<a class="nav-link${on ? " is-active" : ""}" data-nav="${key}" href="${href}"${on ? html` aria-current="page"` : ""}>${glyph}<span>${label}</span></a>`;
  return html`<header class="site-header">
    <div class="hdr-top">
      <div class="bleed__inner hdr-top__inner">
        <a class="brand" href="${homeHash()}">
          <span class="brand__mark">${icon("chip", 18)}</span>
          <span class="brand__text"><span class="brand__name">${t("he", "appName")}</span><span class="brand__alt">MIFRAT</span></span>
        </a>
        <div class="site-search" data-search>
          <label class="search-field search-field--dark">
            ${icon("search", 16)}
            <input data-search-input type="search" placeholder="${t(lang, "searchLabel")}" autocomplete="off" aria-label="${t(lang, "searchLabel")}" role="combobox" aria-expanded="false" aria-autocomplete="list">
            <kbd class="kbd" aria-hidden="true">/</kbd>
          </label>
          <div class="search-results" data-search-results role="listbox" aria-live="polite" hidden></div>
        </div>
        <div class="site-controls">
          ${button({
            label: t(lang, "savedNav"),
            icon: html`${icon("heart", 17)}<span class="saved-count" data-saved-count hidden>0</span>`,
            iconOnly: true,
            href: savedHash(),
            className: `hdr-ctl saved-link${route.view === "saved" ? " is-active" : ""}`,
            data: { nav: "saved" },
            title: t(lang, "savedNav"),
          })}
          ${dropdown("currency", t(lang, "currencyToggle"), icon("coin", 15), currency, [
            { value: "ILS", text: "₪ ILS" },
            { value: "USD", text: "$ USD" },
          ])}
          ${dropdown("lang", t(lang, "langToggle"), icon("globe", 15), lang, [
            { value: "he", text: "עברית" },
            { value: "en", text: "English" },
          ])}
          <button class="btn btn--icon hdr-ctl" id="theme-toggle" type="button" title="${themeLabel}" aria-label="${themeLabel}">
            ${icon(theme === "light" ? "moon" : "sun", 17)}
          </button>
        </div>
      </div>
    </div>
    <nav class="hdr-nav" aria-label="${t(lang, "navMain")}">
      <div class="bleed__inner hdr-nav__inner">
        ${navLink("build", "#/build", icon("wrench", 16), t(lang, "builderNav"), isBuild)}
        <button type="button" class="nav-link${isProducts ? " is-active" : ""}" data-nav="products" id="products-btn" aria-expanded="false" aria-haspopup="true" aria-controls="mega-menu">
          ${icon("chip", 16)}<span>${t(lang, "productsMenu")}</span><span class="nav-link__chev">${icon("chevron", 13)}</span>
        </button>
        ${navLink("drops", dropsHash(), icon("trend-down", 16), t(lang, "dropsNav"), route.view === "drops")}
        ${navLink("compare", "#/compare", icon("compare", 16), t(lang, "compareTitle"), route.view === "compare")}
        <span class="hdr-nav__status" data-updated hidden></span>
      </div>
    </nav>
    ${megaMarkup(lang)}
  </header>`;
}

function footerMarkup(lang: Lang): Html {
  return html`<footer class="site-footer">
    <div class="bleed__inner site-footer__inner">
      <div class="site-footer__brand">
        <a class="brand" href="${homeHash()}"><span class="brand__mark">${icon("chip", 16)}</span><span class="brand__name">${t(lang, "appName")}</span></a>
        <p>${t(lang, "footerDesc")}</p>
      </div>
      <div class="site-footer__col">
        <h3>${t(lang, "footerProductsHead")}</h3>
        <a href="${categoriesHash()}">${t(lang, "browseAllCategories")}</a>
        <a href="${categoryHash("cpu")}">${categoryLabel("cpu", lang)}</a>
        <a href="${categoryHash("gpu")}">${categoryLabel("gpu", lang)}</a>
        <a href="${categoryHash("motherboard")}">${categoryLabel("motherboard", lang)}</a>
        <a href="${dropsHash()}">${t(lang, "dropsNav")}</a>
      </div>
      <div class="site-footer__col">
        <h3>${t(lang, "footerBuildHead")}</h3>
        <a href="#/build">${t(lang, "builderNav")}</a>
        <a href="${savedHash()}">${t(lang, "savedNav")}</a>
        <a href="#/compare">${t(lang, "compareTitle")}</a>
        <a href="${qaHash()}">${t(lang, "qaTitle")}</a>
      </div>
      <div class="site-footer__col">
        <h3>${t(lang, "footerLegalHead")}</h3>
        <a href="${privacyHash()}">${t(lang, "privacyTitle")}</a>
        <a href="${termsHash()}">${t(lang, "termsTitle")}</a>
        <a href="${cookiesHash()}">${t(lang, "cookiesTitle")}</a>
        <a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">${t(lang, "sourceLinkLabel")}</a>
      </div>
    </div>
    <div class="bleed__inner"><p class="site-footer__disclaimer">${t(lang, "disclaimer")}</p></div>
  </footer>`;
}

/** Header + empty <main> + footer. Returns after wiring the header controls. */
export function renderShell(app: HTMLElement, state: ShellState, handlers: ShellHandlers): void {
  app.innerHTML = html`<a class="skip-link" href="#main-content">${t(state.lang, "skipToContent")}</a>${headerMarkup(state)}<main id="main-content" tabindex="-1"></main>${footerMarkup(state.lang)}<aside class="compare-tray" id="compare-tray" aria-label="${t(state.lang, "compareTitle")}" hidden></aside>`.value;
  openDropdown = null;

  fillMenuData(app, state.lang);

  wireDropdown(app.querySelector('[data-dropdown="lang"]')!, (value) => handlers.onLang(value as Lang));
  wireDropdown(app.querySelector('[data-dropdown="currency"]')!, (value) => handlers.onCurrency(value as Currency));
  document.getElementById("theme-toggle")!.addEventListener("click", () => {
    handlers.onTheme(state.theme === "light" ? "dark" : "light");
  });

  const productsBtn = document.getElementById("products-btn")!;
  productsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = !document.getElementById("mega-menu")?.classList.contains("is-open");
    closeMenus();
    if (willOpen) setMegaOpen(true);
  });
  app.querySelector('[data-role="mega-scrim"]')?.addEventListener("click", () => setMegaOpen(false));
  // Picking a category closes the menu even when the hash does not change.
  document.getElementById("mega-menu")?.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("a")) setMegaOpen(false);
  });

  const searchRoot = app.querySelector<HTMLElement>("[data-search]");
  if (searchRoot) bindSearch(searchRoot, state.lang, state.currency);
  syncPickControls();
}

/** Re-marks the active nav item after a hash change (header is not re-rendered). */
export function syncNav(): void {
  const route = parseRoute();
  const flags: Record<string, boolean> = {
    build: route.view === "build",
    products: route.view === "categories" || route.view === "category" || route.view === "product",
    drops: route.view === "drops",
    compare: route.view === "compare",
    saved: route.view === "saved",
  };
  document.querySelectorAll<HTMLElement>("[data-nav]").forEach((el) => {
    const on = flags[el.dataset.nav ?? ""] ?? false;
    el.classList.toggle("is-active", on);
    if (on && el.tagName === "A") el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  syncCompareTray();
}

// ---- menus ---------------------------------------------------------------

/**
 * Fills the data-driven bits of the shell from meta.json (already fetched by
 * the page, so no extra request): each menu tile's cover photo (the category
 * icon stays when there is none or it fails to load), the product counts,
 * and the "prices updated" line in the nav bar.
 */
function fillMenuData(root: ParentNode, lang: Lang): void {
  void loadMeta()
    .then((meta) => {
      const byId = new Map(meta.categories.map((c) => [c.id, c]));
      const locale = lang === "he" ? "he-IL" : "en-US";
      root.querySelectorAll<HTMLElement>("[data-cover-cat]").forEach((slot) => {
        const src = safeImageUrl(byId.get(slot.dataset.coverCat ?? "")?.cover);
        if (!src || !slot.isConnected) return;
        const img = document.createElement("img");
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        img.addEventListener("error", () => img.remove(), { once: true });
        img.addEventListener("load", () => slot.querySelector(".ic")?.remove(), { once: true });
        img.src = src;
        slot.append(img);
      });
      root.querySelectorAll<HTMLElement>("[data-count-cats]").forEach((el) => {
        const n = (el.dataset.countCats ?? "").split(",").reduce((sum, id) => sum + (byId.get(id)?.count ?? 0), 0);
        if (n === 0) return;
        const num = n.toLocaleString(locale);
        const prefix = el.dataset.countPrefix;
        el.textContent = el.dataset.countBare ? num : prefix ? `${prefix} · ${num}` : `${num} ${t(lang, "homeTileProducts")}`;
      });
      const status = root.querySelector<HTMLElement>("[data-updated]");
      const text = updatedText(lang, meta.generated_at);
      if (status && text) {
        const dot = document.createElement("span");
        dot.className = "live-dot";
        dot.setAttribute("aria-hidden", "true");
        status.replaceChildren(dot, `${text} · ${storesCount(lang, ACTIVE_VENDORS.length)}`);
        status.hidden = false;
      }
    })
    .catch(() => {});
}

function setMegaOpen(open: boolean): void {
  const mega = document.getElementById("mega-menu");
  if (!mega) return;
  mega.classList.toggle("is-open", open);
  mega.toggleAttribute("inert", !open);
  document.querySelector(".mega-scrim")?.classList.toggle("is-open", open);
  document.getElementById("products-btn")?.setAttribute("aria-expanded", open ? "true" : "false");
}

let openDropdown: HTMLElement | null = null;

function closeDropdown(root: HTMLElement): void {
  const list = root.querySelector<HTMLElement>(".select-menu__list");
  if (list) list.hidden = true;
  root.querySelector(".select-menu__btn")?.setAttribute("aria-expanded", "false");
  root.querySelectorAll(".is-active").forEach((el) => el.classList.remove("is-active"));
  if (openDropdown === root) openDropdown = null;
}

/** Closes the mega menu, search results and any open dropdown. */
export function closeMenus(except?: EventTarget | null): void {
  setMegaOpen(false);
  closeSearchResults(except);
  if (openDropdown) closeDropdown(openDropdown);
}

/**
 * Listbox dropdown (currency / language). The whole button is the hitbox;
 * arrow keys move, Enter/Space picks, Escape closes.
 */
function wireDropdown(root: HTMLElement, onPick: (value: string) => void): void {
  const btn = root.querySelector<HTMLButtonElement>(".select-menu__btn")!;
  const list = root.querySelector<HTMLElement>(".select-menu__list")!;
  const options = Array.from(list.querySelectorAll<HTMLElement>('[role="option"]'));
  let hl = Math.max(0, options.findIndex((o) => o.getAttribute("aria-selected") === "true"));

  const paint = (): void => options.forEach((o, i) => o.classList.toggle("is-active", i === hl));
  const isOpen = (): boolean => !list.hidden;
  const setOpen = (open: boolean): void => {
    if (open && openDropdown && openDropdown !== root) closeDropdown(openDropdown);
    openDropdown = open ? root : openDropdown === root ? null : openDropdown;
    list.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) paint();
  };
  const focusOption = (i: number): void => {
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
    closeSearchResults();
    setOpen(!isOpen());
  });
  btn.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!isOpen()) {
        setOpen(true);
        focusOption(hl);
      } else {
        focusOption(hl + (e.key === "ArrowDown" ? 1 : -1));
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
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        focusOption(i + (e.key === "ArrowDown" ? 1 : -1));
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

/** Registered once: the header is re-created, so these query the live DOM. */
export function bindGlobalMenuClose(): void {
  document.addEventListener("click", (e) => {
    const target = e.target as HTMLElement;
    const inHeader = target.closest(".site-header");
    if (!inHeader) closeMenus(target);
    else if (!target.closest("[data-search]")) closeSearchResults();
    if (openDropdown && !target.closest(".select-menu")) closeDropdown(openDropdown);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const wasOpen = document.getElementById("mega-menu")?.classList.contains("is-open");
      closeMenus();
      if (wasOpen) document.getElementById("products-btn")?.focus();
      return;
    }
    // "/" jumps to the header search, unless the user is already typing.
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable]")) return;
      const input = document.querySelector<HTMLInputElement>(".site-header [data-search-input]");
      if (input && input.offsetParent !== null) {
        e.preventDefault();
        input.focus();
      }
    }
  });
}
