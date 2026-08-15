# PC Part Picker (Israel)

See `pc-parts-il-plan.md` in the project docs for the full plan — this repo
implements it. This README tracks live status; the plan doc stays the
source of truth for *why* decisions were made (per its own §0/§17).

## Status: Phase 0 (recon), nearly done — moving into Phase 1

### Decisions locked in (Aug 2026)
- **Language:** Bilingual, Hebrew + English (affects RTL layout work and
  title-parsing — normalize_and_match.py will eventually need to handle
  both languages per product).
- **Accounts:** Not for v1. Shareable build links are enough for now.
  Staying on **Option A** (git-as-database) architecture. Accounts are a
  real want *eventually* — when that's prioritized, revisit Option B (§4/§17
  of the plan) rather than over-building for it now.
- **KSP:** Out of scope for v1, per the plan (§10/§16). `spiders/ksp.py`
  exists only as an isolated, disabled stub.

### Phase 0 checklist — status

Domains confirmed (Aug 2026):
| Vendor | Domain | Platform/notes |
|---|---|---|
| TMS | tms.co.il | OpenCart, clean server-rendered category URLs |
| Ivory | ivory.co.il | Broad electronics retailer, not PC-only — scope category crawl carefully |
| 1PC | 1pc.co.il | Has parallel /he/ and /en/ paths |
| Plonter | plonter.co.il confirmed as canonical (see below) | |

**robots.txt: checked for all four (Aug 2026) — see each spider's docstring
for the full breakdown.** Summary:
- **TMS, Ivory, Plonter**: category/product browsing is allowed; disallow
  rules only target checkout/account/filter-query-params/admin paths. Plain
  HTML scraping via Scrapy is fine per robots.txt.
- **1PC**: same pattern (transactional paths blocked, browsing allowed) —
  *and* a genuinely useful internal endpoint was found:
  `POST /en/PCBuilder/CategoryViewData` returns clean HTML product-tile
  fragments (SKU, title, precise price, URL) instead of full rendered pages.
  See `spiders/onepc.py` docstring for the full request/response shape.
  This is a materially better foundation than parsing rendered category
  pages — **1PC is now the strongest first-vendor candidate**, alongside TMS.
- **Plonter domain resolved**: robots.txt was fetched for `plonter.co.il`,
  confirming that's the live/checked domain. `plonter.com/main.tmpl` still
  needs a quick manual check to see if it's a redirect or a genuinely
  separate site before fully ruling it out.
- Noise to ignore in all four vendors' Network tabs: Google Analytics
  `google-analytics.com/mp/collect` pings (measurement only), and for
  Plonter specifically, `db.access4u.co.il/api/isValidScript` (an
  accessibility-compliance widget check-in, unrelated to product data).

**Still outstanding (your 5-minute manual tasks):**
1. ToS skim for all four (linked from each homepage footer) — robots.txt
   being permissive doesn't rule out an explicit ToS prohibition.
2. For 1PC: capture the `categoryId` for GPU, motherboard, RAM, storage,
   PSU, and case the same way CPU (`categoryId=158`) was found — open
   https://1pc.co.il/en/pcbuilder, click each component type, watch the
   Network tab for the `CategoryViewData` request, note the `categoryId`.
   `spiders/onepc.py` has a `CATEGORIES` dict ready for these.
3. For Ivory: confirm via **view-source** (not DevTools Elements, which
   shows the post-JS DOM) whether product tiles exist in the raw HTML —
   determines plain Scrapy vs. needing scrapy-playwright.
4. Resolve plonter.com vs plonter.co.il for real (redirect vs. separate site).
5. **Submit the KSP official API enrollment application now** (§10/§16) —
   non-blocking, but approval timing is unknown, so starting the clock costs
   nothing.
6. Set up the Zyte Scrapy Cloud account via the GitHub Education Pack and
   deploy an empty test project to confirm the free unit + periodic-job
   scheduling work as expected.

Per-vendor recon notes live in each spider file's docstring (§0 of the
plan: "add to the decision log / doc rather than letting the reasoning
live only in a commit message") — that's the up-to-date source, more
detailed than this summary table.

### ⚠️ robots.txt policy (Aug 2026)

This project does **not** observe robots.txt (`ROBOTSTXT_OBEY = False` in
`scraper/settings.py`) — an explicit, informed decision by the project
owner, not an oversight. See `pc-parts-il-plan.md` §17 decision log for the
full reasoning and caveats. Two endpoints in particular are used
specifically *because* of this decision (both are excellent data sources
that sit on robots.txt-disallowed paths):
- **TMS**: `route=product/configurator/getProductByCategory` — clean JSON,
  see `spiders/tms.py`.
- **Plonter**: `/pnp/alon.tmpl` — full-catalog feed, see `spiders/plonter.py`.

This does **not** extend to KSP's active bot-management/WAF — that's a
different category of obstacle (technical countermeasure vs. stated
preference) and the plan's existing "don't build anything to defeat
CAPTCHA/spoof detection" stance (§10) is unchanged.

## Repo layout

```
/scraper                    # Scrapy project (skeleton in place)
  /spiders
    tms.py                   # stub — selectors need real DOM inspection
    ivory.py                 # stub — needs Network-tab JSON API check
    onepc.py                 # stub — needs /he/ vs /en/ decision
    plonter.py                # stub — needs canonical-domain resolution
    ksp.py                    # disabled stub, Phase 5 only, do not build yet
  items.py                    # shared Item schema — stable, don't churn this
  settings.py                  # rate limiting, robots.txt obey, encoding notes
  sync_from_scrapy_cloud.py    # pulls latest job items via Scrapy Cloud API
  normalize_and_match.py       # Phase 1: passthrough. Phase 2: real matching (§8)
  scrapy.cfg
/data
  catalog.json                 # empty placeholder for now
  history/                      # daily snapshots, once retention (§12) is built
/site                          # Astro/Next.js app — not started yet (Phase 1)
/.github/workflows
  sync-and-deploy.yml           # implements §9 exactly
  weekly-downsample.yml         # Phase 4, disabled stub
```

## Next steps (Phase 1, per plan §16)

1. Finish the Phase 0 checklist above (ToS skims, TMS's remaining category
   IDs, Plonter's product-URL gap).
2. Pick the 2 easiest-looking vendors — **TMS and Plonter are now the
   strongest candidates** given the JSON/full-feed sources found (see the
   robots.txt policy note above), with 1PC close behind (fully-mapped
   category IDs, just needs a real test run). Ivory remains HTML-scraping
   only for now.
3. Deploy to Scrapy Cloud, set up a Periodic Job.
4. Wire up `sync-and-deploy.yml` with real `SHUB_APIKEY`/`SHUB_PROJECT_ID`
   secrets and confirm the loop runs unattended.
5. Scaffold `/site` (Astro or Next.js static export) with a bare-bones page
   that just lists whatever's in `data/catalog.json` — no matching or
   compatibility logic yet, per the plan's explicit Phase 1 scope.
6. Prove the whole loop runs unattended for a week before starting Phase 2.
