"""Source, native-range, and actual CPU binding tests; never submits a job."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from build_workflow_interfaces import Graph
from reviewed_stage_seeds import reviewed_stage_seeds,STAGE_SEEDS,SEEDVR_MAX,RGTHREE_SEED_MAX
from adapters import manifest as adapter_manifest,settings_for,build_graph,workflow_path
from schema_adapters import manifest,build,validate_values


class ReviewedStageSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit={row['id']:row for row in json.loads((ROOT/'verification/catalog-audit.json').read_text(encoding='utf-8'))if 'id'in row}
        cls.public=json.loads((ROOT/'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']
        cls.node_info=json.loads((ROOT/'private/review72/object_info.json').read_text(encoding='utf-8'))

    def data(self,wid):
        path=Path(self.audit[wid]['source']);raw=path.read_bytes()
        return path,raw,hashlib.sha256(raw).hexdigest(),Graph(json.loads(raw.decode('utf-8-sig'))),copy.deepcopy(self.public[wid]['controls'])

    def fresh(self,wid):
        path,raw,sha,graph,controls=self.data(wid)
        return reviewed_stage_seeds({'id':wid},controls,graph=graph,source_hash=sha)

    def test_source_defaults_targets_order_fresh_curated_and_idempotence(self):
        for wid,contract in STAGE_SEEDS.items():
            with self.subTest(wid=wid):
                path,raw,sha,graph,controls=self.data(wid);before=copy.deepcopy(graph.__dict__)
                self.assertEqual(sha,contract['sourceHash'])
                fresh=reviewed_stage_seeds({'id':wid},controls,graph=graph,source_hash=sha)
                ids=[node+':'+key for node,key,*_ in contract['stages']]
                fields=[c for c in fresh if c['id']in ids]
                self.assertEqual([f['id']for f in fields],ids)
                for field,(nid,key,public_key,typ,value,label,maximum)in zip(fields,contract['stages']):
                    self.assertEqual((field['nodeId'],field['key'],field['value'],field['label']),(nid,public_key,value,label))
                    self.assertEqual(field['targets'],[{'node':nid,'input':key}])
                    self.assertEqual(field['members'],[{'id':nid+':'+key,'nodeId':nid,'key':key,'targets':field['targets']}])
                    self.assertEqual((field['min'],field['max'],field['step']),(0,maximum,1))
                derived={'sourceHash':sha,'controls':fresh}
                self.assertEqual(reviewed_stage_seeds({'id':wid},controls,source_hash=sha,derived=derived),fresh)
                self.assertEqual(reviewed_stage_seeds({'id':wid},fresh,source_hash=sha,derived=derived),fresh)
                self.assertEqual(reviewed_stage_seeds({'id':wid},fresh,source_hash=sha,graph=graph),fresh)
                self.assertEqual(graph.__dict__,before);self.assertEqual(path.read_bytes(),raw)

    def test_native_seed_range_and_per_stage_randomization(self):
        for wid,contract in STAGE_SEEDS.items():
            fresh=self.fresh(wid);ids={n+':'+k for n,k,*_ in contract['stages']}
            fields=[f for f in fresh if f['id']in ids];spec={'controls':fields}
            for field,stage in zip(fields,contract['stages']):
                native=self.node_info[stage[3]]['input']['required'][stage[1]]
                self.assertEqual(native[0],'INT')
                self.assertGreaterEqual(field['min'],native[1]['min'])
                self.assertLessEqual(field['max'],native[1]['max'])
                self.assertTrue(field['min']<=field['value']<=field['max'])
                with self.subTest(wid=wid,field=field['id']):
                    self.assertEqual(validate_values(spec,{field['id']:field['max']})[field['id']],field['max'])
                    with self.assertRaises(ValueError):validate_values(spec,{field['id']:field['max']+1})
                    with patch('schema_adapters.secrets.randbelow',side_effect=lambda n:n-1):
                        value=validate_values(spec,{field['id']:-1})[field['id']]
                    self.assertEqual(value,field['max'])

    def test_source_hash_default_inactive_edge_and_curated_drift_fail_closed(self):
        for wid,contract in STAGE_SEEDS.items():
            _,_,sha,graph,controls=self.data(wid)
            with self.subTest(wid=wid),self.assertRaises(ValueError):
                reviewed_stage_seeds({'id':wid},controls,graph=graph,source_hash='drift')
            nid,key,*_=contract['stages'][0]
            for mode in ('default','inactive','target','edge'):
                altered=copy.deepcopy(graph)
                if mode=='default':altered.nodes[nid]['widgets_values_named']={key:7}
                elif mode=='inactive':altered.nodes[nid]['mode']=2
                elif mode=='target':
                    with patch.object(altered,'targets',return_value=[('wrong',key)]),self.assertRaises(ValueError):
                        reviewed_stage_seeds({'id':wid},controls,graph=altered,source_hash=sha)
                    continue
                else:
                    src,_,_,_,_=contract['edges'][0];altered.out[src]=[]
                with self.subTest(wid=wid,mode=mode),self.assertRaises(ValueError):
                    reviewed_stage_seeds({'id':wid},controls,graph=altered,source_hash=sha)
            fresh=self.fresh(wid);derived={'sourceHash':sha,'controls':fresh}
            next(f for f in fresh if f['id']==nid+':'+key)['targets']=[{'node':'wrong','input':key}]
            with self.assertRaises(ValueError):reviewed_stage_seeds({'id':wid},controls,source_hash=sha,derived=derived)

    def test_non_stage_controls_preserved_and_nonreviewed_workflows_untouched(self):
        for wid,contract in STAGE_SEEDS.items():
            _,_,sha,graph,controls=self.data(wid)
            nodes={s[0]for s in contract['stages']}
            before=[c for c in controls if not(c.get('kind')=='seed'and(c.get('nodeId')in nodes or any(m['nodeId']in nodes for m in c.get('members',[]))))]
            after=self.fresh(wid)
            self.assertEqual([c for c in after if not(c.get('kind')=='seed'and c.get('nodeId')in nodes)],before)
        self.assertEqual(next(f for f in self.fresh('local-card-50')if f['id']=='672:sampling_mode.seed'),
                         next(f for f in self.public['local-card-50']['controls']if f['id']=='672:sampling_mode.seed'))
        for number in (17,18,40,75,124,131):
            controls=copy.deepcopy(self.public[f'local-card-{number}']['controls'])
            self.assertIs(reviewed_stage_seeds({'id':f'local-card-{number}'},controls,source_hash='irrelevant'),controls)

    def test_generic_stage_values_write_only_corresponding_concrete_node(self):
        for number in (50,51,77,90):
            wid=f'local-card-{number}';spec=copy.deepcopy(manifest(wid))
            contract=STAGE_SEEDS[wid];ids={n+':'+k for n,k,*_ in contract['stages']}
            spec['controls']=[f for f in self.fresh(wid)if f['id']in ids]
            # Isolate this CPU seed binding from upload/API/point contracts.
            spec.update(media=[],texts=[],apiProfiles=[])
            before,_,_=build(spec,{}, {},{}, {},'cpu-stage-seed')
            for field in spec['controls']:
                changed,_,_=build(spec,{field['id']:7},{},{},{},'cpu-stage-seed')
                target=field['targets'][0];node=target['node'];key=target['input']
                self.assertEqual(before[node]['inputs'][key],field['value'])
                self.assertEqual(changed[node]['inputs'][key],7)
                changed[node]['inputs'][key]=field['value']
                self.assertEqual(changed,before)

    def test_107_independent_enhancement_binding_and_old_receipt_compatibility(self):
        wid='local-card-107';workflow=adapter_manifest(wid)
        base={'seed':998425033959259,'size':'1024x1536','output_size':1536}
        original=workflow_path(wid).read_bytes();legacy=settings_for(workflow,base)
        self.assertNotIn('upscale_seed',legacy)
        before=build_graph(wid,'One blue cup','',legacy,[],'cpu-stage')
        self.assertEqual(before['80']['inputs']['seed'],base['seed']%(2**32))
        for value in (0,1375963829,SEEDVR_MAX):
            changed=build_graph(wid,'One blue cup','',settings_for(workflow,{**base,'upscale_seed':value}),[],'cpu-stage')
            self.assertEqual(changed['80']['inputs']['seed'],value)
            self.assertEqual(changed['3']['inputs']['seed'],base['seed'])
            changed['80']['inputs']['seed']=before['80']['inputs']['seed'];self.assertEqual(changed,before)
        for value in (True,-2,SEEDVR_MAX+1,1.0,'1',None):
            with self.subTest(value=value),self.assertRaises(ValueError):settings_for(workflow,{**base,'upscale_seed':value})
        with patch('adapters.secrets.randbelow',return_value=9):
            self.assertEqual(settings_for(workflow,{**base,'upscale_seed':-1})['upscale_seed'],9)
        self.assertEqual(workflow_path(wid).read_bytes(),original)

    def test_85_independent_redraw_binding_and_old_receipt_compatibility(self):
        wid='local-card-85';workflow=adapter_manifest(wid)
        base={'seed':187155922071792,'size':'896x1088'}
        original=workflow_path(wid).read_bytes();legacy=settings_for(workflow,base)
        self.assertNotIn('refine_seed',legacy)
        before=build_graph(wid,'One blue cup','',legacy,[],'cpu-stage')
        self.assertEqual(before['63']['inputs']['seed'],base['seed'])
        changed=build_graph(wid,'One blue cup','',settings_for(workflow,{**base,'refine_seed':199739316831602}),[],'cpu-stage')
        self.assertEqual(changed['63']['inputs']['seed'],199739316831602)
        self.assertEqual(changed['58']['inputs']['seed'],base['seed'])
        changed['63']['inputs']['seed']=base['seed'];self.assertEqual(changed,before)
        for value in (True,-2,9007199254740992,1.0,'1',None):
            with self.subTest(value=value),self.assertRaises(ValueError):settings_for(workflow,{**base,'refine_seed':value})
        with self.assertRaises(ValueError):settings_for(workflow,{**base,'seed':RGTHREE_SEED_MAX+1})
        with patch('adapters.secrets.randbelow',return_value=9):
            self.assertEqual(settings_for(workflow,{**base,'refine_seed':-1})['refine_seed'],9)
        self.assertEqual(workflow_path(wid).read_bytes(),original)


if __name__=='__main__':unittest.main()
