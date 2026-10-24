import { describe, expect, it } from "vitest";
import {
  checkCompatibility,
  impliedFilterValues,
  isProductCompatibleWithBuild,
  knownPartWattage,
  numSpec,
  optionMatchesTokens,
  slotForCategory,
} from "../src/build";
import { product } from "./fixtures";

const codes = (parts: Parameters<typeof checkCompatibility>[0], watts = 0) =>
  checkCompatibility(parts, watts).map((i) => i.code);

describe("slotForCategory / numSpec", () => {
  it("maps categories onto builder slots", () => {
    expect(slotForCategory("cpu_cooler")?.id).toBe("cooler");
    expect(slotForCategory("case_fan")?.id).toBe("extras");
    expect(slotForCategory("nope")).toBeNull();
  });

  it("reads the first finite numeric spec and ignores strings/null", () => {
    const p = product("a", "A", { tdp_w: null, wattage_w: 65, x: "7" });
    expect(numSpec(p, ["tdp_w", "wattage_w"])).toBe(65);
    expect(numSpec(p, ["x"])).toBeNull();
    expect(numSpec(p, ["missing"])).toBeNull();
  });
});

describe("socket compatibility", () => {
  const am5Cpu = product("c", "AMD Ryzen 7 9800X3D", { socket: "AM5" });
  const am5Board = product("b", "ASUS PRIME B650-PLUS", { socket: "AM5" });
  const lgaBoard = product("b2", "MSI PRO B760-P", { socket: "LGA1700" });

  it("accepts matching sockets", () => {
    expect(codes({ cpu: am5Cpu, motherboard: am5Board })).toEqual([]);
  });

  it("errors on mismatched sockets", () => {
    const issues = checkCompatibility({ cpu: am5Cpu, motherboard: lgaBoard }, 0);
    expect(issues).toHaveLength(1);
    expect(issues[0]).toMatchObject({
      level: "err",
      code: "socket",
      params: { cpu: "AM5", board: "LGA1700" },
    });
  });

  it("infers the CPU socket from the name when specs are empty", () => {
    const ryzen = product("c", "AMD Ryzen 5 5600X Tray");
    const core = product("c2", "Intel Core i5-13600K");
    expect(codes({ cpu: ryzen, motherboard: am5Board })).toContain("socket");
    expect(codes({ cpu: core, motherboard: lgaBoard })).toEqual([]);
  });

  it("infers the board socket from the chipset when no socket spec exists", () => {
    const board = product("b", "Gigabyte B550 AORUS ELITE");
    expect(codes({ cpu: am5Cpu, motherboard: board })).toContain("socket");
  });

  it("stays silent when either side is unknown", () => {
    const unknownCpu = product("c", "Mystery chip");
    expect(codes({ cpu: unknownCpu, motherboard: am5Board })).toEqual([]);
  });

  it("warns when the cooler lists sockets that exclude the CPU", () => {
    const cooler = product("k", "Cooler X", { sockets: ["LGA1700", "LGA1200"] });
    const issues = checkCompatibility({ cpu: am5Cpu, cooler }, 0);
    expect(issues).toEqual([{ level: "warn", code: "coolerSocket", params: { cpu: "AM5" } }]);
  });
});

describe("memory compatibility", () => {
  const ddr5Board = product("b", "Board", { memory_type: "DDR5" });

  it("errors on a DDR generation mismatch", () => {
    const ddr4 = product("m", "Corsair DDR4 3200", { memory_type: "DDR4" });
    const issues = checkCompatibility({ motherboard: ddr5Board, memory: ddr4 }, 0);
    expect(issues[0]).toMatchObject({
      level: "err",
      code: "memoryType",
      params: { memory: "DDR4", board: "DDR5" },
    });
  });

  it("falls back to the title when the spec is missing", () => {
    const ddr4 = product("m", "Kingston Fury 32GB DDR4 3200");
    expect(codes({ motherboard: ddr5Board, memory: ddr4 })).toContain("memoryType");
  });

  it("accepts the same generation", () => {
    const ddr5 = product("m", "Kit", { memory_type: "DDR5" });
    expect(codes({ motherboard: ddr5Board, memory: ddr5 })).toEqual([]);
  });

  it("errors when the kit exceeds the board's max capacity", () => {
    const board = product("b", "B", { memory_type: "DDR5", memory_max_gb: 64 });
    const kit = product("m", "Kit", { memory_type: "DDR5", total_gb: 128 });
    expect(codes({ motherboard: board, memory: kit })).toEqual(["memoryMax"]);
  });

  it("warns when the kit is faster than any speed the board lists", () => {
    const board = product("b", "B", {
      memory_type: "DDR5",
      memory_speeds: ["4800", "6000 MHz"],
    });
    const kit = product("m", "Kit", { memory_type: "DDR5", speed_mhz: 7200 });
    const issues = checkCompatibility({ motherboard: board, memory: kit }, 0);
    expect(issues).toEqual([{ level: "warn", code: "memorySpeed", params: { speed: 7200 } }]);
  });
});

describe("case fit: form factor, GPU length, cooler height, radiator", () => {
  it("errors when the board form factor is not supported by the case", () => {
    const board = product("b", "B", { form_factor: "E-ATX" });
    const case_ = product("c", "Case", {
      mb_form_factors: ["ATX", "Micro-ATX", "Mini-ITX"],
    });
    const issues = checkCompatibility({ motherboard: board, case: case_ }, 0);
    expect(issues).toEqual([{ level: "err", code: "boardForm", params: { form: "EATX" } }]);
  });

  it("normalises form-factor spellings (mATX == Micro-ATX)", () => {
    const board = product("b", "B", { form_factor: "mATX" });
    const case_ = product("c", "Case", { mb_form_factors: ["Micro-ATX"] });
    expect(codes({ motherboard: board, case: case_ })).toEqual([]);
  });

  it("errors on a GPU longer than the case allows, and passes at the limit", () => {
    const case_ = product("c", "Case", { max_gpu_length_mm: 330 });
    const long = product("g", "G", { length_mm: 340 });
    const exact = product("g", "G", { length_mm: 330 });
    expect(codes({ gpu: long, case: case_ })).toEqual(["gpuLength"]);
    expect(codes({ gpu: exact, case: case_ })).toEqual([]);
  });

  it("errors on a cooler taller than the case clearance", () => {
    const case_ = product("c", "Case", { max_cooler_height_mm: 160 });
    const tall = product("k", "Tower", { height_mm: 165 });
    expect(checkCompatibility({ cooler: tall, case: case_ }, 0)).toEqual([
      { level: "err", code: "coolerHeight", params: { height: 165, max: 160 } },
    ]);
    const exact = product("k", "Tower", { height_mm: 160 });
    expect(codes({ cooler: exact, case: case_ })).toEqual([]);
  });

  it("warns when the AIO radiator is larger than every size the case lists", () => {
    const case_ = product("c", "Case", {
      radiator_support: { "240 mm": 1, "280 mm": 1 },
    });
    const aio360 = product("k", "AIO", { radiator_size_mm: 360 });
    const aio240 = product("k", "AIO", { radiator_size_mm: 240 });
    expect(checkCompatibility({ cooler: aio360, case: case_ }, 0)).toEqual([
      { level: "warn", code: "radiator", params: { size: 360 } },
    ]);
    expect(codes({ cooler: aio240, case: case_ })).toEqual([]);
  });

  it("does not guess when sizes are unknown", () => {
    const parts = {
      case: product("c", "Case"),
      gpu: product("g", "G", { length_mm: 999 }),
      cooler: product("k", "K", { height_mm: 999, radiator_size_mm: 999 }),
      motherboard: product("b", "B", { form_factor: "E-ATX" }),
    };
    expect(codes(parts)).toEqual([]);
  });
});

describe("PSU headroom", () => {
  it("errors when the supply is below the estimated draw", () => {
    const psu = product("p", "PSU", { wattage_w: 450 });
    expect(checkCompatibility({ psu }, 500)).toEqual([
      { level: "err", code: "psuLow", params: { capacity: 450, watts: 500 } },
    ]);
  });

  it("warns inside the 20% headroom band, and is clean above it", () => {
    const psu = product("p", "PSU", { wattage_w: 550 });
    expect(codes({ psu }, 500)).toEqual(["psuHeadroom"]);
    expect(codes({ psu }, 458)).toEqual([]); // 458 * 1.2 = 549.6 <= 550
    expect(codes({ psu }, 459)).toEqual(["psuHeadroom"]);
  });

  it("is silent without an estimate or a rated capacity", () => {
    expect(codes({ psu: product("p", "PSU", { wattage_w: 100 }) }, 0)).toEqual([]);
    expect(codes({ psu: product("p", "PSU") }, 800)).toEqual([]);
  });

  it("warns when the GPU's recommended PSU exceeds the supply", () => {
    const psu = product("p", "PSU", { wattage_w: 650 });
    const gpu = product("g", "G", { recommended_psu_w: 750 });
    expect(checkCompatibility({ psu, gpu }, 0)).toEqual([
      {
        level: "warn",
        code: "psuGpu",
        params: { capacity: 650, recommended: 750 },
      },
    ]);
  });
});

describe("knownPartWattage", () => {
  it("counts TDP, ignores PSUs and unknown parts", () => {
    expect(knownPartWattage("cpu", product("c", "C", { tdp_w: 105.4 }))).toBe(105);
    expect(knownPartWattage("gpu", product("g", "G", { tdp_w: 320 }))).toBe(320);
    expect(knownPartWattage("psu", product("p", "P", { wattage_w: 850 }))).toBe(0);
    expect(knownPartWattage("memory", product("m", "M"))).toBe(0);
  });
});

describe("picker filtering and implied filters", () => {
  const am5Cpu = product("c", "Ryzen", { socket: "AM5" });
  const am5Board = product("b1", "B650", { socket: "AM5" });
  const lgaBoard = product("b2", "B760", { socket: "LGA1700" });

  it("filters motherboards by the chosen CPU's socket", () => {
    expect(isProductCompatibleWithBuild(am5Board, "motherboard", { cpu: am5Cpu })).toBe(true);
    expect(isProductCompatibleWithBuild(lgaBoard, "motherboard", { cpu: am5Cpu })).toBe(false);
  });

  it("filters PSUs below the estimated draw", () => {
    const parts = { gpu: product("g", "G", { tdp_w: 400 }) };
    const weak = product("p", "P", { wattage_w: 300 });
    const strong = product("p", "P", { wattage_w: 650 });
    expect(isProductCompatibleWithBuild(weak, "psu", parts)).toBe(false);
    expect(isProductCompatibleWithBuild(strong, "psu", parts)).toBe(true);
  });

  it("filters cases that are too small for the build", () => {
    const parts = { gpu: product("g", "G", { length_mm: 350 }) };
    const small = product("c", "C", { max_gpu_length_mm: 300 });
    const big = product("c", "C", { max_gpu_length_mm: 360 });
    expect(isProductCompatibleWithBuild(small, "case", parts)).toBe(false);
    expect(isProductCompatibleWithBuild(big, "case", parts)).toBe(true);
  });

  it("derives implied filter values from the build", () => {
    expect(impliedFilterValues("motherboard", { cpu: am5Cpu })).toEqual({
      socket: ["AM5"],
    });
    const board = product("b", "B", { memory_type: "DDR5" });
    expect(impliedFilterValues("memory", { motherboard: board })).toEqual({
      memory_type: ["DDR5"],
    });
    expect(impliedFilterValues("gpu", { cpu: am5Cpu })).toEqual({});
  });

  it("matches option values against implied tokens", () => {
    expect(optionMatchesTokens("Socket AM5", ["AM5"])).toBe(true);
    expect(optionMatchesTokens("LGA1700", ["AM5"])).toBe(false);
    expect(optionMatchesTokens("", ["AM5"])).toBe(false);
  });
});
