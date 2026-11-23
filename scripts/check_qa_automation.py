"""Offline QA automation proofs, including real normalization and matching."""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.specs.merge import Fact, TIER_MANUFACTURER, TIER_TITLE, merge_facts, same_value
from scraper.specs.report import CoverageReport, _wording_only, qa_cases
from scraper.specs.derive import infer_specs
from scraper.specs import build, schema
from scraper.specs import resolution
from scraper.specs.merge import TIER_OVERRIDE
from scraper.mfr import store
from scraper import normalize_and_match as normalize


class ComparisonTests(unittest.TestCase):
    def test_unknown_and_boolean_are_distinct(self):
        for a, b in ((False, None), (False, 0), (True, 1), (True, 'Yes'), (None, 'None')):
            self.assertFalse(same_value(a, b))

    def test_vectors_preserve_order_but_socket_sets_do_not(self):
        self.assertFalse(same_value([120, 160, 70], [160, 120, 70], field='dimensions_mm'))
        self.assertTrue(same_value(['AM5', 'LGA 1700'], ['LGA1700', 'AM5'], field='sockets'))
        self.assertFalse(same_value(['AM5'], ['AM5', 'AM5'], field='dimensions_mm'))

    def test_supported_feature_sets_keep_legitimate_representation_equivalence(self):
        for field, values in (
                ('memory_speeds', ['DDR5-5600', 'DDR5-6000']),
                ('m2_slots', ['1 x M.2 PCIe 4.0', '1 x M.2 PCIe 5.0']),
                ('mb_form_factors', ['ATX', 'Mini ITX']),
                ('front_usb', ['USB 3.0', 'USB Type-C']),
                ('connectors', ['4-pin PWM', '3-pin ARGB']),
                ('external_power', ['1 x 8-pin', '1 x 6-pin'])):
            self.assertTrue(same_value(values, list(reversed(values)), field=field), field)
        self.assertFalse(same_value(['1 x 8-pin'], ['2 x 8-pin'], field='external_power'))

    def test_meaningful_model_tokens_cannot_be_wording_noise(self):
        for a, b in (('RX 9070', 'RX 9070 XT'), ('NF-P12', 'NF-P12 redux'),
                     ('Core Ultra 5 245K', 'Core Ultra 5 245KF'),
                     ('Threadripper 7980X', 'Threadripper 7960X'),
                     ('P10 FLUX', 'P10 FLUX FT'), ('FT', 'FT ARGB'),
                     ('AP303 Glass', 'AP303 Metal'), ('Box', 'Tray')):
            self.assertFalse(_wording_only('model', a, b), (a, b))
        self.assertTrue(_wording_only('model', 'NH-U12S', 'NH U12S'))

    def test_numeric_units_not_rounding_tolerances(self):
        self.assertTrue(same_value('65W', '65 w'))
        self.assertFalse(same_value(158, 160, field='height_mm'))

    def test_gpu_title_cannot_displace_exact_manufacturer_memory(self):
        result = merge_facts('gpu', {'memory_gb': [
            Fact(16, TIER_MANUFACTURER, 'manufacturer:sheet'),
            Fact(12, TIER_TITLE, 'title:listing')]})
        self.assertEqual(result.specs['memory_gb'], 16)

    def test_more_digits_do_not_displace_qualified_model(self):
        result = merge_facts('cooler_air', {'model': [
            Fact('NH-U12S', TIER_MANUFACTURER, 'manufacturer:sheet'),
            Fact('NH-U12S 120 160', TIER_TITLE, 'title:listing')]})
        self.assertEqual(result.specs['model'], 'NH-U12S')

    def test_part_number_from_a_good_source_is_not_a_qualified_model_name(self):
        result = merge_facts('cpu', {'model': [
            Fact('100-1000001084WOF', TIER_MANUFACTURER, 'manufacturer:sheet'),
            Fact('Ryzen 7 9800X3D', TIER_TITLE, 'title:listing')]})
        self.assertEqual(result.specs['model'], 'Ryzen 7 9800X3D')

    def test_platform_memory_is_unknown_without_exact_model_source(self):
        for socket in ('LGA1851', 'LGA1151', 'AM4', 'AM5', 'LGA1700'):
            specs = {'manufacturer': 'Intel', 'model': 'Core Ultra 5 245K', 'socket': socket}
            infer_specs('cpu', specs, {})
            self.assertIsNone(specs.get('max_memory_gb'))
        specs = {'model': 'Core Ultra 5 245K', 'socket': 'LGA1851', 'max_memory_gb': 256}
        sources = {'max_memory_gb': 'manufacturer'}
        infer_specs('cpu', specs, sources)
        self.assertEqual((specs['max_memory_gb'], sources['max_memory_gb']), (256, 'manufacturer'))


class ManufacturerTests(unittest.TestCase):
    def test_ambiguous_name_and_same_page_variants_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            entries = {str(i): {'url': 'https://example.invalid/family', 'category': 'case_fan',
                               'keys': ['BL122'], 'names': ['lightwings'], 'specs': {'rpm_max': rpm}}
                       for i, rpm in enumerate((1600, 2100))}
            (path / 'brand.json').write_text(json.dumps({'brand': 'be quiet!',
                'schema_version': schema.SCHEMA_VERSION, 'entries': entries}), encoding='utf-8')
            index = store.load_index(path)
            self.assertNotIn(('be quiet!', 'k:BL122'), index)
            self.assertNotIn(('be quiet!', 'n:lightwings'), index)
            store.load_index.cache_clear()

    def test_multiple_distinct_exact_keys_never_become_last_entry_wins(self):
        index = {('brand', 'k:' + key): {'category': 'case_fan', 'url': url,
                 'keys': [key], 'specs': {'rpm_max': rpm}}
                 for key, url, rpm in [('AAA1', 'https://example.invalid/a', 1600),
                                      ('AAA2', 'https://example.invalid/b', 2100)]}
        for keys in (['AAA1', 'AAA2'], ['AAA2', 'AAA1']):
            self.assertEqual(store.facts_from(index, 'case_fan', 'brand', keys, '',
                tier=TIER_MANUFACTURER, source='manufacturer'), {})

    def test_reordered_duplicate_keys_are_not_ambiguous_variants(self):
        a = {'url': 'https://example.invalid/fan', 'category': 'case_fan',
             'keys': ['BL122', '4260052191606'], 'specs': {'rpm_max': 1600}}
        b = {**a, 'keys': list(reversed(a['keys']))}
        self.assertEqual(store._entry_key(a), store._entry_key(b))

    def test_nonfan_duplicate_cache_selection_is_unchanged_in_this_rollout(self):
        # Non-fan duplicate-cache rules require their own rollout. Do not
        # change Antec case answers as a side effect of fan QA automation.
        old = {'url': 'https://www.antec.com/product/case/df700-flux', 'fetched': '2026-10-17',
               'category': 'case', 'keys': ['0761345800709', 'df700flux'], 'names': ['df700 flux'],
               'specs': {'max_gpu_length_mm': 405}}
        new = {**old, 'url': old['url'] + '.php', 'fetched': '2026-10-20',
               'keys': old['keys'] + ['DF700FLUX'], 'specs': {'max_gpu_length_mm': 405, 'weight_kg': 7.4}}
        for entries in ((old, new), (new, old)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                (path / 'antec.json').write_text(json.dumps({'brand': 'Antec', 'schema_version': schema.SCHEMA_VERSION,
                    'entries': dict(enumerate(entries))}), encoding='utf-8')
                index = store.load_index(path)
                self.assertEqual(index[('antec', 'n:df700 flux')], entries[-1])
                self.assertNotIn(('antec', 'k:0761345800709'), index)
                store.load_index.cache_clear()

    def test_nonfan_multi_key_selection_is_annotation_only(self):
        a = {'category': 'case', 'url': 'https://example.invalid/a', 'keys': ['AAA1'],
             'specs': {'max_gpu_length_mm': 330}}
        b = {'category': 'case', 'url': 'https://example.invalid/b', 'keys': ['AAA2'],
             'specs': {'max_gpu_length_mm': 405}}
        facts = store.facts_from({('brand', 'k:AAA1'): a, ('brand', 'k:AAA2'): b},
            'case', 'brand', ['AAA1', 'AAA2', 'AAA1'], '', tier=TIER_MANUFACTURER, source='manufacturer')
        self.assertEqual(facts['max_gpu_length_mm'][0].value, 330)
        self.assertEqual((facts['max_gpu_length_mm'][0].evidence or {})['match_method'], 'ambiguous_legacy')


class PipelineTests(unittest.TestCase):
    def replay(self, *, rpm=1600, method='exact', override=None, uncertain=False, boxed=False, all_metrics=False):
        fixture = json.loads((ROOT / 'scripts/fixtures/qa_automation_2026_11_23.json').read_text(encoding='utf-8'))
        entry = fixture['manufacturer']['entry']
        if all_metrics:
            # Synthetic competing vendor cells around the pinned real sheet.
            fixture['listings'][0]['vendor_meta']['detail_specs'].update(
                {'ספיקת אוויר': '48.8 CFM', 'רעש': '28.5 dB', 'לחץ סטטי': '1.2 mmH2O'})
        if boxed:
            box = copy.deepcopy(fixture['listings'][1])
            box['vendor_sku'] = 'fixture-245K-Box'
            box['title_raw'] = 'Intel Core Ultra 5 245K / 1851 Box'
            fixture['listings'].append(box)
        entry['specs']['rpm_max'] = rpm
        index = {('be quiet!', 'k:BL122'): entry}
        if method == 'name':
            from scraper.mfr.common import strict_name
            index = {('be quiet!', 'n:' + strict_name(fixture['listings'][0]['title_raw'], 'be quiet!')): entry}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.dict(resolution.RULE_MODES, {'manufacturer_fan_performance': 'enabled'}))
            path = Path(directory)
            manual = path / 'manual.json'
            manual.write_text('{"products": [], "blocked_pairs": []}', encoding='utf-8')
            stack.enter_context(patch.object(normalize, 'MANUAL_PATH', manual))
            stack.enter_context(patch.object(normalize, 'OUTPUT_PATH', path / 'catalog.json'))
            stack.enter_context(patch.object(normalize, 'VENDOR_SPIDER_NAMES', ['tms']))
            stack.enter_context(patch.object(normalize, 'find_latest_snapshot', return_value=(path / 'tms_test.jsonl', '2026-11-23')))
            stack.enter_context(patch.object(normalize, 'load_listings', return_value=copy.deepcopy(fixture['listings'])))
            stack.enter_context(patch.object(normalize, '_attach_eilat', return_value=([], {})))
            stack.enter_context(patch.object(normalize, '_merge_detail_specs', side_effect=lambda rows: rows))
            stack.enter_context(patch.object(build.reference, 'match_reference_row', return_value=None))
            stack.enter_context(patch.object(build.reference, 'overrides_for', return_value=override or {}))
            stack.enter_context(patch.object(store, '_index', return_value=index))
            if method == 'name':
                stack.enter_context(patch.object(store, 'facts_for', side_effect=lambda category, brand, numbers, name:
                    store.facts_from(index, category, brand, numbers, fixture['listings'][0]['title_raw'],
                                     tier=TIER_MANUFACTURER, source='manufacturer')))
            for extra in (build.icecat_store, build.extract_store, build.xref_store):
                stack.enter_context(patch.object(extra, 'facts_for', return_value={}))
            stack.enter_context(patch.object(normalize, 'suggest_fuzzy_matches', return_value=[]))
            if uncertain:
                stack.enter_context(patch.object(build, '_identity_uncertain', return_value=True))
            with redirect_stdout(io.StringIO()):
                catalog, _, report = normalize.build_catalog(datetime(2026, 11, 23, 12, tzinfo=timezone.utc))
            self.assertEqual(len(catalog['products']), 4 if boxed else 3)
            for product in catalog['products']:
                if product['category'] == 'cpu':
                    self.assertIsNone(product['specs']['max_memory_gb'])
            if boxed:
                packages = {p['specs']['packaging'] for p in catalog['products']
                            if p.get('specs', {}).get('model') == 'Core Ultra 5 245K'}
                self.assertEqual(packages, {'boxed', 'tray'})
            for raw, current in zip(sorted(fixture['listings'], key=lambda x: x['vendor_sku']),
                                    sorted(catalog['listings'], key=lambda x: x['vendor_sku'])):
                for field in ('vendor_sku', 'price_ils', 'in_stock', 'url', 'title_raw', 'scraped_at'):
                    self.assertEqual(current[field], raw[field])
            fan = next(p for p in catalog['products'] if p['category'] == 'case_fan')
            case = next(c for c in qa_cases(report, limit=None) if c.get('field') == 'rpm_max')
            return fan, case, report

    def test_native_exact_manufacturer_answer_resolves_without_manual_entries(self):
        fan, case, _ = self.replay()
        self.assertEqual(fan['specs']['rpm_max'], 1600)
        self.assertEqual({key: case['resolution'][key] for key in ('state', 'reason', 'rule')},
                         {'state': 'auto_resolved', 'reason': 'exact_manufacturer_spec',
                          'rule': 'manufacturer_fan_performance'})
        self.assertRegex(case['resolution']['evidence_ref'], r'^[0-9a-f]{64}$')

    def test_name_fallback_cannot_authorize_automatic_resolution(self):
        _, case, _ = self.replay(method='name')
        self.assertFalse(case.get('auto_resolved'))

    def test_identity_uncertainty_prevents_automatic_resolution(self):
        _, case, _ = self.replay(uncertain=True)
        self.assertFalse(case.get('auto_resolved'))

    def test_changed_evidence_reopens_the_case(self):
        _, case, _ = self.replay(rpm=2100)
        # Stronger conflicting source must reopen even an otherwise qualified sheet.
        report = CoverageReport()
        report.add_product(product_id='p', category='case_fan', specs={'rpm_max': 2100},
            sources={'rpm_max': 'manufacturer'}, invalid=[], issues=[], reference={}, conflicts=[
                {'field': 'rpm_max', 'kept': {'value': 2100, 'tier': 'manufacturer'},
                 'dropped': {'value': 1600, 'tier': 'reference'}}])
        self.assertFalse(qa_cases(report.to_dict())[0].get('auto_resolved'))

    def test_human_override_remains_authoritative(self):
        fan, case, _ = self.replay(override={'rpm_max': [Fact(1650, TIER_OVERRIDE, 'override:cited') ]})
        self.assertEqual(fan['specs']['rpm_max'], 1650)
        self.assertTrue(case.get('fixed'))
        self.assertFalse(case.get('auto_resolved'))

    def test_box_tray_and_full_suffix_remain_separate_in_the_real_pipeline(self):
        self.replay(boxed=True)

    def test_every_enabled_fan_metric_has_a_native_pipeline_proof(self):
        fan, _, report = self.replay(all_metrics=True)
        cases = {c['field']: c for c in qa_cases(report, limit=None) if c.get('field') in resolution.FAN_FIELDS}
        self.assertEqual(set(cases), set(resolution.FAN_FIELDS))
        for field, value in {'rpm_max': 1600, 'airflow_cfm': 51.5, 'noise_db': 25.5,
                             'static_pressure_mmh2o': 1.34}.items():
            self.assertEqual(fan['specs'][field], value)
            self.assertTrue(cases[field].get('auto_resolved'), field)


class ResolutionTests(unittest.TestCase):
    def conflict(self):
        fixture = json.loads((ROOT / 'scripts/fixtures/qa_automation_2026_11_23.json').read_text(encoding='utf-8'))
        entry = fixture['manufacturer']['entry']
        facts = store.facts_from({('be quiet!', 'k:BL122'): entry}, 'case_fan', 'be quiet!', ['BL122'], '',
                                 tier=TIER_MANUFACTURER, source='manufacturer')
        facts['rpm_max'].append(Fact(1700, 1, 'vendor:tms'))
        return merge_facts('case_fan', facts).conflicts_as_dicts()[0]

    def cases(self, conflicts=None, *, actual: int | None = 1600, issues=None, invalid=None, mode='enabled'):
        report = CoverageReport()
        with patch.dict(resolution.RULE_MODES, {'manufacturer_fan_performance': mode}):
            report.add_product(product_id='p', category='case_fan', specs={'rpm_max': actual},
                sources={'rpm_max': 'manufacturer'}, conflicts=conflicts or [self.conflict()],
                invalid=invalid or [], issues=issues or [], reference={})
        return qa_cases(report.to_dict(), limit=None)

    def test_off_shadow_enabled_are_distinct(self):
        self.assertNotIn('resolution', self.cases(mode='off')[0])
        self.assertEqual(self.cases(mode='shadow')[0]['resolution']['state'], 'shadow')
        self.assertFalse(self.cases(mode='shadow')[0].get('auto_resolved'))
        self.assertTrue(self.cases()[0]['auto_resolved'])

    def test_any_equally_qualified_contradiction_blocks_every_claim_for_the_field(self):
        for rank in (-1, 0, 0.5, None, float('nan')):
            competing = copy.deepcopy(self.conflict())
            competing['dropped'].update(value=1800, rank=rank)
            cases = self.cases([self.conflict(), competing])
            self.assertTrue(all(not c.get('auto_resolved') for c in cases))

    def test_missing_or_different_proof_does_not_resolve(self):
        for key, value in (('match_method', 'name'), ('complete', None), ('meaning', 'pump_rpm'),
                           ('unit', 'GHz'), ('origin', None), ('source_url', None),
                           ('fingerprint', None), ('matched_key', 'OTHER')):
            conflict = self.conflict()
            conflict['kept']['evidence'][key] = value
            self.assertFalse(self.cases([conflict])[0].get('auto_resolved'), key)

    def test_malformed_legacy_proof_stays_open_instead_of_crashing(self):
        for proof in (None, [], 'proof', 42):
            conflict = self.conflict()
            conflict['kept']['evidence'] = proof
            self.assertFalse(self.cases([conflict])[0].get('auto_resolved'))
        conflict = self.conflict()
        conflict['kept']['evidence']['sku_keys'] = 'BL122'
        self.assertFalse(self.cases([conflict])[0].get('auto_resolved'))
        conflict = self.conflict()
        conflict['kept']['evidence']['fingerprint'] = int('1' * 64)
        self.assertFalse(self.cases([conflict])[0].get('auto_resolved'))

    def test_unknown_changed_and_invalid_final_answers_reopen_even_with_old_flags(self):
        conflict = self.conflict()
        conflict.update(auto_resolved=True, resolution={'state': 'auto_resolved'})
        for actual in (None, 1580, 1700):
            self.assertFalse(self.cases([conflict], actual=actual)[0].get('auto_resolved'))
        self.assertFalse(self.cases(issues=[{'field': 'rpm_max'}])[0].get('auto_resolved'))
        self.assertFalse(self.cases(invalid=[{'field': 'rpm_max'}])[0].get('auto_resolved'))

    def test_resolved_history_does_not_consume_either_cap(self):
        conflict = self.conflict()
        with patch.dict(resolution.RULE_MODES, {'manufacturer_fan_performance': 'enabled'}):
            report = CoverageReport()
            report.add_product(product_id='a', category='case_fan', specs={'rpm_max': 1600},
                sources={'rpm_max': 'manufacturer'}, conflicts=[conflict], invalid=[], issues=[], reference={})
            report.add_product(product_id='z', category='case_fan', specs={'rpm_max': 1700},
                sources={'rpm_max': 'vendor'}, conflicts=[conflict], invalid=[], issues=[], reference={})
        cases = qa_cases(report.to_dict(), limit=1, per_category=1)
        self.assertEqual([c['product_id'] for c in cases], ['a', 'z'])

    def test_final_identity_flags_reopen_resolution(self):
        report = {'conflicts': [{'product_id': 'p', 'auto_resolved': True,
                                'resolution': {'state': 'auto_resolved'}}]}
        resolution.reopen_uncertain(report, [{'product_id': 'p', 'kind': 'variant_conflict'}])
        self.assertNotIn('auto_resolved', report['conflicts'][0])

    def test_cross_product_twin_flag_reopens_every_implicated_product(self):
        from scraper.matching import find_cross_product_twin_cases
        products = [
            {'product_id': 'a', 'category': 'case_fan', 'offers': [
                {'vendor_id': 'tms', 'listing_key': 'tms:BL122', 'vendor_sku': 'BL122',
                 'mpn': 'BL122', 'title_raw': 'be quiet! Light Wings LX', 'price_ils': 195}]},
            {'product_id': 'b', 'category': 'case_fan', 'offers': [
                {'vendor_id': 'tms', 'listing_key': 'tms:BL122-PC', 'vendor_sku': 'BL122-PC',
                 'mpn': 'BL122-PC', 'title_raw': 'be quiet! Light Wings LX', 'price_ils': 185}]},
        ]
        identity_cases = find_cross_product_twin_cases(products)
        self.assertEqual(identity_cases[0]['product_ids'], ['a', 'b'])
        report = {'conflicts': [{'product_id': pid, 'auto_resolved': True,
                                 'resolution': {'state': 'auto_resolved'}}
                                for pid in ('a', 'b', 'unrelated')]}
        resolution.reopen_uncertain(report, identity_cases)
        self.assertTrue(all('auto_resolved' not in case and 'resolution' not in case
                            for case in report['conflicts'][:2]))
        self.assertTrue(report['conflicts'][2]['auto_resolved'])

    def test_contradictory_memory_kit_does_not_turn_into_an_automatic_answer(self):
        from scraper.specs.resolvers.vendor_struct import parse_detail_specs
        facts = parse_detail_specs('memory', {'נפח': '96GB (2×24GB)'})
        for field in ('total_gb', 'module_count', 'module_size_gb'):
            self.assertNotIn(field, facts)

    def test_workbench_does_not_call_an_unapplied_current_pid_override_fixed(self):
        from scraper import qa_tool
        data = {
            qa_tool.CATALOG: {'products': [{'product_id': 'p', 'specs': {'rpm_max': 1700},
                                            'spec_sources': {'rpm_max': 'vendor'}}]},
            qa_tool.QA: {'cases': [{'kind': 'spec_conflict', 'product_id': 'p', 'field': 'rpm_max',
                                    'kept': 1700, 'dropped': 1600}]},
            qa_tool.OVERRIDES: {'products': {'p': {'rpm_max': 1600}}}}
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: data.get(path, default)):
            self.assertEqual(qa_tool.build_cases()[0]['state'], 'open')

    def test_workbench_keeps_auto_and_human_dismissal_distinct(self):
        from scraper import qa_tool
        case = {'kind': 'spec_conflict', 'product_id': 'p', 'field': 'rpm_max',
                'kept': 1600, 'dropped': 1700, 'auto_resolved': True,
                'resolution': {'state': 'auto_resolved', 'reason': 'exact_manufacturer_spec'}}
        data = {qa_tool.CATALOG: {'products': [{'product_id': 'p'}]}, qa_tool.QA: {'cases': [case]}}
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: data.get(path, default)):
            self.assertEqual(qa_tool.build_cases()[0]['state'], 'auto_resolved')
        data[qa_tool.DISMISSED] = {'spec_conflict|p|rpm_max': True}
        with patch.object(qa_tool, '_read', side_effect=lambda path, default: data.get(path, default)):
            self.assertEqual(qa_tool.build_cases()[0]['state'], 'dismissed')


if __name__ == '__main__':
    unittest.main()
