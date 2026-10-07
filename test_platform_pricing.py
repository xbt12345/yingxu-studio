"""Pure reference-pricing tests; no accounts, network or private state."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from platform_pricing import (CREDIT_POLICY, POLICY_PATH, PricingValidationError,
                              creation_quote, enrich_workflow_quote, load_pricing_policy)


class PlatformPricing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='yingxu-reference-pricing-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'policy.json'
        self.raw = json.loads(POLICY_PATH.read_text(encoding='utf-8'))

    def policy(self, raw=None):
        self.path.write_text(json.dumps(self.raw if raw is None else raw), encoding='utf-8')
        return load_pricing_policy(self.path)

    def quote(self, **changes):
        values = {'model': 'seedream-4.5', 'kind': 'image', 'quality': '2K', 'count': 1, 'duration': None}
        return creation_quote(**{**values, **changes}, policy=self.policy())

    def test_published_image_tariff_counts_output_images(self):
        one = self.quote()
        eight = self.quote(count=8)
        self.assertEqual((25, 25), (one['amount_minor'], one['credits']))
        self.assertEqual((200, 200), (eight['amount_minor'], eight['credits']))
        self.assertEqual('reference', one['mode'])
        self.assertFalse(one['available'])
        self.assertTrue(one['availability_reason'])
        self.assertEqual(CREDIT_POLICY, one['credit_policy'])
        self.assertEqual(('CNY', True), (one['currency'], one['configured']))

    def test_video_rounds_total_to_fen_once_instead_of_each_second(self):
        for quality, expected in [('480p', 370), ('720p', 796), ('1080p', 1984)]:
            with self.subTest(quality=quality):
                quoted = self.quote(model='seedance-2.0', kind='video', quality=quality, duration=4)
                self.assertEqual((expected, expected), (quoted['amount_minor'], quoted['credits']))
                self.assertEqual(4, quoted['duration'])
        self.assertEqual(4958, self.quote(model='seedance-2.0', kind='video', quality='1080p', duration=10)['credits'])

    def test_unconfigured_and_unknown_models_never_look_free(self):
        self.raw['creation_pricing']['models']['flux-2-pro'] = {'kind':'image','configured':False,'reason':'fixture 未定价'}
        for model in ('flux-2-pro', 'future-model'):
            with self.subTest(model=model):
                quoted = self.quote(model=model)
                self.assertFalse(quoted['configured'])
                self.assertIsNone(quoted['credits'])
                self.assertIsNone(quoted['amount_minor'])
                self.assertTrue(quoted['reason'])

    def test_image_quality_tariff_rounds_the_whole_batch_only_once(self):
        for quality,count,expected in [('1K',1,21),('1K',8,162),('1.5K',8,324),('2K',8,405)]:
            with self.subTest(quality=quality,count=count):
                quoted = self.quote(model='flux-2-pro',quality=quality,count=count)
                self.assertEqual((True,expected,expected),tuple(quoted[key] for key in ('configured','credits','amount_minor')))

    def test_veo_supported_quality_has_price_and_unpriced_quality_stays_pending(self):
        for quality,duration,expected in [('720p',4,1078),('1080p',8,2156)]:
            with self.subTest(quality=quality,duration=duration):
                quoted = self.quote(model='veo-3.1',kind='video',quality=quality,duration=duration)
                self.assertTrue(quoted['configured'])
                self.assertEqual(expected,quoted['credits'])
        pending = self.quote(model='veo-3.1',kind='video',quality='480p',duration=8)
        self.assertFalse(pending['configured'])
        self.assertIsNone(pending['credits'])
        self.assertIsNone(pending['amount_minor'])
        self.assertTrue(pending['reason'])

    def test_model_type_quality_and_control_invariants(self):
        invalid = [{'kind': 'video', 'quality': '720p', 'duration': 8},
                   {'quality': '4K'}, {'duration': 8}, {'count': True}, {'count': 0},
                   {'count': 9}, {'count': '2'},
                   {'model': 'seedance-2.0', 'kind': 'video', 'quality': '720p', 'count': 2, 'duration': 8},
                   {'model': 'seedance-2.0', 'kind': 'video', 'quality': '720p', 'duration': 8.0},
                   {'model': 'seedance-2.0', 'kind': 'video', 'quality': '720p', 'duration': None},
                   {'model': 'veo-3.1', 'kind': 'video', 'quality': '720p', 'duration': 5}]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(PricingValidationError):
                self.quote(**changes)

    def test_missing_malformed_and_oversize_policy_fail_closed(self):
        for content in (None, '{', '[]', '"invalid"', ' ' * 256_001):
            with self.subTest(content=None if content is None else content[:15]):
                if content is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.path.write_text(content, encoding='utf-8')
                policy = load_pricing_policy(self.path)
                self.assertEqual(CREDIT_POLICY, policy['credit_policy'])
                self.assertTrue(all(not model['configured'] for model in policy['creation_pricing']['models'].values()))

    def test_exchange_configuration_cannot_change_confirmed_unit(self):
        for credit in ({'currency': 'USD', 'credits_per_yuan': 100, 'rounding': 'ceil_to_fen'},
                       {'currency': 'CNY', 'credits_per_yuan': '100', 'rounding': 'ceil_to_fen'},
                       {'currency': 'CNY', 'credits_per_yuan': 10, 'rounding': 'ceil_to_fen'}):
            with self.subTest(credit=credit):
                raw = {**self.raw, 'credit_policy': credit}
                policy = self.policy(raw)
                self.assertEqual(CREDIT_POLICY, policy['credit_policy'])
                self.assertFalse(policy['creation_pricing']['models']['seedream-4.5']['configured'])

    def test_bad_unit_prices_do_not_escape_or_turn_into_zero(self):
        for value in (True, 0, -1, 'NaN', 'Infinity', '1e9999', {}, None):
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw['creation_pricing']['models']['seedance-2.0']['quality_amount_minor']['480p'] = value
                model = self.policy(raw)['creation_pricing']['models']['seedance-2.0']
                self.assertFalse(model['configured'])
                self.assertNotIn('quality_amount_minor', model)

    def test_only_public_whitelisted_fields_are_exposed(self):
        raw = copy.deepcopy(self.raw)
        raw['private_key'] = 'secret top-level'
        raw['creation_pricing']['models']['seedream-4.5']['api_key'] = 'secret per-model'
        raw['creation_pricing']['models']['secret-model'] = {'api_key': 'other secret'}
        raw['creation_pricing']['models']['seedream-4.5']['source_url'] = 'https://user:password@example.com/rates'
        policy = self.policy(raw)
        serialized = json.dumps(policy)
        self.assertNotIn('secret', serialized)
        self.assertNotIn('password', serialized)
        self.assertEqual({'credit_policy', 'creation_pricing'}, set(policy))
        self.assertNotIn('source_url', policy['creation_pricing']['models']['seedream-4.5'])

    def test_published_tariffs_cannot_claim_a_model_is_connected(self):
        for model in self.raw['creation_pricing']['models'].values():
            model['available'] = True
            model['generation_endpoint'] = '/pretend-generation'
        policy = self.policy()
        for model in policy['creation_pricing']['models'].values():
            self.assertFalse(model['available'])
            self.assertNotIn('generation_endpoint', model)
            self.assertTrue(model['availability_reason'])
        for model, kind, quality, duration in [('seedream-4.5','image','2K',None),
                                               ('seedance-2.0','video','720p',8)]:
            quote = creation_quote(model,kind,quality,1,duration,policy)
            self.assertTrue(quote['configured'])
            self.assertFalse(quote['available'])

    def test_configured_video_duration_range_is_enforced(self):
        raw = copy.deepcopy(self.raw)
        raw['creation_pricing']['models']['seedance-2.0']['durations'] = {'min': 8, 'max': 10}
        policy = self.policy(raw)
        with self.assertRaises(PricingValidationError):
            creation_quote('seedance-2.0', 'video', '720p', 1, 4, policy)
        self.assertTrue(creation_quote('seedance-2.0', 'video', '720p', 1, 8, policy)['configured'])

    def test_workflow_quote_preserves_original_contract_and_unknown_status(self):
        original = {'workflow_id': 'known', 'configured': True, 'credits': 14}
        enriched = enrich_workflow_quote(original, self.policy())
        self.assertEqual(14, enriched['amount_minor'])
        self.assertEqual(original, {key: enriched[key] for key in original})
        self.assertNotIn('amount_minor', enrich_workflow_quote({'workflow_id': 'unknown', 'configured': False, 'credits': None}, self.policy()))
        self.assertNotIn('amount_minor', original)


if __name__ == '__main__':
    unittest.main()
