"""CPU-only contract tests. No build writes, server lifecycle, API, or GPU."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from build_workflow_interfaces import Graph
from review75_generation_sizes import (CONTRACTS, LEGACY, LAYER, MP, UPSCALE,
    reviewed_generation_sizes, generation_size_settings, _execution_template)
from adapters import WORKFLOWS, CATALOG_WORKFLOWS, settings_for, build_graph
from schema_adapters import manifest, build


class GenerationSizeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = {x['id']: x for x in json.loads((ROOT / 'verification/catalog-audit.json').read_text('utf-8-sig')) if x.get('id')}
        cls.forms = json.loads((ROOT / 'public/workflow-interfaces.json').read_text('utf-8-sig'))['workflows']
        cls.workflows = {w['id']: w for w in WORKFLOWS + CATALOG_WORKFLOWS}

    def source(self, wid):
        path = Path(self.catalog[wid]['source']); raw = path.read_bytes()
        return Graph(json.loads(raw.decode('utf-8-sig'))), hashlib.sha256(raw).hexdigest(), path, raw

    def fresh(self, wid, controls=None):
        graph, sha, _, _ = self.source(wid)
        return reviewed_generation_sizes({'id': wid}, controls or [], graph=graph, source_hash=sha)

    def test_all_actual_sources_fresh_curated_idempotent_defaults_units_and_old_fields_unchanged(self):
        for wid, contract in CONTRACTS.items():
            with self.subTest(workflow=wid):
                graph, sha, path, original = self.source(wid)
                self.assertEqual(sha, contract['hash'])
                graph_before = copy.deepcopy(graph.__dict__)
                sentinel = {'id': 'unrelated', 'targets': [{'node': 'unchanged', 'input': 'untouched'}], 'value': 'sentinel'}
                fresh = reviewed_generation_sizes({'id': wid}, [sentinel], graph=graph, source_hash=sha)
                self.assertEqual(fresh[0], sentinel)
                self.assertEqual(graph.__dict__, graph_before)
                for definition, field in zip(contract['fields'], fresh[1:]):
                    self.assertEqual(field, definition['field'])
                    self.assertLessEqual(len(field['help']), 12)
                    self.assertEqual(field['unit'], 'MP' if field['node'] == MP else '倍' if field['node'] == UPSCALE else '千像素' if definition['side'] == 'total_pixel(kilo pixel)' else 'px')
                    self.assertEqual(field['value'], _execution_template(wid)[field['nodeId']]['inputs'][field['targets'][0]['input']])
                derived = {'sourceHash': sha, 'controls': fresh}
                curated = reviewed_generation_sizes({'id': wid}, [sentinel], source_hash=sha, derived=derived)
                self.assertEqual(curated, fresh)
                self.assertEqual(reviewed_generation_sizes({'id': wid}, curated, source_hash=sha, derived=derived), fresh)
                self.assertEqual(path.read_bytes(), original)

    def test_hash_default_mode_units_rounding_targets_and_curated_proof_fail_closed(self):
        for wid, contract in CONTRACTS.items():
            graph, sha, _, _ = self.source(wid)
            field = contract['fields'][0]['field']; nid = field['nodeId']; native_key = field['targets'][0]['input']
            with self.subTest(wid=wid), self.assertRaises(ValueError):
                reviewed_generation_sizes({'id': wid}, [], graph=graph, source_hash='drift')
            for change in ('default', 'mode', 'target'):
                altered = copy.deepcopy(graph)
                if change == 'default':
                    values = __import__('build_workflow_interfaces').widget_bindings(altered.nodes[nid])
                    altered.nodes[nid]['widgets_values_named'] = {k: v[0] for k, v in values.items()}
                    altered.nodes[nid]['widgets_values_named'][native_key] = field['value'] + 1
                elif change == 'mode': altered.nodes[nid]['mode'] = 4
                with self.subTest(wid=wid, change=change):
                    if change == 'target':
                        with patch.object(altered, 'targets', return_value=[('wrong', native_key)]), self.assertRaises(ValueError):
                            reviewed_generation_sizes({'id': wid}, [], graph=altered, source_hash=sha)
                    else:
                        with self.assertRaises(ValueError): reviewed_generation_sizes({'id': wid}, [], graph=altered, source_hash=sha)
            fresh = self.fresh(wid)
            for change in ('value', 'targets', 'sourceHash'):
                derived = {'sourceHash': sha, 'controls': copy.deepcopy(fresh)}
                if change == 'sourceHash': derived['sourceHash'] = 'drift'
                elif change == 'targets': derived['controls'][0]['targets'][0]['node'] = 'wrong'
                else: derived['controls'][0]['value'] += 1
                with self.subTest(wid=wid, change=change), self.assertRaises(ValueError):
                    reviewed_generation_sizes({'id': wid}, [], source_hash=sha, derived=derived)
        # Different unit or rounding changes must not silently turn a budget into pixels.
        for key, value in [('scale_to_side', 'shortest'), ('round_to_multiple', '8')]:
            wid = 'local-card-16'; graph, sha, _, _ = self.source(wid)
            node = graph.nodes['38']; values = __import__('build_workflow_interfaces').widget_bindings(node)
            node['widgets_values_named'] = {k: v[0] for k, v in values.items()}; node['widgets_values_named'][key] = value
            with self.subTest(change=key), self.assertRaises(ValueError): reviewed_generation_sizes({'id': wid}, [], graph=graph, source_hash=sha)

    def test_actual_latent_and_saved_output_link_drift_is_rejected(self):
        for wid, contract in CONTRACTS.items():
            graph, sha, _, _ = self.source(wid); template = _execution_template(wid)
            for src, slot, dst, port, typ in (contract['edges'][0], contract['edges'][-1]):
                altered = copy.deepcopy(template); altered[dst]['inputs'][port] = ['different_source', slot]
                with self.subTest(wid=wid, port=port), patch('review75_generation_sizes._execution_template', return_value=altered), self.assertRaises(ValueError):
                    reviewed_generation_sizes({'id': wid}, [], graph=graph, source_hash=sha)

    def test_legacy_new_settings_change_only_the_real_reviewed_target_and_old_ticket_defaults(self):
        counts = {12: 1, 16: 2, 17: 2, 18: 2, 20: 1, 78: 1, 85: 0}
        for wid in sorted(LEGACY):
            number = int(wid.split('-')[-1]); workflow = self.workflows[wid]
            assets = [{'kind': 'image', 'remote': f'owned-{i}.png'} for i in range(counts[number])]
            old = settings_for(workflow, {'seed': 123})
            for definition in CONTRACTS[wid]['fields']: self.assertNotIn(definition['field']['key'], old)
            base = build_graph(wid, 'CPU creative instruction', '', old, assets, 'cpu-same')
            for definition in CONTRACTS[wid]['fields']:
                field = definition['field']; target = field['targets'][0]
                self.assertEqual(base[target['node']]['inputs'][target['input']], field['value'])
                value = 2048 if field['node'] == LAYER else 2
                new = settings_for(workflow, {'seed': 123, field['key']: value})
                changed = build_graph(wid, 'CPU creative instruction', '', new, assets, 'cpu-same')
                self.assertEqual(changed[target['node']]['inputs'][target['input']], value)
                reverted = copy.deepcopy(changed); reverted[target['node']]['inputs'][target['input']] = field['value']
                self.assertEqual(reverted, base)
                same = settings_for(workflow, {'seed': 123, field['key']: field['value']})
                self.assertEqual(build_graph(wid, 'CPU creative instruction', '', same, assets, 'cpu-same'), base)

    def test_legacy_native_ranges_steps_and_nul12_regression(self):
        for wid in LEGACY:
            workflow = self.workflows[wid]
            for definition in CONTRACTS[wid]['fields']:
                field = definition['field']; key = field['key']
                for value in (field['min'], field['value'], field['max']):
                    settings = settings_for(workflow, {'seed': 123, key: value})
                    self.assertEqual(settings[key], value)
                bad = [True, '1024', None, float('nan'), float('inf'), field['min'] - field['step'], field['max'] + field['step']]
                bad += [1024.0] if field.get('integer') else [1.001]
                for value in bad:
                    with self.subTest(wid=wid, key=key, value=str(value)), self.assertRaises(ValueError):
                        settings_for(workflow, {'seed': 123, key: value})
        for key in ('prompt_turn2real', 'prompt_semireal'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                settings_for(self.workflows['local-card-12'], {'seed': 123, key: 'bad\x00prompt', 'output_pixels': 1024})

    def test_generic_compiler_manifest_clone_changes_only_one_true_output_budget(self):
        for wid in sorted(set(CONTRACTS) - LEGACY):
            spec = copy.deepcopy(manifest(wid)); fields = self.fresh(wid)
            # Only clone the new reviewed controls. The current live registry is
            # intentionally not rebuilt here and may lack unrelated in-flight
            # nativeBounds additions for old seconds-to-frame transforms.
            spec['controls'] = copy.deepcopy(fields)
            values = {f['id']: f['value'] for f in spec['controls']}
            texts = {f['id']: 'CPU source creative instruction' for f in spec['texts']}
            media = {f['id']: {'kind': f['kind'], 'remote': f'owned-{f["id"]}.png' if f['kind'] == 'image' else f'owned-{f["id"]}.mp4'} for f in spec['media']}
            baseline, _, _ = build(spec, values, texts, media, {}, 'cpu-budget')
            for field in fields:
                target = field['targets'][0]; changed_values = {**values, field['id']: 2048 if field['node'] == LAYER else 2}
                changed, _, _ = build(spec, changed_values, texts, media, {}, 'cpu-budget')
                self.assertEqual(changed[target['node']]['inputs'][target['input']], changed_values[field['id']])
                changed[target['node']]['inputs'][target['input']] = baseline[target['node']]['inputs'][target['input']]
                self.assertEqual(changed, baseline)

    def test_only_confirmed_output_fields_are_added_not_reference_only_or_inactive_siblings(self):
        prohibited = {'local-card-17': '124:megapixels', 'local-card-18': '123:megapixels',
                      'local-card-85': '70:megapixels', 'local-card-96': '21:megapixels', 'local-card-114': '121:megapixels'}
        for wid, field in prohibited.items(): self.assertNotIn(field, {f['id'] for f in self.fresh(wid)})
        controls = [{'id': 'preserve', 'value': 999}]
        for wid in ('local-card-11', 'local-card-51', 'local-card-124', 'unrelated'):
            self.assertIs(reviewed_generation_sizes({'id': wid}, controls, source_hash='arbitrary'), controls)
        self.assertEqual(generation_size_settings('local-card-11', {'output_pixels': 1024}), {})


if __name__ == '__main__': unittest.main()
