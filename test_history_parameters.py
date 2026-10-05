"""Old executed seed recovery, identity bounds and public receipt isolation."""
import ast
import copy
import json
from pathlib import Path
import unittest
from history_parameters import history_seed_values,LEGACY_STAGE_SEEDS

ROOT=Path(__file__).resolve().parent
INTERFACES=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']


class HistoryParameters(unittest.TestCase):
    def generic(self):
        wid='local-card-50';cfg=INTERFACES[wid]
        job={'workflow_id':wid,'schema_spec':{'id':wid,'source_hash':cfg['sourceHash']},
             'catalog_values':{'432:noise_seed':123},
             'graph':{'467':{'class_type':'RandomNoise','inputs':{'noise_seed':777}},
                      '432':{'class_type':'RandomNoise','inputs':{'noise_seed':999}},
                      'api':{'class_type':'VisionAPIDirect','inputs':{'api_key':'private-test-secret'}}}}
        return job,cfg

    def legacy(self,wid):
        cfg=INTERFACES[wid];sha,fid,nid,key,typ,primary,pkey,ptype,edges=LEGACY_STAGE_SEEDS[wid]
        graph={primary:{'class_type':ptype,'inputs':{pkey:711107}},nid:{'class_type':typ,'inputs':{key:888}}}
        for dst,kind,port,value in edges:
            graph.setdefault(dst,{'class_type':kind,'inputs':{}})['inputs'][port]=copy.deepcopy(value)
        return {'workflow_id':wid,'settings':{'seed':711107},'graph':graph},cfg,fid

    def test_only_missing_same_source_safe_seeds_without_mutation(self):
        job,cfg=self.generic();before=copy.deepcopy(job)
        self.assertEqual(history_seed_values(job,cfg),{'467:noise_seed':777})
        self.assertEqual(job,before)
        self.assertNotIn('private-test-secret',json.dumps(history_seed_values(job,cfg)))

    def test_source_and_class_drift_cannot_project(self):
        for drift in ('id','hash','class'):
            job,cfg=self.generic()
            if drift=='id':job['schema_spec']['id']='local-card-51'
            elif drift=='hash':job['schema_spec']['source_hash']='0'*64
            else:job['graph']['467']['class_type']='VisionAPIDirect'
            with self.subTest(drift=drift):self.assertEqual(history_seed_values(job,cfg),{})

    def test_invalid_seed_values_and_non_seed_ports_are_not_public(self):
        for value in (-1,True,'777',0.5,9007199254740992,['credential',0]):
            job,cfg=self.generic();job['graph']['467']['inputs']['noise_seed']=value
            with self.subTest(value=value):self.assertEqual(history_seed_values(job,cfg),{})
        job,cfg=self.generic();cfg=copy.deepcopy(cfg)
        next(f for f in cfg['controls']if f['id']=='467:noise_seed')['targets'][0]['input']='api_key'
        self.assertEqual(history_seed_values(job,cfg),{})

    def test_both_hashless_legacy_contracts_preserve_independent_executed_stage(self):
        for wid in LEGACY_STAGE_SEEDS:
            job,cfg,fid=self.legacy(wid)
            with self.subTest(wid=wid):self.assertEqual(history_seed_values(job,cfg),{fid:888})

    def test_legacy_source_topology_primary_seed_and_existing_value_guards(self):
        for wid in LEGACY_STAGE_SEEDS:
            for drift in ('source','edge','primary','existing','class'):
                job,cfg,fid=self.legacy(wid);cfg=copy.deepcopy(cfg)
                if drift=='source':cfg['sourceHash']='0'*64
                elif drift=='edge':
                    dst,_,port,_=LEGACY_STAGE_SEEDS[wid][-1][0];job['graph'][dst]['inputs'][port]=['wrong-node',0]
                elif drift=='primary':job['settings']['seed']=555
                elif drift=='existing':job['catalog_values']={fid:321}
                else:job['graph'][fid.split(':')[0]]['class_type']='VisionAPIDirect'
                with self.subTest(wid=wid,drift=drift):self.assertEqual(history_seed_values(job,cfg),{})

    def test_public_receipt_exposes_only_scalar_projection_keeps_legacy_mode(self):
        tree=ast.parse((ROOT/'server.py').read_text('utf-8-sig'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='public')
        namespace={'historical_output_presentation':lambda j:[], '__builtins__':__builtins__}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'server.py','exec'),namespace)
        job,cfg,_=self.legacy('local-card-107');job.update(id='offline-ticket',token='request-token',asset_ids=[])
        result=namespace['public'](job)
        self.assertEqual(result['catalog_seed_values'],{'80:seed':888})
        self.assertNotIn('graph',result);self.assertNotIn('schema_spec',result)
        self.assertNotIn('catalog_values',result);self.assertEqual(result['settings'],job['settings'])


if __name__=='__main__':unittest.main()
