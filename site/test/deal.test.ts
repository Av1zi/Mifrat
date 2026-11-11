import { describe, expect, it } from "vitest";
import { dealChip } from "../src/ui/deal";
import type { Offer } from "../src/types";

function offer(extra: Partial<Offer> = {}): Offer {
  return { vendor: "ksp", url: "https://ksp.example/p", price: 1990, in_stock: true, last_seen: "2026-11-10", stale: false, ...extra };
}

describe("deal chips (owner Q1, audit 2026-11-10 P)", () => {
  it("a plain offer has none", () => {
    expect(dealChip(offer(), "ILS", "en").toString()).toBe("");
  });

  it("a clearance twin shows its price on hover, the offer price stays", () => {
    const chip = dealChip(offer({ clearance_price: 1250 }), "ILS", "en").toString();
    expect(chip).toContain("Clearance");
    expect(chip).toContain("1,250");
    expect(chip).not.toContain("1,990");
  });

  it("a new-PC deal and a clearance twin show two chips", () => {
    const chip = dealChip(offer({ new_pc_deal: true, promo_price: 1700, clearance_price: 1250 }), "ILS", "en").toString();
    expect(chip.match(/deal-chip__tip/g)?.length).toBe(2);
  });
});
