import { describe, expect, it } from "vitest";
import { checkCompatibility } from "../src/build";
import { boardSize, caseType, listedBoardSizes, supportedBoardSizes } from "../src/formFactors";
import {
  driveConnection,
  driveForm,
  facetFor,
  kitOrder,
  lanSpeed,
  normalizeOption,
  optionComparator,
  railKeys,
} from "../src/views/category/facets";
import { product } from "./fixtures";

describe("board sizes", () => {
  it("reads every vendor spelling", () => {
    expect(boardSize("Micro ATX")).toBe("Micro-ATX");
    expect(boardSize("mATX")).toBe("Micro-ATX");
    expect(boardSize("Compact MicroATX")).toBe("Micro-ATX");
    expect(boardSize("E-ATX (310mm Width)")).toBe("E-ATX");
    expect(boardSize("EE-ATX")).toBe("E-ATX");
    expect(boardSize("ITX")).toBe("Mini-ITX");
    expect(boardSize("Thin Mini ITX")).toBe("Thin Mini-ITX");
    expect(boardSize("Mid Tower")).toBeNull();
  });

  it("splits cells that arrive unsplit", () => {
    expect(listedBoardSizes(["E-ATX (310mm Width)、ATX、Micro-ATX、Mini-ITX"])).toEqual([
      "E-ATX",
      "ATX",
      "Micro-ATX",
      "Mini-ITX",
    ]);
    expect(listedBoardSizes(["ATX / Micro-ATX / Mini-ITX"])).toEqual(["ATX", "Micro-ATX", "Mini-ITX"]);
  });

  it("lets an ATX case take smaller ATX-family boards", () => {
    expect(supportedBoardSizes(["ATX"])).toEqual(["ATX", "Micro-ATX", "Mini-ITX"]);
    expect(supportedBoardSizes(["Mini-DTX"])).toEqual(["Mini-DTX"]);
  });

  it("names the case type the way PCPartPicker does", () => {
    expect(caseType("Mid Tower", ["Mini ITX", "Micro ATX", "ATX", "E-ATX"])).toBe("ATX Mid Tower");
    expect(caseType("Full Tower", ["ATX", "E-ATX"])).toBe("ATX Full Tower");
    expect(caseType("Mini Tower", ["Mini ITX", "Micro ATX"])).toBe("MicroATX Mini Tower");
    expect(caseType("Mid Tower", ["Micro ATX", "Mini ITX"])).toBe("MicroATX Mid Tower");
    expect(caseType("Compact MicroATX", null)).toBe("MicroATX Mini Tower");
    expect(caseType("Small Tower", ["Micro ATX"])).toBe("MicroATX Mini Tower");
    expect(caseType("SFF", ["Mini ITX"])).toBe("Mini ITX Desktop");
    expect(caseType("Mini ITX Tower", null)).toBe("Mini ITX Tower");
    expect(caseType("Mini Tower", null, "Antec NX200M Micro 1X120MM Black")).toBe("MicroATX Mini Tower");
    expect(caseType("SFF | HTPC", ["Mini ITX"])).toBe("HTPC");
    expect(caseType("4U", null)).toBe("Rackmount 4U");
    expect(caseType("Mid Tower", null)).toBeNull();
    expect(caseType("ATX", ["Mini ITX"])).toBeNull();
  });

  it("passes a Micro-ATX board in a case that only lists ATX", () => {
    const board = product("b", "B", { form_factor: "Micro-ATX" });
    const case_ = product("c", "C", { mb_form_factors: ["ATX"] });
    expect(checkCompatibility({ motherboard: board, case: case_ }, 0)).toEqual([]);
  });
});

describe("derived filters", () => {
  it("finds every case that takes a Micro ATX board", () => {
    const facet = facetFor("case", "board_support")!;
    expect(facet.values(product("c", "C", { mb_form_factors: ["ATX"] }))).toEqual(["ATX", "Micro ATX", "Mini ITX"]);
    expect(facet.values(product("c", "C", { mb_form_factors: ["Mini ITX"] }))).toEqual(["Mini ITX"]);
  });

  it("leads with the manufacturer, then the motherboard's size, socket and chipset", () => {
    expect(railKeys("motherboard", ["socket", "chipset", "form_factor", "memory_type", "manufacturer"]).slice(0, 5)).toEqual([
      "manufacturer",
      "board_form",
      "socket",
      "chipset",
      "memory_type",
    ]);
  });

  it("leads with the manufacturer in every category", () => {
    for (const category of ["cpu", "gpu", "storage", "case", "psu", "accessories"]) {
      expect(railKeys(category, ["color", "manufacturer"])[0]).toBe("manufacturer");
    }
  });

  it("buckets storage capacity by marketing size", () => {
    const facet = facetFor("storage", "capacity")!;
    expect(facet.values(product("s", "S", { capacity_gb: 960 }))).toEqual(["1000"]);
    expect(facet.values(product("s", "S", { capacity_gb: 2048 }))).toEqual(["2000"]);
    expect(facet.values(product("s", "S", { capacity_gb: 512 }))).toEqual(["512"]);
    expect(facet.values(product("s", "S", { capacity_gb: null }))).toEqual([]);
  });

  it("reads one connection from the NVMe flag, PCIe gen and interface text", () => {
    expect(driveConnection(product("s", "S", { nvme: true, pcie_gen: 4 }))).toBe("NVMe PCIe 4.0");
    expect(driveConnection(product("s", "S", { interface: "PCIe Gen5 x4 NVMe 2.0" }))).toBe("NVMe PCIe 5.0");
    expect(driveConnection(product("s", "S", { interface: "SATA 6.0 Gb/s", nvme: false }))).toBe("SATA");
    expect(driveConnection(product("s", "S", { type: "HDD" }))).toBe("SATA");
  });

  it("folds form-factor spellings", () => {
    expect(driveForm(product("s", "S", { form_factor: "M.2-2280" }))).toBe("M.2 2280");
    expect(driveForm(product("s", "S", { form_factor: "2.5''" }))).toBe('2.5"');
    expect(driveForm(product("s", "S", { form_factor: "2.5-inch" }))).toBe('2.5"');
    expect(driveForm(product("s", "S", { form_factor: '"3.5' }))).toBe('3.5"');
  });

  it("groups memory kits by stick size, then stick count", () => {
    expect(["2 x 16GB", "1 x 16GB", "1 x 32GB", "2 x 8GB", "1 x 4GB", "3 x 16GB", "1 x 8GB"].sort(kitOrder)).toEqual([
      "1 x 4GB",
      "1 x 8GB",
      "2 x 8GB",
      "1 x 16GB",
      "2 x 16GB",
      "3 x 16GB",
      "1 x 32GB",
    ]);
  });

  it("folds the same lighting and colour written two ways into one option", () => {
    const p = product("c", "C");
    expect(normalizeOption("case", "lighting", "ARGB | LCD", p)).toEqual(["ARGB", "LCD"]);
    expect(normalizeOption("case", "lighting", "LCD | ARGB", p).sort()).toEqual(["ARGB", "LCD"]);
    expect(normalizeOption("cpu_cooler", "lighting", "5V 3-pin ARGB", p)).toEqual(["ARGB"]);
    expect(normalizeOption("motherboard", "color", "Silver / Black", p)).toEqual(["Black / Silver"]);
    expect(normalizeOption("motherboard", "color", "Black / Silver", p)).toEqual(["Black / Silver"]);
    expect(normalizeOption("cpu_cooler", "color", "ARGB", p)).toEqual([]);
  });

  it("names CPU series like PCPartPicker and keeps each line-up together", () => {
    const amd = product("c", "C", { manufacturer: "AMD" }, { brand: "AMD" });
    const intel = product("c", "C", { manufacturer: "Intel" }, { brand: "Intel" });
    expect(normalizeOption("cpu", "series", "Ryzen Threadripper", amd)).toEqual(["AMD Threadripper"]);
    expect(normalizeOption("cpu", "series", "Core Ultra 7 - 265KF", intel)).toEqual(["Intel Core Ultra 7"]);
    expect(normalizeOption("cpu", "series", "Ultra 5", intel)).toEqual(["Intel Core Ultra 5"]);
    const order = optionComparator("cpu", "series", "str");
    expect(["Intel Core i9", "AMD Ryzen 9", "Intel Core i3", "AMD Ryzen 5"].sort(order)).toEqual([
      "AMD Ryzen 5",
      "AMD Ryzen 9",
      "Intel Core i3",
      "Intel Core i9",
    ]);
  });

  it("lists AMD microarchitectures first, Zen generations in order", () => {
    const order = optionComparator("cpu", "microarchitecture", "str");
    expect(["Raptor Lake", "Zen 4", "Zen+", "Alder Lake", "Zen", "Zen 2"].sort(order)).toEqual([
      "Zen",
      "Zen+",
      "Zen 2",
      "Zen 4",
      "Alder Lake",
      "Raptor Lake",
    ]);
  });

  it("puts the chipset's platform in front", () => {
    const p = product("b", "B");
    expect(normalizeOption("motherboard", "chipset", "B650E", p)).toEqual(["AMD B650E"]);
    expect(normalizeOption("motherboard", "chipset", "Z790", p)).toEqual(["Intel Z790"]);
  });

  it("reads LAN speed out of chip names", () => {
    expect(lanSpeed(product("b", "B", { ethernet: "Realtek RTL8125BG 2.5G LAN" }))).toBe("2.5 Gb/s");
    expect(lanSpeed(product("b", "B", { ethernet: "LAN 1 Gb/s" }))).toBe("1 Gb/s");
    expect(lanSpeed(product("b", "B", { ethernet: "REALTEK 8111M LAN (10/100/1000Mbit)" }))).toBe("1 Gb/s");
    expect(lanSpeed(product("b", "B", { ethernet: "Ethernet" }))).toBeNull();
  });
});
