import { afterEach, describe, expect, it } from "vitest";
import {
  addToBuild,
  buildHash,
  buildItemCount,
  categoryHash,
  parseRoute,
  productHash,
  removeFromBuild,
} from "../src/state";

/** parseRoute reads the `location` global; the node environment has none. */
function at(url: string): void {
  const u = new URL(url, "https://mifrat.test");
  Object.defineProperty(globalThis, "location", {
    value: { hash: u.hash, pathname: u.pathname, search: u.search },
    configurable: true,
    writable: true,
  });
}

afterEach(() => {
  Reflect.deleteProperty(globalThis, "location");
});

describe("parseRoute: static pages", () => {
  it.each([
    ["/", "home"],
    ["/#/", "home"],
    ["/#", "home"],
    ["/#/categories", "categories"],
    ["/#/categories/", "categories"],
    ["/#/privacy", "privacy"],
    ["/#/terms/", "terms"],
    ["/#/cookies", "cookies"],
    ["/#/qa", "qa"],
    ["/#/no/such/page", "notfound"],
  ])("%s -> %s", (url, view) => {
    at(url);
    expect(parseRoute().view).toBe(view);
  });
});

describe("parseRoute: builder", () => {
  it("returns an empty (non-shared) build for a bare #/build", () => {
    at("/#/build");
    expect(parseRoute()).toEqual({ view: "build", shared: null, listId: null });
  });

  it("parses legacy #/build?slot=id links, including repeated multi-slot params", () => {
    at("/#/build?cpu=mpn%3Acpu%3Aa&memory=m1&memory=m2&storage=");
    expect(parseRoute()).toEqual({
      view: "build",
      shared: { cpu: ["mpn:cpu:a"], memory: ["m1", "m2"] },
      listId: null,
    });
  });

  it("round-trips buildHash through parseRoute", () => {
    const build = { cpu: ["mpn:cpu:a b"], memory: ["x", "y"] };
    at("/" + buildHash(build));
    expect(parseRoute()).toMatchObject({ view: "build", shared: build });
  });

  it("resolves /list/<id> short links when there is no hash route", () => {
    at("/list/aB3!xQ9");
    expect(parseRoute()).toEqual({ view: "build", shared: null, listId: "aB3!xQ9" });
    at("/list/aB3!xQ9/");
    expect(parseRoute()).toMatchObject({ listId: "aB3!xQ9" });
  });

  it("decodes percent-escaped list ids and survives malformed escapes", () => {
    at("/list/ab%26cd");
    expect(parseRoute()).toMatchObject({ view: "build", listId: "ab&cd" });
    at("/list/ab%ZZcd");
    expect(parseRoute()).toMatchObject({ view: "build", listId: "ab%ZZcd" });
  });

  it("lets a hash route win over the /list path", () => {
    at("/list/aB3!xQ9#/c/cpu");
    expect(parseRoute().view).toBe("category");
    at("/list/aB3!xQ9#/build?cpu=a");
    expect(parseRoute()).toMatchObject({ view: "build", listId: null, shared: { cpu: ["a"] } });
  });

  it("does not treat other paths as share links (empty hash is home)", () => {
    at("/list/a/b");
    expect(parseRoute().view).toBe("home");
    at("/random/path");
    expect(parseRoute().view).toBe("home");
  });
});

describe("parseRoute: category and product", () => {
  it("parses a plain category with defaults", () => {
    at("/#/c/cpu");
    expect(parseRoute()).toEqual({
      view: "category",
      category: "cpu",
      params: {
        q: "",
        sort: "price_asc",
        stockOnly: false,
        filters: {},
        ranges: {},
        productId: null,
        pick: null,
      },
    });
  });

  it("parses search, sort, stock, pick, filters and ranges", () => {
    at(
      "/#/c/motherboard?q=asus&sort=price_desc&stock=1&pick=motherboard&f.socket=AM5%7CLGA1700&r.price=100%2C500&r.weight=%2C9&r.bad=x%2Cy&p=abc"
    );
    const route = parseRoute();
    expect(route.view).toBe("category");
    if (route.view !== "category") return;
    expect(route.params).toEqual({
      q: "asus",
      sort: "price_desc",
      stockOnly: true,
      filters: { socket: ["AM5", "LGA1700"] },
      ranges: {
        price: { min: 100, max: 500 },
        weight: { min: null, max: 9 },
      },
      productId: "abc",
      pick: "motherboard",
    });
  });

  it("ignores an unknown sort key", () => {
    at("/#/c/cpu?sort=bogus");
    const route = parseRoute();
    expect(route.view === "category" && route.params.sort).toBe("price_asc");
  });

  it("round-trips categoryHash through parseRoute", () => {
    const params = {
      q: "x y",
      sort: "name" as const,
      stockOnly: true,
      filters: { socket: ["AM5"] },
      ranges: { price: { min: 1, max: null } },
      productId: null,
      pick: "cpu",
    };
    at("/" + categoryHash("case_fan", params));
    expect(parseRoute()).toEqual({ view: "category", category: "case_fan", params });
  });

  it("parses and decodes product routes", () => {
    at("/" + productHash("gpu", "mpn:gpu:n506taerooc8gd"));
    expect(parseRoute()).toEqual({
      view: "product",
      category: "gpu",
      productId: "mpn:gpu:n506taerooc8gd",
    });
  });
});

describe("draft build helpers", () => {
  it("replaces single slots and appends to multi slots", () => {
    const build: Record<string, string[]> = {};
    addToBuild(build, "cpu", "a");
    addToBuild(build, "cpu", "b");
    addToBuild(build, "memory", "m");
    addToBuild(build, "memory", "m");
    expect(build).toEqual({ cpu: ["b"], memory: ["m", "m"] });
    expect(buildItemCount(build)).toBe(3);
  });

  it("removes one instance at a time and drops emptied slots", () => {
    const build = { memory: ["m", "m"] };
    removeFromBuild(build, "memory", "m");
    expect(build).toEqual({ memory: ["m"] });
    removeFromBuild(build, "memory", "m");
    expect(build).toEqual({});
    removeFromBuild(build, "memory", "m");
    expect(build).toEqual({});
  });
});
