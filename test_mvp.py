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
import struct
import zlib
import av
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'private/runtime'))
from fastapi.testclient import TestClient
from adapters import CATALOG_WORKFLOWS, manifest, settings_for, build_graph
from PIL import Image
import platform_api
from test_server_helpers import load_server, TestAccounts, ORIGIN, authenticated_client

server=None

class MVPContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the isolated import fixture; never bootstrap into the real DB.
        global server
        server,temporary=load_server('yingxu_isolated_mvp_backend')
        cls.addClassCleanup(temporary.cleanup)
        cls.addClassCleanup(lambda:sys.modules.pop(server.__name__,None))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patches=[patch.object(server,'DB',Path(self.tmp.name)/'test.sqlite3'),patch.object(server,'PRIVATE',Path(self.tmp.name)),patch.object(server,'BASE','http://comfy.example.test'),patch.object(platform_api,'PlatformAccounts',TestAccounts)]
        for p in self.patches:p.start()
        (server.PRIVATE/'receipts').mkdir()
        with server.database() as db:
            db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
            db.execute('CREATE TABLE assets (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.accounts=server.platform_bridge.accounts()
        self.owner=self.accounts.bootstrap_admin()
        for workflow_id in ('h3-reference','bernini-edit','local-card-2'):
            self.accounts.configure_pricing(self.owner['id'],workflow_id,0)
        self.client=authenticated_client(server,self.accounts,self.owner)
        self.body=dict(workflow_id='h3-reference',prompt='Ocean waves at sunrise.',token='test-idempotency-key',settings={})
    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def save_fixture(self,record):
        server.save(record)
        self.accounts.grant_resource(self.owner['id'],'job',record['id'])
        return record
    def own_asset_fixture(self,record):
        self.accounts.grant_resource(self.owner['id'],'asset',record['id'])
        self.accounts.remember_asset(self.owner['id'],record)
    @staticmethod
    def png_delivery_fixture():
        # Only synthetic credentials: exercise plain, compressed and Unicode text.
        secret=b'sk-fake-route-test-only-not-a-real-key'
        metadata=json.dumps({'prompt':{'api_key':secret.decode()},'workflow':'fake workflow'},ensure_ascii=False).encode()
        rgba=bytes([10,20,30,0,70,80,90,64,110,120,130,128,210,220,230,255])
        def chunk(kind,payload=b''):
            return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
        compressed=zlib.compress(b'\0'+rgba[:8]+b'\0'+rgba[8:])
        raw=(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,6,0,0,0))
             +chunk(b'tEXt',b'prompt\0'+metadata)
             +chunk(b'zTXt',b'workflow\0\0'+zlib.compress(metadata))
             +chunk(b'iTXt',b'workflow\0\0\0\0\0'+metadata)
             +chunk(b'iTXt',b'prompt\0\1\0\0\0'+zlib.compress(metadata))
             +chunk(b'IDAT',compressed[:4])+chunk(b'IDAT',compressed[4:])+chunk(b'IEND'))
        return raw,rgba,secret
    @staticmethod
    def png_delivery_chunks(raw):
        offset=8;chunks=[]
        while offset<len(raw):
            size=struct.unpack_from('>I',raw,offset)[0];end=offset+size+12
            chunks.append((raw[offset+4:offset+8],raw[offset:end]))
            offset=end
        return chunks
    def assert_safe_png_delivery(self,original,response,rgba,secret):
        source_chunks=self.png_delivery_chunks(original)
        self.assertEqual({kind for kind,_ in source_chunks if kind in (b'tEXt',b'iTXt',b'zTXt')},
                         {b'tEXt',b'iTXt',b'zTXt'})
        delivered=response.content;chunks=self.png_delivery_chunks(delivered)
        self.assertEqual(response.headers['content-type'],'image/png')
        self.assertFalse(any(kind in (b'tEXt',b'iTXt',b'zTXt') for kind,_ in chunks))
        self.assertNotIn(secret,delivered)
        self.assertEqual(delivered,b'\x89PNG\r\n\x1a\n'+b''.join(raw for kind,raw in source_chunks
                         if kind not in (b'tEXt',b'iTXt',b'zTXt')))
        self.assertEqual([raw for kind,raw in chunks if kind==b'IDAT'],
                         [raw for kind,raw in source_chunks if kind==b'IDAT'])
        for raw in (original,delivered):
            with Image.open(io.BytesIO(raw)) as image:
                self.assertEqual(image.mode,'RGBA');self.assertEqual(image.size,(2,2))
                self.assertEqual(image.tobytes(),rgba)
    def test_png_media_delivery_strips_text_and_keeps_rgba_idat_and_job_identity(self):
        original,rgba,secret=self.png_delivery_fixture()
        folder=server.PRIVATE/'outputs'/'fake-png-job';folder.mkdir(parents=True)
        path=folder/'0.png';path.write_bytes(original)
        graph={'190':{'class_type':'RH_LLMAPI_NODE','inputs':{'api_key':secret.decode(),'model':'fake-model'}}}
        saved={'id':'fake-png-job','token':'fake-png-token','status':'done','graph':graph,
               'outputs':[{'id':'original-output-id','src':'/api/media/fake-png-job/0.png',
                           'bytes':len(original),'type':'image','output_node':'182'}]}
        self.save_fixture(saved)
        with server.database() as db:before=db.execute('SELECT id,token,data FROM jobs').fetchall()
        source_sha=hashlib.sha256(original).hexdigest();url=saved['outputs'][0]['src']
        with patch.object(server,'poll_once') as poll,patch.object(server.requests.sessions.Session,'request',
                side_effect=AssertionError('PNG route must not contact a remote service')) as remote:
            full=self.client.get(url);self.assertEqual(full.status_code,200,full.text)
            self.assert_safe_png_delivery(original,full,rgba,secret)
            size=len(full.content)
            ranged=self.client.get(url,headers={'Range':f'bytes=0-{size-1}'})
            self.assertEqual(ranged.status_code,206,ranged.text)
            self.assertEqual(ranged.headers['content-range'],f'bytes 0-{size-1}/{size}')
            self.assert_safe_png_delivery(original,ranged,rgba,secret)
            partial=self.client.get(url,headers={'Range':'bytes=8-32'})
            self.assertEqual(partial.status_code,206);self.assertEqual(partial.content,full.content[8:33])
            self.assertEqual(partial.headers['content-range'],f'bytes 8-32/{size}')
            poll.assert_not_called();remote.assert_not_called()
        cache=server.PRIVATE/'delivery-images'/(source_sha+'.png')
        self.assertEqual(cache.read_bytes(),full.content)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),source_sha)
        self.assertEqual(path.read_bytes(),original);self.assertEqual(server.job(saved['id']),saved)
        with server.database() as db:self.assertEqual(db.execute('SELECT id,token,data FROM jobs').fetchall(),before)
    def test_png_asset_delivery_strips_text_and_keeps_source_hash_and_asset_identity(self):
        original,rgba,secret=self.png_delivery_fixture();id=hashlib.sha256(original).hexdigest()
        folder=server.PRIVATE/'uploads';folder.mkdir();path=folder/(id+'.png');path.write_bytes(original)
        saved={'id':id,'name':'owned-reference.png','kind':'image','bytes':len(original),'remote':'fake/reference.png'}
        with server.database() as db:
            db.execute('INSERT INTO assets VALUES (?,?)',(id,json.dumps(saved)))
            before=db.execute('SELECT id,data FROM assets').fetchall()
        self.own_asset_fixture(saved)
        with patch.object(server,'poll_once') as poll,patch.object(server.requests.sessions.Session,'request',
                side_effect=AssertionError('PNG asset route must not contact a remote service')) as remote:
            full=self.client.get('/api/assets/'+id+'/file');self.assertEqual(full.status_code,200,full.text)
            self.assert_safe_png_delivery(original,full,rgba,secret)
            ranged=self.client.get('/api/assets/'+id+'/file',headers={'Range':f'bytes=0-{len(full.content)-1}'})
            self.assertEqual(ranged.status_code,206,ranged.text)
            self.assert_safe_png_delivery(original,ranged,rgba,secret)
            poll.assert_not_called();remote.assert_not_called()
        self.assertEqual((server.PRIVATE/'delivery-images'/(id+'.png')).read_bytes(),full.content)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),id)
        self.assertEqual(path.read_bytes(),original);self.assertEqual(server.asset(id),saved)
        with server.database() as db:
            self.assertEqual(db.execute('SELECT id,data FROM assets').fetchall(),before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
    def test_malformed_png_media_and_asset_routes_fail_closed_without_original_fallback(self):
        valid,_,secret=self.png_delivery_fixture()
        # A truncated end and a corrupt text CRC are both invalid despite valid pixels.
        broken_crc=bytearray(valid);text_end=8+len(self.png_delivery_chunks(valid)[0][1])+len(self.png_delivery_chunks(valid)[1][1])
        broken_crc[text_end-1]^=1
        with patch.object(server,'poll_once') as poll,patch.object(server.requests.sessions.Session,'request',
                side_effect=AssertionError('Malformed PNG delivery must not contact a remote service')) as remote:
            for index,original in enumerate((valid[:-1],bytes(broken_crc))):
                with self.subTest(case=index):
                    id=hashlib.sha256(original).hexdigest();job_id='malformed-png-'+str(index)
                    output_dir=server.PRIVATE/'outputs'/job_id;output_dir.mkdir(parents=True)
                    source=output_dir/'0.png';source.write_bytes(original)
                    upload_dir=server.PRIVATE/'uploads';upload_dir.mkdir(exist_ok=True)
                    asset_source=upload_dir/(id+'.png');asset_source.write_bytes(original)
                    saved={'id':job_id,'token':job_id,'status':'done','graph':{'fake_key':secret.decode()},
                           'outputs':[{'id':'unchanged-'+str(index),'src':f'/api/media/{job_id}/0.png','bytes':len(original)}]}
                    self.save_fixture(saved)
                    with server.database() as db:
                        db.execute('INSERT INTO assets VALUES (?,?)',(id,json.dumps({'id':id,'name':'invalid.png','bytes':len(original)})))
                        jobs_before=db.execute('SELECT id,token,data FROM jobs').fetchall()
                        assets_before=db.execute('SELECT id,data FROM assets').fetchall()
                    self.own_asset_fixture({'id':id,'name':'invalid.png','bytes':len(original)})
                    for url in (saved['outputs'][0]['src'],'/api/assets/'+id+'/file'):
                        for headers in ({},{'Range':'bytes=0-63'}):
                            response=self.client.get(url,headers=headers)
                            self.assertEqual(response.status_code,500,response.text)
                            self.assertIn('原件已保留',response.json()['detail'])
                            self.assertNotIn(secret,response.content);self.assertNotEqual(response.content,original)
                    self.assertEqual(source.read_bytes(),original);self.assertEqual(asset_source.read_bytes(),original)
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),id)
                    self.assertFalse((server.PRIVATE/'delivery-images'/(id+'.png')).exists())
                    with server.database() as db:
                        self.assertEqual(db.execute('SELECT id,token,data FROM jobs').fetchall(),jobs_before)
                        self.assertEqual(db.execute('SELECT id,data FROM assets').fetchall(),assets_before)
            poll.assert_not_called();remote.assert_not_called()
    def test_empty_translation_guard_requires_reviewed_source_chain_and_explicit_receipt(self):
        spec=server.schema_adapters.manifest('local-card-93')
        graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        graph['71']['inputs']['prompt']='把花瓶改成蓝色，保持一只花瓶。'
        job={'workflow_id':spec['id'],'schema_spec':spec,'graph':graph}
        empty={'outputs':{'82':{'text':['','  ']}}}
        self.assertIn('英文直接使用',server.reviewed_translation_failure(job,empty))
        matched=copy.deepcopy(job)
        from reviewed_repairs import apply_reviewed_repairs
        apply_reviewed_repairs(matched['graph'],spec)
        self.assertIn('英文直接使用',server.reviewed_translation_failure(matched,empty))
        matched['graph']['10'].pop('_meta',None)
        self.assertIsNone(server.reviewed_translation_failure(matched,empty))
        for receipt in ({'outputs':{}},{'outputs':None},{'outputs':{'82':None}},
                        {'outputs':{'82':{'text':[]}}},
                        {'outputs':{'82':{'text':['a blue vase']}}},
                        {'outputs':{'82':{'text':[None]}}}):
            self.assertIsNone(server.reviewed_translation_failure(job,receipt))
        altered=copy.deepcopy(job);altered['graph']['82']['inputs']['text']=['71',0]
        self.assertIsNone(server.reviewed_translation_failure(altered,empty))
        altered=copy.deepcopy(job);altered['schema_spec']['source_hash']='new-source'
        self.assertIsNone(server.reviewed_translation_failure(altered,empty))
        altered=copy.deepcopy(job);altered['graph']['71']['inputs']['prompt']='  '
        self.assertIsNone(server.reviewed_translation_failure(altered,empty))
    def test_collect_retains_returned_image_and_receipt_when_translation_failed(self):
        spec=server.schema_adapters.manifest('local-card-93')
        graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        graph['71']['inputs']['prompt']='把花瓶改成蓝色。'
        job={'id':'empty-translation','token':'empty-translation','workflow_id':spec['id'],
             'schema_spec':spec,'graph':graph,'status':'queued'}
        with server.database() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?)',(job['id'],job['token'],json.dumps(job)))
        self.accounts.grant_resource(self.owner['id'],'job',job['id'])
        folder=server.PRIVATE/'outputs'/job['id'];folder.mkdir(parents=True)
        Image.new('RGB',(16,16),'blue').save(folder/'0.png')
        before=hashlib.sha256((folder/'0.png').read_bytes()).hexdigest()
        receipt={'outputs':{'48':{'images':[{'filename':'test.png','subfolder':'','type':'output'}]},
                            '82':{'text':['']}},'status':{'status_str':'success'}}
        with patch.object(server.requests,'get') as remote:
            server.collect(job,receipt)
            remote.assert_not_called()
        saved=server.job(job['id'])
        self.assertEqual(saved['status'],'failed');self.assertEqual(saved['stage'],'描述翻译失败')
        self.assertEqual(len(saved['outputs']),1)
        self.assertEqual(saved['outputs'][0]['src'],'/api/media/empty-translation/0.png')
        self.assertEqual(hashlib.sha256((folder/'0.png').read_bytes()).hexdigest(),before)
        self.assertEqual(json.loads((server.PRIVATE/'receipts'/(job['id']+'.json')).read_text('utf-8')),receipt)
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
    def test_inpaint_submission_preserves_only_confirmed_uploaded_mask_region(self):
        from region_preservation import REGION_NODE
        uploads=server.PRIVATE/'uploads';uploads.mkdir()
        source_id='b'*64
        marked=Image.new('RGBA',(32,32),(40,90,150,255))
        marked.putpixel((8,8),(40,90,150,0))
        marked.save(uploads/(source_id+'.png'))
        record={'id':source_id,'kind':'image','remote':'marked.png','width':32,'height':32}
        for workflow_id,slot,output in [('local-card-86','91','46'),('local-card-131','134','174')]:
            with self.subTest(workflow_id=workflow_id):
                spec=server.schema_adapters.manifest(workflow_id)
                body=server.Submission(workflow_id=workflow_id,source_hash=spec['source_hash'],
                       prompt='Replace the selected mark with a red star.',
                       catalog_assets={slot:source_id},token='region-'+workflow_id)
                with patch.object(server,'asset',return_value=record),patch.object(server,'ensure_remote',side_effect=lambda item:item):
                    with server.database() as db:prepared=server.prepare_schema_submission(body,spec,db)
                composite=prepared['graph'][REGION_NODE]
                self.assertEqual(composite['inputs']['destination'],[slot,0])
                self.assertEqual(composite['inputs']['mask'],[slot,1])
                self.assertEqual(prepared['graph'][output]['inputs']['images'],[REGION_NODE,0])
                self.assertEqual(prepared['execution_adaptations'][0]['output_size'],'original-image')
                # Both re-editing and rerunning must keep this final constraint.
                rerun,values=server.schema_adapters.rerun(prepared,{slot:record},'region-rerun')
                server.preserve_region_output(spec,rerun)
                self.assertEqual(rerun[REGION_NODE],composite)
    def test_region_preservation_rejects_unknown_source_or_mask_without_partial_rewrite(self):
        for workflow_id,slot in [('local-card-86','91'),('local-card-131','134')]:
            with self.subTest(workflow_id=workflow_id):
                spec=server.schema_adapters.manifest(workflow_id)
                original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                altered=copy.deepcopy(original);altered[slot]['class_type']='UnreviewedSource'
                before=copy.deepcopy(altered)
                with self.assertRaises(ValueError):server.preserve_region_output(spec,altered)
                self.assertEqual(altered,before)
                altered_spec={**spec,'source_hash':'unreviewed-new-source'}
                with self.assertRaises(ValueError):server.preserve_region_output(altered_spec,original)
                self.assertEqual(original,json.loads(server.schema_adapters.template_path(spec).read_text('utf-8')))
    def test_reviewed_pose_and_inbetween_labels_preserve_media_identity_and_existing_order_metadata(self):
        expected={30:{'36':('生成视频','result'),'147':('姿态控制预览','control')},
                  124:{'65':('首尾帧生成结果','result'),'34':('补间生成结果','result')}}
        for card,roles in expected.items():
            with self.subTest(card=card):
                spec=server.schema_adapters.manifest('local-card-'+str(card))
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                graph_before=copy.deepcopy(graph)
                self.assertEqual(server.reviewed_output_metadata(spec,graph),
                                 {node:dict(label=label,role=role)for node,(label,role)in roles.items()})
                items=[{'output_node':node}for node in spec['outputs']]
                outputs=[{'id':f'label{card}o{i}','src':f'/api/media/unchanged/{i}.mp4',
                          'output_node':item['output_node'],'display_order':9-i,
                          'bytes':100+i,'removedAt':123 if i==0 else None,'published':i==1}
                         for i,item in enumerate(items)]
                before=copy.deepcopy(outputs)
                job={'id':'label'+str(card),'workflow_id':spec['id'],'schema_spec':spec,'graph':graph,'outputs':outputs}
                result=server.present_outputs(job,items,outputs)
                self.assertEqual([out['id']for out in result],[out['id']for out in before])
                self.assertEqual([out['src']for out in result],[out['src']for out in before])
                for old,new in zip(before,result):
                    for key in old:self.assertEqual(new[key],old[key])
                    self.assertEqual((new['label'],new['role']),roles[new['output_node']])
                self.assertEqual(server.historical_output_presentation(job),result)
                self.assertEqual(outputs,before);self.assertEqual(graph,graph_before)

    def test_pose_and_inbetween_labels_reject_source_hash_and_output_chain_drift(self):
        for card in (30,124):
            spec=server.schema_adapters.manifest('local-card-'+str(card))
            graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
            self.assertEqual(server.reviewed_output_metadata({**spec,'source_hash':'drift'},graph),{})
            self.assertEqual(server.reviewed_output_metadata({**spec,'source_hash':None},graph),{})
        cases=[(30,'36','12','image',['48',1],{'147'}),
               (30,'147','147','images',['12',0],{'36'}),
               (124,'65','62','samples',['61',1],{'34'}),
               (124,'34','19','positive',['44',0],{'65'})]
        for card,output,node,key,replacement,remaining in cases:
            with self.subTest(card=card,node=node):
                spec=server.schema_adapters.manifest('local-card-'+str(card))
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                graph[node]['inputs'][key]=replacement
                before=copy.deepcopy(graph)
                metadata=server.reviewed_output_metadata(spec,graph)
                self.assertNotIn(output,metadata);self.assertEqual(set(metadata),remaining)
                self.assertEqual(graph,before)

    def test_reviewed_character_video_labels_preserve_identity_order_and_source_records(self):
        expectations={
            22:{'200':('主体分割预览','mask'),'86':('原片预览','control'),'119':('生成视频','result')},
            23:{'491':('原片预览','control'),'508':('生成视频','result'),'475':('主体分割预览','mask')},
            24:{'3667':('面部控制预览','control'),'3683':('主体控制预览','control'),
                '3701':('对比预览 · 参考图 / 面部控制 / 生成结果','comparison'),'3736':('生成视频','result')},
            25:{'566':('面部控制预览','control'),'600':('对比预览 · 参考图 / 面部控制 / 生成结果','comparison'),
                '635':('生成视频','result'),'582':('主体控制预览','control')},
            26:{'430':('对比预览 · 参考图 / 面部控制 / 生成结果','comparison'),'493':('姿态骨架预览','control'),
                '396':('面部控制预览','control'),'465':('生成视频','result')},
            27:{'696':('面部控制预览','control'),'712':('服装控制预览','control'),
                '730':('对比预览 · 参考图 / 面部控制 / 生成结果','comparison'),'765':('生成视频','result')},
            28:{'377':('主体控制预览','control'),'398':('面部控制预览','control'),'508':('生成视频 · 首次结果','result'),
                '358':('生成视频 · 放大','result'),'345':('生成视频 · 插帧','result')},
            116:{'696':('面部控制预览','control'),'730':('对比预览 · 参考图 / 面部控制 / 生成结果','comparison'),
                 '765':('生成视频','result'),'712':('服装控制预览','control')},
            40:{'40':('生成视频','result'),'42':('对比预览 · 原片 / 生成结果 / 参考图','comparison')},
            43:{'362':('对比预览 · 原片 / 编辑结果','comparison'),'363':('编辑结果','result')},
            44:{'5069':('修复结果','result'),'5135':('对比预览 · 原片 / 修复结果','comparison')},
            45:{'37':('对比预览 · 原片 / 编辑结果','comparison'),'24':('编辑结果','result')},
            46:{'5104':('扩图结果','result'),'5131':('对比预览 · 原片 / 扩图结果','comparison')},
        }
        for card,expected in expectations.items():
            with self.subTest(card=card):
                spec=server.schema_adapters.manifest('local-card-'+str(card))
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                graph_before=copy.deepcopy(graph)
                metadata=server.reviewed_output_metadata(spec,graph)
                self.assertEqual(metadata,{node:{'label':label,'role':role}for node,(label,role)in expected.items()})
                job_id='character-label-'+str(card)
                items=[{'output_node':node}for node in spec['outputs']]
                outputs=[{'id':job_id+'o'+str(i),'type':'video','src':f'/api/media/{job_id}/{i}.mp4',
                          'label':None,'bytes':100+i,'published':i==1,'removedAt':123 if i==0 else None}
                         for i in range(len(items))]
                before=copy.deepcopy(outputs)
                job={'id':job_id,'workflow_id':spec['id'],'schema_spec':spec,'graph':graph,'outputs':outputs}
                result=server.present_outputs(job,items,outputs)
                self.assertEqual([o['id']for o in result],[o['id']for o in before])
                self.assertEqual([o['src']for o in result],[o['src']for o in before])
                for i,output in enumerate(result):
                    self.assertEqual(output['output_node'],items[i]['output_node'])
                    self.assertEqual((output['label'],output['role']),expected[items[i]['output_node']])
                    for key in ('bytes','published','removedAt'):self.assertEqual(output[key],before[i][key])
                    self.assertNotIn('display_order',output)
                historical={**job,'outputs':[dict(o,output_node=item['output_node'])for o,item in zip(outputs,items)]}
                self.assertEqual(server.historical_output_presentation(historical),result)
                self.assertEqual(outputs,before);self.assertEqual(graph,graph_before)

    def test_character_video_labels_reject_swapped_ports_and_unreviewed_decode_chains(self):
        for card,pure,decode,sampler,comparison in [
            (22,'119','43','41',None),(23,'508','465','489',None),
            (24,'3736','3657','3739','3701'),(25,'635','556','638','600'),
            (26,'465','386','468','430'),(27,'765','686','768','730'),
            (116,'765','686','768','730'),(40,'40','18','31','42'),
            (43,'363','467','500','362'),(44,'5069','5158:5113','5102','5135'),
            (45,'24','50:44','50:35','37'),(46,'5104','5167:5132','5126','5131')]:
            spec=server.schema_adapters.manifest('local-card-'+str(card))
            original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
            for changed_node in (decode,sampler):
                with self.subTest(card=card,node=changed_node):
                    graph=copy.deepcopy(original);graph[changed_node]['class_type']='UnreviewedImageSource'
                    metadata=server.reviewed_output_metadata(spec,graph)
                    self.assertNotIn(pure,metadata)
                    if comparison:self.assertNotIn(comparison,metadata)
            for output_node in spec['outputs']:
                with self.subTest(card=card,output=output_node):
                    graph=copy.deepcopy(original);graph[output_node]['inputs']['images']=['unrelated',0]
                    metadata=server.reviewed_output_metadata(spec,graph)
                    self.assertNotIn(output_node,metadata)
                    self.assertEqual(set(metadata),set(spec['outputs'])-{output_node})
        for card,face in [(24,'3667'),(25,'566'),(26,'396'),(27,'696'),(28,'398'),(116,'696')]:
            with self.subTest(card=card,face=face):
                spec=server.schema_adapters.manifest('local-card-'+str(card))
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                graph[face]['inputs']['images'][1]=0
                self.assertNotIn(face,server.reviewed_output_metadata(spec,graph),'pose port0 must not receive face label')

    def test_character_loop_outputs_require_both_decode_branches_and_actual_enhancement_paths(self):
        spec=server.schema_adapters.manifest('local-card-28')
        original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        for node in ('285','290','288','294'):
            with self.subTest(node=node):
                graph=copy.deepcopy(original);graph[node]['class_type']='UnreviewedSource'
                self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),{'377','398'})
        for node,key,value,remaining in [
            ('354','images',['539',0],{'377','398','508'}),
            ('317','frames',['539',0],{'377','398','508','358'}),
            ('345','images',['354',0],{'377','398','508','358'})]:
            with self.subTest(node=node,key=key):
                graph=copy.deepcopy(original);graph[node]['inputs'][key]=value
                self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),remaining)

    def test_video_edit_labels_require_actual_comparison_composition_and_decode_ports(self):
        cases=[(40,'42','41','image2',['27',0],'40','18','samples',['31',1]),
               (43,'362','436','image1',['467',0],'363','467','samples',['405',0]),
               (44,'5135','5158:5134','image2',['5099',0],'5069','5158:5113','samples',['5158:5111',0]),
               (45,'37','50:28','image2',['34',0],'24','50:44','samples',['50:8',0]),
               (46,'5131','5167:5133','image2',['5167:5130',0],'5104','5167:5132','samples',['5167:5123',0]),
               (48,'362','436','image1',['467',0],'363','467','samples',['405',0]),
               (49,'357','431','image1',['394',0],'358','394','samples',['456',0]),
               (60,'330','332','image_2',['361',0],'347','45','samples',['22',1])]
        for card,comparison,concat,key,replacement,pure,decode,decode_key,decode_port in cases:
            with self.subTest(card=card):
                spec=server.schema_adapters.manifest('local-card-'+str(card))
                original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                graph=copy.deepcopy(original);graph[concat]['inputs'][key]=replacement
                self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),{pure})
                graph=copy.deepcopy(original);graph[decode]['inputs'][decode_key]=decode_port
                self.assertEqual(server.reviewed_output_metadata(spec,graph),{})
                # Playback FPS fixes do not alter what each media file represents.
                graph=copy.deepcopy(original)
                for output in spec['outputs']:graph[output]['inputs']['frame_rate']=24
                self.assertEqual(server.reviewed_output_metadata(spec,graph),server.reviewed_output_metadata(spec,original))

    def test_new_local_edit_labels_preserve_output_order_and_distinguish_two_pass_preview(self):
        expected={48:{'363':('编辑结果','result'),'362':('对比预览 · 原片 / 编辑结果','comparison')},
                  49:{'358':('换衣结果','result'),'357':('对比预览 · 原片 / 换衣结果','comparison')},
                  50:{'477':('编辑结果 · 首次','result'),'75':('编辑结果 · 放大精修','result'),
                      '491':('对比预览 · 原片 / 首次结果','comparison')},
                  60:{'347':('修复结果','result'),'330':('对比预览 · 原片 / 修复结果','comparison')},
                  126:{'39':('生成视频 · 原始结果','result'),'72':('生成视频 · 放大','result'),
                       '63':('生成视频 · 放大插帧','result')}}
        for card,roles in expected.items():
            with self.subTest(card=card):
                spec=server.schema_adapters.manifest('local-card-'+str(card))
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                before=copy.deepcopy(graph);metadata=server.reviewed_output_metadata(spec,graph)
                self.assertEqual(metadata,{node:dict(label=label,role=role)for node,(label,role)in roles.items()})
                outputs=[{'id':str(card)+'o'+str(i),'src':'/api/media/original/'+str(i)+'.mp4'}for i in range(len(spec['outputs']))]
                result=server.present_outputs({'id':'labels','workflow_id':spec['id'],'schema_spec':spec,'graph':graph},
                                              [{'output_node':node}for node in spec['outputs']],outputs)
                self.assertEqual([o['id']for o in result],[o['id']for o in outputs])
                self.assertEqual([o['src']for o in result],[o['src']for o in outputs])
                self.assertEqual(graph,before)
        spec=server.schema_adapters.manifest('local-card-50')
        original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        # A comparison containing the refined decode may not claim only first pass.
        graph=copy.deepcopy(original);graph['482']['inputs']['image']=['439',0]
        self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),{'477','75'})
        graph=copy.deepcopy(original);graph['439']['inputs']['samples']=['437',1]
        self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),{'477','491'})
        graph=copy.deepcopy(original);graph['475']['inputs']['samples']=['470',1]
        self.assertEqual(server.reviewed_output_metadata(spec,graph),{})
        spec=server.schema_adapters.manifest('local-card-126')
        original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        for node,key,value,remaining in [('62','frames',['11',0],{'39','72'}),
                                          ('71','images',['unreviewed',0],{'39'}),
                                          ('11','samples',['8',1],set())]:
            graph=copy.deepcopy(original);graph[node]['inputs'][key]=value
            self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),remaining)

    def test_character_video_historical_receipt_fallback_keeps_saved_file_numbers(self):
        spec=server.schema_adapters.manifest('local-card-25')
        graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        job_id='character-old-25'
        outputs=[{'id':job_id+'o'+str(i),'type':'video','src':f'/api/media/{job_id}/{i}.mp4','label':None}
                 for i in range(len(spec['outputs']))]
        receipt={'outputs':{node:{'gifs':[{'filename':f'unknown-{i}.mp4','type':'output'}]}
                            for i,node in reversed(list(enumerate(spec['outputs'])))}}
        (server.PRIVATE/'receipts'/(job_id+'.json')).write_text(json.dumps(receipt),'utf-8')
        job={'id':job_id,'workflow_id':spec['id'],'schema_spec':spec,'graph':graph,'outputs':outputs}
        before=copy.deepcopy(job)
        result=server.historical_output_presentation(job)
        self.assertEqual([o['id']for o in result],[o['id']for o in outputs])
        self.assertEqual([o['src']for o in result],[o['src']for o in outputs])
        self.assertEqual([o['role']for o in result],['control','comparison','result','control'])
        self.assertEqual(job,before)

    def test_reviewed_image_outputs_label_actual_chains_and_preserve_file_identity(self):
        for workflow_id,pure_node,comparison_node in [('local-card-95','24','13'),('local-card-96','18','22')]:
            with self.subTest(workflow_id=workflow_id):
                spec=server.schema_adapters.manifest(workflow_id)
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                original_graph=copy.deepcopy(graph)
                job={'id':'reviewed-image','workflow_id':workflow_id,'schema_spec':spec,'graph':graph}
                items=[{'output_node':comparison_node},{'output_node':pure_node}]
                outputs=[{'id':'reviewed-imageo0','type':'image','src':'/api/media/reviewed-image/0.png','bytes':123},
                         {'id':'reviewed-imageo1','type':'image','src':'/api/media/reviewed-image/1.png','bytes':456}]
                original_outputs=copy.deepcopy(outputs)
                result=server.present_outputs(job,items,outputs)
                self.assertEqual([output['id']for output in result],['reviewed-imageo1','reviewed-imageo0'])
                self.assertEqual([output['output_node']for output in result],[pure_node,comparison_node])
                self.assertEqual([output['role']for output in result],['result','comparison'])
                self.assertEqual(result[0]['label'],'编辑结果')
                self.assertIn('对比拼图',result[1]['label'])
                self.assertIn('两张参考图' if workflow_id=='local-card-96' else '原图',result[1]['label'])
                for output in result:
                    old=next(item for item in outputs if item['id']==output['id'])
                    for key in old:self.assertEqual(output[key],old[key])
                self.assertEqual(outputs,original_outputs);self.assertEqual(graph,original_graph)

    def test_reviewed_edit_labels_do_not_follow_wrong_nodes_or_swapped_output_links(self):
        for workflow_id,pure_node,comparison_node,pure_source,comparison_source,decode_node,stitch_node in [
            ('local-card-95','24','13','11','5','11','5'),('local-card-96','18','22','19','6','19','6')]:
            with self.subTest(workflow_id=workflow_id):
                spec=server.schema_adapters.manifest(workflow_id)
                original=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                self.assertEqual(server.reviewed_output_metadata({'id':'unreviewed'},original),{})
                graph=copy.deepcopy(original)
                graph[pure_node]['inputs']['images']=[comparison_source,0]
                graph[comparison_node]['inputs']['images']=[pure_source,0]
                self.assertEqual(server.reviewed_output_metadata(spec,graph),{})
                graph=copy.deepcopy(original);graph[decode_node]['class_type']='SyntheticUnreviewedImage'
                self.assertEqual(server.reviewed_output_metadata(spec,graph),{})
                graph=copy.deepcopy(original);graph[stitch_node]['inputs']['image2']=['unrelated',0]
                self.assertEqual(set(server.reviewed_output_metadata(spec,graph)),{pure_node})

    def test_background_outputs_distinguish_alpha_subject_and_actual_white_fill(self):
        spec=server.schema_adapters.manifest('local-card-133')
        graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        metadata=server.reviewed_output_metadata(spec,graph)
        self.assertEqual(metadata['18'],{'label':'透明主体','role':'result','display_order':0})
        self.assertEqual(metadata['17'],{'label':'白底图','role':'result','display_order':1})
        for node,key,value in [('19','color','#000000'),('16','fill_background',False),
                               ('16','mask',['12',0]),('16','RGBA_image',['12',0])]:
            with self.subTest(node=node,key=key):
                changed=copy.deepcopy(graph);changed[node]['inputs'][key]=value
                self.assertEqual(set(server.reviewed_output_metadata(spec,changed)),{'18'})
        changed=copy.deepcopy(graph);changed['18']['inputs']['images']=['11',1]
        self.assertNotIn('18',server.reviewed_output_metadata(spec,changed))
        changed=copy.deepcopy(graph);changed['11']['class_type']='SyntheticOpaqueImage'
        self.assertEqual(server.reviewed_output_metadata(spec,changed),{})

    def test_upscaler_outputs_distinguish_original_direct_and_redrawn_branches(self):
        spec=server.schema_adapters.manifest('local-card-90')
        graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        before=copy.deepcopy(graph)
        metadata=server.reviewed_output_metadata(spec,graph)
        self.assertEqual(set(metadata),{'115','16','128','92'})
        self.assertEqual(metadata['115'],{'label':'原图','role':'control','display_order':3})
        self.assertEqual(metadata['16']['label'],'放大结果 A · SeedVR')
        self.assertEqual(metadata['128']['label'],'放大结果 B · 重绘后 SeedVR')
        self.assertEqual(metadata['92']['label'],'Wan 重绘放大结果')
        job={'id':'upscaler-output','workflow_id':spec['id'],'schema_spec':spec,'graph':graph}
        outputs=[{'id':job['id']+'o'+str(i),'src':'/api/media/unchanged/'+str(i)+'.png'}for i in range(4)]
        result=server.present_outputs(job,[{'output_node':node}for node in spec['outputs']],outputs)
        self.assertEqual([output['id']for output in result],['upscaler-outputo1','upscaler-outputo2','upscaler-outputo3','upscaler-outputo0'])
        for output in result:self.assertEqual(output['src'],next(old['src']for old in outputs if old['id']==output['id']))
        self.assertEqual(graph,before)
        for node,key,value,remaining in [
            ('128','images',['13',0],{'115','16','92'}),
            ('126','image',['11',0],{'115','16','92'}),
            ('13','image',['86',0],{'115','128','92'}),
            ('67','pixels',['11',0],{'115','16'}),
            ('77','unet_name','unreviewed-model.safetensors',{'115','16'}),
            ('115','images',['86',0],{'16','128','92'}),
        ]:
            with self.subTest(node=node,key=key):
                changed=copy.deepcopy(graph);changed[node]['inputs'][key]=value
                self.assertEqual(set(server.reviewed_output_metadata(spec,changed)),remaining)
        old_job={**job,'outputs':[dict(outputs[0],output_node='115'),dict(outputs[1],output_node='16')]}
        shown=server.historical_output_presentation(old_job)
        self.assertEqual([output['label']for output in shown],['放大结果 A · SeedVR','原图'])
        self.assertNotIn('label',old_job['outputs'][0],'historical projection does not change saved output records')

    def test_historical_labels_are_read_only_receipt_derived_and_keep_output_identity(self):
        for workflow_id,pure_node,comparison_node in [('local-card-95','24','13'),('local-card-96','18','22')]:
            with self.subTest(workflow_id=workflow_id):
                spec=server.schema_adapters.manifest(workflow_id)
                graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
                job_id=workflow_id+'-history'
                outputs=[{'id':job_id+'o0','type':'image','src':'/api/media/'+job_id+'/0.png','label':None,'removedAt':123,'published':True},
                         {'id':job_id+'o1','type':'image','src':'/api/media/'+job_id+'/1.png','label':None,'bytes':456}]
                job={'id':job_id,'token':job_id+'-private','workflow_id':workflow_id,'schema_spec':spec,'graph':graph,
                     'asset_ids':[],'status':'done','outputs':outputs}
                # The old collector used registered output order, not receipt
                # dictionary insertion order. File names intentionally reveal
                # no semantic role.
                receipt={'outputs':{pure_node:{'images':[{'filename':'unknown-b.png','type':'output'}]},
                                    comparison_node:{'images':[{'filename':'unknown-a.png','type':'output'}]}}}
                path=server.PRIVATE/'receipts'/(job_id+'.json');path.write_text(json.dumps(receipt),'utf-8')
                before_receipt=path.read_bytes();before=copy.deepcopy(job)
                with server.database()as db:db.execute('INSERT INTO jobs VALUES (?,?,?)',(job_id,job['token'],json.dumps(job)))
                self.accounts.grant_resource(self.owner['id'],'job',job_id)
                with patch.object(server.requests,'get')as get,patch.object(server.requests,'post')as post:
                    response=self.client.get('/api/jobs/'+job_id)
                    get.assert_not_called();post.assert_not_called()
                self.assertEqual(response.status_code,200)
                presented=response.json()['outputs']
                self.assertEqual([output['id']for output in presented],[job_id+'o1',job_id+'o0'])
                self.assertEqual([output['output_node']for output in presented],[pure_node,comparison_node])
                self.assertEqual([output['role']for output in presented],['result','comparison'])
                self.assertEqual(presented[0]['label'],'编辑结果')
                self.assertEqual(presented[1]['src'],outputs[0]['src'])
                self.assertEqual(presented[1]['removedAt'],123);self.assertTrue(presented[1]['published'])
                self.assertEqual(server.job(job_id),before);self.assertEqual(path.read_bytes(),before_receipt)

    def test_historical_labels_never_guess_without_receipt_or_exact_graph_mapping(self):
        spec=server.schema_adapters.manifest('local-card-95')
        graph=json.loads(server.schema_adapters.template_path(spec).read_text('utf-8'))
        job={'id':'missing-history','token':'private-token','workflow_id':spec['id'],'schema_spec':spec,'graph':graph,
             'asset_ids':[],'outputs':[{'id':'missing-historyo0','src':'/kept.png','label':None}]}
        before=copy.deepcopy(job)
        self.assertEqual(server.public(job)['outputs'],job['outputs'])
        (server.PRIVATE/'receipts'/'missing-history.json').write_text('{invalid','utf-8')
        self.assertEqual(server.public(job)['outputs'],job['outputs'])
        job['outputs'][0]['output_node']='13'
        self.assertEqual(server.public(job)['outputs'][0]['role'],'comparison','already recorded node identity needs no receipt guessing')
        job['graph']['5']['inputs']['image2']=['unrelated',0]
        self.assertIsNone(server.public(job)['outputs'][0]['label'])
        self.assertNotIn('role',server.public(job)['outputs'][0])
        self.assertEqual(job['outputs'][0]['src'],before['outputs'][0]['src'])
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
        self.own_asset_fixture(record)
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
        j=dict(id='own',token='own-token',status='running',prompt_id='own-remote');self.save_fixture(j)
        response=Mock();response.json.return_value={'queue_running':[[1,'other-remote']], 'queue_pending':[]}
        with patch.object(server.requests,'get',return_value=response),patch.object(server.requests,'post') as post:
            self.assertEqual(self.client.post('/api/jobs/own/cancel').status_code,409)
            post.assert_not_called()
    def test_private_files_and_cross_origin_submission_blocked(self):
        self.assertEqual(self.client.get('/private/workspace.sqlite3').status_code,404)
        self.assertEqual(self.client.post('/api/jobs',headers={'Origin':'https://example.com'},json=self.body).status_code,403)

    def test_running_cancel_is_targeted_and_waits_for_remote_confirmation(self):
        self.save_fixture(dict(id='own',token='own-token',status='running',prompt_id='own-remote',started=1))
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
        self.save_fixture(dict(id='own',token='own-token',status='running',prompt_id='own-remote'))
        queue=Mock();queue.json.return_value={'queue_running':[[1,'own-remote']],'queue_pending':[]}
        with patch.object(server.requests,'get',return_value=queue),patch.object(server.requests,'post',side_effect=requests.Timeout):
            self.assertEqual(self.client.post('/api/jobs/own/cancel').status_code,200)
        self.assertEqual(server.job('own')['status'],'cancelling')
        self.assertTrue(server.job('own')['cancel_requested'])

    def test_unknown_cancel_is_persisted_and_idempotent(self):
        self.save_fixture(dict(id='lost',token='lost-token',status='unknown',prompt_id=None,started=0))
        with patch.object(server.requests,'post') as post:
            a=self.client.post('/api/jobs/lost/cancel');b=self.client.post('/api/jobs/lost/cancel')
        self.assertEqual(a.status_code,200);self.assertEqual(b.status_code,200)
        self.assertEqual(a.json()['status'],'cancelling');self.assertTrue(server.job('lost')['cancel_requested']);post.assert_not_called()

    def test_cancel_recovers_id_then_retries_scoped_cancel(self):
        self.save_fixture(dict(id='lost',token='lost-token',status='cancelling',cancel_requested=True,prompt_id=None,started=0))
        queue=Mock();queue.json.return_value={'queue_pending':[[1,'remote',{}, {'yingxu_job_id':'lost'}]],'queue_running':[]}
        history=Mock();history.json.return_value={}
        empty=Mock();empty.json.return_value={'queue_pending':[],'queue_running':[]}
        cancelled=Mock(status_code=200);cancelled.json.return_value={'cancelled':True}
        with patch.object(server.requests,'get',side_effect=[queue,history,empty]),patch.object(server.requests,'post',return_value=cancelled) as post:
            server.poll_once()
        self.assertEqual(server.job('lost')['status'],'cancelled')
        self.assertTrue(post.call_args.args[0].endswith('/api/jobs/remote/cancel'))

    def test_abandon_is_not_remote_cancel_and_cannot_resurrect(self):
        self.save_fixture(dict(id='lost',token='lost-token',status='cancelling',cancel_requested=True,prompt_id=None,started=0))
        with patch.object(server.requests,'post') as post:
            r=self.client.post('/api/jobs/lost/abandon')
        self.assertEqual(r.json()['status'],'abandoned');post.assert_not_called()
        server.update('lost',status='queued')
        self.assertEqual(server.job('lost')['status'],'abandoned')
        with patch.object(server.requests,'get') as get:server.poll_once();get.assert_not_called()

    def test_unknown_cancel_survives_offline_then_local_abandon(self):
        self.save_fixture(dict(id='offline',token='offline-token',status='unknown',prompt_id=None,started=0))
        self.client.post('/api/jobs/offline/cancel')
        with patch.object(server.requests,'get',side_effect=requests.Timeout):
            with self.assertRaises(requests.Timeout):server.poll_once()
        self.assertTrue(server.job('offline')['cancel_requested'])
        self.assertNotEqual(server.job('offline')['status'],'cancelled')
        response=self.client.post('/api/jobs/offline/abandon')
        self.assertEqual(response.json()['status'],'abandoned')

    def test_unknown_cancel_without_match_stays_unconfirmed(self):
        self.save_fixture(dict(id='lost',token='lost-token',status='cancelling',cancel_requested=True,prompt_id=None,started=0))
        queue=Mock();queue.json.return_value={'queue_pending':[],'queue_running':[]}
        history=Mock();history.json.return_value={}
        with patch.object(server.requests,'get',side_effect=[queue,history]),patch.object(server.requests,'post') as post:
            server.poll_once();post.assert_not_called()
        self.assertEqual(server.job('lost')['status'],'cancelling')
        self.assertIsNone(server.job('lost')['prompt_id'])

    def test_old_remote_never_receives_global_interrupt(self):
        self.save_fixture(dict(id='own',token='own-token',status='running',prompt_id='own-remote'))
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
            self.own_asset_fixture(a)
        j=dict(id='restore',token='restore-token',asset_ids=ids,prompt='图片1中的人物，参考视频1的动作',negative='闪烁',settings={'seed':123},graph={})
        self.save_fixture(j)
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
        self.save_fixture(original)
        response=Mock(status_code=200);response.json.return_value={'prompt_id':'new-remote'}
        with patch.object(server,'asset',return_value=aa[0]),patch.object(server,'ensure_remote',side_effect=lambda a:a),patch.object(server,'vhs_audio_asset',side_effect=lambda a:a),patch.object(server,'public_asset',side_effect=lambda a:a),patch.object(server.requests,'post',return_value=response) as post:
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
            with patch.object(server.secrets,'randbelow')as random:
                retry=self.client.post('/api/jobs/original/rerun',json={'token':'same-legacy-seeds','randomize_seed':False})
                self.assertEqual(retry.status_code,200,retry.text);random.assert_not_called()
            retried=server.job(retry.json()['id']);expected=copy.deepcopy(graph)
            expected['443']['inputs']['filename_prefix']='yingxu/'+retried['id']
            self.assertEqual(retried['graph'],expected);self.assertEqual(retried['settings'],settings)

    def test_qwen_edit_rerun_changes_seed_and_keeps_both_reference_slots(self):
        assets=[dict(id='first',kind='image',remote='first.png'),dict(id='second',kind='image',remote='second.png')]
        settings=settings_for(manifest('local-card-2'),{'seed':123,'aspect_ratio':'4:3 (Standard)','megapixels':1.2})
        graph=build_graph('local-card-2','prompt','negative',settings,assets,'original-edit')
        original=dict(id='original-edit',token='original-edit-token',status='done',workflow_id='local-card-2',prompt='prompt',negative='negative',settings=settings,asset_ids=['first','second'],graph=graph)
        self.save_fixture(original)
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
