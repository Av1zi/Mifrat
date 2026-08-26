import "./style.css";
import { ensureFxRate } from "./format";
import { t } from "./i18n";
import { getCurrency, getLang, homeHash, parseRoute, setCurrency, setLang } from "./state";
import type { Currency, Lang } from "./types";
import { closeDetail } from "./views/detail";
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
  app.innerHTML = `
    <header class="site-header">
      <a class="brand" href="${homeHash()}">
        ${t(lang, "appName")} <small>${lang === "he" ? "Mifrat" : "מפרט"}</small>
      </a>
      <div class="header-spacer"></div>
      <button class="icon-toggle" id="currency-toggle" type="button" title="${t(lang, "currencyToggle")}">
        ${currency === "ILS" ? "₪ → $" : "$ → ₪"}
      </button>
      <button class="icon-toggle" id="lang-toggle" type="button">${t(lang, "langToggle")}</button>
    </header>
    <main id="main-content"></main>
    <footer class="site-footer">
      <p>${t(lang, "disclaimer")}</p>
      <a href="https://github.com/Av1zi/Mifrat" target="_blank" rel="noopener noreferrer">${t(lang, "sourceLinkLabel")}</a>
    </footer>
  `;

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
  } else {
    void renderCategory(main, lang, currency, route.category, route.params);
  }
}

window.addEventListener("hashchange", renderRoute);

void ensureFxRate();
renderShell();
