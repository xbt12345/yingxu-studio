"""Contract tests use synthetic reviewed graphs; no remote jobs are executed."""
import copy
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import schema_adapters
import server


def fixture():
    graph={
        'first':{'class_type':'SyntheticImage','inputs':{'seed':7,'strength':0.5,'prompt':'first','image':'old.png'}},
        'second':{'class_type':'SyntheticImage','inputs':{'seed':7,'strength':0.8,'prompt':'second','image':'old.png'}},
        'combine':{'class_type':'SyntheticCombine','inputs':{'a':['first',0],'b':['second',0]}},
        'save':{'class_type':'SaveImage','inputs':{'images':['combine',0],'filename_prefix':'old'}},
    }
    spec={'id':'card-synthetic','name':'Contract fixture','source':'synthetic.json','source_hash':'source-identity',
          'output':'image','adapter':'generic','validation':'structural-verified','template':'card-synthetic.api.json',
          'outputs':['save'],
          'controls':[
              {'id':'first:strength','key':'strength','kind':'strength','type':'number','value':0.5,'min':0,'max':1,'step':0.1,'targets':[{'node':'first','input':'strength'}]},
              {'id':'second:strength','key':'strength','kind':'strength','type':'number','value':0.8,'min':0,'max':1,'step':0.1,'targets':[{'node':'second','input':'strength'}]},
              {'id':'first:seed','key':'seed','kind':'seed','type':'number','value':7,'min':0,'max':1000,'step':1,'targets':[{'node':'first','input':'seed'},{'node':'second','input':'seed'}]},
          ],
          'texts':[
              {'id':'first:prompt','role':'prompt','key':'prompt','default':'','targets':[{'node':'first','input':'prompt'}]},
              {'id':'second:prompt','role':'prompt','key':'prompt','default':'second default','targets':[{'node':'second','input':'prompt'}]},
          ],'media':[], 'apiProfiles':[]}
    return graph,spec


class SchemaContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.graph,self.spec=fixture()
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        self.templates=patch.object(schema_adapters,'WORKFLOW_DIR',Path(self.tmp.name));self.templates.start()

    def tearDown(self):
        self.templates.stop();self.tmp.cleanup()

    def build(self,values=None,texts=None,assets=None,profiles=None):
        return schema_adapters.build(self.spec,values or {},texts or {},assets or {},profiles or {},'test-job')

    def test_same_name_controls_and_texts_do_not_overwrite_each_other(self):
        graph,values,texts=self.build({'first:strength':0.2,'second:strength':0.9},{'first:prompt':'one','second:prompt':'two'})
        self.assertEqual(graph['first']['inputs']['strength'],0.2)
        self.assertEqual(graph['second']['inputs']['strength'],0.9)
        self.assertEqual(graph['first']['inputs']['prompt'],'one')
        self.assertEqual(graph['second']['inputs']['prompt'],'two')
        self.assertEqual(values['second:strength'],0.9)
        self.assertEqual(texts['second:prompt'],'two')
        self.assertEqual(graph['save']['inputs']['filename_prefix'],'yingxu/test-job')

    def test_unknown_fields_and_invalid_types_never_become_graph_inputs(self):
        for supplied in [{'unreviewed':1},{'first:strength':True},{'first:strength':float('nan')},
                         {'first:strength':0.25},{'first:strength':10**1000},{'first:seed':1001},{'first:seed':1.5}]:
            with self.subTest(supplied=supplied),self.assertRaises(ValueError):self.build(supplied)
        with self.assertRaises(ValueError):self.build(texts={'arbitrary-node:prompt':'data'})
        with self.assertRaises(ValueError):self.build(texts={'first:prompt':[]})

    def test_integer_field_rejects_fraction_and_original_default_can_survive_widget_step(self):
        field=self.spec['controls'][0];field.update(integer=True,step='any',value=1)
        with self.assertRaises(ValueError):self.build({'first:strength':0.5})
        field.update(integer=False,step=0.05,value=0.22)
        graph,_,_=self.build()
        self.assertEqual(graph['first']['inputs']['strength'],0.22)
        with self.assertRaises(ValueError):self.build({'first:strength':0.23})

    def test_fixed_helper_instruction_survives_empty_ui_but_can_be_edited(self):
        self.spec['texts'][1]['preserveWhenEmpty']=True
        graph,_,_=self.build(texts={'second:prompt':''})
        self.assertEqual(graph['second']['inputs']['prompt'],'second')
        graph,_,_=self.build(texts={'second:prompt':'new instruction'})
        self.assertEqual(graph['second']['inputs']['prompt'],'new instruction')

    def test_numeric_step_uses_nonzero_minimum_and_preserves_source_defaults(self):
        field=self.spec['controls'][0];field.update(integer=True,min=1,max=101,step=4,value=81)
        self.assertEqual(self.build({'first:strength':85})[1]['first:strength'],85)
        with self.assertRaises(ValueError):self.build({'first:strength':84})
        field.update(integer=False,min=0.15,max=1,step=0.1,value=0.22)
        self.assertAlmostEqual(self.build({'first:strength':0.25})[1]['first:strength'],0.25)
        self.assertEqual(self.build()[1]['first:strength'],0.22)
        with self.assertRaises(ValueError):self.build({'first:strength':0.3})
        field.update(min=None,step='any',options=[0.22],customRange={'min':0.15,'max':1,'step':0.1})
        self.assertAlmostEqual(self.build({'first:strength':0.25})[1]['first:strength'],0.25)
        with self.assertRaises(ValueError):self.build({'first:strength':0.3})

    def test_numeric_ui_can_bind_reviewed_string_number_inputs(self):
        field=self.spec['controls'][0]
        field.update(integer=True,min=1,max=100,step=1,value=10,transform={'operation':'number-string'})
        graph,values,_=self.build({'first:strength':12.0})
        self.assertEqual(graph['first']['inputs']['strength'],'12')
        self.assertEqual(values['first:strength'],12.0)
        with self.assertRaises(ValueError):self.build({'first:strength':12.5})
        field.update(integer=False,min=0,max=1,step=0.1,value=0.3)
        self.assertEqual(self.build({'first:strength':0.4})[0]['first']['inputs']['strength'],'0.4')
        with self.assertRaises(ValueError):self.build({'first:strength':'0.4'})

    def test_reviewed_person_indices_allow_all_or_normalized_nonnegative_csv(self):
        field=self.spec['controls'][0]
        field.update(kind='indices',type='string',value='')
        for supplied,expected in [('', ''),('  ',''),('0,2,3','0,2,3'),(' 02 ，0,2, 3 ','2,0,3')]:
            with self.subTest(supplied=supplied):
                graph,values,_=self.build({'first:strength':supplied})
                self.assertEqual(graph['first']['inputs']['strength'],expected)
                self.assertEqual(values['first:strength'],expected)
        for supplied in ['-1','0,-2','0,','0,,2','1.5','one','true','0;2',True,0]:
            with self.subTest(supplied=supplied),self.assertRaises(ValueError):
                self.build({'first:strength':supplied})
        field.update(kind='text',value='0,0')
        self.assertEqual(self.build()[0]['first']['inputs']['strength'],'0,0')

    def test_reviewed_size_constraint_accepts_auto_side_but_rejects_two_zero_sides(self):
        self.spec['constraints']=[{'type':'nonzero-size','width':'first:strength','height':'second:strength'}]
        graph,_,_=self.build({'first:strength':0,'second:strength':0.8})
        self.assertEqual(graph['first']['inputs']['strength'],0)
        self.build({'first:strength':0.5,'second:strength':0})
        with self.assertRaisesRegex(ValueError,'不能同时为 0'):
            self.build({'first:strength':0,'second:strength':0})
        self.spec['constraints'][0]['targets']=[{'node':'private-node','input':'private-input'}]
        self.assertEqual(server.public_schema(self.spec)['constraints'],
                         [{'type':'nonzero-size','width':'first:strength','height':'second:strength'}])

    def test_key_only_api_accepts_exact_model_and_key_without_invented_url(self):
        self.graph['first']['inputs'].update(model='exact-model',apikey='')
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        self.spec['apiProfiles']=[{'id':'first','keyOnly':True,'modelOptions':['exact-model'],
                                  'bindings':{'model':{'node':'first','input':'model'},'apiKey':{'node':'first','input':'apikey'}}}]
        profile={'first':{'mode':'custom','model':'exact-model','api_key':'owner-key'}}
        graph,_,_=self.build(profiles=profile)
        self.assertEqual(graph['first']['inputs']['apikey'],'owner-key')
        self.assertNotIn('base_url',graph['first']['inputs'])
        with self.assertRaises(ValueError):self.build(profiles={'first':{**profile['first'],'model':'invented-model'}})

    def test_normalized_subject_points_replace_private_points_and_keep_size_links(self):
        self.graph['first']['inputs']['mask']=['points',0]
        self.graph['first']['inputs']['negative_points']=''
        self.graph['size']={'class_type':'SyntheticSize','inputs':{}}
        size_links={'width':['size',3],'height':['size',4]}
        self.graph['points']={'class_type':'PointsEditor','inputs':{**size_links,'coordinates':'old private points','neg_coordinates':'old negative',
                              'points_store':'old store','bboxes':'old boxes','bbox_store':'old bbox store','normalize':True}}
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        field={'id':'points:normalized','key':'points','kind':'points','type':'text','value':'{"positive":[],"negative":[]}',
               'targets':[{'node':'points','input':'coordinates'}],'transform':{'operation':'points'}}
        self.spec['controls'].append(field)
        value=json.dumps({'positive':[{'x':0.25,'y':0.5}],'negative':[{'x':1,'y':0}]})
        graph,_,_=schema_adapters.build(self.spec,{'points:normalized':value},{},{},{},'point-test',geometry={'width':1280,'height':736,'node':'points','negativeTarget':{'node':'first','input':'negative_points'}})
        inputs=graph['points']['inputs']
        self.assertEqual(json.loads(inputs['coordinates']),[{'x':320,'y':368}])
        self.assertEqual(json.loads(inputs['neg_coordinates']),[{'x':1279,'y':0}])
        self.assertEqual(inputs['width'],size_links['width']);self.assertEqual(inputs['height'],size_links['height'])
        self.assertEqual(inputs['bbox_store'],'[]');self.assertEqual(inputs['bboxes'],'[]');self.assertFalse(inputs['normalize'])
        self.assertEqual(json.loads(inputs['points_store'])['positive'],[{'x':320,'y':368}])
        self.assertEqual(graph['first']['inputs']['negative_points'],['points',1])
        for points in [{'positive':[],'negative':[]},{'positive':[{'x':1.1,'y':0}],'negative':[]},
                       {'positive':[{'x':0.5,'y':0.5}]*13,'negative':[]}]:
            with self.subTest(points=points),self.assertRaises(ValueError):schema_adapters.validate_points(json.dumps(points))

    def test_random_seed_records_the_real_value_and_updates_every_member(self):
        graph,values,_=self.build({'first:seed':-1})
        seed=values['first:seed'];self.assertGreaterEqual(seed,0);self.assertLessEqual(seed,1000)
        self.assertEqual(graph['first']['inputs']['seed'],seed)
        self.assertEqual(graph['second']['inputs']['seed'],seed)

    def test_no_description_is_valid_for_graphs_without_text_inputs(self):
        self.spec['texts']=[]
        graph,_,texts=self.build()
        self.assertEqual(texts,{})
        self.assertEqual(graph['first']['inputs']['prompt'],'first')

    def test_conversion_uses_proven_fps_and_independent_start_value(self):
        self.spec['controls'] += [
            {'id':'start','key':'start','kind':'segment','type':'number','value':2,'min':0,'targets':[{'node':'first','input':'strength'}]},
            {'id':'end','key':'end','kind':'segment','type':'number','value':5,'min':0,'targets':[{'node':'second','input':'strength'}],
             'transform':{'operation':'audio-end','startId':'start'}},
            {'id':'seconds','key':'seconds','kind':'duration','type':'number','value':1.5,'min':0,'targets':[{'node':'first','input':'seed'}],
             'transform':{'operation':'frames','fps':24}},
        ]
        graph,_,_=self.build()
        self.assertEqual(graph['second']['inputs']['strength'],3)
        self.assertEqual(graph['first']['inputs']['seed'],36)
        with self.assertRaises(ValueError):self.build({'end':1})

    def test_optional_image_socket_accepts_loader_and_absent_input_is_pruned(self):
        self.spec['media']=[{'id':'optional','kind':'image','label':'Optional','required':False,
                            'targets':[{'node':'first','input':'image','optional':True,'valueMode':'loader'}]}]
        empty,_,_=self.build()
        self.assertNotIn('image',empty['first']['inputs'])
        graph,_,_=self.build(assets={'optional':{'kind':'image','remote':'uploaded.png'}})
        loader=graph['first']['inputs']['image'][0]
        self.assertEqual(graph[loader]['inputs']['image'],'uploaded.png')
        with self.assertRaises(ValueError):self.build(assets={'optional':{'kind':'audio','remote':'wrong.wav'}})

    def test_required_and_unreviewed_optional_media_are_rejected(self):
        self.spec['media']=[{'id':'original','kind':'image','label':'原图','required':True,'targets':[{'node':'first','input':'image'}]}]
        with self.assertRaisesRegex(ValueError,'原图'):self.build()
        self.spec['media'][0]['required']=False
        with self.assertRaisesRegex(ValueError,'可选素材端口'):self.build()

    def test_blocked_graph_is_never_constructed(self):
        self.spec['validation']='blocked';self.spec['blocking_reason']='Unresolved effective branch'
        with self.assertRaisesRegex(ValueError,'Unresolved effective branch'):self.build()

    def test_rerun_keeps_private_graph_overrides_and_only_changes_seeds_prefixes_and_assets(self):
        self.spec['media']=[{'id':'original','kind':'image','label':'原图','required':True,'targets':[{'node':'first','input':'image'}]}]
        graph,values,texts=self.build(assets={'original':{'kind':'image','remote':'old.png'}})
        graph['first']['inputs']['api_key']='private-credential'
        original={'schema_spec':self.spec,'graph':graph,'catalog_values':values,'catalog_texts':texts}
        new_graph,new_values=schema_adapters.rerun(original,{'original':{'kind':'image','remote':'restored.png'}},'rerun-id')
        expected=copy.deepcopy(graph)
        expected['first']['inputs'].update(seed=new_values['first:seed'],image='restored.png')
        expected['second']['inputs']['seed']=new_values['first:seed']
        expected['save']['inputs']['filename_prefix']='yingxu/rerun-id'
        self.assertEqual(new_graph,expected)
        self.assertNotEqual(new_values['first:seed'],values['first:seed'])
        self.assertEqual(original['graph'],graph)


class SchemaServerContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.graph,self.spec=fixture()
        self.spec['texts']=[]
        (root/self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        (root/'uploads').mkdir();(root/'outputs').mkdir();(root/'receipts').mkdir()
        self.patches=[patch.object(server,'DB',root/'test.sqlite3'),patch.object(server,'PRIVATE',root),
                      patch.object(server,'BASE','http://synthetic-comfy.invalid'),
                      patch.object(schema_adapters,'WORKFLOW_DIR',root),
                      patch.object(schema_adapters,'registry',side_effect=lambda:{self.spec['id']:self.spec})]
        for p in self.patches:p.start()
        with server.database() as db:
            db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
            db.execute('CREATE TABLE assets (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.client=TestClient(server.app)
        self.body={'workflow_id':self.spec['id'],'source_hash':self.spec['source_hash'],'token':'schema-submit-once',
                   'catalog_values':{'first:strength':0.2,'second:strength':0.9,'first:seed':123},
                   'catalog_texts':{},'catalog_assets':{}}
        self.remote=Mock(status_code=200);self.remote.json.return_value={'prompt_id':'synthetic-remote-job'}

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_empty_prompt_submission_is_persisted_before_dispatch_and_is_idempotent(self):
        with patch.object(server.requests,'post',return_value=self.remote) as post:
            first=self.client.post('/api/jobs',json=self.body)
            again=self.client.post('/api/jobs',json=self.body)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['id'],again.json()['id']);self.assertEqual(post.call_count,1)
        self.assertEqual(first.json()['catalog_values']['second:strength'],0.9)
        self.assertNotIn('schema_spec',first.json())
        self.assertNotIn('graph',first.json())

    def test_source_mismatch_blocking_and_unknown_values_fail_before_remote_calls(self):
        with patch.object(server.requests,'post') as post:
            body={**self.body,'source_hash':'wrong'}
            self.assertEqual(self.client.post('/api/jobs',json=body).status_code,409)
            body={**self.body,'catalog_values':{'client:node':5}}
            self.assertEqual(self.client.post('/api/jobs',json=body).status_code,400)
            self.spec['validation']='blocked';self.spec['blocking_reason']='模型选择尚未确认'
            result=self.client.post('/api/jobs',json=self.body)
            self.assertEqual(result.status_code,400);self.assertIn('模型选择',result.json()['detail'])
            post.assert_not_called()

    def test_missing_profile_credentials_reject_before_dispatch_and_valid_overrides_submit(self):
        self.graph['first']['inputs'].update(auth='',model='exact-model')
        self.spec['apiProfiles']=[{'id':'owner-api','label':'图像服务','keyOnly':True,'modelOptions':['exact-model'],
                                  'bindings':{'apiKey':{'node':'first','input':'auth'},'model':{'node':'first','input':'model'}}}]
        path=Path(self.tmp.name,self.spec['template'])
        for linked in (False,True):
            with self.subTest(linked=linked):
                self.graph['first']['inputs']['auth']=['credential',0] if linked else ''
                self.graph['credential']={'class_type':'SyntheticText','inputs':{'value':'  '}}
                path.write_text(json.dumps(self.graph),'utf-8')
                with patch.object(server.requests,'post') as post:
                    result=self.client.post('/api/jobs',json=self.body)
                self.assertEqual(result.status_code,400)
                self.assertIn('图像服务',result.json()['detail'])
                self.assertIn('API key',result.json()['detail']);post.assert_not_called()
                self.assertEqual(server.jobs(),[])
        self.graph['credential']['inputs']['value']='synthetic-owner-key'
        path.write_text(json.dumps(self.graph),'utf-8')
        with patch.object(server.requests,'post',return_value=self.remote) as post:
            result=self.client.post('/api/jobs',json=self.body)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(post.call_count,1)
        self.graph['credential']['inputs']['value']=''
        path.write_text(json.dumps(self.graph),'utf-8')
        override={**self.body,'token':'schema-custom-key',
                  'api_profiles':{'owner-api':{'mode':'custom','model':'exact-model','api_key':'synthetic-custom-key'}}}
        with patch.object(server.requests,'post',return_value=self.remote) as post:
            result=self.client.post('/api/jobs',json=override)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(post.call_count,1)

    def test_rerun_uses_saved_contract_after_registry_changes(self):
        with patch.object(server.requests,'post',return_value=self.remote):
            first=self.client.post('/api/jobs',json=self.body).json()
        original=server.job(first['id']);original['status']='done'
        original['graph']['first']['inputs']['api_key']='private-credential';server.save(original)
        self.spec['controls']=[];self.spec['validation']='blocked'
        with patch.object(server.requests,'post',return_value=self.remote) as post:
            rerun=self.client.post('/api/jobs/'+first['id']+'/rerun',json={'token':'schema-rerun-once'})
            again=self.client.post('/api/jobs/'+first['id']+'/rerun',json={'token':'schema-rerun-once'})
        self.assertEqual(rerun.status_code,200,rerun.text)
        self.assertEqual(again.json()['id'],rerun.json()['id']);self.assertEqual(post.call_count,1)
        child=server.job(rerun.json()['id'])
        self.assertNotEqual(child['catalog_values']['first:seed'],123)
        self.assertEqual(child['graph']['first']['inputs']['api_key'],'private-credential')
        self.assertEqual(child['catalog_values']['second:strength'],0.9)

    def test_audio_upload_validates_actual_audio_frames(self):
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*1600)
        response=Mock(status_code=200);response.json.return_value={'name':'audio.wav','subfolder':''}
        with patch.object(server.requests,'post',return_value=response) as post:
            valid=self.client.post('/api/assets',files={'file':('audio.wav',stream.getvalue(),'audio/wav')})
            invalid=self.client.post('/api/assets',files={'file':('invalid.wav',b'not audio','audio/wav')})
        self.assertEqual(valid.status_code,200,valid.text);self.assertEqual(valid.json()['kind'],'audio')
        self.assertEqual(invalid.status_code,400);self.assertEqual(post.call_count,1)

    def test_text_output_is_saved_and_served_without_remote_download(self):
        graph=copy.deepcopy(self.graph)
        j={'id':'text-result','token':'text-result-token','workflow_id':self.spec['id'],'status':'running',
           'graph':graph,'schema_spec':{**self.spec,'output':'text','outputs':['save']},'settings':{},'asset_ids':[]}
        server.save(j)
        with patch.object(server.requests,'get') as get:
            server.collect(j,{'outputs':{'save':{'text':['第一段','第二段']}},'status':{'completed':True}})
            get.assert_not_called()
        result=self.client.get('/api/jobs/text-result').json()
        self.assertEqual(result['status'],'done');self.assertEqual(result['outputs'][0]['type'],'text')
        self.assertEqual(result['outputs'][0]['text'],'第一段\n第二段')
        self.assertEqual(self.client.get(result['outputs'][0]['src']).content,'第一段\n第二段'.encode())

    def test_output_types_follow_real_suffix_and_preview_nodes_are_excluded(self):
        h={'outputs':{'save':{'gifs':[{'filename':'animated.gif','type':'output'},{'filename':'clip.webm','type':'output'}],
                                  'audio':[{'filename':'voice.wav','type':'output'}]},
                      'preview':{'images':[{'filename':'unwanted.png','type':'output'}]}}}
        items=server.output_items(h,'video',['save'])
        self.assertEqual([item['kind']for item in items],['image','video','audio'])

    def test_registered_preview_temporary_outputs_are_retained_but_inputs_are_not(self):
        h={'outputs':{'preview':{'images':[{'filename':'generated.png','type':'temp'},
                                          {'filename':'source.png','type':'input'}]},
                      'unregistered':{'images':[{'filename':'other.png','type':'temp'}]}}}
        items=server.output_items(h,'image',['preview'])
        self.assertEqual([item['filename']for item in items],['generated.png'])
        self.assertEqual(server.output_items(h,'image'),[])

    def test_linked_credential_is_removed_from_public_workflow(self):
        graph={'key':{'class_type':'PrimitiveString','inputs':{'value':'non-sk-sensitive-key'}},
               'api':{'class_type':'SyntheticAPI','inputs':{'api_key':['key',0],'prompt':'safe text'}}}
        public=server.public_graph(graph)
        self.assertEqual(public['key']['inputs']['value'],'[请填写自己的密钥]')
        self.assertEqual(public['api']['inputs']['prompt'],'safe text')
        self.assertEqual(graph['key']['inputs']['value'],'non-sk-sensitive-key')

    def test_connection_metadata_carries_supported_fields_without_execution_secrets(self):
        self.spec['apiProfiles']=[{'id':'first','api_key':'must-not-leak','baseUrl':'https://user:password@api.example.test/v1?token=secret',
                                  'model':'exact-model','bindings':{'apiKey':{'node':'first','input':'api_key'}}}]
        metadata=server.public_schema(self.spec)
        self.assertEqual(metadata['supportedControlIds'],[f['id']for f in self.spec['controls']])
        self.assertNotIn('targets',metadata['controls'][0])
        self.assertNotIn('bindings',metadata['apiProfiles'][0])
        self.assertNotIn('api_key',metadata['apiProfiles'][0])
        self.assertEqual(metadata['apiProfiles'][0]['baseUrl'],'https://api.example.test/v1')

    def test_point_preview_recipe_is_forwarded_without_real_execution_targets(self):
        self.spec['controls'][0].update(mediaSlotId='video',previewRecipe={'longSideControlId':'size','longSide':1280,'multiple':32,'sourceMultiple':8,'fit':'crop','frameRate':24,
                                                                         'targets':[{'node':'private-node','input':'private-input'}]})
        field=server.public_schema(self.spec)['controls'][0]
        self.assertEqual(field['mediaSlotId'],'video')
        self.assertEqual(field['previewRecipe'],{'longSideControlId':'size','longSide':1280,'multiple':32,'sourceMultiple':8,'fit':'crop','frameRate':24})
        self.assertNotIn('targets',field)

    def test_subject_point_resize_uses_actual_video_dimensions_and_layerstyle_rounding(self):
        self.spec['pointsRecipe']={'slotId':'video','longSideControlId':'size','longSide':1280,'multiple':32,'node':'points'}
        container=Mock();container.streams=[Mock(type='video',width=1920,height=1080)]
        opened=Mock();opened.__enter__=Mock(return_value=container);opened.__exit__=Mock(return_value=False)
        with patch.object(server,'asset_file',return_value=Path('synthetic.mp4')),patch.object(server.av,'open',return_value=opened):
            geometry=server.points_geometry(self.spec,{}, {'video':{'kind':'video'}})
            resized=server.points_geometry(self.spec,{'size':1024}, {'video':{'kind':'video'}})
        self.assertEqual(geometry,{'width':1280,'height':736,'node':'points'})
        self.assertEqual(resized,{'width':1024,'height':576,'node':'points'})

    def test_subject_point_resize_matches_vhs_nearest_multiple_for_irregular_video(self):
        self.spec['pointsRecipe']={'slotId':'video','longSide':1280,'multiple':32,'sourceMultiple':8,'node':'points'}
        # Without VHS this 601px short side crosses LayerStyle's next 32px
        # boundary. VHS first reduces it to 600px, so the target stays 640px.
        container=Mock();container.streams=[Mock(type='video',width=1200,height=601)]
        opened=Mock();opened.__enter__=Mock(return_value=container);opened.__exit__=Mock(return_value=False)
        with patch.object(server,'asset_file',return_value=Path('synthetic.mp4')),patch.object(server.av,'open',return_value=opened):
            geometry=server.points_geometry(self.spec,{}, {'video':{'kind':'video'}})
        self.assertEqual(geometry,{'width':1280,'height':640,'node':'points'})


if __name__=='__main__':unittest.main(verbosity=2)
