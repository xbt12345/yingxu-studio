"""Numeric projection tests load no server, database, accounts or provider."""
import ast
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import unittest

ROOT = Path(__file__).resolve().parent
SAFE = 9007199254740991

class BrowserNumericContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'server.py').read_text('utf-8-sig'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'public_schema')
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        namespace = {'copy': copy, 'urlsplit': urlsplit, 'urlunsplit': urlunsplit}
        exec(compile(module, 'server.py:public_schema', 'exec'), namespace)
        cls.project = staticmethod(namespace['public_schema'])

    def test_all_eleven_native_int64_bounds_are_exact_in_the_browser_projection(self):
        registry = json.loads((ROOT / 'workflows/compiled-registry.json').read_text('utf-8'))['workflows']
        affected = ((45, '53:value'), (50, '425:value'), (54, '121:value'), (55, '105:value_1'),
                    (56, '132:value'), (57, '8:value'), (58, '14:value'), (63, '7:value'),
                    (65, '144:value'), (71, '16:value'), (135, '12:widget_2'))
        for number, identifier in affected:
            with self.subTest(workflow=number, field=identifier):
                spec = registry[f'local-card-{number}']
                unchanged = copy.deepcopy(spec)
                native = next(field for field in spec['controls'] if field['id'] == identifier)
                self.assertIs(type(native['max']), int)
                self.assertGreater(native['max'], SAFE)
                visible = next(field for field in self.project(spec)['controls'] if field['id'] == identifier)
                self.assertEqual(visible['max'], SAFE)
                self.assertEqual(visible['value'], native['value'])
                self.assertEqual(visible.get('step'), native.get('step'))
                self.assertEqual(visible.get('integer'), native.get('integer'))
                self.assertEqual(spec, unchanged)

    def test_float_ranges_and_fractional_seconds_are_preserved(self):
        spec = {'controls': [dict(id='float', type='number', max=1e18, min=0, step=.1, value=1.5),
                             dict(id='int', type='number', min=-(2**63), max=2**63-1,
                                  customRange=dict(min=-(2**63), max=2**63-1, step=1))],
                'texts': [], 'media': []}
        controls = self.project(spec)['controls']
        self.assertEqual(controls[0]['max'], 1e18)
        self.assertEqual(controls[0]['step'], .1)
        self.assertEqual(controls[0]['value'], 1.5)
        self.assertEqual((controls[1]['min'], controls[1]['max']), (-SAFE, SAFE))
        self.assertEqual(controls[1]['customRange'], dict(min=-SAFE, max=SAFE, step=1))

if __name__ == '__main__':
    unittest.main()
