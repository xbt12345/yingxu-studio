"""Final image resolution source, boundaries and real graph writes, no generation."""
import copy,hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from build_workflow_interfaces import Graph
from review74_parameter_contracts import reviewed_final_enhancement_size,reviewed_refinement_reference,reviewed_inactive_middle_position,reviewed_multiview_output_size,MULTIVIEW_OUTPUT_SIZES
from configuration import workflow_path


class Review75OutputContracts(unittest.TestCase):
    def source(self,number):
        audit=json.loads((ROOT/'verification/catalog-audit.json').read_text('utf-8'))
        wid=f'local-card-{number}'
        path=Path(next(r['source']for r in audit if r.get('id')==wid))
        raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        graph=Graph(json.loads(raw.decode('utf-8-sig')))
        cfg=json.loads((ROOT/'public/workflow-interfaces.json').read_text('utf-8'))['workflows'][wid]
        return path,raw,sha,graph,cfg

    def data(self):return self.source(77)

    def test_final_output_not_preprocessor_and_native_metadata_matches(self):
        path,raw,sha,graph,cfg=self.data();before=copy.deepcopy(cfg['controls'])
        result=reviewed_final_enhancement_size({'id':'local-card-77'},before,graph=graph,source_hash=sha)
        field=next(f for f in result if f['id']=='89:resolution')
        info=json.loads((ROOT/'private/review72/object_info.json').read_text('utf-8'))
        native=info['SeedVR2VideoUpscaler']['input']['required']['resolution']
        self.assertEqual(native[0],'INT')
        self.assertEqual({k:field[k]for k in ('min','max','step')},{k:native[1][k]for k in ('min','max','step')})
        self.assertEqual(field['value'],1536);self.assertEqual(field['targets'],[{'node':'89','input':'resolution'}])
        self.assertIn('shortest edge',native[1]['tooltip']);self.assertEqual(graph.ins['80'],[('89',0,0)])
        self.assertEqual([f for f in result if f['id']!='89:resolution'],[f for f in before if f['id']!='89:resolution'])
        self.assertEqual(path.read_bytes(),raw)

    def test_fresh_curated_idempotence_and_source_default_graph_drift(self):
        _,_,sha,graph,cfg=self.data()
        original=copy.deepcopy(cfg['controls'])
        first=reviewed_final_enhancement_size({'id':'local-card-77'},original,graph=graph,source_hash=sha)
        derived={'sourceHash':sha,'controls':first}
        self.assertEqual(reviewed_final_enhancement_size({'id':'local-card-77'},original,source_hash=sha,derived=derived),first)
        self.assertEqual(reviewed_final_enhancement_size({'id':'local-card-77'},first,source_hash=sha,derived=derived),first)
        for change in ('sha','default','output'):
            changed=copy.deepcopy(graph)
            if change=='default':changed.nodes['89']['widgets_values'][2]=2048
            if change=='output':changed.ins['80']=[('92',0,0)]
            with self.subTest(change=change),self.assertRaises(ValueError):
                reviewed_final_enhancement_size({'id':'local-card-77'},original,graph=changed,source_hash='drift'if change=='sha'else sha)
        changed=copy.deepcopy(derived);next(f for f in changed['controls']if f['id']=='89:resolution')['targets'][0]['node']='14'
        with self.assertRaises(ValueError):reviewed_final_enhancement_size({'id':'local-card-77'},original,source_hash=sha,derived=changed)

    def test_real_registered_ui_field_changes_only_output_resolution(self):
        import schema_adapters
        spec=schema_adapters.manifest('local-card-77')
        field=next(f for f in spec['controls']if f['id']=='89:resolution')
        self.assertEqual(field['value'],1536)
        texts={f['id']:f.get('default',f.get('value',''))or '参数复核'for f in spec.get('texts',[])if f.get('required')}
        records={m['id']:{'kind':m['kind'],'remote':'review75-'+m['id']+'.png'}for m in spec.get('media',[])}
        original,_,_=schema_adapters.build(spec,{},texts,records,{},'review75-output')
        baseline=original['89']['inputs']['resolution']
        for value in (16,1024,1536,2048,16384):
            with self.subTest(value=value):
                actual,_,_=schema_adapters.build(spec,{field['id']:value},texts,records,{},'review75-output')
                self.assertEqual(actual['89']['inputs']['resolution'],value)
                actual['89']['inputs']['resolution']=baseline
                self.assertEqual(actual,original)
        for value in (15,17,16385,1024.5,True,'1024'):
            with self.subTest(value=value),self.assertRaises(ValueError):schema_adapters.build(spec,{field['id']:value},texts,records,{},'review75-output')

    def test_dynamic_refinement_default_branch_and_fresh_curated_proof(self):
        _,raw,sha,graph,cfg=self.source(51)
        fresh=reviewed_refinement_reference({'id':'local-card-51'},cfg['controls'],graph=graph,source_hash=sha)
        field=next(f for f in fresh if f['id']=='988:num_guides.strength_1')
        self.assertEqual(field['value'],1.0);self.assertEqual(field['targets'],[{'node':'988','input':'num_guides.strength_1'}])
        first=next(f for f in fresh if f['id']=='1065:num_guides.strength_1')
        self.assertNotEqual(first['targets'],field['targets'])
        derived={'sourceHash':sha,'controls':fresh}
        self.assertEqual(reviewed_refinement_reference({'id':'local-card-51'},fresh,source_hash=sha,derived=derived),fresh)
        changed=copy.deepcopy(graph);changed.nodes['988']['widgets_values']=[1];changed.nodes['988']['widgets_values_named']={'num_guides':1}
        with self.assertRaises(ValueError):reviewed_refinement_reference({'id':'local-card-51'},cfg['controls'],graph=changed,source_hash=sha)
        changed=copy.deepcopy(derived);next(f for f in changed['controls']if f['id']==field['id'])['targets'][0]['node']='1065'
        with self.assertRaises(ValueError):reviewed_refinement_reference({'id':'local-card-51'},fresh,source_hash=sha,derived=changed)
        from schema_adapters import manifest,validate_values,_control_values,_put
        spec=manifest('local-card-51');registered=next(f for f in spec['controls']if f['id']==field['id'])
        template=json.loads(workflow_path('local-card-51').read_text('utf-8'))
        required_points={f['id']:'{"positive":[{"x":0.5,"y":0.5}],"negative":[]}'for f in spec['controls']if f.get('kind')=='points'}
        for value in (0,0.01,1,3.5,10):
            values=validate_values(spec,{**required_points,field['id']:value});result=copy.deepcopy(template)
            for target,next_value in _control_values(registered,values[field['id']],values):_put(result,target,next_value)
            self.assertEqual(result['988']['inputs']['num_guides.strength_1'],value)
            result['988']['inputs']['num_guides.strength_1']=1.0
            self.assertEqual(result,template)

    def test_disabled_middle_has_no_position_control_and_original_default_retained(self):
        path,raw,sha,graph,cfg=self.source(124)
        first=reviewed_inactive_middle_position({'id':'local-card-124'},cfg['controls'],graph=graph,source_hash=sha)
        self.assertFalse(any(f['id']=='44:middle_frame_ratio'for f in first))
        self.assertEqual(reviewed_inactive_middle_position({'id':'local-card-124'},first,source_hash=sha,derived={'sourceHash':sha,'controls':first}),first)
        template=json.loads(workflow_path('local-card-124').read_text('utf-8'))
        self.assertEqual(template['44']['inputs']['middle_frame_ratio'],0.5)
        self.assertNotIn('middle_image',template['44']['inputs']);self.assertNotIn('45',template);self.assertNotIn('46',template)
        changed=copy.deepcopy(graph);changed.nodes['46']['mode']=0
        with self.assertRaises(ValueError):reviewed_inactive_middle_position({'id':'local-card-124'},cfg['controls'],graph=changed,source_hash=sha)
        self.assertEqual(path.read_bytes(),raw)

    def test_multiview_actual_dimensions_keep_units_rounding_and_independent_cameras(self):
        from schema_adapters import manifest,validate_values,_control_values,_put
        for wid,contract in MULTIVIEW_OUTPUT_SIZES.items():
            with self.subTest(wid=wid):
                _,_,sha,graph,cfg=self.source(int(wid.rsplit('-',1)[1]))
                fresh=reviewed_multiview_output_size({'id':wid},cfg['controls'],graph=graph,source_hash=sha)
                field=next(f for f in fresh if f['id']==contract[1]+':scale_to_length')
                self.assertEqual(field['value'],contract[2]);self.assertEqual(field['key']=='output_pixels',wid=='local-card-73')
                self.assertEqual(reviewed_multiview_output_size({'id':wid},fresh,source_hash=sha,derived={'sourceHash':sha,'controls':fresh}),fresh)
                self.assertEqual([f for f in fresh if f['id']!=field['id']],[f for f in cfg['controls']if f['id']!=field['id']])
                template=json.loads(workflow_path(wid).read_text('utf-8'));spec=manifest(wid)
                registered=next(f for f in spec['controls']if f['id']==field['id'])
                for value in (512,1024,1536,2048,4096):
                    values=validate_values(spec,{field['id']:value});result=copy.deepcopy(template)
                    for target,next_value in _control_values(registered,values[field['id']],values):_put(result,target,next_value)
                    self.assertEqual(result[contract[1]]['inputs']['scale_to_length'],value)
                    self.assertEqual(result[contract[1]]['inputs']['round_to_multiple'],'16')
                    result[contract[1]]['inputs']['scale_to_length']=contract[2]
                    self.assertEqual(result,template)


if __name__=='__main__':unittest.main()
