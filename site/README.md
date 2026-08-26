# Mifrat site

Static frontend for the catalog in `data/site/*.json` (written by
`scraper/site_data.py`, called from `normalize_and_match.py`). No backend,
no database, no build-time API calls — everything runs in the browser.

Vite + TypeScript, no UI framework. The whole app is ~16KB of JS
(~6.5KB gzipped).

## How it fits the rest of the repo

- `scraper/normalize_and_match.py` builds `data/catalog.json` (full,
  internal) **and** `data/site/<category>.json` + `data/site/meta.json`
  (small, per-category, client-optimized — see `scraper/site_data.py`).
- This site fetches those `data/site/*.json` files at runtime as plain
  `fetch()` calls to same-origin relative paths (`/data/site/meta.json`
  etc). It never talks to GitHub, a database, or any server — it's a
  static file that reads static files.
- Compatibility rules, if/when Phase 3 happens, belong as a plain TS
  module operating on `attributes` already in this data — no separate
  backend or graph database. See the project's `decisions.md` for why.

## Local development

The data files live outside this folder (`../data/site/`, i.e. the repo's
`data/site/`), so they need to be copied in before the dev server can
serve them. This happens automatically:

```bash
cd site
npm install
npm run dev      # copies ../data/site -> public/data/site, then starts Vite
```

If `../data/site` doesn't exist yet (fresh clone with no catalog built
locally), either run the pipeline first from the repo root:

```bash
python scraper/normalize_and_match.py
```

or just `git pull` — GitHub Actions commits `data/site/*.json` daily, so a
normal clone already has it.

`npm run build` does the same copy step, then builds to `site/dist/`.

## Deploying on Cloudflare Pages

One-time setup in the Cloudflare dashboard (this can't be done from a
repo file — Pages project settings live in Cloudflare's UI):

| Setting | Value |
| --- | --- |
| Framework preset | Vite |
| Root directory | `site` |
| Build command | `npm run build` |
| Build output directory | `dist` |

Root directory being `site` still gives the build access to `../data`
within the same checkout — `npm run build`'s copy step reads
`../../data/site` relative to `site/scripts/copy-data.mjs`, which resolves
correctly. No environment variables or secrets needed, consistent with the
rest of this project (`decisions.md`: "cloud scraping workflow needs zero
secrets" — same is true for this site).

Every push to `main` — whether it's new code in `site/` or a fresh
`data/site/*.json` from the daily normalize job — triggers a Cloudflare
Pages rebuild automatically. No separate deploy step, no CI change needed
on this repo's side.

## What's intentionally not here yet

- **Build sharing** (Phase 3+): not implemented. When it lands, encode the
  selected product IDs into the URL itself (no backend/DB needed) —
  see `decisions.md` for why a backend + database was rejected for this.
- **Compatibility checking** (Phase 3): not implemented. `attributes` on
  each product (socket, chipset, memory_type, form_factor, …) already has
  what a plain client-side rules module would need.
- **Currency conversion**: implemented (`src/format.ts`), using
  api.frankfurter.dev, cached in localStorage for a day. Best-effort only
  — if the fetch fails, the site just stays on ILS, which is why nothing
  else in the app depends on it succeeding.
