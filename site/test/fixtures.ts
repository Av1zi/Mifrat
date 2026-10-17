import type { Product, ProductSpecs } from "../src/types";

/** Minimal Product; `specs` is the only part the compatibility engine reads. */
export function product(
  id: string,
  name: string,
  specs: ProductSpecs = {},
  extra: Partial<Product> = {}
): Product {
  return {
    id,
    name,
    category: "x",
    brand: null,
    model: null,
    specs,
    vendor_count: 1,
    min_price: 100,
    in_stock: true,
    offers: [],
    ...extra,
  };
}
