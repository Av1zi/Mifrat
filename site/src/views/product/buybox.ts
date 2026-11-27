import { formatPrice } from "../../format";
import { lastSeenText, t, vendorLabel, vendorsCount } from "../../i18n";
import { icon } from "../../icons";
import {
  bestRegionOffer,
  effectivePrice,
  eilatPrice,
  isBundleOffer,
  isEilatOnly,
  regionInStock,
  regionOffers,
  regionPrice,
  sortOffers,
} from "../../offers";
import { getRegion } from "../../state";
import type { Currency, Lang, Offer, Product, Region } from "../../types";
import { safeUrl } from "../../utils";
import { button } from "../../ui/button";
import { card } from "../../ui/card";
import { chip } from "../../ui/chip";
import { dealChip, wasPrice } from "../../ui/deal";
import { emptyValue } from "../../ui/empty";
import { html, type Html } from "../../ui/html";
import { compareButton, saveButton } from "../../ui/pick";
import { altPriceLine, notInEilatLine, positivePrice, priceCell, stalePriceTag } from "../../ui/price";
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
  const region = getRegion();
  const offer = bestRegionOffer(product, region);
  const price = regionPrice(product, region);
  const url = offer ? safeUrl(offer.url) : null;
  // Every priced offer needs a whole-PC purchase: the part cannot be bought
  // alone, so the buy button is shown muted and says so.
  const bundle = isBundleOffer(offer);
  const inStock = region === "main" ? product.in_stock : regionInStock(product, region);
  const vendors = new Set(regionOffers(product, region).map((o) => o.vendor)).size;
  return html`<aside class="card card--flush buybox">
    <div class="buybox__photo">${thumb(product.image, initialsOf(product.brand, name), "xl", name, true)}</div>
    <div class="buybox__body">
      <div>
        <p class="buybox__label">${t(lang, "cheapest")}${region === "eilat" ? html` · ${t(lang, "regionEilat")}` : ""}</p>
        <div class="buybox__price">
          ${wasPrice(offer, currency, lang)}${priceCell(price, currency, lang, "lg")}
          ${offer && price !== null ? html`<span class="buybox__where">${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</span>` : ""}
          ${stalePriceTag(offer?.stale, lang)}
          ${price !== null ? dealChip(offer, currency, lang) : ""}
          ${region === "eilat" && price === null
            ? notInEilatLine(effectivePrice(product), currency, lang)
            : altPriceLine(effectivePrice(product), eilatPrice(product), isEilatOnly(product), region, currency, lang)}
        </div>
        <div class="buybox__signals" id="pdp-signals"></div>
        <p class="buybox__meta">${stockLine(inStock, lang)}<span aria-hidden="true">·</span><span>${vendorsCount(lang, vendors)}</span></p>
      </div>
      ${url && price !== null && offer
        ? html`<a class="buy-cta${bundle ? " buy-cta--bundle" : ""}" href="${url}" target="_blank" rel="noopener noreferrer">
            ${icon(bundle ? "tower" : "cart", 20)}
            <span class="buy-cta__text"><span>${t(lang, bundle ? "bundleOnlyCta" : "buyLabel")}</span><small>${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</small></span>
            <span class="buy-cta__price">${formatPrice(price, currency, lang)}</span>
          </a>`
        : ""}
      ${canAdd ? button({ label: t(lang, "addToPartList"), icon: icon("plus", 16), variant: "primary", id: "pdp-add", className: "btn--block" }) : ""}
      <div class="buybox__tools">${saveButton(product, lang, true)}${compareButton(product, lang)}</div>
      ${variants}
    </div>
  </aside>`;
}

/**
 * Phone-only bar pinned to the bottom of the product page once the buy box
 * has scrolled away: best price, where, and the same store link.
 */
export function buyBarMarkup(product: Product, lang: Lang, currency: Currency): Html {
  const region = getRegion();
  const offer = bestRegionOffer(product, region);
  const price = regionPrice(product, region);
  const url = offer ? safeUrl(offer.url) : null;
  if (!offer || !url || price === null) return html``;
  const bundle = isBundleOffer(offer);
  return html`<div class="buybar is-concealed" data-role="buybar" aria-hidden="true">
    <div class="buybar__price">
      ${priceCell(price, currency, lang, "md")}
      <span class="buybar__where">${t(lang, "atVendor")} ${vendorLabel(offer.vendor)}</span>
      ${stalePriceTag(offer.stale, lang)}
      ${altPriceLine(effectivePrice(product), eilatPrice(product), isEilatOnly(product), region, currency, lang)}
    </div>
    ${button({
      label: t(lang, bundle ? "bundleOnlyCta" : "toStore"),
      icon: icon(bundle ? "tower" : "external", 16),
      variant: bundle ? "outline" : "buy",
      href: url,
      external: true,
      className: "buybar__cta",
      ariaLabel: `${t(lang, "toStore")}: ${vendorLabel(offer.vendor)}`,
    })}
  </div>`;
}

const offerKey = (o: Offer): string => `${o.vendor}|${o.url}`;

/** The small second price on one offer row (the other region's price). */
function offerAltLine(original: Offer | undefined, region: Region, currency: Currency, lang: Lang): Html {
  if (!original) return html``;
  return altPriceLine(original.price, original.eilat_price, original.eilat_only === true, region, currency, lang);
}

/** Offers table, cheapest in-stock first, the best price highlighted. */
export function offersCard(product: Product, lang: Lang, currency: Currency, noStore: string[] = []): Html {
  const region = getRegion();
  const offers = sortOffers(regionOffers(product, region));
  const best = bestRegionOffer(product, region);
  // Each shown row's original offer: its other-region price is the small
  // line (an Eilat-only offer's row shows only "Eilat only").
  const originalOf = new Map(product.offers.map((o) => [offerKey(o), o]));
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
      <td><span class="offer-price">${wasPrice(offer, currency, lang)}${priceCell(price, currency, lang)}${isBest && offers.length > 1 ? chip(t(lang, "cheapest"), { tone: "ok" }) : ""}${price !== null ? dealChip(offer, currency, lang) : ""}${offerAltLine(originalOf.get(offerKey(offer)), region, currency, lang)}</span></td>
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
        ? button({ label: t(lang, "toStore"), icon: icon("external", 14), variant: isBundleOffer(offer) ? "outline" : "buy", size: "sm", href: url, external: true, ariaLabel: `${t(lang, "toStore")}: ${vendorLabel(offer.vendor)}` })
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
        <tbody>${rows.length > 0 ? rows : html`<tr><td colspan="9">${emptyValue(lang)} ${t(lang, "notInEilat")}</td></tr>`}</tbody>
      </table></div>
      ${region === "eilat"
        ? html`<p class="card__foot">${t(lang, "eilatNote")}${noStore.length > 0 ? html` ${t(lang, "eilatNoStore")}: ${noStore.map((v) => vendorLabel(v)).join(", ")}.` : ""}</p>`
        : ""}
      <p class="card__foot">${t(lang, "disclaimer")}</p>`,
    {
      title: region === "eilat" ? `${t(lang, "pricesHeading")} · ${t(lang, "regionEilat")}` : t(lang, "pricesHeading"),
      sub: html`${vendorsCount(lang, new Set(offers.map((o) => o.vendor)).size)}${latest ? html` · ${lastSeenText(lang, latest)}` : ""}`,
      flush: true,
      id: "pdp-offers",
    }
  );
}
