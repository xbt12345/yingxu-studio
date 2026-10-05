"""Saved dynamic image links must remain connected, in their real source order."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'scripts'))
from compile_card_workflows import Compiler, CompileError, verified_choice_labels


class DynamicImageCompilerTests(unittest.TestCase):
    def source(self, cls='ImageConcatMulti', count=4):
        schemas = {'LoadImage': {'input': {'required': {'image': ['STRING']}}, 'output': ['IMAGE', 'MASK']}}
        if cls == 'ImageConcatMulti':
            schemas[cls] = {'input': {'required': {
                'inputcount': ['INT', {'min': 2, 'max': 1000}],
                'image_1': ['COMFY_MATCHTYPE_V3', {'template': {'template_id': 'multi_image_or_mask', 'allowed_types': 'IMAGE,MASK'}}],
                'direction': ['COMBO', {'options': ['right', 'down', 'left', 'up']}],
                'match_image_size': ['BOOLEAN']}, 'optional': {'image_2': ['IMAGE,MASK', {}]}}, 'output': ['IMAGE']}
            names = [f'image_{i}' for i in range(1, 5)]
            extras = [{'name': key, 'type': typ, 'widget': {'name': key}, 'link': None}
                      for key, typ in [('inputcount', 'INT'), ('direction', 'COMBO'), ('match_image_size', 'BOOLEAN')]]
            values = [count, 'down', True, None]
        else:
            schemas[cls] = {'input': {'optional': {'image1': ['IMAGE']}}, 'output': ['IMAGE']}
            names = [f'image{i}' for i in range(1, 5)]
            extras = []; values = []
        loaders = [{'id': i, 'type': 'LoadImage', 'mode': 0,
                    'inputs': [{'name': 'image', 'type': 'STRING', 'widget': {'name': 'image'}, 'link': None}],
                    'widgets_values': [f'reference-{i}.png'], 'outputs': [{'name': 'IMAGE', 'type': 'IMAGE'}]}
                   for i in range(1, 5)]
        sockets = [{'name': name, 'type': 'IMAGE', 'link': i} for i, name in enumerate(names, 1)]
        node = {'id': 5, 'type': cls, 'mode': 0, 'inputs': sockets + extras,
                'widgets_values': values, 'outputs': [{'name': 'IMAGE', 'type': 'IMAGE'}]}
        raw = {'nodes': loaders + [node], 'links': [[i, i, 0, 5, i - 1, 'IMAGE'] for i in range(1, 5)]}
        return raw, schemas

    def test_concat_preserves_four_real_images_and_source(self):
        raw, schemas = self.source(); before = copy.deepcopy(raw)
        compiler = Compiler(raw, schemas); compiler.compile_node('5')
        inputs = compiler.compiled['5']['inputs']
        self.assertEqual([inputs[f'image_{i}'] for i in range(1, 5)], [[str(i), 0] for i in range(1, 5)])
        self.assertEqual((inputs['inputcount'], inputs['direction'], inputs['match_image_size']), (4, 'down', True))
        self.assertEqual(raw, before)
        # The node's real v3 protocol accepts both MASK and IMAGE extra ports.
        raw['nodes'][-1]['inputs'][2]['type'] = 'MASK'; raw['links'][2][2] = 1
        compiler = Compiler(raw, schemas); compiler.compile_node('5')
        self.assertEqual(compiler.compiled['5']['inputs']['image_3'], ['3', 1])

    def test_concat_does_not_materialize_unconnected_ports(self):
        raw, schemas = self.source(); raw['nodes'][-1]['inputs'][3]['link'] = None
        compiler = Compiler(raw, schemas); compiler.compile_node('5')
        self.assertNotIn('image_4', compiler.compiled['5']['inputs'])
        self.assertEqual(compiler.compiled['5']['inputs']['inputcount'], 4)

    def test_concat_rejects_count_schema_names_types_and_link_drift(self):
        for change in ('count2', 'count1001', 'countbool', 'countlinked', 'prototype', 'matchtype', 'name', 'type', 'link', 'duplicate'):
            raw, schemas = self.source(); node = raw['nodes'][-1]
            if change == 'count2': node['widgets_values'][0] = 2
            if change == 'count1001': node['widgets_values'][0] = 1001
            if change == 'countbool': node['widgets_values'][0] = True
            if change == 'countlinked': node['inputs'][4]['link'] = 1
            if change == 'prototype': schemas['ImageConcatMulti']['input']['optional']['image_2'][0] = 'LATENT'
            if change == 'matchtype': schemas['ImageConcatMulti']['input']['required']['image_1'][1]['template']['allowed_types'] = 'IMAGE'
            if change == 'name': node['inputs'][2]['name'] = 'image_03'
            if change == 'type': node['inputs'][2]['type'] = 'LATENT'
            if change == 'link': raw['links'][2][3] = 999
            if change == 'duplicate': node['inputs'].append(copy.deepcopy(node['inputs'][2]))
            with self.subTest(change=change), self.assertRaises(CompileError):
                Compiler(raw, schemas).compile_node('5')

    def test_impact_preserves_connected_order_and_skips_disabled_optional(self):
        raw, schemas = self.source('ImpactMakeImageBatch'); before = copy.deepcopy(raw)
        raw['nodes'][-1]['inputs'].append({'name': 'image5', 'type': 'IMAGE', 'link': None})
        raw['nodes'][2]['mode'] = 4
        compiler = Compiler(raw, schemas); compiler.compile_node('5')
        inputs = compiler.compiled['5']['inputs']
        self.assertEqual(list(inputs), ['image1', 'image2', 'image4'])
        self.assertEqual(list(inputs.values()), [['1', 0], ['2', 0], ['4', 0]])
        self.assertEqual(before['nodes'][0], raw['nodes'][0])

    def test_impact_rejects_schema_gap_order_type_duplicate_and_link_drift(self):
        for change in ('prototype', 'gap', 'order', 'type', 'duplicate', 'link'):
            raw, schemas = self.source('ImpactMakeImageBatch'); node = raw['nodes'][-1]
            if change == 'prototype': schemas['ImpactMakeImageBatch']['input']['optional']['image1'][0] = 'MASK'
            if change == 'gap': node['inputs'][2]['name'] = 'image30'
            if change == 'order': node['inputs'][1], node['inputs'][2] = node['inputs'][2], node['inputs'][1]
            if change == 'type': node['inputs'][2]['type'] = 'MASK'
            if change == 'duplicate': node['inputs'].append(copy.deepcopy(node['inputs'][2]))
            if change == 'link': raw['links'][2][3] = 999
            with self.subTest(change=change), self.assertRaises(CompileError):
                Compiler(raw, schemas).compile_node('5')

    def test_other_classes_do_not_gain_arbitrary_image_kwargs(self):
        raw, schemas = self.source(); schemas['UnreviewedConcat'] = schemas.pop('ImageConcatMulti')
        raw['nodes'][-1]['type'] = 'UnreviewedConcat'
        compiler = Compiler(raw, schemas); compiler.compile_node('5')
        self.assertNotIn('image_3', compiler.compiled['5']['inputs'])

    def test_readable_choice_labels_require_the_exact_real_menu(self):
        real = ['enable', 'disable']
        labels = [{'value': 'enable', 'label': '启用'}, {'value': 'disable', 'label': '忽略'}]
        result = verified_choice_labels(labels, real)
        self.assertEqual(result, labels)
        result[0]['label'] = 'modified'
        self.assertEqual(labels[0]['label'], '启用')
        for bad in (labels[:1], list(reversed(labels)), labels + [labels[0]],
                    [{'value': 'new', 'label': 'new'}, labels[1]], ['enable', 'disable'],
                    [{'value': 'enable', 'label': 42}, labels[1]]):
            with self.subTest(options=bad):
                self.assertEqual(verified_choice_labels(bad, real), real)
        self.assertEqual(verified_choice_labels([{'value': True, 'label': 'yes'}], [1]), [1])

    def test_legacy_field_type_errors_do_not_blame_missing_models_or_guess_values(self):
        for cls, key, value, choices in [
                ('SeCVideoSegmentation', 'tracking_direction', 1, ['forward', 'backward', 'bidirectional']),
                ('VisionAPIDirect', 'thinking_mode', 8, ['auto', 'off', 'low', 'medium', 'high'])]:
            raw = {'nodes': [{'id': 1, 'type': cls,
                             'inputs': [{'name': key, 'type': 'COMBO', 'widget': {'name': key}, 'link': None}],
                             'widgets_values': [value], 'outputs': [{'name': 'result', 'type': 'STRING'}]}], 'links': []}
            schemas = {cls: {'input': {'required': {key: [choices]}}, 'output': ['STRING']}}
            compiler = Compiler(raw, schemas); compiler.compile_node('1')
            before = copy.deepcopy(compiler.compiled)
            errors = compiler.dependency_errors()
            with self.subTest(cls=cls):
                self.assertEqual(len(errors), 1)
                self.assertIn('widget 序列', errors[0])
                self.assertNotIn('修复算力端模型', errors[0])
                self.assertEqual(compiler.compiled, before)

    def test_all_fifteen_resolvable_source_links_are_restored_without_source_changes(self):
        registry_path = ROOT / 'private/review72/object_info.json'
        audit_path = ROOT / 'verification/catalog-audit.json'
        if not registry_path.exists() or not audit_path.exists():
            self.skipTest('Installed registry and original source evidence are private local files.')
        schemas = json.loads(registry_path.read_text('utf-8-sig'))
        sources = {item['id']: item for item in json.loads(audit_path.read_text('utf-8')) if 'id' in item}
        cases = [(24, '3648', 'image_'), (25, '547', 'image_'), (26, '377', 'image_'),
                 (27, '677', 'image_'), (116, '677', 'image_'), (50, '480', 'image_'),
                 (4, '160', 'image'), (52, '160', 'image')]
        restored = 0
        for wid, nid, prefix in cases:
            path = Path(sources[f'local-card-{wid}']['source']); original = path.read_bytes()
            compiler = Compiler(json.loads(original.decode('utf-8-sig')), schemas); compiler.compile_node(nid)
            inputs = compiler.compiled[nid]['inputs']
            start, end = (2, 3) if prefix == 'image' else (3, 3) if wid == 50 else (3, 4)
            for index in range(start, end + 1):
                with self.subTest(workflow=wid, node=nid, input=prefix + str(index)):
                    self.assertIsInstance(inputs[prefix + str(index)], list)
                    self.assertIn(inputs[prefix + str(index)][0], compiler.compiled)
                    restored += 1
            if prefix == 'image':
                self.assertEqual(list(inputs), ['image1', 'image2', 'image3'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(original).digest())
        self.assertEqual(restored, 15)


if __name__ == '__main__': unittest.main()
