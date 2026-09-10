import { t } from "../i18n";
import { buildHash, homeHash } from "../state";
import { setPageTitle } from "../titles";
import type { Lang } from "../types";
import { esc } from "../utils";

/**
 * Custom 404 page for unknown routes, unknown categories and
 * missing products. Friendly, centered, bilingual, no dead ends:
 * every path offers a way back to the home page or the builder.
 */
export function renderNotFound(container: HTMLElement, lang: Lang): void {
  const he = lang === "he";
  setPageTitle(lang, he ? "הדף לא נמצא" : "Page Not Found");

  container.innerHTML = `
    <div class="notfound-wrap">
      <div class="notfound-card">
        <p class="notfound-code">404</p>
        <h1>${he ? "הדף שחיפשת לא נמצא" : "This page could not be found"}</h1>
        <p>${he ? "יכול להיות שהכתובת שגויה או שהדף הועבר. אפשר לחזור להתחלה או להמשיך לבנות." : "The address may be mistyped or the page may have moved. You can head back to the start or keep building."}</p>
        <div class="notfound-actions">
          <a class="btn-primary btn-icon" href="${homeHash()}"><span>${esc(t(lang, "home"))}</span></a>
          <a class="btn-ghost" href="${buildHash({})}"><span>${esc(t(lang, "builderNav"))}</span></a>
        </div>
      </div>
    </div>`;
}
