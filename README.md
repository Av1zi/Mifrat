# PC Part Picker (Israel)

See `pc-parts-il-plan.md` in the project docs for the full plan — this repo
implements it. This README tracks live status; the plan doc stays the
source of truth for *why* decisions were made (per its own §0/§17).

## Status: Phase 0 (recon), in progress

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

### Phase 0 checklist — what's done vs. what needs 5 minutes of your time

Domains confirmed via search (Aug 2026):
| Vendor | Domain | Platform/notes |
|---|---|---|
| TMS | tms.co.il | OpenCart, clean server-rendered category URLs, no JSON API spotted in the fetched homepage HTML |
| Ivory | ivory.co.il (or www.ivory.co.il) | Broad electronics retailer, not PC-only — scope category crawl carefully |
| 1PC | 1pc.co.il | Has parallel /he/ and /en/ paths — worth comparing before picking one |
| Plonter | plonter.co.il **and** plonter.com/main.tmpl both surfaced — confirm which is canonical | |

**I could not check robots.txt/ToS or inspect the Network tab from inside
this environment** — my web tools can only fetch URLs that already surfaced
via search, and my sandboxed bash has no network access to `.il` domains.
This is a genuinely 5-minute manual task per vendor for you:

1. Open each of these directly in a browser:
   - https://tms.co.il/robots.txt
   - https://www.ivory.co.il/robots.txt
   - https://1pc.co.il/robots.txt
   - https://www.plonter.co.il/robots.txt (and check whether plonter.com
     redirects to it or is a separate live site)
2. Skim each site's Terms of Service page for any explicit
   automated-access prohibition (linked from each homepage footer).
3. On one category page per vendor: open DevTools → Network tab → filter
   to XHR/Fetch → reload the page. If you see a JSON response with product
   data, note the endpoint URL in that spider's docstring — it's much more
   stable to hit directly than parsing rendered HTML (§7 step 2).
4. **Submit the KSP official API enrollment application now** (§10/§16) —
   this is non-blocking but approval timing is unknown, so starting the
   clock costs nothing.
5. Set up the Zyte Scrapy Cloud account via the GitHub Education Pack and
   deploy an empty test project to confirm the free unit + periodic-job
   scheduling work as expected.

Update the docstring at the top of each spider file in `scraper/spiders/`
with what you find — that's where this project keeps per-vendor recon notes
(§0 of the plan: "add to the decision log / doc rather than letting the
reasoning live only in a commit message").

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

1. Finish the Phase 0 checklist above.
2. Pick the 2 easiest-looking vendors (TMS is a strong first candidate given
   what's already confirmed) and get one spider fully working end to end
   against real selectors.
3. Deploy to Scrapy Cloud, set up a Periodic Job.
4. Wire up `sync-and-deploy.yml` with real `SHUB_APIKEY`/`SHUB_PROJECT_ID`
   secrets and confirm the loop runs unattended.
5. Scaffold `/site` (Astro or Next.js static export) with a bare-bones page
   that just lists whatever's in `data/catalog.json` — no matching or
   compatibility logic yet, per the plan's explicit Phase 1 scope.
6. Prove the whole loop runs unattended for a week before starting Phase 2.
