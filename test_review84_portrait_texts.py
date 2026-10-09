"""Offline portrait-template preservation; never submit to API or GPU."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import schema_adapters as runtime
from anime_batch_protocol import FORMAT_NODE, STATE_KEY, VALID_NODE, batch_pattern
from scripts.review84_portrait_controls import (CONTRACTS, USER_LABEL,
    reviewed_portrait_controls, restore_portrait_templates)


ROOT = Path(__file__).resolve().parent


class PortraitTextContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def fixture(self, wid, *, legacy=True):
        contract = CONTRACTS[wid]
        spec = copy.deepcopy(runtime.manifest(wid))
        user = next(field for field in spec['texts'] if field['id'] == contract['user'] + ':prompt')
        spec['texts'] = [user]
        if legacy:
            spec['texts'] = [dict(id=nid + ':text', key='text', role='prompt',
                label='创作描述', targets=[{'node': nid, 'input': 'text'}], default='', preserveWhenEmpty=False)
                for nid in contract['internal']] + spec['texts']
        graph = json.loads((ROOT / 'workflows/api' / spec['template']).read_text('utf-8'))
        for index, nid in enumerate(contract['internal']):
            # Deliberately anonymous fixtures, never owner's private instructions.
            graph[nid]['inputs']['text'] = ('Neutral role template.',
                'Produce [条数] neutral studio descriptions.', 'Separate entries with |.')[index]
        path = Path(self.temp.name) / spec['template']
        path.write_text(json.dumps(graph, ensure_ascii=False), 'utf-8')
        records = {slot['id']: {'kind': slot['kind'], 'remote': 'offline-reference.png'} for slot in spec['media']}
        return spec, graph, path, records

    def test_legacy_and_current_submissions_cannot_override_internal_roles(self):
        for wid in CONTRACTS:
            for legacy in (True, False):
                with self.subTest(wid=wid, legacy=legacy):
                    spec, template, path, records = self.fixture(wid, legacy=legacy)
                    c = CONTRACTS[wid]
                    supplied = {nid + ':text': 'Attempted template replacement.' for nid in c['internal']}
                    supplied[c['user'] + ':prompt'] = 'Use a soft gray background.'
                    before = copy.deepcopy(spec)
                    with patch.object(runtime, 'template_path', return_value=path):
                        graph, values, texts = runtime.build(spec, {c['count'] + ':value': 5},
                            supplied, records, {}, 'offline-new')
                    self.assertEqual(spec, before)
                    self.assertEqual(set(texts), {c['user'] + ':prompt'})
                    self.assertEqual(graph[c['user']]['inputs']['prompt'], 'Use a soft gray background.')
                    for nid in c['internal']:
                        self.assertEqual(graph[nid], template[nid])
                    self.assertEqual(values[c['count'] + ':value'], 5)
                    self.assertEqual(graph[c['integer']]['inputs']['int_'], 5)
                    self.assertEqual(graph[c['split']]['inputs']['max_count'], 5)
                    if wid == 'local-card-80':
                        self.assertEqual(graph[c['user']]['_meta'][STATE_KEY]['count'], 5)
                        self.assertEqual(graph[VALID_NODE]['inputs']['regex_pattern'], batch_pattern(5))
                        self.assertIn('恰好 5 条', graph[FORMAT_NODE]['inputs']['text'])

    def test_prompt_fallback_moves_to_the_real_user_field(self):
        for wid, c in CONTRACTS.items():
            spec, _, _, _ = self.fixture(wid)
            self.assertEqual(runtime.validate_texts(spec, {}, 'A neutral creative request.'),
                {c['user'] + ':prompt': 'A neutral creative request.'})

    def test_saved_legacy_rerun_restores_only_protocol_texts(self):
        for wid, c in CONTRACTS.items():
            with self.subTest(wid=wid):
                spec, template, path, records = self.fixture(wid)
                with patch.object(runtime, 'template_path', return_value=path):
                    graph, values, texts = runtime.build(spec, {c['count'] + ':value': 2},
                        {c['user'] + ':prompt': 'Preserve this user goal.'}, records, {}, 'offline-old')
                    for index, nid in enumerate(c['internal']):
                        graph[nid]['inputs']['text'] = '' if index != 1 else 'Old accidental user override.'
                    original = dict(schema_spec=spec, graph=graph, catalog_values=values, catalog_texts=texts)
                    before = copy.deepcopy(original)
                    rerun, actual_values = runtime.rerun(original, records, 'offline-rerun', randomize_seed=False)
                self.assertEqual(original, before)
                self.assertEqual(actual_values, values)
                self.assertEqual(rerun[c['user']]['inputs']['prompt'], 'Preserve this user goal.')
                for nid in c['internal']:
                    self.assertEqual(rerun[nid], template[nid])
                for nid, node in graph.items():
                    if nid in c['internal'] or nid == c['save']:
                        continue
                    self.assertEqual(rerun[nid], node, nid)

    def test_source_binding_consumer_and_alias_drift_fail_atomically(self):
        for wid, c in CONTRACTS.items():
            spec, template, _, _ = self.fixture(wid)
            for mutation in ('source', 'output', 'binding', 'alias', 'control-alias',
                             'join', 'replace', 'consumer', 'encoder', 'output-path', 'count-mismatch'):
                with self.subTest(wid=wid, mutation=mutation):
                    contract, graph = copy.deepcopy(spec), copy.deepcopy(template)
                    if mutation == 'source':
                        contract['source_hash'] = 'unknown'
                    elif mutation == 'output':
                        contract['outputs'] = ['unreviewed-output']
                    elif mutation == 'binding':
                        contract['texts'][0]['targets'] = [{'node': c['user'], 'input': 'prompt'}]
                    elif mutation == 'alias':
                        contract['texts'].append(dict(id='user-alias', targets=[{'node': c['internal'][0], 'input': 'text'}]))
                    elif mutation == 'control-alias':
                        contract['controls'].append(dict(id='numeric-alias', targets=[{'node': c['internal'][0], 'input': 'text'}]))
                    elif mutation == 'join':
                        graph[c['join']]['inputs']['string_1'] = [c['internal'][1], 0]
                    elif mutation == 'replace':
                        graph[c['replace']]['inputs']['find1'] = 'unreviewed-marker'
                    elif mutation == 'consumer':
                        graph[c['user']]['inputs']['role'] = 'unreviewed-role'
                    elif mutation == 'encoder':
                        graph[c['encoder']]['inputs']['prompt'] = [c['user'], 0]
                    elif mutation == 'output-path':
                        graph[c['save']]['inputs']['images'] = [c['encoder'], 0]
                    elif mutation == 'count-mismatch':
                        graph[c['integer']]['inputs']['int_'] = 2
                    before = copy.deepcopy(graph)
                    with self.assertRaises(ValueError):
                        restore_portrait_templates(contract, graph, template)
                    self.assertEqual(graph, before)

    def test_missing_template_and_unrelated_unknown_text_are_not_silently_accepted(self):
        for wid, c in CONTRACTS.items():
            spec, graph, _, _ = self.fixture(wid)
            missing = copy.deepcopy(graph)
            missing[c['internal'][0]]['inputs']['text'] = ''
            before = copy.deepcopy(graph)
            with self.assertRaisesRegex(ValueError, '模板缺失'):
                restore_portrait_templates(spec, graph, missing)
            self.assertEqual(graph, before)
            with self.assertRaisesRegex(ValueError, '不属于'):
                runtime.validate_texts(spec, {'unreviewed:text': 'Unknown.'})

    def test_fresh_and_curated_annotations_hide_templates_without_changing_bindings(self):
        for wid, c in CONTRACTS.items():
            spec, graph, _, _ = self.fixture(wid)
            workflow = {'id': wid}
            before = copy.deepcopy(spec)
            controls, texts = reviewed_portrait_controls(workflow, spec['controls'], spec['texts'],
                graph=graph, source_hash=c['source_hash'])
            self.assertEqual(spec, before)
            self.assertEqual([f['id'] for f in texts], [c['user'] + ':prompt'])
            self.assertEqual(texts[0]['label'], USER_LABEL)
            count = next(f for f in controls if f['id'] == c['count'] + ':value')
            original = next(f for f in spec['controls'] if f['id'] == count['id'])
            self.assertEqual(count['value'], original['value'])
            self.assertEqual(count['targets'], original['targets'])
            self.assertEqual((count['min'], count['max'], count['step'], count['integer']), (1, 1000, 1, True))
            second = reviewed_portrait_controls(workflow, controls, texts,
                source_hash=c['source_hash'], derived={'sourceHash': c['source_hash']})
            self.assertEqual(second, (controls, texts))
            with self.assertRaises(ValueError):
                reviewed_portrait_controls(workflow, controls, texts, source_hash='drift', derived={})

    def test_other_workflows_are_unchanged(self):
        spec = {'id': 'unrelated'}
        supplied = {'prompt': 'Unrelated.'}
        self.assertEqual(runtime.validate_texts({'id': 'unrelated', 'texts': []}, {}), {})
        graph = {'unrelated': {'inputs': {'text': 'Preserved.'}}}
        self.assertIs(restore_portrait_templates(spec, graph, {}), graph)


if __name__ == '__main__':
    unittest.main()
