"""Population inventory: immutable archive inputs, audit outputs only."""
import collections as co
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

RUN = Path(__file__).resolve().parent
SNAP = RUN / 'snapshot'
OUT = RUN.parents[2] / 'docs/audits/2026-11-12-reaudit'
sys.path.insert(0, str(SNAP))
from scraper.specs import schema

def read(rel):
    return json.loads((SNAP / rel).read_text(encoding='utf-8-sig'))

def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def lines(path):
    decoder = json.JSONDecoder()
    for n, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            yield n, json.loads(line), 'jsonl'
        except json.JSONDecodeError:
            idx = 0
            while idx < len(line):
                while idx < len(line) and line[idx] not in '{[':
                    idx += 1
                if idx >= len(line):
                    break
                try:
                    obj, end = decoder.raw_decode(line[idx:])
                    yield n, obj, 'recovered'
                    idx += end
                except json.JSONDecodeError:
                    yield n, None, 'unrecoverable'
                    break

def main():
    catalog = read('data/catalog.json')
    products, listings = catalog['products'], catalog['listings']
    effective = dt.datetime.fromisoformat(catalog['generated_at']).date()
    vendors = ['tms', 'onepc', 'ksp', 'ivory', 'yahav']
    buckets, fields, gaps = {}, {}, []
    for p in products:
        category = p['category']
        b = buckets.setdefault(category, {'product_ids': [], 'listing_keys': [], 'vendors': {}})
        b['product_ids'].append(p['product_id'])
        for offer in p['offers']:
            b['listing_keys'].append(offer['listing_key'])
            v = b['vendors'].setdefault(offer['vendor_id'], {'listing_keys': [], 'product_ids': []})
            v['listing_keys'].append(offer['listing_key'])
            v['product_ids'].append(p['product_id'])
        specs = p.get('specs') or {}
        for f in schema.fields_for(category):
            key = category + ':' + f.name
            s = fields.setdefault(key, {'category': category, 'field': f.name, 'type': f.type,
                'schema_total': 0, 'applicable': 0, 'not_applicable': 0, 'filled': 0,
                'null': 0, 'false': 0, 'zero': 0, 'empty_list': 0, 'empty_string': 0,
                'answered_by_sibling': 0, 'gap_product_ids': [], 'vendors': {}})
            s['schema_total'] += 1
            # Evaluate schema metadata independently, cross-check the helper.
            applicable = all(specs.get(g) is None or specs.get(g) in allowed for g, allowed in f.applies_to)
            applicable = applicable and all(specs.get(g) is None or specs.get(g) not in vals for g, vals in f.excluded_by)
            assert applicable == schema.applies(category, f.name, specs)
            if not applicable:
                s['not_applicable'] += 1
                continue
            s['applicable'] += 1
            value = specs.get(f.name)
            if value is None:
                s['null'] += 1
                if any(specs.get(other) is not None for other in f.answered_by):
                    s['answered_by_sibling'] += 1
                    classification = 'answered_by_sibling'
                else:
                    s['gap_product_ids'].append(p['product_id'])
                    classification = 'source_recoverability_not_yet_verified'
                gaps.append({'product_id': p['product_id'], 'category': category, 'field': f.name,
                    'expected_type': f.type, 'classification': classification,
                    'listing_keys': [o['listing_key'] for o in p['offers']],
                    'vendors': sorted({o['vendor_id'] for o in p['offers']}),
                    'source_evidence': [], 'missing_check': 'Trace all cached/raw/detail/reference facts and allowed exact-source availability; null alone is not a defect.',
                    'finding_id': None})
            else:
                s['filled'] += 1
                if value is False:
                    s['false'] += 1
                elif isinstance(value, (int, float)) and value == 0:
                    s['zero'] += 1
                elif value == []:
                    s['empty_list'] += 1
                elif value == '':
                    s['empty_string'] += 1
            for vendor in {o['vendor_id'] for o in p['offers']}:
                v = s['vendors'].setdefault(vendor, {'applicable_products': 0, 'filled_products': 0, 'null_products': 0})
                v['applicable_products'] += 1
                v['filled_products' if value is not None else 'null_products'] += 1
    for b in buckets.values():
        b['products'], b['listings'] = len(b['product_ids']), len(b['listing_keys'])
        for v in b['vendors'].values():
            v['product_ids'] = sorted(set(v['product_ids']))
            v['products'], v['listings'] = len(v['product_ids']), len(v['listing_keys'])
    snapshot_rows, selected, recent, new_files = [], [], [], []
    for vendor in vendors:
        candidates = sorted([p for p in (SNAP / 'data/raw').glob('????-??-??/*.jsonl')
            if p.stem in ({'onepc', '1pc'} if vendor == 'onepc' else {vendor})])
        eligible = [p for p in candidates if 0 <= (effective - dt.date.fromisoformat(p.parent.name)).days <= 14]
        chosen = max(eligible, key=lambda p: (p.parent.name, p.stem == vendor)) if eligible else None
        for path in candidates:
            if path.parent.name > effective.isoformat():
                new_files.append(path.relative_to(SNAP).as_posix())
            if chosen == path or (effective - dt.date.fromisoformat(path.parent.name)).days <= 14:
                records = list(lines(path))
                payloads = [r for _, r, _ in records if isinstance(r, dict)]
                r = {'path': path.relative_to(SNAP).as_posix(), 'vendor': vendor,
                    'snapshot_date': path.parent.name, 'rows': len(payloads),
                    'latest_scraped_at': max((str(x.get('scraped_at') or '') for x in payloads), default=None),
                    'earliest_scraped_at': min((str(x.get('scraped_at') or '') for x in payloads), default=None),
                    'category_guess_counts': dict(co.Counter(str(x.get('category_guess')) for x in payloads)),
                    'malformed': dict(co.Counter(status for _, _, status in records if status != 'jsonl')),
                    'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()}
                recent.append(r)
                if chosen == path:
                    selected.append(r)
                    snapshot_rows.extend({'path': r['path'], 'line': n, 'row': obj} for n,obj,status in records if obj)
    (RUN / 'selected-raw-rows.json').write_text(json.dumps(snapshot_rows, ensure_ascii=False), encoding='utf-8')
    (OUT / 'spec-gaps.jsonl').write_text(''.join(json.dumps(g, ensure_ascii=False) + '\n' for g in gaps), encoding='utf-8')
    qa = read('data/site/qa.json')
    raw_offers = [o for p in products for o in p['offers']]
    aliases = [o for o in raw_offers if o.get('alias_of')]
    visible = [o for o in raw_offers if not o.get('alias_of')]
    dup = [p['product_id'] for p in products if len({o['vendor_id'] for o in p['offers'] if not o.get('alias_of')}) < len([o for o in p['offers'] if not o.get('alias_of')])]
    ledger = {}
    for directory in ['data/detail_pending', 'data/detail_scraped', 'data/matching', 'data/mfr', 'data/icecat', 'data/xref', 'data/extract', 'data/specs', 'data/pcpartdb']:
        for path in (SNAP / directory).glob('*.json*'):
            try:
                obj = read(path.relative_to(SNAP)) if path.suffix == '.json' else list(lines(path))
                ledger[path.relative_to(SNAP).as_posix()] = {'shape': type(obj).__name__, 'top_level_count': len(obj), 'keys': list(obj)[:12] if isinstance(obj, dict) else None}
            except Exception as exc:
                ledger[path.relative_to(SNAP).as_posix()] = {'error': type(exc).__name__}
    coverage = {'status': 'partial', 'generated_at': catalog['generated_at'], 'schema_version': schema.SCHEMA_VERSION,
        'totals': {'products': len(products), 'listings': len(listings), 'offers': len(raw_offers),
            'visible_offers': len(visible), 'collapsed_aliases': len(aliases),
            'multi_vendor_products': sum(p['vendor_count'] > 1 for p in products),
            'singleton_one_listing_products': sum(len(p['offers']) == 1 for p in products),
            'single_vendor_products': sum(p['vendor_count'] == 1 for p in products),
            'manual_products': sum(p['matched_by'] == 'manual' for p in products),
            'visible_duplicate_vendor_products': len(dup),
            'stale_offers': sum(bool(o.get('stale')) for o in raw_offers),
            'unknown_stock_offers': sum(o.get('in_stock') is None for o in raw_offers),
            'unpriced_offers': sum(o.get('price_ils') is None for o in raw_offers),
            'zero_priced_offers': sum(o.get('price_ils') == 0 for o in raw_offers),
            'bundle_only_offers': sum(bool(o.get('bundle_only')) for o in raw_offers),
            'new_pc_deal_offers': sum(bool(o.get('new_pc_deal')) for o in raw_offers),
            'spec_applicable_cells': sum(s['applicable'] for s in fields.values()),
            'spec_filled_cells': sum(s['filled'] for s in fields.values()),
            'spec_null_cells': len(gaps)},
        'vendor_listing_counts': dict(co.Counter(e['vendor_id'] for e in listings)),
        'category_buckets': buckets, 'per_field': list(fields.values()),
        'visible_duplicate_vendor_product_ids': dup,
        'alias_listing_keys': [o['listing_key'] for o in aliases],
        'alias_kinds': dict(co.Counter(o.get('alias_kind') for o in aliases)),
        'qa_kinds': dict(co.Counter(x.get('kind') for x in qa['cases'])),
        'identity_kinds': dict(co.Counter(x.get('kind') for x in catalog['identity_cases'])),
        'review_queue_kinds': dict(co.Counter(x.get('kind', 'fuzzy_pair') for x in read('data/review_queue.json'))),
        'skipped_vendors': catalog['skipped_vendors'], 'selected_snapshots': selected, 'newer_raw_files': new_files,
        'recent_snapshots': recent, 'ledger_inventory': ledger,
        'checks': {'population_enumeration': {'mechanically_scanned_products': len(products), 'mechanically_scanned_listings': len(listings)},
            'spec_applicability': {'mechanically_scanned_cells': sum(s['schema_total'] for s in fields.values()), 'independently_cross_checked': True},
            'individual_source_adjudication': {'products': 0, 'live_verified': 0, 'unexamined_products': len(products)}},
        'candidate_search_methods': [], 'blind_spots': ['Individual source recoverability not yet verified for the gap inventory. Vendor live completeness unproven without census.'],
        'candidate_registry': 'candidates.jsonl'}
    dump('coverage.json', coverage)
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    manifest.update({'schema_version': schema.SCHEMA_VERSION, 'schema_version_location': 'scraper/specs/schema.py; catalog has no schema_version field',
                     'input_selection': selected, 'newer_raw_files_not_incorporated': new_files})
    dump('manifest.json', manifest)
    print(json.dumps(coverage['totals'], indent=2))
    print(json.dumps(coverage['vendor_listing_counts'], indent=2))
    print(json.dumps(selected, indent=2))

if __name__ == '__main__':
    main()
