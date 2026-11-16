import { describe, expect, it } from "vitest";
import {
  bestOffer,
  bestRegionOffer,
  effectivePrice,
  eilatPrice,
  isEilatOnly,
  regionInStock,
  regionMinPrice,
  regionOffers,
  regionPrice,
} from "../src/offers";
import type { Offer } from "../src/types";
import { altPriceLine, notInEilatLine } from "../src/ui/price";
import { product } from "./fixtures";

function offer(vendor: string, price: number | null, extra: Partial<Offer> = {}): Offer {
  return { vendor, url: `https://${vendor}.example/p`, price, in_stock: true, last_seen: "2026-11-16", stale: false, ...extra };
}

describe("regular mode never reads an Eilat price", () => {
  const both = offer("tms", 1180, { eilat_price: 1000, eilat_in_stock: true });
  const plain = offer("ksp", 1200);
  const only = offer("tms", null, { in_stock: false, eilat_price: 900, eilat_in_stock: true, eilat_only: true });

  it("keeps the regular best offer and price", () => {
    const p = product("gpu:1", "Card", {}, { offers: [both, plain], min_price: 1180, eilat_min_price: 1000 });
    expect(bestOffer(p)).toBe(both);
    expect(effectivePrice(p)).toBe(1180);
    expect(regionPrice(p, "main")).toBe(1180);
  });

  it("an Eilat-only offer never sets the regular minimum", () => {
    const p = product("gpu:2", "Card", {}, { offers: [plain, only], min_price: 1200, eilat_min_price: 900 });
    expect(bestOffer(p)).toBe(plain);
    expect(effectivePrice(p)).toBe(1200);
  });

  it("an Eilat-only product has no regular price", () => {
    const p = product("gpu:3", "Card", {}, { offers: [only], min_price: null, eilat_min_price: 900, eilat_only: true });
    expect(effectivePrice(p)).toBeNull();
    expect(regionMinPrice(p, "main")).toBeNull();
    expect(isEilatOnly(p)).toBe(true);
  });
});

describe("Eilat mode", () => {
  const tms = offer("tms", 1180, { eilat_price: 1000, eilat_in_stock: false, was_price: 1300, sale_text: "-10%" });
  const ksp = offer("ksp", 1150, { eilat_price: 1020, eilat_in_stock: true });
  const yahav = offer("yahav", 1100);

  it("uses only offers sold in Eilat, at their Eilat price", () => {
    const p = product("cpu:1", "CPU", {}, { offers: [tms, ksp, yahav] });
    const eilat = regionOffers(p, "eilat");
    expect(eilat.map((o) => [o.vendor, o.price])).toEqual([["tms", 1000], ["ksp", 1020]]);
  });

  it("prefers in-stock in Eilat, like the regular rule", () => {
    const p = product("cpu:2", "CPU", {}, { offers: [tms, ksp, yahav] });
    expect(bestRegionOffer(p, "eilat")?.vendor).toBe("ksp");
    expect(regionPrice(p, "eilat")).toBe(1020);
    expect(regionInStock(p, "eilat")).toBe(true);
  });

  it("drops the regular price's sale figures from the Eilat copy", () => {
    const p = product("cpu:3", "CPU", {}, { offers: [tms] });
    const copy = regionOffers(p, "eilat")[0];
    expect(copy.was_price).toBeUndefined();
    expect(copy.sale_text).toBeUndefined();
  });

  it("a product not sold in Eilat has no Eilat price", () => {
    const p = product("cpu:4", "CPU", {}, { offers: [yahav], min_price: 1100 });
    expect(regionPrice(p, "eilat")).toBeNull();
    expect(regionMinPrice(p, "eilat")).toBeNull();
    expect(eilatPrice(p)).toBeNull();
    expect(regionInStock(p, "eilat")).toBe(false);
  });

  it("an Eilat stale flag carries to the copy", () => {
    const p = product("cpu:5", "CPU", {}, { offers: [offer("ivory", 500, { eilat_price: 420, eilat_in_stock: true, eilat_stale: true })] });
    expect(regionOffers(p, "eilat")[0].stale).toBe(true);
  });
});

describe("the small second price line", () => {
  const text = (h: { value: string }): string => h.value.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();

  it("regular mode shows the Eilat price", () => {
    expect(text(altPriceLine(1180, 1000, false, "main", "ILS", "he"))).toContain("באילת");
    expect(text(altPriceLine(1180, 1000, false, "main", "ILS", "he"))).toContain("1,000");
  });

  it("an Eilat-only part says so", () => {
    expect(text(altPriceLine(null, 900, true, "main", "ILS", "he"))).toContain("באילת בלבד");
  });

  it("Eilat mode shows the regular price", () => {
    const line = text(altPriceLine(1180, 1000, false, "eilat", "ILS", "en"));
    expect(line).toContain("Regular");
    expect(line).toContain("1,180");
  });

  it("nothing when there is no other price", () => {
    expect(altPriceLine(1180, null, false, "main", "ILS", "en").value).toBe("");
    expect(altPriceLine(null, 900, true, "eilat", "ILS", "en").value).toBe("");
  });

  it("not sold in Eilat keeps the regular price, muted", () => {
    const line = text(notInEilatLine(1180, "ILS", "en"));
    expect(line).toContain("Not sold in Eilat");
    expect(line).toContain("1,180");
  });
});