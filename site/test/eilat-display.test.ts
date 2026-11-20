import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Offer, Region } from "../src/types";
import { product } from "./fixtures";
import { html } from "../src/ui/html";
import { buyBarMarkup, buyBoxMarkup, offersCard } from "../src/views/product/buybox";
import { similarMarkup } from "../src/views/product/similar";

const region = vi.hoisted(() => ({ value: "main" as Region }));
vi.mock("../src/state", async (original) => ({
  ...(await original<object>()),
  getRegion: () => region.value,
}));

const offer: Offer = {
  vendor: "tms",
  url: "https://tms.co.il/example",
  price: 1180,
  eilat_price: 1000,
  eilat_in_stock: true,
  in_stock: true,
  stale: false,
  last_seen: "2026-11-20",
};
const p = product(
  "cpu:test",
  "Test CPU",
  {},
  {
    category: "cpu",
    min_price: 1180,
    eilat_min_price: 1000,
    offers: [offer],
  }
);

describe("small Eilat prices without switching region", () => {
  beforeEach(() => {
    region.value = "main";
  });

  it("keeps the main price and adds Eilat in the mobile buy bar", () => {
    const markup = buyBarMarkup(p, "en", "ILS").value;
    expect(markup).toContain("1,180");
    expect(markup).toContain("price-alt--eilat");
    expect(markup).toContain("1,000");
  });

  it("keeps the existing Eilat line in the buy box and offer rows", () => {
    expect(buyBoxMarkup(p, "he", "ILS", false, html``, p.name).value).toContain("באילת");
    expect(offersCard(p, "en", "ILS").value).toContain("price-alt--eilat");
  });

  it("shows the regular secondary price after switching to Eilat", () => {
    region.value = "eilat";
    const markup = buyBarMarkup(p, "en", "ILS").value;
    expect(markup).toContain("Regular");
    expect(markup).toContain("1,180");
  });

  it("does not invent an Eilat price when none was scraped", () => {
    const absent = product(
      "cpu:none",
      "No Eilat",
      {},
      {
        offers: [{ ...offer, eilat_price: undefined }],
      }
    );
    expect(buyBarMarkup(absent, "en", "ILS").value).not.toContain("price-alt--eilat");
  });

  it("includes Eilat prices on similar product cards", () => {
    const base = product(
      "cpu:base",
      "Base CPU",
      { socket: "AM5" },
      { brand: "AMD", category: "cpu" }
    );
    const other = product(
      "cpu:other",
      "Other CPU",
      { socket: "AM5" },
      {
        brand: "AMD",
        category: "cpu",
        offers: [offer],
        min_price: 1180,
        eilat_min_price: 1000,
      }
    );
    expect(similarMarkup(base, [base, other], "en", "ILS", () => false)?.value).toContain(
      "price-alt--eilat"
    );
  });
});
