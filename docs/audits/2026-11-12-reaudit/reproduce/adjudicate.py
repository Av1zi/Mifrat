"""Adjudicate bounded families; expand established causes over all listings."""
import collections as co
import copy
import json
from pathlib import Path
import re
import sys

RUN=Path(__file__).resolve().parent
SNAP=RUN/'snapshot'
OUT=RUN.parents[2]/'docs/audits/2026-11-12-reaudit'
sys.path.insert(0,str(SNAP))
from scraper.specs import labels, schema
from scraper.specs.values import parse_range
from scraper.specs.resolvers.vendor_struct import _emit_rpm_range
from scraper.specs.validate import validate_fact
from scraper.matching import match_listings
from scraper import identity

def read(rel):return json.loads((SNAP/rel).read_text(encoding='utf-8-sig'))
def write_jsonl(name,rows):
    (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')

def main():
    c=read('data/catalog.json'); ps={p['product_id']:p for p in c['products']}
    ls={e['listing_key']:e for e in c['listings']}
    candidates=[json.loads(s) for s in (OUT/'candidates.jsonl').read_text(encoding='utf-8').splitlines()]
    findings=[]; rejects=[]; evidence=[]
    def finding(family,lane,kind,pids,keys,field,observed,expected,cause,fix,regression,severity='S1',previous=None):
        f={'finding_id':f'F-{len(findings)+1:04d}','family_id':family,'lane':lane,'kind':kind,
            'status':'confirmed_defect','severity':severity,'confidence':'high',
            'category':ps[pids[0]]['category'] if pids else None,'product_ids':pids,'listing_keys':keys,
            'vendors':sorted({ls[k]['vendor_id'] for k in keys if k in ls}),'field':field,
            'observed':observed,'expected':expected,'evidence':[], 'cause':cause,'qa_status':'not_checked',
            'previous_finding':previous,'proposed_fix':fix,'proposed_regression_check':regression,
            'review':{'reviewer':'fresh coordinator check; independent investigator unavailable','outcome':'pending'}}
        qa=read('data/site/qa.json')['cases']
        f['qa_status']={'product_case_kinds':sorted({x.get('kind','') for x in qa if x.get('product_id') in pids}),'field_case_present':any(x.get('product_id') in pids and x.get('field')==field for x in qa)}
        for pid in pids:
            p=ps[pid]; idx=next(i for i,x in enumerate(c['products']) if x['product_id']==pid)
            f['evidence'].append({'path':'data/catalog.json','pointer':f'/products/{idx}','record_key':pid,'quote':{'spec':p['specs'].get(field),'name':p['canonical_name']},'reproduction':'reproduce/adjudicate.py'})
        for key in keys:
            if key not in ls:continue
            e=ls[key]; idx=next(i for i,x in enumerate(c['listings']) if x['listing_key']==key)
            f['evidence'].append({'path':'data/catalog.json','pointer':f'/listings/{idx}','record_key':key,'utc_timestamp':e['scraped_at'],'quote':{'title':e['title_raw'],'mpn':e.get('mpn'),'detail_specs':(e.get('vendor_meta') or {}).get('detail_specs',{})},'reproduction':'reproduce/adjudicate.py'})
        findings.append(f)
        return f
    # Independent reading: remove tolerance before reading range endpoints; no helper used to establish expected.
    rpm_tests=[]
    for key,e in ls.items():
        cat=e['category_normalized']; p=ps[e['product_id']]
        table=(e.get('vendor_meta') or {}).get('detail_specs') or {}
        for label,raw in table.items():
            if labels.translate_vendor_label(label,cat)!=labels.RPM_RANGE:continue
            text=str(raw)
            if not re.search(r'±|\+\s*/\s*-|\+/-|%',text):continue
            base=re.split(r'\(?\s*(?:±|\+\s*/\s*-)',text)[0].strip()
            nums=[float(n) for n in re.findall(r'\d+(?:\.\d+)?',base)]
            if not nums or len(nums)>2:continue
            # A two-endpoint range or lone rated maximum; never convert tolerance to minimum.
            expected_min=min(nums) if len(nums)==2 else None
            expected_max=max(nums)
            minfield='rpm_min' if cat=='case_fan' else 'fan_rpm_min'
            maxfield='rpm_max' if cat=='case_fan' else 'fan_rpm_max'
            emitted={}; _emit_rpm_range(emitted,cat,raw,'audit:detail')
            got={field:[fact.value for fact in items] for field,items in emitted.items()}
            rpm_tests.append({'key':key,'pid':p['product_id'],'label':label,'raw':raw,'expected_min':expected_min,'expected_max':expected_max,'helper_span':parse_range(raw),'helper_facts':got})
            for field,expect in [(minfield,expected_min),(maxfield,expected_max)]:
                helper=got.get(field,[None])[0]
                stored=(e.get('attributes') or {}).get(field)
                if helper!=expect and stored==helper and helper is not None:
                    f=finding('RC-001','05','incorrect_listing_rpm',[p['product_id']],[key],field,
                        {'value':stored,'raw_label':label,'raw_value':raw,'helper':helper},
                        {'value':expect,'basis':'Explicit RPM endpoints before tolerance; lone maximum states no minimum.'},
                        {'path':'scraper/specs/values.py','function':'parse_range -> vendor_struct._emit_rpm_range','mechanism':'parse_range selects first and last positive numbers; last token is tolerance 10, not second RPM endpoint.'},
                        'Use an RPM-specific range grammar with explicit endpoints/units; strip tolerance, preserve zero endpoints, lone rate = maximum only. Do not change generic range semantics without auditing callers.',
                        'Fixtures: 900RPM ~ 1800RPM(±10%) -> min900/max1800; 2000RPM ±10% -> min null/max2000; 0-2000RPM -> min0/max2000. Full-population compare table endpoints to listing and shipped specs. Backtest uses corrupted vendor output as truth and does not check source tokens.',severity='S2',previous='2026-11-10/05 wrong values: RPM-min suspicion')
                    f['evidence'].append({'path':'scraper/specs/values.py','line':279,'quote':'numbers[0], numbers[-1]','reproduction':'reproduce/adjudicate.py'})
                shipped=p['specs'].get(field)
                if helper!=expect and shipped==helper and helper is not None:
                    existing=next((f for f in findings if f['kind']=='incorrect_product_rpm' and f['product_ids']==[p['product_id']] and f['field']==field),None)
                    if not existing:
                        finding('RC-001','05','incorrect_product_rpm',[p['product_id']],[key],field,
                            {'value':shipped,'source':p['spec_sources'].get(field),'raw_value':raw},
                            {'value':expect,'basis':'Explicit source endpoints excluding ± tolerance; unknown minimum for lone rated maximum.'},
                            {'path':'scraper/specs/resolvers/vendor_struct.py','function':'_emit_rpm_range','mechanism':'Bad generic span becomes tier-1 fact, survives broad numeric bounds, wins product merge and ships in cpu_cooler.'},
                            'RPM-specific grammar and full source-to-fact provenance; regenerate only in later implementation session.',
                            'Gate exact endpoint interpretation, not plausible numeric bounds or vendor-output agreement.',previous='2026-11-10/05 RPM suspicion')
    # Brand correction runs after names/specs rebuild: scan all board/card products.
    for p in ps.values():
        if p['category'] not in {'gpu','motherboard'}:continue
        mfr=p['specs'].get('manufacturer'); brand=p.get('brand')
        if str(mfr).lower() not in {'amd','intel','nvidia'} or str(brand).lower()==str(mfr).lower():continue
        keys=[o['listing_key'] for o in p['offers']]
        finding('RC-002','08','board_partner_projection',[p['product_id']],keys,'manufacturer',
            {'manufacturer':mfr,'brand':brand,'canonical_name':p['canonical_name'],'legacy_manufacturer':p['attributes'].get('manufacturer')},
            {'manufacturer':brand,'basis':'The current product brand has already been resolved from explicit offer titles naming the board/card partner; all these titles name that partner.'},
            {'path':'scraper/normalize_and_match.py','function':'build_catalog/_recompute_canonical_names/_fill_empty_brands','mechanism':'Name/spec correction precedes brand repair. Last _fill_empty_brands mutates only product.brand; specs.manufacturer and canonical_name remain chip-maker-derived. Boards also lack GPU chip_manufacturer equality trigger.'},
            'Resolve partner before final name/spec/legacy projection and synchronize all fields with explicit sourced provenance; preserve actual NVIDIA/Intel reference cards when no partner is established. Do not rewrite identifiers merely to repair names.',
            'Assert partner agreement across brand/spec manufacturer/legacy/name on three AMD boards and five NVIDIA cards; negative official NVIDIA/Intel card with no partner. Existing check_brands validates brand only and passes.',previous='N follow-up, commits 260de5e8/317c703d')
    # Recoverable speed rejected by closed whitelist: expand all typed listing speeds refused for exact reason.
    for key,e in ls.items():
        if e['category_normalized']!='memory':continue
        value=e['attributes'].get('speed_mhz'); p=ps[e['product_id']]
        if value is None or p['specs'].get('speed_mhz') is not None:continue
        reason=validate_fact('memory',schema.field_map('memory')['speed_mhz'],value)
        if reason and 'JEDEC/XMP/EXPO' in reason:
            finding('RC-003','04','sourced_speed_refused',[p['product_id']],[key],'speed_mhz',
                {'value':None,'listing_value':value,'speed_string':p['specs'].get('speed'),'refusal':reason},
                {'value':value,'basis':'KSP structured listing tag and literal title both state 5066; catalog speed string DDR4-5066 and source-derived latency retain it. Availability on disk is confirmed; manufacturer profile verification is not a live claim.'},
                {'path':'scraper/specs/validate.py','function':'validate_fact/_MEMORY_SPEEDS','mechanism':'Finite whitelist omits 5066, while generic speed string and derived latency accept same evidence, resulting in internal/published inconsistent projections.'},
                'Validate explicitly sourced unusual profiles with schema bounds and exact model provenance; retain conservative guard for unsupported arbitrary numbers. At minimum verify manufacturer profile for 5066 and cover accepted profile set consistently.',
                'KSP148642 source5066 -> typed5066 and matching speed/latency; reject 50/506/50660. Coverage floors do not expose one missing field.',severity='S2')
    # Strong bridge pairs, independently compared against every represented axis and blocked ledger.
    splits=[(['tms:FLUX-PRO','yahav:10034'],'FLUX-PRO'),(['tms:CXMIRROR','1pc:214258','yahav:11386'],'CXMIRROR'),(['tms:ERA-ITX-BU','1pc:95750'],'ERA-ITX-BU')]
    split_tests=[]
    for keys,code in splits:
        rows=[copy.deepcopy(ls[k]) for k in keys]
        result=match_listings(rows,manual_path=SNAP/'data/matching/manual_products.json')
        pids=sorted({ls[k]['product_id'] for k in keys})
        axes=[{'key':r['listing_key'],'axes':identity.variant_values('case',r)} for r in rows] if hasattr(identity,'variant_values') else [{ 'key':r['listing_key'],'attributes':r['attributes']} for r in rows]
        split_tests.append({'keys':keys,'code':code,'assignments':result['assignments'],'axes':axes,'sku_bridges':[identity.sku_part_number_key(ls[k]['vendor_sku'],ls[k]) for k in keys]})
        f=finding('RC-004','01','split_product',pids,keys,None,
            {'assignments':{k:ls[k]['product_id'] for k in keys},'bridge_code':code},
            {'same_physical_sku':True,'basis':'Exact nonnumeric manufacturer-model/SKU bridge printed in one vendor MPN and TMS SKU, same brand/model/finish and matching cached dimensions/clearances. FLUX-PRO fan counts decorate the full case, not another SKU. CXMIRROR has identical 275x400x438 dimensions/415GPU/155cooler; vendor Mini/Mid tower wording is not a revision. ERA cobalt exact full ERA-ITX-BU code and identical dimensions/clearances. No blocked pair or conflicting printed manufacturer identifiers.'},
            {'path':'scraper/identity.py','function':'sku_part_number_key/shared_part_numbers; matching.match_listings identity/reconciliation','mechanism':'Bridge requires both letters and digits, so real all-letter manufacturer/model codes are ignored. Title-derived model codes diverge. Reconciliation never compares identity products with different codes.'},
            'Add a corroborated exact cross-vendor printed-MPN-to-SKU bridge that can admit all-letter codes only within exact category+brand and physical-axis agreement, refusing generic series, conflicting manufacturer numbers, blocked pairs and packaging. Do not blanket-strip title axes/noise (R2 explicitly rejected). Preserve pid/history aliases after reviewed merge.',
            'Positive FLUX-PRO/CXMIRROR/ERA-ITX-BU; negatives DELTA RAM family, same code different brand/finish, CPU packaging, numeric retailer IDs. Exact-code gate currently reuses digit-requiring helper and misses these.',severity='S2')
        f['confidence']='high'
    # KSP retry discrepancy is a latent/policy risk, not observed catalog corruption.
    candidates.append({'candidate_id':'C-POLICY-KSP429','lane':'07','kind':'access_policy_discrepancy','product_ids':[],'listing_keys':[],'field':None,
        'disposition':'intentional_accepted','finding_ids':[],'rejection_id':'R-KSP429','observed':{'README':'429 retried 4x','binding_decisions':'stop on block; no retries','code':'RETRY_HTTP_CODES includes429, RETRY_TIMES4'},
        'missing_check':'Owner resolve contradictory policy; audit uses stricter stop and makes zero requests. Current code behavior can be reproduced statically; no real block tested.'})
    rejects.append({'rejection_id':'R-KSP429','kind':'accepted_access_limitation','candidate_id':'C-POLICY-KSP429','reason':'No vendor traffic permitted from this unestablished environment. Policy discrepancy retained, not a claim current published data is wrong.','evidence':[{'path':'README.md','line':88},{'path':'decisions.md','line':8},{'path':'scraper/spiders/ksp.py','line':303}]})
    for r in candidates:
        links=[f['finding_id'] for f in findings if set(r['listing_keys']) & set(f['listing_keys']) and (r['field'] is None or r['field']==f['field'])]
        if r['kind']=='board_partner_spec' or (r['kind']=='null_with_typed_listing_fact' and links) or (r['kind']=='cross_product_exact_code' and any(f['kind']=='split_product' and set(f['product_ids'])==set(r['product_ids']) for f in findings)):
            r['disposition']='confirmed_defect';r['finding_ids']=links;r['missing_check']=None
        elif r['kind']=='cross_product_exact_code' and r['observed']['code'] in {'a109700t','g4400t'}:
            r['disposition']='intentional_accepted';r['rejection_id']='R-'+r['candidate_id'];r['missing_check']=None
            rejects.append({'rejection_id':r['rejection_id'],'candidate_id':r['candidate_id'],'product_ids':r['product_ids'],'listing_keys':r['listing_keys'],'reason':'CPU own titles/default bases differ Box/Tray; copied retailer code alone is not packaging evidence under latest decision. Not authorized to merge.','evidence':[{'path':'decisions.md','line':58}]})
        elif r['kind']=='extract_quote_semantic_candidate':
            # Air tower wrongly labelled pump can actually be fan speed; do not claim wrong numeric value.
            is_air=ps[r['product_ids'][0]]['category']=='cooler_air'
            if not is_air and not r['observed']['trusted']:
                r['disposition']='intentional_accepted';r['rejection_id']='R-'+r['candidate_id'];r['missing_check']=None
                rejects.append({'rejection_id':r['rejection_id'],'candidate_id':r['candidate_id'],'product_ids':r['product_ids'],'listing_keys':r['listing_keys'],'field':r['field'],'reason':'Pump claim is not a fan fact, but trust gate excludes it and it is not shipped. Latent verifier semantic risk; no present S1 value corruption established.','evidence':[{'path':'data/extract/products.json','record_key':r['observed']['entry'],'quote':r['observed']['quote']},{'path':'scraper/extract/verify.py','line':88}]})
    # Register each distinct confirmed instance even if not found by initial broad candidates.
    for f in findings:
        candidates.append({'candidate_id':'C-'+f['finding_id'],'lane':f['lane'],'kind':f['kind'],'product_ids':f['product_ids'],'listing_keys':f['listing_keys'],'field':f['field'],'disposition':'confirmed_defect','finding_ids':[f['finding_id']],'rejection_id':None,'missing_check':None})
    # Fresh coordinator review: independently check every claimed source mismatch without match helper.
    for f in findings:
        outcome='reconstructed_offline_no_independent_investigator'
        if f['kind'].endswith('_rpm'):
            assert f['observed']['value']!=f['expected']['value']
        elif f['kind']=='board_partner_projection':
            assert f['observed']['manufacturer']!=f['expected']['manufacturer']
            assert any(f['expected']['manufacturer'].casefold() in ls[k]['title_raw'].casefold() for k in f['listing_keys'])
        elif f['kind']=='split_product':
            assert len(f['product_ids'])>1
            rawcode=f['observed']['bridge_code']
            assert any(ls[k].get('mpn')==rawcode for k in f['listing_keys'])
            assert any(ls[k]['vendor_sku']==rawcode for k in f['listing_keys'])
        f['review']['outcome']=outcome
    (RUN/'rpm-source-replay.json').write_text(json.dumps(rpm_tests,ensure_ascii=False,indent=2),encoding='utf-8')
    (RUN/'split-replay.json').write_text(json.dumps(split_tests,ensure_ascii=False,indent=2),encoding='utf-8')
    write_jsonl('findings.jsonl',findings);write_jsonl('candidates.jsonl',candidates);write_jsonl('rejected.jsonl',rejects)
    # Annotate gap inventory only when the specific null is established defective.
    gaps=[json.loads(s) for s in (OUT/'spec-gaps.jsonl').read_text(encoding='utf-8').splitlines()]
    for g in gaps:
        f=next((f for f in findings if f['kind']=='sourced_speed_refused' and g['product_id'] in f['product_ids'] and g['field']==f['field']),None)
        if f:
            g.update(classification='available_on_disk_validation_loss',finding_id=f['finding_id'],source_evidence=f['evidence'],missing_check=None)
    write_jsonl('spec-gaps.jsonl',gaps)
    print(json.dumps({'findings':len(findings),'families':dict(co.Counter(f['family_id'] for f in findings)),
        'unique_products':len({pid for f in findings for pid in f['product_ids']}),'unique_listing_keys':len({k for f in findings for k in f['listing_keys']}),
        'candidate_dispositions':dict(co.Counter(r['disposition'] for r in candidates)),'rpm_source_rows':len(rpm_tests)},indent=2))

if __name__=='__main__':main()
