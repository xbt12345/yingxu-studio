"""Pure H3 binding tests: no providers, uploads, accounts or GPU execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_workflow_interfaces import Graph
from scripts.review86_h3_controls import (HASHES, MODES, REFERENCES, HIDDEN,
                                         reviewed_h3_config, bind_reviewed_h3_assets)
import schema_adapters as runtime


def read(path):
    return json.loads(path.read_text('utf-8-sig'))


class H3ReferenceControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = read(ROOT / 'public/workflow-interfaces.json')['workflows']
        cls.sources = {r['id']: Path(r['source']) for r in read(ROOT / 'verification/catalog-audit.json') if 'id' in r}

    def config(self, wid):
        raw = self.sources[wid].read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), HASHES[wid])
        return reviewed_h3_config({'id': wid}, self.ui[wid], graph=Graph(json.loads(raw.decode('utf-8-sig'))))

    def spec(self, wid):
        original = runtime.manifest(wid)
        result = copy.deepcopy(original)
        cfg = self.config(wid)
        supported = {f['id']: f for f in result['controls']}
        for f in cfg['controls']:
            if f['kind'] == 'mode':
                if f['id'] in supported:
                    supported[f['id']].update(copy.deepcopy(f))
                else:
                    result['controls'].append(copy.deepcopy(f))
            elif f.get('hidden'):
                supported[f['id']]['hidden'] = True
        for i, f in enumerate(result['media']):
            reviewed = cfg['media'][i]
            for key in ('required', 'optional', 'label'):
                if key in reviewed:
                    f[key] = reviewed[key]
        result['referencePolicy'] = copy.deepcopy(cfg.get('referencePolicy', {}))
        self.assertEqual(runtime.manifest(wid), original)
        return result

    def build(self, spec, records, values=None):
        existing = runtime.bind_assets
        def hook(graph, schema, owned):
            return graph if bind_reviewed_h3_assets(graph, schema, owned) else existing(graph, schema, owned)
        with patch.object(runtime, 'bind_assets', side_effect=hook):
            return runtime.build(spec, values or {}, {}, records, {}, 'offline-h3-review', prompt='A neutral, simple scene.')[0]

    def records(self, spec, count):
        return {f['id']: {'kind': f['kind'], 'remote': 'owned-' + str(i) + '.' + {'image': 'png', 'audio': 'wav', 'video': 'mp4'}[f['kind']]}
                for i, f in enumerate(spec['media'][:count])}

    def test_forms_preserve_source_defaults_and_have_exact_caps(self):
        for wid in HASHES:
            with self.subTest(wid=wid):
                before = copy.deepcopy(self.ui[wid]); cfg = self.config(wid)
                self.assertEqual(self.ui[wid], before)
                self.assertEqual(reviewed_h3_config({'id': wid}, cfg), cfg)
                previous = {f['id']: f for f in before['controls']}
                for f in cfg['controls']:
                    if f['id'] in previous:
                        self.assertEqual(f['value'], previous[f['id']]['value'])
                        self.assertEqual(f['targets'], previous[f['id']]['targets'])
                if wid in REFERENCES:
                    policy = cfg['referencePolicy']
                    self.assertEqual((policy['presentation'], policy['minImages'], policy['maxImages']), ('progressive', 1, REFERENCES[wid][1]))
                    self.assertEqual([f['required'] for f in cfg['media']], [True] + [False] * (len(cfg['media']) - 1))

    def test_one_two_three_and_nine_references_bind_owned_images_only(self):
        for wid in ('local-card-4', 'local-card-52'):
            spec = self.spec(wid); before = copy.deepcopy(spec)
            original_path = runtime.template_path(spec); original_bytes = original_path.read_bytes()
            for count in (1, 2, 3, 9):
                with self.subTest(wid=wid, count=count):
                    records = self.records(spec, count); graph = self.build(spec, records)
                    model = graph['144']['inputs']
                    keys = [key for key in model if key.startswith('ref_images.')]
                    self.assertEqual(keys, ['ref_images.ref_image_' + str(i) for i in range(count)])
                    expected = [model[key] for key in keys]
                    self.assertEqual(list(graph['160']['inputs'].values()), expected)
                    self.assertEqual(list(graph['160']['inputs']), ['image' + str(i + 1) for i in range(count)])
                    actual = [v['inputs']['image'] for v in graph.values() if v['class_type'] == 'LoadImage']
                    self.assertEqual(set(actual), {r['remote'] for r in records.values()})
                    self.assertEqual(len(actual), count)
            self.assertEqual(spec, before)
            self.assertEqual(original_path.read_bytes(), original_bytes)

    def test_empty_and_over_cap_references_are_rejected(self):
        for wid in REFERENCES:
            spec = self.spec(wid)
            with self.subTest(wid=wid), self.assertRaises(ValueError):
                self.build(spec, {})
            records = self.records(spec, len(spec['media']))
            records['not-a-real-port'] = {'kind': 'image', 'remote': 'owned-excess.png'}
            with self.subTest(wid=wid), self.assertRaises(ValueError):
                self.build(spec, records)

    def test_removed_middle_slot_is_contiguous_and_prompt_batch_matches(self):
        spec = self.spec('local-card-52')
        records = {'65': {'kind': 'image', 'remote': 'owned-first.png'},
                   '70': {'kind': 'image', 'remote': 'owned-third.png'},
                   '144:ref_image_7': {'kind': 'image', 'remote': 'owned-eighth.png'}}
        graph = self.build(spec, records)
        links = [graph['144']['inputs']['ref_images.ref_image_' + str(i)] for i in range(3)]
        self.assertEqual(links[:2], [['80:74', 0], ['94:91', 0]])
        self.assertEqual(list(graph['160']['inputs'].values()), links)
        self.assertNotIn('66', graph)
        self.assertNotIn('ref_images.ref_image_7', graph['144']['inputs'])
        direct = graph[links[2][0]]
        self.assertEqual(direct['inputs']['image'], 'owned-eighth.png')

    def test_rerun_retains_reference_order_and_sparse_catalog_slot_identity(self):
        spec = self.spec('local-card-52')
        records = {'65': {'kind': 'image', 'remote': 'owned-first.png'},
                   '144:ref_image_5': {'kind': 'image', 'remote': 'owned-sixth.png'}}
        graph = self.build(spec, records)
        values = runtime.validate_values(spec, {})
        original = {'schema_spec': spec, 'graph': graph, 'catalog_values': values}
        existing = runtime.bind_assets
        def hook(g, s, r):
            return g if bind_reviewed_h3_assets(g, s, r) else existing(g, s, r)
        with patch.object(runtime, 'bind_assets', side_effect=hook):
            replay, replay_values = runtime.rerun(original, records, 'offline-h3-replay', randomize_seed=False)
        self.assertEqual(list(replay['160']['inputs'].values()), list(graph['160']['inputs'].values()))
        self.assertEqual(replay_values, values)
        self.assertEqual(set(records), {'65', '144:ref_image_5'})

    def test_two_and_three_port_workflows_do_not_gain_guessed_extra_slots(self):
        for wid in ('local-card-53', 'local-card-62'):
            spec = self.spec(wid); cap = REFERENCES[wid][1]; consumer = REFERENCES[wid][0]
            for count in (1, cap):
                with self.subTest(wid=wid, count=count):
                    graph = self.build(spec, self.records(spec, count))
                    keys = [key for key in graph[consumer]['inputs'] if key.startswith('ref_images.')]
                    self.assertEqual(keys, ['ref_images.ref_image_' + str(i) for i in range(count)])

    def test_authored_mode_couples_real_lora_and_steps_with_default_preserved(self):
        for wid, route in MODES.items():
            spec = self.spec(wid); boolean, ms, ss, eight, four, l8, l4, sampler = route
            records = self.records(spec, len(spec['media']))
            mode = next(f for f in spec['controls'] if f['id'] == boolean + ':value')
            self.assertEqual([o['value'] for o in mode['options']], [False, True])
            for choice, selected_steps, selected_lora in ((False, eight, l8), (True, four, l4)):
                with self.subTest(wid=wid, choice=choice):
                    graph = self.build(spec, records, {boolean + ':value': choice})
                    self.assertIs(graph[boolean]['inputs']['value'], choice)
                    self.assertEqual(graph[ss]['inputs']['on_true' if choice else 'on_false'], [selected_steps, 0])
                    self.assertEqual(graph[selected_steps]['inputs']['value'], 4 if choice else 8)
                    self.assertEqual(graph[ms]['inputs']['on_true' if choice else 'on_false'], [selected_lora, 0])
                    self.assertIn('turbo_' + str(4 if choice else 8) + 'step', graph[selected_lora]['inputs']['lora_name'])
                    self.assertEqual(graph[sampler]['inputs']['steps'], [ss, 0])

    def test_hidden_longest_edges_keep_defaults_and_old_draft_values(self):
        for wid, fid in HIDDEN.items():
            spec = self.spec(wid); field = next(f for f in spec['controls'] if f['id'] == fid)
            records = self.records(spec, len(spec['media']))
            target = field['targets'][0]
            self.assertTrue(field['hidden'])
            default = self.build(spec, records)
            self.assertEqual(default[target['node']]['inputs'][target['input']], field['value'])
            old_value = 1536
            restored = self.build(spec, records, {fid: old_value})
            self.assertEqual(restored[target['node']]['inputs'][target['input']], old_value)

    def test_source_hash_and_binding_drift_reject_without_weakening_other_graphs(self):
        cfg = copy.deepcopy(self.ui['local-card-52']); cfg['sourceHash'] = 'drift'
        with self.assertRaises(ValueError):
            reviewed_h3_config({'id': 'local-card-52'}, cfg)
        spec = self.spec('local-card-52'); spec['source_hash'] = 'drift'
        with self.assertRaises(ValueError):
            self.build(spec, self.records(spec, 1))
        graph = {'sentinel': {'class_type': 'Unknown', 'inputs': {'value': 7}}}
        before = copy.deepcopy(graph)
        self.assertFalse(bind_reviewed_h3_assets(graph, {'id': 'local-card-37'}, {}))
        self.assertEqual(graph, before)


if __name__ == '__main__':
    unittest.main()
