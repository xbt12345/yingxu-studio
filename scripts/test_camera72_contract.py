"""Source/metadata protocol tests only; no builder, server, or GPU calls."""
import copy, hashlib, json, unittest
from pathlib import Path
from build_workflow_interfaces import Graph
from camera72_contract import (reviewed_camera72_controls,CAMERA72_SOURCE_HASH,
    CAMERA72_ORDER,CAMERA72_FIELDS,CAMERA72_SEQUENCE)

ROOT=Path(__file__).resolve().parents[1]


class Camera72ContractTests(unittest.TestCase):
    def setUp(self):
        audit=json.loads((ROOT/'verification/catalog-audit.json').read_text(encoding='utf-8'))
        path=Path(next(r['source'] for r in audit if r.get('id')=='local-card-72'))
        raw=path.read_bytes();self.sha=hashlib.sha256(raw).hexdigest()
        self.graph=Graph(json.loads(raw.decode('utf-8-sig')))
        self.controls=json.loads((ROOT/'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']['local-card-72']['controls']
        self.workflow={'id':'local-card-72'}

    def fresh(self,controls=None,graph=None):
        return reviewed_camera72_controls(self.workflow,controls or copy.deepcopy(self.controls),
                graph=graph or self.graph,source_hash=self.sha)

    def test_source_sequence_and_all_ranges_align_without_value_target_or_group_changes(self):
        self.assertEqual(self.sha,CAMERA72_SOURCE_HASH)
        before=copy.deepcopy(self.controls);source_before=copy.deepcopy(self.graph.__dict__)
        # Include grouping metadata to make preservation explicit.
        for f in before:f['uiGroup']='camera-group' if f.get('kind')=='camera' else 'seed-group'
        fresh=self.fresh(before)
        self.assertEqual(self.controls[3]['id'],fresh[3]['id'])
        self.assertEqual(self.graph.__dict__,source_before)
        order=[f['nodeId'] for f in fresh if f.get('kind')=='camera' and f['key']=='horizontal_angle']
        self.assertEqual(order,list(CAMERA72_ORDER))
        for old in before:
            new=next(f for f in fresh if f['id']==old['id'])
            for key in ('id','value','targets','type','key','nodeId','uiGroup','members','defaultAdjustment','sourceDefault'):
                self.assertEqual(old.get(key),new.get(key),(old['id'],key))
            if old.get('kind')!='camera':self.assertEqual(old,new)
            else:
                self.assertEqual(new['viewIndex'],CAMERA72_ORDER.index(old['nodeId'])+1)
                self.assertEqual(new['cameraSequence'],CAMERA72_SEQUENCE)
                for key in ('min','max','step'):self.assertEqual(new[key],CAMERA72_FIELDS[old['key']][key])

    def test_curated_same_annotations_and_idempotence_require_fresh_proof(self):
        fresh=self.fresh()
        derived={'sourceHash':self.sha,'controls':fresh}
        curated=reviewed_camera72_controls(self.workflow,copy.deepcopy(self.controls),source_hash=self.sha,derived=derived)
        self.assertEqual(curated,fresh)
        self.assertEqual(reviewed_camera72_controls(self.workflow,copy.deepcopy(curated),source_hash=self.sha,derived=derived),fresh)
        for change in ('sourceHash','sequence','view','range','target'):
            d=copy.deepcopy(derived)
            f=next(x for x in d['controls']if x.get('kind')=='camera')
            if change=='sourceHash':d['sourceHash']='drift'
            elif change=='sequence':f['cameraSequence']['firstList']['cameraNodes'].reverse()
            elif change=='view':f['viewIndex']=9
            elif change=='range':f['max']=90
            else:f['targets'][0]['node']='120'
            with self.subTest(change=change),self.assertRaises(ValueError):
                reviewed_camera72_controls(self.workflow,copy.deepcopy(self.controls),source_hash=self.sha,derived=d)

    def test_source_hash_list_positive_and_save_drift_rejected_before_mutation(self):
        with self.assertRaises(ValueError):
            reviewed_camera72_controls(self.workflow,self.controls,graph=self.graph,source_hash='drift')
        for dst,key,source,port in [('137','prompt_1','109',0),('138','optional_prompt_list','137',1),
                ('68','prompt','138',0),('65','positive','71',0),('123','images','68',0)]:
            graph=copy.deepcopy(self.graph)
            slot=next(i for i,f in enumerate(graph.nodes[dst]['inputs'])if f['name']==key)
            graph.ins[dst]=[(source,port,index)if index==slot else (origin,output,index)
                           for origin,output,index in graph.ins[dst]]
            before=copy.deepcopy(self.controls)
            with self.subTest(dst=dst,key=key),self.assertRaises(ValueError):self.fresh(self.controls,graph)
            self.assertEqual(self.controls,before)

    def test_no_guessing_extra_controls_type_bindings_or_legacy_default_clamp(self):
        for change in ('type','target','missing','duplicate'):
            fields=copy.deepcopy(self.controls);f=next(x for x in fields if x.get('kind')=='camera')
            if change=='type':f['type']='text'
            elif change=='target':f['targets'][0]['input']='zoom'
            elif change=='missing':fields.remove(f)
            else:fields.append(copy.deepcopy(f))
            with self.subTest(change=change),self.assertRaises(ValueError):self.fresh(fields)
        fields=copy.deepcopy(self.controls)
        old=next(x for x in fields if x.get('nodeId')=='119' and x['key']=='vertical_angle')
        old['value']=90
        fresh=self.fresh(fields)
        new=next(x for x in fresh if x['id']==old['id'])
        self.assertEqual(new['value'],90)
        self.assertEqual(new['sourceDefaultRangeIssue'],{'value':90,'min':-30,'max':60})
        self.assertIs(reviewed_camera72_controls({'id':'local-card-75'},fields),fields)


if __name__=='__main__':unittest.main()
