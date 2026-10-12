"""Documented aliases and IPv6 must pass both browser-origin guards."""
import os
from unittest import TestCase, main
from unittest.mock import patch

import test_platform_http as fixture
from fastapi.testclient import TestClient


class ConfiguredOriginContracts(TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PlatformHTTP.setUpClass.__func__(cls)

    start_patch = fixture.PlatformHTTP.start_patch
    actor = fixture.PlatformHTTP.actor

    def setUp(self):
        fixture.PlatformHTTP.setUp(self)
        self.start_patch(patch.dict(os.environ, {'YINGXU_LOCAL_MODE':'0',
            'RAILWAY_ENVIRONMENT_ID':'', 'RAILWAY_PUBLIC_DOMAIN':'',
            'YINGXU_ALLOWED_ORIGINS':''}))

    def login(self, base, origin, **headers):
        client = TestClient(self.backend.app, base_url=base, raise_server_exceptions=False)
        self.addCleanup(client.close)
        return client.post('/api/account/login', headers={'Origin':origin, **headers},
                           json={'username':'alice-user', 'password':fixture.PASSWORD})

    def test_configured_custom_domain_works_with_railway_internal_http(self):
        with patch.dict(os.environ, {'RAILWAY_PUBLIC_DOMAIN':'fixture.up.railway.app',
                'RAILWAY_ENVIRONMENT_ID':'test',
                'YINGXU_ALLOWED_ORIGINS':'https://studio.example'}):
            response = self.login('http://studio.example', 'https://studio.example')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('secure', response.headers['set-cookie'].lower())

    def test_tailscale_config_and_ipv6_loopback_are_usable(self):
        (self.private/'access.json').write_text('{"origin":"https://studio.tail-test.ts.net"}', 'utf-8')
        response = self.login('http://studio.tail-test.ts.net', 'https://studio.tail-test.ts.net')
        self.assertEqual(response.status_code, 200, response.text)
        # Bundled TestClient's URL transport cannot parse IPv6. ASGI uses Host
        # to construct the request URL, so exercise the same IPv6 origin here.
        response = self.login(fixture.ORIGIN, 'http://[::1]:8770', Host='[::1]:8770')
        self.assertEqual(response.status_code, 200, response.text)

    def test_host_and_forwarded_headers_cannot_add_an_origin(self):
        response = self.login('http://evil.example', 'http://evil.example',
                              **{'X-Forwarded-Host':'evil.example', 'X-Forwarded-Proto':'http'})
        self.assertEqual(response.status_code, 403)
        with patch.dict(os.environ, {'RAILWAY_PUBLIC_DOMAIN':'fixture.up.railway.app',
                'YINGXU_ALLOWED_ORIGINS':'https://good.example https://evil.example,https://evil.example/path'}):
            self.assertEqual(self.login('http://evil.example', 'https://evil.example').status_code, 403)

    def test_allowlisted_alias_does_not_bypass_csrf(self):
        with patch.dict(os.environ, {'RAILWAY_PUBLIC_DOMAIN':'fixture.up.railway.app',
                'YINGXU_ALLOWED_ORIGINS':'https://studio.example'}):
            client = self.actor(self.alice, origin='https://studio.example')
            client.headers.pop('X-CSRF-Token')
            response = client.post('/api/jobs', json={'workflow_id':self.workflow,
                'token':'csrf-alias-test', 'prompt':'test'})
            self.assertEqual(response.status_code, 403)
            self.network_post.assert_not_called()


if __name__ == '__main__':
    main()
