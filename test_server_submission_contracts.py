"""Test exact server pure contracts without importing its live SQLite runtime."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from pydantic import BaseModel,ConfigDict,Field,ValidationError,field_validator,model_validator
import adapters

ROOT=Path(__file__).resolve().parent


def isolated_contracts():
    tree=ast.parse((ROOT/'server.py').read_text('utf-8'))
    names={'Submission','redraw_legacy_refinement_seed'}
    nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef))and n.name in names]
    if len(nodes)!=2:raise AssertionError('Exact pure server contracts changed')
    scope={'BaseModel':BaseModel,'ConfigDict':ConfigDict,'Field':Field,
           'field_validator':field_validator,'model_validator':model_validator,
           'secrets':SimpleNamespace(randbelow=lambda span:17)}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'server-pure-contracts','exec'),scope)
    rerun=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='rerun')
    seed_branch=next(n for n in ast.walk(rerun)if isinstance(n,ast.If)
                    and isinstance(n.test,ast.Attribute)and n.test.attr=='randomize_seed')
    restore=next(n for n in ast.walk(rerun)if isinstance(n,ast.For)
                 and isinstance(n.iter,ast.Call)and isinstance(n.iter.func,ast.Name)
                 and n.iter.func.id=='enumerate')
    return scope,seed_branch,restore


class SubmissionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope,cls.seed_branch,cls.restore=isolated_contracts()
        cls.Submission=cls.scope['Submission']

    def test_catalog_negative_accepts_complete_reviewed_length(self):
        for wid in ('local-card-5','local-card-107'):
            with self.subTest(wid=wid):
                body=self.Submission(workflow_id=wid,negative='避'*6000,token='offline-test')
                self.assertEqual(len(body.negative),6000)
                with self.assertRaises(ValidationError):
                    self.Submission(workflow_id=wid,negative='避'*6001,token='offline-test')

    def test_original_named_video_limit_stays_2000(self):
        for wid in ('h3-reference','bernini-edit'):
            with self.subTest(wid=wid):
                self.Submission(workflow_id=wid,negative='避'*2000,token='offline-test')
                with self.assertRaises(ValidationError):
                    self.Submission(workflow_id=wid,negative='避'*2001,token='offline-test')

    def test_top_level_nul_is_rejected_before_any_submission(self):
        for key in ('prompt','negative'):
            with self.subTest(key=key),self.assertRaises(ValidationError):
                self.Submission(workflow_id='local-card-12',token='offline-test',**{key:'blue\x00cup'})

    def test_legacy_extra_branch_nul_rejected_and_regular_text_preserved(self):
        w=adapters.manifest('local-card-12')
        for key in ('prompt_turn2real','prompt_semireal'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                adapters.settings_for(w,{key:'blue\x00cup'})
        text='保留原图的面部与相机；仅修改光线。'
        result=adapters.settings_for(w,{'seed':7,'prompt_turn2real':text,'prompt_semireal':text})
        self.assertEqual(result['prompt_turn2real'],text)
        self.assertEqual(result['prompt_semireal'],text)

    def seed_run(self,wid,settings,graph,randomize):
        scope={**self.scope,'body':SimpleNamespace(randomize_seed=randomize),
               'original':{'workflow_id':wid},'settings':copy.deepcopy(settings),'graph':copy.deepcopy(graph)}
        exec(compile(ast.Module(body=[copy.deepcopy(self.seed_branch)],type_ignores=[]),'exact-rerun-seeds','exec'),scope)
        return scope['settings'],scope['graph']

    def test_independent_refinement_redraw_records_actual_and_reedit_replays_it(self):
        for wid,key,primary,secondary in [('local-card-85','refine_seed','58','63'),
                                          ('local-card-107','upscale_seed','3','80')]:
            w=adapters.manifest(wid)
            settings=adapters.settings_for(w,{'seed':777,key:991})
            graph=adapters.build_graph(wid,'a blue cup','no watermark',settings,[],'before')
            settings_after,after=self.seed_run(wid,settings,graph,True)
            with self.subTest(wid=wid):
                self.assertNotEqual(after[primary]['inputs']['seed'],graph[primary]['inputs']['seed'])
                self.assertNotEqual(after[secondary]['inputs']['seed'],graph[secondary]['inputs']['seed'])
                self.assertEqual(settings_after[key],after[secondary]['inputs']['seed'])
                self.assertNotEqual(settings_after[key],settings_after['seed'])
                editable={k:v for k,v in settings_after.items()if k not in ('width','height')}
                fresh=adapters.build_graph(wid,'a blue cup','no watermark',
                       adapters.settings_for(w,editable),[],'reedit')
                self.assertEqual(fresh[primary]['inputs']['seed'],after[primary]['inputs']['seed'])
                self.assertEqual(fresh[secondary]['inputs']['seed'],after[secondary]['inputs']['seed'])
                without_seeds=lambda g:{nid:{**n,'inputs':{k:v for k,v in n['inputs'].items()
                                         if not (nid in (primary,secondary)and k=='seed')}}for nid,n in g.items()}
                self.assertEqual(without_seeds(graph),without_seeds(after))

    def test_old_ticket_without_new_key_uses_actual_graph_and_creates_honest_settings(self):
        for wid,key,node in [('local-card-85','refine_seed','63'),('local-card-107','upscale_seed','80')]:
            settings=adapters.settings_for(adapters.manifest(wid),{'seed':777})
            graph=adapters.build_graph(wid,'cup','',settings,[],'old-ticket')
            self.assertNotIn(key,settings)
            settings_after,after=self.seed_run(wid,settings,graph,True)
            self.assertEqual(settings_after[key],after[node]['inputs']['seed'])
            self.assertNotEqual(after[node]['inputs']['seed'],graph[node]['inputs']['seed'])

    def test_old_coupled_ticket_stale_settings_are_corrected_from_saved_graph(self):
        for wid,key,node in [('local-card-85','refine_seed','63'),('local-card-107','upscale_seed','80')]:
            settings=adapters.settings_for(adapters.manifest(wid),{'seed':777,key:991})
            graph=adapters.build_graph(wid,'cup','',settings,[],'old-coupled')
            graph[node]['inputs']['seed']=777
            settings_after,after=self.seed_run(wid,settings,graph,True)
            self.assertEqual(settings_after[key],after[node]['inputs']['seed'])
            self.assertEqual(settings_after[key],795)

    def test_original_seed_retry_does_not_change_any_stage(self):
        for wid,key in [('local-card-85','refine_seed'),('local-card-107','upscale_seed')]:
            settings=adapters.settings_for(adapters.manifest(wid),{'seed':777,key:991})
            graph=adapters.build_graph(wid,'cup','',settings,[],'same')
            settings_after,after=self.seed_run(wid,settings,graph,False)
            self.assertEqual(settings_after,settings);self.assertEqual(after,graph)

    def test_refinement_native_range_and_drift_rejected_atomically(self):
        helper=self.scope['redraw_legacy_refinement_seed']
        for wid,node,typ,key,max_ in [('local-card-85','63','KSampler','refine_seed',9007199254740991),
                                     ('local-card-107','80','SeedVR2VideoUpscaler','upscale_seed',4294967295)]:
            graph={node:{'class_type':typ,'inputs':{'seed':max_}}};settings={}
            helper(wid,graph,settings)
            self.assertTrue(0<=settings[key]<=max_);self.assertEqual(settings[key],graph[node]['inputs']['seed'])
            for bad in ({'class_type':'other','inputs':{'seed':7}},
                        {'class_type':typ,'inputs':{'seed':max_+1}},
                        {'class_type':typ,'inputs':{'seed':True}}):
                changed={node:copy.deepcopy(bad)};settings={'seed':7};before=copy.deepcopy(changed)
                with self.assertRaises(ValueError):helper(wid,changed,settings)
                self.assertEqual(changed,before);self.assertEqual(settings,{'seed':7})

    def test_all_legacy_material_restore_keeps_exact_original_loader_routes(self):
        ui=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
        for w in adapters.CATALOG_WORKFLOWS:
            cfg=ui[w['id']];values={f['key']:750001 if f['kind']=='seed'else f['value']for f in cfg['controls']}
            for f in cfg['controls']:
                if f['kind']=='seed'and(f['key'].startswith('widget_')or w['id']in
                   ('local-card-11','local-card-15','local-card-16','local-card-17','local-card-18','local-card-20')):
                    values.pop(f['key']);values['seed']=750001
            settings=adapters.settings_for(w,values)
            assets=[{'kind':'image','remote':f'offline-{i}.png','has_edit_mask':True}for i in range(w['minImages'])]
            graph=adapters.build_graph(w['id'],'cup','',settings,assets,'restore')
            restored=copy.deepcopy(graph)
            scope={'original':{'workflow_id':w['id']},'graph':restored,'aa':assets}
            with self.subTest(wid=w['id']):
                exec(compile(ast.Module(body=[copy.deepcopy(self.restore)],type_ignores=[]),'exact-rerun-materials','exec'),scope)
                self.assertEqual(restored,graph)


if __name__=='__main__':unittest.main()
