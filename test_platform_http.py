"""Real studio HTTP boundary on isolated SQLite and synthetic compute replies.

Load a separate server module with a temporary DATA_DIR before any import side
effects. No original workspace DB, bootstrap credentials or compute service is
used. TestClient is deliberately not entered, so the live lifespan never runs.
"""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parent/'private/runtime'))
from fastapi.testclient import TestClient

import configuration
from payment_gateway import PaymentGateway
import platform_api
import platform_pricing
from platform_accounts import PlatformAccounts


ROOT=Path(__file__).resolve().parent
ORIGIN='http://127.0.0.1:8770'
PASSWORD='offline-password-12345'


class TestAccounts(PlatformAccounts):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('password_rounds',100_000)
        super().__init__(*args,**kwargs)


class PlatformHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boot=tempfile.TemporaryDirectory(prefix='yingxu-platform-http-boot-')
        cls.addClassCleanup(cls.boot.cleanup)
        name='yingxu_isolated_http_backend'
        spec=importlib.util.spec_from_file_location(name,ROOT/'server.py')
        cls.backend=importlib.util.module_from_spec(spec)
        sys.modules[name]=cls.backend
        cls.addClassCleanup(lambda:sys.modules.pop(name,None))
        read=Path.read_text
        def safe_read(path,*args,**kwargs):
            if path==ROOT/'private'/'backend.json':return '{}'
            return read(path,*args,**kwargs)
        with patch.object(configuration,'DATA_DIR',Path(cls.boot.name)), \
                patch.dict(os.environ,{'CHENYU_CARD_URL':''}), \
                patch.object(Path,'read_text',safe_read), \
                patch.object(platform_api,'PlatformAccounts',TestAccounts):
            spec.loader.exec_module(cls.backend)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='yingxu-platform-http-')
        self.addCleanup(self.temp.cleanup)
        self.private=Path(self.temp.name)
        for name in ('uploads','outputs','receipts'):(self.private/name).mkdir()
        self.start_patch(patch.object(self.backend,'PRIVATE',self.private))
        self.start_patch(patch.object(self.backend,'DB',self.private/'workspace.sqlite3'))
        self.start_patch(patch.object(self.backend,'BASE','https://synthetic-compute.invalid'))
        self.start_patch(patch.dict(os.environ,{'YINGXU_ALLOWED_ORIGINS':'https://testserver'}))
        self.start_patch(patch.object(platform_api,'PlatformAccounts',TestAccounts))
        self.network_get=self.start_patch(patch.object(self.backend.requests,'get',side_effect=AssertionError('No compute or payment network access')))
        self.network_post=self.start_patch(patch.object(self.backend.requests,'post',side_effect=AssertionError('No compute or payment network access')))
        with self.backend.database() as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, token TEXT UNIQUE, data TEXT NOT NULL)')
            db.execute('CREATE TABLE assets(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.bridge=self.backend.platform_bridge
        self.store=self.bridge.accounts()
        self.admin=self.store.bootstrap_admin()
        self.alice=self.store.register('alice-user',PASSWORD)
        self.bob=self.store.register('bob-user',PASSWORD)
        self.start_patch(patch.object(self.bridge,'gateway',PaymentGateway({},http=SimpleNamespace(post=Mock(side_effect=AssertionError('No payment network access'))))))
        self.client=self.actor(self.alice)
        self.admin_client=self.actor(self.admin)
        self.bob_client=self.actor(self.bob)
        self.anon=TestClient(self.backend.app,base_url=ORIGIN,raise_server_exceptions=False)
        self.addCleanup(self.anon.close)
        self.workflow='local-card-10'
        self.store.configure_package(self.admin['id'],'test-package','测试套餐',100,2900,True)
        self.store.configure_pricing(self.admin['id'],self.workflow,10)

    def start_patch(self,manager):
        result=manager.start()
        self.addCleanup(manager.stop)
        return result

    def actor(self,user,origin=ORIGIN):
        client=TestClient(self.backend.app,base_url=origin,raise_server_exceptions=False)
        self.addCleanup(client.close)
        session=self.store.create_session(user['id'])
        client.cookies.set(platform_api.COOKIE,session['token'])
        client.headers.update({'Origin':origin,'X-CSRF-Token':session['csrf_token'],'X-Platform-Account':user['id']})
        return client

    def fund(self,user,reference=None):
        order=self.store.create_order(user['id'],'test-package','fund-'+user['id'],'admin_contact')
        self.store.confirm_order(self.admin['id'],order['id'],reference or 'fund-'+user['id'])

    def job_fixture(self,owner,identifier):
        record={'id':identifier,'token':'token-'+identifier,'workflow_id':self.workflow,
            'prompt':'synthetic private prompt '+owner['id'],'negative':'','settings':{'seed':1},
            'asset_ids':[],'status':'done','stage':'已保存作品','started':0,'ended':1,
            'outputs':[{'id':identifier+'o0','type':'text','src':f'/api/media/{identifier}/0.txt'}],
            'graph':{},'prompt_id':'remote-'+identifier,'error':None,'owner_id':owner['id']}
        with self.backend.database() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?)',(identifier,record['token'],json.dumps(record)))
        self.store.grant_resource(owner['id'],'job',identifier)
        folder=self.private/'outputs'/identifier;folder.mkdir()
        (folder/'0.txt').write_text('synthetic private output','utf-8')
        return record

    def asset_fixture(self,owner):
        identifier='a'*64
        record={'id':identifier,'name':'synthetic-reference.webp','kind':'image','bytes':5}
        with self.backend.database() as db:db.execute('INSERT INTO assets VALUES(?,?)',(identifier,json.dumps(record)))
        self.store.grant_resource(owner['id'],'asset',identifier)
        (self.private/'uploads'/(identifier+'.webp')).write_bytes(b'test')
        return identifier

    def submit(self,client=None,token='offline-submit-0001',prompt='synthetic scene',extra=None,expected='10'):
        client=client or self.client
        body={'workflow_id':self.workflow,'token':token,'prompt':prompt,**(extra or {})}
        manifest={'id':self.workflow,'name':'Synthetic workflow','negative':True,
                  'minImages':0,'maxImages':0,'minVideos':0,'maxVideos':0}
        reply=SimpleNamespace(status_code=200,json=lambda:{'prompt_id':'synthetic-remote-id'})
        with patch.object(self.backend,'manifest',return_value=manifest), \
                patch.object(self.backend,'settings_for',return_value={'seed':1}), \
                patch.object(self.backend,'build_graph',return_value={'1':{'class_type':'SyntheticOutput','inputs':{}}}), \
                patch.object(self.backend.requests,'post',return_value=reply) as remote:
            headers={} if expected is None else {'X-Expected-Credits':expected}
            response=client.post('/api/jobs',json=body,headers=headers)
        return response,remote

    def count(self,table):
        with self.backend.database() as db:return db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_anonymous_private_api_is_closed_while_site_is_visible(self):
        for path in ('/api/jobs','/api/account/me','/api/account/dashboard','/api/admin/dashboard'):
            with self.subTest(path=path):self.assertEqual(self.anon.get(path).status_code,401)
        self.assertEqual(self.anon.post('/api/jobs',json={},headers={'Origin':ORIGIN}).status_code,401)
        self.assertEqual(self.anon.get('/studio.html').status_code,200)
        self.assertEqual(self.anon.get('/healthz').status_code,200)
        self.network_get.assert_not_called();self.network_post.assert_not_called()

    def test_registration_cannot_choose_an_administrator_role(self):
        payload={'username':'new-user','password':PASSWORD}
        denied=self.anon.post('/api/account/register',json={**payload,'role':'admin'},headers={'Origin':ORIGIN})
        self.assertEqual(denied.status_code,422)
        response=self.anon.post('/api/account/register',json=payload,headers={'Origin':ORIGIN})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['user']['role'],'user')

    def test_login_uses_httponly_cookie_and_https_cookie_is_secure(self):
        response=self.anon.post('/api/account/login',json={'username':'alice-user','password':PASSWORD},headers={'Origin':ORIGIN})
        self.assertEqual(response.status_code,200,response.text)
        cookie=response.headers['set-cookie'].lower()
        self.assertIn('httponly',cookie);self.assertIn('samesite=lax',cookie)
        self.assertNotIn('token',response.json()['user'])
        self.assertNotIn('session_token',response.json())
        https=TestClient(self.backend.app,base_url='https://testserver',raise_server_exceptions=False)
        self.addCleanup(https.close)
        secure=https.post('/api/account/login',json={'username':'alice-user','password':PASSWORD},headers={'Origin':'https://testserver'})
        self.assertEqual(secure.status_code,200,secure.text)
        self.assertIn('secure',secure.headers['set-cookie'].lower())

    def test_mutations_require_matching_origin_and_csrf(self):
        payload={'package_id':'test-package','idempotency_key':'csrf-test-key','method':'admin_contact'}
        for headers in ({'Origin':'https://evil.example'}, {'X-CSRF-Token':'wrong'}, {'Origin':''},{'X-CSRF-Token':''}):
            with self.subTest(headers=headers):self.assertEqual(self.client.post('/api/account/orders',json=payload,headers=headers).status_code,403)
        self.assertEqual(self.count('platform_orders'),0)

    def test_stale_account_header_rejects_read_and_write(self):
        self.assertEqual(self.client.get('/api/account/dashboard',headers={'X-Platform-Account':self.bob['id']}).status_code,409)
        response=self.client.post('/api/account/orders',json={'package_id':'test-package','method':'admin_contact','idempotency_key':'account-switch'},headers={'X-Platform-Account':self.bob['id']})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.count('platform_orders'),0)

    def test_sync_job_list_receives_actor_context_and_filters_other_users(self):
        self.job_fixture(self.alice,'alice-job');self.job_fixture(self.bob,'bob-job')
        self.assertEqual([j['id'] for j in self.client.get('/api/jobs').json()],['alice-job'])
        self.assertEqual([j['id'] for j in self.bob_client.get('/api/jobs').json()],['bob-job'])
        self.assertEqual(self.admin_client.get('/api/jobs').json(),[])

    def test_all_job_asset_and_media_paths_deny_other_account(self):
        self.job_fixture(self.bob,'bob-job');identifier=self.asset_fixture(self.bob)
        for path in ('/api/jobs/bob-job','/api/jobs/bob-job/workflow','/api/media/bob-job/0.txt',f'/api/assets/{identifier}/file'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,404)
        for action in ('cancel','abandon','retrieve','rerun'):
            with self.subTest(action=action):self.assertEqual(self.client.post('/api/jobs/bob-job/'+action,json={'token':'not-mine-0001'}).status_code,404)
        self.network_get.assert_not_called();self.network_post.assert_not_called()

    def test_owned_resources_remain_available_through_actual_endpoints(self):
        self.job_fixture(self.alice,'alice-job');identifier=self.asset_fixture(self.alice)
        self.assertEqual(self.client.get('/api/jobs/alice-job').status_code,200)
        self.assertEqual(self.client.get('/api/jobs/alice-job/workflow').status_code,200)
        self.assertEqual(self.client.get('/api/media/alice-job/0.txt').text,'synthetic private output')
        self.assertEqual(self.client.get(f'/api/assets/{identifier}/file').status_code,200)

    def test_ordinary_user_cannot_use_administration_or_local_directory(self):
        self.assertEqual(self.client.get('/api/admin/dashboard').status_code,403)
        for path,payload in (('/api/admin/packages',{'id':'other','title':'other','credits':100,'amount_minor':1,'enabled':True}),
                             ('/api/admin/pricing',{'workflow_id':self.workflow,'credits':0}),
                             (f'/api/admin/users/{self.alice["id"]}',{'role':'admin'}),
                             ('/api/local-directory',{'initial':''})):
            with self.subTest(path=path):self.assertEqual(self.client.post(path,json=payload).status_code,403)
        self.assertEqual(self.store.account(self.alice['id'])['role'],'user')
        combined=self.admin_client.post('/api/admin/users/'+self.alice['id'],json={'role':'admin','disabled':True})
        self.assertEqual(combined.status_code,400,combined.text)
        unchanged=self.store.account(self.alice['id'])
        self.assertEqual(unchanged['role'],'user')
        self.assertTrue(unchanged['enabled'])

    def test_recharge_order_replays_same_key_and_rejects_client_prices(self):
        body={'package_id':'test-package','method':'admin_contact','idempotency_key':'recharge-same-key'}
        one=self.client.post('/api/account/orders',json=body)
        two=self.client.post('/api/account/orders',json=body)
        self.assertEqual(one.status_code,200,one.text)
        self.assertEqual(one.json()['order']['id'],two.json()['order']['id'])
        self.assertEqual(one.json()['checkout']['mode'],'manual')
        self.assertEqual(self.count('platform_orders'),1)
        self.assertEqual(self.client.post('/api/account/orders',json={**body,'amount_minor':1,'credits':999999}).status_code,422)
        conflict=self.client.post('/api/account/orders',json={**body,'package_id':'different-package'})
        self.assertEqual(conflict.status_code,409)

    def test_other_user_cannot_read_or_cancel_recharge_order(self):
        order=self.store.create_order(self.bob['id'],'test-package','other-order-key','admin_contact')
        self.assertEqual(self.client.get('/api/account/orders/'+order['id']).status_code,404)
        self.assertEqual(self.client.post('/api/account/orders/'+order['id']+'/cancel').status_code,404)
        self.assertEqual(self.store.get_order(order['id'])['status'],'pending')

    def test_manual_confirmation_uses_price_snapshot_and_credits_only_once(self):
        created=self.client.post('/api/account/orders',json={'package_id':'test-package','method':'admin_contact','idempotency_key':'snapshot-order'}).json()['order']
        changed=self.admin_client.post('/api/admin/packages',json={'id':'test-package','title':'新套餐','credits':999,'amount_minor':9900,'enabled':True})
        self.assertEqual(changed.status_code,200,changed.text)
        path='/api/admin/orders/'+created['id']+'/confirm';body={'payment_reference':'synthetic-bank-transfer-01'}
        first=self.admin_client.post(path,json=body);second=self.admin_client.post(path,json=body)
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(first.json()['amount_minor'],2900)
        self.assertEqual(first.json()['credits'],100)
        self.assertEqual(self.store.account(self.alice['id'])['balance'],100)
        self.assertEqual(len([e for e in self.store.ledger(self.alice['id']) if e['event']=='recharge']),1)

    def test_ordinary_user_cannot_confirm_their_own_recharge(self):
        order=self.store.create_order(self.alice['id'],'test-package','forbidden-confirm','admin_contact')
        response=self.client.post('/api/admin/orders/'+order['id']+'/confirm',json={'payment_reference':'browser-says-paid'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.store.account(self.alice['id'])['balance'],0)

    def test_unconfigured_payment_methods_and_browser_webhooks_never_credit(self):
        for method in ('alipay','wechat','bank'):
            with self.subTest(method=method):
                response=self.client.post('/api/account/orders',json={'package_id':'test-package','method':method,'idempotency_key':'disabled-'+method})
                self.assertEqual(response.status_code,409)
        self.assertEqual(self.anon.post('/api/payments/webhooks/alipay',data={'success':'true'}).status_code,400)
        self.assertEqual(self.anon.post('/api/payments/webhooks/wechat',json={'success':True}).status_code,400)
        self.assertEqual(self.count('platform_orders'),0)
        self.assertEqual(self.store.account(self.alice['id'])['balance'],0)

    def test_missing_or_changed_quote_stops_before_job_or_credit_reservation(self):
        self.fund(self.alice)
        for expected in (None,'9'):
            response,remote=self.submit(expected=expected)
            self.assertEqual(response.status_code,409,response.text)
            remote.assert_not_called()
        self.assertEqual(self.count('jobs'),0);self.assertEqual(self.count('platform_reservations'),0)
        self.assertEqual(self.store.account(self.alice['id'])['balance'],100)

    def test_identical_submission_replay_has_one_job_one_hold_and_raw_client_token(self):
        self.fund(self.alice)
        first,remote=self.submit();second,retry=self.submit()
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(first.json()['id'],second.json()['id'])
        self.assertEqual(first.json()['request_token'],'offline-submit-0001')
        self.assertNotIn('owner_id',first.json());self.assertNotIn('request_fingerprint',first.json())
        self.assertEqual(remote.call_count,1);retry.assert_not_called()
        self.assertEqual(self.count('jobs'),1);self.assertEqual(self.count('platform_reservations'),1)
        account=self.store.account(self.alice['id'])
        self.assertEqual((account['balance'],account['held']),(90,10))

    def test_same_account_token_with_different_parameters_is_a_conflict(self):
        self.fund(self.alice)
        first,_=self.submit()
        second,remote=self.submit(prompt='a different scene')
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.status_code,409,second.text)
        remote.assert_not_called()
        self.assertEqual(self.count('jobs'),1);self.assertEqual(self.count('platform_reservations'),1)

    def test_different_accounts_can_use_the_same_client_token(self):
        self.fund(self.alice);self.fund(self.bob)
        first,_=self.submit();second,_=self.submit(client=self.bob_client)
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(second.status_code,200,second.text)
        self.assertNotEqual(first.json()['id'],second.json()['id'])
        self.assertEqual(self.count('jobs'),2)
        self.assertEqual(len(self.client.get('/api/jobs').json()),1)
        self.assertEqual(len(self.bob_client.get('/api/jobs').json()),1)
        self.assertEqual(self.store.account(self.alice['id'])['held'],10)
        self.assertEqual(self.store.account(self.bob['id'])['held'],10)

    def test_job_insert_ownership_failure_rolls_back_job_balance_and_ledger(self):
        self.fund(self.alice)
        original=self.store.grant_resource
        def fail(account,kind,identifier,connection=None):
            if kind=='job':raise sqlite3.IntegrityError('synthetic ownership failure')
            return original(account,kind,identifier,connection)
        with patch.object(self.store,'grant_resource',side_effect=fail):
            response,remote=self.submit()
        self.assertEqual(response.status_code,500,response.text)
        remote.assert_not_called()
        self.assertEqual(self.count('jobs'),0);self.assertEqual(self.count('platform_reservations'),0)
        self.assertEqual(self.store.account(self.alice['id'])['balance'],100)
        self.assertEqual(self.store.account(self.alice['id'])['held'],0)
        self.assertFalse(any(e['event']=='reserve' for e in self.store.ledger(self.alice['id'])))

    def test_output_failure_retains_hold_and_http_retrieval_settles_only_once(self):
        self.fund(self.alice)
        response,_=self.submit();self.assertEqual(response.status_code,200,response.text)
        identifier=response.json()['id']
        self.backend.update(identifier,status='failed',failure_phase='output',output_failure_code='storage_full')
        self.assertEqual(self.store.reservation(identifier)['status'],'held')
        self.assertEqual(self.store.account(self.alice['id'])['held'],10)
        history={'synthetic-remote-id':{'status':{'completed':True,'status_str':'success'},'outputs':{}}}
        reply=SimpleNamespace(raise_for_status=lambda:None,json=lambda:history)
        def finish(record,h):self.backend.update(record['id'],status='done',failure_phase=None)
        with patch.object(self.backend.requests,'get',return_value=reply),patch.object(self.backend,'finish_output_collection',side_effect=finish):
            retrieved=self.client.post('/api/jobs/'+identifier+'/retrieve')
            repeat=self.client.post('/api/jobs/'+identifier+'/retrieve')
        self.assertEqual(retrieved.status_code,200,retrieved.text);self.assertEqual(repeat.status_code,409)
        self.assertEqual(self.store.reservation(identifier)['status'],'settled')
        account=self.store.account(self.alice['id'])
        self.assertEqual((account['balance'],account['held']),(90,0))
        self.assertEqual(len([e for e in self.store.ledger(self.alice['id']) if e['event']=='settle']),1)

    def test_insufficient_credits_rolls_back_and_never_dispatches(self):
        response,remote=self.submit()
        self.assertEqual(response.status_code,402,response.text)
        remote.assert_not_called()
        self.assertEqual(self.count('jobs'),0);self.assertEqual(self.count('platform_reservations'),0)
        self.assertEqual(self.store.account(self.alice['id'])['held'],0)

    def test_admin_generation_review_http_preserves_hold_until_verified_resolution(self):
        self.fund(self.alice)
        response,_=self.submit()
        identifier=response.json()['id']
        self.backend.update(identifier,status='failed',failure_phase='output')
        dashboard=self.admin_client.get('/api/admin/dashboard')
        self.assertEqual(dashboard.status_code,200,dashboard.text)
        reviews=dashboard.json()['generation_reviews']
        self.assertEqual([r['job_id'] for r in reviews],[identifier])
        self.assertNotIn('prompt',reviews[0]);self.assertNotIn('graph',reviews[0])
        path='/api/admin/generation-reviews/'+identifier+'/resolve'
        body={'decision':'release','confirmation_reference':'synthetic-review-001','note':'compute consumption independently verified'}
        self.assertEqual(self.client.post(path,json=body).status_code,403)
        self.assertEqual(self.store.account(self.alice['id'])['held'],10)
        self.assertEqual(self.admin_client.post(path,json={**body,'confirmation_reference':'x'}).status_code,422)
        first=self.admin_client.post(path,json=body)
        second=self.admin_client.post(path,json=body)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.status_code,200,second.text)
        self.assertTrue(second.json()['already_resolved'])
        self.assertEqual((self.store.account(self.alice['id'])['balance'],self.store.account(self.alice['id'])['held']),(100,0))
        conflict=self.admin_client.post(path,json={**body,'decision':'settle'})
        self.assertEqual(conflict.status_code,409,conflict.text)

    def test_late_payment_review_http_accepts_string_identifier_and_never_trusts_user(self):
        order=self.store.create_order(self.alice['id'],'test-package','late-payment-http','wechat')
        self.store.mark_order_checkout(order['id'],'wechat',order['id'])
        self.store.cancel_order(self.alice['id'],order['id'])
        with self.assertRaises(platform_api.AccountError):
            self.store.credit_verified_order(order['id'],'wechat',2900,'CNY','synthetic-late-provider-tx')
        review=self.admin_client.get('/api/admin/dashboard').json()['payment_reviews'][0]
        self.assertIsInstance(review['id'],str)
        path='/api/admin/payment-reviews/'+review['id']+'/resolve'
        body={'decision':'credit','note':'provider receipt independently confirmed'}
        self.assertEqual(self.client.post(path,json=body).status_code,403)
        first=self.admin_client.post(path,json=body)
        second=self.admin_client.post(path,json=body)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(self.store.account(self.alice['id'])['balance'],100)
        self.assertEqual(len([e for e in self.store.ledger(self.alice['id']) if e['event']=='recharge']),1)


    def test_admin_adjustment_requires_admin_csrf_and_strict_validated_body(self):
        path = '/api/admin/users/'+self.alice['id']+'/credits'
        payload = {'delta':25,'reason':'后台调整测试积分','idempotency_key':'http-adjust-0001'}
        self.assertEqual(self.anon.post(path,json=payload,headers={'Origin':ORIGIN}).status_code,401)
        self.assertEqual(self.client.post(path,json=payload).status_code,403)
        self.assertEqual(self.admin_client.post(path,json=payload,headers={'X-CSRF-Token':''}).status_code,403)
        for delta in (True,False,1.5,'25',self.store.MAX_CREDITS+1):
            with self.subTest(delta=delta):
                self.assertEqual(self.admin_client.post(path,json={**payload,'delta':delta}).status_code,422)
        for extra in ({'held':1},{'balance':9999},{'role':'admin'}):
            self.assertEqual(self.admin_client.post(path,json={**payload,**extra}).status_code,422)
        self.assertEqual(self.admin_client.post(path,json={**payload,'delta':0}).status_code,400)
        self.assertEqual(self.admin_client.post(path,json={**payload,'reason':'  '}).status_code,422)
        self.assertEqual(0,self.store.account(self.alice['id'])['balance'])
        self.assertEqual(0,self.count('platform_credit_adjustments'))

    def test_admin_adjustment_http_replays_once_and_binds_all_financial_fields(self):
        path = '/api/admin/users/'+self.alice['id']+'/credits'
        payload = {'delta':25,'reason':'后台调整测试积分','idempotency_key':'http-adjust-0001'}
        first = self.admin_client.post(path,json=payload)
        repeat = self.admin_client.post(path,json=payload)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(repeat.status_code,200,repeat.text)
        self.assertFalse(first.json()['adjustment']['already_applied'])
        self.assertTrue(repeat.json()['adjustment']['already_applied'])
        self.assertEqual(first.json()['adjustment']['id'],repeat.json()['adjustment']['id'])
        self.assertEqual(25,repeat.json()['user']['available'])
        self.assertNotIn('password_hash',first.json()['user'])
        self.assertNotIn('username_key',first.json()['user'])
        for change in ({'delta':26},{'reason':'另一后台调整原因'}):
            self.assertEqual(self.admin_client.post(path,json={**payload,**change}).status_code,409)
        self.assertEqual(self.admin_client.post('/api/admin/users/'+self.bob['id']+'/credits',json=payload).status_code,409)
        self.assertEqual(1,self.count('platform_credit_adjustments'))
        self.assertEqual(1,self.count('platform_ledger'))

    def test_admin_adjustment_http_protects_held_balance_and_disabled_state(self):
        self.fund(self.alice)
        self.store.reserve(self.alice['id'],'held-adjustment-test',self.workflow)
        self.store.disable_account(self.admin['id'],self.alice['id'],True)
        path = '/api/admin/users/'+self.alice['id']+'/credits'
        payload = {'delta':-91,'reason':'后台扣减测试积分','idempotency_key':'http-debit-0001'}
        denied = self.admin_client.post(path,json=payload)
        self.assertEqual(denied.status_code,409,denied.text)
        accepted = self.admin_client.post(path,json={**payload,'delta':-90})
        self.assertEqual(accepted.status_code,200,accepted.text)
        user = accepted.json()['user']
        self.assertEqual((0,10,False),(user['available'],user['held'],user['enabled']))
        self.assertEqual('held',self.store.reservation('held-adjustment-test')['status'])
        self.assertEqual(self.client.get('/api/account/me').status_code,401)

    def test_admin_adjustment_http_storage_failure_does_not_partially_credit(self):
        path = '/api/admin/users/'+self.alice['id']+'/credits'
        payload = {'delta':25,'reason':'后台事务回滚测试积分','idempotency_key':'http-rollback-0001'}
        with patch.object(self.store,'_audit',side_effect=RuntimeError('simulated audit failure')):
            self.assertEqual(self.admin_client.post(path,json=payload).status_code,500)
        self.assertEqual(0,self.store.account(self.alice['id'])['balance'])
        self.assertEqual(0,self.count('platform_credit_adjustments'))
        self.assertEqual(0,self.count('platform_ledger'))
        self.assertEqual(self.admin_client.post(path,json=payload).status_code,200)

    def test_admin_reads_ledger_and_safe_audit_metadata_while_user_is_denied(self):
        self.store.adjust_credits(self.admin['id'],self.alice['id'],25,'后台审计测试积分','http-audit-0001')
        paths = ('/api/admin/users/'+self.alice['id']+'/ledger','/api/admin/audit')
        for path in paths:
            self.assertEqual(self.client.get(path).status_code,403)
            self.assertEqual(self.anon.get(path).status_code,401)
        ledger = self.admin_client.get(paths[0])
        self.assertEqual(ledger.status_code,200,ledger.text)
        body = ledger.json()
        self.assertEqual(self.alice['id'],body['user']['id'])
        self.assertEqual('adjustment',body['ledger'][0]['event'])
        self.assertEqual('后台审计测试积分',body['ledger'][0]['reason'])
        with self.store.transaction() as db:
            self.store._audit(db,self.admin['id'],'safe-test',self.alice['id'],{'delta':25,'api_key':'SECRET','graph':{'key':'SECRET'}})
        audit = self.admin_client.get(paths[1])
        self.assertEqual(audit.status_code,200,audit.text)
        self.assertEqual({'delta':25},audit.json()['audit'][0]['data'])
        self.assertNotIn('SECRET',audit.text)
        self.assertNotIn('password_hash',audit.text)
        self.assertEqual(self.admin_client.get('/api/admin/users/missing-user/ledger').status_code,404)

    def test_admin_dashboard_stats_and_workflow_choices_only_expose_real_names(self):
        self.fund(self.alice)
        self.store.reserve(self.alice['id'],'stat-hold',self.workflow)
        self.store.disable_account(self.admin['id'],self.bob['id'],True)
        self.store.create_order(self.alice['id'],'test-package','stat-pending-order')
        with patch.object(self.backend,'WORKFLOWS',[{'id':'real-api-tool','name':'真实 API 工具','graph':'SECRET-GRAPH'}]), \
                patch.object(self.backend,'CATALOG_WORKFLOWS',[{'id':'real-legacy-tool','name':'真实传统工作流','source':'SECRET-SOURCE'}]), \
                patch.object(self.backend.schema_adapters,'registry',return_value={
                    'real-schema-tool':{'id':'real-schema-tool','name':'真实编译工作流','validation':'structural-verified','api_key':'SECRET-KEY'},
                    'blocked-schema-tool':{'id':'blocked-schema-tool','name':'受阻工作流','validation':'blocked','api_key':'SECRET-BLOCKED'}}):
            response = self.admin_client.get('/api/admin/dashboard')
            self.assertEqual(response.status_code,200,response.text)
            data = response.json()
            self.assertEqual({'users':3,'enabled_users':2,'available_credits':90,'held_credits':10,'pending_orders':1},data['stats'])
            self.assertEqual([{'id':'real-api-tool','name':'真实 API 工具'},
                {'id':'real-legacy-tool','name':'真实传统工作流'},
                {'id':'real-schema-tool','name':'真实编译工作流'}],data['workflow_options'])
            self.assertNotIn('blocked-schema-tool',{item['id']for item in data['workflow_options']})
            self.assertNotIn('SECRET',response.text)
            pricing = self.admin_client.post('/api/admin/pricing',json={'workflow_id':'real-legacy-tool','credits':12})
            self.assertEqual(pricing.status_code,200,pricing.text)
        self.assertEqual(self.client.get('/api/admin/dashboard').status_code,403)

    def test_demoted_administrator_cannot_reuse_existing_session_for_credit_adjustment(self):
        self.store.set_role(self.admin['id'],self.bob['id'],'admin')
        self.store.set_role(self.bob['id'],self.admin['id'],'user')
        path = '/api/admin/users/'+self.alice['id']+'/credits'
        denied = self.admin_client.post(path,json={'delta':25,'reason':'降级账号尝试加积分','idempotency_key':'demoted-adjust-0001'})
        self.assertEqual(denied.status_code,403,denied.text)
        self.assertEqual(0,self.store.account(self.alice['id'])['balance'])

    def test_admin_user_creation_returns_safe_zero_balance_user_without_login(self):
        before_sessions = self.count('platform_sessions')
        response = self.admin_client.post('/api/admin/users',json={'username':'created-user','password':PASSWORD})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('set-cookie',response.headers)
        user = response.json()['user']
        self.assertEqual(('created-user','user',True,False,0,0,0),
                         (user['username'],user['role'],user['enabled'],user['legacy_owner'],user['balance'],user['held'],user['available']))
        self.assertNotIn('password_hash',response.text)
        self.assertNotIn('username_key',response.text)
        self.assertNotIn(PASSWORD,response.text)
        self.assertEqual(before_sessions,self.count('platform_sessions'))
        self.assertEqual(self.admin['id'],self.admin_client.get('/api/account/me').json()['user']['id'])
        self.assertEqual(user['id'],self.store.authenticate('CREATED-USER',PASSWORD)['id'])
        self.assertEqual(0,self.count('platform_ledger'))
        audit = self.admin_client.get('/api/admin/audit').json()['audit'][0]
        self.assertEqual(('create_user',user['id']),(audit['action'],audit['target']))
        self.assertEqual({'username':'created-user','role':'user','enabled':True},audit['data'])

    def test_admin_user_creation_explicit_role_and_normalized_duplicates(self):
        response = self.admin_client.post('/api/admin/users',json={'username':'ＣＲＥＡＴＥＤ.User','password':PASSWORD,'role':'admin'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(('CREATED.User','admin'),(response.json()['user']['username'],response.json()['user']['role']))
        for username in ('created.user','ＡＬＩＣＥ－ＵＳＥＲ'):
            denied = self.admin_client.post('/api/admin/users',json={'username':username,'password':PASSWORD})
            self.assertEqual(denied.status_code,409,denied.text)
            self.assertEqual('username_taken',denied.json()['code'])
        self.assertEqual(4,self.count('platform_accounts'))

    def test_admin_created_username_at_the_supported_limit_can_log_in(self):
        username = 'n'*80
        response = self.admin_client.post('/api/admin/users',json={'username':username,'password':PASSWORD})
        self.assertEqual(response.status_code,200,response.text)
        login = self.anon.post('/api/account/login',json={'username':username,'password':PASSWORD},headers={'Origin':ORIGIN})
        self.assertEqual(login.status_code,200,login.text)
        self.assertEqual(response.json()['user']['id'],login.json()['user']['id'])
        self.assertEqual('user',login.json()['user']['role'])

    def test_admin_user_creation_requires_admin_csrf_and_same_origin(self):
        before_audit=self.count('platform_admin_audit')
        payload = {'username':'forbidden-user','password':PASSWORD,'role':'admin'}
        self.assertEqual(self.anon.post('/api/admin/users',json=payload,headers={'Origin':ORIGIN}).status_code,401)
        self.assertEqual(self.client.post('/api/admin/users',json=payload).status_code,403)
        self.assertEqual(self.admin_client.post('/api/admin/users',json=payload,headers={'X-CSRF-Token':''}).status_code,403)
        self.assertEqual(self.admin_client.post('/api/admin/users',json=payload,headers={'Origin':'https://untrusted.invalid'}).status_code,403)
        self.assertEqual(3,self.count('platform_accounts'))
        self.assertEqual(before_audit,self.count('platform_admin_audit'),
                         'Rejected requests add no user-creation or other audit events.')

    def test_admin_user_creation_rejects_invalid_or_extra_body_fields(self):
        payload = {'username':'created-user','password':PASSWORD}
        for changed in ({'role':'superadmin'},{'role':None},{'role':True},{'username':123},{'username':'ab'},
                        {'username':'a'*81},{'password':123},{'password':'short'},{'password':'a'*129},
                        {'balance':100},{'held':100},{'enabled':False},{'legacy_owner':True},{'csrf_token':'fake'}):
            with self.subTest(fields=list(changed)):
                self.assertEqual(self.admin_client.post('/api/admin/users',json={**payload,**changed}).status_code,422)
        for changed in ({'username':'bad/name'},{'password':' '*10}):
            response = self.admin_client.post('/api/admin/users',json={**payload,**changed})
            self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(3,self.count('platform_accounts'))

    def test_admin_user_creation_audit_failure_is_atomic_and_can_retry(self):
        payload = {'username':'rollback-user','password':PASSWORD,'role':'admin'}
        count = self.count('platform_admin_audit')
        with patch.object(self.store,'_audit',side_effect=RuntimeError('simulated audit failure')):
            self.assertEqual(self.admin_client.post('/api/admin/users',json=payload).status_code,500)
        self.assertEqual(3,self.count('platform_accounts'))
        self.assertEqual(count,self.count('platform_admin_audit'))
        response = self.admin_client.post('/api/admin/users',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(4,self.count('platform_accounts'))
        self.assertEqual(count+1,self.count('platform_admin_audit'))

    def test_credentials_validation_does_not_echo_passwords_or_extra_private_values(self):
        secret = 'private-password-secret-'+'x'*130
        payload = {'username':'created-user','password':secret,'private':{'password':'extra-password-secret'}}
        response = self.admin_client.post('/api/admin/users',json=payload)
        self.assertEqual(response.status_code,422,response.text)
        self.assertNotIn(secret,response.text)
        self.assertNotIn('extra-password-secret',response.text)
        self.assertTrue(all(set(error)=={'loc','msg','type'} for error in response.json()['detail']))
        for path in ('/api/account/register','/api/account/login'):
            response = self.anon.post(path,json={'username':'created-user','password':True,'private':secret},headers={'Origin':ORIGIN})
            self.assertEqual(response.status_code,422,response.text)
            self.assertNotIn(secret,response.text)
            self.assertTrue(all('input' not in error and 'ctx' not in error for error in response.json()['detail']))
        response = self.client.post('/api/account/password',json={'current_password':True,'new_password':secret})
        self.assertEqual(response.status_code,422,response.text)
        self.assertNotIn(secret,response.text)
        self.assertEqual(3,self.count('platform_accounts'))

    def test_admin_user_creation_rejects_a_demoted_session(self):
        self.store.set_role(self.admin['id'],self.bob['id'],'admin')
        self.store.set_role(self.bob['id'],self.admin['id'],'user')
        response = self.admin_client.post('/api/admin/users',json={'username':'forbidden-user','password':PASSWORD})
        self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(3,self.count('platform_accounts'))

    def test_admin_user_pagination_reads_beyond_500_with_accurate_filtered_total(self):
        with self.store.transaction() as db:
            password_hash = db.execute('SELECT password_hash FROM platform_accounts WHERE id=?',(self.alice['id'],)).fetchone()[0]
            db.executemany('''INSERT INTO platform_accounts(id,username,username_key,password_hash,role,enabled,created_at)
                VALUES(?,?,?,?,?,?,?)''',[(f'http-page-{index}',f'aggregate{index}',f'aggregate{index}',password_hash,'user',int(index%2==0),0) for index in range(500)])
        response = self.admin_client.get('/api/admin/users',params={'offset':500,'limit':50})
        self.assertEqual(response.status_code,200,response.text)
        data = response.json()
        self.assertEqual((503,500,50,3),(data['total'],data['offset'],data['limit'],len(data['users'])))
        self.assertTrue(all('available' in user and 'password_hash' not in user and 'username_key' not in user for user in data['users']))
        filtered = self.admin_client.get('/api/admin/users',params={'query':'aggregate','role':'user','state':'disabled','offset':240,'limit':50})
        self.assertEqual(filtered.status_code,200,filtered.text)
        self.assertEqual((250,10),(filtered.json()['total'],len(filtered.json()['users'])))
        self.assertTrue(all(not user['enabled'] and user['role']=='user' for user in filtered.json()['users']))

    def test_blocked_workflows_cannot_be_configured_as_payable_tools(self):
        blocked = {identifier for identifier,spec in self.backend.schema_adapters.registry().items()
                   if spec.get('validation') != 'structural-verified'}
        self.assertTrue(blocked)
        options = self.admin_client.get('/api/admin/dashboard').json()['workflow_options']
        self.assertFalse(blocked & {option['id'] for option in options})
        identifier = next(iter(blocked))
        before = self.store.list_pricing(self.admin['id'])
        self.assertEqual(400,self.admin_client.post('/api/admin/pricing',json={'workflow_id':identifier,'credits':1}).status_code)
        self.assertEqual(403,self.client.post('/api/admin/pricing',json={'workflow_id':identifier,'credits':1}).status_code)
        self.assertEqual(before,self.store.list_pricing(self.admin['id']))
        self.network_get.assert_not_called();self.network_post.assert_not_called()

    def test_reference_pricing_requires_account_and_existing_csrf_boundary(self):
        payload = {'model':'seedream-4.5','kind':'image','quality':'2K','count':1,'duration':None}
        self.assertEqual(401,self.anon.get('/api/account/pricing-policy').status_code)
        self.assertEqual(401,self.anon.post('/api/account/creation-quote',json=payload,headers={'Origin':ORIGIN}).status_code)
        self.assertEqual(403,self.client.post('/api/account/creation-quote',json=payload,headers={'X-CSRF-Token':''}).status_code)
        self.assertEqual(403,self.client.post('/api/account/creation-quote',json=payload,headers={'Origin':'https://evil.example'}).status_code)
        response = self.client.get('/api/account/pricing-policy')
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual('no-store',response.headers['cache-control'])
        self.assertEqual({'credit_policy','creation_pricing'},set(response.json()))
        self.assertEqual(100,response.json()['credit_policy']['credits_per_yuan'])

    def test_reference_quotes_count_parameters_without_creating_jobs_or_debits(self):
        before = {table:self.count(table) for table in ('jobs','platform_orders','platform_ledger','platform_admin_audit')}
        balance = self.store.account(self.alice['id'])
        image = self.client.post('/api/account/creation-quote',json={
            'model':'seedream-4.5','kind':'image','quality':'2K','count':8,'duration':None})
        self.assertEqual(200,image.status_code,image.text)
        self.assertEqual((True,200,200,'reference'),tuple(image.json()[key] for key in ('configured','credits','amount_minor','mode')))
        video = self.client.post('/api/account/creation-quote',json={
            'model':'seedance-2.0','kind':'video','quality':'480p','count':1,'duration':4})
        self.assertEqual(200,video.status_code,video.text)
        self.assertEqual(370,video.json()['credits'])
        self.assertEqual(before,{table:self.count(table) for table in before})
        self.assertEqual(balance,self.store.account(self.alice['id']))
        self.network_get.assert_not_called();self.network_post.assert_not_called()

    def test_creation_quote_strictly_rejects_extra_fields_and_invalid_model_controls(self):
        payload = {'model':'seedream-4.5','kind':'image','quality':'2K','count':1,'duration':None}
        changes = [{'count':True},{'count':'2'},{'count':2.0},{'count':0},{'count':9},
                   {'duration':8},{'duration':'8'},{'quality':'4K'},{'kind':'audio'},
                   {'model':'seedance-2.0','kind':'image'},
                   {'model':'seedance-2.0','kind':'video','quality':'720p','duration':8,'count':2},
                   {'model':'seedance-2.0','kind':'video','quality':'720p','duration':8.0},
                   {'model':'seedance-2.0','kind':'video','quality':'720p','duration':3},
                   {'model':'veo-3.1','kind':'video','quality':'720p','duration':5},
                   {'prompt':'must not be sent'},{'price':1},{'api_key':'must not be sent'}]
        for change in changes:
            with self.subTest(change=change):
                response = self.client.post('/api/account/creation-quote',json={**payload,**change})
                self.assertEqual(422,response.status_code,response.text)
        for key in payload:
            response = self.client.post('/api/account/creation-quote',json={name:value for name,value in payload.items() if name!=key})
            self.assertEqual(422,response.status_code,response.text)

    def test_missing_and_unknown_reference_prices_remain_explicitly_unconfigured(self):
        payload = {'model':'flux-2-pro','kind':'image','quality':'2K','count':1,'duration':None}
        for model in ('new-unpriced-model','another-unpriced-model'):
            response = self.client.post('/api/account/creation-quote',json={**payload,'model':model})
            self.assertEqual(200,response.status_code,response.text)
            self.assertFalse(response.json()['configured'])
            self.assertIsNone(response.json()['credits'])
            self.assertIsNone(response.json()['amount_minor'])
            self.assertTrue(response.json()['reason'])
        with patch.object(platform_pricing,'POLICY_PATH',self.private/'does-not-exist.json'):
            response = self.client.post('/api/account/creation-quote',json={**payload,'model':'seedream-4.5'})
            self.assertEqual(200,response.status_code,response.text)
            self.assertFalse(response.json()['configured'])
            self.assertIsNone(response.json()['credits'])
            self.assertEqual(100,response.json()['credit_policy']['credits_per_yuan'])

    def test_image_quality_reference_price_and_veo_partial_pricing_use_same_http_contract(self):
        image = self.client.post('/api/account/creation-quote',json={
            'model':'flux-2-pro','kind':'image','quality':'1K','count':8,'duration':None})
        self.assertEqual(200,image.status_code,image.text)
        self.assertEqual((True,162),tuple(image.json()[key] for key in ('configured','credits')))
        video = self.client.post('/api/account/creation-quote',json={
            'model':'veo-3.1','kind':'video','quality':'720p','count':1,'duration':4})
        self.assertEqual(200,video.status_code,video.text)
        self.assertEqual((True,1078),tuple(video.json()[key] for key in ('configured','credits')))
        pending = self.client.post('/api/account/creation-quote',json={
            'model':'veo-3.1','kind':'video','quality':'480p','count':1,'duration':8})
        self.assertEqual(200,pending.status_code,pending.text)
        self.assertFalse(pending.json()['configured'])
        self.assertIsNone(pending.json()['credits'])
        self.assertIsNone(pending.json()['amount_minor'])
        self.assertEqual(0,self.count('platform_ledger'))

    def test_credit_unit_and_workflow_money_are_shared_with_admin_and_account_views(self):
        for client,path in ((self.client,'/api/account/dashboard'),(self.admin_client,'/api/admin/dashboard')):
            response = client.get(path)
            self.assertEqual(200,response.status_code,response.text)
            self.assertEqual(platform_pricing.CREDIT_POLICY,response.json()['credit_policy'])
        quote = self.client.get('/api/account/quote/'+self.workflow)
        self.assertEqual(200,quote.status_code,quote.text)
        self.assertEqual((True,10,10,'CNY'),tuple(quote.json()[key] for key in ('configured','credits','amount_minor','currency')))
        missing = self.client.get('/api/account/quote/not-priced-yet')
        self.assertFalse(missing.json()['configured'])
        self.assertNotIn('amount_minor',missing.json())
        self.assertEqual(platform_pricing.CREDIT_POLICY,missing.json()['credit_policy'])

    def test_admin_user_pagination_rejects_bad_filters_and_literal_wildcards(self):
        exact = self.store.register('literal_name',PASSWORD)
        self.store.register('literalXname',PASSWORD)
        response = self.admin_client.get('/api/admin/users',params={'query':'LITERAL_NAME'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([exact['id']],[user['id'] for user in response.json()['users']])
        for query in ('%','literal%name','\\'):
            self.assertEqual(0,self.admin_client.get('/api/admin/users',params={'query':query}).json()['total'])
        for parameters in ({'role':'superadmin'},{'state':'unknown'},{'limit':101},{'limit':0},{'offset':-1},{'query':'a'*81}):
            self.assertEqual(self.admin_client.get('/api/admin/users',params=parameters).status_code,422)
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        self.assertEqual(self.anon.get('/api/admin/users').status_code,401)


if __name__=='__main__':unittest.main()
