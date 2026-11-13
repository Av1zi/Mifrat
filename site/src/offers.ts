import { positivePrice } from "./ui/price";
import type { Offer, Product } from "./types";

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
