import { attributeLabel } from "../../i18n";
import { formatSpecValue, specFields, specUnit, specValue } from "../../specs";
import type { Lang, Product } from "../../types";
import { canonicalSpecText } from "./data";

const MAX_COLUMNS = 4;

/**
 * Curated scan columns per category: a display concern only (the schema
 * order still drives the filter rail and the product sheet). Picks favour
 * fields that are broadly filled and short per cell; wide list-valued fields
 * (chipset_support, sockets) are excluded on purpose. Categories not listed
 * fall back to schema order + coverage.
 */
const COLUMN_PRIORITY: Record<string, string[]> = {
  cpu: ["socket", "core_count", "thread_count", "tdp_w"],
  motherboard: ["socket", "chipset", "memory_type", "form_factor"],
  memory: ["memory_type", "speed_mhz", "total_gb", "cas_latency"],
  storage: ["capacity_gb", "type", "interface", "form_factor"],
  gpu: ["chip_manufacturer", "memory_gb", "memory_type", "interface"],
  psu: ["wattage_w", "efficiency", "type", "modular"],
  case: ["type", "color", "drive_bays_35", "volume_l"],
  aio: ["radiator_size_mm", "fan_rpm_max", "color"],
  cooler_air: ["fan_size_mm", "fan_rpm_max", "tdp_w", "color"],
  case_fan: ["size_mm", "rpm_max", "color", "pwm"],
};

/** Share of products that must carry a field before it becomes a column. */
const MIN_COVERAGE = 0.05;

/** Data-driven column choice: curated list first, then schema order, both gated on coverage. */
export function pickColumns(products: Product[], category: string): string[] {
  const skip = new Set(["manufacturer", "model", "part_numbers"]);
  const known = new Set(specFields(category).map((field) => field.name));
  const n = Math.max(1, products.length);
  const coverage = (name: string): number => {
    let filled = 0;
    for (const p of products) if (canonicalSpecText(p, name)) filled++;
    return filled / n;
  };
  const curated = (COLUMN_PRIORITY[category] ?? []).filter(
    (name) => known.has(name) && coverage(name) >= MIN_COVERAGE
  );
  if (curated.length > 0) return curated.slice(0, MAX_COLUMNS);
  return specFields(category)
    .filter((field) => !skip.has(field.name) && coverage(field.name) >= MIN_COVERAGE)
    .slice(0, MAX_COLUMNS)
    .map((field) => field.name);
}

/**
 * Short chip text for one field, or "" when the product has no value (empty
 * chips are omitted, never rendered as "unknown"). Numbers carry their unit
 * ("105 W"), counts their label ("Core Count 8"), flags just their label.
 */
export function chipText(product: Product, field: string, lang: Lang): string {
  const value = specValue(product, field);
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? attributeLabel(field, lang) : "";
  if (typeof value === "number") {
    const unit = specUnit(field);
    return unit ? `${value} ${unit}` : `${attributeLabel(field, lang)} ${value}`;
  }
  return formatSpecValue(value, lang);
}
