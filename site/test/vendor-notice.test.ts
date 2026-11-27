import { describe, expect, it } from "vitest";
import schedule from "../../scraper/ksp_schedule.json";
import { kspNotice } from "../src/ui/vendorNotice";

describe("KSP temporary notice", () => {
  it("shows both languages while KSP is paused", () => {
    expect(kspNotice("en").value).toContain("temporarily paused");
    expect(kspNotice("he").value).toContain("מופסקים זמנית");
  });
  it("does not disappear just because the planned restart date elapsed", () => {
    expect(
      kspNotice("en", { vendor_updated_at: { ksp: "2026-11-16T01:00:00Z" }, skipped_vendors: [] })
        .value
    ).toContain("Last price update: 16 Nov");
    expect(
      kspNotice("en", { vendor_updated_at: { ksp: "invalid" }, skipped_vendors: [] }).value
    ).toContain("temporarily paused");
  });
  it("clears only when a KSP crawl after the restart is published", () => {
    expect(
      kspNotice("en", { vendor_updated_at: { ksp: schedule.resume_after }, skipped_vendors: [] })
        .value
    ).toBe("");
  });
  it("says prices are unavailable once the catalog stops carrying them", () => {
    const meta = { skipped_vendors: ["ksp"] };
    expect(kspNotice("en", meta).value).toContain("KSP prices are currently unavailable.");
    expect(kspNotice("he", meta).value).toContain("מחירי KSP אינם זמינים כרגע.");
  });
  it("does not promise a past restart date after a failed attempt", () => {
    const notice = kspNotice("en", undefined, new Date("2026-11-23T10:00:00Z")).value;
    expect(notice).toContain("temporarily paused");
    expect(notice).not.toContain("planned for");
  });
});
