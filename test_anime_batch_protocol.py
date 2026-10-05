"""Offline response framing checks; live registered-node/GPU gates stay separate."""
import copy
import json
import re
import unittest
from pathlib import Path

from anime_batch_protocol import (AnimeBatchProtocolError, FORMAT_NODE, PROMPT_NODE,
    RESPONSE_NODE, ROLE_NODE, SOURCE_HASH, STATE_KEY, VALID_NODE, batch_pattern,
    repair_anime_batch_protocol)


class AnimeBatchProtocolTests(unittest.TestCase):
    def source(self, count=2):
        graph=json.loads((Path(__file__).parent/'workflows/api/local-card-80.api.json').read_text('utf-8'))
        graph['85']['inputs']['int_']=count
        graph['87']['inputs']['max_count']=count
        return graph, {'id':'local-card-80','source_hash':SOURCE_HASH,'outputs':['64']}

    def test_exact_number_of_nonempty_prompts_is_required(self):
        for count,text in ((1,'One adult blue-sweater portrait.'),(2,'First safe adult portrait.|Second safe adult portrait.'),
                           (3,' One. | Two. | Three. '),(2,'One with\nsoft light.|Two with gray backdrop.')):
            with self.subTest(count=count,text=text):self.assertTrue(re.search(batch_pattern(count),text))
        for count,text in ((2,'One.'),(2,'One.|Two.|Three.'),(2,'One.\nNext Scene: Two.'),
                           (2,'One.| '),(2,' |Two.'),(3,'One.||Three.'),(1,''),(1,' \n\t'),
                           (2,'COMPILATION_ERROR: no reference.|not a prompt'),(1,'error: not a prompt')):
            with self.subTest(count=count,text=text):self.assertIsNone(re.search(batch_pattern(count),text))
        for count in (None,0,1001,True,2.0,'2'):
            with self.assertRaises(AnimeBatchProtocolError):batch_pattern(count)

    def test_only_roles_and_split_are_redirected_and_original_response_remains_visible(self):
        graph,spec=self.source();before=copy.deepcopy(graph)
        evidence=repair_anime_batch_protocol(spec,graph)
        self.assertEqual(evidence['count'],2)
        self.assertEqual(graph['146']['inputs']['role'],[ROLE_NODE,0])
        self.assertEqual(graph['87']['inputs']['text'],[PROMPT_NODE,0])
        self.assertEqual(graph[RESPONSE_NODE]['inputs'],{'text':['146',0]})
        self.assertEqual(graph[VALID_NODE]['inputs']['regex_pattern'],batch_pattern(2))
        self.assertEqual(graph[PROMPT_NODE]['inputs'],{'continue':[VALID_NODE,0],'in':[RESPONSE_NODE,0]})
        for nid,value in before.items():
            if nid in (FORMAT_NODE,ROLE_NODE,RESPONSE_NODE,VALID_NODE,PROMPT_NODE):continue
            for key,original in value['inputs'].items():
                if (nid,key)in(('146','role'),('87','text')):continue
                self.assertTrue(graph[nid]['inputs'][key]==original,(nid,key))
        self.assertEqual(graph['91'],before['91'])
        self.assertEqual(graph['96'],before['96'])
        self.assertEqual(graph['83'],before['83'])
        self.assertEqual(graph['64'],before['64'])

    def test_saved_rerun_and_legitimate_bound_count_change_are_supported(self):
        graph,spec=self.source(1);repair_anime_batch_protocol(spec,graph)
        before=copy.deepcopy(graph);repair_anime_batch_protocol(spec,graph)
        self.assertTrue(graph==before)

    def test_original_linked_count_source_resolves_the_same_public_control(self):
        graph,spec=self.source()
        graph['88']={'class_type':'ImpactInt','inputs':{'value':2}}
        graph['85']['inputs']['int_']=['88',0]
        graph['87']['inputs']['max_count']=['88',0]
        before=copy.deepcopy(graph)
        evidence=repair_anime_batch_protocol(spec,graph)
        self.assertEqual(evidence['count'],2)
        self.assertEqual(graph['88'],before['88'])
        self.assertEqual(graph['85']['inputs']['int_'],['88',0])
        self.assertEqual(graph['87']['inputs']['max_count'],['88',0])
        graph['85']['inputs']['int_']=3;graph['87']['inputs']['max_count']=3
        repair_anime_batch_protocol(spec,graph)
        self.assertEqual(graph['146']['_meta'][STATE_KEY]['count'],3)
        self.assertEqual(graph[VALID_NODE]['inputs']['regex_pattern'],batch_pattern(3))
        self.assertIn('恰好 3 条',graph[FORMAT_NODE]['inputs']['text'])
        before=copy.deepcopy(graph);repair_anime_batch_protocol(spec,graph)
        self.assertTrue(graph==before)

    def test_drift_rejection_is_atomic_and_does_not_print_credentials(self):
        graph,spec=self.source()
        for mutation in ('source','outputs','split','count-mismatch','role','consumer','protocol','metadata','extra-input'):
            with self.subTest(mutation=mutation):
                changed=copy.deepcopy(graph);contract=copy.deepcopy(spec)
                if mutation=='source':contract['source_hash']='unknown'
                if mutation=='outputs':contract['outputs']=['other']
                if mutation=='split':changed['87']['inputs']['delimiter']='\n'
                if mutation=='count-mismatch':changed['85']['inputs']['int_']=3
                if mutation=='role':changed['146']['inputs']['role']='unreviewed'
                if mutation=='consumer':changed['45']['inputs']['prompt']=['146',0]
                if mutation in ('protocol','metadata','extra-input'):
                    repair_anime_batch_protocol(contract,changed)
                    if mutation=='protocol':changed[VALID_NODE]['inputs']['regex_pattern']='.*'
                    if mutation=='metadata':changed['146']['_meta'][STATE_KEY]['source_hash']='changed'
                    if mutation=='extra-input':changed[VALID_NODE]['inputs']['unreviewed_option']=True
                before=copy.deepcopy(changed)
                with self.assertRaises(AnimeBatchProtocolError):repair_anime_batch_protocol(contract,changed)
                self.assertTrue(changed==before)
        other=copy.deepcopy(graph)
        self.assertIsNone(repair_anime_batch_protocol({'id':'unreviewed'},other))
        self.assertTrue(other==graph)

    def test_generated_nodes_match_saved_installed_input_and_output_contracts(self):
        snapshot=Path(__file__).parent/'private/review72/object_info.json'
        if not snapshot.exists():self.skipTest('安装节点快照只在本地验收工作区保存。')
        registered=json.loads(snapshot.read_text('utf-8-sig'))
        graph,spec=self.source();original_ids=set(graph);repair_anime_batch_protocol(spec,graph)
        for nid in set(graph)-original_ids:
            node=graph[nid];schema=registered[node['class_type']]['input']
            known={**schema.get('required',{}),**schema.get('optional',{})}
            self.assertTrue(set(node['inputs'])<=set(known),(nid,list(node['inputs'])))
            self.assertTrue(set(schema.get('required',{}))<=set(node['inputs']),nid)
        self.assertEqual(registered['RegexMatch']['output'],['BOOLEAN'])
        self.assertEqual(registered['TextSplitByDelimiter']['output'],['STRING'])
        self.assertEqual(registered['TextSplitByDelimiter']['output_is_list'],[True])


if __name__=='__main__':unittest.main()
