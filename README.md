# Mifrat Israeli PC Part Picker

Live price comparison for PC components sold in Israel. Daily scrapes from
local vendors merge into one catalog; a static site serves it with no backend
(except short build-link storage).

## Docs

- `PROJECT_OVERVIEW.md` — what the project does, how data flows, how the site works (plain concepts, no code).
- `GLOSSARY.md` — the project's terms (listing, product, offer, model code, variant axis, ...).
- `scraper/specs/README.md` — how the typed spec pipeline works (schema, tiers, merge, validation).
- `scraper/mfr/README.md`, `scraper/icecat/README.md`, `scraper/extract/README.md` — the manufacturer, Open Icecat and verified-AI spec sources.
- `site/README.md` — frontend dev + Cloudflare deploy.
- `nano/NANO_README.md` - Jetson Nano setup (TMS, 1PC, KSP).
- `docs/ops-alerts.md` - scrape console (`/admin/`) and the single 10:00 daily phone report (ntfy), without per-problem notifications: how it works and the one-time setup.
- `data/raw/RAW_README.md` — raw snapshot convention.
- `docs/` — design plans and audits (`merge-identity-plan.md` is the product-identity design) and agent tooling config (`docs/agents/`).
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
- Cloudflare Workers Builds auto-deploys on every push to `main`. No
  separate deploy step.

Spiders stay location-agnostic; moving a vendor between the Nano and
GitHub Actions is a scheduling change (which workflow/timer calls it), not
a rewrite.

### Decisions locked in
- **Language:** Bilingual, Hebrew + English.
- **Accounts:** Shareable build links only (`/list/<id>` via Worker + D1; legacy `#/build?...` kept). Git-as-database otherwise.
- **Scraping:** bound by the rules below.
- **Specs:** typed per-category schema (`scraper/specs/`) — `null` means unknown, never guess. See `scraper/specs/README.md`.

### About `decisions.md`

It's gitignored and stays local-only rather than pushed to the public
repo — it's the working log. `PROJECT_OVERVIEW.md` is the tracked,
public source of truth for architecture and reasoning.

## Scraping rules

Binding for every spider and spec fetcher. Code comments cite these by
number ("Scraping rules, rule 6").

**robots.txt** is ignored for cloud vendors (Ivory, YahavPC) and obeyed for
home vendors (TMS, 1PC, KSP) and for every manufacturer and foreign-retailer
spec fetcher. Never build `?limit=` URLs for TMS. Take-down on request
either way; store only what the site needs and link out to buy.

**Home-IP rules** (TMS, 1PC, KSP on the Nano — a ban hits the home
connection, so the defence is behaving like one person, not volume):

1. Once a day per vendor, strictly sequential, one request at a time, with
   randomized delays.
2. Warm up only as far as the vendor allows: the first request is a plain
   category page; follow-up calls carry the session and referer a browser
   would.
3. Browser-shaped headers: one stable current desktop user agent,
   Hebrew-Israeli accept-language, the standard fetch headers.
4. Run inside a randomized night window, never at an exact time (the
   schedule is in `nano/NANO_README.md`).
5. Replay captured parameters exactly. Never explore or fuzz an API.
6. Hard stop on blocks: a 403 or 429 ends the day. No retries against a
   block, no automatic re-runs; two block responses in one run close the
   spider.
7. Blocked repeatedly: pause several days, slow down, and if still blocked,
   drop the vendor. Never escalate against active defences.
8. No proxies of any kind, no CAPTCHA services, no WAF evasion.

**KSP** is the one logged exception (2026-10-30): its public catalog only
answers a browser-shaped TLS handshake, so the spider uses one fixed Chrome
profile per run with matching client hints, from the home IP, 3-9s between
requests, and the first 403/429 ends the run without retry. A block pauses
all KSP phases until the owner reviews it; no Eilat, detail or cover request
may follow it. The Nano's separate detail job became available on 2026-11-13
(see `docs/ksp-detail-plan.md`); it uses the same stop/pacing rules. If KSP
escalates or objects, the vendor is dropped.

Owner-reviewed KSP header update (2026-11-22): one fixed Windows Chrome/158
UA with aligned UA-hint versions, retaining the supported `chrome146` TLS
profile. PC stream tests changed from 403 to 200 when only the UA changed;
this does not prove a targeted blocklist or Nano/full-crawl acceptance. This
is a one-time header exception, not permission to rotate identities after a
block. Cookies, dynamic `tt`, pacing, completeness checks and pause rules
are unchanged. The consumed Nov 22 recovery is not re-armed by this change.
The isolated updated runner reached HTTP200 but failed the current-price
payload check; a later native browser stream returned 403. KSP remains
paused: the header patch alone has not restored end-to-end scraping.

Ivory's regular builder feed remains active. Its **Eilat category-page
scrape is paused** after 13 HTTP 403s on 2026-11-17; a green regular-price
run does not mean Eilat prices were collected.

Prefer prices already observed together: KSP's current price response feeds
regular and Eilat prices into one offer, without a second Eilat crawl. TMS
still needs its Eilat view for Eilat-only listings and branch availability.
Detail enrichment is bounded and normally fetched once per listing; it is
not a nightly price-refresh substitute. Cloud detail vendors run separately,
stop on a first block, and retain captured specs even when a phase fails.

**Manufacturer fetchers** (`scraper/mfr/`): robots obeyed, 1 request/s,
browser headers, no retries, the first 403/429 stops that brand.

## The site

`/site` is a static Vite + TypeScript frontend (no framework, no database)
reading `data/site/<category>.json` + `data/site/meta.json` —
small, per-category files written by `scraper/site_data.py` alongside
`data/catalog.json`, so browsers fetch only the category they're viewing.
See `site/README.md` for local dev and the Cloudflare deploy setup.
Deploys automatically on every push to `main`. Short
`/list/<id>` build links are the one server-side piece (`site/worker.ts` + D1);
legacy `#/build?...` links keep working.

## Repo layout

```
/scraper
  /spiders                    # tms · onepc · ksp (Nano) · ivory · yahav · plonter (kept, unscheduled)
  /specs                      # typed spec pipeline (schema, resolvers, merge, validate) — see specs/README.md
  /mfr  /icecat  /extract  /xref  # spec sources: manufacturer pages, Open Icecat, verified AI, foreign retailers
  identity.py                 # model codes, variant axes, part-number classes
  matching.py                 # listing -> product matching
  normalize_and_match.py      # builds catalog.json + review_queue.json + data/site/*.json + history
  run_spider.py               # ONLY entrypoint for real runs → data/raw/<today>/<vendor>.jsonl
/scripts                      # git_commit_push.sh + the offline check_*.py gates
/nano                         # Jetson Nano setup for TMS/1PC/KSP (NANO_README.md + systemd units)
/data
  raw/YYYY-MM-DD/<vendor>.jsonl  # daily raw snapshots (git = database)
  catalog.json                   # built catalog — the "database"
  site/<category>.json + meta.json + history/  # client-optimized site files
/.github/workflows
  scrape-cloud.yml            # ivory + yahav listings, then cloud detail pages
  normalize-and-deploy.yml    # gates, then build catalog + site JSON
  site-checks.yml             # tsc, lint, vitest, build + Python spec checks on code pushes/PRs
  extract-specs.yml           # manual verified-AI extraction
  weekly-downsample.yml       # thin old raw snapshots
  pip-audit.yml               # weekly dependency advisory check
/site                         # static Vite+TS frontend + short-link Worker (see site/README.md)
```

## Quickstart

```bash
pip install -r requirements.txt
python scraper/run_spider.py <tms|onepc|ivory|yahav|ksp>   # real run entrypoint
python -m scraper.normalize_and_match                  # rebuild catalog + site JSON
cd site; npm install; npm run dev                       # frontend (auto-copies data)
npm --prefix site run build                             # typecheck + bundle
npm --prefix site test                                  # vitest
```

Verifying a change: a single-spider test crawl, a local normalize run, the
`scripts/check_*.py` gates that cover what you touched (PROJECT_OVERVIEW §11),
and the site build.


### Special thanks

* [Devansh Awatramani](https://github.com/Devansh-awat) for giving me a lot of AI usage for free <3
