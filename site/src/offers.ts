import { positivePrice } from "./ui/price";
import type { Offer, Product, Region } from "./types";

/** The offer's only price needs a whole-PC purchase (mirrors matching.is_conditional_offer). */
export function isBundleOffer(offer: Offer | null | undefined): boolean {
  return offer?.bundle_only === true;
}

/** Equal prices: today's offer ahead of a stale one (mirrors matching.choose_best_offer). */
function byPriceThenFresh(a: Offer, b: Offer): number {
  return (positivePrice(a.price) ?? Infinity) - (positivePrice(b.price) ?? Infinity) || Number(a.stale) - Number(b.stale);
}

/** Offers cheapest first, in-stock ahead of out-of-stock, bundle prices after plain ones, unpriced last. */
export function sortOffers(offers: Offer[]): Offer[] {
  return [...offers].sort((a, b) => {
    if (a.in_stock !== b.in_stock) return a.in_stock ? -1 : 1;
    if (isBundleOffer(a) !== isBundleOffer(b)) return isBundleOffer(a) ? 1 : -1;
    return byPriceThenFresh(a, b);
  });
}

/**
 * Cheapest priced offer, preferring in-stock ones; null when nothing is
 * priced. A bundle price wins only when no plain offer is priced.
 */
export function bestOffer(product: Product): Offer | null {
  const priced = (product.offers ?? []).filter((o) => positivePrice(o.price) !== null);
  if (priced.length === 0) return null;
  const plain = priced.filter((o) => !isBundleOffer(o));
  const ranked = plain.length > 0 ? plain : priced;
  const inStock = ranked.filter((o) => o.in_stock);
  const pool = inStock.length > 0 ? inStock : ranked;
  return pool.slice().sort(byPriceThenFresh)[0] ?? null;
}

/** The price a product contributes to totals and sorting (null = no price). */
export function effectivePrice(product: Product): number | null {
  return positivePrice(bestOffer(product)?.price ?? product.min_price);
}

// ---- Eilat (scraper/eilat.py) -------------------------------------------------
// The Eilat price lives beside the regular one on the same offer; nothing above
// reads it, so a regular minimum, sort or total never takes an Eilat price.

/**
 * The offer as seen at its vendor's Eilat store, or null when not sold there.
 * The regular price's promo amounts (was / deal / clearance) are regular-price
 * figures and are dropped; `bundle_only` is a purchase condition and stays.
 */
function asEilat(offer: Offer): Offer | null {
  const price = positivePrice(offer.eilat_price);
  if (price === null) return null;
  const {
    was_price: _was,
    sale_text: _sale,
    promo_price: _promo,
    promo_kind: _kind,
    new_pc_deal: _deal,
    clearance_price: _clearance,
    ...rest
  } = offer;
  return { ...rest, price, in_stock: offer.eilat_in_stock === true, stale: offer.eilat_stale === true };
}

/** Offers in the active region: Eilat-store copies (price = Eilat price) or the regular ones. */
export function regionOffers(product: Product, region: Region): Offer[] {
  if (region === "main") return product.offers ?? [];
  return (product.offers ?? []).map(asEilat).filter((o): o is Offer => o !== null);
}

/** bestOffer over the active region's offers. */
export function bestRegionOffer(product: Product, region: Region): Offer | null {
  if (region === "main") return bestOffer(product);
  return bestOffer({ ...product, offers: regionOffers(product, region) });
}

/** The product's price in the active region (sort, filter, totals); null = none there. */
export function regionPrice(product: Product, region: Region): number | null {
  if (region === "main") return effectivePrice(product);
  return positivePrice(bestRegionOffer(product, region)?.price ?? product.eilat_min_price);
}

/** The product's catalog minimum in the active region (from the site row). */
export function regionMinPrice(product: Product, region: Region): number | null {
  return positivePrice(region === "main" ? product.min_price : product.eilat_min_price);
}

/** Any offer has an in-stock price in the active region. */
export function regionInStock(product: Product, region: Region): boolean {
  return regionOffers(product, region).some((o) => o.in_stock && positivePrice(o.price) !== null);
}

/** Cheapest Eilat price, for the small line under a regular price. */
export function eilatPrice(product: Product): number | null {
  return regionPrice(product, "eilat");
}

/** Sold only at Eilat stores (no regular price at all). */
export function isEilatOnly(product: Product): boolean {
  return product.eilat_only === true || ((product.offers ?? []).length > 0 && (product.offers ?? []).every((o) => o.eilat_only === true));
}
