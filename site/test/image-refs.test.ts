import { describe, expect, it } from "vitest";
import { collectImageRefs, isInsideDir, isSafeImageRef } from "../scripts/image-refs.mjs";

describe("isSafeImageRef", () => {
  it("accepts the cover and derived shapes the pipeline writes", () => {
    for (const rel of [
      "tms/ABC-1.2_x.webp",
      "onepc/171975.webp",
      "ksp/thumbs/340404.webp",
      "ivory/covers256/NE1000GM-W-ATX3.0.webp",
    ]) {
      expect(isSafeImageRef(rel), rel).toBe(true);
    }
  });

  it("rejects traversal, other files and other shapes", () => {
    for (const rel of [
      "../catalog.json",
      "a/thumbs/../../../.env",
      "a/thumbs/../../../.git/config",
      "tms/../../x.webp",
      "tms/x.png",
      "tms/a/b.webp",
      "TMS/x.webp",
      "tms\\..\\x.webp",
      "/etc/x.webp",
      "tms/x.webp\u0000",
      "",
    ]) {
      expect(isSafeImageRef(rel), rel).toBe(false);
    }
  });
});

describe("isInsideDir", () => {
  it("only accepts paths strictly below the root", () => {
    expect(isInsideDir("data/images", "data/images/tms/x.webp")).toBe(true);
    expect(isInsideDir("data/images", "data/images")).toBe(false);
    expect(isInsideDir("data/images", "data/images/../catalog.json")).toBe(false);
    expect(isInsideDir("data/images", "data/images-evil/x.webp")).toBe(false);
  });
});

describe("collectImageRefs", () => {
  // The fixture holds vendor-shaped "/images/..." strings next to real refs,
  // a nested history/ file and a non-JSON file that must be skipped.
  it("keeps real image refs and skips vendor-shaped path strings", () => {
    const { refs, rejected } = collectImageRefs("test/image-refs-fixture");
    expect([...refs].sort()).toEqual(["ksp/340404.webp", "tms/thumbs/C245KFT.webp"]);
    expect(rejected).toHaveLength(4);
  });
});
