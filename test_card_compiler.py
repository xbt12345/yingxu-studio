"""Regression checks for graph conversion without submitting GPU jobs."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
from compile_card_workflows import Compiler, CompileError, sanitize


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.schemas = {
            'Source': {'input': {'required': {'value': ['STRING', {'default': ''}]}}, 'output': ['STRING']},
            'SaveImage': {'input': {'required': {'images': ['STRING']}}, 'output': [], 'output_node': True},
        }

    def test_real_link_id_overrides_stale_slot_metadata(self):
        raw = {'nodes': [
            {'id': 1, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['x']},
            {'id': 2, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 22}]},
        ], 'links': [[22, 1, 0, 2, 1, 'STRING']]}
        compiler = Compiler(raw, self.schemas)
        self.assertEqual(compiler.outputs('image'), ['2'])
        self.assertEqual(compiler.compiled['2']['inputs']['images'], ['1', 0])

    def test_missing_node_is_blocked_instead_of_replaced(self):
        raw = {'nodes': [{'id': 1, 'type': 'MissingSaveImage'}], 'links': []}
        with self.assertRaisesRegex(CompileError, 'Card node unavailable'):
            Compiler(raw, self.schemas).outputs('image')

    def test_disabled_subgraph_does_not_emit_child_results(self):
        definition = {'id': 'off', 'nodes': [{'id': 5, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'widget': {'name': 'images'}}], 'widgets_values': ['disabled output']}], 'links': []}
        raw = {'nodes': [
            {'id': 1, 'type': 'off', 'mode': 4},
            {'id': 2, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'widget': {'name': 'images'}}], 'widgets_values': ['active output']},
        ], 'links': [], 'definitions': {'subgraphs': [definition]}}
        compiler = Compiler(raw, self.schemas)
        self.assertEqual(compiler.outputs('image'), ['2'])
        self.assertNotIn('1:5', compiler.compiled)

    def test_saved_boolean_and_number_widgets_have_current_api_types(self):
        schema = {'Int': {'input': {'required': {'Number': ['STRING']}}},
                  'WanVideoSampler': {'input': {'required': {'batched_cfg': ['BOOLEAN', {'default': False}]}}}}
        raw = {'nodes': [
            {'id': 1, 'type': 'Int', 'inputs': [{'name': 'Number', 'widget': {'name': 'Number'}}], 'widgets_values': [81]},
            {'id': 2, 'type': 'WanVideoSampler', 'inputs': [{'name': 'batched_cfg', 'widget': {'name': 'batched_cfg'}}], 'widgets_values': ['']},
        ], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('1'); compiler.compile_node('2')
        self.assertEqual(compiler.compiled['1']['inputs']['Number'], '81')
        self.assertIs(compiler.compiled['2']['inputs']['batched_cfg'], False)
        self.assertEqual(len(compiler.normalized), 2)

    def test_legacy_one_guide_socket_keeps_its_reference_link(self):
        schema = {**self.schemas, 'LTXVAddGuideMulti': {'input': {'required': {
            'num_guides': ['COMFY_DYNAMICCOMBO_V3', {'options': [{'key': '1', 'inputs': {'required': {
                'image_1': ['STRING'], 'frame_idx_1': ['INT', {'default': 0}], 'strength_1': ['FLOAT', {'default': 1.0}]}}}]}]}}}}
        raw = {'nodes': [
            {'id': 1, 'type': 'Source', 'inputs': [{'name': 'value', 'widget': {'name': 'value'}}], 'widgets_values': ['reference']},
            {'id': 2, 'type': 'LTXVAddGuideMulti', 'inputs': [{'name': 'num_guides', 'widget': {'name': 'num_guides'}}, {'name': 'image_1', 'link': 9}], 'widgets_values': [0]},
        ], 'links': [[9, 1, 0, 2, 1, 'STRING']]}
        compiler = Compiler(raw, schema)
        compiler.compile_node('2')
        self.assertEqual(compiler.compiled['2']['inputs']['num_guides'], '1')
        self.assertEqual(compiler.compiled['2']['inputs']['num_guides.image_1'], ['1', 0])

    def test_upstream_chat_rename_preserves_prompt_names_and_output_slots(self):
        schema = {'VisionChat': {'input': {'required': {
            'system_prompt': ['STRING'], 'prompt': ['STRING'], 'thinking_mode': [['auto', 'off', 'medium']]}},
            'output': ['STRING', 'STRING', 'STRING', 'STRING']}}
        raw = {'nodes': [{'id': 2, 'type': 'MultimodalChat', 'inputs': [
            {'name': 'prompt', 'widget': {'name': 'prompt'}},
            {'name': 'system_prompt', 'widget': {'name': 'system_prompt'}},
            {'name': 'thinking_mode', 'widget': {'name': 'thinking_mode'}},
        ], 'widgets_values': ['user instruction', 'system instruction', 'thinking']}], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('2')
        migrated = compiler.compiled['2']
        self.assertEqual(migrated['class_type'], 'VisionChat')
        self.assertEqual(migrated['inputs']['prompt'], 'user instruction')
        self.assertEqual(migrated['inputs']['system_prompt'], 'system instruction')
        self.assertEqual(migrated['inputs']['thinking_mode'], 'medium')
        self.assertEqual(raw['nodes'][0]['type'], 'MultimodalChat')

    def test_rename_does_not_override_an_available_original_class(self):
        schema = {name: {'input': {'required': {'prompt': ['STRING']}}} for name in ('MultimodalChat', 'VisionChat')}
        raw = {'nodes': [{'id': 2, 'type': 'MultimodalChat', 'inputs': [{'name': 'prompt', 'widget': {'name': 'prompt'}}], 'widgets_values': ['original']}], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('2')
        self.assertEqual(compiler.compiled['2']['class_type'], 'MultimodalChat')
        self.assertEqual(compiler.normalized, [])

    def test_dynamic_subgraph_instance_ids_keep_independent_inputs(self):
        definition = {'id': 'def', 'nodes': [
            {'id': 5, 'type': 'SaveImage', 'inputs': [{'name': 'images', 'link': 10}]},
        ], 'links': [[10, -10, 0, 5, 0, 'STRING'], [11, 5, 0, -20, 0, 'STRING']]}
        raw = {'nodes': [
            {'id': 1, 'type': 'def', 'inputs': [{'name': 'input', 'widget': {'name': 'input'}}], 'widgets_values': ['a']},
            {'id': 2, 'type': 'def', 'inputs': [{'name': 'input', 'widget': {'name': 'input'}}], 'widgets_values': ['b']},
        ], 'links': [], 'definitions': {'subgraphs': [definition]}}
        compiler = Compiler(raw, self.schemas)
        compiler.outputs('image')
        self.assertEqual(compiler.compiled['1:5']['inputs']['images'], 'a')
        self.assertEqual(compiler.compiled['2:5']['inputs']['images'], 'b')

    def test_dependency_path_repair_requires_exact_unique_basename(self):
        schema = {'Model': {'input': {'required': {'lora_name': [['new/same.safetensors', 'other/model.safetensors']]}}}}
        raw = {'nodes': [{'id': 1, 'type': 'Model', 'inputs': [{'name': 'lora_name', 'widget': {'name': 'lora_name'}}], 'widgets_values': ['old/same.safetensors']}], 'links': []}
        compiler = Compiler(raw, schema)
        compiler.compile_node('1')
        self.assertEqual(compiler.dependency_errors(), [])
        self.assertEqual(compiler.compiled['1']['inputs']['lora_name'], 'new/same.safetensors')
        ambiguous = copy.deepcopy(schema)
        ambiguous['Model']['input']['required']['lora_name'][0].append('another/same.safetensors')
        compiler = Compiler(raw, ambiguous)
        compiler.compile_node('1')
        self.assertEqual(len(compiler.dependency_errors()), 1)

    def test_export_removes_linked_keys_media_and_saved_point_state(self):
        graph = {
            'key': {'class_type': 'Source', 'inputs': {'value': 'private-key'}},
            'api': {'class_type': 'API', 'inputs': {'apikey': ['key', 0], 'prompt': 'private prompt'}},
            'video': {'class_type': 'Video', 'inputs': {'video': 'personal.mp4'}},
            'points': {'class_type': 'PointsEditor', 'inputs': {'points_store': '{"positive":[1]}', 'coordinates': '[1]', 'neg_coordinates': '[2]', 'bbox_store': '[3]', 'bboxes': '[4]'}},
        }
        cleaned = sanitize(graph, [{'targets': [{'node': 'api', 'input': 'prompt'}]}], [{'targets': [{'node': 'video', 'input': 'video'}]}])
        self.assertEqual(cleaned['key']['inputs']['value'], '')
        self.assertEqual(cleaned['api']['inputs']['prompt'], '')
        self.assertEqual(cleaned['video']['inputs']['video'], '')
        self.assertEqual(cleaned['points']['inputs']['points_store'], '{"positive":[],"negative":[]}')
        self.assertEqual(cleaned['points']['inputs']['bboxes'], '[]')
        self.assertEqual(graph['key']['inputs']['value'], 'private-key')


if __name__ == '__main__':
    unittest.main()
