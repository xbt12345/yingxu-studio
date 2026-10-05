"""Legacy seed bounds checked against source, native metadata, and adapters."""
import ast,copy,hashlib,json,sys,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from build_workflow_interfaces import Graph
from reviewed_native_seed_limits import reviewed_native_seed_limits,NATIVE_SEED_LIMITS,NATIVE_SEED_MAX
from adapters import manifest,settings_for,workflow_path


class ReviewedNativeSeedLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit={r['id']:r for r in json.loads((ROOT/'verification/catalog-audit.json').read_text(encoding='utf-8'))if 'id'in r}
        cls.public=json.loads((ROOT/'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']

    def data(self,wid):
        path=Path(self.audit[wid]['source']);raw=path.read_bytes()
        return path,raw,hashlib.sha256(raw).hexdigest(),Graph(json.loads(raw.decode('utf-8-sig'))),copy.deepcopy(self.public[wid]['controls'])

    def test_all_twelve_fresh_curated_change_only_max_preserve_defaults_ids_and_binding(self):
        info=json.loads((ROOT/'private/review72/object_info.json').read_text(encoding='utf-8'))
        self.assertEqual(info['Seed (rgthree)']['input']['required']['seed'][1]['max'],NATIVE_SEED_MAX)
        self.assertEqual(len(NATIVE_SEED_LIMITS),12)
        for wid,contract in NATIVE_SEED_LIMITS.items():
            with self.subTest(wid=wid):
                path,raw,sha,graph,controls=self.data(wid);before=copy.deepcopy(graph.__dict__)
                template_bytes=workflow_path(wid).read_bytes();self.assertEqual(sha,contract[0])
                fresh=reviewed_native_seed_limits({'id':wid},controls,graph=graph,source_hash=sha)
                expected=copy.deepcopy(controls)
                next(f for f in expected if f['id']==contract[1])['max']=NATIVE_SEED_MAX
                self.assertEqual(fresh,expected)
                derived={'sourceHash':sha,'controls':fresh}
                self.assertEqual(reviewed_native_seed_limits({'id':wid},controls,source_hash=sha,derived=derived),fresh)
                self.assertEqual(reviewed_native_seed_limits({'id':wid},fresh,source_hash=sha,derived=derived),fresh)
                self.assertEqual(reviewed_native_seed_limits({'id':wid},fresh,source_hash=sha,graph=graph),fresh)
                self.assertEqual(graph.__dict__,before);self.assertEqual(path.read_bytes(),raw)
                self.assertEqual(workflow_path(wid).read_bytes(),template_bytes)

    def test_source_hash_node_default_inactive_and_implicit_widget_drift_fail_closed(self):
        for wid in NATIVE_SEED_LIMITS:
            _,_,sha,graph,controls=self.data(wid)
            with self.subTest(wid=wid),self.assertRaises(ValueError):
                reviewed_native_seed_limits({'id':wid},controls,graph=graph,source_hash='drift')
        for wid in ('local-card-1','local-card-10','local-card-11'):
            _,_,sha,graph,controls=self.data(wid);nid=NATIVE_SEED_LIMITS[wid][2]
            for key in ('class','default','inactive'):
                changed=copy.deepcopy(graph)
                if key=='class':changed.nodes[nid]['type']='RandomNoise'
                elif key=='inactive':changed.nodes[nid]['mode']=2
                elif wid=='local-card-1':changed.nodes[nid]['widgets_values_named']={'seed':1}
                else:changed.nodes[nid]['widgets_values'][0]=1
                with self.subTest(wid=wid,key=key),self.assertRaises(ValueError):
                    reviewed_native_seed_limits({'id':wid},controls,graph=changed,source_hash=sha)

    def test_actual_template_class_and_curated_proof_drift_fail_closed(self):
        wid='local-card-11';_,_,sha,graph,controls=self.data(wid);fid=NATIVE_SEED_LIMITS[wid][1]
        original=json.loads(workflow_path(wid).read_text(encoding='utf-8'))
        for key in ('class','default'):
            changed=copy.deepcopy(original)
            if key=='class':changed['157']['class_type']='KSampler'
            else:changed['157']['inputs']['seed']=1
            class FakePath:
                def read_text(self,**kwargs):return json.dumps(changed)
            with patch('reviewed_native_seed_limits.workflow_path',return_value=FakePath()),self.assertRaises(ValueError):
                reviewed_native_seed_limits({'id':wid},controls,graph=graph,source_hash=sha)
        fresh=reviewed_native_seed_limits({'id':wid},controls,graph=graph,source_hash=sha)
        for key in ('source','target','members','max'):
            derived={'sourceHash':sha,'controls':copy.deepcopy(fresh)}
            proof=next(f for f in derived['controls']if f['id']==fid)
            if key=='source':derived['sourceHash']='drift'
            elif key=='target':proof['targets'][0]['node']='wrong'
            elif key=='members':proof['members']=[]
            else:proof['max']=9007199254740991
            with self.subTest(key=key),self.assertRaises(ValueError):
                reviewed_native_seed_limits({'id':wid},controls,source_hash=sha,derived=derived)

    def test_real_adapter_accepts_native_boundary_and_random_rejects_native_plus_one(self):
        for wid,contract in NATIVE_SEED_LIMITS.items():
            workflow=manifest(wid);baseline=settings_for(workflow,{'seed':contract[3]})
            for value in (0,contract[3],NATIVE_SEED_MAX):
                with self.subTest(wid=wid,value=value):
                    result=settings_for(workflow,{'seed':value})
                    self.assertEqual(result['seed'],value)
                    result['seed']=baseline['seed'];self.assertEqual(result,baseline)
            with patch('adapters.secrets.randbelow',return_value=7):
                result=settings_for(workflow,{'seed':-1})
                self.assertEqual(result['seed'],7)
                missing=settings_for(workflow,{})
                self.assertEqual(missing['seed'],7)
            for value in (NATIVE_SEED_MAX+1,9007199254740991,True,-2,1.0,'1',None):
                with self.subTest(wid=wid,value=value),self.assertRaises(ValueError):
                    settings_for(workflow,{'seed':value})
            changed=copy.deepcopy(workflow);changed['source_hash']='drift'
            with self.assertRaises(ValueError):settings_for(changed,{'seed':0})

    def test_nonreviewed_seed_contract_and_adapter_are_unchanged(self):
        for wid in ('local-card-17','local-card-18','local-card-107'):
            controls=copy.deepcopy(self.public[wid]['controls'])
            self.assertIs(reviewed_native_seed_limits({'id':wid},controls,source_hash='irrelevant'),controls)
            result=settings_for(manifest(wid),{'seed':9007199254740991})
            self.assertEqual(result['seed'],9007199254740991)

    def test_real_fresh_customization_missing_nodeid_curated_identity_and_wrong_nodeid(self):
        # Execute only the builder's real source-to-fresh-form prefix in memory.
        # Exclude every curated refresh, audit write, build/compile and dispatch.
        import build_workflow_interfaces as builder
        tree=ast.parse((ROOT/'scripts/build_workflow_interfaces.py').read_text(encoding='utf-8'))
        func=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='build')
        loop=next(n for n in func.body if isinstance(n,ast.For))
        index=next(i for i,n in enumerate(loop.body)if isinstance(n,ast.Assign)and
                   isinstance(n.value,ast.Call)and getattr(n.value.func,'id',None)=='customize')
        loop.body=loop.body[:index+1]
        loop.body.insert(0,ast.parse('if w["id"] not in selected_ids: continue').body[0])
        loop.body+=ast.parse('fresh[w["id"]]={"controls":controls,"sourceHash":hashlib.sha256(raw_bytes).hexdigest()}').body
        func.body=func.body[:func.body.index(loop)]+[loop]
        func.body.insert(0,ast.parse('fresh={}').body[0])
        func.body+=ast.parse('return fresh').body;func.name='fresh_contract_only'
        namespace={**vars(builder),'selected_ids':set(NATIVE_SEED_LIMITS)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[])),'fresh-contract-only','exec'),namespace)
        forms=namespace['fresh_contract_only']()
        self.assertEqual(set(forms),set(NATIVE_SEED_LIMITS))
        for wid in ('local-card-109','local-card-128'):
            _,_,sha,graph,curated=self.data(wid);fid=NATIVE_SEED_LIMITS[wid][1]
            field=next(f for f in forms[wid]['controls']if f['id']==fid)
            self.assertNotIn('nodeId',field);self.assertEqual(field['max'],NATIVE_SEED_MAX)
            result=reviewed_native_seed_limits({'id':wid},curated,source_hash=sha,derived=forms[wid])
            # The old curated identity remains present; no other field changes.
            old=next(f for f in curated if f['id']==fid)
            new=next(f for f in result if f['id']==fid)
            self.assertEqual(new.get('nodeId'),old.get('nodeId'))
            expected=copy.deepcopy(curated);next(f for f in expected if f['id']==fid)['max']=NATIVE_SEED_MAX
            self.assertEqual(result,expected)
            bad=copy.deepcopy(forms[wid]['controls']);next(f for f in bad if f['id']==fid)['nodeId']='wrong'
            with self.assertRaises(ValueError):reviewed_native_seed_limits({'id':wid},bad,graph=graph,source_hash=sha)


if __name__=='__main__':unittest.main()
