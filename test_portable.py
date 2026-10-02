"""Packaging contracts that must hold on a brand-new checkout."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import configuration
import server
from adapters import build_graph, settings_for
from scripts.check_setup import check_files


class PortableContracts(unittest.TestCase):
    def test_shipped_files_and_template_hashes(self):
        self.assertEqual(len(check_files()), len(server.WORKFLOWS + server.CATALOG_WORKFLOWS))

    def test_demo_never_advertises_remote_generation(self):
        with patch.object(server, 'BASE', ''), patch.object(server.requests, 'get') as remote:
            client = TestClient(server.app)
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
                    if key in ('api_key', 'access_token', 'authorization', 'password', 'secret') and isinstance(value, str):
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


if __name__ == '__main__':
    unittest.main()
