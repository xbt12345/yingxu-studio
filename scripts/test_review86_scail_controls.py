"""CPU contract tests through production graph binding; no GPU submissions."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from build_workflow_interfaces import Graph
from compile_card_workflows import Compiler
from review86_scail_controls import (CONTRACTS, apply_scail_output_size,
    finalize_scail_schema, reviewed_scail_controls, scail_dimension_values)
import schema_adapters as runtime


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


class ScailControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {row['id']: Path(row['source']) for row in read(ROOT/'verification/catalog-audit.json') if 'id' in row}
        cls.ui = read(ROOT/'public/workflow-interfaces.json')['workflows']
        cls.node_info = read(ROOT/'private/research/card-20261004/object_info.json')

    def source(self, wid):
        raw = self.sources[wid].read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CONTRACTS[wid]['hash'])
        return json.loads(raw.decode('utf-8-sig'))

    def controls(self, wid):
        return reviewed_scail_controls({'id': wid}, self.ui[wid]['controls'],
            graph=Graph(self.source(wid)), source_hash=CONTRACTS[wid]['hash'])

    def spec(self, wid):
        source = runtime.manifest(wid)
        self.assertIsNotNone(source)
        # Production contract binding is tested; external providers/assets are
        # deliberately removed so these are pure graph builds, not live runs.
        spec = copy.deepcopy(source)
        spec.update(texts=[], media=[], apiProfiles=[])
        return finalize_scail_schema(spec)

    def build(self, wid, supplied=None):
        spec = self.spec(wid)
        values = {field['id']: 314159 for field in spec['controls'] if field.get('kind') == 'seed'}
        values.update(supplied or {})
        return runtime.build(spec, values, {}, {}, {}, 'scail-offline-contract')

    def test_source_proof_compiler_and_runtime_mode_both_use_same_boolean(self):
        wid = 'local-card-23'; c = CONTRACTS[wid]
        fields = self.controls(wid)
        mode = next(f for f in fields if f['id'] == '575:value')
        self.assertIs(mode['value'], False)
        self.assertEqual([option['value'] for option in mode['options']], [False, True])
        compiler = Compiler(self.source(wid), self.node_info)
        compiler.outputs('video')
        self.assertEqual(compiler.targets('575', 'value'), mode['targets'])
        self.assertEqual(mode['controlledTargets'],
            [{'node': nid, 'input': 'replacement_mode'} for nid in c['mode_targets']])
        for choice in (False, True):
            with self.subTest(choice=choice):
                graph, values, _ = self.build(wid, {'575:value': choice})
                self.assertIs(graph['575']['inputs']['value'], choice)
                self.assertIs(values['575:value'], choice)
                for nid in c['mode_targets']:
                    self.assertEqual(graph[nid]['inputs']['replacement_mode'], ['575', 0])
                self.assertTrue(graph[c['embeds']]['inputs']['preserve_main_ref_background'])
        for invalid in ('true', 1, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.build(wid, {'575:value': invalid})

    def test_card22_does_not_gain_a_guessed_mode_or_change_authored_flags(self):
        controls = self.controls('local-card-22')
        self.assertFalse(any(f.get('kind') == 'mode' for f in controls))
        graph, _, _ = self.build('local-card-22')
        self.assertIs(graph['197']['inputs']['replacement_mode'], True)
        self.assertIs(graph['347']['inputs']['replacement_mode'], False)
        self.assertIs(graph['347']['inputs']['preserve_main_ref_background'], False)

    def test_zero_pair_and_old_drafts_keep_dynamic_geometry_and_historical_long_edge(self):
        for wid, c in CONTRACTS.items():
            original = read(runtime.template_path(self.spec(wid)))
            for length in (None, 768, 1536):
                supplied = {} if length is None else {c['length']+':value': length}
                with self.subTest(wid=wid, history_long_edge=length):
                    graph, values, _ = self.build(wid, supplied)
                    self.assertEqual(values[c['embeds']+':width'], 0)
                    self.assertEqual(values[c['embeds']+':height'], 0)
                    self.assertEqual(graph[c['scale']]['inputs']['scale_to_length'], [c['length'], 0])
                    self.assertEqual(graph[c['length']]['inputs']['value'], 1024 if length is None else length)
                    for nid in (c['reference'], c['embeds']):
                        for axis in ('width', 'height'):
                            self.assertEqual(graph[nid]['inputs'][axis], original[nid]['inputs'][axis])
                    self.assertEqual(graph[c['scale']]['inputs']['aspect_ratio'], 'original')
                    self.assertEqual(graph[c['scale']]['inputs']['round_to_multiple'], '16')
                    for f in self.spec(wid)['controls']:
                        if f.get('kind') == 'seed':
                            self.assertEqual(values[f['id']], 314159)
                            for target in f['targets']:
                                self.assertEqual(graph[target['node']]['inputs'][target['input']], 314159)

    def test_custom_dimensions_update_actual_preprocess_reference_and_model_together(self):
        for wid, c in CONTRACTS.items():
            for width, height in ((640, 480), (832, 480), (64, 8096)):
                with self.subTest(wid=wid, width=width, height=height):
                    graph, values, _ = self.build(wid,
                        {c['embeds']+':width': width, c['embeds']+':height': height,
                         c['length']+':value': 1536})
                    scale = graph[c['scale']]['inputs']
                    self.assertEqual((scale['aspect_ratio'], scale['proportional_width'], scale['proportional_height']),
                                     ('custom', width, height))
                    self.assertEqual((scale['scale_to_side'], scale['scale_to_length'], scale['round_to_multiple']),
                                     ('longest', max(width, height), '32'))
                    for nid in (c['reference'], c['embeds']):
                        self.assertEqual((graph[nid]['inputs']['width'], graph[nid]['inputs']['height']), (width, height))
                    self.assertEqual(values[c['length']+':value'], 1536)
                    if wid == 'local-card-22':
                        # Its authored black reference canvas follows the scale
                        # outputs; it must not be stranded at an old size.
                        self.assertEqual(graph['577']['inputs']['width'], [c['scale'], 3])
                        self.assertEqual(graph['577']['inputs']['height'], [c['scale'], 4])

    def test_bad_pairs_fail_before_any_remote_execution(self):
        bad_pairs = ((0, 480), (640, 0), (32, 64), (64, 8128), (65, 64),
                     (-32, 64), (64.5, 64), (True, 64), (float('nan'), 64), (float('inf'), 64))
        for wid, c in CONTRACTS.items():
            spec = self.spec(wid)
            for width, height in bad_pairs:
                values = {c['embeds']+':width': width, c['embeds']+':height': height}
                with self.subTest(wid=wid, width=width, height=height), self.assertRaises(ValueError):
                    runtime.validate_values(spec, values)
                with self.subTest(helper=wid, width=width, height=height), self.assertRaises(ValueError):
                    scail_dimension_values(spec, values)

    def test_schema_finalization_is_idempotent_and_retains_zero_as_reviewed_sentinel(self):
        for wid, c in CONTRACTS.items():
            original = copy.deepcopy(runtime.manifest(wid))
            original_snapshot = copy.deepcopy(original)
            spec = finalize_scail_schema(original)
            self.assertEqual(original, original_snapshot)
            self.assertEqual(finalize_scail_schema(spec), spec)
            expected = {'type': 'paired-size', 'width': c['embeds']+':width', 'height': c['embeds']+':height',
                        'min_nonzero': 64, 'max': 8096, 'multiple': 32}
            self.assertIn(expected, spec['constraints'])
            for axis in ('width', 'height'):
                field = next(f for f in spec['controls'] if f['id'] == c['embeds']+':'+axis)
                self.assertEqual((field['value'], field['min'], field['nativeMinimum'], field['step']), (0, 0, 64, 32))
                self.assertLessEqual(len(field['help']), 12)
                self.assertEqual(field['dimensionGroup'], 'video-size')
                self.assertEqual(field['dimensionAxis'], axis)
            previous = {f['id']: f for f in original['controls']}
            added = {c['embeds']+':width', c['embeds']+':height', c.get('mode_source', '')+':value'}
            for field in spec['controls']:
                if field['id'] in previous and field['id'] not in added:
                    self.assertEqual(field, previous[field['id']])

    def test_curated_reuse_has_same_source_targets_and_cannot_accept_drift(self):
        for wid, c in CONTRACTS.items():
            fresh = self.controls(wid)
            derived = {'sourceHash': c['hash'], 'controls': fresh}
            result = reviewed_scail_controls({'id': wid}, fresh, source_hash=c['hash'], derived=derived)
            self.assertEqual(result, fresh)
            for mutant in ('hash', 'target', 'duplicate'):
                altered = copy.deepcopy(derived)
                if mutant == 'hash':
                    altered['sourceHash'] = 'changed'
                elif mutant == 'target':
                    next(f for f in altered['controls'] if f['id'] == c['embeds']+':width')['targets'][0]['node'] = 'wrong'
                else:
                    altered['controls'].append(copy.deepcopy(next(f for f in fresh if f['id'] == c['embeds']+':width')))
                with self.subTest(wid=wid, mutant=mutant), self.assertRaises(ValueError):
                    reviewed_scail_controls({'id': wid}, fresh, source_hash=c['hash'], derived=altered)

    def test_source_and_template_drift_fail_closed_without_writes(self):
        for wid, c in CONTRACTS.items():
            raw = self.source(wid)
            with self.assertRaises(ValueError):
                reviewed_scail_controls({'id': wid}, self.ui[wid]['controls'], graph=Graph(raw), source_hash='changed')
            altered = copy.deepcopy(raw)
            scale = next(n for n in altered['nodes'] if str(n['id']) == c['scale'])
            scale['type'] = 'OtherResize'
            with self.assertRaises(ValueError):
                reviewed_scail_controls({'id': wid}, self.ui[wid]['controls'], graph=Graph(altered), source_hash=c['hash'])
            spec = self.spec(wid)
            for mutant in ('link', 'constant', 'target', 'constraint'):
                template = read(runtime.template_path(spec)); changed_spec = copy.deepcopy(spec)
                if mutant == 'link':
                    template[c['reference']]['inputs']['width'] = ['other', 3]
                elif mutant == 'constant':
                    template[c['length']]['inputs']['value'] = 768
                elif mutant == 'target':
                    next(f for f in changed_spec['controls'] if f['id'] == c['embeds']+':width')['targets'][0]['node'] = 'wrong'
                else:
                    changed_spec['constraints'][-1]['multiple'] = 16
                with self.subTest(wid=wid, mutant=mutant), self.assertRaises(ValueError):
                    finalize_scail_schema(changed_spec, template=template)
            source_bytes = self.sources[wid].read_bytes()
            path = runtime.template_path(spec); template_bytes = path.read_bytes()
            self.build(wid, {c['embeds']+':width': 640, c['embeds']+':height': 480})
            self.assertEqual(path.read_bytes(), template_bytes)
            self.assertEqual(self.sources[wid].read_bytes(), source_bytes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
