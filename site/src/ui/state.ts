import { t } from "../i18n";
import type { Lang } from "../types";
import { button } from "./button";
import { html, type Html } from "./html";

export function loadingState(lang: Lang): Html {
  return html`<div class="state" role="status"><span class="state__spinner" aria-hidden="true"></span>${t(lang, "loading")}</div>`;
}

export function emptyState(message: string, action?: Html): Html {
  return html`<div class="state"><p>${message}</p>${action ?? ""}</div>`;
}

/**
 * Failure panel for data views: friendly message, a retry button wired by
 * the delegated `[data-action="reload"]` handler in main.ts, and the
 * technical reason in a details element for bug reports.
 */
export function errorState(lang: Lang, err: unknown): Html {
  const detail =
    err instanceof Error && err.message
      ? html`<details class="state__details"><summary>${t(lang, "details")}</summary><code>${err.message}</code></details>`
      : "";
  return html`<div class="state state--error"><p>${t(lang, "loadError")}</p>${button({ label: t(lang, "retry"), data: { action: "reload" } })}${detail}</div>`;
}
