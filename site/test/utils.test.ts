import { describe, expect, it } from "vitest";
import {
  displayName,
  esc,
  normSearch,
  safeImageUrl,
  safeUrl,
  searchScore,
  searchTokens,
  skuOf,
} from "../src/utils";
import { product } from "./fixtures";

describe("esc", () => {
  it("escapes the five HTML-significant characters", () => {
    expect(esc(`<a href="x" title='y'>&</a>`)).toBe(
      "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;"
    );
  });

  it("escapes ampersands first (no double escaping of its own output)", () => {
    expect(esc("&lt;")).toBe("&amp;lt;");
  });

  it("maps null/undefined to empty and stringifies other values", () => {
    expect(esc(null)).toBe("");
    expect(esc(undefined)).toBe("");
    expect(esc(0)).toBe("0");
    expect(esc(27)).toBe("27");
  });
});

describe("safeUrl / safeImageUrl", () => {
  it("allows http(s), same-origin paths and fragments", () => {
    expect(safeUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(safeUrl("  http://example.com ")).toBe("http://example.com");
    expect(safeUrl("/p/cpu/x")).toBe("/p/cpu/x");
    expect(safeUrl("#/build")).toBe("#/build");
  });

  it("rejects script-bearing and protocol-relative URLs", () => {
    for (const bad of [
      "javascript:alert(1)",
      "JaVaScRiPt:alert(1)",
      "data:text/html,<script>",
      "vbscript:x",
      "file:///etc/passwd",
      "//evil.example/x",
      "",
      null,
      undefined,
      42,
    ]) {
      expect(safeUrl(bad)).toBeNull();
    }
  });

  it("allows only same-origin /images/ for <img>", () => {
    expect(safeImageUrl("/images/tms/123.webp")).toBe("/images/tms/123.webp");
    expect(safeImageUrl("  /images/a.webp ")).toBe("/images/a.webp");
    expect(safeImageUrl("https://cdn.vendor.example/a.jpg")).toBeNull();
    expect(safeImageUrl("/other/a.jpg")).toBeNull();
    expect(safeImageUrl("data:image/png;base64,AAAA")).toBeNull();
    expect(safeImageUrl(undefined)).toBeNull();
  });
});

describe("search normalisation and scoring", () => {
  it("normalises case, punctuation, inch marks and Hebrew maqaf", () => {
    expect(normSearch(`  Gigabyte  RTX-5070 "OC"  `)).toBe("gigabyte rtx 5070 oc");
    expect(normSearch("מעבד־אינטל")).toBe("מעבד אינטל");
    expect(searchTokens("")).toEqual([]);
    expect(searchTokens("  ")).toEqual([]);
    expect(searchTokens("Ryzen 7")).toEqual(["ryzen", "7"]);
  });

  const row = (
    name: string,
    extra: Partial<{ brand: string; category: string; haystack: string }> = {}
  ) => {
    const n = normSearch(name);
    return {
      haystack: extra.haystack ?? n,
      name: n,
      brand: extra.brand ?? "",
      category: extra.category ?? "",
    };
  };

  it("returns -1 for no tokens or when any token is missing", () => {
    expect(searchScore([], row("anything"))).toBe(-1);
    expect(searchScore(["ryzen", "9999"], row("AMD Ryzen 7 9800X3D"))).toBe(-1);
  });

  it("matches non-adjacent tokens", () => {
    const tokens = searchTokens("gigabyte 5070 oc");
    const score = searchScore(tokens, row("Gigabyte GeForce RTX 5070 Windforce OC"));
    expect(score).toBeGreaterThanOrEqual(0);
  });

  it("ranks exact > prefix > substring name matches", () => {
    const tokens = searchTokens("rtx 5070");
    const exact = searchScore(tokens, row("RTX 5070"));
    const prefix = searchScore(tokens, row("RTX 5070 Ti OC"));
    const inside = searchScore(tokens, row("Gigabyte RTX 5070 OC"));
    expect(exact).toBeGreaterThan(prefix);
    expect(prefix).toBeGreaterThan(inside);
  });

  it("lifts brand and category matches, and a name hit beats a spec-only hit", () => {
    const branded = searchScore(["msi"], row("MSI Board", { brand: "msi" }));
    const unbranded = searchScore(["msi"], row("MSI Board"));
    expect(branded).toBeGreaterThan(unbranded);

    const haystack = "some card gpu";
    const catHit = searchScore(["gpu"], row("Some Card", { category: "gpu", haystack }));
    const noCat = searchScore(["gpu"], row("Some Card", { haystack }));
    expect(catHit).toBeGreaterThan(noCat);

    const nameHit = searchScore(["white"], row("Case White"));
    const specHit = searchScore(["white"], row("Case X", { haystack: "case x white" }));
    expect(nameHit).toBeGreaterThan(specHit);
  });

  it("prefers shorter names on otherwise equal matches", () => {
    const short = searchScore(["ssd"], row("SSD 1TB"));
    const long = searchScore(["ssd"], row("SSD 1TB NVMe PCIe Gen4 M.2 2280 with heatsink"));
    expect(short).toBeGreaterThan(long);
  });
});

describe("skuOf / displayName", () => {
  it("prefers the model, else the id tail", () => {
    expect(skuOf(product("mpn:gpu:abc", "G", {}, { model: "ABC-1" }))).toBe("ABC-1");
    expect(skuOf(product("mpn:gpu:abc", "G"))).toBe("abc");
  });

  it("drops a leading SKU echo from the name", () => {
    const p = product(
      "mpn:cpu:100-000000",
      "100-000000 AMD Ryzen 7",
      {},
      {
        model: "100-000000",
      }
    );
    expect(displayName(p)).toBe("AMD Ryzen 7");
  });

  it("replaces placeholder names with the SKU or brand", () => {
    expect(displayName(product("mpn:cpu:abc", "unknown"))).toBe("abc");
    const p = product("x", "N/A", {}, { brand: "ASUS", model: "unknown" });
    expect(displayName(p)).toBe("ASUS");
  });
});
