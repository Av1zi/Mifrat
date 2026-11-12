"""Independent full-population candidate searches, followed by helper evidence.

No network, no catalog rebuild, no persistent source-store writes.
"""
import collections as co
import html
import itertools
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

RUN = Path(__file__).resolve().parent
SNAP = RUN / 'snapshot'
OUT = RUN.parents[2] / 'docs/audits/2026-11-12-reaudit'
sys.path.insert(0, str(SNAP))
from scraper.specs import schema
from scraper.specs.build import listing_facts
from scraper.extract import store as ex_store
from scraper.extract.verify import product_text, verified
from scraper.specs.resolvers import vendor_struct

def read(rel):
    return json.loads((SNAP / rel).read_text(encoding='utf-8-sig'))

def compact(text):
    return re.sub(r'[^a-z0-9]', '', str(text or '').casefold())

def words(text):
    text = html.unescape(str(text or '')).casefold()
    return set(re.findall(r'[a-z0-9]+(?:[-.][a-z0-9]+)*', text))

def independently_code(value):
    text = re.sub(r'-PC$', '', str(value or ''), flags=re.I)
    key = compact(text)
    if key.startswith('gv'):
        key = key[2:]
    if len(key) < 4 or (key.isdigit() and len(key) not in {8,12,13,14}) or re.fullmatch(r'c(?:\d{3,5}|ultra)\w*[tb](?:p)?', key):
        return None
    return key

def main():
    catalog = read('data/catalog.json')
    products, listings = catalog['products'], catalog['listings']
    bypid = co.defaultdict(list)
    for e in listings:
        bypid[e['product_id']].append(e)
    candidates, signature_seen = [], set()
    def emit(lane, kind, pids, keys, field=None, observed=None, reason=None):
        sig = (kind, tuple(sorted(pids)), tuple(sorted(keys)), field)
        if sig in signature_seen:
            return
        signature_seen.add(sig)
        candidates.append({'candidate_id': f'C-{len(candidates)+1:05d}', 'lane': lane, 'kind': kind,
            'product_ids': sorted(set(pids)), 'listing_keys': sorted(set(keys)), 'field': field,
            'disposition': 'needs_evidence', 'finding_ids': [], 'rejection_id': None,
            'observed': observed or {}, 'missing_check': reason or 'Adjudicate physical identity/source wording and trace admission against pinned raw/code.'})
    by_code, by_title, by_model = co.defaultdict(list), co.defaultdict(list), co.defaultdict(list)
    for p in products:
        for o in p['offers']:
            codes = set(filter(None, [independently_code(o.get('mpn')), independently_code(o.get('vendor_sku'))]))
            for code in codes:
                by_code[code].append((p,o))
            title = words(o.get('title_raw'))
            title -= {'case','fan','series','kit','pack','edition','new','for','with','the','and','computer','pc','cpu','cooler','liquid','memory','ram','ssd','hdd'}
            if title and any(re.search(r'\d', token) for token in title):
                by_title[(p['category'], tuple(sorted(title)))].append((p,o))
            model = o.get('model_code') or (o.get('attributes') or {}).get('model')
            if model:
                by_model[(p['category'], compact(model))].append((p,o))
        grouped = co.defaultdict(list)
        for o in p['offers']:
            grouped[o['vendor_id']].append(o)
        for vendor, offers in grouped.items():
            if len(offers)>1:
                emit('01','same_vendor_within_product',[p['product_id']],[o['listing_key'] for o in offers],observed={'vendor':vendor,'aliases':[o.get('alias_of') for o in offers]})
        if p['category'] in {'motherboard','gpu'}:
            mfr = (p.get('specs') or {}).get('manufacturer')
            if str(mfr or '').lower() in {'amd','intel','nvidia'} and str(p.get('brand') or '').lower() != str(mfr).lower():
                emit('05','board_partner_spec',[p['product_id']],[o['listing_key'] for o in p['offers']], 'manufacturer',{'spec':mfr,'brand':p.get('brand')},'Trace actual board/card maker evidence; chip designer is not board partner.')
        specs = p.get('specs') or {}
        if p['category']=='memory':
            count,size,total = specs.get('module_count'),specs.get('module_size_gb'),specs.get('total_gb')
            if all(x is not None for x in [count,size,total]) and count*size!=total:
                emit('05','kit_math',[p['product_id']],[o['listing_key'] for o in p['offers']], 'total_gb',{'count':count,'size':size,'total':total})
        if p['category']=='cpu':
            cores,threads=specs.get('core_count'),specs.get('thread_count')
            if cores and threads and threads<cores:
                emit('05','threads_below_cores',[p['product_id']],[o['listing_key'] for o in p['offers']],'thread_count',{'cores':cores,'threads':threads})
        for f in schema.fields_for(p['category']):
            value=specs.get(f.name)
            if value is not None:
                bad = ((f.type=='int' and (not isinstance(value,int) or isinstance(value,bool)))
                    or (f.type=='float' and (not isinstance(value,(int,float)) or isinstance(value,bool)))
                    or (f.type=='bool' and not isinstance(value,bool))
                    or (f.type in {'str','enum'} and not isinstance(value,str))
                    or (f.type=='enum' and value not in f.enum)
                    or (f.type=='list_str' and not isinstance(value,list)))
                if bad or (isinstance(value,(float,int)) and not isinstance(value,bool) and ((f.lo is not None and value<f.lo) or (f.hi is not None and value>f.hi))):
                    emit('05','schema_value',[p['product_id']],[o['listing_key'] for o in p['offers']],f.name,{'value':value,'type':f.type})
    for code, rows in by_code.items():
        pids={p['product_id'] for p,o in rows}
        if len(pids)>1:
            emit('01','cross_product_exact_code',pids,[o['listing_key'] for p,o in rows],observed={'code':code,'titles':[o['title_raw'] for p,o in rows]})
    for kind,index in [('cross_product_title_fingerprint',by_title),('cross_product_model',by_model)]:
        for bucket, rows in index.items():
            pids={p['product_id'] for p,o in rows}
            if len(pids)>1:
                emit('01',kind,pids,[o['listing_key'] for p,o in rows],observed={'bucket':bucket,'titles':[o['title_raw'] for p,o in rows]})
    # Inverted distinctive-model token index: one-sided missing codes, all products.
    digit_tokens=co.defaultdict(list)
    for e in listings:
        for token in words(e.get('title_raw')):
            if re.search('[a-z]',token) and re.search(r'\d',token) and len(token)>=4:
                digit_tokens[(e['category_normalized'],token)].append(e)
    compared=set()
    for bucket, rows in digit_tokens.items():
        if len(rows)>40:
            continue
        for a,b in itertools.combinations(rows,2):
            pair=tuple(sorted([a['listing_key'],b['listing_key']]))
            if a['product_id']==b['product_id'] or pair in compared:
                continue
            compared.add(pair)
            wa,wb=words(a['title_raw']),words(b['title_raw'])
            if len(wa&wb)/max(1,min(len(wa),len(wb)))>=.85:
                emit('01','model_token_overlap',[a['product_id'],b['product_id']],pair,observed={'anchor':bucket,'overlap':sorted(wa&wb),'titles':[a['title_raw'],b['title_raw']]})
    # Independently classify high-risk head/identity words before using helpers.
    for e in listings:
        title=e['title_raw']
        if (re.search(r'\b(?:raid adapter|hdd cage|water block|lcd.*module|barebone|superserver|SYS-\w+)',title,re.I)
                or re.search(r'פאנל.*בלבד|לוח.*(?:B650E-E|B650-E)',title,re.I)):
            emit('03','scope_category_candidate',[e['product_id']],[e['listing_key']],observed={'category':e['category_normalized'],'title':title})
    # Every listing typed fact vs every product field; null means unknown, not defect.
    fact_rows=[]
    for e in listings:
        category=e['category_normalized']
        facts=listing_facts(category,e)
        p=next(p for p in products if p['product_id']==e['product_id'])
        for field, items in facts.items():
            actual=(p.get('specs') or {}).get(field)
            for fact in items:
                if actual is None:
                    fact_rows.append({'product_id':p['product_id'],'listing_key':e['listing_key'],'category':category,'field':field,'value':fact.value,'source':fact.source,'tier':fact.tier})
    (RUN/'null-with-listing-facts.json').write_text(json.dumps(fact_rows,ensure_ascii=False,indent=2),encoding='utf-8')
    groups=co.defaultdict(list)
    for r in fact_rows:
        groups[(r['product_id'],r['field'])].append(r)
    for (pid,field), rows in groups.items():
        emit('04','null_with_typed_listing_fact',[pid],[r['listing_key'] for r in rows],field,{'facts':rows},'Check validation, same-tier conflicts, witness and applicability; a typed fact can legitimately be refused.')
    # Extraction quote semantics: verifier is NOT proof a quote concerns the field.
    entries=ex_store._entries()
    reached=set()
    ex_rows=[]
    for p in products:
        ls=bypid[p['product_id']]
        text=product_text(ls)
        ids=ex_store._candidate_ids(p['product_id'],p['category'],ls)
        reached.update(ids)
        for key in ids:
            entry=entries.get(key)
            if not entry or entry.get('category')!=p['category']:
                continue
            for field,value in (entry.get('specs') or {}).items():
                quote=(entry.get('quotes') or {}).get(field,'')
                verdict=verified(p['category'],field,value,quote,text)
                ex_rows.append({'product_id':p['product_id'],'entry':key,'field':field,'value':value,'quote':quote,'verified':verdict,'trusted':(entry.get('model'),p['category'],field) in ex_store._trusted(),'shipped':(p.get('specs') or {}).get(field),'source':(p.get('spec_sources') or {}).get(field)})
                if (field.startswith('fan_rpm') and re.search(r'\bpump\b|משאבה',quote,re.I)) or (field.endswith('_mm') and re.search(r'\bcm\b',quote,re.I)):
                    emit('08','extract_quote_semantic_candidate',[p['product_id']],[e['listing_key'] for e in ls],field,ex_rows[-1], 'Check that quote concerns this component/field and unit, not merely matching digits.')
    (RUN/'extraction-facts.json').write_text(json.dumps(ex_rows,ensure_ascii=False,indent=2),encoding='utf-8')
    # All public images, offers, ids, prices and specs checked, independent projection.
    publish=[]
    for path in (SNAP/'data/site').glob('*.json'):
        obj=read(path.relative_to(SNAP))
        if isinstance(obj,list) and path.stem!='index':
            publish.extend(obj)
    pmap={p['product_id']:p for p in products}
    refs, mismatches=[],[]
    for p in publish:
        original=pmap.get(p['id'])
        if not original:
            emit('08','published_unknown_id',[p['id']],[])
            continue
        for field,value in (p.get('specs') or {}).items():
            if field!='cooler_type' and value != (original.get('specs') or {}).get(field):
                emit('08','published_spec_mismatch',[p['id']],[o['listing_key'] for o in original['offers']],field,{'site':value,'catalog':original['specs'].get(field)})
        for imagefield in ['image','thumb']:
            ref=p.get(imagefield)
            if not ref:
                continue
            tail=ref.removeprefix('/images/')
            full=SNAP/'data/images'/tail.replace('/thumbs/','/').replace('/covers256/','/')
            refs.append({'product_id':p['id'],'field':imagefield,'ref':ref,'exists':full.exists(),'safe':full.resolve().is_relative_to((SNAP/'data/images').resolve())})
            if not full.exists() or not refs[-1]['safe']:
                emit('08','image_reference',[p['id']],[o['listing_key'] for o in original['offers']],imagefield,refs[-1])
    # All details/ledgers and stale rows enumerated for resumability.
    details={}
    for vendor in ['tms','onepc','ivory','yahav','plonter']:
        path=SNAP/f'data/raw/detail/{vendor}.jsonl'
        if not path.exists():
            continue
        rows=[]
        for n,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():continue
            try: r=json.loads(line)
            except ValueError:continue
            rows.append({'line':n,'sku':r.get('vendor_sku'),'scraped_at':r.get('scraped_at'),'spec_rows':len(r.get('specs') or {}),'url':r.get('url')})
        details[vendor]=rows
    (RUN/'detail-inventory.json').write_text(json.dumps(details,indent=2),encoding='utf-8')
    (RUN/'image-references.json').write_text(json.dumps(refs,indent=2),encoding='utf-8')
    (OUT/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in candidates),encoding='utf-8')
    metrics={'candidate_count':len(candidates),'kinds':dict(co.Counter(r['kind'] for r in candidates)),
        'token_pair_comparisons':len(compared),'listing_typed_facts_for_nulls':len(fact_rows),
        'null_product_fields_with_facts':len(groups),'extract_claims_reached':len(ex_rows),
        'extract_entries_total':len(entries),'extract_unreached':sorted(set(entries)-reached),
        'detail_rows':{v:len(rows) for v,rows in details.items()},'image_refs':len(refs),
        'published_products':len(publish)}
    (RUN/'scan-metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps(metrics,indent=2))

if __name__=='__main__':main()
