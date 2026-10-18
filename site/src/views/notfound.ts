import { t } from "../i18n";
import { buildHash, homeHash } from "../state";
import { setPageTitle } from "../titles";
import type { Lang } from "../types";
import { button } from "../ui/button";
import { card } from "../ui/card";
import { html, mount } from "../ui/html";

/** Custom 404: every dead end offers a way back to home or the builder. */
export function renderNotFound(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  setPageTitle(lang, he ? "הדף לא נמצא" : "Page Not Found");

  mount(
    container,
    html`<div class="notfound">
      ${card(
        html`<p class="notfound__code">404</p>
          <h1>${he ? "הדף שחיפשת לא נמצא" : "This page could not be found"}</h1>
          <p>${he ? "יכול להיות שהכתובת שגויה או שהדף הועבר. אפשר לחזור להתחלה או להמשיך לבנות." : "The address may be mistyped or the page may have moved. You can head back to the start or keep building."}</p>
          <div class="notfound__actions">
            ${button({ label: t(lang, "home"), variant: "primary", href: homeHash() })}
            ${button({ label: t(lang, "builderNav"), href: buildHash({}) })}
          </div>`
      )}
    </div>`
  );
}
