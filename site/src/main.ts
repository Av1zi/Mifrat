import "./styles/index.css";
import "@fontsource/ibm-plex-sans-hebrew/400.css";
import "@fontsource/ibm-plex-sans-hebrew/500.css";
import "@fontsource/ibm-plex-sans-hebrew/600.css";
import "@fontsource/ibm-plex-sans-hebrew/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import { ensureFxRate } from "./format";
import { categoryLabel, t } from "./i18n";
import { bindGlobalMenuClose, closeMenus, renderShell, syncNav } from "./shell";
import {
  applyStoredTheme,
  getCurrency,
  getLang,
  parseRoute,
  setCurrency,
  setLang,
  setTheme,
  type Theme,
} from "./state";
import { setPageTitle } from "./titles";
import type { Currency, Lang } from "./types";
import { mount } from "./ui/html";
import { bindPickControls } from "./ui/pick";
import { errorState } from "./ui/state";
import { renderBuilder, renderListRoute } from "./views/builder";
import { renderCategories } from "./views/categories";
import { renderCompare } from "./views/compare";
import { renderCategory } from "./views/category";
import { renderCookies } from "./views/cookies";
import { renderDrops } from "./views/drops";
import { renderHome } from "./views/home";
import { renderNotFound } from "./views/notfound";
import { renderPrivacy } from "./views/privacy";
import { renderProduct } from "./views/product";
import { renderQa } from "./views/qa";
import { renderSaved } from "./views/saved";
import { renderTerms } from "./views/terms";

let lang: Lang = getLang();
let currency: Currency = getCurrency();
let theme: Theme = applyStoredTheme();
const app = document.getElementById("app")!;

function applyDocumentLang(): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
  document
    .querySelector('meta[name="description"]')
    ?.setAttribute("content", t(lang, "metaDescription"));
}

function renderApp(): void {
  applyDocumentLang();
  document.documentElement.dataset.theme = theme;
  renderShell(
    app,
    { lang, currency, theme },
    {
      onLang(next) {
        lang = next;
        setLang(lang);
        renderApp();
      },
      onCurrency(next) {
        currency = next;
        setCurrency(currency);
        // The FX fetch is opt-in: ILS mode makes zero external requests.
        if (currency === "USD") void ensureFxRate();
        renderApp();
      },
      onTheme(next) {
        theme = next;
        setTheme(theme);
        renderApp();
      },
    }
  );
  renderRoute();
}

function routeError(main: HTMLElement, err: unknown): void {
  console.error("[route]", err);
  mount(main, errorState(lang, err));
}

function renderRoute(): void {
  const main = document.getElementById("main-content")!;
  const route = parseRoute();
  syncNav();
  const guard = (task: Promise<void> | void): void => {
    if (task) task.catch((err) => routeError(main, err));
  };
  try {
    switch (route.view) {
      case "privacy":
        renderPrivacy(main, lang);
        break;
      case "terms":
        renderTerms(main, lang);
        break;
      case "cookies":
        renderCookies(main, lang);
        break;
      case "notfound":
        renderNotFound(main, lang);
        break;
      case "qa":
        setPageTitle(lang, t(lang, "qaTitle"));
        guard(renderQa(main, lang, currency));
        break;
      case "compare":
        guard(renderCompare(main, lang, currency, route.ids));
        break;
      case "saved":
        guard(renderSaved(main, lang, currency));
        break;
      case "drops":
        guard(renderDrops(main, lang, currency));
        break;
      case "categories":
        setPageTitle(lang, t(lang, "allCategoriesTitle"), t(lang, "metaCategoriesDesc"));
        guard(renderCategories(main, lang, currency));
        break;
      case "home":
        guard(renderHome(main, lang, currency));
        break;
      case "build": {
        const shared = route.listId !== null || route.shared !== null;
        setPageTitle(lang, shared ? t(lang, "sharedBuildTitle") : t(lang, "builderPageTitle"), t(lang, "metaBuilderDesc"));
        guard(
          route.listId
            ? renderListRoute(main, lang, currency, route.listId)
            : renderBuilder(main, lang, currency, route.shared, null)
        );
        break;
      }
      case "product":
        setPageTitle(lang, t(lang, "productPageTitle"));
        guard(renderProduct(main, lang, currency, route.category, route.productId));
        break;
      case "category":
        setPageTitle(lang, categoryLabel(route.category, lang));
        guard(renderCategory(main, lang, currency, route.category, route.params));
        break;
    }
  } catch (err) {
    routeError(main, err);
  }
}

bindGlobalMenuClose();
bindPickControls();
document.addEventListener("click", (e) => {
  if ((e.target as HTMLElement).closest('[data-action="reload"]')) location.reload();
});
window.addEventListener("hashchange", () => {
  closeMenus();
  renderRoute();
  // A new page starts at the top (in-page anchors are handled by the views).
  window.scrollTo({ top: 0 });
});

// FX is opt-in: only USD display needs the frankfurter rate, so ILS-default
// visitors make zero third-party requests on load.
if (currency === "USD") void ensureFxRate();
renderApp();
