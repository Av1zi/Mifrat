# Mifrat — project overview

A PC-part price comparison and build planner for Israel. This is the system
map, not a release log or setup manual. [Documentation map](docs/README.md)
links to the task-specific guides; [the preserved long overview](docs/archive/2026-11-22/PROJECT_OVERVIEW.md)
contains historical detail, not current instructions.

## 1. What this project is

Vendor listings become products with comparable offers. Visitors browse,
filter, compare, inspect price history and assemble builds with compatibility
guidance. Hebrew and English are supported. No visitor account is required.

The catalog is versioned files in git, not a database service. Browsing and
compatibility run in the browser. Cloudflare Worker + D1 handle shared build
links and private operations; they do not serve a dynamic catalog.

## 2. Big picture — capture, merge, serve

```text
vendor spiders → data/raw/<night>/<vendor>.jsonl
                         ↓
                 normalize and match
                         ↓
       catalog + category JSON + history + ops report
                         ↓
         git push → Cloudflare build → static site
```

Ivory and Yahav run in GitHub Actions; TMS, 1PC and KSP use the home Nano.
Spiders are location-independent; workflows and timers choose where they run.
KSP is currently paused, not a working nightly source. Older snapshots may
stale-forward for up to 14 days; beyond that the vendor is skipped.

## 3. Repository map

| Area | Responsibility |
|---|---|
| `scraper/spiders/` | Vendor listing/detail capture |
| `scraper/identity.py`, `matching.py` | Physical identity and listing grouping |
| `scraper/specs/` | Typed facts, source trust, validation and reporting |
| `scraper/mfr/`, `icecat/`, `extract/`, `xref/` | Additional spec sources |
| `scraper/normalize_and_match.py` | Catalog/public-data orchestration |
| `data/` | Observations, human ledgers and generated outputs |
| `site/` | Vite + TypeScript frontend, Worker and D1 migrations |
| `nano/`, `.github/workflows/` | Home and cloud automation |
| `scripts/run_checks.py` | Authoritative check list and severity levels |

## 4. Collection and scheduling

`scraper/run_spider.py` is the real-run entrypoint. Test crawls write ignored
`*_test.jsonl`, never production snapshots. A snapshot is one vendor's view
for a scrape night: 21:00 UTC to the next 21:00 UTC, named by the ending date.
Older folders retain their historical UTC names. See
[raw data](data/raw/RAW_README.md) for the storage contract.

[README scraping rules](README.md#scraping-rules) govern every request. Home
vendors run sequentially, with randomized night scheduling and no catch-up
after downtime. Cloud scheduling has an Israel-time cutoff. Exact schedules
live in the workflows/timers, explained in [the Nano guide](nano/NANO_README.md).
Blocks mean stop and de-escalate, not retry or rotate identities.

KSP's Nov 22 one-shot recovery failed and consumed its marker. The approved
fixed header update did not restore end-to-end scraping. Listing/detail timers
remain disabled; all phases share an owner-reviewed persistent pause. Read
[the stream status](docs/ksp-stream-transport.md) before any KSP work. Plonter
is unscheduled; its code and snapshots are retained as history.

## 5. Detail enrichment

Listing crawls capture prices; bounded detail jobs collect specs and images
for listings still pending. A nonempty spec table is required before marking
a listing complete. Detail observations are append-only.

Cloud detail vendors run independently through `scraper.run_cloud_detail`.
A first block stops that vendor and skips images; already captured specs are
retained and bundled before failure is reported. Home detail uses the same
source policies. KSP detail was implemented Nov 13 but is currently disabled.

## 6. Normalize and match

The normalizer loads recent observations, cleans text, deduplicates by newest
observation, merges detail data, groups listings, builds specs and writes
public data. It does not replace unknown facts with guesses.

### Identity and offers

A product is one physical SKU: category + canonical model code + variant axes.
`identity.py` owns the readers and axes. Full CPU suffixes compare exactly
(`245K` is not `245KF`); Box and Tray remain separate. A listing stays with
its own packaging evidence; conflicting labels produce QA, not a move based
on equal prices. Copied retailer C-codes are not packaging evidence.

Manual products and blocked pairs come first. Then grouping uses model-code
identity, compatible axes and part-number evidence, followed by reconciliation
and verified identifier joins. Different manufacturer part numbers distinguish
variants; retailer numbers alone are not physical identity. After splitting,
the remaining members must still have connecting evidence. Ambiguous permitted
identity merges are flagged; fuzzy suggestions are review-only, never automatic.

Names are rebuilt from identity and validated specs. Retired product ids alias
to live successors so links, saved builds, extraction and history can resolve.
The original [identity design](docs/merge-identity-plan.md) explains the trade-off;
later refinements are in the code and local decisions.

Decorated vendor twins may fold into one displayed offer, retaining aliases
internally and deal/clearance chips publicly. Plain offers outrank bundle-only
offers, even when the plain one is out of stock. Store sales are not new-PC
deals. Bundle-only history is excluded when a plain priced offer exists.

### Specs and prices

[The spec guide](scraper/specs/README.md) owns schema, tiers, reference joins,
title witnesses, inference and schema-change steps. `specs` is authoritative;
the transitional `attributes` view is derived, never a competing fact store.

Eilat prices are observed, never calculated. Inline and legacy separate
observations are supported with their own freshness. They do not affect
regular-mode minima, sorting, totals or price history. Ivory Eilat collection
is paused independently of its working regular feed. KSP's stream is designed
to collect both prices together, but live recovery remains unresolved.

## 7. Data artifacts

| Artifact | Meaning |
|---|---|
| `data/raw/` | Vendor observations; inputs, not browser payloads |
| `data/catalog.json` | Full internal products, listings, specs and provenance |
| `data/matching/`, `data/specs/` | Human grouping, dismissal and override ledgers |
| `data/site/` | Trimmed categories, index, metadata, QA, specs report and history |
| `data/ops/` | Recomputed crawl/change facts and check results |
| `data/images/` | Referenced local cover photos plus one runner-up |
| Enrichment JSON | Cached source facts read by normalize |

Catalog and public files must be one coherent build: identical product set
and generation timestamp where required. Generated-data conflicts are resolved
by rebuilding from merged code and inputs, not text-merging JSON. Images and
raw observations are inputs, not generated catalog outputs.

## 8. Website

The static site fetches metadata, a search index and only the categories/history
needed by the current page. Schema-generated metadata drives labels, filters
and spec order. Product ids and alias resolution connect navigation and builds.

Category pages browse/filter/pick; product pages show offers, specs and history;
the builder warns only when known facts conflict. Comparison is within one
category, up to four products. Saved parts and drafts stay in local storage.

Most routes use hashes. `/list/<id>` stores a shared build in D1; legacy long
links still work. Opening a shared build is view-only until the visitor edits
it, and does not overwrite their draft. Short-link APIs validate size, shape
and origin, rate-limit requests, deduplicate builds and cap storage growth.

Images are same-origin WebP, with white-composited transparency and derived
thumbnails. The downloader bounds hosts, redirects, body size, time and pixel
count; the browser never hotlinks vendor images. Language, theme and display
currency are preferences; failed currency conversion falls back to shekels.
[Site development/deployment](site/README.md) has runnable commands.

## 9. Operations and automation

New raw data or cloud-scrape completion triggers normalize; unchanged inputs
skip it. Cloudflare Workers Builds deploys each `main` push. A code-only check
workflow verifies changes without rebuilding the production catalog.

Publishing workflows separate read-only build jobs from narrowly scoped write
jobs using validated short-lived bundles. Human releases use owner attribution
and preserve unrelated local work. A pushed commit, passed CI and served
Cloudflare deployment are different facts; verify each before claiming it.

The private `/admin/` console combines crawl facts, lifecycle changes, Nano
phase events and check findings. Missing once is not gone: gone requires two
valid crawls spanning at least 36 hours; partial crawls never count absences.
The sole phone message is the 10:00 Israel daily report, quiet when all is OK.
Worker outage means Nano journal logging, not extra direct pushes.
[Operations setup](docs/ops-alerts.md) owns auth, secrets and report setup.

## 10. Constraints to preserve

- `TWISTED_REACTOR` stays first in `scraper/settings.py`; spiders retain both
  `start()` and `start_requests()` for environment compatibility.
- New frontend fields must survive the `site_data.py` trimming allowlist.
- `site/wrangler.jsonc` is the only Worker config; run Wrangler from `site/`.
- Credentials stay out of git and logs. Worker/D1 identifiers are public;
  tokens, private keys and sessions are not. Rotate an exposed credential.

## 11. How to verify changes

`scripts/run_checks.py` declares the checks: **code** and **integrity** failures
block, **quality** failures warn without freezing fresh prices. Warnings appear
in operations and escalate in severity after three nights, never into blockers.
Golden fixture exit codes still distinguish failure from churn; the central
runner maps both to quality warnings. Population protection is separate.

For collection/pipeline changes: use one policy-permitted test crawl to an
ignored file, a local normalize in an isolated output environment, the checks
covering the change, site tests and build. A paused source is not permission
to crawl it for verification; use offline fixtures and disclose the live gap.

```bash
python scripts/run_checks.py --suite code
npm --prefix site test
npm --prefix site run lint
npm --prefix site run build
```

The publish suite follows normalize. It writes `data/ops/checks.json`; run it
in the isolated validation environment, not over unrelated production work.
For documentation-only changes, verify links, preserved rules and archives;
no crawl or catalog regeneration is needed. Setup commands are in the README.

## 12. Glossary

[GLOSSARY.md](GLOSSARY.md) defines the domain terms without implementation
details. Keep definitions there and operational instructions in their guides.
