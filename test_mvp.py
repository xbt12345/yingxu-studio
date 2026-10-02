import json
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import requests
import copy
import hashlib
import av
import server
from fastapi.testclient import TestClient
from adapters import CATALOG_WORKFLOWS, manifest, settings_for, build_graph
from PIL import Image

class MVPContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patches=[patch.object(server,'DB',Path(self.tmp.name)/'test.sqlite3'),patch.object(server,'PRIVATE',Path(self.tmp.name)),patch.object(server,'BASE','http://comfy.example.test')]
        for p in self.patches:p.start()
        (server.PRIVATE/'receipts').mkdir()
        with server.database() as db:
            db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
            db.execute('CREATE TABLE assets (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.client=TestClient(server.app)
        self.body=dict(workflow_id='h3-reference',prompt='Ocean waves at sunrise.',token='test-idempotency-key',settings={})
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_flux_klein_compiled_graph_binds_visible_inputs(self):
        for workflow_id, prompt_node, seed_node, size_node, scale_node, output_node in (
            ('local-card-9','108','96','105','107','104'),
            ('local-card-10','83','75','54','58','31'),
        ):
            with self.subTest(workflow_id=workflow_id):
                workflow=manifest(workflow_id)
                settings=settings_for(workflow,{'seed':424242,'resolution':'1024x1024','output_pixels':1024})
                graph=build_graph(workflow_id,'蓝色花瓶','无文字' if workflow['negative'] else '',settings,[],workflow_id)
                self.assertEqual(graph[prompt_node]['inputs']['value'],'蓝色花瓶')
                self.assertEqual(graph[seed_node]['inputs']['noise_seed' if workflow_id=='local-card-9' else 'seed'],424242)
                self.assertEqual(graph[size_node]['inputs']['resolution'],'1024x1024')
                self.assertEqual(graph[scale_node]['inputs']['scale_to_length'],1024)
                self.assertEqual(graph[output_node]['inputs']['filename_prefix'],'yingxu/'+workflow_id)
                self.assertEqual(sum(node['class_type']=='SaveImage' for node in graph.values()),1)
                self.assertEqual(sum(node['class_type']=='LoadImage' for node in graph.values()),0)
                with self.assertRaises(ValueError):settings_for(workflow,{'resolution':'2048x2048'})
    def test_flux_comparison_uses_native_resolution_and_preserves_scaling(self):
        assets=[{'kind':'image','remote':'first.png'},{'kind':'image','remote':'second.png'}]
        for size in ('1024x1024','1344x768','640x1536'):
            with self.subTest(size=size):
                settings=settings_for(manifest('local-card-11'),{'seed':7,'resolution':size})
                graph=build_graph('local-card-11','blue vase','',settings,assets,'comparison')
                self.assertEqual(graph['162']['inputs']['resolution'],size)
                self.assertEqual(graph['159']['inputs']['scale_to_side'],'total_pixel(kilo pixel)')
                self.assertEqual(graph['159']['inputs']['scale_to_length'],1536)
                self.assertEqual(graph['63']['inputs']['image'],'first.png')
                self.assertEqual(graph['64']['inputs']['image'],'second.png')
                self.assertEqual(graph['147']['inputs']['images'],['146',0])
                self.assertNotIn('10000',graph)
        with self.assertRaises(ValueError):settings_for(manifest('local-card-11'),{'resolution':'999x999'})
    def test_mask_workflows_reject_unmarked_images_before_execution(self):
        uploads=server.PRIVATE/'uploads';uploads.mkdir()
        asset_id='a'*64
        source={'id':asset_id}
        source_path=uploads/(asset_id+'.png')
        Image.new('RGB',(32,32),'white').save(source_path)
        with self.assertRaisesRegex(server.HTTPException,'画笔标注区域'):
            server.require_edit_mask(source)
        marked=Image.new('RGBA',(32,32),'white')
        marked.putpixel((8,8),(255,255,255,0))
        marked.save(source_path)
        server.require_edit_mask(source)
    def test_flux_4b_image_edit_binds_both_reference_ports(self):
        assets=[{'kind':'image','remote':'original.png'},{'kind':'image','remote':'reference.png'}]
        for workflow_id in ('local-card-17','local-card-18'):
            with self.subTest(workflow_id=workflow_id):
                settings=settings_for(manifest(workflow_id),{'seed':17})
                graph=build_graph(workflow_id,'keep @图片1; use @图片2 style','no text',settings,assets,workflow_id)
                self.assertEqual(graph['76']['inputs']['image'],'original.png')
                self.assertEqual(graph['81']['inputs']['image'],'reference.png')
                self.assertEqual(sum(node['class_type']=='SaveImage' for node in graph.values()),2)
                for node in (('109','121') if workflow_id=='local-card-17' else ('107','127')):
                    self.assertEqual(graph[node]['inputs']['text'],'keep 图1; use 图2 style')
                if workflow_id=='local-card-18':
                    self.assertEqual(graph['108']['inputs']['text'],'no text')
                    self.assertEqual(graph['128']['inputs']['text'],'no text')
    def test_optional_annotation_uses_original_image_without_empty_mask(self):
        for marked in (False,True):
            with self.subTest(marked=marked):
                assets=[{'kind':'image','remote':'source.png','has_edit_mask':marked},{'kind':'image','remote':'reference.png'}]
                graph=build_graph('local-card-16','make 图1 blue','',{'seed':17},assets,'optional-mask')
                self.assertEqual('2' in graph,marked)
                self.assertEqual('mask' in graph['38']['inputs'],marked)
                self.assertEqual(graph['21']['inputs']['pixels'],['2' if marked else '38',0])
    def test_flux_klein_basic_graph_preserves_size_scheduler_and_prompt(self):
        for workflow_id,prompt_node,width_node,height_node,seed_node,output_node in (
            ('local-card-19','76','86','87','88','9'),
            ('local-card-21','28','19','20','21','14'),
        ):
            with self.subTest(workflow_id=workflow_id):
                workflow=manifest(workflow_id)
                supplied={'size':'1152x640','seed':12345}
                settings=settings_for(workflow,supplied)
                graph=build_graph(workflow_id,'晨光中的白杯','模糊' if workflow['negative'] else '',settings,[],workflow_id)
                self.assertEqual(graph[prompt_node]['inputs']['value'],'晨光中的白杯')
                self.assertEqual(graph[width_node]['inputs']['value'],settings['width'])
                self.assertEqual(graph[height_node]['inputs']['value'],settings['height'])
                self.assertGreater(settings['width'],settings['height'])
                self.assertEqual(graph[seed_node]['inputs']['noise_seed'],12345)
                self.assertEqual(graph[output_node]['inputs']['filename_prefix'],'yingxu/'+workflow_id)
                self.assertEqual(sum(node['class_type']=='SaveImage' for node in graph.values()),1)
                with self.assertRaises(ValueError):settings_for(workflow,{'size':'1151x640'})
    def test_z_image_full_version_drops_identical_duplicate_output(self):
        workflow=manifest('local-card-104')
        settings=settings_for(workflow,{'seed':7,'resolution':'1024x1024'})
        graph=build_graph(workflow['id'],'蓝色杯子','不要水印',settings,[],'z-full')
        self.assertEqual(graph['104']['inputs']['value'],'蓝色杯子')
        self.assertEqual(graph['113']['inputs']['text'],'不要水印')
        self.assertEqual(graph['103']['inputs']['resolution'],'1024x1024')
        self.assertEqual(graph['116']['inputs']['seed'],7)
        self.assertEqual(graph['99']['inputs']['filename_prefix'],'yingxu/z-full')
        self.assertNotIn('95',graph)
        self.assertEqual(sum(node['class_type']=='SaveImage' for node in graph.values()),1)
    def test_qwen_eight_step_saves_enhanced_result(self):
        settings=settings_for(manifest('local-card-107'),{'seed':424242,'size':'1536x1024','output_size':1536})
        graph=build_graph('local-card-107','白色杯子','不要水印',settings,[],'qwen-eight')
        self.assertEqual(graph['6']['inputs']['text'],'白色杯子')
        self.assertEqual(graph['7']['inputs']['text'],'不要水印')
        self.assertGreater(graph['58']['inputs']['width'],graph['58']['inputs']['height'])
        self.assertEqual(graph['3']['inputs']['seed'],424242)
        self.assertEqual(graph['80']['inputs']['seed'],424242)
        self.assertEqual(graph['80']['inputs']['resolution'],1536)
        self.assertEqual(graph['site-output']['inputs']['images'],['80',0])
        self.assertNotIn('60',graph)
    def test_krea_switches_and_lora_strength_bind_to_source_nodes(self):
        settings=settings_for(manifest('local-card-108'),{'seed':7,'prompt_seed':8,'lora_enabled':True,'prompt_optimize':False,'model_strength':1.15,'megapixels':1.5})
        graph=build_graph('local-card-108','红色风筝','',settings,[],'krea-switches')
        self.assertTrue(graph['67']['inputs']['value'])
        self.assertFalse(graph['68']['inputs']['value'])
        self.assertEqual(graph['59']['inputs']['strength_model'],1.15)
        self.assertEqual(graph['49']['inputs']['megapixels'],1.5)
        self.assertEqual(graph['63']['inputs']['value'],'红色风筝')
    def test_three_model_prompts_and_anima_size_are_independent(self):
        image={'kind':'image','remote':'anime.png'}
        settings=settings_for(manifest('local-card-12'),{'seed':9,'prompt_turn2real':'第二路写真','prompt_semireal':'第三路电影感'})
        graph=build_graph('local-card-12','第一路写实','',settings,[image],'three-prompts')
        self.assertEqual([graph[node]['inputs']['text'] for node in ('19','171','180')],['第一路写实','第二路写真','第三路电影感'])
        settings=settings_for(manifest('local-card-85'),{'seed':10,'size':'1152x896'})
        graph=build_graph('local-card-85','白色猫咪','',settings,[],'anima-size')
        self.assertEqual((graph['65']['inputs']['width_override'],graph['65']['inputs']['height_override']),(1152,896))
    def test_z_image_turbo_selects_one_real_branch_and_one_seed(self):
        for workflow_id in ('local-card-109','local-card-128'):
            for branch,decode,stage_seed in (('standard','55','51'),('lora','56','48')):
                with self.subTest(workflow_id=workflow_id,branch=branch):
                    settings=settings_for(manifest(workflow_id),{'seed':123,'resolution':'1024x1024','branch':branch,'upscale':1})
                    graph=build_graph(workflow_id,'白色杯子','不要水印',settings,[],workflow_id)
                    self.assertEqual(graph['45']['inputs']['value'],'白色杯子')
                    self.assertEqual(graph['54']['inputs']['text'],'不要水印')
                    self.assertEqual(graph['44']['inputs']['resolution'],'1024x1024')
                    self.assertEqual(graph['57']['inputs']['seed'],123)
                    self.assertEqual(graph[stage_seed]['inputs']['seed'],123)
                    self.assertEqual(graph['site-output']['inputs']['images'],[decode,0])
                    self.assertEqual(sum(node['class_type']=='SaveImage' for node in graph.values()),1)
    def test_z_image_variants_keep_distinct_source_vae_and_style_control(self):
        for workflow_id in ('local-card-104','local-card-129'):
            settings=settings_for(manifest(workflow_id),{'seed':9,'resolution':'1024x1024'})
            graph=build_graph(workflow_id,'白杯','不要水印',settings,[],workflow_id)
            self.assertEqual(graph['99']['inputs']['filename_prefix'],'yingxu/'+workflow_id)
            self.assertEqual(sum(node['class_type']=='SaveImage' for node in graph.values()),1)
        self.assertNotEqual(
            build_graph('local-card-104','白杯','',settings_for(manifest('local-card-104'),{}),[],'a')['94']['inputs']['vae_name'],
            build_graph('local-card-129','白杯','',settings_for(manifest('local-card-129'),{}),[],'b')['94']['inputs']['vae_name'])
        settings=settings_for(manifest('local-card-130'),{'seed':10,'size':'1024x1024','lora_strength':-0.4})
        graph=build_graph('local-card-130','白杯','',settings,[],'red-z')
        self.assertEqual(graph['13']['inputs']['prompt'],'白杯')
        self.assertEqual(graph['11']['inputs']['width'],1024)
        self.assertEqual(graph['34']['inputs']['value'],-0.4)
        self.assertEqual(graph['5']['inputs']['seed'],10)
    def test_connected_catalog_identity_matches_card_inventory(self):
        inventory=json.loads((Path(__file__).parent/'workflows/manifest.json').read_text('utf-8'))
        originals={x['id']:x for x in inventory['workflows']}
        interfaces=json.loads((Path(__file__).parent/'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
        for workflow in CATALOG_WORKFLOWS:
            with self.subTest(workflow_id=workflow['id']):
                source=originals[workflow['id']]
                self.assertEqual(workflow['name'],source['name'])
                self.assertEqual(workflow['source'],source['source'])
                self.assertEqual(workflow['source_hash'],source['source_hash'])
                self.assertEqual(workflow['source_hash'],interfaces[workflow['id']]['sourceHash'])
    def test_krea_workflows_bind_actual_prompt_and_seed_nodes(self):
        settings=settings_for(manifest('local-card-108'),{'seed':77,'prompt_seed':88,'aspect_ratio':'9:16 (Portrait Widescreen)','megapixels':1.5})
        graph=build_graph('local-card-108','白杯','',settings,[],'krea-turbo')
        self.assertEqual(graph['63']['inputs']['value'],'白杯')
        self.assertEqual(graph['53']['inputs']['seed'],77)
        self.assertEqual(graph['60']['inputs']['sampling_mode.seed'],88)
        self.assertEqual(graph['49']['inputs']['aspect_ratio'],'9:16 (Portrait Widescreen)')
        self.assertEqual(graph['49']['inputs']['megapixels'],1.5)
        self.assertEqual(graph['29']['inputs']['filename_prefix'],'yingxu/krea-turbo')
        with self.assertRaises(ValueError):settings_for(manifest('local-card-108'),{'prompt_seed':2**32})
        settings=settings_for(manifest('local-card-110'),{'seed':99,'size':'1024x1024'})
        graph=build_graph('local-card-110','白杯','无文字',settings,[],'krea-master')
        self.assertEqual(graph['90']['inputs']['text'],'白杯')
        self.assertEqual(graph['173']['inputs']['text'],'无文字')
        self.assertEqual(graph['29']['inputs']['width'],1024)
        self.assertEqual(graph['29']['inputs']['height'],1024)
        self.assertEqual(graph['63']['inputs']['noise_seed'],99)
    def test_workflow_exports_redact_platform_api_credentials(self):
        graph={
            'key-node':{'class_type':'CR Prompt Text','inputs':{'prompt':'sk-'+('A'*40)}},
            'api-node':{'class_type':'RH_LLMAPI_NODE','inputs':{'api_key':['key-node',0],'access_token':'private-token','model':'sample-model'}},
        }
        safe=server.public_graph(graph)
        self.assertEqual(safe['key-node']['inputs']['prompt'],'[请填写自己的密钥]')
        self.assertEqual(safe['api-node']['inputs']['access_token'],'[请填写自己的密钥]')
        self.assertEqual(safe['api-node']['inputs']['api_key'],['key-node',0])
        self.assertEqual(safe['api-node']['inputs']['model'],'sample-model')
        self.assertEqual(graph['key-node']['inputs']['prompt'],'sk-'+('A'*40))
    def test_qwen_edit_variants_bind_real_reference_slots(self):
        original={'kind':'image','remote':'original.png'}
        clothes={'kind':'image','remote':'clothes.png'}
        settings=settings_for(manifest('local-card-3'),{'seed':19,'aspect_ratio':'3:4 (Portrait Standard)','megapixels':1.2})
        graph=build_graph('local-card-3','给人物换装','不要水印',settings,[original,clothes],'outfit')
        self.assertEqual(graph['551']['inputs']['image'],'original.png')
        self.assertEqual(graph['547']['inputs']['image'],'clothes.png')
        self.assertEqual(graph['560']['inputs']['value'],'给人物换装')
        self.assertEqual(graph['540:491']['inputs']['negative_prompt'],'不要水印')
        self.assertEqual(graph['541']['inputs']['megapixels'],1.2)
        self.assertTrue(graph['540:489']['inputs']['switch'])
        self.assertEqual(graph['558']['inputs']['seed'],19)
        settings=settings_for(manifest('local-card-84'),{'seed':20,'aspect_ratio':'1:1 (Square)','megapixels':1})
        graph=build_graph('local-card-84','转成真人','不要水印',settings,[original],'anime-to-real')
        self.assertEqual(graph['506']['inputs']['image'],'original.png')
        self.assertEqual(graph['497:474']['inputs']['prompt'],'转成真人')
        self.assertEqual(graph['497:474']['inputs']['negative_prompt'],'不要水印')
        self.assertTrue(graph['497:468']['inputs']['switch'])
        self.assertEqual(graph['515']['inputs']['seed'],20)
        settings=settings_for(manifest('local-card-78'),{'seed':21})
        graph=build_graph('local-card-78','镜头拉近','不要水印',settings,[original],'angle')
        self.assertEqual(graph['31']['inputs']['image'],'original.png')
        self.assertEqual(graph['11']['inputs']['prompt'],'镜头拉近')
        self.assertEqual(graph['3']['inputs']['prompt'],'不要水印')
        self.assertEqual(graph['39']['inputs']['megapixels'],1.5)
        self.assertEqual(graph['14']['inputs']['seed'],21)
        settings=settings_for(manifest('local-card-83'),{'seed':22})
        graph=build_graph('local-card-83','转成真人','',settings,[original],'krea-anime')
        self.assertEqual(graph['227']['inputs']['image'],'original.png')
        self.assertEqual(graph['471']['inputs']['value'],'转成真人')
        self.assertEqual(graph['221']['inputs']['seed'],22)
        self.assertEqual(graph['228']['inputs']['filename_prefix'],'yingxu/krea-anime')
        settings=settings_for(manifest('local-card-82'),{'seed':23,'prompt_seed':24,'output_long_side':1024})
        graph=build_graph('local-card-82','转成真人','避免水印',settings,[original],'qwen-anime')
        self.assertEqual(graph['31']['inputs']['image'],'original.png')
        self.assertEqual(graph['43']['inputs']['text'],'转成真人')
        self.assertEqual(graph['9']['inputs']['prompt'],'避免水印')
        self.assertEqual(graph['161']['inputs']['seed'],24)
        self.assertEqual(graph['28']['inputs']['seed'],23)
        self.assertEqual(graph['26']['inputs']['value'],1024)
        settings=settings_for(manifest('local-card-12'),{'seed':25})
        graph=build_graph('local-card-12','保留人物轮廓','',settings,[original],'three-models')
        self.assertEqual(graph['63']['inputs']['image'],'original.png')
        self.assertEqual(graph['158']['inputs']['seed'],25)
        self.assertEqual([graph[node]['inputs']['text'] for node in ('19','171','180')],
                         ['保留人物轮廓','reskin this into a real photo','转为写实摄影'])
        for node in ('62','170','179'):
            self.assertIn('yingxu/three-models/',graph[node]['inputs']['filename_prefix'])
        settings=settings_for(manifest('local-card-14'),{'seed':26,'strength':0.7,'horizontal_angle':90,'vertical_angle':15,'zoom':4.5})
        graph=build_graph('local-card-14','让镜头向右转','',settings,[original],'camera-angle')
        self.assertEqual(graph['63']['inputs']['image'],'original.png')
        self.assertEqual(graph['114']['inputs']['prompt'],'让镜头向右转')
        self.assertEqual(graph['95']['inputs']['seed'],26)
        self.assertEqual(graph['105']['inputs']['horizontal_angle'],90)
        self.assertEqual(graph['105']['inputs']['vertical_angle'],15)
        self.assertEqual(graph['105']['inputs']['zoom'],4.5)
        self.assertEqual(graph['108']['inputs']['strength'],0.7)
    def test_ideogram_personal_api_binds_without_exporting_key(self):
        for wid,api,old_key,output in [('local-card-105','190','188','182'),('local-card-106','178','179','158')]:
            with self.subTest(workflow=wid):
                settings=settings_for(manifest(wid),{'seed':123,'noise_seed':456,'aspect_ratio':'3:2 (Photo)','megapixels':1.2})
                graph=build_graph(wid,'红色纸灯笼','',settings,[],wid)
                self.assertEqual(graph[api]['inputs']['seed'],123)
                self.assertEqual(graph['187:18' if wid.endswith('105') else '98:18']['inputs']['noise_seed'],456)
                self.assertEqual(graph['183' if wid.endswith('105') else '37']['inputs']['aspect_ratio'],'3:2 (Photo)')
                own=server.bind_api_profiles(wid,graph,{api:{'mode':'custom','base_url':'https://example.test/v1','model':'my-model','api_key':'my-private-key'}})
                self.assertEqual(own[api]['inputs']['api_key'],'my-private-key')
                self.assertNotIn(old_key,own)
                self.assertIn(output,own)
                self.assertNotIn('my-private-key',json.dumps(server.public_graph(own)))
                with self.assertRaises(server.HTTPException):server.bind_api_profiles(wid,graph,{api:{'mode':'custom','base_url':'ftp://bad','model':'model','api_key':'key'}})
    def test_qwen_image_catalog_maps_every_visible_input_to_compiled_graph(self):
        w=manifest('local-card-1')
        self.assertEqual(w['name'],'0921qwenimage2.1图像生成')
        settings=settings_for(w,{'aspect_ratio':'4:3 (Standard)','megapixels':1.5,'seed':424242})
        graph=build_graph(w['id'],'蓝色花瓶','水印',settings,[],'qwen-test')
        self.assertEqual(graph['459:452']['inputs']['prompt'],'蓝色花瓶')
        self.assertEqual(graph['459:452']['inputs']['negative_prompt'],'水印')
        self.assertEqual(graph['13']['inputs']['aspect_ratio'],'4:3 (Standard)')
        self.assertEqual(graph['13']['inputs']['megapixels'],1.5)
        self.assertEqual(graph['476']['inputs']['seed'],424242)
        self.assertEqual(graph['461']['inputs']['filename_prefix'],'yingxu/qwen-test')
        self.assertEqual(len(graph),10)
        with self.assertRaises(ValueError):settings_for(w,{'aspect_ratio':'unsupported'})
        with self.assertRaises(ValueError):settings_for(w,{'megapixels':16.1})
    def test_qwen_edit_preserves_image_slot_order_and_uses_both_inputs(self):
        w=manifest('local-card-2')
        self.assertEqual(w['name'],'0921qwenimage2.1图像编辑')
        settings=settings_for(w,{'aspect_ratio':'3:2 (Photo)','megapixels':1.2,'seed':7})
        refs=[{'kind':'image','remote':'original.png'},{'kind':'image','remote':'style.png'}]
        graph=build_graph(w['id'],'保留人物并换装','不要水印',settings,refs,'edit-test')
        self.assertEqual(graph['530']['inputs']['image'],'original.png')
        self.assertEqual(graph['527']['inputs']['image'],'style.png')
        self.assertEqual(graph['518:491']['inputs']['prompt'],'保留人物并换装')
        self.assertEqual(graph['518:491']['inputs']['negative_prompt'],'不要水印')
        self.assertEqual(graph['522']['inputs']['aspect_ratio'],'3:2 (Photo)')
        self.assertEqual(graph['522']['inputs']['megapixels'],1.2)
        self.assertTrue(graph['518:489']['inputs']['switch'])
        self.assertEqual(graph['536']['inputs']['seed'],7)
        self.assertEqual(graph['517']['inputs']['filename_prefix'],'yingxu/edit-test')
        with self.assertRaises(ValueError):build_graph(w['id'],'描述','',settings,refs[:1],'missing')
    def test_graph_replaces_all_original_assets_and_prompts(self):
        s=settings_for(manifest('h3-reference'),{'seed':123})
        g=build_graph('h3-reference','ONLY MY PROMPT','',s,[{'kind':'image','remote':'ours.png'}],'ours')
        self.assertEqual(g['72']['inputs']['value'],'ONLY MY PROMPT')
        loads=[n['inputs'] for n in g.values() if n['class_type'] in ['LoadImage','LoadAudio','VHS_LoadVideo']]
        self.assertEqual(loads,[{'image':'ours.png'}])
        self.assertEqual(g['55']['inputs']['noise_seed'],123)
        self.assertFalse(any('API' in n['class_type'] for n in g.values()))
    def test_standard_branch_has_no_missing_acceleration_lora(self):
        s=settings_for(manifest('bernini-edit'),{'seed':42,'steps':20,'cfg':4.5})
        g=build_graph('bernini-edit','EDIT','NEGATIVE',s,[{'kind':'video','remote':'ours.mp4'}],'ours')
        self.assertFalse(any('Lora' in n['class_type'] for n in g.values()))
        self.assertEqual(g['385']['inputs']['steps'],20)
        self.assertEqual(g['379']['inputs']['step'],10)
        self.assertEqual(g['384']['inputs']['cfg'],4.5)
        self.assertEqual(g['378']['inputs']['text'],'NEGATIVE')
    def test_video_trim_handles_bind_to_source_frames(self):
        s=settings_for(manifest('bernini-edit'),{'trim_start':2,'duration':5,'fps':16,'seed':42})
        g=build_graph('bernini-edit','EDIT','',s,[{'kind':'video','remote':'ours.mp4'}],'trim')
        self.assertEqual(g['425']['inputs']['skip_first_frames'],32)
        self.assertEqual(g['425']['inputs']['frame_load_cap'],81)
        subsecond=settings_for(manifest('bernini-edit'),{'trim_start':2.25,'duration':5.15,'fps':16,'seed':42})
        g=build_graph('bernini-edit','EDIT','',subsecond,[{'kind':'video','remote':'ours.mp4'}],'trim-subsecond')
        self.assertEqual(g['425']['inputs']['skip_first_frames'],36)
        self.assertEqual(g['425']['inputs']['frame_load_cap'],83)
        precise=settings_for(manifest('bernini-edit'),{'trim_start':2.53,'duration':1.27,'fps':16,'seed':42})
        self.assertEqual(precise['trim_start'],2.53)
        self.assertEqual(precise['duration'],1.27)
    def test_video_trim_rejects_span_past_source_before_remote_submit(self):
        identity='a'*64
        folder=server.PRIVATE/'uploads';folder.mkdir()
        path=folder/(identity+'.mp4')
        with av.open(str(path),'w') as container:
            stream=container.add_stream('libx264',rate=16);stream.width=64;stream.height=64;stream.pix_fmt='yuv420p'
            for _ in range(32):
                frame=av.VideoFrame.from_image(Image.new('RGB',(64,64),'blue'))
                for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        record=dict(id=identity,kind='video',name='short.mp4',remote='short.mp4')
        with server.database() as db:
            db.execute('INSERT INTO assets VALUES (?,?)',(identity,json.dumps(record)))
        body=dict(workflow_id='bernini-edit',prompt='EDIT',token='trim-out-of-range',settings={'trim_start':1,'duration':2},asset_ids=[identity])
        with patch.object(server.requests,'post') as post:
            response=self.client.post('/api/jobs',json=body)
        self.assertEqual(response.status_code,400)
        self.assertIn('超出原视频时长',response.json()['detail'])
        post.assert_not_called()
    def test_invalid_settings_and_missing_video_do_not_submit(self):
        with patch.object(server.requests,'post') as post:
            for changes in [{'settings':{'seed':1.2}},{'settings':{'duration':90}},{'settings':{'unknown':5}},{'negative':'unsupported'},{'workflow_id':'bernini-edit'}]:
                r=self.client.post('/api/jobs',json={**self.body,**changes})
                self.assertEqual(r.status_code,400,r.text)
            post.assert_not_called()
    def test_same_token_submits_once(self):
        response=Mock(status_code=200);response.json.return_value={'prompt_id':'remote-123'}
        with patch.object(server.requests,'post',return_value=response) as post:
            a=self.client.post('/api/jobs',json=self.body).json()
            b=self.client.post('/api/jobs',json=self.body).json()
            self.assertEqual(a['id'],b['id']);self.assertEqual(post.call_count,1)
            self.assertEqual(len(server.jobs()),1)
    def test_uncertain_submission_never_repeats_automatically(self):
        with patch.object(server.requests,'post',side_effect=requests.Timeout) as post:
            a=self.client.post('/api/jobs',json=self.body).json()
            b=self.client.post('/api/jobs',json=self.body).json()
            self.assertEqual(a['status'],'unknown');self.assertEqual(a['id'],b['id']);self.assertEqual(post.call_count,1)
    def test_cannot_cancel_another_running_job(self):
        j=dict(id='own',token='own-token',status='running',prompt_id='own-remote');server.save(j)
        response=Mock();response.json.return_value={'queue_running':[[1,'other-remote']], 'queue_pending':[]}
        with patch.object(server.requests,'get',return_value=response),patch.object(server.requests,'post') as post:
            self.assertEqual(self.client.post('/api/jobs/own/cancel').status_code,409)
            post.assert_not_called()
    def test_private_files_and_cross_origin_submission_blocked(self):
        self.assertEqual(self.client.get('/private/workspace.sqlite3').status_code,404)
        self.assertEqual(self.client.post('/api/jobs',headers={'Origin':'https://example.com'},json=self.body).status_code,403)

    def test_running_cancel_is_targeted_and_waits_for_remote_confirmation(self):
        server.save(dict(id='own',token='own-token',status='running',prompt_id='own-remote',started=1))
        queue=Mock();queue.json.return_value={'queue_running':[[1,'own-remote']],'queue_pending':[]}
        accepted=Mock(status_code=200);accepted.json.return_value={'cancelled':True}
        with patch.object(server.requests,'get',return_value=queue),patch.object(server.requests,'post',return_value=accepted) as post:
            r=self.client.post('/api/jobs/own/cancel')
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['status'],'cancelling')
            self.assertTrue(post.call_args.args[0].endswith('/api/jobs/own-remote/cancel'))
            self.client.post('/api/jobs/own/cancel')
            self.assertEqual(post.call_count,1)
        history=Mock();history.json.return_value={'own-remote':{'status':{'status_str':'error','messages':[['execution_interrupted',{}]]}}}
        with patch.object(server.requests,'get',side_effect=[queue,history]):server.poll_once()
        self.assertEqual(server.job('own')['status'],'cancelled')

    def test_cancel_does_not_report_success_on_transport_error(self):
        server.save(dict(id='own',token='own-token',status='running',prompt_id='own-remote'))
        queue=Mock();queue.json.return_value={'queue_running':[[1,'own-remote']],'queue_pending':[]}
        with patch.object(server.requests,'get',return_value=queue),patch.object(server.requests,'post',side_effect=requests.Timeout):
            self.assertEqual(self.client.post('/api/jobs/own/cancel').status_code,200)
        self.assertEqual(server.job('own')['status'],'cancelling')
        self.assertTrue(server.job('own')['cancel_requested'])

    def test_unknown_cancel_is_persisted_and_idempotent(self):
        server.save(dict(id='lost',token='lost-token',status='unknown',prompt_id=None,started=0))
        with patch.object(server.requests,'post') as post:
            a=self.client.post('/api/jobs/lost/cancel');b=self.client.post('/api/jobs/lost/cancel')
        self.assertEqual(a.status_code,200);self.assertEqual(b.status_code,200)
        self.assertEqual(a.json()['status'],'cancelling');self.assertTrue(server.job('lost')['cancel_requested']);post.assert_not_called()

    def test_cancel_recovers_id_then_retries_scoped_cancel(self):
        server.save(dict(id='lost',token='lost-token',status='cancelling',cancel_requested=True,prompt_id=None,started=0))
        queue=Mock();queue.json.return_value={'queue_pending':[[1,'remote',{}, {'yingxu_job_id':'lost'}]],'queue_running':[]}
        history=Mock();history.json.return_value={}
        empty=Mock();empty.json.return_value={'queue_pending':[],'queue_running':[]}
        cancelled=Mock(status_code=200);cancelled.json.return_value={'cancelled':True}
        with patch.object(server.requests,'get',side_effect=[queue,history,empty]),patch.object(server.requests,'post',return_value=cancelled) as post:
            server.poll_once()
        self.assertEqual(server.job('lost')['status'],'cancelled')
        self.assertTrue(post.call_args.args[0].endswith('/api/jobs/remote/cancel'))

    def test_abandon_is_not_remote_cancel_and_cannot_resurrect(self):
        server.save(dict(id='lost',token='lost-token',status='cancelling',cancel_requested=True,prompt_id=None,started=0))
        with patch.object(server.requests,'post') as post:
            r=self.client.post('/api/jobs/lost/abandon')
        self.assertEqual(r.json()['status'],'abandoned');post.assert_not_called()
        server.update('lost',status='queued')
        self.assertEqual(server.job('lost')['status'],'abandoned')
        with patch.object(server.requests,'get') as get:server.poll_once();get.assert_not_called()

    def test_unknown_cancel_survives_offline_then_local_abandon(self):
        server.save(dict(id='offline',token='offline-token',status='unknown',prompt_id=None,started=0))
        self.client.post('/api/jobs/offline/cancel')
        with patch.object(server.requests,'get',side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout):server.poll_once()
        self.assertTrue(server.job('offline')['cancel_requested'])
        self.assertNotEqual(server.job('offline')['status'],'cancelled')
        response=self.client.post('/api/jobs/offline/abandon')
        self.assertEqual(response.json()['status'],'abandoned')

    def test_unknown_cancel_without_match_stays_unconfirmed(self):
        server.save(dict(id='lost',token='lost-token',status='cancelling',cancel_requested=True,prompt_id=None,started=0))
        queue=Mock();queue.json.return_value={'queue_pending':[],'queue_running':[]}
        history=Mock();history.json.return_value={}
        with patch.object(server.requests,'get',side_effect=[queue,history]),patch.object(server.requests,'post') as post:
            server.poll_once();post.assert_not_called()
        self.assertEqual(server.job('lost')['status'],'cancelling')
        self.assertIsNone(server.job('lost')['prompt_id'])

    def test_old_remote_never_receives_global_interrupt(self):
        server.save(dict(id='own',token='own-token',status='running',prompt_id='own-remote'))
        queue=Mock();queue.json.return_value={'queue_running':[[1,'own-remote']],'queue_pending':[]}
        unsupported=Mock(status_code=404)
        with patch.object(server.requests,'get',return_value=queue),patch.object(server.requests,'post',return_value=unsupported) as post:
            self.assertEqual(self.client.post('/api/jobs/own/cancel').status_code,409)
            self.assertEqual(post.call_count,1)
            self.assertNotIn('/interrupt',post.call_args.args[0])

    def test_private_origin_config_is_exact_and_private(self):
        (server.PRIVATE/'access.json').write_text(json.dumps({'origin':'https://my-pc.example.ts.net'}),'utf-8-sig')
        self.assertEqual(self.client.get('/api/workflows',headers={'Origin':'https://my-pc.example.ts.net'}).status_code,200)
        self.assertEqual(self.client.get('/api/workflows',headers={'Origin':'https://another.example.ts.net'}).status_code,403)
        self.assertEqual(self.client.get('/private/access.json').status_code,404)
    def test_cached_asset_is_reuploaded_when_remote_copy_disappears(self):
        (server.PRIVATE/'uploads').mkdir()
        f=io.BytesIO();Image.new('RGB',(8,8),'blue').save(f,format='PNG');data=f.getvalue()
        result=Mock(status_code=200);result.json.return_value={'name':'ours.png','subfolder':''}
        absent=Mock(status_code=404);absent.__enter__=Mock(return_value=absent);absent.__exit__=Mock(return_value=False)
        with patch.object(server.requests,'post',return_value=result) as post,patch.object(server.requests,'get',return_value=absent):
            a=self.client.post('/api/assets',files={'file':('source.png',data,'image/png')})
            b=self.client.post('/api/assets',files={'file':('source.png',data,'image/png')})
            self.assertEqual(a.status_code,200);self.assertEqual(a.json()['id'],b.json()['id']);self.assertEqual(post.call_count,2)

    def test_edit_snapshot_restores_reference_bytes_and_order(self):
        (server.PRIVATE/'uploads').mkdir()
        ids=[]
        for kind,ext,data in [('image','.png',b'original-image'),('video','.mp4',b'original-video')]:
            id=hashlib.sha256(data).hexdigest();ids.append(id)
            (server.PRIVATE/'uploads'/(id+ext)).write_bytes(data)
            a=dict(id=id,kind=kind,name='参考'+ext,bytes=len(data),remote='private/'+id+ext)
            with server.database() as db:db.execute('INSERT INTO assets VALUES (?,?)',(id,json.dumps(a)))
        j=dict(id='restore',token='restore-token',asset_ids=ids,prompt='图片1中的人物，参考视频1的动作',negative='闪烁',settings={'seed':123},graph={})
        server.save(j)
        restored=self.client.get('/api/jobs/restore').json()
        self.assertEqual([r['id'] for r in restored['references']],ids)
        self.assertNotIn('remote',restored['references'][0])
        self.assertEqual(self.client.get(restored['references'][1]['src']).content,b'original-video')
        self.assertEqual(restored['negative'],'闪烁')
        (server.PRIVATE/'uploads'/(ids[1]+'.mp4')).unlink()
        self.assertEqual(self.client.get(restored['references'][1]['src']).status_code,409)
        self.assertFalse(self.client.get('/api/jobs/restore').json()['references'][1]['available'])

    def test_rerun_uses_saved_graph_changes_only_seed_and_output_and_is_idempotent(self):
        aa=[dict(id='video-id',kind='video',remote='original.mp4')]
        settings=settings_for(manifest('bernini-edit'),{'duration':3,'long_side':384,'steps':12,'seed':123})
        graph=build_graph('bernini-edit','original prompt','original negative',settings,aa,'original')
        graph['385']['inputs']['denoise']=0.85  # Must survive even if not an exposed setting.
        original=dict(id='original',token='original-token',status='done',workflow_id='bernini-edit',prompt='original prompt',negative='original negative',settings=settings,asset_ids=['video-id'],graph=graph)
        server.save(original)
        response=Mock(status_code=200);response.json.return_value={'prompt_id':'new-remote'}
        with patch.object(server,'asset',return_value=aa[0]),patch.object(server,'ensure_remote',side_effect=lambda a:a),patch.object(server,'public_asset',side_effect=lambda a:a),patch.object(server.requests,'post',return_value=response) as post:
            body={'token':'rerun-once-token'}
            first=self.client.post('/api/jobs/original/rerun',json=body)
            self.assertEqual(first.status_code,200,first.text)
            again=self.client.post('/api/jobs/original/rerun',json=body)
            self.assertEqual(first.json()['id'],again.json()['id']);self.assertEqual(post.call_count,1)
            child=server.job(first.json()['id'])
            self.assertNotEqual(child['settings']['seed'],123)
            expected=copy.deepcopy(graph)
            for key in ['384','386']:expected[key]['inputs']['noise_seed']=child['settings']['seed']
            expected['443']['inputs']['filename_prefix']='yingxu/'+child['id']
            self.assertEqual(child['graph'],expected)
            for key in ['prompt','negative','asset_ids']:self.assertEqual(child[key],original[key])
            self.assertEqual(server.job('original'),original)

    def test_qwen_edit_rerun_changes_seed_and_keeps_both_reference_slots(self):
        assets=[dict(id='first',kind='image',remote='first.png'),dict(id='second',kind='image',remote='second.png')]
        settings=settings_for(manifest('local-card-2'),{'seed':123,'aspect_ratio':'4:3 (Standard)','megapixels':1.2})
        graph=build_graph('local-card-2','prompt','negative',settings,assets,'original-edit')
        original=dict(id='original-edit',token='original-edit-token',status='done',workflow_id='local-card-2',prompt='prompt',negative='negative',settings=settings,asset_ids=['first','second'],graph=graph)
        server.save(original)
        response=Mock(status_code=200);response.json.return_value={'prompt_id':'new-remote'}
        with patch.object(server,'asset',side_effect=lambda key:next(a for a in assets if a['id']==key)),patch.object(server,'ensure_remote',side_effect=lambda a:a),patch.object(server,'public_asset',side_effect=lambda a:a),patch.object(server.requests,'post',return_value=response):
            submitted=self.client.post('/api/jobs/original-edit/rerun',json={'token':'qwen-edit-rerun'})
        self.assertEqual(submitted.status_code,200,submitted.text)
        child=server.job(submitted.json()['id'])
        self.assertNotEqual(child['settings']['seed'],123)
        self.assertEqual(child['graph']['536']['inputs']['seed'],child['settings']['seed'])
        self.assertEqual(child['graph']['530']['inputs']['image'],'first.png')
        self.assertEqual(child['graph']['527']['inputs']['image'],'second.png')
        self.assertEqual(child['graph']['517']['inputs']['filename_prefix'],'yingxu/'+child['id'])
        self.assertEqual(child['graph']['518:491']['inputs'],graph['518:491']['inputs'])

    def test_mp4_keeps_encoded_packets_and_importable_graph(self):
        from portable import embed_workflow
        path=Path(self.tmp.name)/'clip.mp4'
        with av.open(str(path),'w') as container:
            stream=container.add_stream('libx264',rate=16);stream.width=64;stream.height=64;stream.pix_fmt='yuv420p'
            for _ in range(4):
                frame=av.VideoFrame.from_image(Image.new('RGB',(64,64),'blue'))
                for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        def packets():
            with av.open(str(path)) as container:
                return [(p.stream.index,p.pts,p.dts,hashlib.sha256(bytes(p)).hexdigest()) for p in container.demux() if p.dts is not None]
        before=packets();graph={'1':{'class_type':'LoadImage','inputs':{'image':'原图.png'}}}
        embed_workflow(path,graph)
        self.assertEqual(packets(),before)
        with av.open(str(path)) as container:self.assertEqual(json.loads(container.metadata['prompt']),graph)
        digest=path.read_bytes();embed_workflow(path,graph);self.assertEqual(path.read_bytes(),digest)

if __name__=='__main__':unittest.main(verbosity=2)
