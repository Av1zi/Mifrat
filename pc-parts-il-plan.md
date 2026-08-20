# PC Part Picker (Israel) — Build Plan

Revised August 2026 (rev. 2): Zyte Scrapy Cloud abandoned; moved to a hybrid
cloud + local scraping architecture.

## 0. For future readers / AI agents

This is the source of truth for how the project works and why. Read this
before proposing changes. The major rev. 2 change: after repeated failed
attempts with Zyte, scraping was split into two execution environments —
GitHub Actions for cloud-safe vendors, and a Jetson Nano at home for TMS.
The reasoning lives in DECISIONS.md; this file describes the plan itself.

## 1. What we're building

A PCPartPicker-style site for the Israeli market: scrape prices and specs
from local vendors daily, normalize them into one canonical catalog, let
users build a parts list with compatibility checking, and show which vendor
has the best current price per part.

Three sub-systems, built separately: the scraper, the catalog/matcher, and
the site. The matching problem (knowing TMS's listing and Ivory's listing
are the same GPU) is the genuinely hard part; scraping and compatibility
rules are manageable by comparison.

This is mostly a fun project, but the architecture keeps a clean upgrade
path if it ever gets traction (§15).

## 2. Architecture overview — hybrid cloud + local

The system has two scraper locations feeding one pipeline:

- Cloud scraping (GitHub Actions): 1PC and Plonter now; Ivory joins in
  Phase 2 (§16)
- Local scraping (Jetson Nano at home): TMS
- Both write raw snapshots into the git repository
- A normalizer job merges them into one catalog
- Cloudflare Pages auto-deploys the site on every push

Why the split: TMS actively rejects datacenter/scraping-infrastructure IP
addresses (confirmed during the failed Zyte attempts), so it must be scraped
from a residential IP — the Jetson Nano at home. The other three vendors
show no evidence of such blocking, so they run where free compute exists:
GitHub Actions. Spiders are location-agnostic; if a cloud vendor ever starts
blocking Actions IPs, moving it to the Nano is a scheduling change, not a
rewrite.

The "git as the database" model from rev. 1 is kept: raw snapshots and the
catalog are committed files, history is versioned for free, and the frontend
does client-side filtering over the catalog. A real database (Cloudflare D1)
only enters the picture if user accounts or server-side writes are ever
needed.

## 3. Why GitHub Actions for cloud scraping

Requirements: free, reliable enough for daily runs, no new accounts, no
student-verification dependency.

GitHub Actions won because public repos get free minutes with no cap that
matters here, the code already lives there, and nothing expires. Its known
quirks — UTC-only scheduling, 10–30+ minute drift, occasional skipped runs,
and auto-disabling scheduled workflows after 60 days of repo inactivity —
are all acceptable for daily price data and are mitigated (§8).

Rejected alternatives: Zyte (failed repeatedly, then abandoned);
PythonAnywhere free tier (outbound connections are whitelisted, Israeli
retail sites unreachable); Oracle Cloud Always Free (best raw free tier, but
requires a credit card and more ops — kept as the documented upgrade path);
fly.io/Railway/Render free tiers (gutted or expiring as of 2026).

## 4. The Jetson Nano's role

The Nano is an already-owned, low-power (5–10W) ARM64 Linux box that runs
24/7 for free. Its only job is scraping TMS once a day from the home
residential IP.

Setup principles:

- Run it headless (no desktop environment) under a dedicated low-privilege
  user account.
- The system Python on the stock Jetson image is too old for modern Scrapy —
  install a current Python (3.11+) via Miniforge, and run the scraper inside
  that environment. This is the single most common setup failure on this
  hardware; do it first.
- Pin the exact same Scrapy version on the Nano and in Actions so the two
  environments never drift.
- Schedule the daily scrape with a systemd timer rather than cron: it
  supports randomized delay (jitter) and can catch up after downtime.
- Push results to GitHub using an SSH deploy key scoped to this one repo.
  If the Nano is ever compromised, the blast radius is writing to this repo
  and nothing else. The private key lives only on the Nano, never in the
  repo.
- Keep the SD card healthy: logs go to RAM/tmp, not disk; the only daily
  write is one small git commit.
- Verify NTP time sync — wrong clocks poison the daily-history data.

## 5. Data flow

1. Raw capture. Each scraper writes its results as JSONL files under
   `data/raw/YYYY-MM-DD/<vendor>.jsonl` and commits them to the repo. One
   line per listing, one file per vendor per day.
2. Normalization. A scheduled Actions job (running after both scrapes are
   expected to be done) reads the latest raw snapshots, merges and
   deduplicates them, and builds `data/catalog.json` — one entry per unique
   product, with compatibility attributes and a list of vendor links/prices.
3. Deployment. The catalog commit triggers Cloudflare Pages, which rebuilds
   and serves the site automatically.

Stale-forward rule: if a vendor's raw snapshot is missing today (Nano down,
spider broken, site blocked us), the normalizer carries that vendor's
listings forward from the most recent day and stamps them with a last-seen
date. A vendor having a bad day must never wipe its prices off the site —
but stale data must be visibly stale.

## 6. Scraping approach — general principles

Prefer the vendor's own internal endpoints over HTML parsing. Every vendor
here was checked with browser DevTools first. When a site's own frontend
calls a JSON or XHR endpoint, scraping that endpoint is cleaner, cheaper,
and looks exactly like normal user traffic. HTML scraping is the fallback
layer, not the default.

Per-vendor choices (details in each spider's docstring):

| Vendor | Method | Why |
| --- | --- | --- |
| TMS | HTML category pages + a follow-up Claris stock-availability POST | The configurator JSON API is WAF-blocked from datacenter IPs; category pages return clean 200s and sit on an allowed robots.txt path |
| 1PC | PCBuilder CategoryViewData POST endpoint | Purpose-built endpoint returning product-tile fragments; 10 categories mapped |
| Plonter | Full-catalog feed (`alon.tmpl`) | Entire catalog in one request |
| Ivory | Raw HTML scraping | No usable API found; tiles confirmed server-rendered, so no Playwright needed |
| KSP | Nothing yet (Phase 5) | Official API application is the preferred path; scraping only as last resort |

Known per-vendor quirks that are already handled or tracked: TMS's `stock`
field comes from a second Claris API call and falls back to unknown (not a
guess) if that call fails or is blocked; 1PC's price
attribute carries floating-point noise (round half-up to the real shekel
price); Plonter's feed is Windows-1255 encoded and lacks product URLs; the
Scrapy `start()` vs `start_requests()` entrypoint change (define both).

## 7. Protecting the home IP (TMS on the Nano)

Scraping from home means a ban hits your own internet connection. The
defense is behavioral, not technical — at ~10–30 requests per day, volume
is not the risk; looking like a machine is.

The rules:

1. Once a day, strictly sequential, slow. One concurrent request, throttled
   with randomized delays. The whole run takes a couple of minutes.
2. Warm up like a human. Fetch the configurator page first to establish a
   session, then make API calls with that session and a proper referer.
3. Send browser-shaped headers: a stable current desktop user-agent,
   Hebrew-Israeli accept-language, and the standard fetch headers a real
   browser sends.
4. Run at human hours with jitter (Israeli morning, ± up to 45 minutes),
   never at an exact predictable time.
5. Replay captured parameters exactly. Never explore or fuzz the API's
   parameter space — every request we send should mirror one the site
   itself makes.
6. Hard stop on blocks. A 403 or 429 means stop for the day. No retries
   against a block, no automatic re-runs. Two block responses in one run
   close the spider.
7. If blocked repeatedly: de-escalate or drop. Pause several days, try the
   slower HTML pages, reduce frequency — and if still blocked, drop the
   vendor. Never escalate against active defenses.
8. No third-party residential proxy services. At this volume they add cost
   and route the project through strangers' infrastructure for zero
   benefit.

## 8. Scheduling

| Job | Where | When |
| --- | --- | --- |
| Scrape 1PC, Plonter (Ivory joins Phase 2) | GitHub Actions | Daily, ~03:30 UTC |
| Scrape TMS | Jetson Nano | Daily, ~06:00 UTC with up to 45 min jitter |
| Normalize + build catalog | GitHub Actions | Daily, ~09:00 UTC |
| Site deploy | Cloudflare Pages | Automatically on push |

All workflows are schedule- and manual-dispatch-only; no push-triggered
workflows, which keeps timing predictable and avoids recursion questions.
Manual dispatch exists everywhere so any missed scheduled run can be
re-triggered by hand.

## 9. Secrets and public-repo safety

The repo is public; assume everything committed is read by everyone.

- The cloud scraping workflows need zero secrets — the endpoints are
  public. Keep it that way.
- The Nano authenticates with an SSH deploy key that exists only on the
  Nano's filesystem with strict permissions. Never embed tokens in remote
  URLs.
- Anything sensitive (e.g. a Sentry DSN) lives in GitHub Actions secrets or
  a git-ignored, permission-locked env file on the Nano — never in code.
- Remove all Zyte artifacts (deploy configs, the old deploy section in
  scrapy.cfg, the scrapinghub dependency) so no stale IDs linger publicly.
- The ignore file must cover env files, private keys, virtualenvs, caches,
  and local databases.
- Commit identity is a bot name with a noreply email, never a personal one.
- Raw price data is public information and fine to commit; nothing else
  scraped or personal belongs in the repo.

## 10. Failure handling and common pitfalls

Designed-in resilience:

- Count checks fail loudly: if a vendor's raw file is missing or has far
  fewer items than expected, the job fails and alerts fire. This is what
  catches "a vendor redesigned their site and we now scrape nothing."
- One vendor failing must not kill the others' scrapes.
- Git push conflicts between the two writers are handled with
  rebase-and-retry with jitter in a shared commit-and-push step.
- The Nano's timer catches up after downtime; the normalizer tolerates
  missing days via stale-forward.
- TMS is a known single point of failure (it can only run from home). If
  the Nano is down, the site shows stale prices with a last-seen date —
  graceful degradation instead of a broken site.

Pitfalls explicitly planned around: ancient system Python on the Nano;
ARM64 dependency installs (keep the dependency list lean — no Playwright on
the Nano unless truly required); Scrapy version drift between environments;
GitHub cron drift and skips; scheduled-workflow auto-disable (daily commits
keep the repo active); SD card wear; clock drift; overlapping runs;
repo growth from daily history (90-day raw retention plus later
downsampling).

## 11. Data model

Two layers:

- Raw listings (per vendor, per day): vendor id, vendor SKU, raw title,
  price in ILS, in-stock (or unknown), URL, scrape timestamp, category
  guess.
- Canonical products: product id, canonical name, category, brand, model,
  a flexible attributes blob per category (socket, wattage, form factor,
  memory type, dimensions…), and a list of vendor links with current price
  and last-seen date.

A loose attributes schema beats a rigid one — categories share almost no
fields, and scraped specs are inconsistent across vendors anyway.

## 12. Matching (Phase 2)

Extract structured signals from messy mixed Hebrew/English titles instead of
matching raw strings; prefer canonical model numbers where vendors expose
them; fuzzy-match only as a thresholded fallback, with anything uncertain
going to a human review queue rather than straight into the catalog; store
confirmed vendor-SKU-to-product mappings so listings match once, not daily.

## 13. Compatibility (Phase 3)

A rules engine over clean attributes, evaluated client-side: socket match,
RAM type/speed, PSU wattage vs. total draw with headroom, GPU length and
cooler height vs. case clearance, form factor, slot counts. Build
incrementally; don't model every edge case on day one.

## 14. Legal and ethical posture

- robots.txt is ignored for cloud-run scrapers (1PC, Plonter, Ivory) and
  followed for locally-run scrapers (TMS, on the Nano) — see DECISIONS.md
  for the full reasoning and TMS's current compliance gap. Take-down-on-
  request posture either way.
- Rate limiting matters more now that robots.txt isn't a self-imposed
  backstop.
- Store and display only what's needed; link out to buy rather than
  replacing vendor pages.
- The robots.txt decision does NOT extend to active bot defenses. If KSP's
  WAF blocks us, that's a signal to stop, not to escalate — nothing in this
  project is designed to defeat CAPTCHAs or spoof detection.
- Scraping TMS now carries higher personal stakes (home IP), which is why
  §7 is mandatory.

## 15. If the project gets traction

Nothing here blocks growth: Cloudflare Pages absorbs read traffic for free;
the first moves would be adding Cloudflare D1 for user-facing write
features (accounts, saved builds), and moving the Nano's role to an Oracle
Always Free or cheap VPS if hardware reliability becomes a concern. Until
then, keep it lean.

## 16. Phased roadmap

- Phase 0 (done): recon for all four vendors, endpoints mapped, robots.txt
  decision logged, KSP API application submitted.
- Phase 1 — hybrid pipeline MVP: repo hygiene pass (remove Zyte artifacts,
  pin dependencies); Nano set up and scraping TMS on schedule; Actions
  scraping 1PC + Plonter; passthrough normalizer producing catalog.json;
  bare-bones static page. Prove it runs unattended for a week.
- Phase 2 — matching: add Ivory to cloud scraping; real normalizer, fuzzy
  matcher, and manual-merge review; one clean canonical catalog.
- Phase 3 — compatibility and builder UI.
- Phase 4 — history, retention/downsampling, RTL Hebrew polish, search.
- Phase 5 — KSP, only if the API application comes through or it's still
  worth the burden.

## 17. Open items

- Plonter product-URL resolution (the feed has none — sitemap
  cross-reference is the leading candidate).
- Ivory category URL map and selectors for PC sections.
- Calibrate the minimum item-count thresholds after the first clean runs.
- Confirm TMS API responses are full categories, not first pages.
- Revisit whether TMS's configurator JSON API is viable again now that TMS
  runs from the Nano's residential IP instead of datacenter IPs — the HTML
  fallback (§6) was adopted before the Nano decision existed. Not urgent,
  since HTML is already working and robots.txt-clean, but worth a
  deliberate keep-or-switch call rather than leaving it as inherited by
  default.
- `normalize_and_match.py` and `sync_from_scrapy_cloud.py` still assume the
  old single-file Scrapy Cloud pull, not the `data/raw/YYYY-MM-DD/<vendor>.jsonl`
  layout or stale-forward rule in §5 — unbuilt Phase 1 work, not a bug.