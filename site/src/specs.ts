/**
 * Per-category spec metadata, generated from the one definition in
 * `scraper/specs/schema.py` (see `./specSchema.generated.ts`).
 *
 * Before the spec overhaul this file hand-maintained SPEC_PRIORITY,
 * FILTER_ALLOWLIST and VARIANT_IDENTITY_KEYS over an 800-key attribute blob
 * (`scraper/extractors.py`). Now the extractor IS the schema, so the UI reads
 * the same field list the pipeline writes: display order, filter allowlist and
 * labels all come from the schema, and only the two genuinely UI-side choices
 * (which schema-named fields make good variant pills, and which are too noisy
 * for a table column) live here.
 *
 * Values arrive already typed and already in their final unit — numbers are
 * bare (units live in the field name: `_ghz`, `_mm`, `_w`, ...). Nothing here
 * parses strings.
 */

import {
  FILTERABLE_FIELDS,
  SPEC_FIELDS,
  type SpecFieldMeta,
} from "./specSchema.generated";
import { t } from "./i18n";
import type { Lang, Product, SpecValue } from "./types";

export type { SpecFieldMeta };

/** Ordered schema fields for a category (the PDP renders exactly this order). */
export function specFields(category: string): SpecFieldMeta[] {
  return SPEC_FIELDS[category] ?? [];
}

export function specFieldMap(category: string): Map<string, SpecFieldMeta> {
  return new Map(specFields(category).map((field) => [field.name, field]));
}

/** Checkbox-filter allowlist: the schema fields flagged `filterable`. */
export function filterableSpecs(category: string): string[] {
  return FILTERABLE_FIELDS[category] ?? [];
}

/** Numeric schema fields (become range sliders, never checkboxes). */
export function isNumericSpec(field: SpecFieldMeta | undefined): boolean {
  return field?.type === "int" || field?.type === "float";
}

/**
 * Fields that carry data but never deserve a PDP row or a table column:
 * part numbers get their own SKU line in the title band.
 */
const HIDDEN_SPECS = new Set(["part_numbers"]);

export function displaySpecFields(category: string): SpecFieldMeta[] {
  return specFields(category).filter((field) => !HIDDEN_SPECS.has(field.name));
}

/** Field names in render order (used for similar-product scoring). */
export function specPriority(category: string): string[] {
  return displaySpecFields(category).map((field) => field.name);
}

/**
 * Identity keys for variant grouping (PDP pills). A product needs all of
 * these (plus a non-empty model) before it may show variant pills — without
 * identity, whole brand lines collapse into phantom "variants" (MSI H610M vs
 * B550M vs B760M as color variants, RTX 5060 vs 5060 Ti as VRAM variants).
 * Schema field names, so this matches `specs` directly.
 */
export const VARIANT_IDENTITY_KEYS: Record<string, string[]> = {
  motherboard: ["chipset", "socket"],
  gpu: ["chipset"],
  memory: ["memory_type", "total_gb"],
  psu: ["wattage_w"],
  cpu: [],
  storage: [],
  case: [],
  case_fan: [],
  aio: [],
  cooler_air: [],
  cooling_other: [],
  accessories: [],
};

/**
 * Schema fields that make good "series" variant groups (PCPP's
 * "Wattage: 850 W / 750 W / 1000 W" pills), most useful first. Only fields the
 * pipeline actually fills — folded-away twins never match and only dilute
 * signatures.
 */
export const VARIANT_KEY_PRIORITY = [
  "wattage_w",
  "tdp_w",
  "capacity_gb",
  "memory_gb",
  "speed_mhz",
  "core_count",
  "packaging",
  "length_mm",
  "color",
  "form_factor",
  "memory_type",
  "efficiency",
  "modular",
];

/**
 * User-facing spelling for enum-ish values the schema stores canonically.
 * Anything absent renders as-is ("80+ Gold", "DDR5", "M.2-2280").
 */
const ENUM_LABELS: Record<string, string> = {
  boxed: "Boxed",
  tray: "Tray",
  bulk: "Bulk",
  oem: "OEM",
  no: "No",
  semi: "Semi-Modular",
  full: "Full-Modular",
  standard: "Standard",
  reverse: "Reverse",
};

/** One spec value -> display text. Empty string means "render as unknown". */
export function formatSpecValue(value: SpecValue | undefined, lang: Lang): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? t(lang, "yesLabel") : t(lang, "noLabel");
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([name, count]) => `${count}\u00d7 ${name}`)
      .join(", ");
  }
  if (typeof value === "number") return String(value);
  return ENUM_LABELS[value.toLowerCase()] ?? value;
}

/** Read one field off a product's typed sheet (undefined when absent). */
export function specValue(product: Product, field: string): SpecValue | undefined {
  const specs = product.specs;
  return specs ? specs[field] : undefined;
}
