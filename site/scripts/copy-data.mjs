// Copies ../../data/site/*.json (written by scraper/site_data.py) into
// site/public/data/site/, so the frontend can always fetch same-origin
// relative paths ("/data/site/meta.json") in both `vite dev` and the
// built site — no CORS, no dependency on GitHub's raw content CDN at
// request time, no backend.
//
// Also copies the product photos referenced by those JSON files from
// ../../data/images/<vendor>/<sku>.webp into site/public/images/... —
// same-origin hosting so vendor sites can't break our photos by moving
// or deleting theirs. Only referenced files are copied (a few thousand),
// not the whole archive.
//
// List-page thumbnails (/images/<vendor>/thumbs/<sku>.webp, 128px long edge,
// WebP q70) are NOT stored in the repo: they are derived here, with sharp,
// from the cover of the same name — and only for the thumbs the JSON
// references. Without sharp (unsupported platform) the full cover is copied
// instead, so pages still render, just heavier.
//
// Runs automatically before `npm run dev` and `npm run build` (see
// package.json). Re-run any time data/site/*.json changes locally.

import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

let sharp = null;
try {
  sharp = (await import("sharp")).default;
} catch {
  console.warn("[copy-data] sharp unavailable - list thumbnails fall back to full covers");
}

const THUMB_EDGE = 128;
const THUMB_QUALITY = 70;
const MENU_EDGE = 256;
const MENU_QUALITY = 74;

// Derived derivative subdirectories: /images/<vendor>/<dir>/<rest> is built
// here with sharp from the same-name cover /images/<vendor>/<rest>.
const DERIVED_DIRS = { thumbs: { edge: THUMB_EDGE, quality: THUMB_QUALITY }, covers256: { edge: MENU_EDGE, quality: MENU_QUALITY } };

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, "..", "..", "data", "site");
const dest = path.resolve(here, "..", "public", "data", "site");
const imagesSrc = path.resolve(here, "..", "..", "data", "images");
const imagesDest = path.resolve(here, "..", "public", "images");

if (!existsSync(src)) {
  console.error(
    `[copy-data] ${src} does not exist.\n` +
      "Run the pipeline first from the repo root:\n" +
      "  python scraper/normalize_and_match.py\n" +
      "or pull the latest data/site/*.json committed by GitHub Actions."
  );
  process.exit(1);
}

rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });

console.log(`[copy-data] copied ${src} -> ${dest}`);

// Collect every /images/<vendor>/<file> referenced by the site JSON layer
// (category files + per-category history files).
const referenced = new Set();
const collect = (dir) => {
  if (!existsSync(dir)) return;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collect(full);
      continue;
    }
    if (!entry.name.endsWith(".json")) continue;
    const text = readFileSync(full, "utf8");
    const re = /"\/images\/([^"]+)"/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      try {
        referenced.add(decodeURIComponent(m[1]));
      } catch {
        referenced.add(m[1]);
      }
    }
  }
};
collect(dest);

rmSync(imagesDest, { recursive: true, force: true });
let copied = 0;
let thumbs = 0;
let menus = 0;
let missing = 0;

// /images/<vendor>/<dir>/<rest> is derived from /images/<vendor>/<rest>.
const deriveOf = (rel) => {
  const parts = rel.split("/");
  const spec = parts.length > 2 ? DERIVED_DIRS[parts[1]] : null;
  if (!spec) return null;
  return { cover: [parts[0], ...parts.slice(2)].join("/"), ...spec };
};

const copyOne = async (rel) => {
  const derived = deriveOf(rel);
  const from = path.join(imagesSrc, derived ? derived.cover : rel);
  const to = path.join(imagesDest, rel);
  if (!existsSync(from)) {
    missing++;
    return;
  }
  mkdirSync(path.dirname(to), { recursive: true });
  if (derived && sharp) {
    await sharp(from)
      .resize(derived.edge, derived.edge, { fit: "inside", withoutEnlargement: true })
      .webp({ quality: derived.quality })
      .toFile(to);
    if (derived.edge === THUMB_EDGE) thumbs++;
    else menus++;
    return;
  }
  cpSync(from, to);
  if (derived) {
    if (derived.edge === THUMB_EDGE) thumbs++;
    else menus++;
  } else {
    copied++;
  }
};

const queue = [...referenced];
await Promise.all(
  Array.from({ length: 12 }, async () => {
    for (let rel = queue.pop(); rel !== undefined; rel = queue.pop()) await copyOne(rel);
  })
);

const totalRefs = referenced.size;
const resolved = copied + thumbs + menus;
const ratio = totalRefs ? resolved / totalRefs : 1;
console.log(
  `[copy-data] images: ${copied} covers, ${thumbs} thumbnails, ${menus} menu covers ` +
    `-> ${imagesDest} (${resolved}/${totalRefs} referenced resolved, ` +
    `${(ratio * 100).toFixed(1)}%)` +
    (missing > 0 ? `, ${missing} missing on disk` : "")
);

// A deploy that ships without its photos shows initials everywhere and looks
// broken. Refuse to build when too many referenced images are not on disk —
// the fix is to run `python -m scraper.download_images --from-catalog` (or
// pull the latest data/images) and rebuild. Attribute-less products are rare
// (a handful of vendor 404s), so 90% is a safe floor.
if (totalRefs > 0 && ratio < 0.9) {
  console.error(
    `[copy-data] FAIL: only ${(ratio * 100).toFixed(1)}% of referenced images exist under ` +
      `${imagesSrc} (${missing} missing).\n` +
      "  Backfill them from the catalog, then rebuild:\n" +
      "    python -m scraper.download_images --from-catalog"
  );
  process.exit(1);
}

// ---- sitemap.xml -----------------------------------------------------------
// Generated from the same JSON, so it always matches the deployed catalog.
// Routes are hash routes (#/c/<category>, #/p/<category>/<id>), the only
// route form the site serves; see decisions.md for what that means for
// crawlers. Gitignored (site/.gitignore), rebuilt on every dev/build run.
const origin = (process.env.SITE_ORIGIN ?? "https://mifrat.net").replace(/\/+$/, "");
const xmlEscape = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const meta = JSON.parse(readFileSync(path.join(dest, "meta.json"), "utf8"));
const lastmod = typeof meta.generated_at === "string" ? meta.generated_at.slice(0, 10) : null;

const routes = ["/", "/#/categories", "/#/build", "/#/qa"];
let products = 0;
for (const cat of meta.categories ?? []) {
  if (!cat.count) continue;
  routes.push(`/#/c/${encodeURIComponent(cat.id)}`);
  const file = path.join(dest, `${cat.id}.json`);
  if (!existsSync(file)) continue;
  for (const product of JSON.parse(readFileSync(file, "utf8"))) {
    routes.push(`/#/p/${encodeURIComponent(cat.id)}/${encodeURIComponent(product.id)}`);
    products++;
  }
}

const urls = routes
  .map((route) => `  <url><loc>${xmlEscape(origin + route)}</loc>${lastmod ? `<lastmod>${lastmod}</lastmod>` : ""}</url>`)
  .join("\n");
writeFileSync(
  path.resolve(here, "..", "public", "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`
);
console.log(`[copy-data] wrote sitemap.xml (${routes.length} urls, ${products} products)`);
