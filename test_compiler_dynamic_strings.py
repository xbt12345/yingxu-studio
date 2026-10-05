"""A real JoinStringMulti third input must reach execution and the text binding."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'scripts'))
from compile_card_workflows import Compiler, CompileError


class DynamicStringCompilerTests(unittest.TestCase):
    def source(self, count=3, extra_name='string_3', extra_type='STRING', connected=True):
        schemas = {
            'Text Multiline': {'input': {'required': {'text': ['STRING', {'default': ''}]}}, 'output': ['STRING']},
            'JoinStringMulti': {'input': {
                'required': {'inputcount': ['INT', {'default': 2, 'min': 2, 'max': 1000}],
                             'string_1': ['STRING', {'default': '', 'forceInput': True}],
                             'delimiter': ['STRING', {'default': ' '}], 'return_list': ['BOOLEAN', {'default': False}]},
                'optional': {'string_2': ['STRING', {'default': '', 'forceInput': True}]}}, 'output': ['STRING']},
        }
        texts = [{'id': i, 'type': 'Text Multiline', 'mode': 0,
                  'inputs': [{'name': 'text', 'type': 'STRING', 'widget': {'name': 'text'}, 'link': None}],
                  'widgets_values': [text], 'outputs': [{'name': 'STRING', 'type': 'STRING', 'links': [i]}]}
                 for i, text in enumerate(('original role', 'batch task', 'user creative requirement'), 1)]
        join = {'id': 4, 'type': 'JoinStringMulti', 'mode': 0,
                'inputs': [{'name': 'string_1', 'type': 'STRING', 'link': 1},
                           {'name': 'string_2', 'type': 'STRING', 'link': 2},
                           {'name': 'inputcount', 'type': 'INT', 'widget': {'name': 'inputcount'}, 'link': None},
                           {'name': 'delimiter', 'type': 'STRING', 'widget': {'name': 'delimiter'}, 'link': None},
                           {'name': 'return_list', 'type': 'BOOLEAN', 'widget': {'name': 'return_list'}, 'link': None},
                           {'name': extra_name, 'type': extra_type, 'link': 3 if connected else None}],
                'widgets_values': [count, ' ', False, None], 'outputs': [{'name': 'string', 'type': 'STRING', 'links': []}]}
        raw = {'nodes': texts + [join], 'links': [[1, 1, 0, 4, 0, 'STRING'], [2, 2, 0, 4, 1, 'STRING']]}
        if connected: raw['links'].append([3, 3, 0, 4, 5, extra_type])
        return raw, schemas

    def test_third_creative_input_survives_and_is_editable_without_changing_source(self):
        raw, schemas = self.source(); original = copy.deepcopy(raw)
        compiler = Compiler(raw, schemas); compiler.compile_node('4')
        self.assertEqual(compiler.compiled['4']['inputs']['string_3'], ['3', 0])
        self.assertEqual(compiler.compiled['3']['inputs']['text'], 'user creative requirement')
        self.assertEqual(compiler.targets('3', 'text'), [{'node': '3', 'input': 'text'}])
        self.assertEqual(compiler.input_spec({'node': '4', 'input': 'string_3'})[0], 'STRING')
        self.assertEqual(raw, original)

    def test_only_source_connected_strings_are_materialized(self):
        raw, schemas = self.source(connected=False)
        compiler = Compiler(raw, schemas); compiler.compile_node('4')
        self.assertNotIn('string_3', compiler.compiled['4']['inputs'])
        self.assertNotIn('3', compiler.compiled)
        self.assertEqual(compiler.compiled['4']['inputs']['inputcount'], 3)
        # Missing optional strings are skipped by the real KJ combine method.
        raw, schemas = self.source(count=4, extra_name='string_4')
        compiler = Compiler(raw, schemas); compiler.compile_node('4')
        self.assertEqual(compiler.compiled['4']['inputs']['string_4'], ['3', 0])
        self.assertNotIn('string_3', compiler.compiled['4']['inputs'])

    def test_unknown_count_socket_and_schema_drift_are_rejected(self):
        for count in (2, 0, 1001, True, 3.0, '3'):
            raw, schemas = self.source(count=count)
            with self.subTest(count=count), self.assertRaises(CompileError):
                Compiler(raw, schemas).compile_node('4')
        for name, typ in [('string_0', 'STRING'), ('string_03', 'STRING'), ('string_4', 'STRING'),
                          ('string_unbounded', 'STRING'), ('string_3', 'IMAGE')]:
            raw, schemas = self.source(extra_name=name, extra_type=typ)
            with self.subTest(name=name, typ=typ), self.assertRaises(CompileError):
                Compiler(raw, schemas).compile_node('4')
        for mutation in ('max', 'prototype', 'linked-count'):
            raw, schemas = self.source()
            if mutation == 'max': schemas['JoinStringMulti']['input']['required']['inputcount'][1]['max'] = 10000
            if mutation == 'prototype': schemas['JoinStringMulti']['input']['optional']['string_2'][0] = 'IMAGE'
            if mutation == 'linked-count': raw['nodes'][-1]['inputs'][2]['link'] = 7
            with self.subTest(mutation=mutation), self.assertRaises(CompileError):
                Compiler(raw, schemas).compile_node('4')

    def test_other_node_class_does_not_gain_dynamic_kwargs(self):
        raw, schemas = self.source()
        schemas['UnreviewedJoin'] = schemas.pop('JoinStringMulti')
        raw['nodes'][-1]['type'] = 'UnreviewedJoin'
        compiler = Compiler(raw, schemas); compiler.compile_node('4')
        self.assertNotIn('string_3', compiler.compiled['4']['inputs'])

    def test_all_six_saved_third_string_links_and_source_hashes_are_preserved(self):
        meta_path = ROOT / 'private/review72/object_info.json'
        audit_path = ROOT / 'verification/catalog-audit.json'
        if not meta_path.exists() or not audit_path.exists():
            self.skipTest('Owner source and installed registry snapshots are private local evidence.')
        schemas = json.loads(meta_path.read_text('utf-8-sig'))
        sources = {item['id']: item for item in json.loads(audit_path.read_text('utf-8')) if 'id' in item}
        for wid, nid in [('local-card-34', '1496'), ('local-card-34', '1528'),
                         ('local-card-79', '26'), ('local-card-80', '83'),
                         ('local-card-81', '270'), ('local-card-89', '42')]:
            path = Path(sources[wid]['source'])
            original = path.read_bytes(); raw = json.loads(original.decode('utf-8-sig'))
            compiler = Compiler(raw, schemas); compiler.compile_node(nid)
            with self.subTest(workflow=wid, node=nid):
                self.assertEqual(compiler.compiled[nid]['inputs']['inputcount'], 3)
                link = compiler.compiled[nid]['inputs']['string_3']
                self.assertIsInstance(link, list)
                self.assertIn(link[0], compiler.compiled)
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(original).digest())


if __name__ == '__main__': unittest.main()
