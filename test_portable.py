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


def text_value(graph, value, outputs=None):
    """Evaluate only the shipped string plumbing, never a model/API node."""
    if not isinstance(value, list):
        return str(value)
    node_id, output = value
    if outputs and node_id in outputs:
        return outputs[node_id][output]
    node = graph[node_id]
    fields = node['inputs']
    resolve = lambda item: text_value(graph, item, outputs)
    if node['class_type'] == 'PrimitiveStringMultiline':
        return fields['value']
    if node['class_type'] == 'StringReplace':
        return resolve(fields['string']).replace(resolve(fields['find']), resolve(fields['replace']))
    if node['class_type'] == 'PreviewAny':
        return resolve(fields['source'])
    if node['class_type'] == 'StringConcatenate':
        return resolve(fields['string_a']) + fields['delimiter'] + resolve(fields['string_b'])
    if node['class_type'] == 'JoinStringMulti':
        return fields['delimiter'].join(resolve(fields['string_'+str(index)])
                                         for index in range(1, fields['inputcount'] + 1))
    raise AssertionError('Unexpected text plumbing: '+node['class_type'])


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

    def shipped_graph(self, identifier, prompt='a copper observatory above the clouds', negative=''):
        entry = next(item for item in server.WORKFLOWS + server.CATALOG_WORKFLOWS if item['id'] == identifier)
        assets = [{'kind':kind, 'remote':f'anonymous-{index}.{extension}', 'has_edit_mask':True}
                  for kind, count, extension in [('image', entry['minImages'], 'png'),
                                                  ('video', entry['minVideos'], 'mp4')]
                  for index in range(count)]
        with patch.object(configuration, 'ROOT', Path('/nonexistent-yingxu-source')):
            return build_graph(identifier, prompt, negative, settings_for(entry, {}), assets, 'portable-text')

    def test_clean_ideogram_templates_deliver_user_idea_and_ratio_to_the_llm(self):
        prompt = 'a copper observatory above the clouds'
        for identifier, prefix, llm in [('local-card-105', '186:', '190'), ('local-card-106', '134:', '178')]:
            with self.subTest(workflow=identifier):
                graph = self.shipped_graph(identifier, prompt)
                rendered = text_value(graph, graph[llm]['inputs']['prompt'],
                    {prefix+'164':['640'], prefix+'165':['360']})
                self.assertIn('User idea: '+prompt, rendered)
                self.assertIn('TARGET IMAGE ASPECT RATIO: 640:360', rendered)
                self.assertIn('"compositional_deconstruction"', rendered)
                self.assertNotIn('{{original_prompt}}', rendered)
                self.assertNotIn('{{width}}', rendered)
                self.assertNotIn('{{height}}', rendered)

    def test_clean_krea_template_keeps_optimizer_rules_separate_from_the_user_prompt(self):
        prompt = 'a copper observatory above the clouds'
        graph = self.shipped_graph('local-card-108', prompt)
        rendered = text_value(graph, graph['60']['inputs']['prompt'])
        self.assertIn('Then output a single expanded prompt paragraph.', rendered)
        self.assertTrue(rendered.endswith("User's Input:\n\n"+prompt))
        self.assertEqual(prompt, text_value(graph, graph['65']['inputs']['on_false']))

    def test_clean_anime_conversion_retains_image_description_instructions_but_no_saved_results(self):
        graph = self.shipped_graph('local-card-82')
        role = text_value(graph, graph['161']['inputs']['role'])
        self.assertIn('中文提示词', role)
        self.assertIn('400字以内', role)
        self.assertEqual('', graph['164']['inputs']['text_0'])
        self.assertEqual('', graph['166']['inputs']['text'])

    def test_clean_anima_template_preserves_quality_defaults_and_explicit_negative_override(self):
        graph = self.shipped_graph('local-card-85')
        self.assertIn('best quality', text_value(graph, ['46', 0]))
        self.assertIn('watermark', graph['66']['inputs']['text'])
        overridden = self.shipped_graph('local-card-85', negative='visible compression blocks')
        self.assertEqual('visible compression blocks', overridden['66']['inputs']['text'])

    def test_clean_locator_templates_keep_default_targets_until_explicitly_changed(self):
        locators = [('local-card-24', '3724', 'human', '3720'),
                    ('local-card-25', '623', 'human', '619'),
                    ('local-card-27', '753', 'cloths', '749'),
                    ('local-card-28', '443', 'human', '433'),
                    ('local-card-116', '753', 'cloths', '749')]
        with patch.object(schema_adapters, 'ROOT', Path('/nonexistent-yingxu-source')), patch.object(configuration, 'ROOT', Path('/nonexistent-yingxu-source')):
            for identifier, node, default, consumer in locators:
                spec = schema_adapters.manifest(identifier)
                records = {slot['id']: {'kind':slot['kind'], 'remote':'anonymous.' +
                    {'image':'png', 'video':'mp4', 'audio':'wav'}[slot['kind']]} for slot in spec['media']}
                seeds = {field['id']:0 for field in spec['controls'] if field.get('kind') == 'seed'}
                for supplied, expected in [(None, default), ('', default), (' \t ', default), ('red jacket', 'red jacket')]:
                    with self.subTest(workflow=identifier, supplied=supplied):
                        texts = {} if supplied is None else {node+':value':supplied}
                        graph, _, _ = schema_adapters.build(spec, seeds, texts, records, {},
                            'portable-locator', prompt='Preserve the original motion and background.')
                        self.assertEqual(graph[node]['inputs']['value'], expected)
                        self.assertEqual(graph[consumer]['inputs']['prompt'], [node, 0])

    def test_recompiling_locator_templates_uses_generic_targets_without_saved_user_text(self):
        import sys
        with patch.object(sys, 'path', [str(configuration.ROOT / 'scripts'), *sys.path]):
            from scripts.compile_card_workflows import sanitize
        for identifier, node, expected in [('local-card-24', '3724', 'human'),
                                           ('local-card-25', '623', 'human'),
                                           ('local-card-27', '753', 'cloths'),
                                           ('local-card-28', '443', 'human'),
                                           ('local-card-116', '753', 'cloths')]:
            with self.subTest(workflow=identifier):
                spec = schema_adapters.manifest(identifier)
                graph = json.loads((configuration.ROOT / 'workflows/api' / spec['template']).read_text('utf-8'))
                graph[node]['inputs']['value'] = 'owner-specific target from saved footage'
                sanitized = sanitize(graph, spec['texts'], spec['media'], workflow_id=identifier)
                self.assertEqual(sanitized[node]['inputs']['value'], expected)
                self.assertEqual(graph[node]['inputs']['value'], 'owner-specific target from saved footage')
                unknown = sanitize(graph, spec['texts'], spec['media'], workflow_id='unknown-workflow')
                self.assertEqual(unknown[node]['inputs']['value'], '')


if __name__ == '__main__':
    unittest.main()
