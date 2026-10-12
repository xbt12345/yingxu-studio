"""Portable Baidu client contracts using synthetic credentials and HTTP only."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch

import requests

# Importing configuration must not load an owner's .env during this test.
with patch('dotenv.load_dotenv', return_value=False):
    import baidu_video


ENDPOINT = 'https://vod.bj.baidubce.com/v3/aigc/seedance/api/v3/contents/generations/tasks'
UPSTREAM = {
    'baidu-sd2': 'doubao-seedance-2-0-260128',
    'baidu-sd2.5': 'doubao-seedance-2-5-260628',
}
KEY = 'synthetic-contract-key'
RAW_MESSAGE = 'private-provider-message-with-synthetic-credential'
IMAGE = 'data:image/png;base64,aW1hZ2U='


class BaiduVideoContracts(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='yingxu-baidu-contract-')
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / 'missing-baidu-video.json'
        self.start_patch(patch.object(baidu_video, '_CONFIG_PATH', self.config))
        self.start_patch(patch.dict(os.environ, {
            'BAIDU_VOD_API_KEY': KEY,
            'BCE_ACCESS_KEY': '',
            'BCE_SECRET_KEY': '',
        }))
        self.http = self.start_patch(patch('baidu_video.requests.request',
            side_effect=AssertionError('A test attempted an unconfigured HTTP request.')))

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def respond(self, data=None, status=200, error=None):
        response = Mock(status_code=status)
        response.json = Mock(side_effect=error) if error else Mock(return_value=data)
        self.http.side_effect = None
        self.http.return_value = response
        self.http.reset_mock()
        return response

    @staticmethod
    def draft(model='baidu-sd2', **changes):
        return {'model': model, 'prompt': '  synthetic scene  ', 'duration': 4,
                'quality': '480p', 'mode': 'text', 'ratio': '16:9', **changes}

    def assert_safe_error(self, error):
        self.assertNotIn(RAW_MESSAGE, str(error))
        self.assertNotIn(KEY, str(error))
        self.assertIsNone(getattr(error, 'request', None))
        self.assertIsNone(getattr(error, 'response', None))

    def test_environment_key_works_without_private_configuration_or_http(self):
        os.environ['BAIDU_VOD_API_KEY'] = '  Bearer ' + KEY + '  '
        self.assertFalse(self.config.exists())
        for model in UPSTREAM:
            with self.subTest(model=model):
                self.assertEqual({'available': True, 'availability_reason': ''},
                                 baidu_video.model_availability(model))
        self.http.assert_not_called()
        self.assertFalse(self.config.exists())

    def test_ak_sk_never_replace_a_missing_bearer_key(self):
        os.environ['BAIDU_VOD_API_KEY'] = ''
        os.environ['BCE_ACCESS_KEY'] = 'synthetic-ak'
        os.environ['BCE_SECRET_KEY'] = 'synthetic-sk'
        self.assertFalse(baidu_video.model_availability('baidu-sd2')['available'])
        with self.assertRaises(baidu_video.BaiduVideoError):
            baidu_video.submit(baidu_video.build_payload(self.draft()))
        self.http.assert_not_called()

    def test_malformed_bearer_credentials_never_reach_http(self):
        for key in ('', KEY + '\r\ninjected-header: true'):
            with self.subTest(key_kind='empty' if not key else 'newline'):
                os.environ['BAIDU_VOD_API_KEY'] = key
                self.assertFalse(baidu_video.model_availability('baidu-sd2.5')['available'])
                with self.assertRaises(baidu_video.BaiduVideoError) as caught:
                    baidu_video.submit(baidu_video.build_payload(self.draft()))
                self.assert_safe_error(caught.exception)
        self.http.assert_not_called()

    def test_both_text_payloads_use_exact_upstream_models_and_no_image_roles(self):
        for model, upstream in UPSTREAM.items():
            with self.subTest(model=model):
                payload = baidu_video.build_payload(self.draft(model))
                self.assertEqual({
                    'model': upstream,
                    'content': [{'type': 'text', 'text': 'synthetic scene'}],
                    'resolution': '480p', 'duration': 4,
                    'ratio': '16:9', 'generate_audio': True,
                }, payload)
                self.assertNotIn('api_key', payload)
        self.http.assert_not_called()

    def test_first_frame_payload_roles_and_sd25_adaptive_ratio(self):
        for model in UPSTREAM:
            with self.subTest(model=model):
                draft = self.draft(model, mode='first_frame')
                if model == 'baidu-sd2.5':
                    draft.pop('ratio')
                payload = baidu_video.build_payload(draft, [{'data_url': IMAGE, 'slot': 0}])
                self.assertEqual(UPSTREAM[model], payload['model'])
                self.assertEqual('adaptive' if model == 'baidu-sd2.5' else '16:9', payload['ratio'])
                self.assertEqual([
                    {'type': 'text', 'text': 'synthetic scene'},
                    {'type': 'image_url', 'image_url': {'url': IMAGE}, 'role': 'first_frame'},
                ], payload['content'])
        self.http.assert_not_called()

    def test_reference_images_keep_order_and_reference_role_for_both_models(self):
        urls = ['https://assets.example.test/one.png', 'https://assets.example.test/two.png']
        for model in UPSTREAM:
            with self.subTest(model=model):
                payload = baidu_video.build_payload(
                    self.draft(model, mode='reference_image', generate_audio=False, ratio='9:16'),
                    [{'url': url} for url in urls])
                self.assertEqual(UPSTREAM[model], payload['model'])
                self.assertEqual('9:16', payload['ratio'])
                self.assertIs(False, payload['generate_audio'])
                self.assertEqual([{'type': 'image_url', 'image_url': {'url': url},
                                   'role': 'reference_image'} for url in urls], payload['content'][1:])
        self.http.assert_not_called()

    def test_first_frame_adaptive_and_unsupported_pair_contracts_fail_before_http(self):
        cases = [
            (self.draft('baidu-sd2.5', mode='first_frame', ratio='16:9'), [{'url': 'https://example.test/a.png'}]),
            (self.draft('baidu-sd2', mode='first_frame', ratio='adaptive'), [{'url': 'https://example.test/a.png'}]),
            (self.draft(mode='first_frame'), [{'data_url': IMAGE, 'slot': 1}]),
            (self.draft(mode='last_frame'), [{'data_url': IMAGE}]),
            (self.draft(mode='first_last_frame'), [{'data_url': IMAGE}, {'data_url': IMAGE}]),
        ]
        for draft, references in cases:
            with self.subTest(model=draft['model'], mode=draft['mode'], ratio=draft['ratio']):
                with self.assertRaises(baidu_video.BaiduVideoError):
                    baidu_video.build_payload(draft, references)
        self.http.assert_not_called()

    def test_post_uses_bearer_timeout_no_redirect_and_submits_each_model_once(self):
        os.environ['BAIDU_VOD_API_KEY'] = '  bEaReR ' + KEY + '  '
        for model in UPSTREAM:
            with self.subTest(model=model):
                payload = baidu_video.build_payload(self.draft(model))
                self.respond({'id': 'synthetic-task_1'})
                self.assertEqual('synthetic-task_1', baidu_video.submit(payload))
                self.http.assert_called_once_with('POST', ENDPOINT,
                    headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'},
                    json=payload, timeout=(10, 90), allow_redirects=False)

    def test_get_uses_bearer_timeout_no_redirect_and_no_payload(self):
        self.respond({'status': 'queued'})
        self.assertEqual({'status': 'queued', 'video_url': None, 'error': None},
                         baidu_video.query('synthetic-task_1'))
        self.http.assert_called_once_with('GET', ENDPOINT + '/synthetic-task_1',
            headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'},
            json=None, timeout=(10, 90), allow_redirects=False)

    def test_transport_failures_remain_uncertain_without_retry_or_secret_context(self):
        for method in ('POST', 'GET'):
            with self.subTest(method=method):
                raw = requests.Timeout(RAW_MESSAGE + KEY,
                    request=requests.Request('POST', 'https://example.test',
                                             headers={'Authorization': KEY}).prepare())
                self.http.reset_mock()
                self.http.side_effect = raw
                with self.assertRaises(requests.RequestException) as caught:
                    if method == 'POST':
                        baidu_video.submit(baidu_video.build_payload(self.draft()))
                    else:
                        baidu_video.query('synthetic-task')
                self.assert_safe_error(caught.exception)
                self.assertNotIsInstance(caught.exception, baidu_video.BaiduVideoError)
                self.assertIn('尚待确认', str(caught.exception))
                self.http.assert_called_once()

    def test_http_failures_distinguish_rejection_from_uncertainty_and_hide_provider_messages(self):
        for method, status in (('POST', 400), ('POST', 403), ('POST', 429),
                               ('POST', 302), ('POST', 500), ('GET', 403), ('GET', 404)):
            with self.subTest(method=method, status=status):
                self.respond({'error': {'code': 'InvalidParameter', 'message': RAW_MESSAGE + KEY}}, status)
                expected = baidu_video.BaiduVideoError if method == 'POST' and 400 <= status < 500 else requests.HTTPError
                with self.assertRaises(expected) as caught:
                    if method == 'POST':
                        baidu_video.submit(baidu_video.build_payload(self.draft()))
                    else:
                        baidu_video.query('synthetic-task')
                self.assert_safe_error(caught.exception)
                self.assertIn('InvalidParameter', str(caught.exception))
                self.assertIn(str(status), str(caught.exception))
                self.http.assert_called_once()

    def test_untrusted_error_codes_are_not_echoed(self):
        self.respond({'error': {'code': '<script>' + RAW_MESSAGE, 'message': KEY}}, 400)
        with self.assertRaises(baidu_video.BaiduVideoError) as caught:
            baidu_video.submit(baidu_video.build_payload(self.draft()))
        self.assert_safe_error(caught.exception)
        self.assertNotIn('<script>', str(caught.exception))
        self.http.assert_called_once()

    def test_invalid_json_and_non_object_responses_do_not_trigger_resubmission(self):
        for method, status in (('POST', 200), ('POST', 400), ('GET', 200), ('GET', 404)):
            with self.subTest(method=method, status=status):
                self.respond(status=status, error=ValueError(RAW_MESSAGE))
                expected = baidu_video.BaiduVideoError if method == 'POST' and status == 400 else requests.RequestException
                with self.assertRaises(expected) as caught:
                    if method == 'POST':
                        baidu_video.submit(baidu_video.build_payload(self.draft()))
                    else:
                        baidu_video.query('synthetic-task')
                self.assert_safe_error(caught.exception)
                self.http.assert_called_once()
        self.respond([{'id': 'not-the-contract'}])
        with self.assertRaises(requests.RequestException):
            baidu_video.submit(baidu_video.build_payload(self.draft()))
        self.http.assert_called_once()

    def test_missing_or_invalid_submission_ids_remain_uncertain_without_retry(self):
        for task_id in (None, '', '../foreign-task', 123):
            with self.subTest(task_id=task_id):
                self.respond({'id': task_id})
                with self.assertRaises(requests.RequestException) as caught:
                    baidu_video.submit(baidu_video.build_payload(self.draft()))
                self.assertIn('尚待确认', str(caught.exception))
                self.http.assert_called_once()

    def test_query_maps_queued_running_done_and_terminal_failures(self):
        for upstream, expected in (('queued', 'queued'), ('running', 'running'),
                ('succeeded', 'done'), ('failed', 'failed'), ('expired', 'failed'), ('cancelled', 'failed')):
            with self.subTest(upstream=upstream):
                self.respond({'status': upstream, 'content': {'video_url': 'https://media.example.test/result.mp4'},
                              'error': {'message': RAW_MESSAGE + KEY}})
                result = baidu_video.query('synthetic-task')
                self.assertEqual(expected, result['status'])
                self.assertEqual('https://media.example.test/result.mp4' if expected == 'done' else None,
                                 result['video_url'])
                self.assertEqual(expected == 'failed', bool(result['error']))
                self.assertNotIn(RAW_MESSAGE, str(result))
                self.assertNotIn(KEY, str(result))
                self.http.assert_called_once()

    def test_query_unknown_status_or_missing_result_stays_uncertain(self):
        for response in ({'status': 'unknown'}, {'status': 'succeeded'},
                         {'status': 'succeeded', 'content': {'video_url': 'file:///untrusted.mp4'}}):
            with self.subTest(response=response):
                self.respond(response)
                with self.assertRaises(requests.RequestException):
                    baidu_video.query('synthetic-task')
                self.http.assert_called_once()

    def test_usage_keeps_only_numeric_documented_fields(self):
        self.respond({'status': 'running', 'usage': {'completion_tokens': 14,
            'total_tokens': 22, 'provider_message': RAW_MESSAGE, 'other_tokens': 4}})
        self.assertEqual({'completion_tokens': 14, 'total_tokens': 22},
                         baidu_video.query('synthetic-task')['usage'])
        self.respond({'status': 'running', 'usage': {'completion_tokens': True, 'total_tokens': '22'}})
        self.assertEqual({}, baidu_video.query('synthetic-task')['usage'])

    def test_invalid_query_ids_and_unknown_submit_models_never_reach_http(self):
        for task_id in ('../other', 'task?secret=1', '', None):
            with self.subTest(task_id=task_id), self.assertRaises(baidu_video.BaiduVideoError):
                baidu_video.query(task_id)
        with self.assertRaises(baidu_video.BaiduVideoError):
            baidu_video.submit({'model': 'unsupported-model'})
        self.http.assert_not_called()


if __name__ == '__main__':
    main()
