"""Focused source/UI protocol tests; no builders, server, API, or GPU."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_workflow_interfaces import Graph
from compile_card_workflows import Compiler
from review74_parameter_contracts import (reviewed_independent_seeds,reviewed_color_supplement,
    reviewed_camera14_size,SEED112_HASH,SEED112_FIELDS,COLOR_SUPPLEMENTS)
from schema_adapters import manifest,build


class Review74ParameterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit=json.loads((ROOT/'verification/catalog-audit.json').read_text(encoding='utf-8'))
        cls.public=json.loads((ROOT/'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']
        cls.node_info=json.loads((ROOT/'private/review72/object_info.json').read_text(encoding='utf-8'))

    def data(self,number):
        wid=f'local-card-{number}'
        path=Path(next(row['source']for row in self.audit if row.get('id')==wid))
        raw=path.read_bytes()
        return {'id':wid},hashlib.sha256(raw).hexdigest(),Graph(json.loads(raw.decode('utf-8-sig'))),copy.deepcopy(self.public[wid]),path

    def test_112_independent_default_seeds_targets_fresh_curated_and_idempotence(self):
        workflow,sha,graph,cfg,path=self.data(112)
        self.assertEqual(sha,SEED112_HASH)
        before=copy.deepcopy(cfg['controls']);graph_before=copy.deepcopy(graph.__dict__)
        fresh=reviewed_independent_seeds(workflow,before,graph=graph,source_hash=sha)
        seeds=[f for f in fresh if f.get('kind')=='seed']
        self.assertEqual(len(seeds),2)
        for field,(nid,value,label) in zip(seeds,SEED112_FIELDS):
            self.assertEqual(field['id'],nid+':noise_seed')
            self.assertEqual(field['value'],value)
            self.assertEqual(field['targets'],[{'node':nid,'input':'noise_seed'}])
            self.assertEqual(field['label'],label)
            self.assertEqual(field['members'],[{k:field[k]for k in ('id','nodeId','key','targets')}])
        self.assertNotEqual(seeds[0]['value'],seeds[1]['value'])
        self.assertEqual([f for f in fresh if f.get('kind')!='seed'],[f for f in before if f.get('kind')!='seed'])
        self.assertEqual(graph.__dict__,graph_before)
        derived={'sourceHash':sha,'controls':fresh}
        curated=reviewed_independent_seeds(workflow,copy.deepcopy(before),source_hash=sha,derived=derived)
        self.assertEqual(curated,fresh)
        self.assertEqual(reviewed_independent_seeds(workflow,curated,source_hash=sha,derived=derived),fresh)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),sha)

    def test_112_seed_source_hash_default_and_target_proof_drift_fail_closed(self):
        workflow,sha,graph,cfg,_=self.data(112)
        fresh=reviewed_independent_seeds(workflow,cfg['controls'],graph=graph,source_hash=sha)
        with self.assertRaises(ValueError):reviewed_independent_seeds(workflow,cfg['controls'],graph=graph,source_hash='drift')
        for field in ('value','target','sourceHash'):
            derived={'sourceHash':sha,'controls':copy.deepcopy(fresh)}
            seed=next(f for f in derived['controls']if f['id']=='196:noise_seed')
            if field=='value':seed['value']+=1
            elif field=='target':seed['targets'][0]['node']='116'
            else:derived['sourceHash']='drift'
            with self.subTest(field=field),self.assertRaises(ValueError):
                reviewed_independent_seeds(workflow,copy.deepcopy(cfg['controls']),source_hash=sha,derived=derived)
        mutated=copy.deepcopy(graph)
        mutated.nodes['196']['widgets_values_named']={'noise_seed':1}
        with self.assertRaises(ValueError):reviewed_independent_seeds(workflow,cfg['controls'],graph=mutated,source_hash=sha)
        with patch.object(graph,'targets',return_value=[('116','noise_seed')]),self.assertRaises(ValueError):
            reviewed_independent_seeds(workflow,cfg['controls'],graph=graph,source_hash=sha)

    def test_color_supplements_fresh_curated_blank_and_real_text_preserve_trigger(self):
        for number in (112,113):
            with self.subTest(number=number):
                workflow,sha,graph,cfg,path=self.data(number)
                expected,nid,tagger=COLOR_SUPPLEMENTS[workflow['id']]
                self.assertEqual(sha,expected)
                raw_bytes=path.read_bytes();source_before=copy.deepcopy(graph.__dict__)
                fresh=reviewed_color_supplement(workflow,cfg['texts'],graph=graph,source_hash=sha)
                field=next(f for f in fresh if f['id']==nid+':string_b')
                self.assertTrue(field['preserveWhenEmpty']);self.assertFalse(field['required'])
                self.assertEqual(graph.__dict__,source_before)
                derived={'sourceHash':sha,'texts':fresh}
                curated=reviewed_color_supplement(workflow,copy.deepcopy(cfg['texts']),source_hash=sha,derived=derived)
                self.assertEqual(curated,fresh)
                self.assertEqual(reviewed_color_supplement(workflow,curated,source_hash=sha,derived=derived),fresh)
                compiler=Compiler(json.loads(raw_bytes.decode('utf-8-sig')),self.node_info)
                compiler.outputs('image')
                self.assertEqual(compiler.targets(nid,'string_b'),[{'node':nid,'input':'string_b'}])
                self.assertEqual(compiler.compiled[nid]['inputs'],{'string_a':'colorMangaKlein. ','string_b':'','delimiter':''})
                # Clone the registry locally; no production registry/template write.
                spec=copy.deepcopy(manifest(workflow['id']))
                spec['texts']=[f for f in spec['texts']if f['id']!=field['id']]
                spec['texts'].append({**field,'targets':compiler.targets(nid,'string_b'),'default':''})
                assets={f['id']:{'kind':f['kind'],'remote':'owned-'+f['id']+'.png'}for f in spec['media']}
                # Exact seed values make this a one-text-variable protocol check.
                values={f['id']:f['value']for f in spec['controls']}
                texts={f['id']:'CPU source instruction'for f in spec['texts']if f['id']!=field['id']}
                blank,_,blank_texts=build(spec,values,{**texts,field['id']:''},assets,{},'cpu-text')
                supplied='Apply muted blue; preserve the original line art.'
                changed,_,_=build(spec,values,{**texts,field['id']:supplied},assets,{},'cpu-text')
                self.assertEqual(blank_texts[field['id']],'')
                self.assertEqual(blank[nid]['inputs']['string_b'],'')
                self.assertEqual(changed[nid]['inputs']['string_b'],supplied)
                self.assertEqual(changed[nid]['inputs']['string_a'],'colorMangaKlein. ')
                self.assertEqual(changed[nid]['inputs']['delimiter'],'')
                reverted=copy.deepcopy(changed);reverted[nid]['inputs']['string_b']=''
                self.assertEqual(reverted,blank)
                self.assertEqual(path.read_bytes(),raw_bytes)

    def test_color_supplement_guards_hash_mode_trigger_delimiter_and_link(self):
        for number in (112,113):
            workflow,sha,graph,cfg,_=self.data(number)
            _,nid,tagger=COLOR_SUPPLEMENTS[workflow['id']]
            with self.subTest(number=number),self.assertRaises(ValueError):
                reviewed_color_supplement(workflow,cfg['texts'],graph=graph,source_hash='drift')
            for change in ('mode','trigger','delimiter','link'):
                mutated=copy.deepcopy(graph)
                if change=='mode':mutated.nodes[tagger]['mode']=0
                elif change in ('trigger','delimiter'):
                    values={key:value for key,(value,_)in __import__('build_workflow_interfaces').widget_bindings(mutated.nodes[nid]).items()}
                    values['string_a'if change=='trigger'else'delimiter']='drift'
                    mutated.nodes[nid]['widgets_values_named']=values
                else:mutated.ins[nid]=[(tagger,0,0)]
                with self.subTest(number=number,change=change),self.assertRaises(ValueError):
                    reviewed_color_supplement(workflow,cfg['texts'],graph=mutated,source_hash=sha)
            fresh=reviewed_color_supplement(workflow,cfg['texts'],graph=graph,source_hash=sha)
            derived={'sourceHash':sha,'texts':copy.deepcopy(fresh)}
            next(f for f in derived['texts']if f['id']==nid+':string_b')['preserveWhenEmpty']=False
            with self.assertRaises(ValueError):reviewed_color_supplement(workflow,cfg['texts'],source_hash=sha,derived=derived)

    def test_camera14_output_budget_fresh_curated_preserves_camera_seed_and_all_old_targets(self):
        workflow,sha,graph,cfg,path=self.data(14)
        before=copy.deepcopy(cfg['controls']);source_bytes=path.read_bytes()
        old={f['id']:copy.deepcopy(f)for f in before if f['id']!='135:scale_to_length'}
        fresh=reviewed_camera14_size(workflow,before,graph=graph,source_hash=sha)
        field=next(f for f in fresh if f['id']=='135:scale_to_length')
        self.assertEqual(field['value'],1324)
        self.assertEqual(field['key'],'output_pixels')
        self.assertEqual(field['targets'],[{'node':'135','input':'scale_to_length'}])
        self.assertEqual((field['min'],field['max'],field['step']),(512,4096,1))
        for f in fresh:
            if f['id']in old:self.assertEqual(f,old[f['id']])
        derived={'sourceHash':sha,'controls':fresh}
        curated=reviewed_camera14_size(workflow,copy.deepcopy(before),source_hash=sha,derived=derived)
        self.assertEqual(curated,fresh)
        self.assertEqual(reviewed_camera14_size(workflow,curated,source_hash=sha,derived=derived),fresh)
        self.assertEqual(path.read_bytes(),source_bytes)
        with self.assertRaises(ValueError):reviewed_camera14_size(workflow,before,graph=graph,source_hash='drift')
        altered=copy.deepcopy(derived)
        next(f for f in altered['controls']if f['id']==field['id'])['targets'][0]['node']='83'
        with self.assertRaises(ValueError):reviewed_camera14_size(workflow,before,source_hash=sha,derived=altered)


if __name__=='__main__':unittest.main()
