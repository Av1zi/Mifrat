import "./style.css";
import { ensureFxRate } from "./format";
import { t } from "./i18n";
import { applyStoredTheme, getCurrency, getLang, getTheme, homeHash, parseRoute, setCurrency, setLang, setTheme, type Theme } from "./state";
import type { Currency, Lang } from "./types";
import { closeDetail } from "./views/detail";
import { renderBuilder } from "./views/builder";
import { renderCategory } from "./views/category";
import { renderHome } from "./views/home";

let lang: Lang = getLang();
let currency: Currency = getCurrency();
let theme: Theme = applyStoredTheme();
const app = document.getElementById("app")!;

function applyDocumentLang(): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
}

const CATS: Array<{ id: string; he: string; en: string }> = [
  { id: "cpu", he: "מעבדים", en: "CPU" },
  { id: "motherboard", he: "לוחות אם", en: "Motherboard" },
  { id: "memory", he: "זיכרון", en: "Memory" },
  { id: "gpu", he: "כרטיסי מסך", en: "GPU" },
  { id: "storage", he: "אחסון", en: "Storage" },
  { id: "psu", he: "ספקי כוח", en: "PSU" },
  { id: "case", he: "מארזים", en: "Case" },
];

function themeIcon(name: Theme): string {
  return name === "dark" ? "◐" : "○";
}

function renderShell(): void {
  applyDocumentLang();
  document.documentElement.dataset.theme = theme;
  const isBuild = location.hash.startsWith("#/build");
  const isHome = !location.hash || location.hash === "#/" || location.hash === "#";
  const catLinks = CATS.map(
    (c) =>
      `<a class="nav-link" href="#/c/${c.id}">${lang === "he" ? c.he : c.en}</a>`
  ).join("");
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
          <div class="theme-switch" role="group" aria-label="${t(lang, "themeDark")}">
            <button type="button" data-theme-btn="light" aria-pressed="${theme === "light"}">${themeIcon("light")} ${lang === "he" ? "בהיר" : "Light"}</button>
            <button type="button" data-theme-btn="dark" aria-pressed="${theme === "dark"}">${themeIcon("dark")} ${lang === "he" ? "כהה" : "Dark"}</button>
          </div>
          <button class="icon-toggle" id="currency-toggle" type="button" title="${t(lang, "currencyToggle")}">
            ${currency === "ILS" ? "₪ → $" : "$ → ₪"}
          </button>
          <button class="icon-toggle" id="lang-toggle" type="button">${t(lang, "langToggle")}</button>
        </div>
      </div>
      <nav class="header-nav" aria-label="main">
        <div class="header-nav-inner">
          <a class="nav-build ${isBuild ? "active" : ""}" href="#/build">🔧 ${t(lang, "builderNav")}</a>
          <a class="nav-link ${isHome ? "active" : ""}" href="${homeHash()}">${t(lang, "home")}</a>
          <span class="nav-sep">${lang === "he" ? "קטגוריות" : "Parts"}</span>
          ${catLinks}
        </div>
      </nav>
    </header>
    <main id="main-content"></main>
    <footer class="site-footer">
      <p>${t(lang, "disclaimer")}</p>
      <a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">${t(lang, "sourceLinkLabel")}</a>
    </footer>`;
  document.getElementById("lang-toggle")!.addEventListener("click", () => {
    lang = lang === "he" ? "en" : "he";
    setLang(lang);
    renderShell();
  });
  document.getElementById("currency-toggle")!.addEventListener("click", () => {
    currency = currency === "ILS" ? "USD" : "ILS";
    setCurrency(currency);
    renderShell();
  });
  app.querySelectorAll("[data-theme-btn]").forEach((btn) => {
    btn.addEventListener("click", () => {
      theme = (btn as HTMLElement).dataset.themeBtn as Theme;
      setTheme(theme);
      renderShell();
    });
  });
  renderRoute();
}

function renderRoute(): void {
  const main = document.getElementById("main-content")!;
  const route = parseRoute();
  if (route.view === "home") {
    closeDetail();
    void renderHome(main, lang, currency);
  } else if (route.view === "build") {
    void renderBuilder(main, lang, currency, route.shared);
  } else {
    void renderCategory(main, lang, currency, route.category, route.params);
  }
}

window.addEventListener("hashchange", renderRoute);
void ensureFxRate();
// Keep theme in sync if OS preference changes and user never picked one.
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
  if (!localStorage.getItem("mifrat:theme")) {
    theme = getTheme();
    renderShell();
  }
});
renderShell();
