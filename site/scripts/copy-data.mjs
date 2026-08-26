// Copies ../../data/site/*.json (written by scraper/site_data.py) into
// site/public/data/site/, so the frontend can always fetch same-origin
// relative paths ("/data/site/meta.json") in both `vite dev` and the
// built site — no CORS, no dependency on GitHub's raw content CDN at
// request time, no backend.
//
// Runs automatically before `npm run dev` and `npm run build` (see
// package.json). Re-run any time data/site/*.json changes locally.

import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, "..", "..", "data", "site");
const dest = path.resolve(here, "..", "public", "data", "site");

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
