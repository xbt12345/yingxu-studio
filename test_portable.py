"""Packaging contracts that must hold on a brand-new checkout."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from test_server_helpers import load_server, authenticated_client
import configuration
import schema_adapters
from adapters import build_graph, settings_for
from scripts.check_setup import check_files
from scripts.review87_infinite_controls import derive_infinite_reference_geometry

server=None


class PortableContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global server
        server,temporary=load_server('yingxu_isolated_portable_backend')
        cls.addClassCleanup(temporary.cleanup)
        import sys
        cls.addClassCleanup(lambda:sys.modules.pop(server.__name__,None))

    def test_shipped_files_and_template_hashes(self):
        shipped = {entry['id'] for entry in check_files()}
        ready = {entry['id'] for entry in schema_adapters.registry().values() if entry['validation'] == 'structural-verified'}
        self.assertEqual(shipped, {entry['id'] for entry in server.WORKFLOWS + server.CATALOG_WORKFLOWS} | ready)

    def test_demo_never_advertises_remote_generation(self):
        with patch.object(server, 'BASE', ''), patch.object(server.requests, 'get') as remote:
            accounts=server.platform_bridge.accounts()
            client=authenticated_client(server,accounts,accounts.bootstrap_admin())
            self.addCleanup(client.close)
            self.assertFalse(client.get('/api/health').json()['configured'])
            self.assertEqual(client.get('/api/workflows').json(), [])
            self.assertEqual(client.get('/api/catalog-connections').json(), [])
            result = client.post('/api/jobs', json={'workflow_id': 'h3-reference', 'prompt': 'test', 'token': 'portable-test-123'})
            self.assertEqual(result.status_code, 503)
            remote.assert_not_called()

    def test_fallback_does_not_require_private_templates(self):
        with patch.object(configuration, 'ROOT', Path('/nonexistent-yingxu-source')):
            for entry in server.WORKFLOWS + server.CATALOG_WORKFLOWS:
                self.assertTrue(configuration.workflow_path(entry['id']).is_file())

    def test_templates_have_no_literal_credentials(self):
        for file in (configuration.ROOT / 'workflows/api').glob('*.json'):
            graph = json.loads(file.read_text('utf-8'))
            for node in graph.values():
                for key, value in node.get('inputs', {}).items():
                    if key.lower() in ('api_key', 'apikey', 'access_token', 'authorization', 'password', 'secret') and isinstance(value, str):
                        self.assertEqual(value, '', file.name)

    def test_all_shipped_graphs_build_without_owner_templates(self):
        with patch.object(configuration, 'ROOT', Path('/nonexistent-yingxu-source')):
            for entry in server.WORKFLOWS + server.CATALOG_WORKFLOWS:
                with self.subTest(workflow=entry['id']):
                    assets = [{'kind': kind, 'remote': f'reference-{i}.{ext}', 'has_edit_mask': True}
                              for kind, count, ext in [('image', entry['minImages'], 'png'), ('video', entry['minVideos'], 'mp4')]
                              for i in range(count)]
                    graph = build_graph(entry['id'], 'A quiet landscape', '', settings_for(entry, {}), assets, 'portable-check')
                    self.assertTrue(graph)
                    for node in graph.values():
                        for value in node['inputs'].values():
                            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                                self.assertIn(value[0], graph)

    def test_generic_templates_build_without_owner_files(self):
        with patch.object(schema_adapters, 'ROOT', Path('/nonexistent-yingxu-source')), patch.object(configuration, 'ROOT', Path('/nonexistent-yingxu-source')):
            for spec in schema_adapters.registry().values():
                if spec['validation'] != 'structural-verified':
                    continue
                with self.subTest(workflow=spec['id']):
                    assets = {slot['id']: {'kind': slot['kind'], 'remote': 'fixture.' + {'image': 'png', 'video': 'mp4', 'audio': 'wav'}[slot['kind']]} for slot in spec['media']}
                    values = {field['id']: -1 for field in spec['controls'] if field['kind'] == 'seed'}
                    # Required per-speaker regions are user input, not a default.
                    # This packaging test supplies two anonymous fixture people.
                    values.update({field['id']: json.dumps([
                        {'x':.05,'y':.05,'width':.4,'height':.9},
                        {'x':.55,'y':.05,'width':.4,'height':.9},
                    ]) for field in spec['controls'] if field['kind'] == 'speaker_regions'})
                    recipe = spec.get('pointsRecipe')
                    geometry = None
                    if recipe:
                        values.update({field['id']: '{"positive":[{"x":0.5,"y":0.5}],"negative":[]}' for field in spec['controls'] if field['kind'] == 'points'})
                        geometry = {'width': 1280, 'height': 736, 'node': recipe['node'], 'negativeTarget': recipe['negativeTarget']}
                    if spec.get('speakerRegionsRecipe'):
                        geometry = derive_infinite_reference_geometry(spec, values, 1280, 736)
                    graph, _, _ = schema_adapters.build(spec, values, {}, assets, {}, 'portable-generic', geometry=geometry)
                    self.assertTrue(graph)
                    for node in graph.values():
                        for value in node['inputs'].values():
                            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                                self.assertIn(value[0], graph)


if __name__ == '__main__':
    unittest.main()
