import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BuilderCtx } from "../src/views/builder/parts";
import type { BuildMap } from "../src/state";

// Regression tests for the browser findings of the 2026-11-10 security audit
// (B-1..B-6). Every module under test keeps session state, so each test
// re-imports it after vi.resetModules() and stubs the browser globals it reads.

const ORIGIN = "https://mifrat.test";
const STUBBED = ["window", "localStorage", "location", "history", "document", "fetch"];
const saved = new Map<string, PropertyDescriptor | undefined>();

function setGlobal(key: string, value: unknown): void {
  // Node 22+ ships accessor-only `localStorage`/`location` globals: always redefine.
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}

beforeEach(() => {
  for (const key of STUBBED) saved.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  vi.resetModules();
});

afterEach(() => {
  vi.useRealTimers();
  for (const key of STUBBED) {
    const original = saved.get(key);
    if (original) Object.defineProperty(globalThis, key, original);
    else Reflect.deleteProperty(globalThis, key);
  }
});

function memStorage(seed: Record<string, string> = {}): Storage {
  const m = new Map(Object.entries(seed));
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k: string) => m.get(k) ?? null,
    key: (i: number) => [...m.keys()][i] ?? null,
    removeItem: (k: string) => void m.delete(k),
    setItem: (k: string, v: string) => void m.set(k, String(v)),
  };
}

interface Sent {
  method: string;
  url: string;
  headers: unknown;
  body: unknown;
}

interface Env {
  storage: Storage;
  location: { hash: string; pathname: string; origin: string; host: string; search: string };
  /** history.replaceState targets, in call order. */
  replaced: string[];
  requests: Sent[];
}

function install(
  opts: {
    storage?: Storage;
    pathname?: string;
    hash?: string;
    files?: Record<string, unknown>;
  } = {}
): Env {
  const files = opts.files ?? {};
  const env: Env = {
    storage: opts.storage ?? memStorage(),
    location: {
      hash: opts.hash ?? "",
      pathname: opts.pathname ?? "/",
      origin: ORIGIN,
      host: "mifrat.test",
      search: "",
    },
    replaced: [],
    requests: [],
  };
  // Delegates at call time so vi.useFakeTimers() also drives window timers.
  setGlobal("window", {
    setTimeout: (fn: () => void, ms?: number) => globalThis.setTimeout(fn, ms),
    clearTimeout: (id?: number) => globalThis.clearTimeout(id),
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => true,
    scrollTo() {},
  });
  setGlobal("localStorage", env.storage);
  setGlobal("location", env.location);
  setGlobal("history", {
    replaceState: (_state: unknown, _title: string, url: string) => {
      env.replaced.push(url);
      const next = new URL(url, `${ORIGIN}${env.location.pathname}`);
      env.location.pathname = next.pathname;
      env.location.hash = next.hash;
    },
  });
  setGlobal("document", {
    activeElement: null,
    documentElement: { lang: "en", dataset: {} },
    body: { classList: { toggle() {} } },
    getElementById: () => null,
    addEventListener() {},
    removeEventListener() {},
  });
  setGlobal("fetch", async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    env.requests.push({ method, url, headers: init?.headers, body: init?.body });
    const reply = (status: number, body: unknown) => ({
      ok: status < 400,
      status,
      statusText: "",
      json: async () => structuredClone(body),
    });
    if (method === "POST" && url === "/api/lists")
      return reply(200, { id: `n${env.requests.length}w123`.slice(0, 6) });
    if (url in files) return reply(200, files[url]);
    return reply(404, { error: "not found" });
  });
  return env;
}

interface FakeEl {
  innerHTML: string;
  hidden: boolean;
  id: string;
  clientWidth: number;
  style: Record<string, string>;
  parentElement: { clientWidth: number };
  contains(): boolean;
  querySelector(selector: string): FakeEl | null;
  querySelectorAll(): FakeEl[];
  addEventListener(): void;
  setAttribute(): void;
  focus(): void;
  getBoundingClientRect(): { left: number; top: number; width: number; height: number };
}

/** Records innerHTML; with `children`, hands out one child fake per selector. */
function fakeEl(children = false): FakeEl {
  const kids = new Map<string, FakeEl>();
  return {
    innerHTML: "",
    hidden: true,
    id: "",
    clientWidth: 900,
    style: {},
    parentElement: { clientWidth: 940 },
    contains: () => false,
    querySelector(selector: string) {
      if (!children) return null;
      if (!kids.has(selector)) kids.set(selector, fakeEl(true));
      return kids.get(selector) ?? null;
    },
    querySelectorAll: () => [],
    addEventListener() {},
    setAttribute() {},
    focus() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 300 }),
  };
}

function builderCtx(build: BuildMap, extra: Partial<BuilderCtx> = {}): BuilderCtx {
  return {
    container: fakeEl() as unknown as HTMLElement,
    lang: "en",
    currency: "ILS",
    build,
    parts: new Map(),
    activeListId: null,
    ownDraft: true,
    share: { pendingKey: null, timer: undefined },
    ...extra,
  };
}

const DRAFT = JSON.stringify({ cpu: ["cpu:mine"] });
const CATALOG = {
  "/data/site/cpu.json": [
    { id: "cpu:mine", category: "cpu", name: "Mine", brand: null, offers: [] },
    { id: "cpu:theirs", category: "cpu", name: "Theirs", brand: null, offers: [] },
  ],
  "/data/site/gpu.json": [
    { id: "gpu:theirs", category: "gpu", name: "Card", brand: null, offers: [] },
  ],
};

describe("B-1: opening a shared build never writes the visitor's draft", () => {
  it("refreshParts on a shared build leaves mifrat:build and the address bar alone", async () => {
    const env = install({
      storage: memStorage({ "mifrat:build": DRAFT }),
      pathname: "/list/aB3xQ9",
      files: CATALOG,
    });
    const { cleanBuild, refreshParts } = await import("../src/views/builder/parts");
    const ctx = builderCtx(cleanBuild({ cpu: ["cpu:theirs"] }), {
      activeListId: "aB3xQ9",
      ownDraft: false,
    });
    await refreshParts(ctx);
    expect(ctx.parts.get("cpu")?.[0]?.id).toBe("cpu:theirs");
    expect(env.storage.getItem("mifrat:build")).toBe(DRAFT);
    expect(env.replaced).toEqual([]);
  });

  it("the first edit makes it the visitor's draft and leaves the /list path; later refreshes persist", async () => {
    const env = install({
      storage: memStorage({ "mifrat:build": DRAFT }),
      pathname: "/list/aB3xQ9",
      files: CATALOG,
    });
    const { cleanBuild, persist, refreshParts } = await import("../src/views/builder/parts");
    const { removeFromBuild } = await import("../src/state");
    const ctx = builderCtx(cleanBuild({ cpu: ["cpu:theirs"], gpu: ["gpu:theirs"] }), {
      activeListId: "aB3xQ9",
      ownDraft: false,
    });
    await refreshParts(ctx);

    removeFromBuild(ctx.build, "gpu", "gpu:theirs");
    persist(ctx);
    expect(JSON.parse(env.storage.getItem("mifrat:build") ?? "null")).toEqual({
      cpu: ["cpu:theirs"],
    });
    expect(env.replaced).toEqual(["/#/build?cpu=cpu%3Atheirs"]);
    expect(env.location.pathname).toBe("/");
    expect(ctx.ownDraft).toBe(true);
    expect(ctx.activeListId).toBeNull();

    env.storage.removeItem("mifrat:build");
    await refreshParts(ctx);
    expect(JSON.parse(env.storage.getItem("mifrat:build") ?? "null")).toEqual({
      cpu: ["cpu:theirs"],
    });
  });

  it("the stored draft still prunes stale ids on open", async () => {
    const env = install({
      storage: memStorage({
        "mifrat:build": JSON.stringify({ cpu: ["cpu:gone"], gpu: ["gpu:theirs"] }),
      }),
      files: CATALOG,
    });
    const { cleanBuild, refreshParts } = await import("../src/views/builder/parts");
    const { getStoredBuild } = await import("../src/state");
    const ctx = builderCtx(cleanBuild(getStoredBuild()));
    await refreshParts(ctx);
    expect(JSON.parse(env.storage.getItem("mifrat:build") ?? "null")).toEqual({
      gpu: ["gpu:theirs"],
    });
  });

  it("legacy #/build? links are view-only too", async () => {
    const env = install({
      storage: memStorage({ "mifrat:build": DRAFT }),
      hash: "#/build?cpu=cpu:theirs",
      files: CATALOG,
    });
    vi.useFakeTimers();
    const { renderBuilder } = await import("../src/views/builder");
    const { parseRoute } = await import("../src/state");
    const route = parseRoute();
    if (route.view !== "build") throw new Error(`unexpected route ${route.view}`);
    const container = fakeEl();
    await renderBuilder(
      container as unknown as HTMLElement,
      "en",
      "ILS",
      route.shared,
      route.listId
    );
    expect(container.innerHTML).toContain("Theirs");
    expect(env.storage.getItem("mifrat:build")).toBe(DRAFT);
    expect(env.replaced).toEqual([]);
  });

  it("a /list link renders without touching the draft and reuses its own short link (no POST)", async () => {
    const env = install({
      storage: memStorage({ "mifrat:build": DRAFT }),
      pathname: "/list/aB3xQ9",
      files: { ...CATALOG, "/api/lists/aB3xQ9": { build: { cpu: ["cpu:theirs"] } } },
    });
    vi.useFakeTimers();
    const { renderListRoute } = await import("../src/views/builder");
    const container = fakeEl();
    await renderListRoute(container as unknown as HTMLElement, "en", "ILS", "aB3xQ9");
    await vi.advanceTimersByTimeAsync(2000);
    expect(container.innerHTML).toContain(`value="${ORIGIN}/list/aB3xQ9"`);
    expect(env.storage.getItem("mifrat:build")).toBe(DRAFT);
    expect(env.replaced).toEqual([]);
    expect(env.requests.filter((r) => r.method === "POST")).toEqual([]);
  });

  it("a slot pick started from a shared build applies to it, not to the draft", async () => {
    const env = install({ storage: memStorage({ "mifrat:build": DRAFT }) });
    const state = await import("../src/state");
    const { BUILD_SLOTS } = await import("../src/build");
    const { addPickedPart } = await import("../src/views/category/picker");

    state.setOpenSharedBuild({ cpu: ["cpu:theirs"] });
    const base = state.getPickBaseBuild();
    base.cpu?.push("cpu:extra");
    expect(state.getPickBaseBuild()).toEqual({ cpu: ["cpu:theirs"] });
    expect(env.storage.getItem("mifrat:build")).toBe(DRAFT);

    const ctx = {
      pickSlot: BUILD_SLOTS.find((s) => s.id === "gpu"),
      container: fakeEl(),
      lang: "en",
    };
    addPickedPart(ctx as never, { id: "gpu:theirs", category: "gpu" } as never);
    expect(JSON.parse(env.storage.getItem("mifrat:build") ?? "null")).toEqual({
      cpu: ["cpu:theirs"],
      gpu: ["gpu:theirs"],
    });
    expect(env.location.hash).toBe("#/build?cpu=cpu%3Atheirs&gpu=gpu%3Atheirs");
    // Once the draft is written, picks are based on it again.
    expect(state.getPickBaseBuild()).toEqual({ cpu: ["cpu:theirs"], gpu: ["gpu:theirs"] });
  });
});

describe("B-2: price-history SVG sink", () => {
  it("escapes hostile date labels", async () => {
    install({
      files: {
        "/data/site/history/cpu.json": {
          dates: [`<a href="//evil.example">x</a>`, "2026-11-01", "<foreignObject>"],
          timestamps: [],
          "cpu:x": { v: { tms: [100, 120, 110] } },
        },
      },
    });
    const { renderPriceHistory } = await import("../src/views/product/history");
    const host = fakeEl(true);
    await renderPriceHistory(host as unknown as HTMLElement, "en", "ILS", "cpu", "cpu:x");
    const svg = host.querySelector(".ph-chart")?.innerHTML ?? "";
    expect(svg).toContain("ph-line");
    expect(svg).not.toContain("<a ");
    expect(svg).not.toContain("<foreignObject>");
    expect(svg).toContain("&lt;foreignObject&gt;");
  });

  it("non-string dates still draw the chart", async () => {
    install({
      files: {
        "/data/site/history/gpu.json": {
          dates: [{}, "x", 7],
          timestamps: [],
          "gpu:y": { v: { tms: [1, 2, 3] } },
        },
      },
    });
    const { renderPriceHistory } = await import("../src/views/product/history");
    const host = fakeEl(true);
    await expect(
      renderPriceHistory(host as unknown as HTMLElement, "en", "ILS", "gpu", "gpu:y")
    ).resolves.toBeUndefined();
    expect(host.querySelector(".ph-chart")?.innerHTML).toContain("ph-line");
  });
});

describe("B-3: blocked or full site storage", () => {
  function blockStorage(): void {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Access is denied for this document.", "SecurityError");
      },
    });
  }

  it("state getters fall back instead of throwing, and writes last the session", async () => {
    install();
    blockStorage();
    const state = await import("../src/state");
    const storage = await import("../src/storage");
    expect(state.getLang()).toBe("he");
    expect(state.getCurrency()).toBe("ILS");
    expect(state.getListView()).toBe("table");
    expect(state.getStoredBuild()).toEqual({});
    expect(storage.readJson("mifrat:saved", [])).toEqual([]);

    state.setLang("en");
    state.setStoredBuild({ cpu: ["cpu:a"] });
    storage.writeJson("mifrat:saved", [{ id: "a" }]);
    expect(state.getLang()).toBe("en");
    expect(state.getStoredBuild()).toEqual({ cpu: ["cpu:a"] });
    expect(storage.readJson("mifrat:saved", [])).toEqual([{ id: "a" }]);
  });

  it("the FX rate still loads, and an out-of-range cached rate is ignored", async () => {
    const endpoint = "https://api.frankfurter.dev/v1/latest?base=ILS&symbols=USD";
    const env = install({ files: { [endpoint]: { rates: { USD: 0.25 } } } });
    blockStorage();
    const fx = await import("../src/format");
    await fx.ensureFxRate();
    expect(fx.formatPrice(400, "USD", "en")).toBe("$100");

    vi.resetModules();
    const today = new Date().toISOString().slice(0, 10);
    setGlobal(
      "localStorage",
      memStorage({ "mifrat:fx:ils-usd": `{"date":"${today}","rate":1e400}` })
    );
    const fresh = await import("../src/format");
    await fresh.ensureFxRate();
    expect(fresh.formatPrice(400, "USD", "en")).toBe("$100");
    expect(env.requests.filter((r) => r.url === endpoint)).toHaveLength(2);
  });

  it("a failed write is kept in memory only until storage works again", async () => {
    const backing = memStorage();
    let full = true;
    const quota = {
      ...backing,
      getItem: (k: string) => backing.getItem(k),
      setItem: (k: string, v: string) => {
        if (full) throw new DOMException("full", "QuotaExceededError");
        backing.setItem(k, v);
      },
    } as Storage;
    install({ storage: quota });
    const storage = await import("../src/storage");
    storage.writeItem("mifrat:view", "cards");
    expect(storage.readItem("mifrat:view")).toBe("cards");
    full = false;
    storage.writeItem("mifrat:view", "table");
    // Another tab writes: this tab must see it, not a stale memory copy.
    backing.setItem("mifrat:view", "cards");
    expect(storage.readItem("mifrat:view")).toBe("cards");
  });
});

describe("B-4: stored part refs are fully typed", () => {
  it("drops compare entries whose brand or thumb is not text", async () => {
    install({
      storage: memStorage({
        "mifrat:compare": JSON.stringify({
          category: "cpu",
          items: [
            { id: "cpu:a", category: "cpu", name: "A", brand: 5 },
            { id: "cpu:b", category: "cpu", name: "B", thumb: {} },
            { id: "cpu:c", category: "cpu", name: "C", brand: "AMD", thumb: null },
            { id: "cpu:d", category: "cpu", name: "D" },
          ],
        }),
      }),
    });
    const { getCompare } = await import("../src/compare");
    const { initialsOf } = await import("../src/ui/thumb");
    const items = getCompare().items;
    expect(items.map((p) => p.id)).toEqual(["cpu:c", "cpu:d"]);
    for (const p of items) expect(() => initialsOf(p.brand, p.name)).not.toThrow();
  });
});

describe("B-6: short links are created once per build", () => {
  const posts = (env: Env): Sent[] => env.requests.filter((r) => r.method === "POST");

  it("re-rendering the same build (any key order) POSTs once, as same-origin JSON", async () => {
    const env = install();
    vi.useFakeTimers();
    const { bindShare } = await import("../src/views/builder/share");
    bindShare(builderCtx({ cpu: ["cpu:a"], gpu: ["gpu:b"] }));
    await vi.advanceTimersByTimeAsync(1000);
    const again = builderCtx({ gpu: ["gpu:b"], cpu: ["cpu:a"] });
    bindShare(again);
    bindShare(again);
    await vi.advanceTimersByTimeAsync(1000);
    expect(posts(env)).toHaveLength(1);
    expect(posts(env)[0]).toMatchObject({
      url: "/api/lists",
      headers: { "content-type": "application/json" },
    });

    bindShare(builderCtx({ cpu: ["cpu:a"] }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(posts(env)).toHaveLength(2);
  });

  it("a page re-entered while the first POST is pending joins it", async () => {
    const env = install();
    vi.useFakeTimers();
    const { bindShare } = await import("../src/views/builder/share");
    bindShare(builderCtx({ cpu: ["cpu:a"] }));
    bindShare(builderCtx({ cpu: ["cpu:a"] }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(posts(env)).toHaveLength(1);
  });

  it("an empty build never POSTs", async () => {
    const env = install();
    vi.useFakeTimers();
    const { bindShare } = await import("../src/views/builder/share");
    bindShare(builderCtx({}));
    await vi.advanceTimersByTimeAsync(1000);
    expect(posts(env)).toEqual([]);
  });

  it("a build opened from its short link is not POSTed again", async () => {
    const env = install();
    vi.useFakeTimers();
    const { bindShare, rememberShortLink } = await import("../src/views/builder/share");
    rememberShortLink({ cpu: ["cpu:a"] }, "aB3xQ9");
    bindShare(builderCtx({ cpu: ["cpu:a", "cpu:a"] }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(posts(env)).toEqual([]);
  });
});
