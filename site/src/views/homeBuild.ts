import { loadCategory } from "../api";
import { BUILD_SLOTS, isProductCompatibleWithBuild, knownPartWattage, numSpec } from "../build";
import { formatPrice } from "../format";
import { t } from "../i18n";
import { icon } from "../icons";
import { bestOffer, effectivePrice } from "../offers";
import { buildHash, buildItemCount, categoryHash, getStoredBuild, productHash, type BuildMap } from "../state";
import type { Currency, Lang, Product } from "../types";
import { html, mount, type Html } from "../ui/html";
import { bindThumbs, initialsOf, thumb } from "../ui/thumb";
import { vendorTag } from "../ui/vendor";
import { displayName } from "../utils";

/** Rows shown in the hero card; the builder has the rest. */
const MAX_ROWS = 8;

/**
 * The sample build is picked from today's catalog, never hard-coded: per
 * slot, in-stock parts sold by at least two stores and compatible with what
 * is already picked, then the one nearest a mid-range price percentile.
 */
const SAMPLE_PLAN: Array<{ slot: string; category: string; pct: number }> = [
  { slot: "cpu", category: "cpu", pct: 0.5 },
  { slot: "motherboard", category: "motherboard", pct: 0.45 },
  { slot: "memory", category: "memory", pct: 0.35 },
  { slot: "gpu", category: "gpu", pct: 0.55 },
  { slot: "storage", category: "storage", pct: 0.4 },
  { slot: "cooler", category: "cpu_cooler", pct: 0.5 },
  { slot: "case", category: "case", pct: 0.45 },
  { slot: "psu", category: "psu", pct: 0.4 },
];

interface Row {
  slot: string;
  product: Product;
}

function nearestToPercentile(pool: Product[], pct: number): Product | null {
  const priced = pool
    .map((p) => ({ p, price: effectivePrice(p) }))
    .filter((x): x is { p: Product; price: number } => x.price !== null)
    .sort((a, b) => a.price - b.price || a.p.id.localeCompare(b.p.id));
  if (priced.length === 0) return null;
  return priced[Math.min(priced.length - 1, Math.floor(priced.length * pct))].p;
}

async function sampleBuild(): Promise<Row[]> {
  const chosen: Record<string, Product> = {};
  const rows: Row[] = [];
  for (const step of SAMPLE_PLAN) {
    const products = await loadCategory(step.category).catch(() => [] as Product[]);
    let pool = products.filter(
      (p) => p.in_stock && effectivePrice(p) !== null && isProductCompatibleWithBuild(p, step.slot, chosen)
    );
    if (step.slot === "storage") {
      // A sample build boots from an NVMe drive, not a 3.5" archive disk.
      const nvme = pool.filter((p) => p.specs?.nvme === true || /nvme/i.test(p.name));
      if (nvme.length > 0) pool = nvme;
    }
    if (step.slot === "psu") {
      const watts = Object.entries(chosen).reduce((sum, [slot, p]) => sum + knownPartWattage(slot, p), 0);
      const need = Math.max(550, Math.ceil(watts * 1.5));
      pool = pool.filter((p) => (numSpec(p, ["wattage_w"]) ?? 0) >= need);
    }
    const widely = pool.filter((p) => p.vendor_count >= 2);
    const pick = nearestToPercentile(widely.length > 0 ? widely : pool, step.pct);
    if (!pick) continue;
    chosen[step.slot] = pick;
    rows.push({ slot: step.slot, product: pick });
  }
  return rows;
}

async function storedRows(build: BuildMap): Promise<Row[]> {
  const rows: Row[] = [];
  for (const slot of BUILD_SLOTS) {
    for (const id of build[slot.id] ?? []) {
      for (const category of slot.categories) {
        const match = (await loadCategory(category).catch(() => [] as Product[])).find((p) => p.id === id);
        if (match) {
          rows.push({ slot: slot.id, product: match });
          break;
        }
      }
    }
  }
  return rows;
}

function rowMarkup(row: Row, lang: Lang, currency: Currency): Html {
  const slot = BUILD_SLOTS.find((s) => s.id === row.slot);
  const { product } = row;
  const price = effectivePrice(product);
  const offer = bestOffer(product);
  const href = productHash(product.category, product.id);
  return html`<li class="hb__row">
    <a class="hb__slot" href="${categoryHash(product.category)}">${slot ? slot.label[lang] : product.category}</a>
    <a class="hb__part" href="${href}">${thumb(product.thumb ?? product.image, initialsOf(product.brand, product.name), "sm")}<span class="hb__name" dir="auto">${displayName(product)}</span></a>
    <span class="hb__price"><b>${price !== null ? formatPrice(price, currency, lang) : ""}</b>${offer ? vendorTag(offer.vendor) : ""}</span>
  </li>`;
}

export function homeBuildSkeleton(lang: Lang): Html {
  const own = buildItemCount(getStoredBuild()) > 0;
  return html`<header class="hb__head"><span class="hb__title">${own ? t(lang, "yourBuildTitle") : t(lang, "sampleBuildTitle")}</span></header>
    <ul class="hb__rows" aria-hidden="true">${Array.from({ length: MAX_ROWS }, () => html`<li class="hb__row hb__row--skel"><span></span><span></span><span></span></li>`)}</ul>
    <div class="hb__foot"><span class="skel-bar"></span></div>`;
}

/**
 * Hero card: the visitor's own draft build when there is one, otherwise a
 * sample build assembled from today's prices. Both open in the builder.
 */
export async function fillHomeBuild(host: HTMLElement, lang: Lang, currency: Currency): Promise<void> {
  const stored = getStoredBuild();
  const own = buildItemCount(stored) > 0;
  let rows: Row[];
  try {
    rows = own ? await storedRows(stored) : await sampleBuild();
  } catch {
    rows = [];
  }
  if (!host.isConnected) return;
  if (rows.length === 0) {
    host.hidden = true;
    return;
  }

  const map: BuildMap = {};
  for (const row of rows) map[row.slot] = [...(map[row.slot] ?? []), row.product.id];
  const total = rows.reduce((sum, row) => sum + (effectivePrice(row.product) ?? 0), 0);
  const extra = rows.length - MAX_ROWS;
  const vendors = new Set(rows.map((row) => bestOffer(row.product)?.vendor).filter(Boolean)).size;

  mount(
    host,
    html`<header class="hb__head">
      <span class="hb__title">${own ? t(lang, "yourBuildTitle") : t(lang, "sampleBuildTitle")}</span>
      <span class="hb__sub">${own ? t(lang, "yourBuildSub") : t(lang, "sampleBuildSub")}</span>
    </header>
    <ul class="hb__rows">${rows.slice(0, MAX_ROWS).map((row) => rowMarkup(row, lang, currency))}</ul>
    ${extra > 0 ? html`<p class="hb__more">${t(lang, "andMoreParts").replace("{n}", String(extra))}</p>` : ""}
    <footer class="hb__foot">
      <a class="btn btn--primary" href="${own ? "#/build" : buildHash(map)}">${t(lang, "openBuild")}${icon("forward", 15)}</a>
      <span class="hb__total"><span>${t(lang, "totalShort")}${vendors > 1 ? html` · ${t(lang, "fromStores").replace("{n}", String(vendors))}` : ""}</span><b>${formatPrice(total, currency, lang)}</b></span>
    </footer>`
  );
  bindThumbs(host);
}
