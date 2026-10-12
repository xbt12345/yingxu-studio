"""Public-graph CPU submission tests; no provider or GPU queue requests."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import schema_adapters as runtime
from public_fixtures import historical_path
from scripts.review87_flash_controls import (
    POLICIES, reviewed_flash_config, reviewed_flash_controls, finalize_flash_schema,
    apply_flash_control_projection, derive_flash_processing_geometry,
)
from scripts.review87_output_loops import MARKER


def read(path):
    return json.loads(path.read_text('utf-8-sig'))


class FlashControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interfaces = read(ROOT / 'public/workflow-interfaces.json')['workflows']

    def config(self, wid):
        self.assertEqual(self.interfaces[wid]['sourceHash'], POLICIES[wid]['hash'])
        spec = runtime.manifest(wid)
        graph = read(runtime.template_path(spec))
        # Authored subgraph IDs differ from compiled execution IDs. Validate the
        # shipped API with its execution guard, then check interface idempotency.
        finalize_flash_schema(spec, template=graph)
        return reviewed_flash_config(wid, self.interfaces[wid])

    def spec(self, wid):
        spec = copy.deepcopy(runtime.manifest(wid))
        previous = {field['id']: field for field in spec['controls']}
        for field in reviewed_flash_controls(wid):
            if field['id'] not in previous:
                spec['controls'].append(copy.deepcopy(field))
        template = read(runtime.template_path(spec))
        return finalize_flash_schema(spec, template=template)

    def build(self, spec, values):
        records = {field['id']: {'kind': 'video', 'remote': 'owned-clip.mp4'} for field in spec['media']}
        old_projection = runtime.apply_ltx_control_projection
        def hook(graph, contract, scalar):
            return apply_flash_control_projection(old_projection(graph, contract, scalar), contract, scalar)
        fixed_seed = {field['id']: 0 for field in spec['controls'] if field.get('kind') == 'seed'}
        with patch.object(runtime, 'apply_ltx_control_projection', side_effect=hook):
            return runtime.build(spec, {**fixed_seed, **values}, {}, records, {}, 'offline-flash-review')[0]

    def test_public_execution_contract_preserves_existing_controls(self):
        for wid in POLICIES:
            with self.subTest(wid=wid):
                previous = copy.deepcopy(self.interfaces[wid])
                cfg = self.config(wid)
                self.assertEqual(self.interfaces[wid], previous)
                self.assertEqual(reviewed_flash_config(wid, cfg), cfg)
                by_id = {field['id']: field for field in cfg['controls']}
                for field in previous['controls']:
                    for key in ('value', 'key', 'targets', 'derived', 'members'):
                        self.assertEqual(by_id[field['id']].get(key), field.get(key))
                self.assertEqual(len(cfg['outputLoopPolicies']), len(POLICIES[wid]['sinks']))

    def test_historical_native_widget_limits_match_reviewed_controls(self):
        evidence = historical_path('workflow-controls-review87')
        native = read(evidence / 'flash-native-VHS_LoadVideo.json')['VHS_LoadVideo']['input']['required']
        loop = read(evidence / 'native-VHS_VideoCombine.json')['VHS_VideoCombine']['input']['required']['loop_count']
        for wid in POLICIES:
            for field in reviewed_flash_controls(wid):
                expected = native[field['key']] if field['key'].startswith('custom_') else loop
                self.assertEqual(expected[0], 'INT')
                self.assertEqual(expected[1]['max'], field['max'])
                if field['key'].startswith('custom_'):
                    self.assertEqual(expected[1]['min'], field['min'])

    def test_custom_dimensions_survive_the_actual_submission_graph(self):
        for wid, policy in POLICIES.items():
            for width, height in ((640, 480), (960, 0), (0, 720)):
                with self.subTest(wid=wid, width=width, height=height):
                    spec = self.spec(wid)
                    template_path = runtime.template_path(spec)
                    before = template_path.read_bytes()
                    graph = self.build(spec, {policy['loader'] + ':custom_width': width,
                                              policy['loader'] + ':custom_height': height})
                    self.assertEqual(graph[policy['loader']]['inputs']['custom_width'], width)
                    self.assertEqual(graph[policy['loader']]['inputs']['custom_height'], height)
                    if policy['resize']:
                        self.assertEqual(graph[policy['resize']]['inputs']['scale_to_side'], 'None')
                        self.assertEqual(graph[policy['resize']]['inputs']['image'], policy['resizeSource'])
                    if wid == 'local-card-122':
                        expected_short_edge = next(f['value'] for f in spec['controls'] if f['id'] == '34:value')
                        self.assertEqual(graph['10']['inputs']['resolution'], expected_short_edge)
                    self.assertEqual(template_path.read_bytes(), before)

    def test_zero_dimensions_keep_authored_resize_and_existing_defaults(self):
        for wid, policy in POLICIES.items():
            with self.subTest(wid=wid):
                spec = self.spec(wid)
                graph = self.build(spec, {})
                self.assertEqual(graph[policy['loader']]['inputs']['custom_width'], 0)
                self.assertEqual(graph[policy['loader']]['inputs']['custom_height'], 0)
                if policy['resize']:
                    self.assertEqual(graph[policy['resize']]['inputs']['scale_to_side'], policy['side'])
                for sink in policy['sinks']:
                    self.assertEqual(graph[sink]['inputs']['loop_count'], 0)

    def test_loop_count_changes_output_marker_only_and_keeps_native_audio_link(self):
        for wid, policy in POLICIES.items():
            with self.subTest(wid=wid):
                spec = self.spec(wid)
                original = self.build(spec, {})
                repeated = self.build(spec, {policy['sinks'][0] + ':loop_count': 2})
                expected = copy.deepcopy(original)
                for sink in policy['sinks']:
                    expected[sink].setdefault('_meta', {})[MARKER] = {
                        'version': 1, 'workflow_id': wid, 'node': sink,
                        'extra_repeats': 2, 'control_id': policy['sinks'][0] + ':loop_count',
                        'source_hash': policy['hash'], 'mode': 'repeat-finished-audio-video-stream-copy',
                    }
                    self.assertEqual(repeated[sink]['inputs']['loop_count'], 0)
                    self.assertEqual(repeated[sink]['inputs']['audio'], [policy['loader'], 2])
                self.assertEqual(repeated, expected)

    def test_fractional_negative_huge_boolean_and_nonfinite_values_reject(self):
        wid = 'local-card-118'; policy = POLICIES[wid]; spec = self.spec(wid)
        for bad in (-1, 1.2, True, float('nan'), float('inf'), 8193, 1, 7):
            with self.subTest(width=bad), self.assertRaises(ValueError):
                self.build(spec, {policy['loader'] + ':custom_width': bad})
        for bad in (-1, 1.2, True, float('nan'), float('inf'), 101):
            with self.subTest(loop=bad), self.assertRaises(ValueError):
                self.build(spec, {policy['sinks'][0] + ':loop_count': bad})

    def test_drifted_hash_bindings_types_and_resize_connections_fail_closed(self):
        wid = 'local-card-118'; spec = self.spec(wid); original = read(runtime.template_path(spec))
        bad = copy.deepcopy(spec); bad['source_hash'] = '0' * 64
        with self.assertRaises(ValueError): apply_flash_control_projection(original, bad, {})
        for node, key, value in (('26', 'image', ['13', 1]), ('26', 'round_to_multiple', '32'),
                                  ('24', 'audio', ['13', 0]), ('24', 'format', 'image/gif')):
            graph = copy.deepcopy(original); graph[node]['inputs'][key] = value
            with self.subTest(node=node, key=key), self.assertRaises(ValueError):
                apply_flash_control_projection(graph, spec, {})
        bad = copy.deepcopy(spec)
        field = next(f for f in bad['controls'] if f['id'] == '13:custom_width')
        field['targets'] = [{'node': '24', 'input': 'frame_rate'}]
        with self.assertRaises(ValueError): finalize_flash_schema(bad, template=original)

    def test_audio_trimming_cannot_silently_cancel_output_repetition(self):
        spec = self.spec('local-card-118'); graph = read(runtime.template_path(spec))
        graph['24']['inputs']['trim_to_audio'] = True
        with self.assertRaisesRegex(ValueError, '音频裁切'):
            apply_flash_control_projection(graph, spec, {'24:loop_count': 1})
        self.assertEqual(apply_flash_control_projection(graph, spec, {'24:loop_count': 0})['24']['inputs']['trim_to_audio'], True)

    def test_geometry_zero_or_one_zero_preserves_source_aspect_and_native_alignment(self):
        for wid, policy in POLICIES.items():
            spec = self.spec(wid)
            self.assertIsNone(derive_flash_processing_geometry(spec, {}, 1920, 1080))
            for width, height, expected in ((640, 0, (640, 360)), (0, 720, (1280, 720)), (640, 480, (640, 480))):
                with self.subTest(wid=wid, width=width, height=height):
                    geometry = derive_flash_processing_geometry(spec, {policy['loader'] + ':custom_width': width,
                                                                       policy['loader'] + ':custom_height': height}, 1920, 1080)
                    multiple = policy['multiple'] if policy['resize'] or policy.get('padNode') else 1
                    if policy.get('padNode'):
                        expected = (expected[0] + 648, expected[1])
                        aligned_expected = tuple(v // multiple * multiple for v in expected)
                    else:
                        aligned_expected = tuple(((v + multiple - 1) // multiple) * multiple for v in expected)
                    self.assertEqual((geometry['width'], geometry['height']),
                                     aligned_expected)
                    self.assertFalse(geometry['isFinalOutputSize'])
                    if width and height:
                        self.assertEqual(geometry['crop'], {'x': 240., 'y': 0., 'width': 1440., 'height': 1080.})

    def test_ltx_multiple_resize_chain_cannot_silently_override_custom_size(self):
        for wid in ('local-card-44', 'local-card-45', 'local-card-46'):
            spec = self.spec(wid); policy = POLICIES[wid]; original = read(runtime.template_path(spec))
            for node, key, value in [(policy['intermediate'], 'resize_type.multiplier', 2),
                                      (policy['roundNode'], 'resize_type.multiple', 64)]:
                graph = copy.deepcopy(original); graph[node]['inputs'][key] = value
                with self.subTest(wid=wid, key=key), self.assertRaisesRegex(ValueError, 'LTX'):
                    apply_flash_control_projection(graph, spec, {})

    def test_outpaint_dimensions_add_preserved_edges_and_reject_native_latent_overflow(self):
        spec = self.spec('local-card-46')
        values = {'5141:custom_width': 640, '5141:custom_height': 480,
                  '5149:left': 64, '5149:right': 96, '5149:top': 32, '5149:bottom': 0}
        graph = self.build(spec, values)
        self.assertEqual(tuple(graph['5149']['inputs'][axis] for axis in ('left', 'right', 'top', 'bottom')), (64, 96, 32, 0))
        geometry = derive_flash_processing_geometry(spec, values, 1920, 1080)
        self.assertEqual((geometry['width'], geometry['height']), (800, 512))
        values['5149:left'] = 16384
        with self.assertRaisesRegex(ValueError, '合计'):
            derive_flash_processing_geometry(spec, values, 1920, 1080)
        graph = read(runtime.template_path(spec)); graph['5149']['inputs']['target_width'] = 512
        with self.assertRaisesRegex(ValueError, '额外尺寸覆盖'):
            apply_flash_control_projection(graph, spec, {})

    def test_extreme_aspect_zero_rounding_and_h3_native_minimum_reject(self):
        spec = self.spec('local-card-118')
        with self.assertRaisesRegex(ValueError, '组合过小'):
            derive_flash_processing_geometry(spec, {'13:custom_width': 8}, 8192, 8)
        spec = self.spec('local-card-60')
        geometry = derive_flash_processing_geometry(spec, {'359:custom_width': 8, '359:custom_height': 8}, 1920, 1080)
        self.assertEqual((geometry['width'], geometry['height']), (32, 32))

    def test_flash_native_128_pixel_target_does_not_accept_impossible_small_frames(self):
        spec = self.spec('local-card-118')
        with self.assertRaisesRegex(ValueError, '128'):
            self.build(spec, {'13:custom_width': 32, '13:custom_height': 32})
        spec = self.spec('local-card-120')
        graph = self.build(spec, {'18:custom_width': 32, '18:custom_height': 32})
        self.assertEqual(graph['18']['inputs']['custom_width'], 32)

    def test_other_workflows_are_untouched_and_saved_templates_never_change(self):
        cfg = {'controls': [], 'sourceHash': 'untouched'}
        self.assertEqual(reviewed_flash_config('local-card-51', cfg), cfg)
        graph = {'a': {'inputs': {'width': 0}}}; spec = {'id': 'local-card-51'}
        self.assertIs(apply_flash_control_projection(graph, spec, {}), graph)
        for wid in POLICIES:
            spec = self.spec(wid); path = runtime.template_path(spec); before = path.read_bytes()
            self.build(spec, {})
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
