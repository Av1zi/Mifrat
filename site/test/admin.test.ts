import { afterEach, describe, expect, it, vi } from "vitest";
import { loadAlerts, loadChanges, loadRuns } from "../src/admin/data";
import type { OpsAbsent, OpsChanges, OpsCrawl, OpsEvent, OpsStatus } from "../src/ops/types";
import {
  calendarView,
  goneView,
  newView,
  nightKey,
  pricesView,
  tonightView,
  type Data,
  type Filters,
} from "../src/admin/views";

const NOW = new Date("2026-11-19T12:00:00Z");

afterEach(() => vi.unstubAllGlobals());

describe("admin optional data", () => {
  it("rejects incompatible change history instead of rendering a broken page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ schema: 99 })));
    await expect(loadChanges()).rejects.toThrow("schema");
  });

  it("treats invalid runs and alerts responses as unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: "unavailable" })));
    expect(await loadRuns()).toBeNull();
    expect(await loadAlerts()).toBeNull();
  });
});
const FILTERS: Filters = { vendor: "", category: "", q: "", days: 7 };

function crawl(start: string, extra: Partial<OpsCrawl> = {}): OpsCrawl {
  return {
    vendor: "ksp",
    file_day: "2026-11-19",
    start,
    end: start,
    rows: 900,
    keys: 900,
    crawls_in_file: 1,
    misfiled: false,
    outside_window: false,
    suspect: null,
    baseline: false,
    onboarding: false,
    new: 0,
    missing: 0,
    gone: 0,
    returned: 0,
    price_changes: 0,
    ...extra,
  };
}

function data(extra: Partial<Data> = {}): Data {
  const status: OpsStatus = {
    schema: 1,
    generated_at: NOW.toISOString(),
    window_days: 120,
    vendors: [
      {
        id: "ksp",
        label: "KSP",
        host: "home",
        active: true,
        min_rows: 800,
        due_utc: "04:00",
        dropped: null,
      },
    ],
    first_snapshot: {},
    crawls: { ksp: [crawl("2026-11-19T01:00:00Z")] },
    catalog: {
      generated_at: NOW.toISOString(),
      products: 1,
      listings: 1,
      skipped_vendors: [],
      review_queue: 0,
      vendors: {},
      categories: { cpu: 1 },
      qa: {},
      spec_counts: {},
    },
  };
  return { status, changes: null, checks: null, runs: null, alerts: null, ...extra };
}

function changes(events: OpsEvent[] = [], absent: OpsAbsent[] = []): OpsChanges {
  return {
    schema: 1,
    generated_at: NOW.toISOString(),
    event_days: 30,
    events,
    absent,
    dropped: {},
  };
}

function calendar(d: Data, now = NOW, month = "2026-11", day = ""): string {
  return calendarView(d, now, { month, day }).value;
}

function selectedNight(markup: string, day: string): string {
  return markup.match(new RegExp(`<a[^>]*day=${day}[^>]*>(.*?)</a>`, "s"))?.[1] ?? "";
}

describe("admin calendar", () => {
  it("groups crawls by the shared 21:00 UTC night, including late daytime starts", () => {
    expect(nightKey("2026-11-19T10:30:00Z")).toBe("2026-11-18");
    expect(nightKey("2026-08-19T09:30:00Z")).toBe("2026-08-18");
    expect(nightKey("2026-11-19T20:59:59Z")).toBe("2026-11-18");
    expect(nightKey("2026-11-19T21:00:00Z")).toBe("2026-11-19");
    expect(nightKey("2026-08-19T21:00:00Z")).toBe("2026-08-19");
  });

  it("marks the latest night missing once each vendor's deadline passes", () => {
    const d = data();
    d.status.crawls = {};
    const cell = selectedNight(calendar(d), "2026-11-18");
    expect(cell).toContain("mchip--none");
    expect(cell).not.toContain("mchip--pending");
    expect(calendar(d)).toContain("with a problem");
  });

  it("only marks vendors pending while their own deadline is still ahead", () => {
    const d = data();
    d.status.crawls = {};
    d.status.vendors.push({
      ...d.status.vendors[0],
      id: "ivory",
      label: "Ivory",
      host: "cloud",
      due_utc: "06:00",
    });
    const now = new Date("2026-11-19T05:00:00Z");
    const cell = selectedNight(calendar(d, now), "2026-11-18");
    expect(cell).toContain('mchip--none" title="KSP:');
    expect(cell).toContain('mchip--pending" title="Ivory:');
  });

  it("shows a pending deadline rather than 'Not scraped' in tonight's details", () => {
    const d = data();
    d.status.crawls = {};
    const markup = calendar(d, new Date("2026-11-19T02:00:00Z"), "2026-11", "2026-11-18");
    const detail = markup.split('id="cal-day"')[1];
    expect(detail).toContain("due 06:00");
    expect(detail).not.toContain("Not scraped");
  });

  it("does not crash or invent missing crawls for invalid/future date links", () => {
    expect(() => calendar(data(), NOW, "2026-99", "2026-11-99")).not.toThrow();
    expect(calendar(data(), NOW, "2026-99", "2026-11-99")).toContain("November 2026");
    expect(calendar(data(), NOW, "2026-11", "2026-11-30")).not.toContain('id="cal-day"');
  });
});

describe("admin change filters", () => {
  it("searches product ids, not just human-readable titles", () => {
    const d = data({
      changes: changes([
        {
          type: "new_product",
          at: NOW.toISOString(),
          pid: "model:cpu:unique-processor",
          product: "Test processor",
          category: "cpu",
          vendors: ["ksp"],
        },
      ]),
    });
    expect(newView(d, { ...FILTERS, q: "unique-processor" }, NOW).value).toContain(
      "Test processor"
    );
  });

  it("applies the period to currently missing listings by their first absence", () => {
    const absent: OpsAbsent = {
      key: "ksp:old",
      vendor: "ksp",
      state: "missing",
      title: "Old missing listing",
      url: "https://ksp.co.il/",
      price: 100,
      last_seen: "2026-11-01T01:00:00Z",
      since: "2026-11-02T01:00:00Z",
      pid: null,
      product: "",
      category: "cpu",
      product_live: false,
    };
    const d = data({
      changes: changes(
        [],
        [
          absent,
          {
            ...absent,
            key: "ksp:new",
            title: "Recent missing listing",
            since: "2026-11-19T01:00:00Z",
          },
        ]
      ),
    });
    const markup = goneView(d, { ...FILTERS, days: 1 }, NOW).value;
    expect(markup).not.toContain("Old missing listing");
    expect(markup).toContain("Recent missing listing");
  });

  it("does not show future or invalid timestamps in the selected period", () => {
    const d = data({
      changes: changes([
        {
          type: "new_product",
          at: "2026-11-20T01:00:00Z",
          pid: "future",
          product: "Future product",
          category: "cpu",
        },
      ]),
    });
    expect(newView(d, FILTERS, NOW).value).not.toContain("Future product");
  });

  it("describes the selected price period and discloses truncated tables", () => {
    const events: OpsEvent[] = Array.from({ length: 201 }, (_, i) => ({
      type: "price",
      at: "2026-11-19T01:00:00Z",
      vendor: "ksp",
      title: `Processor ${i}`,
      price: 90,
      old: 100,
    }));
    const markup = pricesView(
      data({ changes: changes(events) }),
      { ...FILTERS, days: 3 },
      NOW
    ).value;
    expect(markup).toContain("last 3 days");
    expect(markup).toContain("Showing 200 of 201");
  });
});

describe("admin open problems", () => {
  it("includes the newest Nano failure per phase and open Worker alerts", () => {
    const d = data({
      runs: [
        {
          vendor: "ksp_detail",
          at: "2026-11-19T04:00:00Z",
          ok: 0,
          outcome: "blocked",
          detail: "HTTP 403",
          items: null,
        },
        {
          vendor: "ksp",
          at: "2026-11-19T01:00:00Z",
          ok: 1,
          outcome: "ok",
          detail: null,
          items: 900,
        },
      ],
      alerts: [
        {
          key: "normalize-failed",
          severity: "high",
          title: "Normalize failed live",
          detail: "New data unpublished",
          opened_at: NOW.toISOString(),
          last_push: null,
          closed_at: null,
        },
      ],
    });
    const markup = tonightView(d, NOW).value;
    expect(markup).toContain("KSP detail blocked the scraper");
    expect(markup).toContain("Normalize failed live");
  });

  it("a later success clears historical failures, closed alerts are excluded, keys are deduplicated", () => {
    const d = data({
      runs: [
        {
          vendor: "ksp_detail",
          at: "2026-11-19T04:00:00Z",
          ok: 1,
          outcome: "ok",
          detail: null,
          items: 20,
        },
        {
          vendor: "ksp_detail",
          at: "2026-11-18T04:00:00Z",
          ok: 0,
          outcome: "blocked",
          detail: null,
          items: null,
        },
      ],
      alerts: [
        {
          key: "old",
          severity: "high",
          title: "Old resolved problem",
          detail: "",
          opened_at: "2026-11-18T04:00:00Z",
          last_push: null,
          closed_at: NOW.toISOString(),
        },
      ],
    });
    expect(tonightView(d, NOW).value).not.toContain("blocked the scraper");
    expect(tonightView(d, NOW).value).not.toContain("Old resolved problem");
    d.status.crawls = {};
    d.status.vendors[0].host = "cloud";
    d.alerts = [
      {
        key: "missing:ksp",
        severity: "high",
        title: "Live missing KSP",
        detail: "",
        opened_at: NOW.toISOString(),
        last_push: null,
        closed_at: null,
      },
    ];
    expect(tonightView(d, NOW).value.match(/class="finding finding--/g)).toHaveLength(1);
  });

  it("keeps late crawls visible on Nights and does not leak pre-night crawls into it", () => {
    const d = data();
    d.status.crawls.ksp = [
      crawl("2026-11-18T20:30:00Z", { keys: 812 }),
      crawl("2026-11-19T10:30:00Z", { keys: 913 }),
    ];
    const markup = tonightView(d, NOW).value;
    const latest =
      markup.split('aria-label="Night of Wed 18 Nov"')[1]?.split("</section>")[0] ?? "";
    expect(latest).toContain("913");
    expect(latest).not.toContain("812");
    expect(latest).not.toContain("Not scraped");
  });
});
