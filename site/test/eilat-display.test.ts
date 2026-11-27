import { beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../src/i18n";
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

describe("Eilat price display", () => {
  beforeEach(() => {
    region.value = "main";
  });

  it("keeps the main price and adds Eilat in the mobile buy bar", () => {
    const markup = buyBarMarkup(p, "en", "ILS").value;
    expect(markup).toContain("1,180");
    expect(markup).toContain("price-alt--eilat");
    expect(markup).toContain("1,000");
  });

  it("highlights the Eilat line in the buy box", () => {
    const markup = buyBoxMarkup(p, "he", "ILS", false, html``, p.name).value;
    expect(markup).toContain('class="price-alt__badge">באילת');
  });

  it("gives each vendor its own Eilat cell, including missing and Eilat-only prices", () => {
    const mixed = {
      ...p,
      offers: [
        { ...offer, eilat_stale: true },
        {
          ...offer,
          vendor: "ivory",
          price: 1260,
          eilat_price: undefined,
          stale: true,
        },
        {
          ...offer,
          vendor: "ksp",
          price: null,
          in_stock: false,
          eilat_price: 900,
          eilat_only: true,
        },
      ],
    };
    const markup = offersCard(mixed, "en", "ILS").value;
    const cells = Array.from(
      markup.matchAll(/<td class="col-eilat-price">([\s\S]*?)<\/td>/g),
      ([, cell]) => cell
    );
    expect(markup).toContain('<th scope="col" class="col-eilat-price">Eilat price</th>');
    expect(markup).not.toContain("price-alt--eilat");
    expect(cells).toHaveLength(3);
    expect(cells[0]).toContain("1,000");
    expect(cells[0]).toContain(t("en", "staleData"));
    expect(cells[1]).toContain(t("en", "notListed"));
    expect(cells[1]).not.toContain(t("en", "staleData"));
    expect(cells[2]).toContain("900");
    expect(cells[2]).toContain(t("en", "eilatOnlyLine"));
  });

  it("shows the regular secondary price after switching to Eilat", () => {
    region.value = "eilat";
    const markup = buyBarMarkup(p, "en", "ILS").value;
    expect(markup).toContain("Regular");
    expect(markup).toContain("1,180");
    const table = offersCard(p, "en", "ILS").value;
    expect(table).not.toContain("col-eilat-price");
    expect(table).toContain('<th scope="col">Eilat price</th>');
    expect(table).toMatch(/class="price-alt">Regular .*1,180/);
  });

  it("labels the displayed offer when its price is stale, using the active region", () => {
    const stale = {
      ...offer,
      vendor: "ksp",
      url: "https://ksp.co.il/web/item/1",
      price: 1100,
      eilat_price: 900,
      stale: true,
      eilat_stale: false,
    };
    const mixed = { ...p, offers: [offer, stale] };
    const box = () => buyBoxMarkup(mixed, "he", "ILS", false, html``, p.name).value;
    const bar = () => buyBarMarkup(mixed, "en", "ILS").value;
    expect(box()).toContain(t("he", "staleData"));
    expect(bar()).toContain(t("en", "staleData"));

    region.value = "eilat";
    expect(box()).not.toContain(t("he", "staleData"));
    expect(bar()).not.toContain(t("en", "staleData"));
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
