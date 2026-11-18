import { describe, expect, it } from "vitest";
import schedule from "../../scraper/ksp_schedule.json";
import { kspNotice } from "../src/ui/vendorNotice";

describe("KSP temporary notice", () => {
  it("shows both languages while KSP is paused", () => {
    expect(kspNotice("en").value).toContain("temporarily paused");
    expect(kspNotice("he").value).toContain("מופסקים זמנית");
  });
  it("does not disappear just because the planned restart date elapsed", () => {
    expect(kspNotice("en", "2026-11-16T01:00:00Z").value).toContain("temporarily paused");
    expect(kspNotice("en", "invalid").value).toContain("temporarily paused");
  });
  it("clears only when a KSP crawl after the restart is published", () => {
    expect(kspNotice("en", schedule.resume_after).value).toBe("");
  });
  it("does not promise a past restart date after a failed attempt", () => {
    const notice = kspNotice("en", undefined, new Date("2026-11-23T10:00:00Z")).value;
    expect(notice).toContain("after a successful restart");
    expect(notice).not.toContain("planned for");
  });
});
