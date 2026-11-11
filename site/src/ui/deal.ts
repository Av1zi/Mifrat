import { formatPrice } from "../format";
import { t } from "../i18n";
import type { Currency, Lang, Offer } from "../types";
import { html, type Html } from "./html";
import { positivePrice } from "./price";

function tipChip(label: string, tip: string, alignEnd: boolean | undefined): Html {
  return html`<span class="chip chip--ok deal-chip${alignEnd ? " deal-chip--end" : ""}" tabindex="0"><bdi>${label}</bdi><span class="visually-hidden">: ${tip}</span><span class="deal-chip__tip" aria-hidden="true">${tip}</span></span>`;
}

/**
 * Green chip on a conditional offer (owner Q1). The shown price stays the
 * offer's own; hovering or focusing the chip reveals the deal terms and, when
 * known, the deal price. A second chip carries the same store's cheaper
 * clearance listing of the part. Empty for a plain offer.
 */
export function dealChip(
  offer: Offer | null | undefined,
  currency: Currency,
  lang: Lang,
  opts: { alignEnd?: boolean } = {}
): Html {
  if (!offer) return html``;
  let deal: Html = html``;
  if (offer.bundle_only) {
    const price = positivePrice(offer.price);
    const tip = price !== null ? `${formatPrice(price, currency, lang)} · ${t(lang, "dealBundleTip")}` : t(lang, "dealBundleTip");
    deal = tipChip(t(lang, "dealBundle"), tip, opts.alignEnd);
  } else if (offer.new_pc_deal) {
    const promo = positivePrice(offer.promo_price);
    const tip = promo !== null ? `${formatPrice(promo, currency, lang)} ${t(lang, "dealPcTip")}` : t(lang, "dealPcTipNoPrice");
    deal = tipChip(t(lang, "dealPc"), tip, opts.alignEnd);
  }
  const was = positivePrice(offer.was_price);
  const price = positivePrice(offer.price);
  const sale: Html =
    !offer.bundle_only && (was !== null || offer.sale_text)
      ? tipChip(
          offer.sale_text ? `${t(lang, "dealSale")} ${offer.sale_text}` : t(lang, "dealSale"),
          was !== null && price !== null && was > price
            ? `${t(lang, "dealSaleWas")} ${formatPrice(was, currency, lang)}`
            : t(lang, "dealSaleTip"),
          opts.alignEnd
        )
      : html``;
  const clearance = positivePrice(offer.clearance_price);
  if (clearance === null) return html`${sale}${deal}`;
  const clearanceTip = `${formatPrice(clearance, currency, lang)} · ${t(lang, "dealClearanceTip")}`;
  return html`${sale}${deal}${tipChip(t(lang, "dealClearance"), clearanceTip, opts.alignEnd)}`;
}

/** The crossed-out old price of a store-wide sale, or nothing. */
export function wasPrice(offer: Offer | null | undefined, currency: Currency, lang: Lang): Html {
  const was = positivePrice(offer?.was_price);
  const price = positivePrice(offer?.price);
  if (was === null || price === null || was <= price) return html``;
  return html`<s class="price-was">${formatPrice(was, currency, lang)}</s>`;
}
