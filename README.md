# Mifrat — PC Part Picker (Israel)

Live price comparison for PC components sold in Israel. Daily scrapes from
local vendors merge into one catalog; a static site serves it with no backend
(except short build-link storage).

## Docs

- `PROJECT_OVERVIEW.md` — what the project does, how data flows, how the site works (plain concepts, no code).
- `scraper/specs/README.md` — how the typed spec pipeline works (schema, tiers, merge, validation).
- `site/README.md` — frontend dev + Cloudflare deploy.
- `nano/NANO_README.md` — Jetson Nano setup (TMS scraper).
- `data/raw/RAW_README.md` — raw snapshot convention.
- `AGENTS.md` + `decisions.md` (both local-only, gitignored) — agent operating rules + running decision log.

## Status: live pipeline, in production

### Architecture: hybrid cloud + local

Daily scrapes run in two places:

- **GitHub Actions** — `ivory`, `yahav` (`scrape-cloud.yml`).
  Plonter dropped 2026-09-29 (datacenter IP-class block, spider kept for a
  possible re-scrape).
- **Jetson Nano at home** — `tms`, `onepc` and (since 2026-10-30) `ksp`,
  because those vendors block datacenter IPs. See `nano/NANO_README.md` for
  setup.
- Both write dated raw snapshots to `data/raw/YYYY-MM-DD/<vendor>.jsonl`
  and push them to this repo.
- `normalize-and-deploy.yml` reads the latest
  snapshots — falling back to the most recent prior day per vendor if
  today's is missing (stale-forward, 14d window) — and builds `data/catalog.json`.
- Cloudflare Pages auto-deploys on every push to `main`. No separate
  deploy step.

Spiders stay location-agnostic; moving a vendor between the Nano and
GitHub Actions is a scheduling change (which workflow/timer calls it), not
a rewrite.

### Decisions locked in
- **Language:** Bilingual, Hebrew + English.
- **Accounts:** Shareable build links only (`/list/<id>` via Worker + D1; legacy `#/build?...` kept). Git-as-database otherwise.
- **KSP:** Active since 2026-10-30 as a **home-run, listing-only** vendor.
  Its public catalog is fetched with a Chrome TLS profile (`curl_cffi`);
  its `/m_action/api/item/<uin>` detail endpoint is WAF-blocked (403), so
  there is no KSP detail/MPN enrichment. One run/day, 1 request at a time,
  3-9s apart, first 403 stops the run (429 retried 4x), no proxies or CAPTCHA
  solving. The exception is logged in `decisions.md`.
- **robots.txt:** Ignored for cloud-run vendors;
  **followed** for locally-run vendors (TMS, 1PC, KSP on the Nano). TMS:
  one run/day, sequential, throttled, browser headers, hard-stop after
  2x 403/429. KSP: one run/day, one request at a time, 3-9s apart,
  first 403 stops the run (429 retried 4x). Never escalate against blocks or
  WAFs.
- **Specs:** typed per-category schema (`scraper/specs/`) — `null` means unknown, never guess. See `scraper/specs/README.md`.

### About `decisions.md`

It's gitignored and stays local-only rather than pushed to the public
repo — it's the working log. `PROJECT_OVERVIEW.md` is the tracked,
public source of truth for architecture and reasoning.

## The site

`/site` is a static Vite + TypeScript frontend (no framework, no database)
reading `data/site/<category>.json` + `data/site/meta.json` —
small, per-category files written by `scraper/site_data.py` alongside
`data/catalog.json`, so browsers fetch only the category they're viewing.
See `site/README.md` for local dev and the exact Cloudflare Pages dashboard settings
(root directory, build command, output directory — those live in Cloudflare's UI,
not a repo file). Deploys automatically on every push to `main`. Short
`/list/<id>` build links are the one server-side piece (`site/worker.ts` + D1);
legacy `#/build?...` links keep working.

## Repo layout

```
/scraper
  /spiders                    # tms · onepc · ksp (Nano) · ivory · yahav · plonter (kept, unscheduled)
  /specs                      # typed spec pipeline (schema, resolvers, merge, validate) — see specs/README.md
  normalize_and_match.py      # builds catalog.json + review_queue.json + data/site/*.json + history
  run_spider.py               # ONLY entrypoint for real runs → data/raw/<today>/<vendor>.jsonl
/scripts                      # git_commit_push.sh + spec/size/detail gates
/nano                         # Jetson Nano setup for TMS/1PC/KSP (NANO_README.md + systemd units)
/data
  raw/YYYY-MM-DD/<vendor>.jsonl  # daily raw snapshots (git = database)
  catalog.json                   # built catalog — the "database"
  site/<category>.json + meta.json + history/  # client-optimized site files
/.github/workflows
  scrape-cloud.yml            # ivory + yahav
  normalize-and-deploy.yml    # build catalog + site JSON
/site                         # static Vite+TS frontend + short-link Worker (see site/README.md)
```

## Quickstart

```bash
pip install -r requirements.txt
python scraper/run_spider.py <tms|onepc|ivory|yahav|ksp>   # real run entrypoint
python -m scraper.normalize_and_match                  # rebuild catalog + site JSON
cd site; npm install; npm run dev                       # frontend (auto-copies data)
npm --prefix site run build                             # typecheck + bundle
```

See `AGENTS.md` for the full command + hygiene rules (gitignored, local-only).
