"""Real local FFmpeg audio/video loop tests and source-contract failure tests."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import av
import numpy as np
import schema_adapters as runtime
from scripts.review87_flash_controls import POLICIES, reviewed_flash_controls, finalize_flash_schema
from scripts.review87_output_loops import (
    MARKER, prepare_output_loops, output_loop_native_values, repeat_output_if_needed,
    _media_info,
)


class OutputLoopsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = shutil.which('ffmpeg')
        cls.folder_context = tempfile.TemporaryDirectory(prefix='output-loop-tests-')
        cls.folder = Path(cls.folder_context.name)
        cls.lossless = cls.folder / 'source-ffv1.mkv'
        cls.silent = cls.folder / 'silent.mp4'
        cls.audible = cls.folder / 'audible.mp4'
        if cls.ffmpeg:
            def generate(arguments):
                subprocess.run([cls.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', *arguments], capture_output=True, check=True)
            generate(['-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=4:duration=2',
                      '-c:v', 'ffv1', str(cls.lossless)])
            generate(['-i', str(cls.lossless), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(cls.silent)])
            generate(['-i', str(cls.lossless), '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=8000:duration=2',
                      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.audible)])

    @classmethod
    def tearDownClass(cls):
        cls.folder_context.cleanup()

    def contract(self, wid='local-card-118'):
        spec = copy.deepcopy(runtime.manifest(wid))
        fields = {field['id'] for field in spec['controls']}
        spec['controls'] += [copy.deepcopy(field) for field in reviewed_flash_controls(wid) if field['id'] not in fields]
        graph = json.loads(runtime.template_path(spec).read_text('utf-8-sig'))
        return finalize_flash_schema(spec, template=graph), graph

    def marked(self, repeats=1):
        spec, graph = self.contract()
        return spec, prepare_output_loops(spec, graph, {'24:loop_count': repeats})

    def copy_media(self, source, name):
        if not self.ffmpeg:
            self.skipTest('FFmpeg is unavailable; source/contract tests still run.')
        destination = self.folder / name
        shutil.copyfile(source, destination)
        return destination

    def test_zero_default_leaves_native_graph_and_missing_media_untouched(self):
        spec, graph = self.contract(); before = copy.deepcopy(graph)
        ready = prepare_output_loops(spec, graph, {'24:loop_count': 0})
        self.assertEqual(graph, before)
        self.assertEqual(ready, before)
        self.assertFalse(repeat_output_if_needed(spec, ready, '24', self.folder / 'nonexistent.part'))

    def test_native_values_are_separate_from_requested_ui_and_markers_are_idempotent(self):
        spec, graph = self.contract()
        values = {'24:loop_count': 2, '13:custom_width': 640}
        before = copy.deepcopy(values)
        native = output_loop_native_values(spec, values)
        self.assertEqual(values, before)
        self.assertEqual(native, {'24:loop_count': 0, '13:custom_width': 640})
        ready = prepare_output_loops(spec, graph, values)
        self.assertEqual(ready['24']['inputs']['loop_count'], 0)
        self.assertEqual(ready['24']['_meta'][MARKER]['extra_repeats'], 2)
        self.assertEqual(prepare_output_loops(spec, ready, values), ready)
        self.assertEqual(prepare_output_loops(spec, ready, {}), ready)
        reset = prepare_output_loops(spec, ready, {'24:loop_count': 0})
        self.assertNotIn(MARKER, reset['24']['_meta'])

    def test_every_flash_output_maps_to_exact_real_loop_targets(self):
        for wid, policy in POLICIES.items():
            with self.subTest(wid=wid):
                spec, graph = self.contract(wid)
                ready = prepare_output_loops(spec, graph, {policy['sinks'][0] + ':loop_count': 3})
                for sink in policy['sinks']:
                    self.assertEqual(ready[sink]['inputs']['loop_count'], 0)
                    self.assertEqual(ready[sink]['_meta'][MARKER]['extra_repeats'], 3)

    def test_bernini_and_all_four_digital_human_contracts_prepare_real_output_nodes(self):
        from scripts.review87_infinite_controls import CONTRACTS, OUTPUT_LOOP_POLICIES, loop_field
        from scripts.review87_video_controls import reviewed_video_controls, finalize_video_schema
        for wid in ['local-card-5', *CONTRACTS]:
            with self.subTest(wid=wid):
                spec = copy.deepcopy(runtime.manifest(wid))
                self.assertIsNotNone(spec)
                graph = json.loads(runtime.template_path(spec).read_text('utf-8-sig'))
                if wid == 'local-card-5':
                    fields = {f['id'] for f in spec['controls']}
                    spec['controls'] += [f for f in reviewed_video_controls(wid) if f['id'] not in fields]
                    spec = finalize_video_schema(spec, template=graph)
                    control = '395:loop_count'
                else:
                    field = loop_field(wid)
                    spec['controls'] = [f for f in spec['controls'] if f['id'] != field['id']] + [field]
                    spec['outputLoopPolicies'] = copy.deepcopy(OUTPUT_LOOP_POLICIES[wid])
                    control = field['id']
                ready = prepare_output_loops(spec, graph, {control: 1})
                for target in next(f for f in spec['controls'] if f['id'] == control)['targets']:
                    self.assertEqual(ready[target['node']]['inputs']['loop_count'], 0)
                    self.assertEqual(ready[target['node']]['_meta'][MARKER]['extra_repeats'], 1)

    def test_dict_and_list_metadata_shapes_are_supported(self):
        spec, graph = self.contract()
        list_result = prepare_output_loops(spec, graph, {'24:loop_count': 1})
        one = copy.deepcopy(spec); one['outputLoopPolicies'] = one['outputLoopPolicies'][0]
        self.assertEqual(prepare_output_loops(one, graph, {'24:loop_count': 1}), list_result)
        mapped = copy.deepcopy(spec); mapped['outputLoopPolicies'] = {'24': mapped['outputLoopPolicies'][0]}
        self.assertEqual(prepare_output_loops(mapped, graph, {'24:loop_count': 1}), list_result)

    def test_hash_metadata_native_binding_audio_and_marker_drift_reject(self):
        spec, graph = self.contract()
        variants = []
        wrong = copy.deepcopy(spec); wrong['source_hash'] = '0' * 64; variants.append((wrong, graph))
        wrong = copy.deepcopy(spec); wrong['outputLoopPolicies'][0]['audioLink'] = ['13', 0]; variants.append((wrong, graph))
        wrong = copy.deepcopy(spec); wrong['outputLoopPolicies'][0]['sink'] = '13'; variants.append((wrong, graph))
        wrong = copy.deepcopy(spec)
        next(field for field in wrong['controls'] if field['id'] == '24:loop_count')['targets'] = [{'node': '13', 'input': 'loop_count'}]
        variants.append((wrong, graph))
        changed = copy.deepcopy(graph); changed['24']['inputs']['format'] = 'image/gif'; variants.append((spec, changed))
        changed = copy.deepcopy(graph); changed['24']['inputs']['audio'] = ['13', 0]; variants.append((spec, changed))
        changed = copy.deepcopy(graph); changed['24']['inputs']['trim_to_audio'] = True; variants.append((spec, changed))
        _, changed = self.marked(); changed['24']['_meta'][MARKER]['source_hash'] = '0' * 64; variants.append((spec, changed))
        for index, (bad_spec, bad_graph) in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                prepare_output_loops(bad_spec, bad_graph, {'24:loop_count': 1})

    def test_invalid_loop_values_reject(self):
        spec, graph = self.contract()
        for value in (-1, 101, True, 1.5, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prepare_output_loops(spec, graph, {'24:loop_count': value})
            with self.subTest(native=value), self.assertRaises(ValueError):
                output_loop_native_values(spec, {'24:loop_count': value})

    def test_silent_mp4_repeats_with_exact_frame_count_without_reencoding(self):
        path = self.copy_media(self.silent, 'silent-download.part')
        spec, graph = self.marked(2)
        before = _media_info(path)
        result = repeat_output_if_needed(spec, graph, '24', path, ffmpeg=self.ffmpeg)
        after = _media_info(path)
        self.assertEqual(after['frames'], before['frames'] * 3)
        self.assertEqual(after['codec'], before['codec'])
        self.assertEqual(after['audioStreams'], 0)
        self.assertAlmostEqual(after['duration'], 6, delta=.35)
        self.assertTrue(result['streamCopy'])
        self.assertFalse(result['audioRepeated'])

    def test_audible_mp4_repeats_sound_in_the_second_half(self):
        path = self.copy_media(self.audible, 'audible-download.part')
        spec, graph = self.marked(1)
        before = _media_info(path)
        result = repeat_output_if_needed(spec, graph, '24', path, ffmpeg=self.ffmpeg)
        after = _media_info(path)
        self.assertEqual(after['frames'], before['frames'] * 2)
        self.assertEqual(after['audioStreams'], 1)
        self.assertTrue(result['audioRepeated'])
        samples = []
        with av.open(str(path)) as container:
            for frame in container.decode(audio=0):
                if frame.time is not None and 2.4 <= frame.time <= 3.4:
                    samples.append(frame.to_ndarray().astype(np.float64))
        self.assertTrue(samples, 'No audio decoded in the repeated half.')
        self.assertGreater(float(np.sqrt(np.mean(np.concatenate(samples, axis=1) ** 2))), .01)

    def test_large_repeat_rejects_before_work_and_original_bytes_stay_identical(self):
        path = self.copy_media(self.audible, 'oversize.part')
        spec, graph = self.marked(100)
        before = path.read_bytes()
        with patch('scripts.review87_output_loops.subprocess.run') as process:
            with self.assertRaisesRegex(ValueError, '预计超过'):
                repeat_output_if_needed(spec, graph, '24', path, max_bytes=len(before) * 100)
            process.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.folder.glob(path.name + '.repeat-*')), [])

    def test_maximum_valid_repeat_keeps_all_frames_despite_aac_packet_padding(self):
        path = self.copy_media(self.audible, 'maximum-repeat.part')
        spec, graph = self.marked(100)
        result = repeat_output_if_needed(spec, graph, '24', path, ffmpeg=self.ffmpeg)
        self.assertEqual(_media_info(path)['frames'], _media_info(self.audible)['frames'] * 101)
        self.assertEqual(result['plays'], 101)

    def test_failed_ffmpeg_cleans_temp_and_preserves_original(self):
        path = self.copy_media(self.silent, 'failure.part'); before = path.read_bytes()
        spec, graph = self.marked(1)
        def fail(arguments, **kwargs):
            Path(arguments[-1]).write_bytes(b'partial failed output')
            return subprocess.CompletedProcess(arguments, 1, b'', b'fake failure')
        with patch('scripts.review87_output_loops.subprocess.run', side_effect=fail):
            with self.assertRaisesRegex(ValueError, '原成片已保留'):
                repeat_output_if_needed(spec, graph, '24', path, ffmpeg=self.ffmpeg)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.folder.glob(path.name + '.repeat-*')), [])

    def test_timeout_retains_original_and_cleans_temporary_file(self):
        path = self.copy_media(self.silent, 'timeout.part'); before = path.read_bytes()
        spec, graph = self.marked(1)
        def expire(arguments, **kwargs):
            Path(arguments[-1]).write_bytes(b'partial timed-out output')
            raise subprocess.TimeoutExpired(arguments, kwargs['timeout'])
        with patch('scripts.review87_output_loops.subprocess.run', side_effect=expire):
            with self.assertRaisesRegex(ValueError, '超时'):
                repeat_output_if_needed(spec, graph, '24', path, ffmpeg=self.ffmpeg)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.folder.glob(path.name + '.repeat-*')), [])

    def test_content_validation_accepts_part_but_rejects_lossless_mkv(self):
        path = self.copy_media(self.lossless, 'wrong-container.part')
        spec, graph = self.marked(1); before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'MP4'):
            repeat_output_if_needed(spec, graph, '24', path, ffmpeg=self.ffmpeg)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_ffmpeg_is_reported_without_modifying_original(self):
        path = self.copy_media(self.silent, 'missing-ffmpeg.part')
        spec, graph = self.marked(1); before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'FFmpeg'):
            repeat_output_if_needed(spec, graph, '24', path, ffmpeg='nonexistent-output-loop-command-87')
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
