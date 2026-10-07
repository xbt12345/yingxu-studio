"""Submission state survives diagnostic failures without a live DB or GPU."""
import ast
import errno
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import requests


class Receipt:
    def __init__(self,events,fail=False):
        self.events=events
        self.fail=fail
        self.body=None
    def __truediv__(self,value):return self
    def write_text(self,text,*args):
        self.events.append('receipt')
        self.body=json.loads(text)
        if self.fail:raise OSError(errno.ENOSPC,'synthetic key=must-not-be-logged')


class DispatchReceipts(unittest.TestCase):
    def dispatch(self,response=None,error=None,receipt_failure=False):
        events=[]
        sink=Receipt(events,receipt_failure)
        record={'id':'synthetic-job','graph':{'7':{'inputs':{'api_key':'synthetic-secret'}}},'status':'submitting'}
        def update(id,**values):
            self.assertEqual(id,record['id'])
            events.append('state')
            record.update(values)
            return dict(record)
        post=Mock(return_value=response,side_effect=error)
        scope={'requests':SimpleNamespace(post=post,RequestException=requests.RequestException),'BASE':'https://synthetic.invalid',
               'CLIENT':'synthetic','PRIVATE':sink,'json':json,'time':SimpleNamespace(time=lambda:1),
               'update':update,'public':lambda value:value,'friendly':lambda value:'工作流执行失败：'+value}
        tree=ast.parse((Path(__file__).with_name('server.py')).read_text('utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'exact-dispatch','exec'),scope)
        result=scope['dispatch'](record)
        self.assertEqual(post.call_count,1)
        return result,events,sink

    def test_validation_state_precedes_receipt_and_payload_is_not_retained(self):
        response=SimpleNamespace(status_code=400,json=lambda:{'node_errors':{'7':{'input':'synthetic-secret'},'rogue-key':{}},'prompt':'private prompt'})
        result,events,sink=self.dispatch(response=response)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(events,['state','receipt'])
        self.assertEqual(sink.body,{'http_status':400,'node_ids':['7']})
        self.assertNotIn('synthetic-secret',result['error'])

    def test_disk_full_does_not_leave_validation_in_submitting(self):
        response=SimpleNamespace(status_code=400,json=lambda:{'error':'synthetic-secret'})
        with self.assertLogs('yingxu.dispatch',level='WARNING') as captured:
            result,events,sink=self.dispatch(response=response,receipt_failure=True)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(events,['state','receipt'])
        self.assertNotIn('must-not-be-logged',' '.join(captured.output))
        self.assertNotIn('synthetic-secret',' '.join(captured.output))

    def test_transport_failure_preserves_unknown_when_receipt_fails(self):
        with self.assertLogs('yingxu.dispatch',level='WARNING') as captured:
            result,events,sink=self.dispatch(error=requests.Timeout('private payload synthetic-secret'),receipt_failure=True)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(events,['state','receipt'])
        self.assertEqual(sink.body,{'type':'Timeout'})
        self.assertNotIn('synthetic-secret',' '.join(captured.output))

    def test_bad_validation_json_is_a_durable_failure(self):
        response=SimpleNamespace(status_code=400,json=lambda:['untrusted body'])
        result,events,sink=self.dispatch(response=response)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(events,['state','receipt'])

    def test_accepted_submission_does_not_depend_on_receipt_storage(self):
        response=SimpleNamespace(status_code=200,json=lambda:{'prompt_id':'remote-job'})
        result,events,sink=self.dispatch(response=response,receipt_failure=True)
        self.assertEqual(result['status'],'queued')
        self.assertEqual(result['prompt_id'],'remote-job')
        self.assertEqual(events,['state'])


if __name__=='__main__':unittest.main()
