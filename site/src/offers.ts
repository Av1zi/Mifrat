import { positivePrice } from "./ui/price";
import type { Offer, Product } from "./types";

/** Offers cheapest first, in-stock ahead of out-of-stock, unpriced last. */
export function sortOffers(offers: Offer[]): Offer[] {
  return [...offers].sort((a, b) => {
    if (a.in_stock !== b.in_stock) return a.in_stock ? -1 : 1;
    return (positivePrice(a.price) ?? Infinity) - (positivePrice(b.price) ?? Infinity);
  });
}

/** Cheapest priced offer, preferring in-stock ones; null when nothing is priced. */
export function bestOffer(product: Product): Offer | null {
  const priced = (product.offers ?? []).filter((o) => positivePrice(o.price) !== null);
  if (priced.length === 0) return null;
  const inStock = priced.filter((o) => o.in_stock);
  const pool = inStock.length > 0 ? inStock : priced;
  return pool.slice().sort((a, b) => (a.price ?? 0) - (b.price ?? 0))[0] ?? null;
}

/** The price a product contributes to totals and sorting (null = no price). */
export function effectivePrice(product: Product): number | null {
  return positivePrice(bestOffer(product)?.price ?? product.min_price);
}
