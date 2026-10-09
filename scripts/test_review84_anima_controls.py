"""CPU-only tests of authored Anima switches, concrete bindings and fail-closed proof."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from build_workflow_interfaces import Graph
from compile_card_workflows import Compiler
from review84_anima_controls import CONTRACTS, TURBO_LORA, reviewed_anima_controls
from schema_adapters import build, manifest, template_path, validate_values


class ReviewedAnimaControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {row['id']: row for row in json.loads(
            (ROOT / 'verification/catalog-audit.json').read_text('utf-8')) if 'id' in row}
        cls.ui = json.loads((ROOT / 'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
        cls.schemas = json.loads((ROOT / 'private/research/card-20261004/object_info.json').read_text('utf-8'))

    def source(self, wid):
        path = Path(self.sources[wid]['source'])
        data = path.read_bytes()
        raw = json.loads(data.decode('utf-8-sig'))
        return path, data, hashlib.sha256(data).hexdigest(), raw, Graph(raw)

    def fresh(self, wid, graph=None):
        _, _, digest, _, original_graph = self.source(wid)
        return reviewed_anima_controls({'id': wid}, copy.deepcopy(self.ui[wid]['controls']),
                                       graph=graph or original_graph, source_hash=digest)

    def spec(self, wid):
        _, _, _, raw, _ = self.source(wid)
        compiler = Compiler(raw, self.schemas)
        outputs = compiler.outputs('image')
        spec = copy.deepcopy(manifest(wid))
        fields = [field for field in self.fresh(wid) if field['kind'] in ('steps', 'toggle')]
        identifiers = {field['id'] for field in fields}
        spec['controls'] = [field for field in spec['controls'] if field['id'] not in identifiers]
        for field in fields:
            field['targets'] = [mapped for target in field['targets']
                                for mapped in compiler.targets(target['node'], target['input'])]
            self.assertEqual(len(field['targets']), 1)
            spec['controls'].append(field)
        self.assertEqual(outputs, spec['outputs'])
        # Isolate the CPU parameter path; no upload, API key or remote request.
        spec.update(texts=[], media=[], apiProfiles=[])
        return spec

    def cpu_graph(self, wid, values=None):
        spec = self.spec(wid)
        fixed = {field['id']: 7 for field in spec['controls'] if field['kind'] == 'seed'}
        fixed.update(values or {})
        return build(spec, fixed, {}, {}, {}, 'cpu-anima-review84')[0]

    def scalar(self, graph, value):
        if not isinstance(value, list):
            return value
        nid, index = value
        self.assertEqual(index, 0)
        node = graph[str(nid)]
        if node['class_type'] == 'ComfySwitchNode':
            enabled = self.scalar(graph, node['inputs']['switch'])
            self.assertIs(type(enabled), bool)
            return self.scalar(graph, node['inputs']['on_true' if enabled else 'on_false'])
        self.assertIn(node['class_type'], ('PrimitiveBoolean', 'PrimitiveInt', 'PrimitiveFloat', 'easy boolean'))
        return self.scalar(graph, node['inputs']['value'])

    def selected_model(self, graph, value):
        nid, index = value
        self.assertEqual(index, 0)
        node = graph[nid]
        if node['class_type'] == 'ComfySwitchNode':
            enabled = self.scalar(graph, node['inputs']['switch'])
            return self.selected_model(graph, node['inputs']['on_true' if enabled else 'on_false'])
        return nid

    def test_source_defaults_preserved_and_only_current_step_branch_is_visible(self):
        for wid, contract in CONTRACTS.items():
            with self.subTest(wid=wid):
                path, data, digest, _, graph = self.source(wid)
                controls = copy.deepcopy(self.ui[wid]['controls'])
                before_graph = copy.deepcopy(graph.__dict__)
                result = reviewed_anima_controls({'id': wid}, controls, graph=graph, source_hash=digest)
                fields = [field for field in result if field['kind'] in ('steps', 'toggle')]
                self.assertEqual([field['value'] for field in fields], [True, contract['standard'], 8])
                toggle = contract['toggle'] + ':value'
                self.assertEqual(fields[1]['visibleWhen'], {'controlId': toggle, 'equals': False, 'defaultValue': True})
                self.assertEqual(fields[2]['visibleWhen'], {'controlId': toggle, 'equals': True, 'defaultValue': True})
                self.assertEqual(fields[0]['accelerationTechnology'], 'Anima Turbo LoRA v0.2')
                self.assertEqual(graph.__dict__, before_graph)
                self.assertEqual(path.read_bytes(), data)
                ids = {field['id'] for field in fields}
                self.assertEqual([field for field in result if field['id'] not in ids],
                                 [field for field in controls if field['id'] not in ids])
                fresh = {'sourceHash': digest, 'controls': result}
                self.assertEqual(reviewed_anima_controls({'id': wid}, controls, source_hash=digest, derived=fresh), result)
                self.assertEqual(reviewed_anima_controls({'id': wid}, result, graph=graph, source_hash=digest), result)

    def test_new_controls_resolve_to_existing_compiled_nodes(self):
        for wid, contract in CONTRACTS.items():
            with self.subTest(wid=wid):
                spec = self.spec(wid)
                fields = {field['id']: field for field in spec['controls']}
                for primitive in ('107', '108'):
                    self.assertEqual(fields['sub0/' + primitive + ':value']['targets'],
                                     [{'node': contract['parent'] + ':' + primitive, 'input': 'value'}])
                self.assertEqual(fields[contract['toggle'] + ':value']['targets'],
                                 [{'node': contract['toggle'], 'input': 'value'}])

    def test_acceleration_switch_retains_lora_steps_and_cfg_linkage(self):
        for wid, contract in CONTRACTS.items():
            template = template_path(manifest(wid))
            before = template.read_bytes()
            for enabled in (False, True):
                with self.subTest(wid=wid, enabled=enabled):
                    graph = self.cpu_graph(wid, {contract['toggle'] + ':value': enabled})
                    prefix = contract['parent'] + ':'
                    sampler = graph[prefix + '106']['inputs']
                    self.assertEqual(self.scalar(graph, sampler['steps']), 8 if enabled else contract['standard'])
                    self.assertEqual(self.scalar(graph, sampler['cfg']), 1 if enabled else 4)
                    self.assertEqual(self.selected_model(graph, sampler['model']), prefix + ('109' if enabled else '87'))
                    self.assertEqual(graph[prefix + '109']['inputs']['lora_name'], TURBO_LORA)
                    self.assertEqual(sampler['steps'], [prefix + '111', 0])
                    self.assertEqual(sampler['cfg'], [prefix + '113', 0])
                    self.assertEqual(sampler['model'], [prefix + '110', 0])
            self.assertEqual(template.read_bytes(), before)

    def test_step_changes_write_only_selected_scalar_and_preserve_other_branch(self):
        for wid, contract in CONTRACTS.items():
            for enabled, primitive in ((False, '107'), (True, '108')):
                values = {contract['toggle'] + ':value': enabled}
                before = self.cpu_graph(wid, values)
                changed = self.cpu_graph(wid, {**values, 'sub0/' + primitive + ':value': 17})
                node = contract['parent'] + ':' + primitive
                sampler = changed[contract['parent'] + ':106']['inputs']
                self.assertEqual(self.scalar(changed, sampler['steps']), 17)
                changed[node]['inputs']['value'] = before[node]['inputs']['value']
                self.assertEqual(changed, before)

    def test_step_native_bounds_and_boolean_validation(self):
        native = self.schemas['KSampler']['input']['required']['steps']
        self.assertEqual((native[0], native[1]['min'], native[1]['max']), ('INT', 1, 10000))
        for wid, contract in CONTRACTS.items():
            spec = self.spec(wid)
            toggle = contract['toggle'] + ':value'
            for field in [field for field in spec['controls'] if field['kind'] == 'steps']:
                self.assertEqual((field['min'], field['max'], field['step']), (1, 10000, 1))
                self.assertNotIn('options', field)
                for valid in (1, 17, 10000):
                    self.assertEqual(validate_values(spec, {field['id']: valid})[field['id']], valid)
                for invalid in (True, 0, 10001, 3.5, '8'):
                    with self.subTest(wid=wid, value=invalid), self.assertRaises(ValueError):
                        validate_values(spec, {field['id']: invalid})
            for invalid in ('false', 0, 1, None):
                with self.subTest(wid=wid, toggle=invalid), self.assertRaises(ValueError):
                    validate_values(spec, {toggle: invalid})

    def test_hash_default_topology_and_curated_drift_fail_closed(self):
        for wid, contract in CONTRACTS.items():
            _, _, digest, _, graph = self.source(wid)
            controls = copy.deepcopy(self.ui[wid]['controls'])
            with self.assertRaises(ValueError):
                reviewed_anima_controls({'id': wid}, controls, graph=graph, source_hash='changed')
            for change in ('default', 'inactive', 'steps_edge', 'cfg_edge', 'model_edge'):
                altered = copy.deepcopy(graph)
                if change == 'default':
                    # The reviewed source names override older positional UI
                    # snapshots. Change the executable named value, not a stale
                    # positional decoration that the compiler does not consume.
                    altered.nodes['sub0/107']['widgets_values_named'] = {'value': contract['standard'] + 1}
                elif change == 'inactive':
                    altered.nodes['sub0/108']['mode'] = 2
                else:
                    altered.out[{'steps_edge': 'sub0/111', 'cfg_edge': 'sub0/113', 'model_edge': 'sub0/110'}[change]] = []
                with self.subTest(wid=wid, change=change), self.assertRaises(ValueError):
                    reviewed_anima_controls({'id': wid}, controls, graph=altered, source_hash=digest)
            fresh = self.fresh(wid)
            next(field for field in fresh if field['kind'] == 'steps')['targets'] = [{'node': 'wrong', 'input': 'value'}]
            with self.assertRaises(ValueError):
                reviewed_anima_controls({'id': wid}, controls, source_hash=digest,
                                        derived={'sourceHash': digest, 'controls': fresh})

    def test_other_workflows_unchanged(self):
        controls = [{'id': 'example', 'kind': 'seed', 'value': 7}]
        for wid in ('local-card-80', 'local-card-81', 'local-card-85', 'local-card-89', 'future-workflow'):
            self.assertIs(reviewed_anima_controls({'id': wid}, controls, source_hash='ignored'), controls)

    def test_depth_preprocessor_is_an_intermediate_and_saved_output_is_decoded_manga(self):
        graph = self.cpu_graph('local-card-87')
        self.assertEqual(graph['710']['inputs']['preprocessor'], 'DepthAnythingV2Preprocessor')
        self.assertEqual(graph['699:87']['class_type'], 'AnimaLLLiteApply')
        self.assertEqual(graph['699:87']['inputs']['image'], ['696', 0])
        self.assertEqual(graph['696']['inputs']['input'], ['702', 0])
        self.assertEqual(graph['702']['inputs']['images'], ['710', 0])
        self.assertEqual(graph['695']['inputs']['images'], ['699:105', 0])
        self.assertEqual(graph['699:105']['class_type'], 'VAEDecode')
        self.assertNotIn('700', graph)


if __name__ == '__main__':
    unittest.main()
