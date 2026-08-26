# PC Part Picker (Israel)

See `pc-parts-il-plan.md` for the full plan — this repo implements it. This
README tracks live status; the plan doc is the source of truth for *why*
decisions were made (per its own §0).

`DECISIONS.md` (untracked, local-only — see "About decisions.md" below)
has the fuller running log this README summarizes.

## Status: Phase 1 (hybrid pipeline MVP), in progress

### Architecture: hybrid cloud + local (rev. 2)

Zyte Scrapy Cloud was abandoned after repeated deploy/runtime failures (see
`pc-parts-il-plan.md` §3). The pipeline now runs in two places:

- **GitHub Actions** — 1PC and Plonter (Ivory joins in Phase 2, §16).
  Scheduled `scrape-cloud.yml`, ~03:30 UTC.
- **Jetson Nano at home** — TMS only, since it blocks datacenter IPs.
  See `nano/README.md` for setup. Scheduled via a systemd timer, ~06:00 UTC
  + up to 45 min jitter.
- Both write dated raw snapshots to `data/raw/YYYY-MM-DD/<vendor>.jsonl`
  and push them to this repo.
- `normalize-and-deploy.yml` (GitHub Actions, ~09:00 UTC) reads the latest
  snapshots — falling back to the most recent prior day per vendor if
  today's is missing (stale-forward, §5) — and builds `data/catalog.json`.
- Cloudflare Pages auto-deploys on every push to `main`. No separate
  deploy step.

Spiders stay location-agnostic; moving a vendor between the Nano and
GitHub Actions is a scheduling change (which workflow/timer calls it), not
a rewrite.

### Repo hygiene: Zyte artifacts removed (Aug 2026)

`scrapy.cfg`'s `[deploy]` section, `scrapinghub.yml`,
`scraper/sync_from_scrapy_cloud.py`, the old single `sync-and-deploy.yml`
workflow, the `scrapinghub` dependency, and the `SHUB_*` env vars are all
gone. The cloud scraping workflow needs **zero secrets**. See
`pc-parts-il-plan.md` §9.

### TMS robots.txt fix (Aug 2026)

The previous TMS spider forced `?limit=100` on every request, which
violates TMS's own `Disallow: /*?limit` rule — a real compliance gap
despite the project's general robots.txt-disregard decision (which never
covered this; see below). Fixed: `scraper/spiders/tms.py` no longer
constructs page-size query params; it follows the site's own pagination
links verbatim. The spider also now runs with `ROBOTSTXT_OBEY = True`
(overriding the global `False`), does a homepage warm-up request before
hitting category pages, and hard-stops after 2 block responses in one run
— see the file's docstring and `pc-parts-il-plan.md` §7.

**Open question, not yet re-verified:** old test logs (`tmp/`, gitignored)
show TMS's HTML category pages themselves 403'ing on every request in a
run from Aug 16 — not just the old configurator JSON API. Dropping
`?limit` fixes the robots.txt violation but hasn't been confirmed to fix
that blocking. Run the Nano once by hand (`nano/README.md` step 6) and
check `journalctl` before trusting this unattended.

### Decisions locked in
- **Language:** Bilingual, Hebrew + English.
- **Accounts:** Not for v1 — shareable build links only. Git-as-database
  (Option A) until a real write path is needed.
- **KSP:** Out of scope for v1 (`spiders/ksp.py` stays an isolated, Phase
  5 stub). API application submitted, approval pending.
- **robots.txt:** Ignored for cloud-run vendors (1PC, Plonter, Ivory);
  **followed** for locally-run vendors (currently TMS on the Nano) — see
  `pc-parts-il-plan.md` §14 and `DECISIONS.md`. Never extended to KSP's
  active WAF/bot-management defenses either way.

### About `decisions.md`

It's gitignored and stays local-only rather than pushed to the public
repo — it's the working log, more candid/detailed than this README, and
covers the home-IP protection rules in more depth than belongs in a public
file. `pc-parts-il-plan.md` remains the tracked, public source of truth for
architecture and reasoning. If you're picking this repo up without that
file, `pc-parts-il-plan.md` has everything needed.

## The site (Aug 2026)

`/site` is a static Vite + TypeScript frontend (no framework, no backend,
no database) reading `data/site/<category>.json` + `data/site/meta.json` —
small, per-category files written by `scraper/site_data.py` alongside
`data/catalog.json`, so browsers fetch only the category they're viewing
instead of the full ~20MB catalog. See `site/README.md` for local dev and
the exact Cloudflare Pages dashboard settings (root directory, build
command, output directory — those live in Cloudflare's UI, not a repo
file). Deploys automatically on every push to `main`, same as the rest of
the pipeline.

## Repo layout

```
/scrapy.cfg                   # settings pointer only — no Zyte [deploy] section
/scraper
  /spiders
    tms.py                    # HTML category pages + Claris stock POST — Nano only
    onepc.py                  # PCBuilder/CategoryViewData, all 10 categories mapped
    plonter.py                # alon.tmpl full-catalog feed — missing product URLs, see TODO
    ivory.py                  # stub — Phase 2
    ksp.py                    # disabled stub, Phase 5 only
  items.py                    # shared Item schema
  settings.py                 # rate limiting, robots.txt (global default), encoding
  run_spider.py                # shared entrypoint: runs one spider, writes
                                # data/raw/<today>/<spider>.jsonl — used by
                                # both GitHub Actions and the Nano
  normalize_and_match.py       # Phase 1: stale-forward passthrough. Phase 2: real matching
/scripts
  git_commit_push.sh           # shared commit+push-with-rebase-retry (§10)
/nano                          # Jetson Nano setup for TMS (§4/§7/§9)
  README.md
  run_tms.sh
  pc-parts-il-tms.service
  pc-parts-il-tms.timer
/data
  raw/YYYY-MM-DD/<vendor>.jsonl  # daily raw snapshots, one file per vendor
  catalog.json                   # built by normalize_and_match.py — the "database"
/.github/workflows
  scrape-cloud.yml              # 1PC + Plonter, ~03:30 UTC
  normalize-and-deploy.yml      # build catalog.json, ~09:00 UTC
  weekly-downsample.yml         # Phase 4, disabled stub
```

## Next steps (Phase 1, per plan §16)

1. Run the Nano once by hand and confirm TMS actually still works against
   the robots.txt-compliant pagination (see the open question above).
2. Confirm `scrape-cloud.yml` and `normalize-and-deploy.yml` run clean on
   a real push (no secrets needed, but worth watching the first few runs).
3. Scaffold `/site` (Astro or Next.js static export) with a bare-bones page
   listing whatever's in `data/catalog.json` — no matching/compatibility
   logic yet, per the plan's explicit Phase 1 scope.
4. Prove the whole loop runs unattended for a week before starting Phase 2
   (Ivory, real matching).
