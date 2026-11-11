import { describe, expect, it } from "vitest";
import { bestOffer, effectivePrice, sortOffers } from "../src/offers";
import type { Offer } from "../src/types";
import { product } from "./fixtures";

function offer(vendor: string, price: number, extra: Partial<Offer> = {}): Offer {
  return { vendor, url: `https://${vendor}.example/p`, price, in_stock: true, last_seen: "2026-11-10", stale: false, ...extra };
}

describe("bundle-only offers (owner Q1)", () => {
  const plain = offer("ksp", 500);
  const bundle = offer("tms", 400, { bundle_only: true });

  it("never outrank a priced plain offer", () => {
    const p = product("gpu:1", "Card", {}, { offers: [bundle, plain] });
    expect(bestOffer(p)).toBe(plain);
    expect(effectivePrice(p)).toBe(500);
  });

  it("outrank even an in-stock bundle when the plain offer is out of stock", () => {
    const out = offer("ksp", 500, { in_stock: false });
    expect(bestOffer(product("gpu:2", "Card", {}, { offers: [bundle, out] }))).toBe(out);
  });

  it("win when they are all a product has", () => {
    expect(bestOffer(product("gpu:3", "Card", {}, { offers: [bundle] }))).toBe(bundle);
  });

  it("a new-PC deal stays a plain offer at its regular price", () => {
    const deal = offer("tms", 450, { new_pc_deal: true, promo_price: 380 });
    expect(bestOffer(product("gpu:4", "Card", {}, { offers: [plain, deal] }))).toBe(deal);
  });

  it("sort after plain offers of the same stock state", () => {
    expect(sortOffers([bundle, plain])).toEqual([plain, bundle]);
  });
});
