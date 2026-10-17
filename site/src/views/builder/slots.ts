import { BUILD_SLOTS, type BuildSlot } from "../../build";
import { t, vendorLabel } from "../../i18n";
import { CATEGORY_ICONS, icon, type IconName } from "../../icons";
import { bestOffer, effectivePrice } from "../../offers";
import { categoryHash, MULTI_SLOTS, productHash } from "../../state";
import type { Product } from "../../types";
import { button } from "../../ui/button";
import { emptyValue } from "../../ui/empty";
import { html, type Html } from "../../ui/html";
import { priceCell } from "../../ui/price";
import { initialsOf, thumb } from "../../ui/thumb";
import { displayName, safeUrl } from "../../utils";
import type { BuilderCtx } from "./parts";

const SLOT_ICONS: Record<string, IconName> = {
  cpu: CATEGORY_ICONS.cpu,
  cooler: CATEGORY_ICONS.cooler_air,
  motherboard: CATEGORY_ICONS.motherboard,
  memory: CATEGORY_ICONS.memory,
  storage: CATEGORY_ICONS.storage,
  gpu: CATEGORY_ICONS.gpu,
  case: CATEGORY_ICONS.case,
  psu: CATEGORY_ICONS.psu,
  extras: CATEGORY_ICONS.accessories,
};

const chooseHref = (slot: BuildSlot): string => categoryHash(slot.categories[0], { pick: slot.id });

function partMarkup(ctx: BuilderCtx, slot: BuildSlot, product: Product): Html {
  const { lang, currency } = ctx;
  const offer = bestOffer(product);
  const price = effectivePrice(product);
  const buy = offer ? safeUrl(offer.url) : null;
  const href = productHash(product.category, product.id);
  const name = displayName(product);
  return html`<div class="part">
    <a class="part__thumb" href="${href}" tabindex="-1" aria-hidden="true">${thumb(product.thumb ?? product.image, initialsOf(product.brand, product.name), "md")}</a>
    <div class="part__main">
      <a class="part__name" href="${href}">${name}</a>
      <span class="part__meta">${product.brand ?? ""}${offer ? html`${product.brand ? " · " : ""}${vendorLabel(offer.vendor)}` : ""}</span>
      <span class="stock"><span class="status-dot ${product.in_stock ? "status-dot--ok" : "status-dot--err"}" aria-hidden="true"></span>${product.in_stock ? t(lang, "inStock") : t(lang, "outOfStock")}</span>
    </div>
    <div class="part__buy">
      ${price !== null && buy
        ? html`<a href="${buy}" target="_blank" rel="noopener noreferrer" title="${t(lang, "buyLabel")}">${priceCell(price, currency, lang)}</a>`
        : emptyValue(lang)}
    </div>
    ${button({
      label: t(lang, "removePart"),
      icon: icon("trash", 16),
      variant: "ghost",
      size: "sm",
      iconOnly: true,
      className: "part__remove",
      data: { action: "remove", slot: slot.id, id: product.id },
      ariaLabel: `${t(lang, "removePart")}: ${name}`,
    })}
  </div>`;
}

function slotCard(ctx: BuilderCtx, slot: BuildSlot): Html {
  const { lang } = ctx;
  const list = ctx.parts.get(slot.id) ?? [];
  const label = slot.label[lang];
  return html`<section class="slot card${list.length === 0 ? " is-empty" : ""}" aria-label="${label}">
    <header class="slot__head">
      <span class="slot__icon" aria-hidden="true">${icon(SLOT_ICONS[slot.id] ?? "grid", 18)}</span>
      <h2><a href="${categoryHash(slot.categories[0])}">${label}</a></h2>
    </header>
    ${list.length === 0
      ? html`<div class="slot__empty"><span class="text-dim">${t(lang, "buildEmptySlot")}</span>${button({ label: slot.choose[lang], icon: icon("plus", 15), variant: "subtle", href: chooseHref(slot) })}</div>`
      : html`${list.map((p) => partMarkup(ctx, slot, p))}${MULTI_SLOTS.has(slot.id)
          ? button({ label: `${t(lang, "addAdditionalLabel")} ${label}`, icon: icon("plus", 15), size: "sm", href: chooseHref(slot), className: "slot__more" })
          : ""}`}
  </section>`;
}

export function slotsMarkup(ctx: BuilderCtx): Html {
  return html`<div class="slots">${BUILD_SLOTS.map((slot) => slotCard(ctx, slot))}</div>`;
}
