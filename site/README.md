# Mifrat site

Static Vite + TypeScript, no UI framework. Browsing, filtering and compatibility
run in the browser over `data/site/*.json`. Worker + D1 handle short build
links and private operations—not a dynamic catalog. [System map](../PROJECT_OVERVIEW.md)
and [operations setup](../docs/ops-alerts.md) explain those boundaries.

## Local development

From the repository root:

```bash
npm --prefix site install
npm --prefix site run dev
npm --prefix site run build
```

Dev/build copy `../data/site/` and referenced images into `public/`; build
typechecks and writes `dist/`. A normal clone includes catalog data. If absent,
obtain current data or run normalize in an appropriate validation environment.
Do not regenerate a production catalog just to start the frontend.

## Data and behaviour contracts

- Fetch same-origin category JSON lazily; schema metadata is generated from
  `scraper/specs/schema.py`, not discovered by the UI. New public fields need
  `scraper/site_data.py`'s trimming allowlist.
- Vendor images are local white-composited WebP; thumbnails are build-derived,
  never committed. The UI does not hotlink vendor hosts.
- In regular mode, category and vendor tables have a separate Eilat price
  column. Compact views, including mobile buy bars, store popovers and search,
  show a highlighted Eilat line. Only observed prices are displayed; regular
  sorts, filters and build totals are unchanged.
- Opening a shared build is view-only until the visitor edits it; it must not
  overwrite their draft. Old product ids resolve through aliases and legacy
  `#/build?...` links remain valid.
- Compatibility uses known product facts in `src/build.ts`; unknowns are not
  conflicts. Currency conversion in `src/format.ts` is best-effort and cached;
  failure falls back to ILS.
- QA shows open work only. Human-fixed/dismissed cases and recomputed
  `auto_resolved` proof history do not consume open-case caps or counts;
  shadow proposals remain open. `src/qaCases.ts` owns the public filter.

## Checks

```bash
npm --prefix site test
npm --prefix site run lint
npm --prefix site run format:check
npm --prefix site run build # includes typecheck
```

Tests use Node with browser globals stubbed where needed. ESLint has a separate
`tools/lint/` package because it needs the TypeScript JS API absent from the
site compiler; the lint script installs it as needed. Formatting is scoped to
tests/tooling, not a bulk reformat of existing `src/`. CI definitions live in
`.github/workflows/site-checks.yml` and Python checks in `scripts/run_checks.py`;
do not keep a second enumerated CI list here.

### Local browser checks

Install Playwright Chromium for these local-only checks, then build the site:

```bash
pip install playwright
python -m playwright install chromium
npm --prefix site run build
npm --prefix site run smoke
python site/scripts/eilat_smoke.py
python site/scripts/admin_smoke.py
python site/scripts/header_smoke.py
```

- Route smoke checks bilingual mobile/desktop routes for console errors,
  overflow, empty pages and unexpected 404s. `scripts/screenshots.py` without
  `--smoke` captures the screenshot matrix; its CLI narrows routes/languages/widths.
- Eilat checks both regions and bilingual mobile/desktop markup.
- Admin checks all tabs, layout, search, reload and rebuild/poll interactions
  with stub APIs and a fixed clock: no live dispatch or admin password.
- Header checks glyph proportions, menu bounds and keyboard selection across
  languages/themes/widths; `--out <directory>` saves review screenshots.

## Deploying

Cloudflare Workers Builds deploys every `main` push, code or data. Dashboard
root directory is `site`; `site/wrangler.jsonc` is the **only** config. Run
Wrangler from `site/`, never add a shadow root config.

Static assets serve directly; Worker-first routes include `/api/*`, `/list/*`
and `/admin` + `/admin/*`. The operations cron runs every half hour. Public
browsing needs no credential; private admin/event ingestion/notifications need
Worker secrets, described in [operations](../docs/ops-alerts.md). The Worker
stays locked without `ADMIN_PASSWORD`. Resource identifiers in config are public;
credentials/session state are not.

## Build sharing

Permanent six-character `/list/<id>` links need a server-side lookup; the codec
in `src/lists.ts` validates/canonicalizes builds and D1 stores insert-only
snapshots. API security covers same-origin JSON, body/id bounds, rate limiting,
dedupe and daily/lifetime growth caps. Fixed short ids do not replace legacy
long links or shorten product ids.

To provision a new environment, from `site/` with the owner's Wrangler login:

```bash
npx wrangler d1 create mifrat-lists
# Put the returned public database id in wrangler.jsonc, then:
npx wrangler d1 migrations apply mifrat-lists --remote
```

The production database already exists; do not recreate it for normal
development or deployment. Applying migrations also provisions ops tables.
Credential setup and production changes require separate owner authorization.
