import "./style.css";
import { ensureFxRate } from "./format";
import { t } from "./i18n";
import { getCurrency, getLang, homeHash, parseRoute, setCurrency, setLang } from "./state";
import type { Currency, Lang } from "./types";
import { closeDetail } from "./views/detail";
import { renderBuilder } from "./views/builder";
import { renderCategory } from "./views/category";
import { renderHome } from "./views/home";

let lang: Lang = getLang();
let currency: Currency = getCurrency();
const app = document.getElementById("app")!;

function applyDocumentLang(): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
}

function renderShell(): void {
  applyDocumentLang();
  const isBuild = location.hash.startsWith("#/build");
  const isHome = !location.hash || location.hash === "#/" || location.hash === "#";
  app.innerHTML = `
    <header class="site-header">
      <a class="brand" href="${homeHash()}">
        ${t(lang, "appName")}
        <small>${lang === "he" ? "Mifrat" : "מפרט"}</small>
      </a>
      <nav style="display:flex; gap:8px; align-items:center; z-index:1">
        <a class="nav-build ${isBuild ? "active" : ""}" href="#/build">🔧 ${t(lang, "builderNav")}</a>
        <a class="nav-link ${isHome ? "active" : ""}" href="${homeHash()}" style="${isHome ? "" : "opacity:0.9"}">${t(lang, "home")}</a>
      </nav>
      <div class="header-spacer"></div>
      <button class="icon-toggle" id="currency-toggle" type="button" title="${t(lang, "currencyToggle")}">
        ${currency === "ILS" ? "₪ → $" : "$ → ₪"}
      </button>
      <button class="icon-toggle" id="lang-toggle" type="button">${t(lang, "langToggle")}</button>
    </header>
    <div style="background: var(--bg-panel); border-bottom:1px solid var(--border);">
      <div style="max-width:1320px; margin:0 auto; padding:8px 20px; display:flex; gap:8px; overflow:auto; scrollbar-width:none;">
        <span style="font-size:0.72rem; font-weight:800; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.07em; white-space:nowrap; padding:6px 0;">${lang==="he" ? "קטגוריות" : "Browse"}:</span>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/cpu">CPU</a>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/motherboard">${lang==="he" ? "לוח אם" : "Motherboard"}</a>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/memory">${lang==="he" ? "זיכרון" : "Memory"}</a>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/gpu">${lang==="he" ? "כרטיס מסך" : "GPU"}</a>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/storage">${lang==="he" ? "אחסון" : "Storage"}</a>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/psu">PSU</a>
        <a class="nav-link" style="background: var(--bg); border-color: var(--border); color: var(--text); padding:5px 12px; font-size:0.78rem;" href="#/c/case">${lang==="he" ? "מארז" : "Case"}</a>
      </div>
    </div>
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
renderShell();