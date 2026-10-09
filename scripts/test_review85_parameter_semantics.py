"""Focused CPU tests of display-only hiding and corrected native parameter units.

Exercise the production browser snapshot plus actual Python graph binding. No
uploads, card requests, generations, or production file writes occur here.
"""
import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'private/workflow-parameter-review-2026-10-08'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from adapters import CATALOG_WORKFLOWS, build_graph, settings_for
from review85_parameter_semantics import PATCHES, reviewed_parameter_semantics
from review86_h3_controls import MODES as H3_MODES
from review86_ltx_controls import POLICIES as LTX_POLICIES
from review86_scail_controls import CONTRACTS as SCAIL_CONTRACTS
from schema_adapters import build, manifest, validate_values


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


class Review85ParameterSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = load(REVIEW/'before-interfaces.json')['workflows']
        cls.ui = load(ROOT/'public/workflow-interfaces.json')['workflows']

    def field(self, wid, fid, config=None):
        return next(f for f in (config or self.ui[wid])['controls'] if f['id'] == fid)

    def browser_snapshot(self, wid, history=None):
        """Use the shipped JS snapshot builder, including hidden controls."""
        script = r"""
import fs from 'node:fs';
import {prepareCatalogSnapshot} from './public/catalog-ui.js';
import {catalogSubmission,catalogHistorySnapshot} from './public/catalog-submission.js';
const [wid,history]=JSON.parse(process.argv[1]);
const cfg=JSON.parse(fs.readFileSync('public/workflow-interfaces.json','utf8')).workflows[wid];
const w={id:wid,fields:[],interface:cfg,catalogConnection:{adapter:'legacy'}};
const d={prompt:'safe CPU binding example',catalogSeedModes:{}};
if(history)Object.assign(d,catalogHistorySnapshot(w,{settings:history,prompt:d.prompt,negative:''}));
for(const field of cfg.controls.filter(f=>f.kind==='seed')){
 d.catalogSeedModes[field.id]='fixed';
 d.catalogValues={...(d.catalogValues||{}),[field.id]:history?.[field.key]??321};
}
prepareCatalogSnapshot(w,d);
console.log(JSON.stringify(catalogSubmission(w,d)));
"""
        result = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps([wid, history])], cwd=ROOT, text=True, capture_output=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def legacy_graph(self, wid, values):
        w = next(w for w in CATALOG_WORKFLOWS if w['id'] == wid)
        supplied = {f['key']: values[f['id']] for f in self.ui[wid]['controls'] if f['id'] in values}
        settings = settings_for(w, supplied)
        refs = [{'id': 'cpu-reference', 'kind': 'image', 'remote': 'cpu-reference.png'}] if wid == 'local-card-13' else []
        return build_graph(wid, 'safe CPU binding example', '', settings, refs, 'review85-cpu'), settings

    def test_hidden_default_and_history_survive_browser_then_actual_adapter(self):
        cases = [
            ('local-card-85', '55:scale_by', None, 1.5, '55', 'scale_by'),
            ('local-card-85', '55:scale_by', {'scale_by': 1.25, 'size': '512x512', 'seed': 123, 'refine_seed': 456}, 1.25, '55', 'scale_by'),
            ('local-card-13', '131:scale_to_length', None, self.field('local-card-13', '131:scale_to_length')['value'], '131', 'scale_to_length'),
            ('local-card-13', '131:scale_to_length', {'output_long_side': 1024, 'seed': 789}, 1024, '131', 'scale_to_length'),
        ]
        for wid, fid, history, expected, nid, key in cases:
            with self.subTest(workflow=wid, history=history):
                self.assertTrue(self.field(wid, fid)['hidden'])
                payload = self.browser_snapshot(wid, history)
                self.assertEqual(payload['catalog_values'][fid], expected)
                graph, settings = self.legacy_graph(wid, payload['catalog_values'])
                self.assertEqual(graph[nid]['inputs'][key], expected)
                if history:
                    self.assertEqual(settings['seed'], history['seed'])

    def test_megapixels_half_and_tile_count_write_distinct_actual_nodes(self):
        for wid, mp, tiles in (('local-card-90', '88', '85'), ('local-card-91', '24', '25'), ('local-card-92', '79', '76')):
            with self.subTest(workflow=wid):
                spec = copy.deepcopy(manifest(wid))
                # Isolate the production value binding from assets/API prerequisites.
                spec.update(texts=[], media=[], apiProfiles=[])
                supplied = {f['id']: 321 for f in spec['controls'] if f.get('kind') == 'seed'}
                supplied.update({mp+':megapixels': .5, tiles+':width_factor': 3, tiles+':height_factor': 2})
                graph, values, _ = build(spec, supplied, {}, {}, {}, 'review85-cpu-mp')
                self.assertEqual(graph[mp]['inputs']['megapixels'], .5)
                self.assertEqual(graph[tiles]['inputs']['width_factor'], 3)
                self.assertEqual(graph[tiles]['inputs']['height_factor'], 2)
                self.assertEqual(values[mp+':megapixels'], .5)
                self.assertEqual(graph[mp]['class_type'], 'ImageScaleToTotalPixels')
                self.assertEqual(graph[tiles]['class_type'], 'TTP_Tile_image_size')

    def test_native_bad_megapixels_and_fractional_tiles_fail_before_graph_execution(self):
        spec = copy.deepcopy(manifest('local-card-90'))
        for values in ({'88:megapixels': .001}, {'88:megapixels': 16.01}, {'85:width_factor': 1.5}, {'85:height_factor': 11}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_values(spec, values)

    def test_every_patch_preserves_defaults_keys_bindings_and_derived_fields(self):
        protected = ('id', 'key', 'value', 'targets', 'derived', 'members', 'presets')
        for wid in {p['workflow_id'] for p in PATCHES}:
            original = copy.deepcopy(self.before[wid])
            snapshot = copy.deepcopy(original)
            result = reviewed_parameter_semantics({'id': wid}, original)
            self.assertEqual(original, snapshot, f'{wid} caller object mutated')
            self.assertEqual(len(result['controls']), len(original['controls']))
            for old, new in zip(original['controls'], result['controls']):
                with self.subTest(workflow=wid, field=old['id']):
                    for key in protected:
                        self.assertEqual(new.get(key), old.get(key), f'{wid}:{old["id"]}:{key}')
                    self.assertEqual([o.get('value') if isinstance(o, dict) else o for o in new.get('options', [])],
                                     [o.get('value') if isinstance(o, dict) else o for o in old.get('options', [])])
            for patch in (p for p in PATCHES if p['workflow_id'] == wid):
                self.assertFalse(set(patch['set']) & set(protected))

    def test_source_hash_or_port_drift_fails_closed_without_mutation(self):
        for mutate in ('hash', 'target', 'duplicate'):
            config = copy.deepcopy(self.before['local-card-85'])
            if mutate == 'hash':
                config['sourceHash'] = '0' * 64
            elif mutate == 'target':
                self.field('local-card-85', '55:scale_by', config)['targets'] = [{'node': 'wrong', 'input': 'scale_by'}]
            else:
                config['controls'].append(copy.deepcopy(self.field('local-card-85', '55:scale_by', config)))
            before = copy.deepcopy(config)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                reviewed_parameter_semantics({'id': 'local-card-85'}, config)
            self.assertEqual(config, before)

    def test_post_build_public_and_compiled_values_keys_targets_derived_preserved(self):
        current_registry = load(ROOT/'workflows/compiled-registry.json')['workflows']
        old_registry = load(REVIEW/'before-registry.json')['workflows']
        approved_additions = {}
        for wid, route in H3_MODES.items():
            approved_additions.setdefault(wid, set()).add(route[0]+':value')
        for wid, policy in LTX_POLICIES.items():
            approved_additions.setdefault(wid, set()).update(
                policy[key] for key in ('widthId', 'heightId', 'scaleId') if policy.get(key))
        for wid, contract in SCAIL_CONTRACTS.items():
            approved_additions.setdefault(wid, set()).update(
                contract['embeds']+':'+axis for axis in ('width', 'height'))
            if contract.get('mode_source'):
                approved_additions[wid].add(contract['mode_source']+':value')
        from review87_video_controls import POLICIES as VIDEO_POLICIES, reviewed_video_controls
        from review87_flash_controls import POLICIES as FLASH_POLICIES, reviewed_flash_controls
        from review87_infinite_controls import CONTRACTS as INFINITE_CONTRACTS, loop_field, SPEAKER_CONTROL_ID
        for wid in VIDEO_POLICIES:
            approved_additions.setdefault(wid,set()).update(f['id'] for f in reviewed_video_controls(wid))
        for wid in FLASH_POLICIES:
            approved_additions.setdefault(wid,set()).update(f['id'] for f in reviewed_flash_controls(wid))
        for wid in INFINITE_CONTRACTS:
            approved_additions.setdefault(wid,set()).add(loop_field(wid)['id'])
        approved_additions.setdefault('local-card-101',set()).add(SPEAKER_CONTROL_ID)
        for before, current in ((self.before, self.ui), (old_registry, current_registry)):
            for wid, old_cfg in before.items():
                if wid not in current:
                    continue
                old_fields = {f['id']: f for f in old_cfg.get('controls', [])}
                new_fields = {f['id']: f for f in current[wid].get('controls', [])}
                self.assertEqual(set(old_fields)-set(new_fields), set(), wid)
                self.assertEqual(set(new_fields)-set(old_fields),
                                 approved_additions.get(wid, set())-set(old_fields), wid)
                for fid, old in old_fields.items():
                    with self.subTest(workflow=wid, field=fid):
                        for key in ('key', 'value', 'targets', 'derived', 'members', 'presets'):
                            self.assertEqual(new_fields[fid].get(key), old.get(key), f'{wid}:{fid}:{key}')
                        self.assertEqual([o.get('value') if isinstance(o, dict) else o for o in new_fields[fid].get('options', [])],
                                         [o.get('value') if isinstance(o, dict) else o for o in old.get('options', [])])

    def test_original_api_templates_are_byte_identical_after_compile(self):
        before = load(REVIEW/'before-template-hashes.json')
        for relative, digest in before.items():
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main(verbosity=2)
