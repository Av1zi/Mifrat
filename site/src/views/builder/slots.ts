import { BUILD_SLOTS, type BuildSlot } from "../../build";
import { formatPrice } from "../../format";
import { buildFootNote, t, vendorLabel } from "../../i18n";
import { icon } from "../../icons";
import { bestOffer, effectivePrice } from "../../offers";
import { categoryHash, MULTI_SLOTS, productHash } from "../../state";
import type { Product } from "../../types";
import { emptyValue } from "../../ui/empty";
import { html, type Html } from "../../ui/html";
import { initialsOf, thumb } from "../../ui/thumb";
import { vendorTag } from "../../ui/vendor";
import { displayName, safeUrl } from "../../utils";
import { chipText, pickColumns } from "../category/columns";
import { buildTotal, type BuilderCtx } from "./parts";

const chooseHref = (slot: BuildSlot): string => categoryHash(slot.categories[0], { pick: slot.id });

/** "LGA1851 · Z890 · ATX": the key specs of a picked part, from the list columns. */
function partSpecs(product: Product, lang: BuilderCtx["lang"]): Html[] {
  return pickColumns([product], product.category)
    .map((field) => chipText(product, field, lang))
    .filter(Boolean)
    .slice(0, 4)
    .map((text, i) => html`${i > 0 ? " · " : ""}<bdi>${text}</bdi>`);
}

function partRow(ctx: BuilderCtx, slot: BuildSlot, product: Product, first: boolean): Html {
  const { lang, currency } = ctx;
  const offer = bestOffer(product);
  const price = effectivePrice(product);
  const buy = offer ? safeUrl(offer.url) : null;
  const href = productHash(product.category, product.id);
  const name = displayName(product);
  const specs = partSpecs(product, lang);
  return html`<tr class="bt-row${first ? "" : " bt-row--extra"}">
    <th scope="row" class="bt-slot">${first ? html`<a href="${categoryHash(slot.categories[0])}">${slot.label[lang]}</a>` : html`<span class="visually-hidden">${slot.label[lang]}</span>`}</th>
    <td class="bt-part">
      <a class="bt-part__thumb" href="${href}" tabindex="-1" aria-hidden="true">${thumb(product.thumb ?? product.image, initialsOf(product.brand, product.name), "sm")}</a>
      <span class="bt-part__text">
        <a class="bt-part__name" href="${href}" dir="auto">${name}</a>
        <span class="bt-part__sub">${specs.length > 0 ? specs : product.brand ?? ""}${product.in_stock ? "" : html` <span class="row__out">· ${t(lang, "outOfStock")}</span>`}</span>
      </span>
    </td>
    <td class="bt-price">${price !== null ? formatPrice(price, currency, lang) : emptyValue(lang)}</td>
    <td class="bt-store">${offer ? vendorTag(offer.vendor) : ""}</td>
    <td class="bt-buy">${buy && price !== null && offer
      ? html`<a class="btn btn--buy btn--sm" href="${buy}" target="_blank" rel="noopener noreferrer" aria-label="${t(lang, "toStore")}: ${vendorLabel(offer.vendor)}">${t(lang, "toStore")}</a>`
      : ""}</td>
    <td class="bt-x"><button type="button" class="x-btn" data-action="remove" data-slot="${slot.id}" data-id="${product.id}" aria-label="${t(lang, "removePart")}: ${name}" title="${t(lang, "removePart")}">${icon("trash", 16)}</button></td>
  </tr>`;
}

function slotRows(ctx: BuilderCtx, slot: BuildSlot): Html {
  const { lang } = ctx;
  const list = ctx.parts.get(slot.id) ?? [];
  const label = slot.label[lang];
  if (list.length === 0) {
    return html`<tr class="bt-row bt-row--empty">
      <th scope="row" class="bt-slot"><a href="${categoryHash(slot.categories[0])}">${label}</a></th>
      <td colspan="5" class="bt-choose"><a class="btn btn--subtle btn--sm" href="${chooseHref(slot)}">${icon("plus", 15)}<span>${slot.choose[lang]}</span></a></td>
    </tr>`;
  }
  return html`${list.map((p, i) => partRow(ctx, slot, p, i === 0))}${MULTI_SLOTS.has(slot.id)
    ? html`<tr class="bt-row bt-row--more">
        <th scope="row" class="bt-slot"><span class="visually-hidden">${label}</span></th>
        <td colspan="5" class="bt-choose"><a class="btn btn--subtle btn--sm" href="${chooseHref(slot)}">${icon("plus", 15)}<span>${t(lang, "addAdditionalLabel")} ${label}</span></a></td>
      </tr>`
    : ""}`;
}

/** The parts table: one row per picked part, a "choose" row per empty slot, the total in the foot. */
export function slotsMarkup(ctx: BuilderCtx): Html {
  const { lang, currency } = ctx;
  const items = [...ctx.parts.values()].flat();
  const stores = new Set(items.map((p) => bestOffer(p)?.vendor).filter(Boolean)).size;
  return html`<section class="card card--flush build-table-card" aria-label="${t(lang, "builderTitle")}">
    <div class="table-wrap"><table class="table build-table">
      <thead><tr>
        <th scope="col" class="bt-slot">${t(lang, "componentHeading")}</th>
        <th scope="col">${t(lang, "selectionHeading")}</th>
        <th scope="col" class="bt-price">${t(lang, "priceHeading")}</th>
        <th scope="col">${t(lang, "storeHeading")}</th>
        <th scope="col"><span class="visually-hidden">${t(lang, "buyHeaderLabel")}</span></th>
        <th scope="col"><span class="visually-hidden">${t(lang, "removePart")}</span></th>
      </tr></thead>
      <tbody>${BUILD_SLOTS.map((slot) => slotRows(ctx, slot))}</tbody>
      <tfoot><tr>
        <td colspan="2" class="bt-note">${items.length > 0 ? buildFootNote(lang, items.length, stores) : t(lang, "buildEmptyNote")}</td>
        <td class="bt-total"><span>${t(lang, "totalShort")}</span><b>${formatPrice(buildTotal(ctx), currency, lang)}</b></td>
        <td colspan="3" class="bt-foot-pad"></td>
      </tr></tfoot>
    </table></div>
  </section>`;
}
