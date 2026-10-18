import { categoryLabel, t } from "./i18n";
import { CATEGORY_ICONS, icon } from "./icons";
import { bindSearch, closeSearchResults } from "./search";
import {
  categoriesHash,
  categoryHash,
  cookiesHash,
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

const MEGA_GROUPS: Array<{ head: "componentHeading" | "coolingHeading" | "accessoriesHeading"; ids: string[] }> = [
  { head: "componentHeading", ids: ["cpu", "motherboard", "memory", "gpu", "storage", "psu", "case"] },
  { head: "coolingHeading", ids: ["cooler_air", "aio", "case_fan", "cooling_other"] },
  { head: "accessoriesHeading", ids: ["accessories", "other"] },
];

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

function headerMarkup(state: ShellState): Html {
  const { lang, currency, theme } = state;
  const route = parseRoute();
  const isBuild = route.view === "build";
  const isProducts = route.view === "categories" || route.view === "category" || route.view === "product";
  const themeLabel = theme === "light" ? t(lang, "themeDark") : t(lang, "themeLight");
  const other = lang === "he" ? "en" : "he";
  return html`<header class="site-header">
    <div class="site-header__inner">
      <a class="brand" href="${homeHash()}">
        <span class="brand__mark">${icon("chip", 18)}</span>
        <span class="brand__name">${t(lang, "appName")}</span>
        <small class="brand__alt">${t(other, "appName")}</small>
      </a>
      <nav class="site-nav" aria-label="${t(lang, "navMain")}">
        <a class="nav-link${isBuild ? " is-active" : ""}" data-nav="build" href="#/build"${isBuild ? html` aria-current="page"` : ""}>${icon("wrench", 16)}<span>${t(lang, "builderNav")}</span></a>
        <button type="button" class="nav-link${isProducts ? " is-active" : ""}" data-nav="products" id="products-btn" aria-expanded="false" aria-haspopup="true" aria-controls="mega-menu">
          ${icon("chip", 16)}<span>${t(lang, "productsMenu")}</span>${icon("chevron", 13)}
        </button>
      </nav>
      <div class="site-search" data-search>
        <label class="search-field">
          ${icon("search", 16)}
          <input data-search-input type="search" placeholder="${t(lang, "searchLabel")}" autocomplete="off" aria-label="${t(lang, "searchLabel")}" role="combobox" aria-expanded="false" aria-autocomplete="list">
        </label>
        <div class="search-results" data-search-results role="listbox" aria-live="polite" hidden></div>
      </div>
      <div class="site-controls">
        ${button({
          label: t(lang, "savedTitle"),
          icon: html`${icon("heart", 17)}<span class="saved-count" data-saved-count hidden>0</span>`,
          iconOnly: true,
          href: savedHash(),
          className: `saved-link${route.view === "saved" ? " is-active" : ""}`,
          data: { nav: "saved" },
          title: t(lang, "savedTitle"),
        })}
        ${dropdown("currency", t(lang, "currencyToggle"), icon("coin", 15), currency, [
          { value: "ILS", text: "ILS (₪)" },
          { value: "USD", text: "USD ($)" },
        ])}
        ${dropdown("lang", t(lang, "langToggle"), icon("globe", 15), lang, [
          { value: "he", text: "עברית" },
          { value: "en", text: "English" },
        ])}
        <button class="btn btn--ghost btn--icon" id="theme-toggle" type="button" title="${themeLabel}" aria-label="${themeLabel}">
          ${icon(theme === "light" ? "moon" : "sun", 17)}
        </button>
      </div>
    </div>
    <div class="mega" id="mega-menu" hidden role="menu" aria-label="${t(lang, "productsMenu")}">
      <div class="mega__inner">
        <a class="mega__all" href="${categoriesHash()}">${t(lang, "browseAllCategories")}${icon("forward", 14)}</a>
        <div class="mega__groups">
          ${MEGA_GROUPS.map(
            (group) => html`<div class="mega__group">
              <h3>${t(lang, group.head)}</h3>
              ${group.ids.map(
                (id) => html`<a class="mega__link" href="${categoryHash(id)}">${icon(CATEGORY_ICONS[id] ?? "grid", 18)}<span>${categoryLabel(id, lang)}</span></a>`
              )}
            </div>`
          )}
        </div>
      </div>
    </div>
  </header>`;
}

function footerMarkup(lang: Lang): Html {
  return html`<footer class="site-footer">
    <div class="site-footer__inner">
      <div class="site-footer__brand">
        <a class="brand" href="${homeHash()}"><span class="brand__mark">${icon("chip", 18)}</span><span class="brand__name">${t(lang, "appName")}</span></a>
        <p>${t(lang, "footerDesc")}</p>
      </div>
      <div class="site-footer__col">
        <h3>${t(lang, "footerProductsHead")}</h3>
        <a href="${categoriesHash()}">${t(lang, "browseAllCategories")}</a>
        <a href="${categoryHash("cpu")}">${categoryLabel("cpu", lang)}</a>
        <a href="${categoryHash("gpu")}">${categoryLabel("gpu", lang)}</a>
        <a href="${categoryHash("motherboard")}">${categoryLabel("motherboard", lang)}</a>
      </div>
      <div class="site-footer__col">
        <h3>${t(lang, "footerBuildHead")}</h3>
        <a href="#/build">${t(lang, "builderNav")}</a>
        <a href="${savedHash()}">${t(lang, "savedTitle")}</a>
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
    <p class="site-footer__disclaimer">${t(lang, "disclaimer")}</p>
  </footer>`;
}

/** Header + empty <main> + footer. Returns after wiring the header controls. */
export function renderShell(app: HTMLElement, state: ShellState, handlers: ShellHandlers): void {
  app.innerHTML = html`${headerMarkup(state)}<main id="main-content"></main>${footerMarkup(state.lang)}<aside class="compare-tray" id="compare-tray" aria-label="${t(state.lang, "compareTitle")}" hidden></aside>`.value;
  openDropdown = null;

  wireDropdown(app.querySelector('[data-dropdown="lang"]')!, (value) => handlers.onLang(value as Lang));
  wireDropdown(app.querySelector('[data-dropdown="currency"]')!, (value) => handlers.onCurrency(value as Currency));
  document.getElementById("theme-toggle")!.addEventListener("click", () => {
    handlers.onTheme(state.theme === "light" ? "dark" : "light");
  });

  const mega = document.getElementById("mega-menu")!;
  const productsBtn = document.getElementById("products-btn")!;
  productsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = mega.hidden;
    closeMenus();
    if (willOpen) {
      mega.hidden = false;
      productsBtn.setAttribute("aria-expanded", "true");
    }
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
    saved: route.view === "saved",
  };
  document.querySelectorAll<HTMLElement>("[data-nav]").forEach((el) => {
    const on = flags[el.dataset.nav ?? ""] ?? false;
    el.classList.toggle("is-active", on);
    if (on) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  syncCompareTray();
}

// ---- menus ---------------------------------------------------------------

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
  const mega = document.getElementById("mega-menu");
  if (mega) mega.hidden = true;
  document.getElementById("products-btn")?.setAttribute("aria-expanded", "false");
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
    if (e.key === "Escape") closeMenus();
  });
}
