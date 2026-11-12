"""Save a reconciled PARTIAL checkpoint, evidence, report, and integrity checks."""
import collections as co
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

RUN=Path(__file__).resolve().parent
ROOT=RUN.parents[2]
SNAP=RUN/'snapshot'
OUT=ROOT/'docs/audits/2026-11-12-reaudit'
sys.path.insert(0,str(SNAP))
from scraper.text_hygiene import clean_tree
from scraper.matching import enrich_listing, dedupe_enriched_listings
from scraper.normalize_and_match import _drop_included_builder_options

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def jl(path):return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8').strip()

def main():
    c=read(SNAP/'data/catalog.json'); ps={p['product_id']:p for p in c['products']};ls={e['listing_key']:e for e in c['listings']}
    fs=jl(OUT/'findings.jsonl');cs=jl(OUT/'candidates.jsonl')
    rep=OUT/'reproduce';rep.mkdir(exist_ok=True)
    for name in ['pin.py','inventory.py','scan.py','adjudicate.py','finish_partial.py','gates.py','final_check.py','input-hashes.json','scan-metrics.json','rpm-source-replay.json','split-replay.json','null-with-listing-facts.json','extraction-facts.json','detail-inventory.json','image-references.json','gate-results.json']:
        shutil.copy2(RUN/name,rep/name)
    shutil.copytree(RUN/'gates',rep/'gates',dirs_exist_ok=True)
    # Store exact affected catalog/listing records and matching raw evidence.
    affected_pids={pid for f in fs for pid in f['product_ids']}
    affected_keys={key for f in fs for key in f['listing_keys']}
    dump(rep/'affected-catalog.json',{'generated_at':c['generated_at'],'products':[ps[p] for p in sorted(affected_pids)],'listings':[ls[k] for k in sorted(affected_keys)]})
    raw_evidence=[];accounting=[]
    manifest=read(OUT/'manifest.json')
    for selected in manifest['input_selection']:
        path=SNAP/selected['path'];records=[]
        for n,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():continue
            raw=json.loads(line);e=enrich_listing(clean_tree(raw));records.append((n,raw,e))
            # Compare numeric URL based listing key before SKU substitutions.
            if e['listing_key'] in affected_keys:
                raw_evidence.append({'path':selected['path'],'line':n,'listing_key':e['listing_key'],'record':raw})
        enriched=dedupe_enriched_listings([e for _,_,e in records])
        raw_keys={e['listing_key'] for _,_,e in records}
        catkeys={k for k,e in ls.items() if e['vendor_id']==('1pc' if selected['vendor']=='onepc' else selected['vendor'])}
        accounting.append({'vendor':selected['vendor'],'path':selected['path'],'raw_rows':len(records),'raw_unique_keys':len(raw_keys),'extra_duplicate_rows':len(records)-len(raw_keys),
            'catalog_keys':len(catkeys),'raw_keys_missing_from_catalog':sorted(raw_keys-catkeys),'catalog_keys_without_raw':sorted(catkeys-raw_keys),
            'raw_to_catalog_keys':[{'line':n,'listing_key':e['listing_key'],'product_id':ls.get(e['listing_key'],{}).get('product_id'),'retained':e['listing_key'] in catkeys} for n,raw,e in records]})
    for vendor in ['tms','onepc','ivory','yahav']:
        path=SNAP/f'data/raw/detail/{vendor}.jsonl'
        if not path.exists():continue
        for n,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():continue
            raw=json.loads(line)
            key=('1pc' if vendor=='onepc' else vendor)+':'+str(raw.get('vendor_sku'))
            if key in affected_keys or any(raw.get('url')==ls[k]['url'] for k in affected_keys):
                raw_evidence.append({'path':path.relative_to(SNAP).as_posix(),'line':n,'listing_key':key,'record':raw})
    dump(rep/'raw-evidence.json',raw_evidence);dump(rep/'raw-accounting.json',accounting)
    for f in fs:
        for idx,row in enumerate(raw_evidence):
            if row['listing_key'] in f['listing_keys']:
                f['evidence'].append({'path':row['path'],'line':row['line'],'record_key':row['listing_key'],'utc_timestamp':row['record'].get('scraped_at'),
                    'quote':row['record'].get('specs') or row['record'].get('title_raw'), 'reproduction':f'reproduce/raw-evidence.json#/{idx}'})
    (OUT/'findings.jsonl').write_text(''.join(json.dumps(f,ensure_ascii=False)+'\n' for f in fs),encoding='utf-8')
    # Resolve EVERY historical emitted row using current aliases and listing keys.
    previous=[];families=co.defaultdict(list)
    for file in sorted((SNAP/'docs/audits/2026-11-10').glob('*.jsonl')):
        for n,row in enumerate(jl(file),1):
            lane=file.name[:2];family=str(row.get('finding') or row.get('finding_id') or 'unknown')
            pids=list(row.get('product_ids') or [])
            if row.get('product_id'):pids.append(row['product_id'])
            keys=list(row.get('listing_keys') or row.get('all_listing_keys') or [])
            if row.get('listing_key'):keys.append(row['listing_key'])
            keys += [o['listing_key'] for o in row.get('offers') or [] if o.get('listing_key')]
            current={ls[k]['product_id'] for k in keys if k in ls}
            current|={pid if pid in ps else (c.get('pid_aliases') or {}).get(pid) for pid in pids}
            current.discard(None)
            status='partially_resolved' if current else 'disappeared_unverifiable'
            if family.startswith('R-'):status='intentional_accepted'
            pr={'lane':lane,'historical_family':family,'historical_path':file.relative_to(SNAP).as_posix(),'line':n,
                'old_product_ids':pids,'listing_keys':keys,'current_product_ids':sorted(current),'anchor_status':status,
                'adjudication':'anchors resolved mechanically; individual historical expected claims need re-adjudication unless summarized below'}
            previous.append(pr);families[(lane,family)].append(pr)
    dump(rep/'previous-instance-anchors.json',previous)
    previous_md=['# Previous-findings reassessment — partial','',
        'All historical JSONL rows are indexed in [previous-instance-anchors.json](reproduce/previous-instance-anchors.json). Retired ids resolve through current listing keys and aliases, never reconstructed slugs. Anchor existence is not resolution of a finding. Historical prose counts sometimes exceeded their JSONL; those unenumerated historical instances remain unverified.', '',
        '| Current reassessment | Evidence and later fix |','|---|---|',
        '| A/A2 wrong-variant merges: partially resolved | Two-PN splitter/I4, title axis QA, sibling narrowing in current identity.py; gates pass. Remaining 27 visible same-vendor products still need physical variant adjudication. Flagging is not proof the underlying merge is fixed. |',
        '| D CPU Box/Tray: resolved for rule regression; residual evidence ambiguity accepted | Current title/attribute/maker/default basis; copied C-code removed in 317c703d. I6 passes. Same-code G4400/A10 candidates rejected as unsafe merges; default Box is identity-only and QA, not a sourced packaging spec. |',
        '| E newest observation: price-selection fix resolved on pinned inputs; Nano rollout unverified | check_snapshot_rows passes; TMS latest snapshot still contains two sessions. Marker code fixed (02b9d084) but no Nano deployment state inspected. Old raw remains immutable. |',
        '| H conditional/sale prices: core fixes resolved on pinned publish set | 234 bundle offers retained and conditional gates pass; sale repair deployed locally, tile_parser2 not proven on Nano. No wrong shown sale price inferred from older flags. |',
        '| P twins: partially resolved | 53 aliases now suppressed; 27 products still visibly repeat a vendor; both can contain wrong variant specs. Cross-product residual splits RC-004. |',
        '| I categorization: prior classifier fixes present; full physical census incomplete | is-a/anchored-inclusion rules f969553c and category gates pass; all historical anchors mapped below. KSP SO-DIMM scope discrepancy and adapter/SSD cooler side finds need policy/source adjudication. |',
        '| F/G chipset/threads/GDDR fixes: largely resolved, residuals not all adjudicated | New invariants/witness pass. H81 null, single-source cache conflict and title-versus-detail 5080/5060 Ti remain evidence checks, not assumed resolved. |',
        '| J text hygiene: resolved by current full corpus gate | 02b9d084, all strings/keys gate passes. |',
        '| N brand repair: partially resolved / new projection omission | product.brand repaired, but 8 products retain chip manufacturer spec/name (RC-002). Existing gate checks brand only. |',
        '| M enum/schema: fixes present; residual validation whitelist gap | chipset/socket/2U/SSI-CEB/x4 changes plus schema misses gate pass; sourced5066 MHz is still refused (RC-003). |',
        '| O count parsing: fixed cases/latent fixtures pass; broader semantics unexamined | Decimal guards in 317c703d do not fix RPM tolerance; RC-001 confirms old lane05 RPM suspicion and new case_fan affected instances. |',
        '| K extract routing: resolved for aliases, residual semantic verification risk | f4ccf0e7/set_run_aliases + check_extract pass, 17 unreached entries <=25. Pump quote can verify as fan speed; most flagged claims untrusted and safely inert. No trust expansion recommended. |',
        '| L ledgers: accepted retained budgets / partial | Empty overrides; orphan enrichment/detail/images budgets pass. Future refresh remains limited to newly missing detail, no age/version queue. |',
        '| V pending live checks: still unverifiable | 1PC206013 price jump, TMS query links, BW025767 CFM, Hyper212height25, Zalman60MM cannot be confirmed by outlier alone. Environment/source eligibility not established; zero live requests. |','',
        '## Every historical emitted family','', '| Lane / family | Historical rows | Current anchor-linked rows | Status |','|---|---:|---:|---|']
    for (lane,family),rows in sorted(families.items()):
        live=sum(bool(r['current_product_ids']) for r in rows)
        status='disappeared/unverifiable' if not live else 'partially resolved / individual re-adjudication remains'
        if family.startswith('R-'):status='intentional/accepted historical rejection'
        previous_md.append(f'| {lane} / {family} | {len(rows)} | {live} | {status} |')
    previous_md += ['', '## Duplicate-groups audit R1–R7',
        'R1/R3/R4/R6 implemented in current model fallback/PN union/verified-code/tail paths; residual all-letter PN bridges RC-004 partially escape R3. R2 noise/axis stripping is an explicitly rejected proposal (2 merges vs322 renamed ids), not a missing fix. R5/R7 remain intentional QA-only variant separation. Current missing-code/multi-vendor/title scans do not imply blanket merging. Full per-original-group live adjudication remains unfinished.']
    (OUT/'previous-findings.md').write_text('\n'.join(previous_md)+'\n',encoding='utf-8')
    host_ledger={'utc_recorded':dt.datetime.now(dt.timezone.utc).isoformat(),'requests':[], 'total_requests':0,
        'location_class':'Windows local checkout; residential-home eligibility unestablished',
        'hosts':{host:{'eligible':False,'prior_run_state':'unknown','block_state':'unknown','request_ceiling_for_this_audit':0,'actual_requests':0,'delay_seconds':delay,'rule':rule}
        for host,delay,rule in [ ('tms.co.il','vendor delay','Nano only, once/day, sequential night window21:00–04:00UTC, robots; no block retries'),
            ('1pc.co.il',2,'Listing Nano/home; detail cloud accepted, but this machine eligibility/window unknown; no probe'),
            ('ksp.co.il',6,'Home stable chrome146/robots, no detail; stricter first403/429stop used despite README/code429retry discrepancy'),
            ('www.ivory.co.il','global throttle','Cloud source; targeted traffic not performed; no prior-run state known'),
            ('www.yahavpc.co.il','global throttle','Cloud source; targeted traffic not performed'),
            ('manufacturer hosts',1,'Home/local with robots; previously blocked Gigabyte/MSI/Intel/Noctua/Kingston/Cougar and declined sources not retested. No manufacturer cache page fetched or parsed live.') ]}}
    dump(rep/'host-ledger.json',host_ledger)
    coverage=read(OUT/'coverage.json');metrics=read(RUN/'scan-metrics.json')
    coverage['candidate_dispositions']=dict(co.Counter(r['disposition'] for r in cs))
    coverage['candidate_count']=len(cs)
    coverage['confirmed_instance_counts']=dict(co.Counter(f['kind'] for f in fs))
    coverage['confirmed_unique_products']=len(affected_pids);coverage['confirmed_unique_listings']=len(affected_keys)
    coverage['confirmed_affected_product_ids']=sorted(affected_pids);coverage['confirmed_affected_listing_keys']=sorted(affected_keys)
    coverage['candidate_adjudicated_count']=sum(r['disposition']!='needs_evidence' for r in cs)
    coverage['candidate_unresolved_count']=sum(r['disposition']=='needs_evidence' for r in cs)
    coverage['mechanical_scan_metrics']=metrics
    coverage['checks']['raw_to_catalog_accounting']={'raw_rows':sum(r['raw_rows'] for r in accounting),'unique_keys':sum(r['raw_unique_keys'] for r in accounting),'missing_catalog_keys':sum(len(r['raw_keys_missing_from_catalog']) for r in accounting),'artifact':'reproduce/raw-accounting.json'}
    coverage['checks']['publication']={'mechanically_scanned_products':4402,'image_references_scanned':metrics['image_refs'],'visual_verified_images':0,'live_verified_pages':0}
    coverage['checks']['individual_source_adjudication']={'confirmed_products':len(affected_pids),'confirmed_listing_keys':len(affected_keys),'live_verified':0,
        'unresolved_candidate_products':len({pid for r in cs if r['disposition']=='needs_evidence' for pid in r['product_ids']}),
        'products_without_individual_confirmation':len(ps)-len(affected_pids)}
    kit_checked=[p for p in ps.values() if p['category']=='memory' and all(p['specs'].get(f) is not None for f in ['module_count','module_size_gb','total_gb'])]
    kit_failures=[p['product_id'] for p in kit_checked if p['specs']['module_count']*p['specs']['module_size_gb']!=p['specs']['total_gb']]
    coverage['checks']['memory_kit_arithmetic']={'products_enumerated':sum(p['category']=='memory' for p in ps.values()),'complete_axis_denominator':len(kit_checked),'product_ids_checked':[p['product_id'] for p in kit_checked],'failures':kit_failures,'blind_spot':'Numeric consistency alone cannot verify actual kit versus single DIMM; live/source physical module identity remains unexamined.'}
    coverage['candidate_search_methods']=[
        {'name':'independent_exact_code','scope':'all7075offers across every category; MPN and SKU; alphanumeric and plausible barcode lengths','blind_spot':'does not scan every raw barcode/custom vendor field, normalized identifier can be retailer evidence rather than maker'},
        {'name':'title_fingerprint','scope':'alloffers; English token residual equality, body words removed; no QA/vendor/brand exclusion','blind_spot':'Hebrew-only models, rare extra words, conflicting variant axes; no transitive merge'},
        {'name':'model_code_bucket','scope':'all offers model_code/attribute.model including multi-vendor','blind_spot':'code parser itself can misread/truncate; independent title pass supplements it'},
        {'name':'distinctive_token_overlap','scope':'all listings via digit-containing model tokens, min token coverage85%,27275pairs','blind_spot':'buckets>40 skipped to avoid generic chip-family explosion; broad word-overlap is noisy; missing axis/one-sided details unresolved'},
        {'name':'spec_field_applicability','scope':'all schema fields/all4402products; independently evaluate gates and cross-check schema.applies; false/zero/empty/notapplicable separated','blind_spot':'does not prove source availability for nulls; sibling-answered null distinguished'},
        {'name':'listing-fact-null-replay','scope':'all7075listings/current resolvers vs every applicable product field','blind_spot':'uses production parser so label/coercion blind spots remain; all enrichment source gap replay unfinished'},
        {'name':'extract_claim_semantics','scope':'3656reached claims/current trust and quote verifier, pump/fan cases','blind_spot':'not a full independent fact semantic truth audit; most claims require more source inspection'},
        {'name':'raw/accounting/publish/images','scope':'9296 selected raw rows -> 7075 keys; all 4402 published products / 8760 image refs; no missing reference result','blind_spot':'pre-spider dropped rows absent from snapshots, image physical associations not visually verified; history full independent replay unfinished'}]
    coverage['lanes']={str(i).zfill(2):{'status':'partial','catalog_population_enumerated':4402,'listing_population_enumerated':7075,'live_verified':0,
        'emitted_candidates':sum(r.get('lane')==str(i).zfill(2) for r in cs),'unresolved_candidates':sum(r.get('lane')==str(i).zfill(2) and r['disposition']=='needs_evidence' for r in cs)} for i in range(1,9)}
    dump(OUT/'coverage.json',coverage)
    family_stats={}
    for family in sorted({f['family_id'] for f in fs}):
        rows=[f for f in fs if f['family_id']==family]
        family_stats[family]={'instances':len(rows),'products':len({pid for f in rows for pid in f['product_ids']}),'listing_keys':len({key for f in rows for key in f['listing_keys']}),'severity':dict(co.Counter(f['severity'] for f in rows))}
    dump(rep/'finding-totals.json',family_stats)
    # No implementation, experiment delta refers only source-vs-parser mismatches.
    lane_titles={1:'Duplicates and same-vendor twins',2:'Wrong merges and physical variants',3:'Categories and scope',4:'Missing specs and recoverability',5:'Incorrect specs and source fidelity',6:'Offers, prices, conditions and history',7:'Scraping completeness, raw and scheduling',8:'References, brands, ids, images and publishing'}
    methods={1:'Exact-code, fingerprint, model and inverted-token searches across all products including multi-vendor, aliases, brandless and decorated titles. 80 within-product vendor-twin groups mechanically enumerated; 53 aliases/27 visible groups. RC-004 three exact all-letter SKU bridges confirmed. Thousands of noisy title/model leads remain source-adjudication pending.',
        2:'All products/50manualproducts enumerated; same-vendor groups and independent field/identity signals reviewed only in bounded families. No new wrong-merge split recommendation confirmed. One current 1PC213833 title says5060Ti8GVENTUS2X while cached detail says5080INSPIRE16G, and catalog combines5080+8GB; source identity is unsettled, not safe to propose a split or guessed replacement. All physical axes/rare/server variants not fully adjudicated.',
        3:'All12pipeline categories (11sitecategories) enumerated. Current is-a gate passes; historical anchors mapped. Narrow independent head-word candidates emitted. All accessories/other are included in population but not individually source verified. SO-DIMM/KSP pre-filter scope and SSD-cooler/RAID-adapter side finds need latest-policy adjudication.',
        4:'Every schema field on every product, exact applicability independent of schema.applies then cross-check. 25101applicable null cells inventoried, false/zero/empty-list separate. All7075listing fact parsers replayed:20claims across17nullproductfields; one5066MHz whitelist loss confirmed RC-003. Other gaps not classified as source omission; all-tier cached/live source recoverability remains unverified.',
        5:'Schema types/bounds checked throughout and invariant gates pass. All range-labelled tolerance cells scanned:27source rows; RC-001 exact counts in finding-totals.json. Source endpoints are independently read excluding±10%; then current helper reproduces failure. Most alarming units/dimensions/OC/connector fields still require individual semantic checks.',
        6:'All7075offer price/stock/stale/condition shapes inventoried. 82unpriced,0zeroprice,234bundle,48new-PC; stale2211TMSoffers from11-11. Snapshot and conditional/history gates pass. Independent entire dated-history replay, live price/availability and query-link resolution are not complete; no unusual-price-alone defect claimed.',
        7:'Five active vendor sources/config/pagination inspected; Plonter historical. Selected raw 9296 rows account for 7075 unique catalog keys, 2221 repeat rows, no absent keys. Repeated TMS sessions persist on saved day 11-11; current newest-selection gate passes. Nano marker fixes not proven deployed. 1PC/Ivory/Yahav can yield partial output before a failed slot/page; runner only blocks zero items, a latent risk, not a current missing-product census. KSP429 policy disagreement retained; no traffic.',
        8:'All4402siteproducts compared with catalogspecs;8760image refs resolve;0visualchecks. All extracted candidate claims reachable(3656) assessed mechanically;17unreached entries retained withinbudget. RC-0028brand/spec/nameprojection mismatchesconfirmed. Manufacturer multiple-entry/alt-name joins, imagevariant correctness, alias/historycontinuity and high-tierfact truth not individually complete.'}
    for i,title in lane_titles.items():
        rows=[f for f in fs if f['lane']==str(i).zfill(2)]
        text=f'# Lane {i:02d}: {title}\n\n**Status: partial. Audit only; no production fixes applied.**\n\nPinned e7cd95223d684cbbdfe72cc2ca76ef568451e963; effective build2026-11-12T12:22:28.077467+00:00. 4402products/7075listings, every category/vendor enumerated in coverage.json. Sequential investigator; independent delegation unavailable. Zero live requests.\n\n## Methods and current results\n\n{methods[i]}\n\n## Confirmed instance links\n\n'
        for family in sorted({f['family_id'] for f in rows}):
            fr=[f for f in rows if f['family_id']==family]
            text+=f'- **{family}**: {len(fr)} distinct observation-level instances; {len({p for f in fr for p in f["product_ids"]})} products. Complete ids/evidence/cause/fix/regression/review in findings.jsonl.\n'
        if not rows:text+='No confirmed new instance in this lane; this is not a clean bill of health.\n'
        text+='\n## Limitations and continuation\n\nEvery generated candidate is retained with disposition in candidates.jsonl. `needs_evidence` is unresolved, not adjudicated. See coverage.json lane totals, previous-findings.md, progress.md. All S1/merge proposals have fresh coordinator reconstruction only; independent review not available. Complete raw/instance evidence under reproduce/. Production helpers supplement rather than establish RPM endpoint evidence; other searches still have documented blind spots.\n'
        filename={1:'01-duplicates.md',2:'02-wrong-merges.md',3:'03-categories.md',4:'04-missing-specs.md',5:'05-incorrect-specs.md',6:'06-offers-prices.md',7:'07-raw-completeness.md',8:'08-references-publish.md'}[i]
        (OUT/filename).write_text(text,encoding='utf-8')
    unresolved=coverage['candidate_unresolved_count']
    s1products={pid for f in fs if f['severity']=='S1' for pid in f['product_ids']}
    readme=f'''# Full-catalog re-audit — PARTIAL checkpoint

**Audit only; no production fixes applied. Stop for owner review before implementation.**

## Outcome

Four confirmed root-cause families affect **{len(affected_pids)} unique products / {len(affected_keys)} listing keys**. There are **{len(fs)} distinct observation-level instances** (listing-level and product-level spec failures are separate records, not additive product counts). **{len(s1products)} products** have confirmed buyer-facing S1 projection/spec errors. No unusual price, similar title or passing gate is treated as correctness proof.

| Priority | Family | Confirmed impact | Durable fix boundary |
|---|---|---|---|
| 1 | RC-001 — RPM tolerance parsed as speed | {family_stats['RC-001']['instances']} listing/product-field instances, {family_stats['RC-001']['products']} products / {family_stats['RC-001']['listing_keys']} listing keys. ±10% becomes minimum10RPM; a source900–1800 can ship10–900. Broad range bounds/backtest pass. | RPM-specific endpoint/tolerance grammar; preserve explicit0; lone maximum does not state a minimum. Full raw-to-fact gate. |
| 2 | RC-002 — partner repair leaves stale spec/name | 8 products / {family_stats['RC-002']['listing_keys']} listings. Product.brand repaired to partner, but GPU/board manufacturer specs and names still NVIDIA/AMD. | Resolve partner before final name/spec/legacy projection; preserve legitimate official chip-maker cards. |
| 3 | RC-003 — real sourced profile refused | KSP148642 Ripjaws5066: `speed_mhz=null` while speedDDR4-5066 and latency7.9 remain. | Review sourced profile whitelist, consistent speed-field validation, no guessed profiles. |
| 4 | RC-004 — all-letter manufacturer-code bridges missed | 3 split groups / 6 products / 7 listing keys: FLUX-PRO, CXMIRROR, ERA-ITX-BU. TMS SKU equals other-vendor printed identifier but digit-required bridge refuses. | Corroborated exact category+brand+physical-axis bridge; not blanket fuzzy/noise merges. Pid/history preservation required. |

Expected values for RPM come from exact cached detail wording excluding tolerance, not model memory. For lone RPM rates the unsupported minimum should be unknown, not an invented lower bound. The split claims include exact bridges and dimensions/axes; no rule prototype was applied to production and post-fix catalog/price/id impact is **unmeasured**. Recommended merge/split and S1 claims received fresh coordinator reconstruction only; **independent review unavailable**.

## Pinned baseline

- Repository `D:\\Mifrat`; HEAD/localmain/localoriginmain `e7cd95223d684cbbdfe72cc2ca76ef568451e963` at pin. No pull/fetch/checkout/commit/push/deploy/issues. Remote freshness unknown.
- Catalog built `2026-11-12T12:22:28.077467+00:00`; effective comparison date2026-11-12UTC. Schema3 from source, **catalog has no schema-version key**.
- Immutable scratch archive plus local decisions and available pcpartdb/pckombo JSON inputs; 7405input files hashed. Existing `docs/prompts/` preserved. Manufacturer page caches were not included in immutable git archive; stored facts are pinned, uncaptured source wording remains a limitation.
- Inputs: TMS 11-11 (latest 21:36:47 UTC), other four 11-12; no newer dated snapshot beyond build-day selection. All 7075 catalog keys accounted for from 9296 selected rows, 2221 duplicates. Saved TMS day holds two sessions; latest-row gate passes, Nano code rollout unproven.

## Coverage actually achieved

- 4402products,7075listings,12pipeline categories/11sitecategories,50manualproducts,1869multivendorproducts,2479one-listing singletons,53aliases;27products visibly repeat a vendor. No bucket excluded by QA dismissal, accessories, other, already-multi or lack of brand.
- Exact per-product/per-field schema applicability:92439applicable cells,67338filled,25101null. Null does not mean bug; recoverability/source omission remains unverified for most.
- 30offline workflowdiagnostics against scratch:29exit0, goldenexit2(identitychurnonly;10of13fixtures resolve via anchors). No real gatefailure; Python3.14local vs3.12CI is recorded. Ref refresh/download/build/publish not invoked. All actual command logs in manifest/reproduce/gates.
- 4661initial heuristic candidates plus audit-instance/policy registrations; **{len(cs)} registry records total, {unresolved} unresolved**. These records overlap and are NOT unique defects. Every candidate has a disposition, but thousands have not been individually adjudicated.
- All4402publishedproducts/specs and8760image refs mechanically checked, no observed specprojection mismatch or missing reference; **0visually verified images,0live pages**. 3656reachableextractclaims/2010entries inventoried;17unreached. Historical JSONL anchors all indexed, family-by-family source reassessment incomplete.

## Important unsettled cases / accepted limits

- 1PC213833 title5060Ti8GVENTUS2X versus cacheddetail5080INSPIRE16G/catalog5080+8GB: wrong-source/join direction unknown; requires exact public-source identity verification, not a guessed correction.
- BW025airflow767CFM, Hyper212height25mm, Zalman60mm and KSP/other residualaxes remain leads, not confirmed physical values without original/live wording.
- KSP detail stays blocked/listingonly. README/code permits429retry4x while bindingstop rules are stricter; this audit uses zerotraffic/stricterstop. No banned-source reprobe, browser workaround, APIusage or fullscrape.
- Manufacturer truth/variant joins, fullhistoryreplay, vendorlivecensus, detailage/refresh, rarepartaxis and visually wrongcovers remain incomplete. No missing-vendor-listing census count claimed.
- Existing raw two-sessionTMS snapshots, staleTMSoffers, nullrequestprices, retainedmanual/orphanledgers, Box/Tray default uncertainty and untrusted extraction facts are not newly invented current defects. R2 blanketnoise stripping remains explicitly rejected.

## Reports and evidence

[Manifest](manifest.json) · [Coverage](coverage.json) · [Findings](findings.jsonl) · [Candidate registry](candidates.jsonl) · [Gap inventory](spec-gaps.jsonl) · [Rejections](rejected.jsonl) · [Previous fixes](previous-findings.md) · [Progress/resume](progress.md) · [Reproduce](reproduce/)

Lane files01–08 document methods and limitations. Exact unique/instance totals are recomputed in `reproduce/finding-totals.json`; examples are illustrative. **This is not a completed audit or a guarantee of no other defects.**
'''
    (OUT/'README.md').write_text(readme,encoding='utf-8')
    (rep/'README.md').write_text('# Reproduction\n\nAudit-only scripts expect a matching `tmp/data-audit/2026-11-12-reaudit/snapshot` and write only this new audit directory/scratch. Restore the pinned git archive and optional inputs matching input-hashes.json; do not run normal normalize entrypoint. `pin.py` refuses an existing run. `inventory.py`, `scan.py`, `adjudicate.py`, then `finish_partial.py` produce this checkpoint. `scan.py` overwrites candidate registry: preserve adjudications before rerunning, or replay adjudicate afterward. `gates.py` is in scratch; exact commands/logs in gate-results.json. Raw/evidence records are public data, no cookies/headers/secrets. Archive .cache page content and production API/extraction jobs were not run.\n',encoding='utf-8')
    # Integrity against original production input hashes (before decisions record).
    hashes=read(RUN/'input-hashes.json');changed=[];missing=[];line_endings=[];worktree_hashes={}
    for rel,record in hashes.items():
        path=ROOT/rel
        if not path.exists():missing.append(rel)
        else:
            worktree_hashes[rel]=sha(path)
            if worktree_hashes[rel]!=record['sha256']:
                if path.read_bytes().replace(b'\r\n',b'\n')==(SNAP/rel).read_bytes().replace(b'\r\n',b'\n'):
                    line_endings.append(rel)
                else:
                    changed.append(rel)
    dump(rep/'worktree-final-hashes.json',worktree_hashes)
    integrity={'utc_checked':dt.datetime.now(dt.timezone.utc).isoformat(),'current_head':git('rev-parse','HEAD'),
        'head_moved':git('rev-parse','HEAD')!=manifest['head'],'input_hashes_checked':len(hashes),'changed_inputs_before_audit_decision_record':changed,'missing_inputs':missing,
        'archive_vs_worktree_line_ending_only_differences':line_endings,
        'hash_scope':'input-hashes.json pins immutable git archive plus copied optional/local inputs; Windows worktree CRLF differs from git LF on listed files. No initial byte-exact worktree hash manifest was captured; initial clean tracked status and final normalized content/gitrevisions provide integrity evidence. Final byte-exact worktree hashes saved separately.',
        'production_unchanged_by_audit':not changed and not missing,'initial_status':manifest['initial_status'],'checkpoint_status':git('status','--short','--branch'),
        'permitted_changes':['docs/audits/2026-11-12-reaudit/**','decisions.md short audit record','tmp/data-audit/2026-11-12-reaudit/** (ignored)'],
        'unrelated_preexisting':'docs/prompts/ remains untracked; not edited', 'independent_review':'unavailable; fresh coordinator reconstruction only'}
    manifest.update(status='partial',coverage_path='coverage.json',candidate_registry='candidates.jsonl',final_integrity=integrity,
        host_access_ledger='reproduce/host-ledger.json',delegation='Unavailable; attempts failed to create child sessions. Work performed sequentially.',
        limitations=['4629 initial candidates unresolved; exact current count in coverage','all-tier spec gap recoverability unfinished','no live/visual verification','historical expected-instance adjudication incomplete','no CI/Nano deployment state inspected','no npm production build writes'],
        commands=read(RUN/'gate-results.json'))
    dump(OUT/'manifest.json',manifest)
    progress=f'''# Resumable audit checkpoint — PARTIAL

Audit only; no production fixes applied. Baselinee7cd9522/build2026-11-12T12:22:28.077467+00:00 remains pinned. Owner review before any implementation.

## Completed

- Authority/docs/latestdecisions/currentpipeline/recentcommits inspected; public source treated as evidence only.
- Inputarchive+7405SHA256hashes, counts/category/vendor/fullapplicablefield/gap inventory.
- 30offlineworkflowdiagnostics; code-side fixtures execute scratch only; no normalize entrypoint/sourcewriter/network.
- Independent heuristic scans all 4402 products / 7075 listings; exact raw 9296 rows / 7075 keys accounting; publish/image reference corpus checks; extracted/detail records enumerated.
- Fourrootcauses expanded83completeobservationrecords affecting42uniqueproducts/50keys; minimalraw/catalogevidence saved; freshcoordinatorreview forS1/merges. Independentinvestigator unavailable.
- EveryhistoricalJSONLanchor mapped; familyfixstatussummary partial.

## Remaining (do not restart/pin new moving state)

- **{unresolved} unresolved candidate records** in candidates.jsonl; overlapping candidates cover {coverage['checks']['individual_source_adjudication']['unresolved_candidate_products']} uniqueproducts. Group by physicalpair/field; do not treat each heuristic record as a defect.
- Most **25101applicablenullcells** need all-tier source/provenance/recoverability checks. One nullfield defect confirmed; siblinganswered nulls classified separately. Never call no local fact a verified live-source omission.
- Every same-vendor53alias and27visibleduplicateproduct needs condition/axis source-adjudication; exactcodes/modeltokenmatches can be false.
- Lane02fullaxis/wrongmerge, lane03scopeaccessories/other, lane05unit/count/connector/OC/numericsemantics, lane06entirehistoryreplay/URLs, lane07vendorcensus/failureledger/actualNanorollout, lane08manufacturer/Icecat/xrefjoinsemantics/idcontinuity/imagevariantvisual checks unfinished.
- Historical prose-only/unlisted instances and remainingexpectedvalue claims not individually reconstructed. Allhistoricalrow anchors are in reproduce/previous-instance-anchors.json.
- Live0,visual0,independentreview0; homeenvironmenteligibility, priorrun/block/windowstate unknown. Do not probeKSPdetail or retired blocked sources. Request owner/Nano captures only when needed for exact candidate.

## Resume

Use `snapshot/` immutable inputs and source. Verify input-hashes.json before mixing evidence. Scripts and fulloutputs in reproduce/. Scratch includes gates.py,selected-raw-rows.json; gates are safe only as inspected and run in scratch. `python -B -X utf8 .../scan.py` regenerates registry and overwrites dispositions; preserve/copy existing auditwork before any rerun. `adjudicate.py` reconstructs the confirmed families from pinneddata without modifyingproduction; `finish_partial.py` regenerates report/coverage/evidence. Do not rerun pin.py (refuses existing), productionnormalize, mfr/extractrefresh orscheduledjobs. Nextinvestigator should independentlyreview RC-001/002/004 against saved exactsource records.

## Integrity

HEADmovement={integrity['head_moved']};changedproductioninputs={len(changed)};missinginputs={len(missing)} before authorizeddecisionrecord. Existingdocs/prompts preserved. Finalstatus and decisionhashdelta recorded in manifest.json after shortrequired decisions.mdentry. All changes remain uncommitted.
'''
    (OUT/'progress.md').write_text(progress,encoding='utf-8')
    print(json.dumps({'families':family_stats,'unique_S1_products':len(s1products),'candidates':len(cs),'unresolved':unresolved,'raw_accounting':[{k:v for k,v in a.items() if k!='raw_to_catalog_keys'} for a in accounting],'integrity':integrity},indent=2))

if __name__=='__main__':main()
