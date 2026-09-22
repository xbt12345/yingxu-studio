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
from adapters import manifest, settings_for, build_graph
from PIL import Image

class MVPContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patches=[patch.object(server,'DB',Path(self.tmp.name)/'test.sqlite3'),patch.object(server,'PRIVATE',Path(self.tmp.name))]
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
            self.assertEqual(self.client.post('/api/jobs/own/cancel').status_code,502)
        self.assertEqual(server.job('own')['status'],'running')

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
