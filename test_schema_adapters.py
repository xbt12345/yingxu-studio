"""Contract tests use synthetic reviewed graphs; no remote jobs are executed."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from fractions import Fraction
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import schema_adapters
import server
from reviewed_repairs import apply_reviewed_repairs, ReviewedRepairError, VIDEO_CHAINS, SOURCE_HASHES


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

    def test_explicitly_disabled_option_cannot_be_submitted(self):
        self.spec['controls'][0]['options']=[{'value':0.2,'disabled':True,'reason':'手工掩膜桥接尚未接入'},0.5]
        with self.assertRaisesRegex(ValueError,'手工掩膜桥接尚未接入'):
            self.build({'first:strength':0.2})
        self.assertEqual(self.build()[1]['first:strength'],0.5)

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
        corrected,_,_=schema_adapters.build(self.spec,{'points:normalized':json.dumps({'positive':[{'x':.22,'y':.16}],
                                                                                   'negative':[{'x':.72,'y':.56}]})},
                                             {},{},{},'corrected-points',geometry={'width':256,'height':144,'node':'points','bindDimensions':True})
        corrected_inputs=corrected['points']['inputs']
        self.assertEqual((corrected_inputs['width'],corrected_inputs['height']),(256,144))
        self.assertEqual(json.loads(corrected_inputs['coordinates']),[{'x':56,'y':23}])
        self.assertEqual(json.loads(corrected_inputs['neg_coordinates']),[{'x':184,'y':81}])
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
             'transform':{'operation':'audio-end','startId':'start','nativeBounds':{'min':0,'max':1e17}}},
            {'id':'seconds','key':'seconds','kind':'duration','type':'number','value':1.5,'min':0,'targets':[{'node':'first','input':'seed'}],
             'transform':{'operation':'frames','fps':24,'nativeBounds':{'min':0,'max':9007199254740991}}},
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


class AudioCropContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.graph={
            'audio':{'class_type':'SyntheticAudio','inputs':{}},
            'crop':{'class_type':'AudioCrop','inputs':{'audio':['audio',0],'start_time':'0:00','end_time':'10'}},
            'save':{'class_type':'SaveAudio','inputs':{'audio':['crop',0],'filename_prefix':'old'}},
        }
        self.spec={'id':'audio-interval-fixture','adapter':'generic','validation':'structural-verified',
                   'template':'audio-interval-fixture.api.json','outputs':['save'],'media':[],'texts':[],
                   'controls':[{'id':'start','kind':'segment','type':'text','value':'0:00','targets':[{'node':'crop','input':'start_time'}]},
                               {'id':'end','kind':'segment','type':'text','value':'10','targets':[{'node':'crop','input':'end_time'}]}]}
        self.templates=patch.object(schema_adapters,'WORKFLOW_DIR',Path(self.tmp.name));self.templates.start()

    def tearDown(self):
        self.templates.stop();self.tmp.cleanup()

    def build(self,values=None):
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        return schema_adapters.build(self.spec,values or {},{},{},{},'audio-interval-test')

    def test_seconds_minutes_and_source_defaults_are_preserved(self):
        for start,end in [('0:00','10'),('0:10','0:23'),('60','1:02'),(' 0 : 05 ',' 10 '),('0:0','0:120')]:
            with self.subTest(start=start,end=end):
                graph,values,_=self.build({'start':start,'end':end})
                self.assertEqual(graph['crop']['inputs']['start_time'],start)
                self.assertEqual(graph['crop']['inputs']['end_time'],end)
                self.assertEqual(values,{'start':start,'end':end})

    def test_zero_end_empty_and_inverse_intervals_are_rejected(self):
        for start,end in [('0','0'),('0:02','0:01'),('0:02','0'),('0:02','0:02')]:
            with self.subTest(start=start,end=end),self.assertRaisesRegex(ValueError,'终点需要晚于起点'):
                self.build({'start':start,'end':end})
        self.build({'start':'0','end':'1'})

    def test_invalid_audio_time_formats_fail_before_remote_execution(self):
        for time in ['-1','0:-1','0.5','00:00:01','five','', '1e3']:
            with self.subTest(time=time),self.assertRaisesRegex(ValueError,'非负整数秒'):
                self.build({'end':time})

    def test_shared_end_is_checked_against_both_speaker_starts(self):
        self.graph['end']={'class_type':'easy string','inputs':{'value':'0:5'}}
        self.graph['crop']['inputs']['end_time']=['end',0]
        self.graph['crop2']={'class_type':'AudioCrop','inputs':{'audio':['audio',0],'start_time':'0:03','end_time':['end',0]}}
        self.graph['combine']={'class_type':'SyntheticAudioCombine','inputs':{'first':['crop',0],'second':['crop2',0]}}
        self.graph['save']['inputs']['audio']=['combine',0]
        self.spec['controls'][1].update(value='0:5',targets=[{'node':'end','input':'value'}])
        self.spec['controls'].append({'id':'second-start','kind':'segment','type':'text','value':'0:03',
                                     'targets':[{'node':'crop2','input':'start_time'}]})
        with self.assertRaisesRegex(ValueError,'终点需要晚于起点'):
            self.build({'end':'0:02'})
        graph,_,_=self.build({'end':'0:02','second-start':'0:01'})
        self.assertEqual(graph['end']['inputs']['value'],'0:02')
        self.assertEqual(graph['crop']['inputs']['end_time'],['end',0])
        self.assertEqual(graph['crop2']['inputs']['end_time'],['end',0])

    def test_unknown_time_expression_cannot_bypass_interval_validation(self):
        self.graph['end']={'class_type':'SyntheticUnknownString','inputs':{'value':'0:05'}}
        self.graph['crop']['inputs']['end_time']=['end',0]
        self.spec['controls'][1]['targets']=[{'node':'end','input':'value'}]
        with self.assertRaisesRegex(ValueError,'绑定尚未完成审查'):
            self.build()

    def test_unreachable_crop_and_utk_zero_duration_do_not_change_semantics(self):
        self.graph['unused']={'class_type':'AudioCrop','inputs':{'start_time':'0:02','end_time':'0'}}
        graph,_,_=self.build()
        self.assertNotIn('unused',graph)
        utk={'utk':{'class_type':'AudioCropProcessUTK','inputs':{'offset_seconds':2,'duration_seconds':0}}}
        original=copy.deepcopy(utk)
        schema_adapters.validate_audio_crops(utk)
        self.assertEqual(utk,original)

    def test_saved_graph_rerun_cannot_bypass_crop_validation(self):
        graph,values,texts=self.build()
        original={'schema_spec':self.spec,'graph':graph,'catalog_values':values,'catalog_texts':texts}
        rerun,rerun_values=schema_adapters.rerun(original,{},'retry',randomize_seed=False)
        self.assertEqual(rerun_values,values)
        self.assertEqual(rerun['crop']['inputs'],graph['crop']['inputs'])
        original['graph']['crop']['inputs']['end_time']='0'
        with self.assertRaisesRegex(ValueError,'终点需要晚于起点'):
            schema_adapters.rerun(original,{},'invalid-retry',randomize_seed=False)


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

    def video_fixture(self,with_audio=False):
        path=server.PRIVATE/'uploads'/'fixture.mp4'
        with server.av.open(str(path),'w')as output:
            video=output.add_stream('libx264',rate=12);video.width=126;video.height=62;video.pix_fmt='yuv420p'
            if with_audio:
                audio=output.add_stream('aac',rate=48000);audio.layout='stereo'
            for index in range(16):
                frame=server.av.VideoFrame(126,62,'yuv420p');frame.pts=index;frame.time_base=Fraction(1,12)
                for plane in frame.planes:plane.update(bytes([30+index])*plane.buffer_size)
                for packet in video.encode(frame):output.mux(packet)
            for packet in video.encode():output.mux(packet)
            if with_audio:
                for start in range(0,64000,1024):
                    frame=server.av.AudioFrame('fltp','stereo',min(1024,64000-start))
                    frame.pts=start;frame.time_base=Fraction(1,48000);frame.sample_rate=48000
                    for plane in frame.planes:plane.update(bytes(plane.buffer_size))
                    for packet in audio.encode(frame):output.mux(packet)
                for packet in audio.encode():output.mux(packet)
        data=path.read_bytes();key=hashlib.sha256(data).hexdigest();path.replace(path.parent/(key+'.mp4'))
        record=dict(id=key,kind='video',name='source.mp4',bytes=len(data),remote='source.mp4')
        with server.database()as db:db.execute('INSERT OR REPLACE INTO assets VALUES (?,?)',(key,json.dumps(record)))
        return record

    def vhs_fixture(self):
        self.spec['media']=[{'id':'source','kind':'video','required':True,'targets':[{'node':'source','input':'video'}]}]
        self.graph['source']={'class_type':'VHS_LoadVideo','inputs':{'video':'old.mp4'}}
        self.graph['first']['inputs']['image']=['source',0]
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')

    def test_vhs_silent_derivative_preserves_video_packets_decoded_frames_and_original(self):
        source=self.video_fixture();original=server.asset_file(source).read_bytes()
        def decoded(path):
            with server.av.open(str(path))as container:
                return [(frame.pts*frame.time_base,frame.width,frame.height,
                         hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest())for frame in container.decode(video=0)]
        with patch.object(server.requests,'post')as post:
            derived=server.vhs_audio_asset(source)
            cached=server.vhs_audio_asset(server.asset(source['id']))
            post.assert_not_called()
        self.assertNotEqual(source['id'],derived['id']);self.assertEqual(cached['id'],derived['id'])
        self.assertEqual(server.asset_file(source).read_bytes(),original)
        self.assertEqual(server.video_packet_signature(server.asset_file(source)),server.video_packet_signature(server.asset_file(derived)))
        self.assertEqual(decoded(server.asset_file(source)),decoded(server.asset_file(derived)))
        with server.av.open(str(server.asset_file(source)))as before,server.av.open(str(server.asset_file(derived)))as after:
            self.assertEqual(before.duration,after.duration);self.assertEqual(after.streams.audio[0].codec_context.name,'aac')
            self.assertGreater(sum(frame.samples for frame in after.decode(audio=0)),0)
        self.assertEqual(list((server.PRIVATE/'uploads').glob('.vhs-silent-*')),[])

    def test_vhs_sound_bearing_source_is_unchanged_and_other_loaders_are_not_adapted(self):
        source=self.video_fixture(with_audio=True);before=server.asset_file(source).read_bytes()
        self.assertIs(server.vhs_audio_asset(source),source)
        self.assertEqual(server.asset_file(source).read_bytes(),before)
        self.assertNotIn('vhs_silent_asset',server.asset(source['id']))
        self.vhs_fixture();self.graph['source']['class_type']='OtherVideoLoader'
        with patch.object(server,'vhs_audio_asset')as adapt:
            self.assertEqual(server.schema_vhs_assets(self.spec,{'source':source},self.graph),{'source':source});adapt.assert_not_called()

    def test_vhs_submission_and_rerun_use_derivative_but_keep_original_reference(self):
        source=self.video_fixture();self.vhs_fixture()
        body={**self.body,'catalog_assets':{'source':source['id']}}
        with patch.object(server,'ensure_remote',side_effect=lambda record:{**record,'remote':'remote-'+record['id']+'.mp4'})as transfer,patch.object(server.requests,'post',return_value=self.remote)as post:
            response=self.client.post('/api/jobs',json=body)
            self.assertEqual(response.status_code,200,response.text)
            original=server.job(response.json()['id']);original['status']='done';server.save(original)
            rerun=self.client.post('/api/jobs/'+original['id']+'/rerun',json={'token':'vhs-schema-rerun'})
            self.assertEqual(rerun.status_code,200,rerun.text);self.assertEqual(post.call_count,2)
        derivative=server.asset(source['id'])['vhs_silent_asset']
        self.assertEqual([call.args[0]['id']for call in transfer.call_args_list],[derivative,derivative])
        child=server.job(rerun.json()['id'])
        for result in (original,child):
            self.assertEqual(result['graph']['source']['inputs']['video'],'remote-'+derivative+'.mp4')
            self.assertEqual(result['catalog_assets'],{'source':source['id']});self.assertEqual(result['asset_ids'],[source['id']])
        self.assertEqual(response.json()['references'][0]['id'],source['id'])

    def test_vhs_failed_packet_preservation_rejects_before_upload_or_gpu_dispatch(self):
        source=self.video_fixture();self.vhs_fixture()
        signature=server.video_packet_signature(server.asset_file(source))
        with patch.object(server,'video_packet_signature',side_effect=[signature,(*signature[:-1],'changed')]),patch.object(server,'ensure_remote')as transfer,patch.object(server.requests,'post')as post:
            response=self.client.post('/api/jobs',json={**self.body,'catalog_assets':{'source':source['id']}})
        self.assertEqual(response.status_code,400,response.text);self.assertIn('无损',response.json()['detail'])
        transfer.assert_not_called();post.assert_not_called();self.assertEqual(server.jobs(),[])
        self.assertNotIn('vhs_silent_asset',server.asset(source['id']))
        self.assertEqual(list((server.PRIVATE/'uploads').glob('.vhs-silent-*')),[])

    def test_derived_asset_uploads_without_a_preexisting_remote_path(self):
        derived=server.vhs_audio_asset(self.video_fixture())
        upload=Mock(status_code=200);upload.json.return_value={'name':'silent-derivative.mp4','subfolder':''}
        with patch.object(server.requests,'get')as get,patch.object(server.requests,'post',return_value=upload)as post:
            restored=server.ensure_remote(derived)
        get.assert_not_called();self.assertEqual(post.call_count,1)
        self.assertEqual(post.call_args.args[0],server.BASE+'/upload/image')
        self.assertEqual(restored['remote'],'silent-derivative.mp4')
        self.assertEqual(server.asset(derived['id'])['remote'],restored['remote'])

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

    def test_seedvr2_invalid_short_edge_rejected_before_asset_lookup_or_remote_call(self):
        spec=json.loads((Path(__file__).parent/'workflows/compiled-registry.json').read_text('utf-8'))['workflows']['local-card-122']
        self.spec=copy.deepcopy(spec)
        for value in (1,15,17,16385,16386,1080.5):
            with self.subTest(short_edge=value),patch.object(server,'asset')as asset,patch.object(server,'ensure_remote')as upload,patch.object(server.requests,'post')as post:
                response=self.client.post('/api/jobs',json={
                    'workflow_id':self.spec['id'],'source_hash':self.spec['source_hash'],
                    'token':f'invalid-seedvr2-{value}','catalog_values':{'34:value':value},
                    'catalog_texts':{},'catalog_assets':{}})
                self.assertEqual(response.status_code,400,response.text)
                self.assertIn('输出短边',response.json()['detail'])
                asset.assert_not_called();upload.assert_not_called();post.assert_not_called()
        with server.database()as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
        for value in (16,1080,1082,16384):
            self.assertEqual(schema_adapters.validate_values(self.spec,{'34:value':value})['34:value'],value)

    def test_uploaded_inpaint_sources_require_alpha_before_remote_dispatch(self):
        self.spec['media']=[{'id':'source','kind':'image','required':True,'targets':[{'node':'source','input':'image'}]}]
        self.graph['source']={'class_type':'LoadImage','inputs':{'image':'old.png'}}
        self.graph['mask-preview']={'class_type':'MaskPreview','inputs':{'mask':['source',1]}}
        self.graph['resize']={'class_type':'LayerUtility: ImageScaleByAspectRatio V2',
                              'inputs':{'image':['source',0],'mask':['mask-preview',0]}}
        self.graph['first']['inputs']['model']=['inpaint',0]
        for consumer in ('AnimaLLLiteApply','ZImageFunControlnet'):
            self.graph['inpaint']={'class_type':consumer,'inputs':{'mask':['resize',1]}}
            Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
            for marked in (False,True):
                with self.subTest(consumer=consumer,marked=marked):
                    key=('1'if marked else'0')*64
                    file=server.PRIVATE/'uploads'/(key+'.png')
                    image=server.Image.new('RGBA',(32,32),(80,120,160,255))
                    if marked:image.putpixel((16,16),(80,120,160,0))
                    image.save(file)
                    record={'id':key,'kind':'image','name':'source.png','bytes':file.stat().st_size,'remote':'source.png'}
                    with server.database()as db:
                        db.execute('INSERT OR REPLACE INTO assets VALUES (?,?)',(key,json.dumps(record)))
                    body={**self.body,'token':f'mask-{consumer}-{marked}','catalog_assets':{'source':key}}
                    with patch.object(server,'ensure_remote',side_effect=lambda a:a)as transfer,patch.object(server.requests,'post',return_value=self.remote)as post:
                        response=self.client.post('/api/jobs',json=body)
                    self.assertEqual(response.status_code,200 if marked else 400,response.text)
                    self.assertEqual(post.call_count,int(marked));self.assertEqual(transfer.call_count,int(marked))
                    if not marked:self.assertIn('编辑区域',response.json()['detail'])

    def test_opaque_segmentation_source_does_not_require_an_edit_mask(self):
        self.spec['media']=[{'id':'source','kind':'image','required':True,'targets':[{'node':'source','input':'image'}]}]
        self.graph['source']={'class_type':'LoadImage','inputs':{'image':'old.png'}}
        self.graph['segmentation']={'class_type':'LayerMask: BiRefNetUltraV2','inputs':{'image':['source',0]}}
        # A mask-only preview outside the selected outputs must not create a
        # requirement either; the actual result is automatic segmentation.
        self.graph['unused-inpaint']={'class_type':'ZImageFunControlnet','inputs':{'mask':['source',1]}}
        self.graph['first']['inputs']['image']=['segmentation',0]
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        key='2'*64;file=server.PRIVATE/'uploads'/(key+'.png')
        server.Image.new('RGB',(32,32),(80,120,160)).save(file)
        record={'id':key,'kind':'image','name':'source.png','bytes':file.stat().st_size,'remote':'source.png'}
        with server.database()as db:db.execute('INSERT INTO assets VALUES (?,?)',(key,json.dumps(record)))
        body={**self.body,'catalog_assets':{'source':key}}
        with patch.object(server,'ensure_remote',side_effect=lambda a:a),patch.object(server.requests,'post',return_value=self.remote)as post:
            response=self.client.post('/api/jobs',json=body)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(post.call_count,1)

    def test_unconnected_manual_preview_bridge_is_rejected_before_dispatch(self):
        self.spec['controls'].append({'id':'bridge:index','key':'index','kind':'mask','type':'number','value':2,
                                      'min':0,'max':2,'step':1,'targets':[{'node':'switch','input':'index'}]})
        self.graph['bridge']={'class_type':'PreviewBridge','inputs':{'images':['second',0],'image':'$bridge-0','block':False,'restore_mask':'never'}}
        self.graph['switch']={'class_type':'easy anythingIndexSwitch','inputs':{'index':2,'value1':['bridge',1],'value2':['second',0]}}
        self.graph['first']['inputs']['mask']=['switch',0]
        Path(self.tmp.name,self.spec['template']).write_text(json.dumps(self.graph),'utf-8')
        body={**self.body,'catalog_values':{**self.body['catalog_values'],'bridge:index':1}}
        with patch.object(server.requests,'post')as post:
            response=self.client.post('/api/jobs',json=body)
        self.assertEqual(response.status_code,400,response.text);self.assertIn('MaskEditor',response.json()['detail'])
        post.assert_not_called();self.assertEqual(server.jobs(),[])
        for selected in (0,2):
            body.update(token=f'bridge-auto-{selected}',catalog_values={**self.body['catalog_values'],'bridge:index':selected})
            with patch.object(server.requests,'post',return_value=self.remote)as post:
                response=self.client.post('/api/jobs',json=body)
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(post.call_count,1)

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

    def test_retry_preserves_actual_seeds_and_graph_while_redraw_still_randomizes(self):
        with patch.object(server.requests,'post',return_value=self.remote):
            first=self.client.post('/api/jobs',json=self.body).json()
        original=server.job(first['id']);original['status']='failed';server.save(original)
        with patch.object(schema_adapters,'_random_seed')as random,patch.object(server.requests,'post',return_value=self.remote)as post:
            retry=self.client.post('/api/jobs/'+original['id']+'/rerun',json={'token':'exact-schema-retry','randomize_seed':False})
            self.assertEqual(retry.status_code,200,retry.text);self.assertEqual(post.call_count,1);random.assert_not_called()
        child=server.job(retry.json()['id']);expected=copy.deepcopy(original['graph'])
        expected['save']['inputs']['filename_prefix']='yingxu/'+child['id']
        self.assertEqual(child['graph'],expected);self.assertEqual(child['catalog_values'],original['catalog_values'])
        with patch.object(server.requests,'post',return_value=self.remote):
            redraw=self.client.post('/api/jobs/'+original['id']+'/rerun',json={'token':'schema-redraw','randomize_seed':True})
        self.assertEqual(redraw.status_code,200,redraw.text)
        self.assertNotEqual(server.job(redraw.json()['id'])['catalog_values']['first:seed'],original['catalog_values']['first:seed'])
        with patch.object(server.requests,'post')as post:
            bad=self.client.post('/api/jobs/'+original['id']+'/rerun',json={'token':'invalid-retry-bool','randomize_seed':'false'})
        self.assertEqual(bad.status_code,422);post.assert_not_called()

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

    def test_paired_mask_upload_preserves_source_rgb_and_both_mask_encodings(self):
        for encoding in ('transparent-white','opaque-gray'):
            with self.subTest(encoding=encoding):
                source=server.Image.new('RGBA',(3,1))
                pixels=[(11+(encoding=='opaque-gray'),22,33,255),(44,55,66,128),(77,88,99,200)]
                source.putdata(pixels);original=io.BytesIO();source.save(original,format='PNG')
                mask=server.Image.new('RGBA',(3,1))
                mask.putdata([(255,255,255,255),(255,255,255,128),(255,255,255,0)]if encoding=='transparent-white'
                             else[(255,255,255,255),(128,128,128,255),(0,0,0,255)])
                mask_bytes=io.BytesIO();mask.save(mask_bytes,format='PNG')
                captured={}
                remote=Mock(status_code=200);remote.json.return_value={'name':'uploaded.png','subfolder':''}
                def transfer(*args,**kwargs):
                    name,stream,content_type=kwargs['files']['image']
                    captured.update(data=stream.read(),name=name,content_type=content_type)
                    return remote
                with patch.object(server.requests,'post',side_effect=transfer)as post:
                    response=self.client.post('/api/assets',files={'file':('original.png',original.getvalue(),'application/octet-stream'),
                                                                 'mask':('mask.png',mask_bytes.getvalue(),'image/png')})
                self.assertEqual(response.status_code,200,response.text);self.assertEqual(post.call_count,1)
                self.assertEqual(captured['content_type'],'image/png');self.assertTrue(captured['name'].endswith('.png'))
                self.assertEqual(response.json()['id'],hashlib.sha256(captured['data']).hexdigest())
                self.assertEqual(response.json()['bytes'],len(captured['data']))
                with server.Image.open(io.BytesIO(captured['data']))as result:
                    self.assertEqual([result.getpixel((x,0))[:3]for x in range(3)],[p[:3]for p in pixels])
                    self.assertEqual([result.getpixel((x,0))[3]for x in range(3)],[0,63,200])
                self.assertEqual(self.client.get('/api/assets/'+response.json()['id']+'/file').content,captured['data'])

    def test_invalid_or_oversized_mask_never_reaches_remote_upload(self):
        source=io.BytesIO();server.Image.new('RGB',(3,1),(11,22,33)).save(source,format='PNG')
        wrong_size=io.BytesIO();server.Image.new('L',(4,1),255).save(wrong_size,format='PNG')
        oversized=io.BytesIO();server.Image.new('L',(4473,4473),0).save(oversized,format='PNG')
        for filename,data,status in [('mask.png',b'broken',400),('mask.png',wrong_size.getvalue(),400),
                                     ('mask.mp4',b'not image',400),('mask.png',oversized.getvalue(),413)]:
            with self.subTest(filename=filename,status=status),patch.object(server.requests,'post')as post:
                response=self.client.post('/api/assets',files={'file':('source.png',source.getvalue(),'image/png'),
                                                             'mask':(filename,data,'application/octet-stream')})
                self.assertEqual(response.status_code,status,response.text);post.assert_not_called()
        with patch.object(server.requests,'post')as post:
            response=self.client.post('/api/assets',files={'file':('source.mp4',b'0000ftypnot-a-real-movie','video/mp4'),
                                                         'mask':('mask.png',wrong_size.getvalue(),'image/png')})
            self.assertEqual(response.status_code,400,response.text);self.assertIn('图片原图',response.json()['detail']);post.assert_not_called()

    def paired_source_fixture(self):
        source=server.Image.new('RGB',(3,1));source.putdata([(11,22,33),(44,55,66),(77,88,99)])
        source_bytes=io.BytesIO();source.save(source_bytes,format='PNG')
        mask=server.Image.new('RGBA',(3,1));mask.putdata([(255,255,255,255),(255,255,255,128),(255,255,255,0)])
        mask_bytes=io.BytesIO();mask.save(mask_bytes,format='PNG')
        files={'file':('original.png',source_bytes.getvalue(),'image/png'),'mask':('mask.png',mask_bytes.getvalue(),'image/png')}
        return source_bytes.getvalue(),files

    def test_paired_upload_retains_independent_original_and_projects_provenance_to_jobs(self):
        source,files=self.paired_source_fixture();remote=Mock(status_code=200)
        remote.json.return_value={'name':'paired.png','subfolder':'private-input-path'}
        with patch.object(server.requests,'post',return_value=remote)as post:
            response=self.client.post('/api/assets',files=files)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(post.call_count,1)
        paired=response.json();original_id=hashlib.sha256(source).hexdigest()
        self.assertNotEqual(paired['id'],original_id)
        self.assertEqual(paired['original_asset_id'],original_id);self.assertEqual(paired['annotation_mode'],'mask')
        self.assertTrue(paired['original_available']);self.assertEqual(paired['original_src'],'/api/assets/'+original_id+'/file')
        self.assertEqual(self.client.get(paired['original_src']).content,source)
        original=server.asset(original_id);self.assertNotIn('remote',original)
        self.assertNotIn('original_asset_id',server.public_asset(original))
        self.assertNotIn('remote',paired);self.assertNotIn('private-input-path',json.dumps(paired))
        saved={'id':'paired-reference-job','token':'paired-reference-token','workflow_id':self.spec['id'],
               'asset_ids':[paired['id']],'schema_spec':{**self.spec,'media':[{'id':'source'}]}}
        server.save(saved);reference=self.client.get('/api/jobs/'+saved['id']).json()['references'][0]
        for key in ('original_asset_id','original_src','original_available','annotation_mode'):
            self.assertEqual(reference[key],paired[key])
        # The unmasked original has no remote copy yet; direct reuse uploads it
        # once instead of crashing on a missing remote key or mislabeling it.
        with patch.object(server.requests,'post',return_value=remote)as post,patch.object(server.requests,'get')as get:
            original_upload=self.client.post('/api/assets',files={'file':('original.png',source,'image/png')})
        self.assertEqual(original_upload.status_code,200,original_upload.text);self.assertEqual(post.call_count,1);get.assert_not_called()
        self.assertEqual(original_upload.json()['id'],original_id);self.assertNotIn('annotation_mode',original_upload.json())

    def test_cached_pair_keeps_original_metadata_and_missing_source_is_explicit(self):
        source,files=self.paired_source_fixture();remote=Mock(status_code=200);remote.json.return_value={'name':'paired.png','subfolder':''}
        with patch.object(server.requests,'post',return_value=remote):
            first=self.client.post('/api/assets',files=files).json()
        available=Mock(status_code=200);available.__enter__=Mock(return_value=available);available.__exit__=Mock(return_value=False)
        with patch.object(server.requests,'get',return_value=available),patch.object(server.requests,'post')as post:
            cached=self.client.post('/api/assets',files=files)
        self.assertEqual(cached.status_code,200,cached.text);post.assert_not_called()
        self.assertEqual(cached.json()['original_src'],first['original_src']);self.assertTrue(cached.json()['original_available'])
        server.asset_file(server.asset(first['original_asset_id'])).unlink()
        projected=server.public_asset(server.asset(first['id']))
        self.assertFalse(projected['original_available']);self.assertEqual(projected['original_src'],'')
        self.assertEqual(projected['original_asset_id'],first['original_asset_id']);self.assertEqual(projected['annotation_mode'],'mask')

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

    def card51_output_fixture(self):
        graph=json.loads((server.ROOT/'workflows/api/local-card-51.api.json').read_text('utf-8'))
        nodes=['939','948','949','955','1048','1049']
        j=dict(id='reviewed-videos',token='reviewed-videos-token',workflow_id='local-card-51',status='running',
               graph=graph,schema_spec={'id':'local-card-51','output':'video','outputs':nodes},settings={},asset_ids=[])
        history={'outputs':{node:{'images'if node in ('948','949')else'gifs':
                                    [{'filename':node+'.mp4','type':'temp'if node=='1048'else'output','subfolder':'generated'}]}
                            for node in reversed(nodes)},'status':{'completed':True}}
        return j,history

    def test_card51_collection_presents_main_results_before_labeled_previews(self):
        j,history=self.card51_output_fixture();server.save(j)
        data=server.asset_file(self.video_fixture()).read_bytes()
        remote=Mock(status_code=200);remote.__enter__=Mock(return_value=remote);remote.__exit__=Mock(return_value=False)
        remote.iter_content.return_value=[data]
        with patch.object(server.requests,'get',return_value=remote)as get:
            server.collect(j,history)
        result=self.client.get('/api/jobs/'+j['id']).json();outputs=result['outputs']
        self.assertEqual(result['status'],'done');self.assertEqual(get.call_count,6)
        self.assertEqual([o['output_node']for o in outputs],['948','949','939','955','1049','1048'])
        self.assertEqual([o['role']for o in outputs],['result','result','comparison','comparison','control','mask'])
        self.assertEqual([o['label']for o in outputs],['生成视频 · 放大精修','生成视频 · 首次结果',
                         '对比预览 · 原片 / 控制图 / 放大精修','对比预览 · 原片 / 控制图 / 首次结果','控制视频预览','主体掩膜预览'])
        self.assertEqual([o['id']for o in outputs],[j['id']+'o'+str(i)for i in [1,2,0,3,5,4]])
        self.assertEqual([o['src']for o in outputs],['/api/media/'+j['id']+'/'+str(i)+'.mp4'for i in [1,2,0,3,5,4]])
        self.assertTrue(all((server.PRIVATE/'outputs'/j['id']/(str(i)+'.mp4')).is_file()for i in range(6)))

    def test_historical_output_presentation_is_metadata_only_and_guards_real_source_links(self):
        j,history=self.card51_output_fixture();items=server.output_items(history,'video',j['schema_spec']['outputs'])
        outputs=[dict(id=j['id']+'o'+str(i),src='/retained/'+str(i)+'.mp4',label=None,removedAt=123,published=True)
                 for i in range(6)]
        before=copy.deepcopy(outputs)
        with patch.object(server.requests,'get')as get,patch.object(Path,'open')as file:
            presented=server.present_outputs(j,items,outputs);get.assert_not_called();file.assert_not_called()
        self.assertEqual(outputs,before)
        self.assertEqual({o['id']:o['src']for o in presented},{o['id']:o['src']for o in outputs})
        self.assertTrue(all(o['removedAt']==123 and o['published']for o in presented))
        j['graph']['1048']['inputs']['images']=['989',0]
        metadata=server.reviewed_output_metadata(j['schema_spec'],j['graph'])
        self.assertNotIn('1048',metadata,'a changed source graph cannot be mislabeled as a mask')
        self.assertEqual(metadata['948']['role'],'result')

    def test_output_origin_metadata_does_not_duplicate_a_file_returned_by_multiple_nodes(self):
        file={'filename':'same.png','subfolder':'shared','type':'output'}
        items=server.output_items({'outputs':{'a':{'images':[file]},'b':{'images':[file]}}},'image',['a','b'])
        self.assertEqual(len(items),1);self.assertEqual(items[0]['output_node'],'a')

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
        self.spec['controls'][0].update(mediaSlotId='video',previewRecipe={'longSideControlId':'size','longSide':1280,'multiple':32,'sourceMultiple':8,'postScale':.5,'fit':'crop','frameRate':24,
                                                                         'targets':[{'node':'private-node','input':'private-input'}]})
        field=server.public_schema(self.spec)['controls'][0]
        self.assertEqual(field['mediaSlotId'],'video')
        self.assertEqual(field['previewRecipe'],{'longSideControlId':'size','longSide':1280,'multiple':32,'sourceMultiple':8,'postScale':.5,'fit':'crop','frameRate':24})
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

    def test_subject_points_use_post_scale_model_frame_instead_of_layerstyle_frame(self):
        self.spec['pointsRecipe']={'slotId':'video','longSideControlId':'size','longSide':512,'multiple':32,
                                  'sourceMultiple':8,'postScale':.5,'node':'points'}
        container=Mock();container.streams=[Mock(type='video',width=640,height=360)]
        opened=Mock();opened.__enter__=Mock(return_value=container);opened.__exit__=Mock(return_value=False)
        with patch.object(server,'asset_file',return_value=Path('synthetic.mp4')),patch.object(server.av,'open',return_value=opened):
            small=server.points_geometry(self.spec,{}, {'video':{'kind':'video'}})
            normal=server.points_geometry(self.spec,{'size':1280}, {'video':{'kind':'video'}})
        self.assertEqual(small,{'width':256,'height':144,'node':'points','bindDimensions':True})
        self.assertEqual(normal,{'width':640,'height':368,'node':'points','bindDimensions':True})


class ReviewedExecutionRepairs(unittest.TestCase):
    def test_gguf_linear_compatibility_changes_only_opt_in_flags_and_survives_rerun(self):
        graph,spec=self.source(124);spec=copy.deepcopy(spec);spec['media']=[]
        graph['41']['inputs']['enable_fp16_accumulation']=True
        graph['43']['inputs']['enable_fp16_accumulation']=True
        before=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
        for nid,original in before.items():
            for key,value in original['inputs'].items():
                expected=False if nid in ('41','43')and key=='enable_fp16_accumulation' else before['61']['inputs']['start_at_step'] if (nid,key)==('64','end_at_step') else value
                self.assertEqual(graph[nid]['inputs'][key],expected,(nid,key))
        fixed=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec);self.assertEqual(graph,fixed)
        source_path=Path(__file__).parent/'workflows/api/local-card-124.api.json'
        source_bytes=source_path.read_bytes()
        with patch.object(schema_adapters,'template_path',return_value=source_path):
            built,values,_=schema_adapters.build(spec,{}, {},{}, {},'gguf-compatibility-test')
        rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':built,'catalog_values':values},{},'gguf-compatibility-rerun')
        for nid in ('41','43'):
            self.assertFalse(built[nid]['inputs']['enable_fp16_accumulation'])
            self.assertFalse(rerun[nid]['inputs']['enable_fp16_accumulation'])
        self.assertEqual(built['64']['inputs']['end_at_step'],built['61']['inputs']['start_at_step'])
        self.assertEqual(rerun['64']['inputs']['end_at_step'],rerun['61']['inputs']['start_at_step'])
        self.assertEqual(source_path.read_bytes(),source_bytes)

    def test_gguf_linear_compatibility_rejects_changed_branch_atomically(self):
        for nid,key,value in [('71','value',1),('55','unet_name','unreviewed.gguf'),
                              ('41','enable_fp16_accumulation',1),('19','model',['3',0]),
                              ('64','end_at_step',2),('61','start_at_step',4),('61','steps',4)]:
            with self.subTest(node=nid,key=key):
                graph,spec=self.source(124);graph[nid]['inputs'][key]=value
                before=copy.deepcopy(graph)
                with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph,before)

    def test_tail_frame_toggle_binds_real_lazy_switch_and_preserves_rerun_choice(self):
        graph,spec=self.source(57);spec=copy.deepcopy(spec);spec['media']=[]
        field={'id':'56:switch','key':'switch','label':'使用尾帧','type':'checkbox',
               'kind':'toggle','value':False,'targets':[{'node':'56','input':'switch'}]}
        if not any(f['id']==field['id']for f in spec['controls']):spec['controls'].append(field)
        self.assertEqual(graph['56']['class_type'],'ComfySwitchNode')
        self.assertEqual(graph['56']['inputs']['on_false'],['9',0])
        self.assertEqual(graph['56']['inputs']['on_true'],['10',0])
        self.assertEqual(graph['10']['inputs']['image'],['24',0])
        self.assertEqual(graph['18']['inputs']['last_frame'],['56',0])
        source_path=Path(__file__).parent/'workflows/api/local-card-57.api.json'
        before=source_path.read_bytes()
        with patch.object(schema_adapters,'template_path',return_value=source_path):
            disabled,_,_=schema_adapters.build(spec,{'56:switch':False},{},{},{},'tail-off-test')
            enabled,values,_=schema_adapters.build(spec,{'56:switch':True},{},{},{},'tail-on-test')
        self.assertFalse(disabled['56']['inputs']['switch'])
        self.assertTrue(enabled['56']['inputs']['switch'])
        self.assertEqual(enabled['18']['inputs'],disabled['18']['inputs'])
        rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':enabled,'catalog_values':values},{},'tail-rerun-test')
        self.assertTrue(rerun['56']['inputs']['switch'])
        self.assertEqual(source_path.read_bytes(),before)

    def test_owner_api_alias_repair_preserves_explicit_custom_api_on_build_and_rerun(self):
        graph,spec=self.source(33)
        graph['29']['inputs']['model']='gemini-3.8-flash-low'
        before=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph['29']['inputs']['model'],'gemini-3.8-flash-thinking-low')
        for key,value in before['29']['inputs'].items():
            if key!='model':self.assertEqual(graph['29']['inputs'][key],value)
        default=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec);self.assertEqual(graph,default)
        custom={'29':{'mode':'custom','base_url':'https://owner-api.example.test/v1',
                      'model':'gemini-3.8-flash-low','api_key':'synthetic-key-not-a-real-credential'}}
        schema_adapters.bind_api_profiles(graph,spec,custom)
        self.assertEqual(graph['29']['_meta']['yingxu_custom_api_profile'],'29')
        selected=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,selected,'explicit API selections must not be silently replaced')
        isolated_spec=copy.deepcopy(spec);isolated_spec['media']=[]
        source_path=Path(__file__).parent/'workflows/api/local-card-33.api.json'
        with patch.object(schema_adapters,'template_path',return_value=source_path):
            built,values,texts=schema_adapters.build(isolated_spec,{}, {},{},custom,'custom-model-test')
        self.assertEqual(built['29']['inputs']['model'],'gemini-3.8-flash-low')
        rerun,_=schema_adapters.rerun({'schema_spec':isolated_spec,'graph':built,'catalog_values':values},{},'custom-model-rerun')
        self.assertEqual(rerun['29']['inputs']['model'],'gemini-3.8-flash-low')
        self.assertEqual(rerun['29']['inputs']['api_key'],'synthetic-key-not-a-real-credential')
        changed=copy.deepcopy(before);changed['29']['inputs']['ref_image']=['21',0]
        unchanged=copy.deepcopy(changed)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(changed,spec)
        self.assertEqual(changed,unchanged)

    def test_reviewed_grok_alias_preserves_prompt_keys_source_and_custom_api_rerun(self):
        for number, nid, old in ((0, '577', 'grok-4-fast-non-reasoning'),
                                 (32, '31', 'grok-4-fast-non-reasoning'),
                                 (80, '146', 'grok-4-fast-reasoning')):
            with self.subTest(workflow=number):
                graph, spec = self.source(number)
                graph[nid]['inputs']['model'] = old
                before = copy.deepcopy(graph)
                changes = apply_reviewed_repairs(graph, spec)
                self.assertEqual(graph[nid]['inputs']['model'], 'grok-4.6')
                self.assertTrue(changes)
                for node_id, original in before.items():
                    for key, value in original['inputs'].items():
                        expected = 'grok-4.6' if node_id == nid and key == 'model' else value
                        if number == 80 and (node_id, key) == ('146', 'role'):
                            from anime_batch_protocol import ROLE_NODE, FORMAT_NODE
                            expected = [ROLE_NODE, 0]
                            self.assertEqual(graph[ROLE_NODE]['inputs']['string_1'], ['83', 0])
                            self.assertEqual(graph[ROLE_NODE]['inputs']['string_2'], [FORMAT_NODE, 0])
                        if number == 80 and (node_id, key) == ('87', 'text'):
                            from anime_batch_protocol import PROMPT_NODE, RESPONSE_NODE
                            expected = [PROMPT_NODE, 0]
                            self.assertEqual(graph[RESPONSE_NODE]['inputs']['text'], ['146', 0])
                        self.assertEqual(graph[node_id]['inputs'][key], expected, (node_id, key))
                fixed = copy.deepcopy(graph)
                apply_reviewed_repairs(graph, spec)
                self.assertEqual(graph, fixed)
                custom = {nid: {'mode': 'custom', 'base_url': 'https://selected.example.test/v1',
                                'model': old, 'api_key': 'synthetic-test-key'}}
                isolated_spec = copy.deepcopy(spec)
                isolated_spec['media'] = []
                source_path = Path(__file__).parent / f'workflows/api/local-card-{number}.api.json'
                source_bytes = source_path.read_bytes()
                with patch.object(schema_adapters, 'template_path', return_value=source_path):
                    built, values, _ = schema_adapters.build(isolated_spec, {}, {}, {}, custom, 'custom-grok-test')
                self.assertEqual(built[nid]['inputs']['model'], old)
                self.assertEqual(built[nid]['_meta']['yingxu_custom_api_profile'], nid)
                rerun, _ = schema_adapters.rerun(
                    {'schema_spec': isolated_spec, 'graph': built, 'catalog_values': values}, {}, 'custom-grok-rerun')
                self.assertEqual(rerun[nid]['inputs']['model'], old)
                self.assertEqual(rerun[nid]['inputs']['api_baseurl'], 'https://selected.example.test/v1')
                self.assertEqual(source_path.read_bytes(), source_bytes)

    def test_reviewed_grok_alias_rejects_unknown_source_and_changed_protocol_atomically(self):
        for number, nid in ((0, '577'), (32, '31'), (80, '146')):
            for variant in ('source', 'image', 'host', 'model', 'protocol', 'output'):
                with self.subTest(workflow=number, variant=variant):
                    graph, spec = self.source(number)
                    spec = copy.deepcopy(spec)
                    if variant == 'source': spec['source_hash'] = 'unreviewed-source'
                    elif variant == 'image': graph[nid]['inputs']['ref_image'] = ['unreviewed', 0]
                    elif variant == 'host': graph[nid]['inputs']['api_baseurl'] = 'https://unreviewed.example.test/v1'
                    elif variant == 'model': graph[nid]['inputs']['model'] = 'unreviewed-model'
                    elif variant == 'protocol': graph[nid]['inputs']['video'] = ['unreviewed', 0]
                    else: spec['outputs'] = ['unreviewed']
                    before = copy.deepcopy(graph)
                    with self.assertRaises(ReviewedRepairError): apply_reviewed_repairs(graph, spec)
                    self.assertEqual(graph, before)

    def source(self, number):
        root=Path(__file__).parent
        wid=f'local-card-{number}'
        graph=json.loads((root/'workflows/api'/f'{wid}.api.json').read_text('utf-8'))
        spec=json.loads((root/'workflows/compiled-registry.json').read_text('utf-8'))['workflows'][wid]
        return graph,spec

    def test_outpaint_omits_unbound_target_defaults_preserving_user_padding_and_source(self):
        root=Path(__file__).parent
        paths=[root/'workflows/api/local-card-46.api.json',root/'private/research/card-20261004/graph-046.json']
        original={path:path.read_bytes() for path in paths}
        raw=json.loads(original[paths[1]])
        raw_nodes=raw.get('nodes',raw.get('graph',{}).get('nodes',[]))
        source_pad=next(n for n in raw_nodes if str(n['id'])=='5149')
        for key in ('target_width','target_height'):
            socket=next(i for i in source_pad['inputs'] if i['name']==key)
            self.assertIsNone(socket['link'])
            self.assertNotIn('widget',socket,'these are optional source sockets, not authored target sizes')
        for targets in ({'target_width':512,'target_height':512},
                        {'target_width':None,'target_height':None},{}):
            graph,spec=self.source(46)
            graph['5149']['inputs'].pop('target_width',None)
            graph['5149']['inputs'].pop('target_height',None)
            graph['5149']['inputs'].update(targets,left=13,right=47,top=2,bottom=9)
            before=copy.deepcopy(graph)
            apply_reviewed_repairs(graph,spec)
            self.assertNotIn('target_width',graph['5149']['inputs'])
            self.assertNotIn('target_height',graph['5149']['inputs'])
            for key,value in before['5149']['inputs'].items():
                if key not in ('target_width','target_height'):
                    self.assertEqual(graph['5149']['inputs'][key],value)
            for nid,value in before.items():
                if nid!='5149':self.assertEqual(graph[nid],value)
            after=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
            self.assertEqual(graph,after,'saved job repair is idempotent')
        for path,data in original.items():self.assertEqual(path.read_bytes(),data)

    def test_outpaint_unknown_size_source_and_link_drift_reject_atomically(self):
        mutations=(('5149','target_width',640),('5149','target_height',['unreviewed',0]),
                   ('5149','target_width',512.0),('5149','left',True),
                   ('5149','image',['wrong',0]),('5149','mask',['wrong',0]),
                   ('5167:5146','input',['5141',0]),('5167:5147','resize_type.multiple',64),
                   ('5167:5109','length',24),('5104','audio',None),
                   ('5131','images',['5141',0]))
        for nid,key,value in mutations:
            with self.subTest(node=nid,input=key,value=value):
                graph,spec=self.source(46);graph[nid]['inputs'][key]=value
                before=copy.deepcopy(graph)
                with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph,before)
        graph,spec=self.source(46);spec['source_hash']='unreviewed-source'
        before=copy.deepcopy(graph)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,before)

    def test_outpaint_build_and_saved_rerun_preserve_independent_padding_choices(self):
        graph,spec=self.source(46)
        spec=copy.deepcopy(spec);spec['media']=[]
        values={'5149:left':13,'5149:right':47,'5149:top':2,'5149:bottom':9,'5162:value':1}
        path=Path(__file__).parent/'workflows/api/local-card-46.api.json'
        with patch.object(schema_adapters,'template_path',return_value=path):
            built,bound,texts=schema_adapters.build(spec,values,{}, {},{},'offline-46-test')
        self.assertEqual({k:built['5149']['inputs'][k] for k in ('left','right','top','bottom')},
                         {'left':13,'right':47,'top':2,'bottom':9})
        self.assertNotIn('target_width',built['5149']['inputs'])
        rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':built,'catalog_values':bound},{},'offline-46-rerun')
        self.assertEqual(rerun['5149']['inputs'],built['5149']['inputs'])

    def test_video_upscalers_keep_read_and_saved_frame_rate_equal(self):
        for wid,(loader,saver,_,_) in VIDEO_CHAINS.items():
            with self.subTest(workflow=wid):
                graph,spec=self.source(int(wid.rsplit('-',1)[1]))
                apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph[saver]['inputs']['frame_rate'],graph[loader]['inputs']['force_rate'])
                self.assertEqual(24/graph[saver]['inputs']['frame_rate'],1,'24 source frames remain one second')
                self.assertEqual(spec['source_hash'],SOURCE_HASHES[wid])
                self.assertTrue(graph[saver]['_meta']['yingxu_execution_repairs'])

    def test_bernini_video_edits_keep_reviewed_fps_and_original_soundtrack(self):
        for number,saver,rate_source,rate,audio in ((5,'395',['368',0],24,['399',2]),
                                                  (41,'443',['428',0],16,['425',2])):
            with self.subTest(workflow=number):
                graph,spec=self.source(number);before=copy.deepcopy(graph)
                evidence=apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph[saver]['inputs']['frame_rate'],rate_source)
                self.assertEqual(graph[saver]['inputs']['audio'],audio)
                self.assertEqual(len(evidence),1)
                for nid,node in before.items():
                    if nid!=saver:self.assertEqual(graph[nid],node,'model and source controls stay unchanged')
                self.assertEqual((24 if number==5 else 17)/rate,
                                 1 if number==5 else 1.0625)
                after=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph,after)

    def test_bernini_rejects_changed_rate_count_audio_or_source_atomically(self):
        changes=((5,'374','value',25),(5,'410','length',['394',0]),
                 (5,'395','audio',None),(41,'428','value',17),
                 (41,'387','length',['430',3]),(41,'443','audio',['425',0]),
                 (41,'427','a',['unexpected',0]),(40,'33','length',9),
                 (40,'42','audio',['27',0]),(40,'13','value',24))
        for number,nid,key,value in changes:
            with self.subTest(workflow=number,node=nid,input=key):
                graph,spec=self.source(number);graph[nid]['inputs'][key]=value
                before=copy.deepcopy(graph)
                with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph,before)
        for number in (5,40,41):
            graph,spec=self.source(number);spec=copy.deepcopy(spec);spec['source_hash']='unreviewed'
            before=copy.deepcopy(graph)
            with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
            self.assertEqual(graph,before)

    def test_bernini_build_rerun_preserve_user_duration_skip_and_audio(self):
        for number,duration_id,duration,target,expected,skip_id,loader,saver,rate in (
                (5,'378:value:seconds',1.5,'378',36,'399:skip_first_frames','399','395',['368',0]),
                (41,'429:value',2.0,'427',2.0,'425:skip_first_frames','425','443',['428',0])):
            with self.subTest(workflow=number):
                _,spec=self.source(number);spec=copy.deepcopy(spec);spec['media']=[]
                source_path=Path(__file__).parent/f'workflows/api/local-card-{number}.api.json'
                before=source_path.read_bytes()
                with patch.object(schema_adapters,'template_path',return_value=source_path):
                    built,values,_=schema_adapters.build(spec,{duration_id:duration,skip_id:3},{},{},{},'bernini-test')
                self.assertEqual(built[target]['inputs']['value'if number==5 else'a'],expected)
                self.assertEqual(built[loader]['inputs']['skip_first_frames'],3)
                self.assertEqual(built[saver]['inputs']['frame_rate'],rate)
                self.assertEqual(built[saver]['inputs']['audio'],[loader,2])
                if number==41:self.assertNotIn('429',built,'original seconds constant is pruned after binding')
                rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':built,'catalog_values':values},{},'bernini-rerun')
                self.assertEqual(rerun[target]['inputs']['value'if number==5 else'a'],expected)
                self.assertEqual(rerun[loader]['inputs']['skip_first_frames'],3)
                self.assertEqual(rerun[saver]['inputs']['frame_rate'],rate)
                self.assertEqual(rerun[saver]['inputs']['audio'],[loader,2])
                self.assertEqual(source_path.read_bytes(),before)

    def test_bernini_character_edit_preserves_nine_selected_frames_at_real_rate(self):
        graph,spec=self.source(40);before=copy.deepcopy(graph)
        evidence=apply_reviewed_repairs(graph,spec,for_template=True)
        self.assertEqual(len(evidence),2)
        for nid,node in before.items():
            if nid not in ('40','42'):self.assertEqual(graph[nid],node)
        for saver in ('40','42'):
            self.assertEqual(graph[saver]['inputs']['frame_rate'],['13',0])
            self.assertEqual(graph[saver]['inputs']['audio'],['27',2])
        spec=copy.deepcopy(spec);spec['media']=[]
        source_path=Path(__file__).parent/'workflows/api/local-card-40.api.json'
        with patch.object(schema_adapters,'template_path',return_value=source_path):
            built,values,_=schema_adapters.build(spec,{'32:value':9,'16:value':1},{},{},{},'bernini-nine-frames')
        self.assertEqual(built['17']['inputs']['length'],9)
        self.assertEqual(built['33']['inputs']['length'],9)
        self.assertEqual(built['15']['inputs']['a'],1)
        self.assertNotIn('32',built);self.assertNotIn('16',built)
        self.assertEqual(9/built['13']['inputs']['value'],0.5625,'nine frames, not a full second or doubled duration')
        rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':built,'catalog_values':values},{},'bernini-nine-rerun')
        self.assertEqual(rerun['17']['inputs']['length'],9)
        self.assertEqual(rerun['33']['inputs']['length'],9)
        for saver in ('40','42'):
            self.assertEqual(rerun[saver]['inputs']['frame_rate'],['13',0])
            self.assertEqual(rerun[saver]['inputs']['audio'],['27',2])

    def qwen_language_source(self,language):
        from scripts.workflow_customization import description_language_control
        graph,spec=self.source(93);spec=copy.deepcopy(spec)
        spec['controls']=description_language_control(spec['controls'])
        graph['76']['inputs']['from_translate']=language
        return graph,spec

    def test_qwen_explicit_english_prompt_reaches_encoder_without_translation(self):
        graph,spec=self.qwen_language_source('english')
        text='Replace only the white oval with a red five-pointed star.'
        graph['71']['inputs']['prompt']=text;before=copy.deepcopy(graph)
        evidence=apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph['82']['inputs']['text'],['71',0])
        self.assertEqual(graph['10']['inputs']['prompt'],['82',0])
        self.assertEqual(graph['71']['inputs']['prompt'],text)
        self.assertEqual(evidence[0]['id'],'review73-explicit-english-description')
        for nid,node in before.items():
            if nid not in ('82','79','20','10','13'):self.assertEqual(graph[nid],node)
        graph=schema_adapters.prune(graph,spec['outputs'])
        self.assertNotIn('76',graph,'explicit English does not invoke the translation service')
        before=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,before,'saved direct route remains idempotent after pruning')

    def test_qwen_auto_and_chinese_preserve_actual_translation_path(self):
        for language,text in (('auto','An English input with auto still uses the selected translation path.'),
                              ('auto','把白色椭圆换成红星'),
                              ('chinese (simplified)','把白色椭圆换成红星')):
            with self.subTest(language=language,text=text):
                graph,spec=self.qwen_language_source(language)
                graph['71']['inputs']['prompt']=text;before=copy.deepcopy(graph)
                apply_reviewed_repairs(graph,spec)
                for nid in ('71','76','82'):
                    self.assertEqual(graph[nid],before[nid],'do not guess language or replace the unverified translation service')

    def test_qwen2511_setup_preserves_source_and_rejects_unreviewed_weights_or_encoders(self):
        graph,spec=self.qwen_language_source('english');graph['71']['inputs']['prompt']='Edit the vase.'
        before=copy.deepcopy(graph);apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph['79']['inputs']['lora_name'],'qwen/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors')
        self.assertEqual((graph['20']['inputs']['steps'],graph['20']['inputs']['cfg']),(4,1))
        for nid in ('10','13'):
            self.assertEqual(graph[nid]['class_type'],'TextEncodeQwenImageEditPlus')
            self.assertEqual(graph[nid]['inputs']['image1'],['103',0])
            self.assertNotIn('image',graph[nid]['inputs'])
        for nid in ('78','1','2','8','16','103','5','50','15','48'):
            self.assertEqual(graph[nid],before[nid])
        for nid,key,value in (('78','unet_name','another-base.safetensors'),('79','lora_name','another-lora.safetensors')):
            changed,spec=self.qwen_language_source('english');changed[nid]['inputs'][key]=value
            saved=copy.deepcopy(changed)
            with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(changed,spec)
            self.assertEqual(changed,saved)
        changed,spec=self.qwen_language_source('english');changed['10']['class_type']='TextEncodeQwenImageEditPlus'
        changed['10']['inputs']['image1']=changed['10']['inputs'].pop('image',changed['10']['inputs'].get('image1'))
        changed['10'].pop('_meta',None);saved=copy.deepcopy(changed)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(changed,spec)
        self.assertEqual(changed,saved)

    def test_qwen_direct_route_rejects_blank_unknown_source_or_unrecorded_link(self):
        graph,spec=self.qwen_language_source('english')
        graph['71']['inputs']['prompt']=' \n\t'
        before=copy.deepcopy(graph)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,before)
        for nid,key,value in (('82','text',['71',0]),('10','prompt',['71',0]),
                              ('76','text',['13',0]),('76','to_translate','spanish')):
            graph,spec=self.qwen_language_source('english');graph['71']['inputs']['prompt']='Edit the vase.'
            graph[nid]['inputs'][key]=value;before=copy.deepcopy(graph)
            with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
            self.assertEqual(graph,before)
        graph,spec=self.qwen_language_source('english');spec['source_hash']='unknown-source'
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)

    def test_qwen_language_build_rerun_and_reedit_keep_explicit_choice(self):
        graph,spec=self.qwen_language_source('auto');spec['media']=[]
        source_path=Path(__file__).parent/'workflows/api/local-card-93.api.json'
        before=source_path.read_bytes();english='Replace only the white oval with a red star.'
        with patch.object(schema_adapters,'template_path',return_value=source_path):
            built,values,texts=schema_adapters.build(spec,{'76:from_translate':'english'},{'71:prompt':english},{},{},'qwen-english')
            edited,edited_values,_=schema_adapters.build(spec,{'76:from_translate':'chinese (simplified)'},{'71:prompt':'把白椭圆换成红星'},{},{},'qwen-chinese-reedit')
            with self.assertRaises(ReviewedRepairError):
                schema_adapters.build(spec,{'76:from_translate':'english'},{'71:prompt':''},{},{},'qwen-blank')
        self.assertEqual(values['76:from_translate'],'english')
        self.assertEqual(texts['71:prompt'],english)
        self.assertNotIn('76',built)
        rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':built,'catalog_values':values},{},'qwen-english-rerun')
        self.assertEqual(rerun['71']['inputs']['prompt'],english)
        self.assertEqual(rerun['82']['inputs']['text'],['71',0])
        self.assertEqual(edited_values['76:from_translate'],'chinese (simplified)')
        self.assertEqual(edited['76']['inputs']['from_translate'],'chinese (simplified)')
        self.assertEqual(edited['82']['inputs']['text'],['76',0])
        self.assertEqual(source_path.read_bytes(),before)

    def test_flashvsr_chunks_cover_exact_boundaries_without_empty_or_repeated_tail_frames(self):
        graph,spec=self.source(119)
        apply_reviewed_repairs(graph,spec)
        chunk_size=graph['519']['inputs']['value']
        self.assertEqual(graph['514']['inputs']['split_index'],['519',0])
        expression=graph['517']['inputs']['expression']
        # Exercise the graph's real integer expression and split/accumulate
        # contract, using identity model frames rather than a GPU model mock.
        for count in (1,24,359,360,361,720,721):
            source=list(range(count));remaining=source[:];output=[]
            iterations=eval(expression,{'__builtins__':{}},{'a':count,'b':chunk_size})
            for _ in range(iterations):
                chunk,remaining=remaining[:chunk_size],remaining[chunk_size:]
                self.assertTrue(chunk,'no extra empty iteration at exact multiples')
                self.assertEqual(graph['515']['inputs']['any_2'],['522',0])
                output.extend(chunk)
            self.assertEqual(output,source,'no lost, reordered or duplicated tail frame')
            self.assertEqual(remaining,[])

    def test_repaired_graph_remains_safe_after_pruning_and_reediting(self):
        for number in (75,119,121):
            with self.subTest(workflow=number):
                graph,spec=self.source(number)
                apply_reviewed_repairs(graph,spec)
                graph=schema_adapters.prune(graph,spec['outputs'])
                before=copy.deepcopy(graph)
                apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph,before)

    def test_upscale_batch_condition_reads_longest_side_of_selected_frames(self):
        graph,spec=self.source(121);apply_reviewed_repairs(graph,spec)
        side=graph['14']['inputs']['a'][0]
        self.assertEqual(graph[side]['class_type'],'easy imageSizeByLongerSide')
        self.assertEqual(graph[side]['inputs']['image'],['17',0])
        self.assertEqual(graph['12']['inputs'],{'boolean':['14',0],'on_true':['6',0],'on_false':['7',0]})
        self.assertEqual(graph['6']['inputs']['value'],8)
        self.assertEqual(graph['7']['inputs']['value'],12)

    def test_realesrgan_keeps_loader_audio_link_instead_of_dropping_soundtrack(self):
        graph,spec=self.source(121)
        apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph['9']['inputs']['audio'],['15',2])
        before=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,before)
        self.assertTrue(any(item['id']=='review73-preserve-upscaled-video-audio'
                            for item in graph['9']['_meta']['yingxu_execution_repairs']))

    def test_realesrgan_rejects_unreviewed_audio_rebinding_atomically(self):
        graph,spec=self.source(121)
        graph['9']['inputs']['audio']=['unreviewed-audio-loader',0]
        before=copy.deepcopy(graph)
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,before)

    def test_unknown_source_or_changed_link_is_rejected_without_partial_changes(self):
        for number,node,key,value in ((118,'42','frames',['13',0]),
                                     (119,'503','initial_value1',['512',0]),
                                     (121,'17','on_false',['20',0]),
                                     (75,'62','prompt',['127',0])):
            with self.subTest(workflow=number):
                graph,spec=self.source(number);graph[node]['inputs'][key]=value
                before=copy.deepcopy(graph)
                with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)
                self.assertEqual(graph,before)
        graph,spec=self.source(121);spec=copy.deepcopy(spec);spec['source_hash']='other-source'
        with self.assertRaises(ReviewedRepairError):apply_reviewed_repairs(graph,spec)

    def test_all_six_camera_views_receive_same_user_description_without_changing_camera_or_seeds(self):
        graph,spec=self.source(75)
        graph['135']['inputs']['value']='Preserve the same single handle.'
        before=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        for conditioning in ('5','62','95','105','115','125'):
            joined=graph[conditioning]['inputs']['prompt'][0]
            self.assertEqual(graph[joined]['class_type'],'JoinStringMulti')
            self.assertEqual(graph[joined]['inputs']['string_2'],['135',0])
            self.assertIs(graph[joined]['inputs']['return_list'],False)
        for nid,node in before.items():
            if node['class_type']=='QwenMultiangleCameraNode' or 'seed' in node['inputs'] or 'noise_seed' in node['inputs']:
                self.assertEqual(graph[nid],node)

    def test_directory_order_default_is_visible_and_explicit_none_is_respected(self):
        from scripts.workflow_customization import directory_image_order_control
        graph,spec=self.source(135);spec=copy.deepcopy(spec)
        original=copy.deepcopy(graph)
        apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph,original,'old jobs have no hidden changed sort order')
        spec['controls']=directory_image_order_control(spec['controls'])
        apply_reviewed_repairs(graph,spec,for_template=True)
        self.assertEqual(graph['12']['inputs']['sort_method'],'Alphabetical (ASC)')
        graph['12']['inputs']['sort_method']='None'
        apply_reviewed_repairs(graph,spec)
        self.assertEqual(graph['12']['inputs']['sort_method'],'None')

    def test_schema_build_and_rerun_use_repairs_without_rebuilding_source_templates(self):
        graph,spec=self.source(121);spec=copy.deepcopy(spec);spec['media']=[]
        source_path=Path(__file__).parent/'workflows/api/local-card-121.api.json'
        before=source_path.read_bytes()
        with patch.object(schema_adapters,'template_path',return_value=source_path):
            built,values,_=schema_adapters.build(spec,{}, {},{}, {},'review73-unit-job')
        self.assertEqual(built['9']['inputs']['frame_rate'],24)
        self.assertEqual(built['9']['inputs']['audio'],['15',2])
        rerun,_=schema_adapters.rerun({'schema_spec':spec,'graph':built,'catalog_values':values},{},'review73-unit-rerun')
        self.assertEqual(rerun['9']['inputs']['frame_rate'],24)
        self.assertEqual(rerun['9']['inputs']['audio'],['15',2])
        self.assertEqual(rerun['14']['inputs']['a'],built['14']['inputs']['a'])
        self.assertEqual(source_path.read_bytes(),before)


if __name__=='__main__':unittest.main(verbosity=2)
