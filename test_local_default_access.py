"""Default desktop entry using temporary data and no external services."""
import os
from unittest import TestCase, main
from unittest.mock import patch

import test_platform_http as fixture
import test_platform_local_mode as local_fixture
import platform_api


class DefaultLocalAccess(TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.PlatformHTTP.setUpClass.__func__(cls)

    start_patch = fixture.PlatformHTTP.start_patch
    actor = fixture.PlatformHTTP.actor
    count = fixture.PlatformHTTP.count
    job_fixture = fixture.PlatformHTTP.job_fixture
    local_client = local_fixture.LocalPlatformHTTP.local_client
    local_identity = local_fixture.LocalPlatformHTTP.local_identity

    def setUp(self):
        fixture.PlatformHTTP.setUp(self)
        self.start_patch(patch.dict(os.environ, {
            'RAILWAY_ENVIRONMENT_ID':'', 'RAILWAY_PUBLIC_DOMAIN':''}))
        os.environ.pop('YINGXU_LOCAL_MODE', None)
        self.local = self.local_client()

    def test_plain_start_reuses_existing_owner_and_work_after_store_reopen(self):
        self.job_fixture(self.admin, 'desktop-existing')
        self.job_fixture(self.alice, 'other-existing')
        before = self.count('platform_accounts')
        # This is the disposable fixture's generated credential, never live data.
        bootstrap = self.private/'admin-bootstrap.json'
        original = bootstrap.read_bytes()
        for restart in (False, True):
            with self.subTest(restart=restart):
                if restart:
                    self.bridge._stores.clear()
                    self.bridge._owners.clear()
                profile = self.local_identity()
                self.assertTrue(profile['local_mode'])
                self.assertEqual(self.admin['id'], profile['user']['id'])
                self.assertEqual(200, self.local.get('/api/jobs/desktop-existing').status_code)
                self.assertEqual(200, self.local.get('/api/media/desktop-existing/0.txt').status_code)
                self.assertEqual(404, self.local.get('/api/jobs/other-existing').status_code)
                self.assertEqual(before, self.count('platform_accounts'))
                self.assertEqual(original, bootstrap.read_bytes())
        self.network_get.assert_not_called()
        self.network_post.assert_not_called()

    def test_missing_stale_and_other_account_cookie_recover_same_owner(self):
        before = self.count('platform_accounts')
        other_session = self.store.create_session(self.alice['id'])
        for cookie in (None, 'expired-synthetic-cookie', other_session['token']):
            with self.subTest(cookie='missing' if cookie is None else 'present'):
                client = self.local_client('http://localhost:8770')
                if cookie:
                    client.cookies.set(platform_api.COOKIE, cookie)
                profile = self.local_identity(client)
                self.assertTrue(profile['local_mode'])
                self.assertEqual(self.admin['id'], profile['user']['id'])
                self.assertEqual(before, self.count('platform_accounts'))

    def test_default_still_requires_loopback_peer_and_host(self):
        for origin, peer in ((fixture.ORIGIN, '192.0.2.55'),
                             ('http://external.example', '127.0.0.1')):
            with self.subTest(origin=origin, peer=peer):
                response = self.local_client(origin, peer).get('/api/account/me', headers={
                    'X-Forwarded-For':'127.0.0.1', 'X-Forwarded-Host':'localhost'})
                self.assertEqual(401, response.status_code, response.text)
                self.assertIs(False, response.json()['local_mode'])
                self.assertNotIn('set-cookie', response.headers)
        self.job_fixture(self.admin, 'owner-only')
        self.job_fixture(self.alice, 'alice-only')
        self.assertEqual(self.alice['id'], self.client.get('/api/account/me').json()['user']['id'])
        self.assertEqual(200, self.client.get('/api/jobs/alice-only').status_code)
        self.assertEqual(404, self.client.get('/api/jobs/owner-only').status_code)

    def test_explicit_disable_and_cloud_flags_keep_session_authentication(self):
        for configuration in ({'YINGXU_LOCAL_MODE':'0'},
                              {'RAILWAY_ENVIRONMENT_ID':'fixture-cloud'},
                              {'RAILWAY_PUBLIC_DOMAIN':'fixture.up.railway.app'}):
            with self.subTest(configuration=configuration), patch.dict(os.environ, configuration):
                response = self.local_client().get('/api/account/me')
                self.assertEqual(401, response.status_code, response.text)
                self.assertIs(False, response.json()['local_mode'])
                self.assertNotIn('set-cookie', response.headers)

    def test_default_local_mode_does_not_expose_account_or_payment_actions(self):
        self.local_identity()
        before = {table:self.count(table) for table in (
            'platform_accounts', 'platform_orders', 'platform_ledger')}
        for path in ('/api/account/login', '/api/account/register', '/api/account/logout',
                     '/api/account/password', '/api/account/orders', '/api/payments/webhooks/wechat'):
            with self.subTest(path=path):
                response = self.local.post(path, json={})
                self.assertEqual(404, response.status_code, response.text)
        self.assertEqual(before, {table:self.count(table) for table in before})
        self.network_post.assert_not_called()

    def test_default_local_mode_retains_csrf_origin_and_account_checks(self):
        response = self.local.post('/api/jobs', json={}, headers={'Origin':fixture.ORIGIN})
        self.assertEqual(409, response.status_code, response.text)
        self.local_identity()
        for headers in ({'X-CSRF-Token':''}, {'Origin':'https://evil.example'},
                        {'X-Platform-Account':self.alice['id']}):
            with self.subTest(headers=list(headers)):
                response = self.local.post('/api/jobs', json={}, headers=headers)
                self.assertIn(response.status_code, (403, 409), response.text)
        self.assertEqual(0, self.count('jobs'))
        self.network_post.assert_not_called()

    def test_local_baidu_quote_submit_and_replay_keep_owner_without_platform_debits(self):
        profile = self.local_identity()
        before = self.store.account(self.admin['id'])
        for model in ('baidu-sd2', 'baidu-sd2.5'):
            with self.subTest(model=model):
                parameters = {'model':model, 'kind':'video', 'quality':'480p', 'count':1, 'duration':4}
                quote = {**parameters, 'mode':'charge', 'configured':True, 'available':True,
                         'credits':24, 'amount_minor':24, 'currency':'CNY'}
                with patch('platform_api.creation_quote', return_value=quote), \
                        patch('baidu_video.submit', return_value='synthetic-'+model) as provider:
                    response = self.local.post('/api/account/creation-quote', json=parameters)
                    self.assertEqual(200, response.status_code, response.text)
                    self.assertEqual(24, response.json()['amount_minor'])
                    self.assertEqual('no-store', response.headers['cache-control'])
                    provider.assert_not_called()
                    payload = {**parameters, 'ratio':'16:9', 'mode':'text',
                               'prompt':'isolated scene', 'token':'local-quoted-'+model}
                    headers = {'X-Expected-Credits':str(response.json()['credits'])}
                    first = self.local.post('/api/creation/jobs', json=payload, headers=headers)
                    self.assertEqual(200, first.status_code, first.text)
                    repeated = self.local.post('/api/creation/jobs', json=payload, headers=headers)
                    self.assertEqual(200, repeated.status_code, repeated.text)
                    self.assertEqual(first.json()['id'], repeated.json()['id'])
                    self.assertEqual(1, provider.call_count)
                    record = self.backend.job(first.json()['id'])
                    self.assertEqual(profile['user']['id'], record['owner_id'])
                    self.assertTrue(record['local_mode'])
                    self.assertEqual(24, record['quote_amount_minor'])
                    self.assertNotIn('credit_cost', record)
                    self.assertEqual(404, self.client.get('/api/jobs/'+record['id']).status_code)
                    foreign_rerun = self.client.post('/api/jobs/'+record['id']+'/rerun',
                        json={'token':'foreign-rerun-'+model}, headers={'X-Expected-Credits':'24'})
                    self.assertEqual(404, foreign_rerun.status_code, foreign_rerun.text)
                    self.assertEqual(1, provider.call_count)
        self.assertEqual(before, self.store.account(self.admin['id']))
        self.assertEqual(0, self.count('platform_reservations'))
        self.assertEqual(0, self.count('platform_ledger'))
        self.network_get.assert_not_called()
        self.network_post.assert_not_called()

    def test_local_provider_quote_still_requires_owner_session_origin_and_csrf(self):
        parameters = {'model':'baidu-sd2', 'kind':'video', 'quality':'480p', 'count':1, 'duration':4}
        with patch('platform_api.creation_quote') as quote, patch('baidu_video.submit') as provider:
            response = self.local.post('/api/account/creation-quote', json=parameters,
                                       headers={'Origin':fixture.ORIGIN})
            self.assertEqual(409, response.status_code, response.text)
            self.local_identity()
            for headers, status in (({'X-CSRF-Token':''}, 403),
                                    ({'Origin':'https://evil.example'}, 403),
                                    ({'X-Platform-Account':self.alice['id']}, 409)):
                response = self.local.post('/api/account/creation-quote', json=parameters, headers=headers)
                self.assertEqual(status, response.status_code, response.text)
            quote.assert_not_called()
            provider.assert_not_called()
        self.assertEqual(0, self.count('jobs'))

    def test_local_baidu_changed_quotes_stop_before_provider_dispatch_and_persistence(self):
        self.local_identity()
        parameters = {'model':'baidu-sd2', 'kind':'video', 'quality':'480p', 'count':1, 'duration':4}
        quote = {**parameters, 'mode':'charge', 'configured':True, 'available':True,
                 'credits':24, 'amount_minor':24, 'currency':'CNY'}
        changed = {**quote, 'credits':25, 'amount_minor':25}
        payload = {**parameters, 'ratio':'16:9', 'mode':'text',
                   'prompt':'isolated scene', 'token':'local-price-change'}
        with patch('platform_api.creation_quote', return_value=quote) as pricing, \
                patch('baidu_video.submit') as provider:
            displayed = self.local.post('/api/account/creation-quote', json=parameters)
            self.assertEqual(200, displayed.status_code, displayed.text)
            # Reject a missing acknowledgement, a stale displayed quote, and a
            # price change between validation and durable job creation.
            for quotes, headers in (([quote], {}), ([changed], {'X-Expected-Credits':'24'}),
                                    ([quote, changed], {'X-Expected-Credits':'24'})):
                with self.subTest(quotes=len(quotes), headers=bool(headers)):
                    pricing.side_effect = quotes
                    response = self.local.post('/api/creation/jobs', json=payload, headers=headers)
                    self.assertEqual(409, response.status_code, response.text)
                    self.assertEqual(0, self.count('jobs'))
                    self.assertEqual(0, self.count('platform_reservations'))
                    self.assertEqual(0, self.count('platform_ledger'))
            provider.assert_not_called()
        self.network_get.assert_not_called()
        self.network_post.assert_not_called()


if __name__ == '__main__':
    main()
