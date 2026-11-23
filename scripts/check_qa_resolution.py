"""Offline regressions for QA-discovered enrichment identity mistakes."""
from __future__ import annotations

import sys
import unittest
import copy
import json
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs import build
from scraper.specs.merge import Fact, TIER_MANUFACTURER, TIER_REFERENCE, TIER_VENDOR
from scraper.specs.resolvers import reference
from scraper import qa_tool
from scraper.normalize_and_match import _adopt_ksp_model_rows
from scraper.specs.report import CoverageReport, qa_cases
from scraper.matching import canonical_category
from scraper.matching import enrich_products_with_pckombo
from scraper.specs.derive import infer_specs
from scraper.specs.validate import cross_check


class EnrichmentIdentityTests(unittest.TestCase):
    def sheet(self, category, attrs, *, sidecar=None, row=None, method='exact-name', manufacturer=None, overrides=None):
        product = {'product_id': 'fixture:qa', 'category': category,
                   'canonical_name': attrs['model'], 'brand': attrs['manufacturer'],
                   'attributes': attrs, 'offers': [], 'pckombo': sidecar}
        listing = {'product_id': product['product_id'], 'listing_key': 'fixture:1',
                   'category_normalized': category, 'title_raw': '',
                   'attributes': attrs, 'vendor_meta': {}}
        matched = (row, 100.0, method) if row else None
        with patch.object(reference, 'match_reference_row', return_value=matched), \
              patch.object(reference, 'overrides_for', return_value=overrides or {}), \
             patch.object(build.mfr_store, 'facts_for', return_value=manufacturer or {}), \
             patch.object(build.icecat_store, 'facts_for', return_value={}), \
             patch.object(build.xref_store, 'facts_for', return_value={}), \
             patch.object(build.extract_store, 'facts_for', return_value={}):
            build.build_product_specs([product], [listing], verbose=False)
        return product['specs']

    def test_exact_pn_sidecar_cannot_override_contradictory_cpu_anchor(self):
        # Real i5-14400F pattern: PC Kombo carries only six P-cores and
        # twelve threads, but the sold CPU has 10 total cores / 16 threads.
        attrs = {'manufacturer': 'Intel', 'model': 'Core i5 14400F',
                 'socket': 'LGA1700', 'core_count': 10, 'thread_count': 16,
                 'integrated_graphics': 'No'}
        row = {'name': 'Intel Core i5-14400F', 'specs': {'core_count': 10}}
        sheet = self.sheet('cpu', attrs, row=row, sidecar={
            'mpn': 'BX8071514400F', 'specs': {'cores': 6, 'threads': 12, 'socket': '1700'}})
        self.assertEqual(sheet['thread_count'], 16)

    def test_consistent_sidecar_still_enriches_missing_facts(self):
        attrs = {'manufacturer': 'Intel', 'model': 'Core i5 14400F',
                 'socket': 'LGA1700', 'core_count': 10, 'integrated_graphics': 'No'}
        sheet = self.sheet('cpu', attrs, sidecar={
            'mpn': 'BX8071514400F', 'specs': {'cores': 10, 'threads': 16}})
        self.assertEqual(sheet['thread_count'], 16)

    def test_sidecar_is_checked_against_matched_reference_anchor(self):
        # A sparse or mistaken vendor anchor must not give the bad sidecar a
        # pass once an exact-name reference supplies the total core count.
        attrs={'manufacturer':'Intel','model':'Core i5 14400','socket':'LGA1700',
               'core_count':6,'thread_count':16}
        sheet=self.sheet('cpu',attrs,row={'name':'Intel Core i5-14400','specs':{'core_count':10}},
                         sidecar={'mpn':'BX8071514400','specs':{'cores':6,'threads':12}})
        self.assertEqual(sheet['core_count'],10)
        self.assertEqual(sheet['thread_count'],16)

    def test_sidecar_does_not_become_vendor_bridge_before_its_anchor_check(self):
        from scraper import matching
        product={'category':'cpu','attributes':{'core_count':10},
                 'offers':[{'mpn':'BX8071514400'}]}
        row={'mpn':'BX8071514400','url':'https://example.invalid/cpu',
             'specs':{'Cores | Cores':'6','Cores | Threads':'12'}}
        with patch.object(matching,'_pckombo_load_index',return_value={}), \
             patch.object(matching,'_pckombo_find_by_mpn',return_value=row):
            enrich_products_with_pckombo([product])
        self.assertEqual(product['attributes'],{'core_count':10})
        self.assertEqual(product['pckombo']['specs']['threads'],12)

    def test_fuzzy_family_fan_performance_cannot_replace_exact_manufacturer_sku(self):
        attrs = {'manufacturer': 'be quiet!', 'model': 'Light Wings LX 120mm PWM White',
                 'part_numbers': ['BL122'], 'size_mm': 120, 'color': 'White'}
        manufacturer = {key: [Fact(value, TIER_MANUFACTURER, 'manufacturer:be quiet!')]
                        for key, value in {'rpm_max': 1600, 'airflow_cfm': 51.5, 'noise_db': 25.5}.items()}
        row = {'name': 'be quiet! Light Wings LX', 'variants': 2,
               'specs': {'size_mm': 120, 'rpm_max': 1500, 'airflow_cfm': 48.8, 'noise_db': 28.5}}
        sheet = self.sheet('case_fan', attrs, row=row, method='fuzzy+anchor', manufacturer=manufacturer)
        self.assertEqual((sheet['rpm_max'], sheet['airflow_cfm'], sheet['noise_db']), (1600, 51.5, 25.5))

    def test_exact_name_fan_reference_retains_reference_tier(self):
        facts = reference.reference_facts('case_fan', {'specs': {'rpm_max': 1600}}, method='exact-name')
        self.assertEqual(facts['rpm_max'][0].tier, TIER_REFERENCE)

    def test_variant_intersection_requires_every_row_to_state_the_fact(self):
        row = reference._intersect_rows([
            {'name': 'same family', 'specs': {'size_mm': 120, 'rpm_max': 1500}},
            {'name': 'same family', 'specs': {'size_mm': 120}},
        ])
        self.assertEqual(row['specs'], {'size_mm': 120})

    def test_model_override_is_not_displaced_by_more_digits_in_vendor_prose(self):
        from scraper.specs.merge import merge_facts, TIER_OVERRIDE
        result=merge_facts('cooler_air',{'model':[
            Fact('NH-U12S chromax.black',TIER_OVERRIDE,'override:file'),
            Fact('NH-U12S chromax. 120 RAM',TIER_VENDOR,'vendor:detail'),
        ]})
        self.assertEqual(result.specs['model'],'NH-U12S chromax.black')

    def test_series_override_survives_real_fact_coercion_and_spec_build(self):
        product = {'product_id': 'fixture:qa', 'category': 'cpu'}
        with patch.object(reference, 'load_overrides', return_value={
                'fixture:qa': {'generation': 'Ultra Series 2'}}):
            overrides = reference.overrides_for(product)
        sheet = self.sheet('cpu', {'manufacturer': 'Intel', 'model': 'Core Ultra 5 225',
                                  'socket': 'LGA1851'}, overrides=overrides)
        self.assertEqual(sheet['generation'], 'Ultra Series 2')

    def test_first_build_rekey_reaches_override_before_specs_are_built(self):
        from scraper import normalize_and_match as normalize
        from scraper.extract import store as extract_store
        old, new = 'model:cooler_air:old-chromax', 'model:cooler_air:new-black-chromax'
        key = 'tms:fixture-cooler'
        attrs = {'manufacturer': 'Noctua', 'model': 'NH-U12S chromax.black 120 RAM',
                 'height_mm': 158, 'fan_size_mm': 120, 'color': 'Black'}
        listing = {'listing_key': key, 'vendor_id': 'tms', 'vendor_sku': 'fixture-cooler',
                   'category_normalized': 'cooler_air', 'title_raw': 'Noctua NH-U12S chromax.black',
                   'attributes': attrs, 'vendor_meta': {}, 'url': 'https://example.invalid/cooler'}
        product = {'product_id': new, 'category': 'cooler_air', 'brand': 'Noctua',
                   'canonical_name': 'Noctua NH-U12S chromax.black', 'attributes': attrs,
                   'offers': [{'listing_key': key, 'vendor_id': 'tms'}]}
        matched = {'products': [product], 'assignments': {key: new},
                   'product_sizes': {new: 1}, 'pid_aliases': {}, 'identity_cases': []}
        saved_aliases = dict(extract_store._RUN_ALIASES)
        try:
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                output, meta = Path(directory) / 'catalog.json', Path(directory) / 'meta.json'
                output.write_text(json.dumps({'listings': [{'listing_key': key, 'product_id': old}],
                                              'pid_aliases': {}}), encoding='utf-8')
                meta.write_text('{"pid_aliases": {}}', encoding='utf-8')
                stack.enter_context(patch.object(normalize, 'OUTPUT_PATH', output))
                stack.enter_context(patch.object(extract_store, 'ALIASES', meta))
                extract_store.set_run_aliases({})
                stack.enter_context(patch.object(normalize, 'VENDOR_SPIDER_NAMES', ['tms']))
                stack.enter_context(patch.object(normalize, 'find_latest_snapshot', return_value=(output, '2026-11-23')))
                stack.enter_context(patch.object(normalize, 'load_listings', return_value=[copy.deepcopy(listing)]))
                stack.enter_context(patch.object(normalize, '_snapshot_freshness', return_value=('2026-11-23', False)))
                stack.enter_context(patch.object(normalize, 'enrich_listing', side_effect=lambda row: row))
                stack.enter_context(patch.object(normalize, '_attach_eilat', return_value=([], {})))
                stack.enter_context(patch.object(normalize, '_merge_detail_specs', side_effect=lambda rows: rows))
                stack.enter_context(patch.object(normalize, 'match_listings', return_value=copy.deepcopy(matched)))
                stack.enter_context(patch.object(normalize, 'suggest_fuzzy_matches', return_value=[]))
                stack.enter_context(patch.object(reference, 'match_reference_row', return_value=None))
                stack.enter_context(patch.object(reference, 'load_overrides', return_value={old: {'model': 'NH-U12S chromax.black'}}))
                for store in (build.mfr_store, build.icecat_store, build.xref_store, build.extract_store):
                    stack.enter_context(patch.object(store, 'facts_for', return_value={}))
                catalog, _, _ = normalize.build_catalog(datetime(2026, 11, 23, tzinfo=timezone.utc))
                self.assertEqual(catalog['products'][0]['specs']['model'], 'NH-U12S chromax.black')
                self.assertEqual(catalog['products'][0]['spec_sources']['model'], 'override')
                self.assertEqual(catalog['pid_aliases'].get(old), new)
        finally:
            extract_store.set_run_aliases(saved_aliases)


class SourceSemanticsTests(unittest.TestCase):
    def test_lighting_presence_does_not_invent_an_addressable_standard(self):
        from scraper.specs import schema
        from scraper.specs.values import coerce
        field = schema.field_map('memory')['lighting']
        for raw in ('Yes', 'true', '1', True):
            with self.subTest(raw=raw):
                self.assertEqual(coerce(field, raw, 'memory'), 'Yes')
        self.assertEqual(coerce(field, 'No', 'memory'), 'No')
        self.assertEqual(coerce(field, 'ARGB', 'memory'), 'ARGB')

    def test_explicit_lighting_type_refines_generic_presence(self):
        from scraper.specs import schema
        from scraper.specs.values import coerce
        from scraper.specs.merge import merge_facts, TIER_TITLE
        field = schema.field_map('memory')['lighting']
        result = merge_facts('memory', {'lighting': [
            Fact(coerce(field, 'Yes', 'memory'), TIER_VENDOR, 'vendor:detail'),
            Fact('RGB', TIER_TITLE, 'title:own'),
        ]})
        self.assertEqual(result.specs['lighting'], 'RGB')

    def test_explicit_no_lighting_is_not_replaced_by_a_title(self):
        from scraper.specs.merge import merge_facts, TIER_TITLE
        result = merge_facts('case_fan', {'led': [
            Fact('No', TIER_MANUFACTURER, 'manufacturer:sheet'),
            Fact('ARGB', TIER_TITLE, 'title:own'),
        ]})
        self.assertEqual(result.specs['led'], 'No')
        self.assertTrue(result.conflicts)

    def test_lighting_presence_override_remains_authoritative(self):
        from scraper.specs.merge import merge_facts, TIER_OVERRIDE
        result = merge_facts('memory', {'lighting': [
            Fact('Yes', TIER_OVERRIDE, 'override:file'),
            Fact('RGB', TIER_VENDOR, 'vendor:detail'),
        ]})
        self.assertEqual(result.specs['lighting'], 'Yes')

    def test_explicit_ultra_series_is_not_a_legacy_core_generation(self):
        from scraper.specs import schema
        from scraper.specs.values import coerce
        field = schema.field_map('cpu')['generation']
        self.assertEqual(coerce(field, 'Intel Core Ultra Processors (Series 2)', 'cpu'),
                         'Ultra Series 2')

    def test_unqualified_series_retains_its_own_semantics(self):
        from scraper.specs.canon import canon_generation
        self.assertEqual(canon_generation('Series 2'), 'Series 2')
        self.assertEqual(canon_generation('Generation 14'), 'Gen 14')
        self.assertEqual(canon_generation('Gen 2'), 'Gen 2')

    def test_core_i5_i7_i9_name_alone_cannot_establish_no_ecc(self):
        from scraper.specs import tables
        for model in ('Core i5 14600KF', 'Core i7 14700', 'Core i9 14900K'):
            with self.subTest(model=model), patch.object(tables, 'load', return_value={}):
                specs = {'manufacturer': 'Intel', 'model': model, 'socket': 'LGA1700'}
                infer_specs('cpu', specs, {})
                self.assertIsNone(specs.get('ecc_support'))

    def test_explicit_ecc_source_is_not_discarded(self):
        specs = {'manufacturer': 'Intel', 'model': 'Core i9 14900K',
                 'socket': 'LGA1700', 'ecc_support': True}
        sources = {'ecc_support': 'manufacturer'}
        infer_specs('cpu', specs, sources)
        self.assertIs(specs['ecc_support'], True)
        self.assertEqual(sources['ecc_support'], 'manufacturer')

    def test_interior_dot_colour_is_preserved_in_the_model(self):
        from scraper.specs.resolvers.vendor_struct import _model_from_title
        self.assertEqual(_model_from_title('Noctua NH-U12S chromax.black 120mm', 'Noctua'),
                         'NH-U12S chromax.black')
        self.assertEqual(_model_from_title('Noctua NF-A14 PWM chromax.black.swap 140mm', 'Noctua'),
                         'NF-A14 PWM chromax.black.swap')

    def test_bare_colour_suffix_is_still_title_noise(self):
        from scraper.specs.resolvers.vendor_struct import _model_from_title
        self.assertEqual(_model_from_title('Noctua NH-U12S Black 120mm', 'Noctua'), 'NH-U12S')

    def test_roman_model_edition_is_not_a_storage_interface(self):
        from scraper.specs.resolvers.vendor_struct import _model_from_title
        self.assertEqual(_model_from_title('ASUS ROG Strix LC III 360', 'ASUS'),
                         'ROG Strix LC III 360')

    def test_explicit_performance_units_are_not_model_words(self):
        from scraper.specs.resolvers.vendor_struct import _model_from_title
        self.assertEqual(_model_from_title('ARCTIC Liquid Freezer III Pro 360 3000RPM 77CFM', 'ARCTIC'),
                         'Liquid Freezer III Pro 360')
        self.assertEqual(_model_from_title('Samsung 870 EVO SATA III 1TB', 'Samsung'), '870 EVO')

    def test_a_performance_number_alone_cannot_make_a_model_identifier(self):
        from scraper.specs.resolvers.vendor_struct import _model_from_title
        self.assertIsNone(_model_from_title('ARCTIC Liquid Freezer III Pro 360mm 3000RPM 77CFM', 'ARCTIC'))

    def test_exact_arctic_brand_alias_has_one_spelling(self):
        from scraper.specs.canon import canon_brand
        self.assertEqual(canon_brand('Arctic Cooling'), 'ARCTIC')
        self.assertEqual(canon_brand('Noctua Cooling'), 'Noctua Cooling')


class MemoryKitCellTests(unittest.TestCase):
    def facts(self, label, value):
        from scraper.specs.resolvers.vendor_struct import parse_detail_specs
        return parse_detail_specs('memory', {label: value})

    def test_capacity_label_reads_the_whole_kit_not_its_module_count(self):
        for label, raw, total, size in [('נפח', '2x16GB', 32, 16),
                                        ('RAM / RAM Capacity', '2x24GB', 48, 24)]:
            with self.subTest(label=label):
                facts = self.facts(label, raw)
                self.assertEqual(facts['total_gb'][0].value, total)
                self.assertEqual(facts['module_count'][0].value, 2)
                self.assertEqual(facts['module_size_gb'][0].value, size)

    def test_reverse_kit_capacity_and_matching_printed_total(self):
        for raw in ('24GBx2', '48GB (2x24GB)', '48GB (24GBx2)'):
            with self.subTest(raw=raw):
                facts = self.facts('נפח', raw)
                self.assertEqual(facts['total_gb'][0].value, 48)
                self.assertEqual(facts['module_count'][0].value, 2)
                self.assertEqual(facts['module_size_gb'][0].value, 24)

    def test_plain_capacity_does_not_invent_a_module_quantity(self):
        facts = self.facts('נפח', '16GB')
        self.assertEqual(facts['total_gb'][0].value, 16)
        self.assertNotIn('module_count', facts)

    def test_contradictory_or_ambiguous_kit_cell_is_not_half_read(self):
        for raw in ('96GB (2x24GB)', '2x16GB or 4x8GB', '2x16GBx2', 'not 2x16GB'):
            with self.subTest(raw=raw):
                facts = self.facts('נפח', raw)
                self.assertNotIn('total_gb', facts)
                self.assertNotIn('module_count', facts)
                self.assertNotIn('module_size_gb', facts)

    def test_unitless_kit_is_not_a_two_gigabyte_capacity(self):
        self.assertNotIn('total_gb', self.facts('נפח', '2x16'))

    def test_coercion_reparses_each_kit_role_not_the_first_number(self):
        from scraper.specs import schema
        from scraper.specs.values import coerce
        for raw in ('2x16GB', '16GBx2', '32GB (2x16GB)'):
            for field, want in [('total_gb', 32), ('module_count', 2), ('module_size_gb', 16)]:
                with self.subTest(raw=raw, field=field):
                    self.assertEqual(coerce(schema.field_map('memory')[field], raw, 'memory'), want)

    def test_quote_verifier_rejects_capacity_and_quantity_role_swaps(self):
        from scraper.extract.verify import verified
        quote = '2x16GB'
        for field, wrong in [('total_gb', 2), ('module_size_gb', 2), ('module_count', 16)]:
            with self.subTest(field=field):
                self.assertIsNone(verified('memory', field, wrong, quote, quote))
        self.assertEqual(verified('memory', 'total_gb', 32, quote, quote), 32)
        self.assertEqual(verified('memory', 'module_size_gb', 16, quote, quote), 16)
        self.assertEqual(verified('memory', 'module_count', 2, quote, quote), 2)

    def test_contradictory_kit_quote_cannot_rescue_a_number_anywhere_in_it(self):
        from scraper.extract.verify import verified
        quote = '96GB (2x24GB)'
        for value in (2, 24, 48, 96):
            with self.subTest(value=value):
                self.assertIsNone(verified('memory', 'total_gb', value, quote, quote))


class QaWorkbenchTests(unittest.TestCase):
    def test_alias_override_is_fixed_when_the_rebuilt_case_confirms_it(self):
        data = {
            qa_tool.CATALOG: {'products': [{'product_id': 'new', 'category': 'memory',
                                           'specs': {'cas_latency': 30},
                                           'spec_sources': {'cas_latency': 'override'}}],
                              'pid_aliases': {'old': 'new'}},
            qa_tool.QA: {'cases': [{'kind': 'spec_conflict', 'product_id': 'new',
                                   'category': 'memory', 'field': 'cas_latency',
                                   'kept': 30, 'dropped': 32, 'fixed': True}]},
            qa_tool.OVERRIDES: {'products': {'old': {'cas_latency': 30}}},
        }
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: data.get(path, default)):
            case = qa_tool.build_cases()[0]
        self.assertEqual(case['state'], 'fixed')
        self.assertEqual(case['fixed_value'], 30)

    def test_unapplied_alias_override_is_not_hidden_as_fixed(self):
        data = {
            qa_tool.CATALOG: {'products': [{'product_id': 'new', 'category': 'memory',
                                           'specs': {'cas_latency': 32},
                                           'spec_sources': {'cas_latency': 'vendor'}}],
                              'pid_aliases': {'old': 'new'}},
            qa_tool.QA: {'cases': [{'kind': 'spec_conflict', 'product_id': 'new',
                                   'category': 'memory', 'field': 'cas_latency',
                                   'kept': 32, 'dropped': 30}]},
            qa_tool.OVERRIDES: {'products': {'old': {'cas_latency': 30}}},
        }
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: data.get(path, default)):
            self.assertEqual(qa_tool.build_cases()[0]['state'], 'open')

    def test_clear_alias_override_targets_the_applied_ledger_entry_only(self):
        data = {
            qa_tool.CATALOG: {'products': [{'product_id': 'new', 'category': 'memory'}],
                              'pid_aliases': {'old': 'new'}},
            qa_tool.OVERRIDES: {'products': {'old': {'cas_latency': 30},
                                           'other': {'cas_latency': 36}}},
        }
        writes = []
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: copy.deepcopy(data.get(path, default))), \
             patch.object(qa_tool, '_write', side_effect=lambda path, value: writes.append(value)):
            qa_tool.act({'action': 'clear', 'product_id': 'new', 'field': 'cas_latency'})
        self.assertEqual(writes[0], {'products': {'other': {'cas_latency': 36}}})

    def test_rekey_aliases_do_not_borrow_evidence_across_a_split(self):
        from scraper.normalize_and_match import _carry_pid_aliases
        previous = {'listings': [{'listing_key': 'a', 'product_id': 'old'},
                                 {'listing_key': 'b', 'product_id': 'old'}],
                    'pid_aliases': {'older': 'old'}}
        current = {'products': [{'product_id': 'new-a'}, {'product_id': 'new-b'}],
                   'listings': [{'listing_key': 'a', 'product_id': 'new-a'},
                                {'listing_key': 'b', 'product_id': 'new-b'}]}
        _carry_pid_aliases(current, previous)
        self.assertEqual(current['pid_aliases'], {})

    def test_clear_last_override_field_removes_empty_entry(self):
        data={'products':{'p':{'rpm_max':1600},'other':{'rpm_max':1700}}}
        writes=[]
        with patch.object(qa_tool,'_read',return_value=data), \
             patch.object(qa_tool,'_write',side_effect=lambda path,data:writes.append(data)):
            qa_tool.act({'action':'clear','product_id':'p','field':'rpm_max'})
        self.assertEqual(writes[0],{'products':{'other':{'rpm_max':1700}}})
    def test_alias_dismissal_state_matches_public_page(self):
        pid = 'model:case:live'
        data = {
            qa_tool.CATALOG: {'products': [{'product_id': pid}], 'pid_aliases': {'model:case:old': pid}},
            qa_tool.QA: {'cases': [{'kind': 'variant_conflict', 'product_id': pid, 'category': 'case'}]},
            qa_tool.DISMISSED: {'variant_conflict|model:case:old|': True},
        }
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: data.get(path, default)):
            self.assertEqual(qa_tool.build_cases()[0]['state'], 'dismissed')

    def test_fuzzy_decision_uses_fresh_key_without_overwriting_history(self):
        pair = {'listing_a': 'a:1', 'listing_b': 'b:2'}
        old = {'0': {'decision': 'not_match', 'listing_a': 'old:1', 'listing_b': 'old:2'}}
        writes = []
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: [pair] if path == qa_tool.QUEUE else old), \
             patch.object(qa_tool, '_write', side_effect=lambda path, value: writes.append(value)), \
             patch.object(qa_tool.subprocess, 'run'):
            qa_tool.act({'action': 'not_match', 'index': 0})
        self.assertEqual(writes[0]['0']['listing_a'], 'old:1')
        self.assertEqual(writes[0]['1'], {**pair, 'decision': 'not_match'})

    def test_issue_case_retains_dropped_value_and_rule(self):
        report = {'issues': [{'kind': 'spec_conflict', 'product_id': 'p', 'category': 'memory',
                              'field': 'total_gb', 'kept': 32, 'dropped': 2, 'rule': 'module_arithmetic'}]}
        case = qa_cases(report)[0]
        self.assertEqual(case.get('dropped'), 2)
        self.assertEqual(case.get('rule'), 'module_arithmetic')

    def test_repartition_preserves_all_manual_members_and_unrelated_products(self):
        manual = {'products': [{'product_id': 'manual:case:old', 'category': 'case',
                                'brand': 'ASUS', 'attributes': {}, 'listing_keys': ['ksp:a', 'ksp:b']},
                               {'product_id': 'manual:case:other', 'listing_keys': ['other:1']}],
                  'blocked_pairs': []}
        writes = []
        with patch.object(qa_tool, '_read', return_value=manual), \
             patch.object(qa_tool, '_write', side_effect=lambda path, data: writes.append(data)):
            qa_tool.act({'action': 'repartition', 'product_id': 'manual:case:old',
                         'groups': [['ksp:a'], ['ksp:b']]})
        products = writes[0]['products']
        self.assertEqual(products[0]['listing_keys'], ['ksp:a'])
        self.assertEqual(products[1]['listing_keys'], ['other:1'])
        self.assertEqual(products[2]['listing_keys'], ['ksp:b'])
        self.assertNotEqual(products[0]['product_id'], products[2]['product_id'])

    def test_repartition_refuses_dropped_members_before_writing(self):
        manual = {'products': [{'product_id': 'manual:case:old', 'listing_keys': ['ksp:a', 'ksp:b']}], 'blocked_pairs': []}
        with patch.object(qa_tool, '_read', return_value=manual), patch.object(qa_tool, '_write') as write:
            with self.assertRaises(ValueError):
                qa_tool.act({'action': 'repartition', 'product_id': 'manual:case:old', 'groups': [['ksp:a']]})
            write.assert_not_called()


class DetailIdentifierTests(unittest.TestCase):
    def test_explicit_part_number_row_does_not_need_copied_model_corroboration(self):
        listings = [{'vendor_id': 'ksp', 'vendor_sku': '471840', 'category_normalized': 'case',
                     'vendor_meta': {'detail_specs': {'P/N': '90DC00V0-B39000', 'דגם': 'Prime AP303'}}},
                    {'vendor_id': 'ksp', 'vendor_sku': '471842', 'category_normalized': 'case',
                     'vendor_meta': {'detail_specs': {'P/N': '90DC00V0-B39010', 'דגם': 'Prime AP303'}}}]
        self.assertEqual(_adopt_ksp_model_rows(listings, {}), 2)
        self.assertEqual([l.get('mpn') for l in listings], ['90DC00V0-B39000', '90DC00V0-B39010'])

    def test_retailer_number_in_part_number_row_is_not_adopted(self):
        listing = {'vendor_id': 'ksp', 'vendor_sku': '471840', 'category_normalized': 'case',
                   'vendor_meta': {'detail_specs': {'P/N': '471840'}}}
        self.assertEqual(_adopt_ksp_model_rows([listing], {}), 0)
        self.assertIsNone(listing.get('mpn'))


class AccessoryCategoryTests(unittest.TestCase):
    def test_nvlink_bridge_is_not_a_gpu_even_when_title_names_titan_rtx(self):
        self.assertEqual(canonical_category('gpu', 'NVIDIA NVLINK for TITAN RTX 4-slot'), 'accessories')
        self.assertEqual(canonical_category('gpu', 'NVIDIA TITAN RTX 24GB graphics card'), 'gpu')

    def test_standalone_ssd_heatsink_is_not_a_drive(self):
        self.assertEqual(canonical_category('storage', 'קירור פסיבי לכונן SSD Coolleo CL-V3SSD-BK בצבע שחור'), 'accessories')
        self.assertEqual(canonical_category('storage', 'Samsung 990 PRO SSD with heatsink 2TB'), 'storage')

    def test_exact_fractal_bracket_code_recovers_mislabelled_vendor_title(self):
        self.assertEqual(canonical_category('storage', 'כונן SSD Fractal Design FD-A-BRKT-001 צבע שחור', sku='FD-A-BRKT-001'), 'accessories')


class ReportingAndApplicabilityTests(unittest.TestCase):
    def fixed_report(self, source='override', actual=30, kept=30):
        report = CoverageReport()
        report.add_product(product_id='p', category='memory',
                           specs={'memory_type': 'DDR5', 'form_factor': 'DIMM', 'cas_latency': actual},
                           sources={'cas_latency': source}, invalid=[], reference={}, issues=[],
                           conflicts=[{'field': 'cas_latency', 'kept': {'value': kept, 'tier': 'override'},
                                       'dropped': {'value': 32, 'tier': 'vendor'}}])
        return report

    def test_effective_override_is_reported_as_fixed_not_an_open_conflict(self):
        cases = qa_cases(self.fixed_report().to_dict())
        self.assertTrue(cases[0].get('fixed'))

    def test_missing_or_changed_override_effect_still_requires_review(self):
        for source, actual in [('vendor', 30), ('override', 28)]:
            with self.subTest(source=source, actual=actual):
                cases = qa_cases(self.fixed_report(source, actual).to_dict())
                self.assertFalse(cases[0].get('fixed'))

    def test_fixed_override_does_not_consume_the_open_category_cap(self):
        report = self.fixed_report()
        for pid in ('open-1', 'open-2'):
            report.add_product(product_id=pid, category='memory',
                               specs={'memory_type': 'DDR5', 'form_factor': 'DIMM', 'cas_latency': 36},
                               sources={'cas_latency': 'vendor'}, invalid=[], reference={}, issues=[],
                               conflicts=[{'field': 'cas_latency', 'kept': {'value': 36}, 'dropped': {'value': 40}}])
        cases = qa_cases(report.to_dict(), limit=None, per_category=1)
        self.assertEqual(len(cases), 2)
        self.assertEqual(sum(bool(case.get('fixed')) for case in cases), 1)

    def test_lighting_presence_and_explicit_type_are_compatible(self):
        for field in ('lighting', 'led'):
            report = {'conflicts': [{'category': 'memory' if field == 'lighting' else 'case_fan',
                                    'product_id': 'p', 'field': field,
                                    'kept': {'value': 'RGB'}, 'dropped': {'value': 'Yes'}}]}
            self.assertEqual(qa_cases(report), [])
            self.assertEqual(len(report['conflicts']), 1)

    def test_lighting_standard_and_negative_conflicts_remain_visible(self):
        for kept, dropped in [('RGB', 'ARGB'), ('No', 'Yes'), ('No', 'RGB')]:
            report = {'conflicts': [{'category': 'memory', 'product_id': 'p',
                                    'field': 'lighting', 'kept': {'value': kept},
                                    'dropped': {'value': dropped}}]}
            self.assertEqual(len(qa_cases(report)), 1)

    def test_dropped_cpu_field_reports_its_actual_final_answer(self):
        specs = {'manufacturer': 'Intel', 'model': 'Core Ultra 7 265F',
                 'socket': 'LGA1851', 'core_count': 20, 'thread_count': 8, 'smt': False}
        sources = {field: 'vendor' for field in specs}
        issues = cross_check('cpu', specs, sources)
        infer_specs('cpu', specs, sources)
        self.assertEqual(specs['thread_count'], 20)
        report = CoverageReport()
        report.add_product(product_id='p', category='cpu', specs=specs, sources=sources,
                           conflicts=[], invalid=[], reference={}, issues=issues)
        case = next(c for c in qa_cases(report.to_dict()) if c.get('field') == 'thread_count')
        self.assertEqual(case['kept'], 20)
        self.assertEqual(case['dropped'], 8)
        self.assertEqual(case.get('kept_field'), 'core_count')

    def test_retaining_a_supporting_field_does_not_invent_a_missing_answer(self):
        specs = {'core_count': 24, 'thread_count': 8}
        sources = {field: 'vendor' for field in specs}
        issues = cross_check('cpu', specs, sources)
        report = CoverageReport()
        report.add_product(product_id='p', category='cpu', specs=specs, sources=sources,
                           conflicts=[], invalid=[], reference={}, issues=issues)
        case = next(c for c in qa_cases(report.to_dict()) if c.get('field') == 'thread_count')
        self.assertIsNone(case['kept'])
        self.assertEqual(case['dropped'], 8)
        self.assertEqual(case.get('kept_field'), 'core_count')

    def test_inapplicable_fields_are_not_counted_as_unknown(self):
        report = CoverageReport()
        report.add_product(product_id='p', category='storage', specs={'type': 'SSD'}, sources={},
                           conflicts=[], invalid=[], reference={}, issues=[])
        self.assertFalse(any(x['field']=='rpm' for x in report.unknown))

    def test_memory_arithmetic_issue_keeps_numeric_answer(self):
        specs={'module_count':2,'module_size_gb':16,'total_gb':2}
        sources={key:'vendor' for key in specs}
        issue=next(x for x in cross_check('memory',specs,sources) if x['field']=='total_gb')
        self.assertEqual(issue['kept'],32)
        self.assertEqual(issue['dropped'],2)

    def test_explicit_external_usb_storage_gets_external_form_factor(self):
        specs={'interface':'USB Type-C','type':'SSD'}
        infer_specs('storage',specs,{},context={'text':'Samsung Portable SSD T7 external USB', 'title':'Samsung Portable SSD T7 external USB', 'detail_rows':0})
        self.assertEqual(specs.get('form_factor'),'External')

    def test_unknown_usb_context_does_not_invent_drive_shape(self):
        specs={'interface':'USB Type-C'}
        infer_specs('storage',specs,{},context={'text':'USB adapter compatible with drives', 'title':'USB adapter compatible with drives', 'detail_rows':0})
        self.assertIsNone(specs.get('form_factor'))

    def test_explicit_soldered_socket_is_not_a_missing_cpu_socket(self):
        from scraper.specs.canon import canon_socket
        self.assertEqual(canon_socket('On-board (soldered)'), 'On-board')
        from scraper.specs import schema
        from scraper.specs.validate import validate_fact
        self.assertIsNone(validate_fact('motherboard',schema.field_map('motherboard')['socket'],'On-board'))
        self.assertIsNotNone(validate_fact('cpu',schema.field_map('cpu')['socket'],'On-board'))
        report=CoverageReport()
        report.add_product(product_id='p',category='motherboard',specs={'socket':'On-board','chipset':'HM65'},
                           sources={'socket':'override'},conflicts=[],invalid=[],reference={},issues=[])
        self.assertFalse(any(x['field']=='socket' for x in report.core_gaps))

    def test_exact_manufacturer_order_code_supplies_tray_without_prefix_inference(self):
        from scraper.specs.witness import part_number_packaging
        self.assertEqual(part_number_packaging('PK8071305502300'), 'tray')
        self.assertIsNone(part_number_packaging('PK8072007045601'))
        self.assertIsNone(part_number_packaging('PK8071300000000'))

    def test_exact_674x_order_code_is_verified_tray(self):
        from scraper.specs.witness import part_number_packaging
        self.assertEqual(part_number_packaging('PK8072007045600'), 'tray')


if __name__ == '__main__':
    unittest.main()
