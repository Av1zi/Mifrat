import { describe, expect, it } from "vitest";
import {
  LIST_ID_CORE_ALPHABET,
  LIST_ID_EXTRA_SYMBOLS,
  LIST_ID_LENGTH,
  MAX_IDS_PER_SLOT,
  MAX_LIST_SLOTS,
  MAX_PRODUCT_ID_LENGTH,
  canonicalizeListBuild,
  generateListId,
  isValidListId,
  sha256Hex,
  validateListBuild,
} from "../src/lists";

/** Deterministic byte source cycling through `bytes`. */
function bytesFrom(bytes: number[]): () => number {
  let i = 0;
  return () => bytes[i++ % bytes.length];
}

describe("isValidListId", () => {
  it("accepts 4-8 chars, alphanumeric at the ends, !$& allowed inside", () => {
    for (const ok of ["abcd", "aB3!xQ9", "a!$&b", "Z9Z9Z9Z9"]) {
      expect(isValidListId(ok)).toBe(true);
    }
  });

  it("rejects bad length, edge symbols and path-hostile characters", () => {
    for (const bad of [
      "",
      "abc",
      "abcdefghi",
      "!abcd",
      "abcd!",
      "ab#cd",
      "ab?cd",
      "ab%cd",
      "ab cd",
      "ab/cd",
    ]) {
      expect(isValidListId(bad)).toBe(false);
    }
  });
});

describe("generateListId", () => {
  it("produces fixed-length ids that validate, with alphanumeric edges", () => {
    const next = (() => {
      let x = 12345;
      return () => ((x = (x * 1103515245 + 12345) & 0x7fffffff) >>> 16) & 0xff;
    })();
    for (let i = 0; i < 500; i++) {
      const id = generateListId(next);
      expect(id).toHaveLength(LIST_ID_LENGTH);
      expect(isValidListId(id)).toBe(true);
      expect(LIST_ID_CORE_ALPHABET).toContain(id[0]);
      expect(LIST_ID_CORE_ALPHABET).toContain(id[id.length - 1]);
    }
  });

  it("uses rejection sampling so a high byte never biases the draw", () => {
    // 62-char alphabet: limit = floor(256/62)*62 = 248, so 248..255 are rejected.
    // 255 is skipped, then 0 -> "A".
    const id = generateListId(bytesFrom([255, 0]));
    expect(id[0]).toBe("A");
    // Mid alphabet has 65 chars: limit = 195, bytes 64 -> index 64 = "&".
    const mid = generateListId(bytesFrom([0, 64, 64, 64, 64, 0]));
    expect(mid).toBe(`A${"&".repeat(4)}A`);
    expect(LIST_ID_EXTRA_SYMBOLS).toContain("&");
  });
});

describe("validateListBuild", () => {
  const slots = new Set(["cpu", "memory", "gpu"]);

  it("accepts a well-formed build", () => {
    expect(validateListBuild({ cpu: ["a"], memory: ["m1", "m2"] }, slots)).toEqual({
      ok: true,
      build: { cpu: ["a"], memory: ["m1", "m2"] },
    });
  });

  it.each([
    ["null", null, "body must be a JSON object"],
    ["array", [], "body must be a JSON object"],
    ["string", "x", "body must be a JSON object"],
    ["empty object", {}, "build is empty"],
    ["unknown slot", { psu: ["a"] }, "unknown slot: psu"],
    ["non-array slot", { cpu: "a" }, "empty slot: cpu"],
    ["empty slot array", { cpu: [] }, "empty slot: cpu"],
    ["non-string id", { cpu: [1] }, "bad product id in slot: cpu"],
    ["empty id", { cpu: [""] }, "bad product id in slot: cpu"],
  ])("rejects %s", (_name, input, error) => {
    expect(validateListBuild(input, slots)).toEqual({ ok: false, error });
  });

  it("enforces the slot, item and id-length limits", () => {
    const many = new Set(Array.from({ length: MAX_LIST_SLOTS + 1 }, (_, i) => `s${i}`));
    const tooManySlots = Object.fromEntries([...many].map((s) => [s, ["a"]]));
    expect(validateListBuild(tooManySlots, many)).toEqual({
      ok: false,
      error: "too many slots",
    });

    const tooManyIds = { gpu: Array.from({ length: MAX_IDS_PER_SLOT + 1 }, () => "a") };
    expect(validateListBuild(tooManyIds, slots)).toEqual({
      ok: false,
      error: "too many items in slot: gpu",
    });

    const longId = { cpu: ["x".repeat(MAX_PRODUCT_ID_LENGTH + 1)] };
    expect(validateListBuild(longId, slots)).toEqual({
      ok: false,
      error: "product id too long in slot: cpu",
    });
    const okId = { cpu: ["x".repeat(MAX_PRODUCT_ID_LENGTH)] };
    expect(validateListBuild(okId, slots).ok).toBe(true);
  });
});

describe("canonicalizeListBuild", () => {
  it("orders slots, de-duplicates and sorts ids", () => {
    const out = canonicalizeListBuild({ memory: ["b", "a", "b"], cpu: ["z"] }, [
      "cpu",
      "motherboard",
      "memory",
    ]);
    expect(Object.keys(out)).toEqual(["cpu", "memory"]);
    expect(out).toEqual({ cpu: ["z"], memory: ["a", "b"] });
  });

  it("appends unknown slots last, sorted by name, and drops empty ones", () => {
    const out = canonicalizeListBuild({ zeta: ["1"], alpha: ["2"], cpu: ["c"], empty: [] }, [
      "cpu",
    ]);
    expect(Object.keys(out)).toEqual(["cpu", "alpha", "zeta"]);
  });

  it("is order-insensitive, so equal builds dedupe to one key", () => {
    const a = canonicalizeListBuild({ storage: ["x", "y"], cpu: ["c"] }, ["cpu", "storage"]);
    const b = canonicalizeListBuild({ cpu: ["c"], storage: ["y", "x"] }, ["cpu", "storage"]);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });
});

describe("sha256Hex", () => {
  it("matches the known SHA-256 vector", async () => {
    expect(await sha256Hex("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
  });
});
