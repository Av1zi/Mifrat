import { formatPrice } from "../../format";
import { t, vendorLabel, vendorsCount } from "../../i18n";
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

/** Sticky price box: best price, where, stock, and the two actions. */
export function buyBoxMarkup(
  product: Product,
  lang: Lang,
  currency: Currency,
  canAdd: boolean,
  variants: Html
): Html {
  const offer = bestOffer(product);
  const price = positivePrice(offer?.price ?? product.min_price);
  const url = offer ? safeUrl(offer.url) : null;
  return html`<aside class="card buybox">
    <p class="buybox__label">${t(lang, "cheapest")}</p>
    ${priceCell(price, currency, lang, "lg")}
    <div class="buybox__signals" id="pdp-signals"></div>
    ${offer && price !== null
      ? html`<p class="buybox__where">${t(lang, "atVendor")} <b>${vendorLabel(offer.vendor)}</b> · ${vendorsCount(lang, product.vendor_count)}</p>`
      : html`<p class="buybox__where">${emptyValue(lang)}</p>`}
    <span class="stock"><span class="status-dot ${product.in_stock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${product.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}</span>
    <div class="buybox__actions">
      ${url && price !== null
        ? button({ label: `${t(lang, "buyLabel")} · ${vendorLabel(offer!.vendor)}`, icon: icon("external", 16), variant: "primary", href: url, external: true })
        : ""}
      ${canAdd ? button({ label: t(lang, "addToPartList"), icon: icon("plus", 16), id: "pdp-add" }) : ""}
      <div class="buybox__tools">${compareButton(product, lang)}${saveButton(product, lang, true)}</div>
    </div>
    ${variants}
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

  const rows = offers.map((offer) => {
    const price = positivePrice(offer.price);
    const total = (price ?? 0) + (offer.shipping ?? 0);
    const url = safeUrl(offer.url);
    return html`<tr class="${offer === best ? "is-best" : offer.in_stock ? "" : "is-out"}">
      <td><b>${vendorLabel(offer.vendor)}</b>${offer === best ? html` ${chip(t(lang, "cheapest"), { tone: "brand" })}` : ""}</td>
      <td>${priceCell(price, currency, lang)}</td>
      ${showShipping
        ? html`<td>${offer.shipping === null || offer.shipping === undefined
            ? emptyValue(lang)
            : offer.shipping === 0
              ? chip(t(lang, "freeShipping"), { tone: "ok" })
              : formatPrice(offer.shipping, currency, lang)}</td>`
        : ""}
      <td><span class="stock"><span class="status-dot ${offer.in_stock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${offer.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}</span>${offer.stale ? html` <span class="stale-tag">${t(lang, "staleData")}</span>` : ""}</td>
      ${showTotal ? html`<td>${price !== null ? formatPrice(total, currency, lang) : emptyValue(lang)}</td>` : ""}
      <td class="col-action">${url && price !== null
        ? button({ label: t(lang, "buyLabel"), icon: icon("external", 14), variant: offer === best ? "primary" : "ghost", size: "sm", href: url, external: true })
        : emptyValue(lang)}</td>
    </tr>`;
  });

  return card(
    html`<div class="table-wrap"><table class="table">
        <thead><tr>
          <th scope="col">${t(lang, "merchantHeading")}</th>
          <th scope="col">${t(lang, "baseHeading")}</th>
          ${showShipping ? html`<th scope="col">${t(lang, "shippingHeading")}</th>` : ""}
          <th scope="col">${t(lang, "availability")}</th>
          ${showTotal ? html`<th scope="col">${t(lang, "totalHeading")}</th>` : ""}
          <th scope="col"><span class="visually-hidden">${t(lang, "buyHeaderLabel")}</span></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p class="fineprint">${t(lang, "disclaimer")}</p>`,
    { title: t(lang, "pricesHeading") }
  );
}
