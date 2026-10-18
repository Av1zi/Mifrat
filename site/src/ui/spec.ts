import { formatSpecValue } from "../specs";
import type { Lang, SpecValue } from "../types";
import { emptyValue } from "./empty";
import { html, type Html } from "./html";

/** One spec value as a cell: its text, or the shared empty look. */
export function specCell(value: SpecValue | undefined, lang: Lang): Html {
  const text = formatSpecValue(value, lang);
  return text ? html`<bdi class="spec-val">${text}</bdi>` : emptyValue(lang);
}
