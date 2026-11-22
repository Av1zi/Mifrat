# Mifrat Israeli PC Part Picker

Live price comparison and build planning for PC components sold in Israel.
Daily vendor snapshots merge into a catalog; a bilingual static Vite +
TypeScript site provides browsing and compatibility. Git is the catalog's
database. Worker + D1 provide short build links and private operations.

## Docs

- [Documentation map](docs/README.md) — choose the guide for your task.
- [Project overview](PROJECT_OVERVIEW.md) — data flow and system boundaries.
- [Glossary](GLOSSARY.md) — listing, product, offer and other domain terms.
- [Specs](scraper/specs/README.md), [site](site/README.md),
  [Nano](nano/NANO_README.md) — component development and setup.
- [Operations](docs/ops-alerts.md) — private console and daily phone report.

Local-only, gitignored `AGENTS.md` and `decisions.md` hold agent instructions
and current binding decisions. They and their private history are not public
documentation. Dated audits and [archived references](docs/archive/2026-11-22/README.md)
are evidence, not current run instructions.

## Pipeline and current source status

```text
spiders → data/raw/<night>/<vendor>.jsonl
        → normalize → catalog + data/site/ + history + operations
        → main push → Cloudflare Workers Builds
```

Ivory and Yahav listing crawls run in GitHub Actions. TMS, 1PC and KSP use
the home Nano because they block datacenter access. Missing snapshots
stale-forward for up to 14 days. Normalize runs after new scrape data, not on
a separate cron; Cloudflare builds every `main` push.

**KSP remains paused** after the failed Nov 22 recovery. Its consumed one-shot
timer must not be reinstalled or re-armed; the fixed header update did not
restore end-to-end prices. Read [KSP status](docs/ksp-stream-transport.md)
before any request. **Ivory Eilat is paused** after Nov 17 blocks; its regular
builder feed remains active. Plonter is unscheduled, with code/history retained.

## Scraping rules

Binding for every spider and spec fetcher. Numbered home-IP rules are stable:
code comments cite them, for example "Scraping rules, rule 6".

**robots.txt** is ignored for cloud vendors (Ivory, YahavPC) and obeyed for
home vendors (TMS, 1PC, KSP) and every manufacturer/foreign-retailer spec
fetcher, except explicitly documented owner-approved narrow overrides in the
source guide. Never build `?limit=` URLs for TMS. Take down on request, store
only what the site needs, and link out to buy.

**Home-IP rules** (a ban affects the owner's home connection):

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

**KSP's documented exception:** one fixed browser-shaped TLS profile,
sequential requests 3–9s apart (6s base); the first 403/429/challenge stops all
listing, Eilat, detail and cover phases and persists an owner-reviewed pause.
The Nov 22 approved Windows Chrome/158 UA/hints retain `chrome146` TLS.
This deliberate mismatch is one reviewed configuration change, not permission
to rotate identities after a block. Cookies, dynamic `tt`, pacing and strict
completeness checks remain unchanged. HTTP200 header tests are not proof of a
complete crawl or Nano acceptance; price-payload validation failed and later
native browsing returned 403. [Transport evidence](docs/ksp-stream-transport.md).

Prefer regular/Eilat prices observed together: KSP's stream is designed to
attach both to one offer; TMS needs its separate Eilat view for branch-only
listings. Eilat values are observed, never calculated. Detail enrichment is
bounded, normally once per listing, not a nightly price-refresh substitute.
Cloud detail vendors run independently, stop on a first block and retain
already captured specs even when the phase fails.

**Manufacturer fetchers:** robots obeyed except listed narrow owner overrides,
one request/s, browser headers, no retries; first 403/429 stops that brand.
[Source rules and exceptions](scraper/mfr/README.md) apply before any fetch.

## Quickstart

A normal clone includes public catalog data. From the repository root:

```bash
pip install -r requirements.txt
npm --prefix site install
npm --prefix site run dev
```

Pipeline commands below are **real operations**, not setup requirements.
Run a vendor only from its approved environment and when not paused:

```bash
python scraper/run_spider.py <vendor>  # writes a real snapshot
python -m scraper.normalize_and_match # rebuilds catalog/public data
```

Tests use `scrapy crawl <vendor> -o <vendor>_test.jsonl`, never `data/raw/`.
For pipeline changes, verify a permitted test crawl, isolated normalize and
the affected checks. Check declarations/levels live in `scripts/run_checks.py`;
code/integrity block, quality warns. See [verification](PROJECT_OVERVIEW.md#11-how-to-verify-changes).

```bash
python scripts/run_checks.py --suite code
npm --prefix site test
npm --prefix site run build
```

### Special thanks

* [Devansh Awatramani](https://github.com/Devansh-awat) for giving me a lot of AI usage for free <3
