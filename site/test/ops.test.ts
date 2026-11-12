import { describe, expect, it } from "vitest";
import { alertMessage, dailyReport } from "../src/ops/report";
import {
  evaluate,
  expectedNight,
  israelParts,
  nightStart,
  vendorHealth,
} from "../src/ops/rules";
import type { OpsCrawl, OpsStatus, OpsVendor } from "../src/ops/types";

const VENDORS: OpsVendor[] = [
  { id: "tms", label: "TMS", host: "home", active: true, min_rows: 1800, due_utc: "04:00", dropped: null },
  { id: "onepc", label: "1PC", host: "home", active: true, min_rows: 1600, due_utc: "04:00", dropped: null },
  { id: "ksp", label: "KSP", host: "home", active: true, min_rows: 800, due_utc: "04:00", dropped: null },
  { id: "ivory", label: "Ivory", host: "cloud", active: true, min_rows: 500, due_utc: "06:00", dropped: null },
  { id: "yahav", label: "YahavPC", host: "cloud", active: true, min_rows: 800, due_utc: "06:00", dropped: null },
  { id: "plonter", label: "Plonter", host: "cloud", active: false, min_rows: 1800, due_utc: "06:00", dropped: "2026-09-29" },
];

function crawl(vendor: string, start: string, extra: Partial<OpsCrawl> = {}): OpsCrawl {
  return {
    vendor,
    file_day: start.slice(0, 10),
    start,
    end: start,
    rows: 2000,
    keys: 2000,
    crawls_in_file: 1,
    misfiled: false,
    outside_window: false,
    suspect: null,
    baseline: false,
    onboarding: false,
    new: 3,
    missing: 1,
    gone: 2,
    returned: 0,
    price_changes: 5,
    ...extra,
  };
}

function catalog(extra: Partial<OpsStatus["catalog"]> = {}): OpsStatus["catalog"] {
  return {
    generated_at: "2026-11-12T05:25:00+00:00",
    products: 4396,
    listings: 7075,
    skipped_vendors: [],
    review_queue: 1272,
    vendors: {},
    categories: {},
    qa: {},
    spec_counts: {},
    ...extra,
  };
}

/** A night where every active vendor crawled between 21:40 and 02:10 UTC. */
function status(
  crawls: Partial<Record<string, OpsCrawl[]>> = {},
  extra: Partial<OpsStatus> = {}
): OpsStatus {
  const night: Record<string, OpsCrawl[]> = {
    tms: [crawl("tms", "2026-11-11T21:40:00+00:00")],
    onepc: [crawl("onepc", "2026-11-12T00:04:00+00:00")],
    ksp: [crawl("ksp", "2026-11-12T00:56:00+00:00", { keys: 900 })],
    ivory: [crawl("ivory", "2026-11-12T02:10:00+00:00", { keys: 620 })],
    yahav: [crawl("yahav", "2026-11-12T02:09:00+00:00", { keys: 1047 })],
    plonter: [crawl("plonter", "2026-09-27T03:00:00+00:00")],
  };
  return {
    schema: 1,
    generated_at: "2026-11-12T05:30:00+00:00",
    window_days: 60,
    vendors: VENDORS,
    first_snapshot: {},
    crawls: { ...night, ...crawls } as Record<string, OpsCrawl[]>,
    catalog: catalog(),
    ...extra,
  };
}

/** 10:00 Israel time on 2026-11-12 (winter, UTC+2) = 08:00 UTC. */
const TEN_AM = new Date("2026-11-12T08:00:00Z");

describe("night window", () => {
  it("a night starts at 21:00 UTC", () => {
    expect(nightStart(new Date("2026-11-12T08:00:00Z")).toISOString()).toBe("2026-11-11T21:00:00.000Z");
    expect(nightStart(new Date("2026-11-12T22:00:00Z")).toISOString()).toBe("2026-11-12T21:00:00.000Z");
  });

  it("before a vendor's due time the previous night is the one expected", () => {
    const tms = VENDORS[0];
    // 23:00 UTC: tonight's TMS run may still be going; last night must be done.
    expect(expectedNight(tms, new Date("2026-11-12T23:00:00Z")).toISOString()).toBe(
      "2026-11-11T21:00:00.000Z"
    );
    // 05:00 UTC: tonight's run (due 04:00) must exist.
    expect(expectedNight(tms, new Date("2026-11-13T05:00:00Z")).toISOString()).toBe(
      "2026-11-12T21:00:00.000Z"
    );
  });
});

describe("vendor health", () => {
  it("a crawl since 21:00 UTC is fresh", () => {
    expect(vendorHealth(status(), VENDORS[0], TEN_AM).state).toBe("fresh");
  });

  it("judges by crawl time, not file name: TMS in the 11-11 file is last night's", () => {
    const s = status({
      tms: [
        crawl("tms", "2026-11-10T22:23:00+00:00", { file_day: "2026-11-11", misfiled: true, crawls_in_file: 2 }),
        crawl("tms", "2026-11-11T21:30:00+00:00", { file_day: "2026-11-11", crawls_in_file: 2 }),
      ],
    });
    const h = vendorHealth(s, VENDORS[0], TEN_AM);
    expect(h.state).toBe("fresh");
    expect(h.notes.join(" ")).toContain("2 crawls in one file");
  });

  it("no crawl since the night began, after the due time, is missing", () => {
    const s = status({ ksp: [crawl("ksp", "2026-11-07T20:12:00+00:00", { keys: 923 })] });
    expect(vendorHealth(s, VENDORS[2], TEN_AM).state).toBe("missing");
  });

  it("before the due time tonight's crawl is only late", () => {
    const s = status();
    // 2026-11-12 23:30 UTC: tonight's night began 21:00; TMS due 04:00.
    const h = vendorHealth(s, VENDORS[0], new Date("2026-11-12T23:30:00Z"));
    // Last night's crawl exists, so the expected night is last night: fresh.
    expect(h.state).toBe("fresh");
  });

  it("a suspect crawl is partial", () => {
    const s = status({ onepc: [crawl("onepc", "2026-11-12T00:04:00+00:00", { suspect: "900 items, floor 1600" })] });
    expect(vendorHealth(s, VENDORS[1], TEN_AM).state).toBe("partial");
  });

  it("a dropped vendor is never missing", () => {
    expect(vendorHealth(status(), VENDORS[5], TEN_AM).state).toBe("dropped");
  });
});

describe("findings", () => {
  it("a healthy night has none", () => {
    expect(evaluate(status(), TEN_AM)).toEqual([]);
  });

  it("all home vendors missing is one Nano finding, not three", () => {
    const old = "2026-11-09T22:00:00+00:00";
    const s = status({
      tms: [crawl("tms", old)],
      onepc: [crawl("onepc", old)],
      ksp: [crawl("ksp", old, { keys: 900 })],
    });
    const keys = evaluate(s, TEN_AM).map((f) => f.key);
    expect(keys).toEqual(["nano-down"]);
  });

  it("one missing vendor is its own finding", () => {
    const s = status({ ksp: [crawl("ksp", "2026-11-07T20:12:00+00:00", { keys: 923 })] });
    const f = evaluate(s, TEN_AM);
    expect(f.map((x) => x.key)).toEqual(["missing:ksp"]);
    expect(f[0].severity).toBe("high");
    // 11-07 20:12 -> 11-12 08:00 UTC is 4.5 days.
    expect(f[0].detail).toContain("4 days ago (923 items)");
  });

  it("a stale report is a finding (a dead pipeline cannot look healthy)", () => {
    const s = status({}, { generated_at: "2026-11-10T05:30:00+00:00" });
    expect(evaluate(s, TEN_AM).map((f) => f.key)).toContain("report-stale");
  });

  it("a blocked Nano run is urgent", () => {
    const f = evaluate(status(), TEN_AM, {
      nanoRuns: { ksp: { vendor: "ksp", at: "2026-11-12T01:00:00Z", ok: false, outcome: "blocked", detail: "HTTP 403" } },
    });
    expect(f[0]).toMatchObject({ key: "blocked:ksp", severity: "urgent" });
  });

  it("site down and API flood are urgent; deploy lag is high", () => {
    const keys = evaluate(status(), TEN_AM, {
      siteOk: false,
      abuseHits: 500,
      deployedCatalogAt: "2026-11-11T05:25:00+00:00",
    }).map((f) => `${f.severity}:${f.key}`);
    expect(keys).toEqual(["urgent:abuse", "urgent:site-down", "high:deploy-behind"]);
  });

  it("a double crawl and a delisting spike warn", () => {
    const s = status({
      ivory: [crawl("ivory", "2026-11-12T02:10:00+00:00", { keys: 600, gone: 40, crawls_in_file: 2 })],
    });
    const keys = evaluate(s, TEN_AM).map((f) => f.key);
    expect(keys).toEqual(["delist-spike:ivory:2026-11-12", "double:ivory:2026-11-12"]);
  });

  it("a skipped active vendor is high", () => {
    const s = status({}, { catalog: catalog({ skipped_vendors: ["yahav", "plonter"] }) });
    expect(evaluate(s, TEN_AM).map((f) => f.key)).toContain("skipped:yahav");
  });
});

describe("daily report", () => {
  it("all OK is silent (priority 2)", () => {
    const msg = dailyReport(status(), [], TEN_AM);
    expect(msg.priority).toBe(2);
    expect(msg.title).toContain("all OK");
    expect(msg.message.split("\n").filter((l) => l.startsWith("✅"))).toHaveLength(5);
    expect(msg.message).not.toContain("Plonter");
  });

  it("a late cloud start (GitHub cron delay) stays silent but is shown", () => {
    const s = status({
      ivory: [crawl("ivory", "2026-11-12T05:10:00+00:00", { keys: 623, outside_window: true })],
    });
    const msg = dailyReport(s, evaluate(s, TEN_AM), TEN_AM);
    expect(msg.priority).toBe(2);
    expect(msg.message).toContain("✅ Ivory");
    expect(msg.message).toContain("late start");
  });

  it("a double crawl is not OK", () => {
    const s = status({
      tms: [crawl("tms", "2026-11-11T21:30:00+00:00", { crawls_in_file: 2, file_day: "2026-11-11" })],
    });
    const msg = dailyReport(s, evaluate(s, TEN_AM), TEN_AM);
    expect(msg.priority).toBe(3);
    expect(msg.message).toContain("⚠️ TMS");
  });

  it("a missing vendor buzzes (priority 3) and names its last crawl", () => {
    const s = status({ ksp: [crawl("ksp", "2026-11-07T20:12:00+00:00", { keys: 923 })] });
    const msg = dailyReport(s, evaluate(s, TEN_AM), TEN_AM);
    expect(msg.priority).toBe(3);
    expect(msg.message).toContain("❌ KSP");
    expect(msg.message).toContain("last 11-07 22:12 (923)");
  });

  it("shows Israel time, DST-correct", () => {
    // 2026-08-12 is summer (UTC+3): a 21:30 UTC crawl reads 00:30.
    const summer = status({ tms: [crawl("tms", "2026-08-11T21:30:00+00:00")] }, { generated_at: "2026-08-12T05:00:00+00:00" });
    const msg = dailyReport(summer, [], new Date("2026-08-12T07:00:00Z"));
    expect(msg.message).toContain("00:30");
  });

  it("stays under ntfy's message cap", () => {
    const many = Array.from({ length: 400 }, (_, i) => ({
      key: `x${i}`, severity: "warn" as const, title: "a long problem title ".repeat(4), detail: "",
    }));
    expect(dailyReport(status(), many, TEN_AM).message.length).toBeLessThanOrEqual(3500);
  });
});

describe("alerts", () => {
  it("maps severity to ntfy priority", () => {
    const f = { key: "k", severity: "urgent" as const, title: "Site is down", detail: "x" };
    expect(alertMessage(f, "open").priority).toBe(5);
    expect(alertMessage({ ...f, severity: "high" }, "open").priority).toBe(4);
    expect(alertMessage(f, "remind").title).toBe("Still open: Site is down");
    expect(alertMessage(f, "resolved")).toMatchObject({ priority: 2, title: "Resolved: Site is down" });
  });
});

describe("Israel clock", () => {
  it("10:00 Israel is 08:00 UTC in winter and 07:00 UTC in summer", () => {
    expect(israelParts(new Date("2026-11-12T08:00:00Z")).hour).toBe(10);
    expect(israelParts(new Date("2026-11-12T07:00:00Z")).hour).toBe(9);
    expect(israelParts(new Date("2026-07-12T07:00:00Z")).hour).toBe(10);
    expect(israelParts(new Date("2026-07-12T08:00:00Z")).hour).toBe(11);
  });
});
