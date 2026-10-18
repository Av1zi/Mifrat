import { categoryLabel, t } from "../../i18n";
import {
  addToBuild,
  buildHash,
  categoryHash,
  navigate,
  setStoredBuild,
  getStoredBuild,
} from "../../state";
import type { Product } from "../../types";
import { chip } from "../../ui/chip";
import { html, type Html } from "../../ui/html";
import { displayName } from "../../utils";
import type { CategoryCtx } from "./data";

/** Banner shown when the category page is a builder slot picker (?pick=<slot>). */
export function pickBannerMarkup(ctx: CategoryCtx): Html {
  const slot = ctx.pickSlot;
  if (!slot) return html``;
  const { lang } = ctx;
  return html`<div class="pick-banner">
    <span class="pick-banner__label">${slot.label[lang]}</span>
    ${slot.categories.length > 1
      ? html`<nav class="pick-banner__tabs">${slot.categories.map(
          (id) => html`<a class="${id === ctx.category ? "is-active" : ""}" href="${categoryHash(id, { pick: slot.id })}">${categoryLabel(id, lang)}</a>`
        )}</nav>`
      : ""}
    ${ctx.hiddenIncompatible > 0
      ? chip(`${ctx.hiddenIncompatible} ${t(lang, "hiddenIncompatible")}`, { tone: "warn" })
      : ""}
    <a class="pick-banner__cancel" href="${buildHash(ctx.storedBuild)}">${t(lang, "cancel")}</a>
  </div>`;
}

/** Adds a product to the slot being picked and returns to the builder. */
export function addPickedPart(ctx: CategoryCtx, product: Product): void {
  const slot = ctx.pickSlot;
  if (!slot) return;
  if (!slot.categories.includes(product.category)) {
    const status = ctx.container.querySelector('[data-role="status"]');
    if (status) status.textContent = `${displayName(product)} — ${t(ctx.lang, "pickMismatch")}`;
    return;
  }
  const build = getStoredBuild();
  addToBuild(build, slot.id, product.id);
  setStoredBuild(build);
  navigate(buildHash(build));
}
