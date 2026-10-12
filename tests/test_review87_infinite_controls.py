"""Published InfiniteTalk graphs, with optional historical native CPU evidence."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from review87_infinite_controls import (CONTRACTS, SPEAKER_CONTROL_ID, SPEAKER_RECIPE,
    apply_infinite_speaker_regions, finalize_infinite_schema, reviewed_infinite_config,
    validate_speaker_regions, verify_upscale_batch_semantics, derive_infinite_reference_geometry,
    map_speaker_regions, OUTPUT_LOOP_POLICIES)
from build_workflow_interfaces import Graph
from public_fixtures import historical_path
import schema_adapters as runtime


def read(path):
    return json.loads(path.read_text('utf-8-sig'))


BOXES = [{'x': .08, 'y': .15, 'width': .3, 'height': .7},
         {'x': .6, 'y': .18, 'width': .33, 'height': .65}]


# A declared test protocol, not evidence of a currently installed ComfyUI server.
# Mutation tests below exercise production rejection of missing/changed contracts.
MASK_SCHEMAS = {
    'MathExpression|pysssss': {'input': {'required': {'expression': ['STRING']}, 'optional': {'a': ['*']}}, 'output': ['INT', 'FLOAT']},
    'SolidMask': {'input': {'required': {'value': ['FLOAT'], 'width': ['INT'], 'height': ['INT']}}, 'output': ['MASK']},
    'MaskComposite': {'input': {'required': {'destination': ['MASK'], 'source': ['MASK'], 'x': ['INT'], 'y': ['INT'], 'operation': [['add', 'subtract']]}}, 'output': ['MASK']},
    'MaskBatchMulti': {'input': {'required': {'inputcount': ['INT'], 'mask_1': ['MASK'], 'mask_2': ['MASK']}}, 'output': ['MASK']},
    'GetImageSizeAndCount': {'output': ['IMAGE', 'INT', 'INT', 'INT']},
}


class InfiniteControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = read(ROOT / 'public/workflow-interfaces.json')['workflows']
        cls.published_registry = {wid: deepcopy(runtime.manifest(wid)) for wid in CONTRACTS}

    def template(self, wid):
        self.assertEqual(self.published_registry[wid]['source_hash'], CONTRACTS[wid]['hash'])
        return read(runtime.template_path(self.published_registry[wid]))

    def compiled_spec(self):
        graph = self.template('local-card-101')
        return finalize_infinite_schema(deepcopy(self.published_registry['local-card-101']), graph), graph

    def geometry(self, spec, width=832, height=480, length=832):
        return derive_infinite_reference_geometry(spec, {'321:value': length}, width, height)

    def test_published_controls_have_reachable_targets_and_preserved_defaults(self):
        for wid in CONTRACTS:
            graph = self.template(wid)
            spec = self.published_registry[wid]
            compiled = {f['id']: f for f in spec['controls']}
            for field in self.ui[wid]['controls']:
                if field['id'] not in compiled:
                    continue  # UI-only/excluded controls are not execution inputs.
                actual = compiled[field['id']]
                self.assertEqual(actual.get('value'), field.get('value'), (wid, field['id']))
                for target in actual.get('targets', []):
                    self.assertIn(target['node'], graph)
                    if not actual.get('transform'):
                        self.assertIn(target['input'], graph[target['node']]['inputs'])

    def test_historical_author_controls_preserved_during_review(self):
        before_ui = read(historical_path('workflow-controls-review87/before-workflow-interfaces.json'))['workflows']
        for wid in CONTRACTS:
            raw = historical_path('sources/' + wid + '.json').read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), CONTRACTS[wid]['hash'])
            before = before_ui[wid]
            after = reviewed_infinite_config(wid, before, Graph(json.loads(raw.decode('utf-8-sig'))))
            new = {f['id']: f for f in after['controls']}
            for field in before['controls']:
                for key in ('value', 'key', 'type', 'targets', 'members', 'derived'):
                    self.assertEqual(new[field['id']].get(key), field.get(key), (wid, field['id'], key))
            self.assertEqual(after['texts'], before['texts'])
            self.assertEqual(after['media'], before['media'])

    def test_audio_endpoints_are_timecodes_with_legacy_literal_preserved(self):
        for wid in ('local-card-99', 'local-card-100', 'local-card-101'):
            fields = {f['id']: f for f in self.ui[wid]['controls']}
            key = '365:value' if wid.endswith('101') else '159:end_time'
            self.assertIn('片段终点（分:秒）', fields[key]['label'])
            self.assertEqual(fields[key]['timecodeInput'], 'integer-seconds-or-mm:ss')
        fields = {f['id']: f for f in self.ui['local-card-99']['controls']}
        self.assertEqual(fields['159:end_time']['value'], '10')

    def test_8_and_16_are_upscale_batch_heuristic_and_sampling_remains_four(self):
        for wid in ('local-card-99', 'local-card-100'):
            result = verify_upscale_batch_semantics(self.template(wid))
            self.assertEqual(result['atOrAbove'], 8)
            self.assertEqual(result['below'], 16)
            self.assertEqual(result['samplingSteps'], 4)

    def test_speaker_masks_follow_audio_order_on_actual_reference_dimensions(self):
        spec, graph = self.compiled_spec()
        original = deepcopy(graph)
        result = apply_infinite_speaker_regions(graph, spec, {SPEAKER_CONTROL_ID: json.dumps(BOXES)}, self.geometry(spec))
        self.assertIs(result, graph)
        self.assertEqual(graph['194']['inputs']['ref_target_masks'], ['review87_speakers', 0])
        self.assertEqual(graph['review87_speakers']['inputs']['mask_1'], ['review87_speaker_1_mask', 0])
        self.assertEqual(graph['review87_speakers']['inputs']['mask_2'], ['review87_speaker_2_mask', 0])
        self.assertEqual(graph['review87_speaker_blank']['inputs']['width'], ['291', 1])
        self.assertEqual(graph['review87_speaker_blank']['inputs']['height'], ['291', 2])
        self.assertEqual(graph['131']['inputs']['frame_rate'], graph['194']['inputs']['fps'])
        for nid in original:
            if nid not in ('131', '194'):
                self.assertEqual(graph[nid], original[nid], nid)
        self.assertEqual(graph['128']['inputs']['steps'], 4)

    def test_mask_inputs_follow_declared_protocol_and_links_survive_pruning(self):
        spec, graph = self.compiled_spec()
        apply_infinite_speaker_regions(graph, spec, {SPEAKER_CONTROL_ID: json.dumps(BOXES)}, self.geometry(spec))
        pruned = runtime.prune(graph, spec['outputs'])
        types = MASK_SCHEMAS
        count = 0
        for nid, node in pruned.items():
            if not nid.startswith('review87_'):
                continue
            count += 1
            cls = node['class_type']
            allowed = {**types[cls]['input'].get('required', {}), **types[cls]['input'].get('optional', {})}
            self.assertFalse(set(node['inputs']) - set(allowed), nid)
            self.assertTrue(set(types[cls]['input'].get('required', {})) <= set(node['inputs']), nid)
            for key, value in node['inputs'].items():
                if isinstance(value, list):
                    self.assertIn(value[0], pruned)
                    source_node = pruned[value[0]]
                    source_type = types[source_node['class_type']]
                    output_type = source_type['output'][value[1]]
                    self.assertIn(allowed[key][0], (output_type, '*'), (nid, key))
        self.assertEqual(count, 14)

    def test_no_default_regions_no_gpu_submission_path(self):
        spec, graph = self.compiled_spec()
        with self.assertRaisesRegex(ValueError, '分别框选'):
            apply_infinite_speaker_regions(graph, spec, {})
        self.assertNotIn('review87_speakers', graph)

    def test_invalid_regions_rejected_and_partial_overlap_accepted(self):
        invalid = [None, [], BOXES[:1], BOXES * 2, 'bad', [{'x': 0}],
                   [BOXES[0], BOXES[0]], [dict(BOXES[0], width=0), BOXES[1]],
                   [dict(BOXES[0], x=-.1), BOXES[1]], [dict(BOXES[0], x=.9), BOXES[1]],
                   [dict(BOXES[0], x=True), BOXES[1]], [dict(BOXES[0], x=float('nan')), BOXES[1]],
                   [dict(BOXES[0], height=1e-320), BOXES[1]],
                   [dict(BOXES[0], x=10**1000), BOXES[1]],
                   [dict(BOXES[0], target='194'), BOXES[1]]]
        for boxes in invalid:
            with self.subTest(boxes=repr(boxes)[:60]), self.assertRaises(ValueError):
                validate_speaker_regions(boxes)
        with self.assertRaises(ValueError):
            validate_speaker_regions([BOXES[0], dict(BOXES[0], x=BOXES[0]['x'] + 1e-13)])
        self.assertEqual(len(validate_speaker_regions([BOXES[0], dict(BOXES[1], x=.35)])), 2)

    def test_source_drift_and_unrelated_templates_do_not_receive_masks(self):
        spec, graph = self.compiled_spec()
        bad = deepcopy(spec)
        bad['source_hash'] = 'changed'
        with self.assertRaisesRegex(ValueError, '来源'):
            apply_infinite_speaker_regions(graph, bad, {SPEAKER_CONTROL_ID: json.dumps(BOXES)}, self.geometry(spec))
        altered = deepcopy(graph)
        altered['192']['inputs']['width'] = 832
        with self.assertRaisesRegex(ValueError, '宽高'):
            apply_infinite_speaker_regions(altered, spec, {SPEAKER_CONTROL_ID: json.dumps(BOXES)}, self.geometry(spec))
        unchanged = {'native': {'class_type': 'other', 'inputs': {}}}
        self.assertIs(apply_infinite_speaker_regions(unchanged, {'id': 'local-card-99'}, {}), unchanged)
        self.assertNotIn('review87_speakers', unchanged)

    def test_missing_or_drifted_mask_dependency_is_not_marked_usable(self):
        spec, graph = self.compiled_spec()
        self.assertEqual(finalize_infinite_schema(spec, graph, schemas=MASK_SCHEMAS)['speakerRegionsRecipe'], SPEAKER_RECIPE)
        for cls in SPEAKER_RECIPE['maskClasses']:
            with self.subTest(missing=cls):
                info = deepcopy(MASK_SCHEMAS)
                del info[cls]
                with self.assertRaisesRegex(ValueError, '原生节点缺失'):
                    finalize_infinite_schema(spec, graph, schemas=info)
            with self.subTest(output_type=cls):
                info = deepcopy(MASK_SCHEMAS)
                info[cls]['output'][0] = 'STRING'
                with self.assertRaisesRegex(ValueError, '接口已改变'):
                    finalize_infinite_schema(spec, graph, schemas=info)
        info = deepcopy(MASK_SCHEMAS)
        info['MaskComposite']['input']['required']['operation'] = [['subtract']]
        with self.assertRaisesRegex(ValueError, '合成操作不可用'):
            finalize_infinite_schema(spec, graph, schemas=info)

    def test_safe_idempotent_projection_and_node_collision_rejected(self):
        spec, graph = self.compiled_spec()
        values = {SPEAKER_CONTROL_ID: json.dumps(BOXES)}
        apply_infinite_speaker_regions(graph, spec, values, self.geometry(spec))
        once = deepcopy(graph)
        apply_infinite_speaker_regions(graph, spec, values, self.geometry(spec))
        self.assertEqual(graph, once)
        spec, graph = self.compiled_spec()
        graph['review87_speaker_blank'] = {'class_type': 'other', 'inputs': {}}
        with self.assertRaisesRegex(ValueError, '名称冲突'):
            apply_infinite_speaker_regions(graph, spec, values, self.geometry(spec))

    def test_loop_fields_share_real_vhs_sinks_and_keep_zero_template_defaults(self):
        for wid in CONTRACTS:
            cfg = self.ui[wid]
            policies = cfg['outputLoopPolicies']
            self.assertEqual(policies, OUTPUT_LOOP_POLICIES[wid])
            field = next(f for f in cfg['controls'] if f['kind'] == 'loop')
            self.assertEqual(field['targets'], [{'node': p['node'], 'input': 'loop_count'} for p in policies])
            self.assertEqual((field['value'], field['min'], field['max']), (0, 0, 100))
            original = self.template(wid)
            for target in field['targets']:
                self.assertEqual(original[target['node']]['inputs']['loop_count'], 0)
            self.assertIn('音画同步重复', field['help'])
            self.assertIn('画面与声音一起循环',field['title'])

    def test_reference_geometry_exact_longest_ratio_round16_and_model_bounds(self):
        spec, _ = self.compiled_spec()
        expected = self.geometry(spec, 1920, 1080, 640)
        self.assertEqual(expected['target'], {'width': 640, 'height': 368})
        self.assertGreater(expected['crop']['x'], 0.)
        self.assertEqual(expected['crop']['height'], 1.)
        self.assertEqual(self.geometry(spec, 1080, 1920, 640)['target'], {'width': 368, 'height': 640})
        self.assertEqual(self.geometry(spec, 1920, 1080, 2048)['width'], 2048)
        for width, height, longest in ((100000, 10, 832), (10, 100000, 832), (1920, 1080, 2049), (1000, 1000, 48)):
            with self.subTest(width=width, height=height, length=longest), self.assertRaises(ValueError):
                self.geometry(spec, width, height, longest)
        for wid in ('local-card-99', 'local-card-100'):
            graph = self.template(wid)
            other = finalize_infinite_schema(self.published_registry[wid], graph)
            self.assertLessEqual(next(f for f in other['controls'] if f['id'] == '321:value')['max'], 2048)
        self.assertEqual(derive_infinite_reference_geometry(other, {'321:value': 832}, 641, 479)['source'], {'width': 640, 'height': 480})

    def test_original_photo_regions_are_mapped_once_through_actual_crop(self):
        spec, graph = self.compiled_spec()
        geometry = self.geometry(spec, 1920, 1080, 640)
        with self.assertRaisesRegex(ValueError, '真实处理画面'):
            apply_infinite_speaker_regions(graph, spec, {SPEAKER_CONTROL_ID: json.dumps(BOXES)})
        mapped = map_speaker_regions(BOXES, geometry)
        self.assertNotAlmostEqual(mapped[0]['x'], BOXES[0]['x'])
        self.assertAlmostEqual(mapped[0]['x'], (BOXES[0]['x'] - geometry['crop']['x']) / geometry['crop']['width'])
        edge_boxes = [dict(BOXES[0], x=0, width=.005), BOXES[1]]
        with self.assertRaisesRegex(ValueError, '裁切外'):
            map_speaker_regions(edge_boxes, geometry)
        values = {SPEAKER_CONTROL_ID: json.dumps(BOXES), '321:value': 640}
        apply_infinite_speaker_regions(graph, spec, values, geometry)
        saved = deepcopy(graph)
        apply_infinite_speaker_regions(graph, spec, values, geometry)
        self.assertEqual(graph, saved)
        self.assertEqual(graph['194']['_meta']['review87_speaker_geometry']['originalBoxes'], BOXES)
        self.assertEqual(graph['194']['_meta']['review87_speaker_geometry']['mappedBoxes'], mapped)

    def test_production_build_and_rerun_keep_original_boxes_and_zero_native_loop(self):
        spec, _ = self.compiled_spec()
        spec.update(media=[], texts=[], apiProfiles=[])
        geometry = self.geometry(spec, 1920, 1080, 640)
        supplied = {SPEAKER_CONTROL_ID: json.dumps(BOXES), '321:value': 640,
                    '131:loop_count': 2, '341:seed': 123456}
        graph, values, _ = runtime.build(spec, supplied, {}, {}, {}, 'review87-build-cpu', geometry=geometry)
        self.assertEqual(json.loads(values[SPEAKER_CONTROL_ID]), BOXES)
        self.assertEqual(values['131:loop_count'], 2)
        self.assertEqual(graph['131']['inputs']['loop_count'], 0)
        self.assertEqual(graph['131']['_meta']['yingxu_output_loop_v1']['extra_repeats'], 2)
        self.assertEqual(graph['194']['inputs']['ref_target_masks'], ['review87_speakers', 0])
        original = {'schema_spec': spec, 'graph': graph, 'catalog_values': values}
        rerun, rerun_values = runtime.rerun(original, {}, 'review87-rerun-cpu', randomize_seed=False, geometry=geometry)
        self.assertEqual(rerun_values, values)
        self.assertEqual(rerun['194']['_meta']['review87_speaker_geometry'], graph['194']['_meta']['review87_speaker_geometry'])
        self.assertEqual(rerun['131']['inputs']['loop_count'], 0)
        self.assertEqual(rerun['131']['_meta']['yingxu_output_loop_v1']['extra_repeats'], 2)

    def test_cpu_executes_upstream_math_solid_composite_batch_without_gpu(self):
        proof = historical_path('workflow-controls-review87')
        try:
            import torch
        except ImportError:
            self.skipTest('Optional upstream CPU execution requires torch.')
        # Math's official AST evaluator is standalone and does not load ComfyUI.
        module = importlib.util.spec_from_file_location('review87_native_math', proof / 'upstream-math-expression.py')
        math_module = importlib.util.module_from_spec(module)
        module.loader.exec_module(math_module)
        # Execute the official node class bodies with only device/API wrappers.
        io = SimpleNamespace(ComfyNode=object, NodeOutput=lambda *x: x)
        comfy = SimpleNamespace(model_management=SimpleNamespace(intermediate_device=lambda: torch.device('cpu')))
        env = {'IO': io, 'torch': torch, 'comfy': comfy}
        tree = ast.parse((proof / 'upstream-core-mask.py').read_text('utf-8'))
        selected = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ('SolidMask', 'MaskComposite')]
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(proof / 'upstream-core-mask.py'), 'exec'), env)
        tree = ast.parse((proof / 'upstream-kj-mask-nodes.py').read_text('utf-8'))
        selected = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MaskBatchMulti']
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(proof / 'upstream-kj-mask-nodes.py'), 'exec'), env)
        for width, height in ((832, 480), (480, 832), (641, 479), (64, 64)):
            with self.subTest(width=width, height=height):
                spec, graph = self.compiled_spec()
                geometry = self.geometry(spec, width, height, max(width, height))
                width, height = geometry['width'], geometry['height']
                apply_infinite_speaker_regions(graph, spec, {SPEAKER_CONTROL_ID: json.dumps(BOXES)}, geometry)
                cache = {'291': (None, width, height)}
                def execute(nid):
                    if nid in cache:
                        return cache[nid]
                    node = graph[nid]
                    args = {k: execute(v[0])[v[1]] if isinstance(v, list) else v for k, v in node['inputs'].items()}
                    cls = node['class_type']
                    if cls == 'MathExpression|pysssss':
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', DeprecationWarning)
                            output = math_module.MathExpression().evaluate(prompt={}, **args)['result']
                    elif cls == 'MaskBatchMulti':
                        output = env[cls]().combine(**args)
                    else:
                        output = env[cls].execute(**args)
                    cache[nid] = output
                    return output
                masks = execute('review87_speakers')[0]
                self.assertEqual(tuple(masks.shape), (2, height, width))
                self.assertEqual(masks.device.type, 'cpu')
                for index, box in enumerate(graph['194']['_meta']['review87_speaker_geometry']['mappedBoxes']):
                    x, y = int(box['x'] * width), int(box['y'] * height)
                    self.assertEqual(float(masks[index, y, x]), 1.)
                    self.assertGreater(float(masks[index].sum()), 0.)
                    self.assertEqual(float(masks[index, 0, 0]), 0.)
                self.assertEqual(float(cache['review87_speaker_blank'][0].sum()), 0.)


if __name__ == '__main__':
    unittest.main()
