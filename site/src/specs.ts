/**
 * Per-category spec curation.
 *
 * Two problems this solves:
 * 1. The attributes blob carries ~730 distinct keys across the catalog
 *    (deep trivia like mosfet phases sits next to socket and wattage).
 *    Showing everything as a filter buries the useful ones.
 * 2. Detail pages listed specs in arbitrary (alphabetical-ish) order, so
 *    "Segment: desktop (Mainstream)"-style trivia sat above core counts.
 *
 * SPEC_PRIORITY lists the keys that matter per category, most important
 * first. It drives three things: which checkbox filters the rail offers
 * (FILTER_ALLOWLIST), which columns the product table shows, and the row
 * order (+ show-more cutoff) on the detail overlay. Anything not listed
 * is still shown — just after the important stuff, never as a filter.
 */

// Vernacular fallback: categories without an explicit list reuse the
// generic order (connectivity basics first, then the rest).
const GENERIC_PRIORITY = [
  "brand",
  "model",
  "socket",
  "chipset",
  "memory_type",
  "form_factor",
  "color",
  "wifi",
];

export const SPEC_PRIORITY: Record<string, string[]> = {
  cpu: [
    "cores",
    "threads",
    "base_clock_ghz",
    "boost_clock_ghz",
    "l2_cache",
    "l3_cache",
    "tdp",
    "generation",
    "tier",
    "microarchitecture",
    "socket",
    "integrated_graphics",
    "smt",
    "ecc_support",
    "cooler_included",
    "packaging",
    "codename",
    "manufacturing_process",
    "launch",
    "brand",
    "model",
  ],
  motherboard: [
    "socket",
    "chipset",
    "form_factor",
    "memory_type",
    "memory_slots",
    "m2_slots",
    "wifi",
    "wifi_standard",
    "sata_ports",
    "pcie_x16_slots",
    "usb_ports",
    "display_outputs",
    "brand",
    "model",
  ],
  memory: [
    "memory_type",
    "capacity_gb",
    "speed_mhz",
    "cas_latency",
    "module_count",
    "modules",
    "voltage",
    "ecc_support",
    "heat_spreader",
    "brand",
    "model",
  ],
  gpu: [
    "gpu_chip",
    "chipset",
    "vram_gb",
    "memory_type",
    "boost_clock_mhz",
    "core_clock_mhz",
    "tdp",
    "gpu_length_mm",
    "slot_width",
    "cooling",
    "brand",
    "model",
  ],
  storage: [
    "capacity_gb",
    "drive_type",
    "drive_form_factor",
    "interface",
    "nvme",
    "pcie_gen",
    "read",
    "write",
    "tbw",
    "brand",
    "model",
  ],
  psu: [
    "wattage",
    "wattage_w",
    "efficiency",
    "modular",
    "form_factor",
    "fanless",
    "brand",
    "model",
  ],
  case: [
    "form_factor",
    "color",
    "side_panel",
    "max_gpu_length_mm",
    "supported_radiator_mm",
    "brand",
    "model",
  ],
  case_fan: [
    "fan_size_mm",
    "rpm",
    "airflow",
    "noise_level",
    "pwm",
    "color",
    "rgb",
    "brand",
    "model",
  ],
  aio: [
    "radiator_size_mm",
    "socket_compat",
    "fan_size_mm",
    "color",
    "brand",
    "model",
  ],
  cooler_air: [
    "socket_compat",
    "cooler_height_mm",
    "fan_size_mm",
    "tdp",
    "color",
    "brand",
    "model",
  ],
};

/**
 * Checkbox filters offered per category. Price (slider), vendor and the
 * in-stock toggle are always available on top of this list.
 */
export const FILTER_ALLOWLIST: Record<string, string[]> = {
  cpu: [
    "brand",
    "tier",
    "generation",
    "socket",
    "cores",
    "threads",
    "tdp",
    "integrated_graphics",
    "smt",
    "ecc_support",
    "cooler_included",
    "packaging",
  ],
  motherboard: [
    "brand",
    "socket",
    "chipset",
    "form_factor",
    "memory_type",
    "wifi",
    "color",
  ],
  memory: [
    "brand",
    "memory_type",
    "capacity_gb",
    "speed_mhz",
    "cas_latency",
    "module_count",
    "ecc_support",
  ],
  gpu: [
    "brand",
    "gpu_vendor",
    "gpu_chip",
    "vram_gb",
    "memory_type",
    "cooling",
    "color",
  ],
  storage: [
    "brand",
    "capacity_gb",
    "drive_type",
    "drive_form_factor",
    "interface",
    "nvme",
  ],
  psu: ["brand", "wattage", "efficiency", "modular", "form_factor"],
  case: ["brand", "form_factor", "color", "side_panel"],
  case_fan: ["brand", "fan_size_mm", "pwm", "rgb", "color"],
  aio: ["brand", "radiator_size_mm", "socket_compat", "color"],
  cooler_air: ["brand", "socket_compat", "color"],
};

export function specPriority(category: string): string[] {
  return SPEC_PRIORITY[category] ?? GENERIC_PRIORITY;
}

export function filterAllowlist(category: string): string[] | null {
  // null = no curated list for this category: fall back to the old
  // show-everything behavior rather than showing nothing.
  return FILTER_ALLOWLIST[category] ?? null;
}

/** Sort attribute keys: priority keys first (in priority order). */
export function sortSpecKeys(category: string, keys: string[]): string[] {
  const order = specPriority(category);
  const rank = new Map(order.map((k, i) => [k, i]));
  return [...keys].sort((a, b) => {
    const ai = rank.has(a) ? rank.get(a)! : Infinity;
    const bi = rank.has(b) ? rank.get(b)! : Infinity;
    if (ai !== bi) return ai - bi;
    return a.localeCompare(b);
  });
}
