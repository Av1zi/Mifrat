# Mifrat site

Static frontend for the catalog in `data/site/*.json` (written by
`scraper/site_data.py`, called from `normalize_and_match.py`), plus a tiny
Cloudflare Worker for short build links only (`worker.ts` + D1 table
`lists` — see "Build sharing" below). No build-time API calls; catalog
reads, compatibility and filtering all run in the browser.

Vite + TypeScript, no UI framework.

## How it fits the rest of the repo

- `scraper/normalize_and_match.py` builds `data/catalog.json` (full,
  internal) **and** `data/site/<category>.json` + `data/site/meta.json`
  (small, per-category, client-optimized — see `scraper/site_data.py`).
- This site fetches those `data/site/*.json` files at runtime as plain
  `fetch()` calls to same-origin relative paths (`/data/site/meta.json`
  etc). It never talks to GitHub, a database, or any server — it's a
  static file that reads static files.
- Compatibility rules are a plain TS module over the product specs already
  in this data — no separate backend. (The one exception: short build-link
  storage, see "Build sharing" below.)

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

## Checks (tests, lint, smoke)

```bash
cd site
npm test             # vitest: compat engine, routing, utils, list ids (test/)
npm run lint         # ESLint (typescript-eslint, flat config)
npx tsc -b           # typecheck (also part of npm run build)
npm run format:check # Prettier, scoped to test/ + tooling; existing src/ is not reformatted
```

- Tests are pure logic in the node environment; the ones that need `location`
  stub the global (see `test/state.test.ts`).
- ESLint lives in its own package, `tools/lint/`: typescript-eslint needs the
  TypeScript JS API (TS 6.x) while the site compiles with TS 7, which ships
  none. `npm run lint` runs `npm ci` there on first use; nothing else to set up.
- CI (`.github/workflows/site-checks.yml`) runs tsc, lint, vitest, build and the
  four `scripts/check_spec_*.py` / `check_image_pick.py` gates on any push or PR
  touching `site/**` or `scraper/specs/**`.
- **Browser smoke check** (local only, not in CI: needs a Playwright Chromium):

  ```bash
  pip install playwright && python -m playwright install chromium
  cd site && npm run build
  npm run smoke        # python scripts/screenshots.py --smoke
  ```

  Serves `dist/`, opens every route in he+en at 375px and 1280px, and fails on
  any console error, horizontal scroll, empty page or unexpected 404 view.
  Without `--smoke` the same script takes the full he/en x light/dark x
  375/768/1280 screenshot matrix into `site/screenshots/<label>/`
  (`--routes`, `--langs`, `--widths` narrow it).

## Deploying

Cloudflare Workers Builds deploys on every push to `main` (a code change in
`site/` or the daily `data/site/*.json` refresh). The repo-root
`wrangler.jsonc` and `package.json:build` exist for that build; the output
is `site/dist`, served as static assets. The Worker entry
(`site/wrangler.jsonc` -> `worker.ts`) handles only `/api/*` and `/list/*`.
No environment variables or secrets are involved.

## Build sharing and other server-side pieces

- **Build sharing**: implemented as short permanent links (`/list/<id>`,
  6 chars) backed by a minimal Worker + D1 table (`worker.ts`,
  `migrations/0001_lists.sql`, shared codec in `src/lists.ts`). A full
  build carries ~110 bits of entropy, so fixed <=8-char ids REQUIRE a
  server-side lookup — stateless URL encoding cannot do it. Legacy
  `#/build?...` links keep working. The D1 database is already created and
  its `database_id` is in `wrangler.jsonc`; to reproduce from scratch: `npx wrangler d1 create mifrat-lists`, paste the id, then
  `npx wrangler d1 execute mifrat-lists --remote --file=migrations/0001_lists.sql`.
- **Compatibility checking**: implemented client-side in `src/build.ts`
  (socket, memory type, form factor, cooler height, radiator, PSU headroom).
- **Currency conversion**: implemented (`src/format.ts`), using
  api.frankfurter.dev, cached in localStorage for a day. Best-effort only
  — if the fetch fails, the site just stays on ILS, which is why nothing
  else in the app depends on it succeeding.
