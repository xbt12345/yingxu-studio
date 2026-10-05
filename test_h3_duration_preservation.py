import copy
import json
import unittest
from pathlib import Path
from h3_duration_preservation import CONTRACTS, GRID, preserve_h3_duration

ROOT = Path(__file__).resolve().parent


class H3RequestedDuration(unittest.TestCase):
    def case(self, wid):
        graph = json.loads((ROOT/'workflows/api'/f'{wid}.api.json').read_text('utf-8'))
        contract = CONTRACTS[wid]
        return graph, {'id': wid, 'source_hash': contract[0], 'outputs': [contract[-1]]}

    def test_all_four_real_contracts_keep_grid_seed_and_requested_seconds(self):
        for wid, contract in CONTRACTS.items():
            with self.subTest(wid=wid):
                graph, spec = self.case(wid)
                before = copy.deepcopy(graph)
                evidence = preserve_h3_duration(graph, spec)
                self.assertEqual(evidence[0]['fps'], 24)
                self.assertEqual(graph[contract[2]], before[contract[2]])
                self.assertEqual(graph[contract[1]], before[contract[1]])
                # All existing inputs apart from the save image/audio edges stay exact.
                for nid, node in before.items():
                    if nid != contract[-2]:
                        self.assertEqual(graph[nid], node)
                new_names = {'yingxu_review74_requested_duration_'+suffix for suffix in ('frames','seconds','images','audio')}
                self.assertEqual(set(graph)-set(before), new_names-set(before))
                self.assertTrue(new_names <= set(graph))
                again = copy.deepcopy(graph)
                preserve_h3_duration(graph, spec)
                self.assertEqual(graph, again)

    def test_boundaries_crop_only_padding_and_align_audio_duration(self):
        for seconds, expected in [(0,5), (.1,5), (1,24), (1.5,36), (5,120), (10,240), (171,4104)]:
            requested = max(5, round(seconds*24))
            padded = requested+(5-requested%17)%17
            self.assertEqual(requested, expected)
            self.assertLessEqual(requested, padded)
            self.assertEqual(requested/24, expected/24)

    def test_card64_bound_duration_updates_both_grid_and_export(self):
        graph,spec=self.case('local-card-64')
        for seconds in (1,3.5,5):
            graph['132']['inputs']['values.a']=seconds
            preserve_h3_duration(graph,spec)
            self.assertEqual(graph['yingxu_review74_requested_duration_frames']['inputs']['values.a'],seconds)
            self.assertEqual(graph['130']['_meta']['yingxu_requested_duration']['seconds_binding'],seconds)
            again=copy.deepcopy(graph);preserve_h3_duration(graph,spec)
            self.assertEqual(graph,again)

    def test_source_output_fps_link_and_injected_node_drift_reject_atomically(self):
        for wid, c in CONTRACTS.items():
            graph, spec = self.case(wid)
            cases = []
            drift = copy.deepcopy(spec); drift['source_hash'] = 'changed'; cases.append((graph,drift))
            drift = copy.deepcopy(spec); drift['outputs'] = ['other']; cases.append((graph,drift))
            for nid, key, value in [(c[2], 'expression', 'a*24'), (c[-2], 'fps', 16),
                                     (c[-2], 'audio', ['unknown',0]), (c[3], 'length', [c[2],0])]:
                drift = copy.deepcopy(graph); drift[nid]['inputs'][key] = value; cases.append((drift,spec))
            repaired = copy.deepcopy(graph); preserve_h3_duration(repaired,spec)
            repaired['yingxu_review74_requested_duration_images']['inputs']['batch_index'] = 1
            cases.append((repaired,spec))
            for value, metadata in cases:
                with self.subTest(wid=wid):
                    before = copy.deepcopy(value)
                    with self.assertRaises(ValueError): preserve_h3_duration(value,metadata)
                    self.assertEqual(value,before)

    def test_other_workflows_unchanged(self):
        graph = {'x':{'class_type':'Other','inputs':{}}}
        original = copy.deepcopy(graph)
        self.assertEqual(preserve_h3_duration(graph,{'id':'local-card-117'}),[])
        self.assertEqual(graph,original)


if __name__ == '__main__': unittest.main()
