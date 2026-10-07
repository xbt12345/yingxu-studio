"""Cloud session boundary, plus isolated tests for the legacy Basic helper."""
import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_server_helpers import load_server, TestAccounts, ORIGIN
from fastapi.testclient import TestClient
import platform_api
from deployment_access import access_denied

server=None
PUBLIC_ORIGIN='https://studio-test.up.railway.app'
PASSWORD='test-cloud-user-password-12345'


class CloudAccessContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global server
        server,temporary=load_server('yingxu_isolated_cloud_backend')
        cls.addClassCleanup(temporary.cleanup)
        cls.addClassCleanup(lambda:sys.modules.pop(server.__name__,None))

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='yingxu-cloud-test-')
        self.addCleanup(temporary.cleanup)
        private=Path(temporary.name)
        for change in (patch.object(server,'DB',private/'workspace.sqlite3'),
                       patch.object(server,'PRIVATE',private),patch.object(server,'BASE',''),
                       patch.object(platform_api,'PlatformAccounts',TestAccounts),
                       patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'test-environment',
                            'RAILWAY_PUBLIC_DOMAIN':'studio-test.up.railway.app',
                            'YINGXU_ACCESS_USERNAME':'yingxu','YINGXU_ACCESS_PASSWORD':'test-only-password-12345'})):
            change.start();self.addCleanup(change.stop)
        with server.database() as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,token TEXT UNIQUE,data TEXT NOT NULL)')
            db.execute('CREATE TABLE assets(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        self.accounts=server.platform_bridge.accounts()
        self.user=self.accounts.register('cloud-user',PASSWORD)
        self.client=TestClient(server.app,base_url=PUBLIC_ORIGIN)
        self.client.headers['Origin']=PUBLIC_ORIGIN
        self.addCleanup(self.client.close)

    def login(self):
        response=self.client.post('/api/account/login',json={'username':'cloud-user','password':PASSWORD})
        self.assertEqual(response.status_code,200,response.text)
        self.client.headers.update({'X-CSRF-Token':response.json()['csrf_token'],'X-Platform-Account':self.user['id']})
        return response

    def test_login_page_is_visible_but_private_api_requires_session(self):
        for path in ('/studio.html','/app.js'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)
        for path in ('/api/jobs','/api/account/dashboard','/api/media/test/0.png','/api/assets/test/file'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,401)
        with patch.object(server.requests,'post') as submit:
            self.assertEqual(self.client.post('/api/jobs',json={}).status_code,401)
            submit.assert_not_called()
        self.assertEqual(self.client.get('/private/workspace.sqlite3').status_code,404)
        self.assertEqual(self.client.get('/private/admin-bootstrap.json').status_code,404)

    def test_bad_basic_bearer_and_login_password_do_not_allow_private_access(self):
        for value in ('Basic not-base64!','Bearer abc','Basic '+base64.b64encode(b'no-colon').decode()):
            with self.subTest(value=value):self.assertEqual(self.client.get('/api/jobs',headers={'Authorization':value}).status_code,401)
        self.assertEqual(self.client.get('/api/jobs',auth=('yingxu','test-only-password-12345')).status_code,401)
        self.assertEqual(self.client.post('/api/account/login',json={'username':'cloud-user','password':'wrong-password-123'}).status_code,401)

    def test_authenticated_site_and_railway_origin_work(self):
        response=self.login()
        self.assertIn('httponly',response.headers['set-cookie'].lower())
        self.assertIn('secure',response.headers['set-cookie'].lower())
        self.assertEqual(self.client.get('/studio.html').status_code,200)
        self.assertEqual(self.client.get('/api/jobs').status_code,200)
        self.assertEqual(self.client.get('/api/workflows').status_code,200)
        self.assertEqual(self.client.get('/api/workflows',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/workflows',headers={'Origin':'https://evil.example','Host':'evil.example'}).status_code,403)

    def test_missing_shared_password_does_not_open_private_session_api(self):
        for password in ('','too-short'):
            with self.subTest(password=password),patch.dict(os.environ,{'YINGXU_ACCESS_PASSWORD':password}):
                self.assertEqual(self.client.get('/studio.html').status_code,200)
                self.assertEqual(self.client.get('/api/jobs').status_code,401)

    def test_malformed_public_domain_does_not_break_static_site_or_trust_origin(self):
        self.login()
        for domain in ('[','evil.example/path','evil.example?query','user@evil.example'):
            with self.subTest(domain=domain),patch.dict(os.environ,{'RAILWAY_PUBLIC_DOMAIN':domain}):
                self.assertEqual(self.client.get('/studio.html').status_code,200)
                self.assertEqual(self.client.get('/api/workflows',headers={'Origin':'https://evil.example'}).status_code,403)

    def test_probe_is_public_and_does_not_call_remote_compute(self):
        with patch.dict(os.environ,{'YINGXU_ACCESS_PASSWORD':''}),patch.object(server.requests,'get') as remote:
            response=self.client.get('/healthz')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),{'status':'ok'})
            remote.assert_not_called()

    def test_local_demo_keeps_private_api_authenticated(self):
        with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'','RAILWAY_PUBLIC_DOMAIN':'','YINGXU_ACCESS_PASSWORD':''}):
            client=TestClient(server.app,base_url=ORIGIN)
            self.addCleanup(client.close)
            self.assertEqual(client.get('/studio.html').status_code,200)
            self.assertEqual(client.get('/api/jobs').status_code,401)
            self.assertEqual(client.post('/api/jobs',headers={'Origin':ORIGIN},json={}).status_code,401)


class LegacyBasicHelperContracts(unittest.TestCase):
    """Basic helper contracts only; the current platform uses account sessions."""
    def setUp(self):
        setting=patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'test-environment',
            'RAILWAY_PUBLIC_DOMAIN':'studio-test.up.railway.app','YINGXU_ACCESS_USERNAME':'yingxu',
            'YINGXU_ACCESS_PASSWORD':'test-only-password-12345'})
        setting.start();self.addCleanup(setting.stop)

    def test_valid_basic_helper_credentials_and_probe(self):
        authorization='Basic '+base64.b64encode(b'yingxu:test-only-password-12345').decode()
        self.assertIsNone(access_denied('/private-api',authorization))
        self.assertIsNone(access_denied('/healthz',None))

    def test_bad_basic_helper_credentials_remain_closed(self):
        for authorization in (None,'Basic malformed','Bearer abc','Basic '+base64.b64encode(b'wrong:wrong').decode()):
            denied=access_denied('/private-api',authorization)
            self.assertEqual(denied.status_code,401)
            self.assertIn('Basic',denied.headers['WWW-Authenticate'])

    def test_missing_or_short_legacy_password_stays_closed_in_cloud(self):
        for password in ('','short'):
            with patch.dict(os.environ,{'YINGXU_ACCESS_PASSWORD':password}):self.assertEqual(access_denied('/private-api',None).status_code,503)
        with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'','RAILWAY_PUBLIC_DOMAIN':'','YINGXU_ACCESS_PASSWORD':''}):
            self.assertIsNone(access_denied('/private-api',None))


if __name__=='__main__':unittest.main()
