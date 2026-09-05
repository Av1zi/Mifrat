// Copies ../../data/site/*.json (written by scraper/site_data.py) into
// site/public/data/site/, so the frontend can always fetch same-origin
// relative paths ("/data/site/meta.json") in both `vite dev` and the
// built site — no CORS, no dependency on GitHub's raw content CDN at
// request time, no backend.
//
// Also copies the product photos referenced by those JSON files from
// ../../data/images/<vendor>/<sku>.jpg into site/public/images/... —
// same-origin hosting so vendor sites can't break our photos by moving
// or deleting theirs. Only referenced files are copied (a few thousand),
// not the whole archive.
//
// Runs automatically before `npm run dev` and `npm run build` (see
// package.json). Re-run any time data/site/*.json changes locally.

import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

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
let missing = 0;
for (const rel of referenced) {
  const from = path.join(imagesSrc, rel);
  const to = path.join(imagesDest, rel);
  if (!existsSync(from)) {
    missing++;
    continue;
  }
  mkdirSync(path.dirname(to), { recursive: true });
  cpSync(from, to);
  copied++;
}

console.log(
  `[copy-data] copied ${copied} referenced images -> ${imagesDest}` +
    (missing > 0 ? ` (${missing} referenced files missing on disk)` : "")
);
