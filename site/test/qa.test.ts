import { describe, expect, it } from "vitest";
import { openQaCases } from "../src/qaCases";
import type { QaCase } from "../src/types";

function qaCase(extra: Partial<QaCase> = {}): QaCase {
  return {
    kind: "spec_conflict",
    product_id: "p",
    category: "memory",
    vendor: "",
    field: "cas_latency",
    kept: 30,
    dropped: 32,
    offers: [],
    ...extra,
  };
}

describe("open QA cases", () => {
  it("does not present an effective override as unresolved work", () => {
    const fixed = qaCase({ fixed: true });
    const open = qaCase({ product_id: "open" });
    expect(openQaCases([fixed, open])).toEqual([open]);
  });

  it("preserves dismissed history without displaying it", () => {
    const cases = [qaCase({ dismissed: true }), qaCase()];
    expect(openQaCases(cases)).toEqual([cases[1]]);
    expect(cases).toHaveLength(2);
  });

  it("keeps an unapplied or reopened correction visible", () => {
    const open = qaCase({ fixed: false, dismissed: false });
    expect(openQaCases([open])).toEqual([open]);
  });

  it("excludes current proof resolutions but keeps shadow and reopened cases", () => {
    const resolved = qaCase({ auto_resolved: true });
    const shadow = qaCase({
      resolution: {
        state: "shadow",
        reason: "exact_manufacturer_spec",
        rule: "manufacturer_fan_performance",
      },
    });
    const reopened = qaCase({ auto_resolved: false });
    expect(openQaCases([resolved, shadow, reopened])).toEqual([shadow, reopened]);
  });
});
