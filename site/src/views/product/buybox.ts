import { formatPrice } from "../../format";
import { lastSeenText, t, vendorLabel, vendorsCount } from "../../i18n";
import { icon } from "../../icons";
import { bestOffer, sortOffers } from "../../offers";
import type { Currency, Lang, Product } from "../../types";
import { safeUrl } from "../../utils";
import { button } from "../../ui/button";
import { card } from "../../ui/card";
import { chip } from "../../ui/chip";
import { emptyValue } from "../../ui/empty";
import { html, type Html } from "../../ui/html";
import { compareButton, saveButton } from "../../ui/pick";
import { positivePrice, priceCell } from "../../ui/price";
import { initialsOf, thumb } from "../../ui/thumb";
import { vendorMono } from "../../ui/vendor";

function stockLine(inStock: boolean, lang: Lang): Html {
  return html`<span class="stock"><span class="status-dot ${inStock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${inStock ? t(lang, "inStock") : t(lang, "outOfStock")}</span>`;
}

/**
 * Photo + price box: best price and where, the drop signal, the big buy
 * link, add-to-build, save/compare, and the variant pills.
 */
export function buyBoxMarkup(
  product: Product,
  lang: Lang,
  currency: Currency,
  canAdd: boolean,
  variants: Html,
  name: string
): Html {
  const offer = bestOffer(product);
  const price = positivePrice(offer?.price ?? product.min_price);
  const url = offer ? safeUrl(offer.url) : null;
  return html`<aside class="card card--flush buybox">
    <div class="buybox__photo">${thumb(product.image, initialsOf(product.brand, name), "xl", name, true)}</div>
    <div class="buybox__body">
      <div>
        <p class="buybox__label">${t(lang, "cheapest")}</p>
        <div class="buybox__price">
          ${priceCell(price, currency, lang, "lg")}
          ${offer && price !== null ? html`<span class="buybox__where">${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</span>` : ""}
        </div>
        <div class="buybox__signals" id="pdp-signals"></div>
        <p class="buybox__meta">${stockLine(product.in_stock, lang)}<span aria-hidden="true">·</span><span>${vendorsCount(lang, product.vendor_count)}</span></p>
      </div>
      ${url && price !== null && offer
        ? html`<a class="buy-cta" href="${url}" target="_blank" rel="noopener noreferrer">
            ${icon("cart", 20)}
            <span class="buy-cta__text"><span>${t(lang, "buyLabel")}</span><small>${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</small></span>
            <span class="buy-cta__price">${formatPrice(price, currency, lang)}</span>
          </a>`
        : ""}
      ${canAdd ? button({ label: t(lang, "addToPartList"), icon: icon("plus", 16), variant: "primary", id: "pdp-add", className: "btn--block" }) : ""}
      <div class="buybox__tools">${saveButton(product, lang, true)}${compareButton(product, lang)}</div>
      ${variants}
    </div>
  </aside>`;
}

/** Offers table, cheapest in-stock first, the best price highlighted. */
export function offersCard(product: Product, lang: Lang, currency: Currency): Html {
  const offers = sortOffers(product.offers);
  const best = bestOffer(product);
  // Shipping is rarely published (currently none of the ~6k listings): show
  // the column only when an offer supplies it, and the total only when
  // shipping can change it.
  const showShipping = offers.some((o) => o.shipping !== null && o.shipping !== undefined);
  const showTotal = offers.some((o) => (o.shipping ?? 0) > 0);
  const latest = offers.map((o) => o.last_seen).sort().at(-1);

  const rows = offers.map((offer) => {
    const price = positivePrice(offer.price);
    const total = (price ?? 0) + (offer.shipping ?? 0);
    const url = safeUrl(offer.url);
    const isBest = offer === best;
    const seen = lastSeenText(lang, offer.last_seen);
    return html`<tr class="${isBest ? "is-best" : offer.in_stock ? "" : "is-out"}">
      <th scope="row"><span class="offer-store">${vendorMono(offer.vendor)}<b>${vendorLabel(offer.vendor)}</b></span></th>
      <td><span class="offer-price">${priceCell(price, currency, lang)}${isBest && offers.length > 1 ? chip(t(lang, "cheapest"), { tone: "ok" }) : ""}</span></td>
      ${showShipping
        ? html`<td>${offer.shipping === null || offer.shipping === undefined
            ? emptyValue(lang)
            : offer.shipping === 0
              ? chip(t(lang, "freeShipping"), { tone: "ok" })
              : formatPrice(offer.shipping, currency, lang)}</td>`
        : ""}
      <td>${stockLine(offer.in_stock, lang)}</td>
      ${showTotal ? html`<td>${price !== null ? formatPrice(total, currency, lang) : emptyValue(lang)}</td>` : ""}
      <td class="offer-seen">${seen}${offer.stale ? html`<span class="offer-stale" title="${t(lang, "staleData")}">${icon("clock", 14)}<span class="visually-hidden">${t(lang, "staleData")}</span></span>` : ""}</td>
      <td class="col-action">${url && price !== null
        ? button({ label: t(lang, "toStore"), icon: icon("external", 14), variant: "buy", size: "sm", href: url, external: true, ariaLabel: `${t(lang, "toStore")}: ${vendorLabel(offer.vendor)}` })
        : emptyValue(lang)}</td>
    </tr>`;
  });

  return card(
    html`<div class="table-wrap"><table class="table offers-table">
        <thead><tr>
          <th scope="col">${t(lang, "merchantHeading")}</th>
          <th scope="col">${t(lang, "baseHeading")}</th>
          ${showShipping ? html`<th scope="col">${t(lang, "shippingHeading")}</th>` : ""}
          <th scope="col">${t(lang, "availability")}</th>
          ${showTotal ? html`<th scope="col">${t(lang, "totalHeading")}</th>` : ""}
          <th scope="col">${t(lang, "lastUpdated")}</th>
          <th scope="col"><span class="visually-hidden">${t(lang, "buyHeaderLabel")}</span></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p class="card__foot">${t(lang, "disclaimer")}</p>`,
    {
      title: t(lang, "pricesHeading"),
      sub: html`${vendorsCount(lang, product.vendor_count)}${latest ? html` · ${lastSeenText(lang, latest)}` : ""}`,
      flush: true,
      id: "pdp-offers",
    }
  );
}
