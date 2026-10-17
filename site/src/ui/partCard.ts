import type { PriceSignal } from "../signals";
import { productHash } from "../state";
import type { PartRef } from "../storage";
import type { Currency, Lang, Product } from "../types";
import { html, type Html } from "./html";
import { saveButtonRef } from "./pick";
import { priceCell } from "./price";
import { signalBadges } from "./signal";
import { initialsOf, thumb } from "./thumb";

/**
 * Compact part card (saved list, home price-drop strip): photo, name,
 * current price with its signal chips, and the heart. `product` is the live
 * catalog row when we have one; without it the snapshot is shown with an
 * empty price.
 */
export function partCard(
  ref: PartRef,
  product: Product | undefined,
  signal: PriceSignal | undefined,
  lang: Lang,
  currency: Currency
): Html {
  return html`<article class="part-card">
    <a class="part-card__link" href="${productHash(ref.category, ref.id)}">
      ${thumb(ref.thumb, initialsOf(ref.brand, ref.name), "lg", ref.name)}
      <span class="part-card__name">${ref.name}</span>
    </a>
    <div class="part-card__buy">
      ${priceCell(product?.min_price, currency, lang, "lg")}
      ${signalBadges(signal, lang)}
    </div>
    <div class="part-card__tools">${saveButtonRef(ref, lang)}</div>
  </article>`;
}
