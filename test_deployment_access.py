"""Exercise cloud access through real HTTP routes, without using a GPU."""
import base64
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import server


class CloudAccessContracts(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'RAILWAY_ENVIRONMENT_ID': 'test-environment',
            'RAILWAY_PUBLIC_DOMAIN': 'studio-test.up.railway.app',
            'YINGXU_ACCESS_USERNAME': 'yingxu',
            'YINGXU_ACCESS_PASSWORD': 'test-only-password-12345',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = TestClient(server.app)

    def test_pages_assets_and_jobs_require_authentication(self):
        for path in ('/studio.html', '/app.js', '/api/jobs', '/api/media/test'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn('Basic', response.headers['WWW-Authenticate'])
        with patch.object(server.requests, 'post') as submit:
            self.assertEqual(self.client.post('/api/jobs', json={}).status_code, 401)
            submit.assert_not_called()

    def test_bad_credentials_do_not_raise_or_allow_access(self):
        for value in ('Basic not-base64!', 'Bearer abc', 'Basic ' + base64.b64encode(b'no-colon').decode()):
            with self.subTest(value=value):
                self.assertEqual(self.client.get('/studio.html', headers={'Authorization': value}).status_code, 401)
        self.assertEqual(self.client.get('/studio.html', auth=('yingxu', 'wrong')).status_code, 401)

    def test_authenticated_site_and_railway_origin_work(self):
        self.client.auth = ('yingxu', 'test-only-password-12345')
        self.assertEqual(self.client.get('/studio.html').status_code, 200)
        response = self.client.get('/api/workflows', headers={'Origin': 'https://studio-test.up.railway.app'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/workflows', headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/workflows', headers={'Origin': 'https://evil.example', 'Host': 'evil.example'}).status_code, 403)

    def test_cloud_with_missing_or_short_password_stays_closed(self):
        for password in ('', 'too-short'):
            with self.subTest(password=password), patch.dict(os.environ, {'YINGXU_ACCESS_PASSWORD': password}):
                self.assertEqual(self.client.get('/studio.html').status_code, 503)

    def test_malformed_public_domain_does_not_break_authenticated_access(self):
        self.client.auth = ('yingxu', 'test-only-password-12345')
        for domain in ('[', 'evil.example/path', 'evil.example?query', 'user@evil.example'):
            with self.subTest(domain=domain), patch.dict(os.environ, {'RAILWAY_PUBLIC_DOMAIN': domain}):
                self.assertEqual(self.client.get('/studio.html').status_code, 200)
                self.assertEqual(self.client.get('/api/workflows', headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_probe_is_public_and_does_not_call_remote_compute(self):
        with patch.dict(os.environ, {'YINGXU_ACCESS_PASSWORD': ''}), patch.object(server.requests, 'get') as remote:
            response = self.client.get('/healthz')
            self.assertEqual(response.json(), {'status': 'ok'})
            self.assertEqual(response.status_code, 200)
            remote.assert_not_called()

    def test_local_demo_does_not_require_new_credentials(self):
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_ID': '', 'RAILWAY_PUBLIC_DOMAIN': '', 'YINGXU_ACCESS_PASSWORD': ''}):
            self.assertEqual(self.client.get('/studio.html').status_code, 200)


if __name__ == '__main__':
    unittest.main()
