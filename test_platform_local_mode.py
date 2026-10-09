"""Explicit loopback mode on isolated storage, without live compute or payment."""
import os
import sqlite3
from unittest import TestCase, main
from unittest.mock import patch

import test_platform_http as fixture
import platform_api
from fastapi.testclient import TestClient


class LocalPlatformHTTP(TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PlatformHTTP.setUpClass.__func__(cls)

    start_patch = fixture.PlatformHTTP.start_patch
    actor = fixture.PlatformHTTP.actor
    fund = fixture.PlatformHTTP.fund
    count = fixture.PlatformHTTP.count
    submit = fixture.PlatformHTTP.submit
    job_fixture = fixture.PlatformHTTP.job_fixture

    def setUp(self):
        fixture.PlatformHTTP.setUp(self)
        self.start_patch(patch.dict(os.environ, {'YINGXU_LOCAL_MODE':'1',
            'RAILWAY_ENVIRONMENT_ID':'', 'RAILWAY_PUBLIC_DOMAIN':''}))
        self.local = self.local_client()

    def local_client(self, base=fixture.ORIGIN, peer='127.0.0.1'):
        client = TestClient(self.backend.app, base_url=base,
                            client=(peer,50000), raise_server_exceptions=False)
        self.addCleanup(client.close)
        return client

    def local_identity(self, client=None):
        client = client or self.local
        response = client.get('/api/account/me')
        self.assertEqual(200,response.status_code,response.text)
        profile = response.json()
        client.headers.update({'Origin':str(client.base_url).rstrip('/'),
            'X-CSRF-Token':profile['csrf_token'], 'X-Platform-Account':profile['user']['id']})
        return profile

    def test_me_auto_binds_existing_owner_and_returns_only_user_information(self):
        before = self.count('platform_accounts')
        self.local.cookies.update(self.client.cookies)
        response = self.local.get('/api/account/me')
        self.assertEqual(200,response.status_code,response.text)
        result = response.json()
        self.assertTrue(result['local_mode'])
        self.assertEqual(self.admin['id'],result['user']['id'])
        self.assertEqual(self.admin['username'],result['user']['username'])
        for field in ('balance','held','available','password_hash','csrf_token','_local_mode'):
            self.assertNotIn(field,result['user'])
        self.assertIn('httponly',response.headers['set-cookie'].lower())
        self.assertIn('samesite=lax',response.headers['set-cookie'].lower())
        self.assertEqual(before,self.count('platform_accounts'))
        self.assertNotIn('set-cookie',self.local.get('/api/account/me').headers)

    def test_both_peer_and_hostname_must_be_local_and_cloud_never_enables_mode(self):
        for base,peer in [(fixture.ORIGIN,'192.0.2.10'),('http://evil.example','127.0.0.1')]:
            with self.subTest(base=base,peer=peer):
                denied = self.local_client(base,peer).get('/api/account/me',headers={
                    'X-Forwarded-For':'127.0.0.1','X-Forwarded-Host':'localhost'})
                self.assertEqual(401,denied.status_code,denied.text)
                self.assertNotIn('set-cookie',denied.headers)
        for setting in ('','true','0'):
            with patch.dict(os.environ,{'YINGXU_LOCAL_MODE':setting}):
                self.assertEqual(401,self.local_client().get('/api/account/me').status_code)
        for key in ('RAILWAY_ENVIRONMENT_ID','RAILWAY_PUBLIC_DOMAIN'):
            with patch.dict(os.environ,{key:'deployed-instance'}):
                self.assertEqual(401,self.local_client().get('/api/account/me').status_code)
        self.assertEqual(200,self.local_client('http://localhost:8770').get('/api/account/me').status_code)

    def test_same_origin_csrf_and_account_binding_are_still_enforced(self):
        self.local_identity()
        for headers in ({'X-CSRF-Token':''},{'Origin':'https://evil.example'},
                        {'Origin':''},{'X-Platform-Account':self.alice['id']}):
            with patch.object(self.backend.requests,'post') as remote:
                response = self.local.post('/api/jobs',json={'workflow_id':self.workflow,
                    'token':'local-denied-001','prompt':'synthetic scene'},headers=headers)
            self.assertIn(response.status_code,(403,409),response.text)
            remote.assert_not_called()
        self.assertEqual(0,self.count('jobs'))
        self.assertEqual(0,self.count('platform_ledger'))

    def test_login_financial_and_account_write_features_are_not_exposed_locally(self):
        self.local_identity()
        before = {table:self.count(table) for table in (
            'platform_accounts','platform_orders','platform_ledger','platform_admin_audit')}
        for path in ('/api/account/login','/api/account/register','/api/account/logout',
                     '/api/account/password','/api/account/creation-quote','/api/account/orders',
                     '/api/admin/users','/api/admin/users/'+self.alice['id'],
                     '/api/admin/users/'+self.alice['id']+'/credits',
                     '/api/admin/pricing','/api/admin/packages',
                     '/api/payments/webhooks/wechat'):
            with self.subTest(path=path):
                response = self.local.post(path,json={})
                self.assertEqual(404,response.status_code,response.text)
                self.assertEqual('local_feature_disabled',response.json()['code'])
        for path in ('/api/account/pricing-policy','/api/account/quote/'+self.workflow,
                     '/api/account/orders','/api/admin/users/'+self.alice['id']+'/ledger'):
            self.assertEqual(404,self.local.get(path).status_code)
        self.assertEqual(before,{table:self.count(table) for table in before})
        users = self.local.get('/api/admin/users')
        self.assertEqual(200,users.status_code,users.text)
        for user in users.json()['users']:
            self.assertTrue({'balance','held','available'}.isdisjoint(user))
        dashboard = self.local.get('/api/account/dashboard').json()
        self.assertEqual({'user','local_mode'},set(dashboard))

    def test_new_job_persists_same_owner_with_no_quote_no_credit_reservation_and_replays_once(self):
        self.local_identity()
        self.job_fixture(self.admin,'owner-historical-job')
        self.job_fixture(self.alice,'other-account-historical-job')
        self.workflow = 'unconfigured-local-workflow'
        before = self.store.account(self.admin['id'])
        first,remote = self.submit(self.local,expected=None,token='local-generation-001')
        self.assertEqual(200,first.status_code,first.text)
        self.assertEqual(1,remote.call_count)
        identifier = first.json()['id']
        record = self.backend.job(identifier)
        self.assertEqual(self.admin['id'],record['owner_id'])
        self.assertTrue(record['local_mode'])
        self.assertNotIn('credit_cost',record)
        self.assertTrue(self.store.owns_resource(self.admin['id'],'job',identifier))
        second,retry = self.submit(self.local,expected='stale-price',token='local-generation-001')
        self.assertEqual(200,second.status_code,second.text)
        self.assertEqual(identifier,second.json()['id']); retry.assert_not_called()
        different,retry = self.submit(self.local,expected=None,token='local-generation-001',prompt='different')
        self.assertEqual(409,different.status_code,different.text); retry.assert_not_called()
        self.backend.update(identifier,status='done',ended=1)
        account = self.store.account(self.admin['id'])
        self.assertEqual((before['balance'],before['held']),(account['balance'],account['held']))
        self.assertEqual(0,self.count('platform_reservations'))
        self.assertEqual(0,self.count('platform_ledger'))
        visible = {job['id'] for job in self.local.get('/api/jobs').json()}
        self.assertEqual({'owner-historical-job',identifier},visible)
        self.assertEqual(404,self.local.get('/api/jobs/other-account-historical-job').status_code)

    def test_job_and_ownership_are_still_atomic_without_billing(self):
        self.local_identity()
        grant = self.store.grant_resource
        def fail(owner,kind,identifier,connection=None):
            if kind == 'job':
                raise sqlite3.IntegrityError('synthetic ownership failure')
            return grant(owner,kind,identifier,connection=connection)
        with patch.object(self.store,'grant_resource',side_effect=fail):
            response,remote = self.submit(self.local,expected=None)
        self.assertEqual(500,response.status_code,response.text)
        remote.assert_not_called()
        self.assertEqual(0,self.count('jobs'))
        self.assertEqual(0,self.count('platform_ledger'))
        self.assertEqual(0,self.count('platform_reservations'))

    def test_enabled_flag_does_not_change_non_loopback_account_billing_or_settlement(self):
        self.fund(self.alice)
        response,remote = self.submit(self.client,expected='10')
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual(1,remote.call_count)
        identifier = response.json()['id']
        record = self.backend.job(identifier)
        self.assertNotIn('local_mode',record)
        self.assertEqual(10,record['credit_cost'])
        self.backend.update(identifier,status='done',ended=1)
        self.assertEqual('settled',self.store.reservation(identifier)['status'])
        account = self.store.account(self.alice['id'])
        self.assertEqual((90,0),(account['balance'],account['held']))
        self.assertEqual(1,len([entry for entry in self.store.ledger(self.alice['id'])
                               if entry['event']=='settle']))

    def test_free_creation_availability_does_not_claim_unimplemented_models_are_live(self):
        self.local_identity()
        response = self.local.post('/api/account/creation-availability',json={
            'model':'Seedream 4.5','kind':'image','quality':'1K','count':1,'duration':None})
        self.assertEqual(200,response.status_code,response.text)
        self.assertFalse(response.json()['available'])
        self.assertTrue(response.json()['availability_reason'])
        self.assertTrue({'credits','amount_minor','credit_policy','configured'}.isdisjoint(response.json()))
        self.network_get.assert_not_called(); self.network_post.assert_not_called()


if __name__ == '__main__':
    main()
