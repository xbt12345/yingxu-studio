"""Exercise actual output/retrieval functions without importing the live server."""
import ast
import copy
import errno
import io
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import av
from fastapi import HTTPException
from PIL import Image
import requests


ROOT=Path(__file__).resolve().parent


class Reply:
    def __init__(self,body=None,chunks=()):
        self.body=body
        self.chunks=chunks
    def raise_for_status(self):pass
    def json(self):return copy.deepcopy(self.body)
    def iter_content(self,size):yield from self.chunks
    def __enter__(self):return self
    def __exit__(self,*args):return False


class OutputRecovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private=Path(self.temp.name)
        (self.private/'outputs').mkdir()
        (self.private/'receipts').mkdir()
        self.record=dict(id='synthetic-output-job',token='synthetic-token',workflow_id='synthetic-workflow',
                         status='queued',prompt_id='same-remote-id',started=0,ended=None,outputs=[],
                         settings={'seed':123},graph={'synthetic':{'inputs':{'seed':123}}},
                         schema_spec={'id':'synthetic-workflow','output':'image','outputs':['first','second']})
        self.original_identity=copy.deepcopy({key:self.record[key] for key in ('id','token','prompt_id','settings','graph')})
        self.history={'status':{'completed':True,'status_str':'success'},'outputs':{}}
        self.get=Mock(side_effect=self.remote_get)
        self.post=Mock(side_effect=AssertionError('Retrieval must never submit, rerun or upload'))
        tree=ast.parse((ROOT/'server.py').read_text('utf-8'))
        names={'output_items','output_collection','output_failure','finish_output_collection','collect',
               '_collect_outputs','poll_once','retrieve','rerun'}
        nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in nodes},names)
        kinds=next(node for node in tree.body if isinstance(node,ast.Assign)
                   and any(isinstance(target,ast.Name) and target.id=='MEDIA_KINDS' for target in node.targets))
        self.scope=dict(Path=Path,json=json,time=time,errno=errno,Image=Image,av=av,contextmanager=contextmanager,
                        lock=threading.RLock(),collecting=set(),PRIVATE=self.private,BASE='https://synthetic.invalid',
                        requests=SimpleNamespace(get=self.get,post=self.post,RequestException=requests.RequestException),
                        HTTPException=HTTPException,Rerun=object,app=SimpleNamespace(post=lambda route:lambda fn:fn),
                        jobs=lambda:[copy.deepcopy(self.record)],job=lambda id:copy.deepcopy(self.record),
                        update=self.update,public=copy.deepcopy,manifest=lambda id:None,
                        schema_adapters=SimpleNamespace(manifest=lambda id:None),
                        present_outputs=lambda job,items,outputs:copy.deepcopy(outputs),
                        reviewed_compiler_failure=lambda *args:None,reviewed_translation_failure=lambda *args:None,
                        public_graph=copy.deepcopy,embed_workflow=Mock(),friendly=lambda text:text,
                        attempt_cancel=Mock(side_effect=AssertionError('No cancellation during retrieval')))
        exec(compile(ast.Module(body=[kinds,*nodes],type_ignores=[]),'exact-server-output-contracts','exec'),self.scope)

    def update(self,id,**values):
        self.assertEqual(id,self.record['id'])
        self.record.update(copy.deepcopy(values))
        return copy.deepcopy(self.record)

    def remote_get(self,url,**kwargs):
        if url.endswith('/queue'):return Reply({'queue_running':[],'queue_pending':[]})
        if url.endswith('/history/'+self.record['prompt_id']):return Reply({self.record['prompt_id']:self.history})
        if url.endswith('/view'):return Reply(chunks=[self.files[kwargs['params']['filename']]])
        raise AssertionError('Unexpected remote URL: '+url)

    def image_history(self,second=b'corrupt-image'):
        output=io.BytesIO()
        Image.new('RGB',(2,2),(30,60,90)).save(output,format='PNG')
        self.files={'first.png':output.getvalue(),'second.png':second}
        self.history['outputs']={name:{'images':[{'filename':name+'.png','type':'output'}]}
                                 for name in ('first','second')}

    def assert_identity(self):
        self.assertEqual({key:self.record[key] for key in self.original_identity},self.original_identity)
        self.post.assert_not_called()
        self.assertEqual(self.scope['collecting'],set())

    def test_oversized_text_stops_polling_without_network_retry(self):
        self.record['schema_spec']['output']='text'
        self.history['outputs']={'first':{'text':['x'*(1024*1024+1)]}}
        self.scope['poll_once']()
        self.assertEqual(self.record['status'],'failed')
        self.assertEqual(self.record['failure_phase'],'output')
        self.assertEqual(self.record['output_failure_code'],'output_too_large')
        self.assertIsNone(self.record['connection_error'])
        self.get.reset_mock()
        self.scope['poll_once']()
        self.get.assert_not_called()
        self.assert_identity()

    def test_stream_size_limit_is_terminal_before_writing_oversized_chunk(self):
        class OversizedChunk:
            def __len__(self):return 100*1024*1024+1
        self.image_history()
        self.files['first.png']=OversizedChunk()
        self.scope['poll_once']()
        self.assertEqual(self.record['output_failure_code'],'output_too_large')
        self.assertEqual(self.record['status'],'failed')
        self.assert_identity()

    def test_corrupt_second_output_retains_first_and_retrieve_reuses_its_file(self):
        self.image_history()
        self.scope['poll_once']()
        self.assertEqual(self.record['output_failure_code'],'invalid_output')
        self.assertEqual(len(self.record['outputs']),1)
        first=self.private/'outputs'/self.record['id']/'0.png'
        before=first.read_bytes()
        self.files['second.png']=self.files['first.png']
        self.get.reset_mock()
        result=self.scope['retrieve'](self.record['id'])
        self.assertEqual(result['id'],self.original_identity['id'])
        self.assertEqual(result['status'],'done')
        self.assertIsNone(result['failure_phase'])
        self.assertIsNone(result['output_failure_code'])
        self.assertIsNone(result['connection_error'])
        self.assertEqual(len(result['outputs']),2)
        self.assertEqual(first.read_bytes(),before)
        views=[call for call in self.get.call_args_list if call.args[0].endswith('/view')]
        self.assertEqual([call.kwargs['params']['filename'] for call in views],['second.png'])
        self.assert_identity()

    def test_local_storage_errors_have_accurate_terminal_reason(self):
        for number,expected in ((errno.ENOSPC,'storage_full'),(errno.EACCES,'storage_unwritable'),(errno.EIO,'storage_error')):
            with self.subTest(errno=number):
                self.record.update(status='queued',outputs=[])
                self.history['outputs']={'first':{'text':['synthetic result']}}
                self.record['schema_spec']['output']='text'
                with patch.object(Path,'write_bytes',side_effect=OSError(number,'synthetic local failure')):
                    self.scope['poll_once']()
                self.assertEqual(self.record['status'],'failed')
                self.assertEqual(self.record['output_failure_code'],expected)
                self.assertIsNone(self.record['connection_error'])
                self.assertNotIn('synthetic local failure',self.record['error'])
                self.assert_identity()

    def test_receipt_write_failure_retains_ready_file_and_public_output(self):
        self.record['schema_spec']['output']='text'
        self.history['outputs']={'first':{'text':['synthetic result']}}
        with patch.object(Path,'write_text',side_effect=OSError(errno.ENOSPC,'synthetic full disk')):
            self.scope['poll_once']()
        self.assertEqual(self.record['output_failure_code'],'storage_full')
        self.assertEqual(len(self.record['outputs']),1)
        output=self.private/'outputs'/self.record['id']/'0.txt'
        self.assertEqual(output.read_text('utf-8'),'synthetic result')
        self.assert_identity()

    def test_invalid_mp4_and_ffmpeg_processing_failure_are_not_storage_or_network_errors(self):
        self.history['outputs']={'first':{'videos':[{'filename':'first.mp4','type':'output'}]}}
        self.files={'first.mp4':b'invalid mp4'}
        self.scope['poll_once']()
        self.assertEqual(self.record['output_failure_code'],'invalid_output')
        self.assert_identity()
        self.record.update(status='queued')
        self.files['first.mp4']=b'\x00\x00\x00\x18ftyp'+b'synthetic media'
        self.scope['embed_workflow'].side_effect=av.error.InvalidDataError(errno.EINVAL,'synthetic bad container')
        self.scope['poll_once']()
        self.assertEqual(self.record['output_failure_code'],'invalid_output')
        self.assertIsNone(self.record['connection_error'])
        self.assertTrue((self.private/'outputs'/self.record['id']/'0.mp4').is_file())
        self.assert_identity()

    def test_generation_failure_clears_output_failure_phase(self):
        self.record.update(failure_phase='output',output_failure_code='storage_full',connection_error='stale')
        self.scope['reviewed_compiler_failure']=lambda *args:'synthetic compilation failure'
        self.scope['poll_once']()
        self.assertEqual(self.record['status'],'failed')
        self.assertEqual(self.record['error'],'synthetic compilation failure')
        self.assertIsNone(self.record['failure_phase'])
        self.assertIsNone(self.record['output_failure_code'])
        self.assertIsNone(self.record['connection_error'])
        self.assert_identity()

    def test_output_failure_cannot_accidentally_enter_paid_rerun_route(self):
        self.record.update(status='failed',failure_phase='output')
        with self.assertRaises(HTTPException) as failure:self.scope['rerun'](self.record['id'],object())
        self.assertEqual(failure.exception.status_code,409)
        self.assertIn('重新取回',failure.exception.detail)
        self.get.assert_not_called()
        self.assert_identity()

    def test_network_timeout_preserves_automatic_query_recovery(self):
        self.image_history(second=b'will-be-replaced')
        original_get=self.remote_get
        def disconnected_view(url,**kwargs):
            if url.endswith('/view'):raise requests.Timeout('synthetic timeout')
            return original_get(url,**kwargs)
        self.get.side_effect=disconnected_view
        self.scope['poll_once']()
        self.assertEqual(self.record['status'],'downloading')
        self.assertIn('自动重试',self.record['connection_error'])
        self.assertIsNone(self.record['failure_phase'])
        self.get.side_effect=original_get
        self.files['second.png']=self.files['first.png']
        self.scope['poll_once']()
        self.assertEqual(self.record['status'],'done')
        self.assertIsNone(self.record['connection_error'])
        self.assert_identity()

    def test_retrieve_history_timeout_returns_active_state_then_poll_recovers(self):
        self.record.update(status='failed',failure_phase='output')
        self.record['schema_spec']['output']='text'
        self.history['outputs']={'first':{'text':['retained original result']}}
        self.get.side_effect=requests.Timeout('synthetic history timeout')
        result=self.scope['retrieve'](self.record['id'])
        self.assertEqual(result['status'],'downloading')
        self.assertIn('不会重新生成',result['connection_error'])
        self.get.side_effect=self.remote_get
        self.scope['poll_once']()
        self.assertEqual(self.record['status'],'done')
        self.assertIsNone(self.record['failure_phase'])
        self.assert_identity()

    def test_retrieve_rejects_non_output_failure_and_missing_remote_identity(self):
        for changes in ({'status':'done','failure_phase':None},
                        {'status':'failed','failure_phase':None},
                        {'status':'downloading','failure_phase':'output'},
                        {'status':'failed','failure_phase':'output','prompt_id':None}):
            with self.subTest(changes=changes):
                self.record.update(status='failed',failure_phase='output',prompt_id='same-remote-id')
                self.record.update(changes)
                self.get.reset_mock()
                with self.assertRaises(HTTPException) as failure:self.scope['retrieve'](self.record['id'])
                self.assertEqual(failure.exception.status_code,409)
                self.get.assert_not_called()
                self.assertEqual(self.scope['collecting'],set())
                self.post.assert_not_called()

    def test_remote_result_missing_is_explicit_terminal_without_resubmission(self):
        self.record.update(status='failed',failure_phase='output')
        self.get.side_effect=lambda *args,**kwargs:Reply({})
        result=self.scope['retrieve'](self.record['id'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['output_failure_code'],'remote_result_unavailable')
        self.assertIsNone(result['connection_error'])
        self.get.reset_mock()
        self.scope['poll_once']()
        self.get.assert_not_called()
        self.assert_identity()

    def test_concurrent_retrieve_and_monitor_do_not_collect_twice(self):
        self.record.update(status='failed',failure_phase='output')
        self.record['schema_spec']['output']='text'
        self.history['outputs']={'first':{'text':['same original result']}}
        entered,release=threading.Event(),threading.Event()
        original_get=self.remote_get
        def blocked_history(url,**kwargs):
            entered.set()
            if not release.wait(3):raise AssertionError('Synthetic retrieval did not release')
            return original_get(url,**kwargs)
        self.get.side_effect=blocked_history
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.scope['retrieve'](self.record['id'])))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(HTTPException) as failure:self.scope['retrieve'](self.record['id'])
            self.assertEqual(failure.exception.status_code,409)
            self.scope['collect'](copy.deepcopy(self.record),self.history)
            self.assertEqual(self.record['outputs'],[])
            self.assertEqual(self.get.call_count,1)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results),1)
        self.assertEqual(results[0]['status'],'done')
        self.assertEqual(len(self.record['outputs']),1)
        self.assert_identity()


if __name__=='__main__':unittest.main()
