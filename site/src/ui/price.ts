import { formatPrice } from "../format";
import { t } from "../i18n";
import type { Currency, Lang, Region } from "../types";
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

export function stalePriceTag(stale: boolean | undefined, lang: Lang): Html {
  return stale ? html`<span class="stale-tag">${t(lang, "staleData")}</span>` : html``;
}

/** A price under the Eilat column heading, with its own freshness. */
export function eilatPriceCell(
  price: number | null | undefined,
  currency: Currency,
  lang: Lang,
  { only, stale }: { only?: boolean; stale?: boolean }
): Html {
  const amount = positivePrice(price);
  if (amount === null) return emptyValue(lang);
  return html`<span class="eilat-price-cell">
    ${priceCell(amount, currency, lang)}
    ${only ? html`<span class="eilat-price-cell__only">${t(lang, "eilatOnlyLine")}</span>` : ""}
    ${stalePriceTag(stale, lang)}
  </span>`;
}

/**
 * The small second price under a product's main one (owner, 2026-11-16):
 *   regular mode: "באילת ₪1,000", or "באילת בלבד ₪1,000" for an Eilat-only part;
 *   Eilat mode:   "רגיל ₪1,180" (the regular price), nothing when there is none.
 * The main price is the active region's; this line never feeds a sort or total.
 */
export function altPriceLine(
  regular: number | null | undefined,
  eilat: number | null | undefined,
  eilatOnly: boolean,
  region: Region,
  currency: Currency,
  lang: Lang
): Html {
  const reg = positivePrice(regular);
  const eil = positivePrice(eilat);
  if (region === "eilat") {
    if (reg === null || eil === null) return html``;
    return html`<span class="price-alt">${t(lang, "regularLine")} <bdi>${formatPrice(reg, currency, lang)}</bdi></span>`;
  }
  if (eil === null) return html``;
  const label = eilatOnly ? t(lang, "eilatOnlyLine") : t(lang, "eilatLine");
  return html`<span class="price-alt price-alt--eilat"><span class="price-alt__badge">${label} <bdi>${formatPrice(eil, currency, lang)}</bdi></span></span>`;
}

/** Eilat mode, no Eilat price: the regular price muted, under "not sold in Eilat". */
export function notInEilatLine(regular: number | null | undefined, currency: Currency, lang: Lang): Html {
  const reg = positivePrice(regular);
  return html`<span class="price-alt price-alt--none">${t(lang, "notInEilat")}${reg !== null ? html` · <bdi>${formatPrice(reg, currency, lang)}</bdi>` : ""}</span>`;
}
