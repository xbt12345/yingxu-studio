"""Check the actual portrait latent choice without building or submitting."""
import copy
import hashlib
import json
import unittest
from pathlib import Path

from build_workflow_interfaces import Graph
from portrait_size_contract import (reviewed_portrait_size_controls,
    PORTRAIT_SIZE_SOURCE_HASH, PORTRAIT_SIZE_SWITCH_ID, PORTRAIT_SIZE_TARGETS,
    PORTRAIT_SIZE_PROOF, CUSTOM_HELP)

ROOT = Path(__file__).resolve().parents[1]


class PortraitSizeContract(unittest.TestCase):
    def setUp(self):
        audit = json.loads((ROOT / 'verification/catalog-audit.json').read_text('utf-8'))
        path = Path(next(row for row in audit if row.get('id') == 'local-card-79')['source'])
        raw = path.read_bytes()
        self.source_hash = hashlib.sha256(raw).hexdigest()
        self.graph = Graph(json.loads(raw.decode('utf-8-sig')))
        self.controls = copy.deepcopy(json.loads((ROOT / 'public/workflow-interfaces.json').read_text('utf-8'))['workflows']['local-card-79']['controls'])
        self.controls = [field for field in self.controls if field['id'] != PORTRAIT_SIZE_SWITCH_ID]
        self.workflow = {'id': 'local-card-79'}

    def test_fresh_and_curated_add_same_false_switch_without_changing_old_values_or_targets(self):
        self.assertEqual(self.source_hash, PORTRAIT_SIZE_SOURCE_HASH)
        graph_before = copy.deepcopy(self.graph.__dict__)
        before = copy.deepcopy(self.controls)
        fresh = reviewed_portrait_size_controls(self.workflow, copy.deepcopy(before),
                                               graph=self.graph, source_hash=self.source_hash)
        switch = next(f for f in fresh if f['id'] == PORTRAIT_SIZE_SWITCH_ID)
        self.assertIs(switch['value'], False)
        self.assertEqual(switch['targets'], PORTRAIT_SIZE_TARGETS)
        self.assertEqual(switch['dimensionSource'], PORTRAIT_SIZE_PROOF)
        self.assertEqual(fresh[fresh.index(switch) + 1]['id'], '486:aspect_ratio')
        self.assertEqual(graph_before, self.graph.__dict__)
        for old in before:
            updated = next(f for f in fresh if f['id'] == old['id'])
            self.assertEqual({k: v for k, v in old.items() if k != 'help'},
                             {k: v for k, v in updated.items() if k != 'help'})
        curated = reviewed_portrait_size_controls(self.workflow, copy.deepcopy(before),
            source_hash=self.source_hash, derived={'sourceHash': self.source_hash, 'controls': fresh})
        self.assertEqual(curated, fresh)
        repeat = reviewed_portrait_size_controls(self.workflow, copy.deepcopy(curated),
            source_hash=self.source_hash, derived={'sourceHash': self.source_hash, 'controls': fresh})
        self.assertEqual(repeat, curated)
        self.assertTrue(all(len(f.get('help', '')) <= 12 for f in fresh))
        self.assertEqual([f['help'] for f in fresh if f['id'] in PORTRAIT_SIZE_PROOF['customControls']], [CUSTOM_HELP, CUSTOM_HELP])

    def test_rejects_hash_default_and_branch_port_drift_before_form_mutation(self):
        with self.assertRaises(ValueError):
            reviewed_portrait_size_controls(self.workflow, self.controls, graph=self.graph, source_hash='drift')
        for dst, key, port in [('sub0/468', 'on_false', 0), ('sub0/468', 'on_true', 2),
                               ('sub0/458', 'latent_image', 1), ('485', 'height', 0)]:
            graph = copy.deepcopy(self.graph)
            slot = next(i for i, value in enumerate(graph.nodes[dst]['inputs']) if value['name'] == key)
            graph.ins[dst] = [(src, port if index == slot else output, index)
                              for src, output, index in graph.ins[dst]]
            before = copy.deepcopy(self.controls)
            with self.subTest(dst=dst, key=key), self.assertRaises(ValueError):
                reviewed_portrait_size_controls(self.workflow, self.controls, graph=graph, source_hash=self.source_hash)
            self.assertEqual(self.controls, before)
        graph = copy.deepcopy(self.graph)
        graph.nodes['485']['widgets_values_named']['switch'] = True
        with self.assertRaises(ValueError):
            reviewed_portrait_size_controls(self.workflow, self.controls, graph=graph, source_hash=self.source_hash)

    def test_curated_requires_verified_fresh_proof_and_public_bindings(self):
        fresh = reviewed_portrait_size_controls(self.workflow, copy.deepcopy(self.controls),
                                               graph=self.graph, source_hash=self.source_hash)
        for changed in ['sourceHash', 'proof', 'target', 'value']:
            derived = {'sourceHash': self.source_hash, 'controls': copy.deepcopy(fresh)}
            switch = next(f for f in derived['controls'] if f['id'] == PORTRAIT_SIZE_SWITCH_ID)
            if changed == 'sourceHash': derived['sourceHash'] = 'drift'
            elif changed == 'proof': switch['dimensionSource']['referenceLongestEdge'] = 1024
            elif changed == 'target': switch['targets'][0]['node'] = 'sub0/456'
            elif changed == 'value': switch['value'] = True
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                reviewed_portrait_size_controls(self.workflow, copy.deepcopy(self.controls),
                    source_hash=self.source_hash, derived=derived)
        controls = copy.deepcopy(self.controls)
        next(f for f in controls if f['id'] == '486:megapixels')['targets'] = [{'node': '485', 'input': 'resolution'}]
        with self.assertRaises(ValueError):
            reviewed_portrait_size_controls(self.workflow, controls, graph=self.graph, source_hash=self.source_hash)
        other = copy.deepcopy(self.controls)
        self.assertIs(reviewed_portrait_size_controls({'id': 'local-card-80'}, other), other)


if __name__ == '__main__':
    unittest.main()
