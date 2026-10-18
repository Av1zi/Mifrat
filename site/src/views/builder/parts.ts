import { loadCategory } from "../../api";
import { BUILD_SLOTS, knownPartWattage } from "../../build";
import { formatPrice } from "../../format";
import { t, vendorLabel } from "../../i18n";
import { bestOffer, effectivePrice } from "../../offers";
import {
  buildHash,
  exitListRoute,
  MULTI_SLOTS,
  productHash,
  replaceRoute,
  setStoredBuild,
  type BuildMap,
} from "../../state";
import type { Currency, Lang, Product } from "../../types";
import { displayName } from "../../utils";

/** Everything one builder page needs. Built once in index.ts, passed explicitly. */
export interface BuilderCtx {
  container: HTMLElement;
  lang: Lang;
  currency: Currency;
  /** Draft: slot id -> product ids. Mutated in place, persisted after each change. */
  build: BuildMap;
  /** Resolved products per slot, in build order. */
  parts: Map<string, Product[]>;
  /** Set while the page was opened from a /list/<id> link; cleared by the first edit. */
  activeListId: string | null;
  share: ShareState;
}

/** Short-link bookkeeping for the exact build currently shown. */
interface ShareState {
  shortUrlFor: { key: string; url: string } | null;
  pendingKey: string | null;
  timer: number | undefined;
}

/**
 * Normalises an incoming build (shared URL, list link or stored draft) to the
 * valid slots: single slots keep one entry, multi slots dedupe.
 */
export function cleanBuild(source: BuildMap): BuildMap {
  const validSlots = new Set(BUILD_SLOTS.map((slot) => slot.id));
  const build: BuildMap = {};
  for (const [slotId, productIds] of Object.entries(source)) {
    if (!validSlots.has(slotId)) continue;
    const ids = productIds.filter(Boolean);
    if (ids.length > 0) build[slotId] = MULTI_SLOTS.has(slotId) ? [...new Set(ids)] : [ids[0]];
  }
  return build;
}

/** Resolves ids to products and drops ids that no longer exist (stale links, removed listings). */
export async function refreshParts(ctx: BuilderCtx): Promise<void> {
  const next = new Map<string, Product[]>();
  const pruned: BuildMap = {};
  await Promise.all(
    BUILD_SLOTS.map(async (slot) => {
      const found: Product[] = [];
      for (const productId of ctx.build[slot.id] ?? []) {
        for (const category of slot.categories) {
          try {
            const match = (await loadCategory(category)).find((p) => p.id === productId);
            if (match) {
              found.push(match);
              break;
            }
          } catch {
            // Try the next category.
          }
        }
      }
      if (found.length > 0) {
        next.set(slot.id, found);
        pruned[slot.id] = found.map((p) => p.id);
      }
    })
  );
  for (const key of Object.keys(ctx.build)) delete ctx.build[key];
  Object.assign(ctx.build, pruned);
  persist(ctx);
  ctx.parts = next;
}

/** Saves the draft and syncs the address bar (leaving a /list path on first edit). */
export function persist(ctx: BuilderCtx): void {
  setStoredBuild(ctx.build);
  if (ctx.activeListId) {
    exitListRoute(buildHash(ctx.build));
    ctx.activeListId = null;
  } else {
    replaceRoute(buildHash(ctx.build));
  }
}

/** First pick per slot: drives wattage and compatibility checks. */
export function firstPicks(ctx: BuilderCtx): Record<string, Product> {
  const out: Record<string, Product> = {};
  for (const [slotId, list] of ctx.parts) if (list[0]) out[slotId] = list[0];
  return out;
}

export function buildWatts(ctx: BuilderCtx): number {
  let watts = 0;
  for (const [slotId, list] of ctx.parts) for (const p of list) watts += knownPartWattage(slotId, p);
  return watts;
}

export function buildTotal(ctx: BuilderCtx): number {
  let total = 0;
  for (const list of ctx.parts.values()) for (const p of list) total += effectivePrice(p) ?? 0;
  return total;
}

/** Plain-text / markdown export of the current parts list. */
export function exportLines(ctx: BuilderCtx, mode: "markdown" | "text"): string {
  const { lang, currency } = ctx;
  const origin = location.origin + location.pathname;
  const total = formatPrice(buildTotal(ctx), currency, lang);
  const lines: string[] =
    mode === "markdown"
      ? [`${t(lang, "componentHeading")}|${t(lang, "markdownItem")}|${t(lang, "priceHeading")}`, ":----|:----|:----"]
      : [];
  for (const slot of BUILD_SLOTS) {
    for (const product of ctx.parts.get(slot.id) ?? []) {
      const price = effectivePrice(product);
      const priceText = price === null ? t(lang, "notListed") : formatPrice(price, currency, lang);
      if (mode === "markdown") {
        const offer = bestOffer(product);
        const where = offer ? ` @ ${vendorLabel(offer.vendor)}` : "";
        const url = origin + productHash(product.category, product.id);
        lines.push(`**${slot.label[lang]}** | [${displayName(product)}](${url}) | ${priceText}${where}`);
      } else {
        lines.push(`${slot.label[lang]}: ${displayName(product)} - ${priceText}`);
      }
    }
  }
  lines.push(
    mode === "markdown"
      ? ` | **${t(lang, "totalLabel")}** | **${total}**`
      : `${t(lang, "totalLabel")} ${total}`
  );
  return lines.join("\n");
}
