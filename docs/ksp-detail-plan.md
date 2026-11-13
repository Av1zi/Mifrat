# KSP detail data: plan

Owner goal: get the rich product info KSP shows on its site (specs, manufacturer part number, descriptions) into the catalog. KSP is a reliable source and 815 products are KSP-only today.

Written 2026-11-09. Status: Phase 1 steps 1, 2 (partly) and 4 done on 2026-11-09 (see "Phase 1 progress"); Phase 0 and Phases 2-3 not started.

## Ground rules for whoever picks this up

- No evasion. If KSP's edge answers 403 / `cf-mitigated: challenge`, that is the answer. No impersonation rotation, no proxies, no challenge solving, no header games beyond what `scraper/spiders/ksp.py` already does for the public catalog.
- Home IP (the Nano) only. KSP is already blocked from datacenter IPs; CI must never fetch KSP.
- `robots.txt` is obeyed for KSP. Fetched 2026-11-09: `Allow: /`; disallowed include `/item/` (the redirect gate), `/cart`, `/account`, `/link/`, `/*.pdf$`, `/web/cart`, `/web/checkout`, `/web/account`, `/web/compare`. The public item URL shape the catalog uses is `/web/item/<uin>`, which is not disallowed. It also names two sitemaps, `googleSiteMaps.xml` (index fetched fine) and `hotTags.xml`.
- Stop on the first 403/429, one request at a time, 3-9s between requests (same as the listing spider).
- Commits are authored by the owner only. No co-author trailers.

## What we know (verified 2026-11-09)

| Fact | Evidence |
|---|---|
| Listing API (`/m_action/api/category/<tag>?page=<n>`) works from the Nano and is the only KSP source today | `scraper/spiders/ksp.py` |
| Detail endpoint `/m_action/api/item/<uin>` returned 403 under every impersonation, and the product page is an empty SPA shell | docstring in `ksp.py`, last tested before 2026-11-04 |
| 923 listings carry 36 distinct Hebrew tags (top: manufacturer, catalog, importer, warranty, type, colour, size, connections, features, memory type, socket, chipset, wattage) | `data/raw/2026-11-07/ksp.jsonl` |
| Listing `vendor_meta` also holds `eilat_price`, `labels`, `family_id`, `dynamic_parent`, `min_price`, `brand` | same file |
| KSP-only products have no MPN, so they cannot merge with other vendors (946 KSP-only at onboarding) | `decisions.md`, KSP onboarding |
| `nano/run_ksp.sh` is listing-only: **no cover-image step exists**, so KSP covers are backfilled by hand | `nano/run_ksp.sh` |
| Sitemap sub-pages (`/sitemap/siteMapItems.xml?page=1`) returned 403 to a plain client on 2026-11-09, so do not build on them without a browser-shaped test from the Nano | one request, then stopped |

## Phase 0: feasibility (one short session, on the Nano, owner present)

Goal: find out which of these KSP actually allows, before writing any parser.

1. **Re-test the detail endpoint once**, with the existing `chrome146` profile and client hints, for ONE known `uin` (e.g. 280943). Record status, `cf-mitigated`, body size. A 200 with JSON means Phase 2 is open. A 403 ends this route and is recorded in `decisions.md` with the date. Do not try variants. Ready to run on the Nano: `python scripts/ksp_detail_probe.py` (one request, refuses a second run the same day, writes nothing into the repo).
2. **Check the public product page** `/web/item/<uin>` for server-rendered data (schema.org `Product` JSON-LD, `__NEXT_DATA__`-style blobs). The earlier note says it is an empty shell, so expect nothing, but one fetch settles it. Done 2026-11-13 in a normal browser: the page renders ~870 characters of site chrome and requests only `new-config`, `header-menu` and an SSE stream; no product data, no part number, no `/api/item` call.
3. **Ask KSP for a sanctioned feed.** `robots.txt` references `affkey` and `appkey` URL parameters, which suggests an affiliate / app-key programme exists. An affiliate product feed (usually XML/CSV with MPN, EAN, specs, images) would be the cleanest answer and needs no scraping. This is an email or form from the owner, not code.
4. Write the outcome in the plan's "Outcome" section below and pick the phase.

## Phase 1: use what we already fetch (safe, no new requests)

Value: no new traffic, works regardless of Phase 0.

1. **Audit tag coverage.** For each of the 36 tags, list which `parse_ksp_tags` categories read it and which tags are dropped (e.g. `חיבורים`, `ואט` on non-PSU, `סוג מציאון`, `מרקר`, `משקל`, `עובי`). Output a table of unmapped tag x category with sample values.
2. **Map the unmapped tags** that match schema fields (`scraper/specs/schema.py`). Follow the repo rules: `null` = unknown, never guess, negatives spelled "No", tier 0.5-1 for vendor tags. Add offline fixtures to the existing KSP checks and re-measure `check_spec_coverage.py` floors in the same commit (floors only go up).
3. **Keep unused listing fields** (`labels`, `eilat_price`, `warranty`, `importer`) in `vendor_meta` and surface the ones the site can show (warranty and official-importer are real buying signals).
4. **Add the KSP cover backfill to the Nano job.** `nano/run_ksp.sh` should run `python -m scraper.download_images --from-catalog --vendor ksp --limit 300 --sleep 3` after the snapshot, then commit `data/images/ksp/` with `scripts/git_commit_push.sh`. It already stops after 2 consecutive 403/429. Note the catalog it reads is the one CI built from the previous snapshot, so new products get their cover one day later. `check_site_images.py` now counts KSP-only gaps separately (15% budget), so this lag will not fail CI.

### Phase 1 progress (2026-11-09)

- Step 1 done: `python scripts/audit_ksp_tags.py [--dropped-only]` prints the tag x category table (categories are the normalized ones the parser receives). Result: only two dropped tags carry spec data; the rest is catalogue / promo / branch stock / marker noise or has no schema field.
- Step 2 partly done: `דור המעבד` -> cpu `generation` (15/15 KSP-only CPUs now filled), `משך אחריות` -> storage `warranty_years` (102/102 KSP-only drives). Pinned by `scripts/check_ksp_tags.py` (in CI). Open: warranty for other categories needs a `warranty_years` schema field first; the `חיבורים` (ports) tag needs a per-category decision (gpu/motherboard output maps); coverage floors not yet raised.
- Step 3 not done: needs the site offer whitelist (`site_data._trim_offer`) and UI work; `warranty` and `importer` are the useful ones.
- Step 4 done in `nano/run_ksp.sh` (best-effort, runs after the snapshot is pushed). Untested on the Nano; watch the first night's log.

## Phase 2: detail scrape (only if Phase 0 step 1 returns 200, or a feed arrives)

If a feed: write a `scraper/mfr`-style importer, not a spider, and skip the rest of this phase.

If the detail endpoint answers 200:

1. New spider `ksp_detail` modelled on the existing `*_detail` spiders and `make_detail_pending` ledger, home-run only (`nano/run_ksp_detail.sh` + systemd service/timer, offset from the listing run).
2. Pending list = KSP uins with no detail row, `--limit 150` per night, hardest-needed first (KSP-only products, then categories with the lowest spec fill).
3. Rate: 3-9s random between requests, sequential, abort the run on the first 403/429, write nothing partial.
4. Capture: manufacturer part number (the big win: it lets KSP-only products merge with TMS/Yahav/1PC), EAN if shown, structured spec table, description, gallery images, warranty.
5. Normalize: add `ksp` to the `detail_index` merge in `normalize_and_match.py` so MPNs flow into identity matching. Expect product merges; run `scripts/check_identity_merge.py` and `report_identity_delta.py` and read the QA kinds before shipping.
6. Spec mapping: new `parse_ksp_detail` in `vendor_struct.py` (labels -> schema fields), plus `labels.py` entries and golden fixtures from saved pages (`nano/save_fixtures.sh`).

## Phase 3: close the loop on the other gaps

- Re-run the manufacturer fetchers for KSP-only products once MPNs exist (they key on part numbers).
- After MPNs land, retire the "KSP listing-only" caveats in README / `PROJECT_OVERVIEW.md`.
- Update `check_spec_coverage.py` floors upward.

## Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Detail endpoint still 403 | Phase 1 and the feed request still deliver value; record the verdict and stop |
| Scraping the detail endpoint risks the listing scrape (an IP-level ban would lose KSP entirely) | Detail runs in its own window after the listing, hard stop on first block, small nightly chunks; the listing is worth more than the details |
| MPN merges change many product ids | Alias map already exists (`pid_aliases`); run identity checks and review `identity_merge` QA cases first |
| Tag mapping errors ship wrong specs | Offline fixtures, `null` when unsure, existing golden and backtest gates |
| `decisions.md` is gitignored and partly AI-written | Treat it as notes, not authority; the owner's decisions in this chat win |

## Outcome (fill in after Phase 0)

- Detail endpoint: **open** (2026-11-13, owner on the Nano, uin 280943: HTTP 200, no `cf-mitigated`, `application/json`, 44,558 bytes, 407 keys). The probe's key-name scan found no part-number-like key. Read from the saved sample (owner, same day): `result` holds `data` (listing fields plus `modalName: "i5-14600K"`), `tags`, `images`, `stock` and `specification.items`, a head/body HTML table copied from the maker (Intel's full ark sheet here) with a `דגם` (model) row of `i5-14600K`. No maker part number (`BX8071514600K`), no barcode, nowhere in the payload. One CPU sample only: whether `דגם` carries the maker code for memory/PSU/case/GPU rows decides Phase 2's value; next probe is one non-CPU item.
- Product page structured data: none (2026-11-13, see Phase 0 step 2)
- Affiliate / feed answer: _pending_
- Second sample (2026-11-13, uin 193193, Kingston FURY Beast 2x16GB DDR5 5600): `דגם` = `KF556C40BBK2-32`, the maker part number; `יצרן`, capacity, speed, CL rows follow.
- Chosen path: **Phase 2, detail scrape** (2026-11-13). `scraper/spiders/ksp_detail.py` + `nano/run_ksp_detail.sh` (night timer 03:00-03:30 UTC after the listing run, only on a night that run succeeded, 150/day, KSP-only first, one request in flight, stop on the first 403/429). The `דגם` row rides as `extra.model_row` and becomes `mpn` only when another vendor of the category prints the same code (`normalize_and_match._adopt_ksp_model_rows`), so a CPU model name never acts as a part number. Pinned by `scripts/check_ksp_detail.py`. Spec rows land in `detail_specs` for the label vocabulary to pick up (unmapped Hebrew labels show in `label_gaps`).
