import { t } from "../i18n";
import { icon } from "../icons";
import { bindSearch } from "../search";
import { categoriesHash } from "../state";
import { setPageTitle } from "../titles";
import type { Currency, Lang } from "../types";
import { html, mount } from "../ui/html";
import { fillQuickCats, quickCats } from "../ui/emptyBox";

/**
 * Custom 404: a chip-shaped "0", a way to search, a way to build, and the
 * main categories, so every dead end leads somewhere.
 */
export function renderNotFound(container: HTMLElement, lang: Lang, currency: Currency): void {
  setPageTitle(lang, t(lang, "nfPageTitle"));
  mount(
    container,
    html`<div class="nf">
      <div class="nf__intro">
        <div class="nf__code" dir="ltr" aria-hidden="true"><span>4</span><span class="nf__chip">${icon("chip", 132)}</span><span>4</span></div>
        <span class="nf__tag">${t(lang, "nfTag")}</span>
        <h1>${t(lang, "nfTitle")}</h1>
        <p class="nf__body">${t(lang, "nfBody")}</p>
        <div class="nf__search" data-search>
          <label class="search-field">
            ${icon("search", 18)}
            <input data-search-input type="search" placeholder="${t(lang, "searchLabel")}" autocomplete="off" aria-label="${t(lang, "searchLabel")}" role="combobox" aria-expanded="false" aria-autocomplete="list">
          </label>
          <div class="search-results" data-search-results role="listbox" aria-live="polite" hidden></div>
        </div>
        <div class="empty-box__actions"><a class="btn btn--primary btn--lg" href="#/build">${icon("wrench", 16)}${t(lang, "builderNav")}</a></div>
      </div>
      ${quickCats(lang, t(lang, "popularCats"), html`<a class="sec-head__link" href="${categoriesHash()}">${t(lang, "browseAllCategories")}</a>`)}
    </div>`
  );
  const search = container.querySelector<HTMLElement>("[data-search]");
  if (search) bindSearch(search, lang, currency);
  fillQuickCats(container, lang);
}
