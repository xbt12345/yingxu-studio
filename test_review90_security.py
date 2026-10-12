"""Offline authorization and bounded webhook ingress regressions."""
import asyncio
import copy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import test_platform_http as fixture
import test_payment_gateway as gateway_fixture
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from payment_gateway import PaymentError


class Review90Security(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PlatformHTTP.setUpClass.__func__(cls)
        gateway_fixture.PaymentGatewayContracts.setUpClass()

    start_patch = fixture.PlatformHTTP.start_patch
    actor = fixture.PlatformHTTP.actor
    fund = fixture.PlatformHTTP.fund
    count = fixture.PlatformHTTP.count

    def setUp(self):
        fixture.PlatformHTTP.setUp(self)
        self.start_patch(patch.dict(os.environ, {'YINGXU_LOCAL_MODE':'0',
            'RAILWAY_ENVIRONMENT_ID':'', 'RAILWAY_PUBLIC_DOMAIN':''}))
        self.start_patch(patch.object(self.backend.schema_adapters, 'template_path',
            side_effect=lambda spec: fixture.ROOT/'workflows/api'/spec['template']))
        self.reply = SimpleNamespace(status_code=200, json=lambda:{'prompt_id':'offline-directory-task'})
        for workflow in ('local-card-135','local-card-136'):
            self.store.configure_pricing(self.admin['id'], workflow, 1)

    def body(self, workflow, token):
        spec = self.backend.schema_adapters.manifest(workflow)
        field = '12:directory' if workflow == 'local-card-135' else '70:value'
        return {'workflow_id':workflow, 'source_hash':spec['source_hash'],
                'token':token, 'catalog_values':{field:'/untrusted/shared/media'}}

    def totals(self):
        return {table:self.count(table) for table in ('jobs','platform_reservations','platform_ledger')}

    def test_ordinary_user_cannot_dispatch_or_pay_for_real_directory_workflows(self):
        self.fund(self.alice)
        before, account = self.totals(), self.store.account(self.alice['id'])
        for workflow in ('local-card-135','local-card-136'):
            with self.subTest(workflow=workflow), patch.object(self.backend.requests,'post',return_value=self.reply) as remote:
                response = self.client.post('/api/jobs',json=self.body(workflow,workflow+'-denied'),
                                            headers={'X-Expected-Credits':'1'})
                self.assertEqual(403,response.status_code,response.text)
                remote.assert_not_called()
                self.assertEqual(before,self.totals())
                self.assertEqual(account,self.store.account(self.alice['id']))

    def test_admin_can_dispatch_real_directory_workflows(self):
        self.fund(self.admin)
        for workflow in ('local-card-135','local-card-136'):
            with self.subTest(workflow=workflow), patch.object(self.backend.requests,'post',return_value=self.reply) as remote:
                response = self.admin_client.post('/api/jobs',json=self.body(workflow,workflow+'-admin'),
                                                  headers={'X-Expected-Credits':'1'})
                self.assertEqual(200,response.status_code,response.text)
                self.assertEqual(1,remote.call_count)
                self.assertEqual(self.admin['id'],self.backend.job(response.json()['id'])['owner_id'])

    def test_local_owner_keeps_directory_workflows_without_billing(self):
        with patch.dict(os.environ, {'YINGXU_LOCAL_MODE':'1'}):
            client = TestClient(self.backend.app,base_url=fixture.ORIGIN,client=('127.0.0.1',50000))
            self.addCleanup(client.close)
            identity = client.get('/api/account/me').json()
            client.headers.update({'Origin':fixture.ORIGIN,'X-CSRF-Token':identity['csrf_token'],
                                   'X-Platform-Account':identity['user']['id']})
            before = self.count('platform_ledger')
            for workflow in ('local-card-135','local-card-136'):
                with self.subTest(workflow=workflow), patch.object(self.backend.requests,'post',return_value=self.reply) as remote:
                    response = client.post('/api/jobs',json=self.body(workflow,workflow+'-local'))
                    self.assertEqual(200,response.status_code,response.text)
                    self.assertEqual(1,remote.call_count)
                    self.assertTrue(self.backend.job(response.json()['id'])['local_mode'])
            self.assertEqual(before,self.count('platform_ledger'))

    def test_new_workflow_identity_is_restricted_by_server_capability(self):
        spec = copy.deepcopy(self.backend.schema_adapters.manifest('local-card-135'))
        spec['id'] = 'new-directory-workflow'
        body = {'workflow_id':spec['id'],'source_hash':spec['source_hash'],
                'token':'future-directory-workflow','catalog_values':{'12:directory':'/shared'}}
        with patch.object(self.backend.schema_adapters,'manifest',return_value=spec), \
                patch.object(self.backend,'prepare_schema_submission') as prepare, \
                patch.object(self.backend,'dispatch') as dispatch:
            response = self.client.post('/api/jobs',json=body)
        self.assertEqual(403,response.status_code,response.text)
        prepare.assert_not_called(); dispatch.assert_not_called()

    def saved_directory_job(self, identifier, workflow, *, strip_kind=False):
        spec = copy.deepcopy(self.backend.schema_adapters.manifest(workflow))
        values = self.backend.schema_adapters.validate_values(spec,{})
        if strip_kind:
            for field in spec['controls']:field.pop('kind',None)
        graph = json.loads((fixture.ROOT/'workflows/api'/spec['template']).read_text('utf-8'))
        record = {'id':identifier,'token':'original-'+identifier,'workflow_id':workflow,
            'schema_spec':spec,'catalog_values':values,'catalog_texts':{},'catalog_assets':{},
            'prompt':'','negative':'','settings':{},'asset_ids':[],'status':'done','stage':'done',
            'started':0,'ended':1,'outputs':[],'graph':graph,'prompt_id':'offline-original',
            'error':None,'owner_id':self.alice['id']}
        with self.backend.database() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?)',(identifier,record['token'],json.dumps(record)))
        self.store.grant_resource(self.alice['id'],'job',identifier)
        return record

    def test_rerun_checks_current_registry_when_saved_contract_has_no_kind(self):
        self.fund(self.alice)
        for workflow in ('local-card-135','local-card-136'):
            identifier = workflow+'-old-snapshot'
            self.saved_directory_job(identifier,workflow,strip_kind=True)
            before = self.totals()
            with self.subTest(workflow=workflow), patch.object(self.backend.requests,'post',return_value=self.reply) as remote:
                response = self.client.post('/api/jobs/'+identifier+'/rerun',json={'token':identifier+'-rerun'},
                                            headers={'X-Expected-Credits':'1'})
                self.assertEqual(403,response.status_code,response.text)
                remote.assert_not_called(); self.assertEqual(before,self.totals())

    def test_rerun_checks_saved_capability_when_current_registry_changes(self):
        self.fund(self.alice)
        self.saved_directory_job('saved-filesystem-contract','local-card-135')
        before = self.totals()
        with patch.object(self.backend.schema_adapters,'manifest',return_value=None), \
                patch.object(self.backend.requests,'post',return_value=self.reply) as remote:
            response = self.client.post('/api/jobs/saved-filesystem-contract/rerun',
                json={'token':'saved-contract-rerun'},headers={'X-Expected-Credits':'1'})
        self.assertEqual(403,response.status_code,response.text)
        remote.assert_not_called(); self.assertEqual(before,self.totals())

    def test_rerun_checks_legacy_loader_graph_without_classification(self):
        self.fund(self.alice)
        self.saved_directory_job('old-unclassified-directory','local-card-136',strip_kind=True)
        before = self.totals()
        with patch.object(self.backend.schema_adapters,'manifest',return_value=None), \
                patch.object(self.backend.requests,'post',return_value=self.reply) as remote:
            response = self.client.post('/api/jobs/old-unclassified-directory/rerun',
                json={'token':'legacy-directory-rerun'},headers={'X-Expected-Credits':'1'})
        self.assertEqual(403,response.status_code,response.text)
        remote.assert_not_called(); self.assertEqual(before,self.totals())

    def call_webhook(self, provider, chunks, headers=()):
        endpoint = next(route.endpoint for route in self.backend.app.routes
                        if getattr(route,'path',None)=='/api/payments/webhooks/'+provider)
        state = {'consumed':0}
        async def receive():
            index = state['consumed']; state['consumed'] += 1
            if index >= len(chunks):raise AssertionError('Body read beyond supplied stream')
            return {'type':'http.request','body':chunks[index],'more_body':index<len(chunks)-1}
        request = Request({'type':'http','method':'POST','path':'/api/payments/webhooks/'+provider,
                           'headers':list(headers)},receive)
        try:response = asyncio.run(endpoint(request)); status = response.status_code
        except HTTPException as error:status = error.status_code
        return status,state['consumed']

    def test_oversized_anonymous_stream_stops_at_limit_without_length_or_with_lying_length(self):
        for provider in ('alipay','wechat'):
            for headers in ((),((b'transfer-encoding',b'chunked'),),((b'content-length',b'1'),)):
                with self.subTest(provider=provider,headers=headers), \
                        patch.object(self.bridge.gateway,'verify_'+provider) as verify:
                    status,consumed = self.call_webhook(provider,[b'a'*65536,b'b',b'must-not-be-read'],headers)
                    self.assertEqual(413,status)
                    self.assertEqual(2,consumed)
                    verify.assert_not_called()

    def test_large_declared_length_is_rejected_before_receiving(self):
        for provider in ('alipay','wechat'):
            with self.subTest(provider=provider):
                self.assertEqual((413,0),self.call_webhook(provider,[b'never-read'],((b'content-length',b'65537'),)))

    def test_exact_limit_preserves_wechat_signed_bytes(self):
        raw = b'{"value":"'+b'x'*(65536-12)+b'"}'
        self.assertEqual(65536,len(raw))
        with patch.object(self.bridge.gateway,'verify_wechat',side_effect=PaymentError('invalid_signature','test')) as verify:
            status,consumed = self.call_webhook('wechat',[raw[:20000],raw[20000:]],((b'content-type',b'application/json'),))
        self.assertEqual((400,2),(status,consumed))
        self.assertEqual(raw,verify.call_args.args[1])

    def test_alipay_stream_retains_duplicate_fields_utf8_and_form_decoding(self):
        raw = 'subject=%E6%B5%8B%E8%AF%95+%2B&trade_no=first&trade_no=second&padding='.encode()
        raw += b'x'*(65536-len(raw))
        with patch.object(self.bridge.gateway,'verify_alipay',side_effect=PaymentError('invalid_signature','test')) as verify:
            status,consumed = self.call_webhook('alipay',[raw[:31],raw[31:]],
                ((b'content-type',b'application/x-www-form-urlencoded'),))
        self.assertEqual((400,2),(status,consumed))
        form = verify.call_args.args[0]
        self.assertEqual('测试 +',form['subject'])
        self.assertEqual(['first','second'],form.getlist('trade_no'))

    def test_normal_anonymous_invalid_signatures_stay_rejected_without_credit(self):
        case = gateway_fixture.PaymentGatewayContracts(); case.setUp()
        with patch.object(self.bridge,'gateway',case.gateway):
            form = case.alipay(); form['total_amount']='0.01'
            response = self.anon.post('/api/payments/webhooks/alipay',content=urlencode(form),
                                      headers={'Content-Type':'application/x-www-form-urlencoded'})
            self.assertEqual(400,response.status_code,response.text)
            headers,raw = case.wechat()
            response = self.anon.post('/api/payments/webhooks/wechat',content=raw+b' ',headers=headers)
            self.assertEqual(400,response.status_code,response.text)
        self.assertEqual(0,self.count('platform_ledger'))
        case.http.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
