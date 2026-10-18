import { t } from "../i18n";
import type { Lang } from "../types";
import { html, type Html } from "./html";

/**
 * The one look for "no value": a quiet "Not listed". Every blank spec,
 * missing price and absent offer field renders through here.
 */
export function emptyValue(lang: Lang): Html {
  return html`<span class="empty-val">${t(lang, "notListed")}</span>`;
}
