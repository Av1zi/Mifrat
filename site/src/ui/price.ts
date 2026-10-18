import { formatPrice } from "../format";
import type { Currency, Lang } from "../types";
import { emptyValue } from "./empty";
import { html, type Html } from "./html";

/** Zero/absent scraped prices mean "unknown", never "free". */
export function positivePrice(price: number | null | undefined): number | null {
  return typeof price === "number" && Number.isFinite(price) && price > 0 ? price : null;
}

export function priceCell(
  price: number | null | undefined,
  currency: Currency,
  lang: Lang,
  size: "md" | "lg" = "md"
): Html {
  const value = positivePrice(price);
  if (value === null) return emptyValue(lang);
  return html`<span class="price price--${size}">${formatPrice(value, currency, lang)}</span>`;
}
