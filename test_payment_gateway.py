"""Real RSA/AES verification with synthetic keys; no payment network calls."""
import base64
import json
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from payment_gateway import PaymentError, PaymentGateway, _canonical


class PaymentGatewayContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.merchant_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.provider_public=cls.provider_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        cls.merchant_private=cls.merchant_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()

    def setUp(self):
        self.now=1_700_000_000
        self.env={'YINGXU_ALIPAY_APP_ID':'test-app','YINGXU_ALIPAY_SELLER_ID':'test-seller',
            'YINGXU_ALIPAY_PUBLIC_KEY_PEM':self.provider_public,'YINGXU_ALIPAY_PRIVATE_KEY_PEM':self.merchant_private,
            'YINGXU_ALIPAY_NOTIFY_URL':'https://studio.example/api/payments/alipay/notify',
            'YINGXU_WECHAT_APP_ID':'test-wx-app','YINGXU_WECHAT_MCH_ID':'test-mch',
            'YINGXU_WECHAT_API_V3_KEY':'01234567890123456789012345678901',
            'YINGXU_WECHAT_PLATFORM_SERIAL':'PUB_KEY_ID_TEST','YINGXU_WECHAT_PLATFORM_PUBLIC_KEY_PEM':self.provider_public,
            'YINGXU_WECHAT_PRIVATE_KEY_PEM':self.merchant_private,'YINGXU_WECHAT_MERCHANT_SERIAL':'TEST_MERCHANT_SERIAL',
            'YINGXU_WECHAT_NOTIFY_URL':'https://studio.example/api/payments/wechat/notify'}
        self.http=SimpleNamespace(post=Mock(side_effect=AssertionError('No live payment call')))
        self.gateway=PaymentGateway(self.env,http=self.http,clock=lambda:self.now)
        self.order={'id':'0123456789abcdef0123456789abcdef','method':'alipay','amount_minor':2900,'currency':'CNY','credits':290}

    def sign(self,message):
        return base64.b64encode(self.provider_key.sign(message,padding.PKCS1v15(),hashes.SHA256())).decode()

    def alipay(self,**values):
        form={'app_id':'test-app','seller_id':'test-seller','out_trade_no':self.order['id'],
              'trade_no':'alipay-transaction-001','total_amount':'29.00','trade_status':'TRADE_SUCCESS',
              'notify_type':'trade_status_sync','charset':'utf-8','sign_type':'RSA2',**values}
        form['sign']=self.sign(_canonical(form,callback=True))
        return form

    def wechat(self,transaction=None,*,timestamp=None):
        value={'appid':'test-wx-app','mchid':'test-mch','out_trade_no':self.order['id'],
            'transaction_id':'wx-transaction-001','trade_state':'SUCCESS','amount':{'total':2900,'currency':'CNY'}}
        if transaction:value.update(transaction)
        plaintext=json.dumps(value,separators=(',',':')).encode()
        nonce=b'test-nonce12';associated=b'transaction'
        encrypted=AESGCM(self.env['YINGXU_WECHAT_API_V3_KEY'].encode()).encrypt(nonce,plaintext,associated)
        envelope={'id':'test-notification','event_type':'TRANSACTION.SUCCESS','resource_type':'encrypt-resource',
            'resource':{'algorithm':'AEAD_AES_256_GCM','nonce':nonce.decode(),'associated_data':associated.decode(),
                        'ciphertext':base64.b64encode(encrypted).decode()}}
        raw=json.dumps(envelope,separators=(',',':')).encode()
        return self.wechat_headers(raw,timestamp=timestamp),raw

    def wechat_headers(self,raw,*,timestamp=None):
        timestamp=str(self.now if timestamp is None else timestamp);nonce='header-nonce'
        return {'Wechatpay-Timestamp':timestamp,'Wechatpay-Nonce':nonce,'Wechatpay-Serial':'PUB_KEY_ID_TEST',
                'Wechatpay-Signature':self.sign(timestamp.encode()+b'\n'+nonce.encode()+b'\n'+raw+b'\n')}

    def test_unconfigured_methods_are_disabled_and_never_create_fake_checkout(self):
        gateway=PaymentGateway({},http=self.http)
        for method in ('alipay','wechat','bank'):
            with self.subTest(method=method):
                self.assertFalse(gateway.enabled(method))
                with self.assertRaises(PaymentError):gateway.create_checkout({**self.order,'method':method})
        self.assertTrue(gateway.enabled('admin_contact'))
        self.http.post.assert_not_called()

    def test_incomplete_or_invalid_keys_disable_automatic_channels(self):
        for key in ('YINGXU_ALIPAY_SELLER_ID','YINGXU_ALIPAY_PRIVATE_KEY_PEM','YINGXU_ALIPAY_NOTIFY_URL'):
            gateway=PaymentGateway({**self.env,key:''},http=self.http)
            self.assertFalse(gateway.enabled('alipay'))
        self.assertFalse(PaymentGateway({**self.env,'YINGXU_WECHAT_API_V3_KEY':'bad'}).enabled('wechat'))
        self.assertFalse(PaymentGateway({**self.env,'YINGXU_ALIPAY_PUBLIC_KEY_PEM':'not-a-key'}).enabled('alipay'))

    def test_alipay_valid_signature_and_order_produce_only_payment_evidence(self):
        proof=self.gateway.verify_alipay(self.alipay(),self.order)
        self.assertEqual(proof,{'provider':'alipay','id':self.order['id'],'amount_minor':2900,'currency':'CNY','transaction_id':'alipay-transaction-001'})
        self.http.post.assert_not_called()

    def test_alipay_unsigned_tampering_is_rejected(self):
        form=self.alipay();form['total_amount']='0.01'
        with self.assertRaises(PaymentError):self.gateway.verify_alipay(form,self.order)

    def test_alipay_signed_amount_order_merchant_and_status_mismatch_are_rejected(self):
        for values in ({'total_amount':'28.99'},{'out_trade_no':'another-order'}, {'seller_id':'another-seller'},
                       {'app_id':'another-app'},{'trade_status':'WAIT_BUYER_PAY'},{'currency':'USD'},
                       {'notify_type':'browser_return'},{'total_amount':'29.001'}):
            with self.subTest(values=values),self.assertRaises(PaymentError):
                self.gateway.verify_alipay(self.alipay(**values),self.order)

    def test_alipay_duplicate_fields_and_browser_success_are_rejected(self):
        form=self.alipay()
        with self.assertRaises(PaymentError):self.gateway.verify_alipay([*form.items(),('total_amount','0.01')],self.order)
        with self.assertRaises(PaymentError):self.gateway.verify_alipay({'success':'true','id':self.order['id']},self.order)

    def test_signed_retries_keep_the_same_transaction_identity_for_ledger_deduplication(self):
        first=self.gateway.verify_alipay(self.alipay(),self.order)
        second=self.gateway.verify_alipay(self.alipay(trade_status='TRADE_FINISHED'),self.order)
        self.assertEqual(first,second)
        # The gateway has no wallet side effects. The ledger owns the unique
        # (provider, transaction_id) and atomic, once-only account increment.
        self.http.post.assert_not_called()

    def test_wechat_rsa_and_aes_notification_matches_saved_order(self):
        headers,raw=self.wechat()
        proof=self.gateway.verify_wechat(headers,raw,{**self.order,'method':'wechat'})
        self.assertEqual(proof,{'provider':'wechat','id':self.order['id'],'amount_minor':2900,'currency':'CNY','transaction_id':'wx-transaction-001'})

    def test_wechat_wrong_signature_unknown_serial_and_stale_timestamp_are_rejected(self):
        headers,raw=self.wechat()
        for current,current_raw in ((headers,raw+b' '),({**headers,'Wechatpay-Serial':'untrusted'},raw),
            ({**headers,'Wechatpay-Signature':'WECHATPAY/SIGNTEST/invalid'},raw)):
            with self.subTest(headers=current),self.assertRaises(PaymentError):self.gateway.verify_wechat(current,current_raw)
        stale_headers,stale_raw=self.wechat(timestamp=self.now-301)
        with self.assertRaises(PaymentError):self.gateway.verify_wechat(stale_headers,stale_raw)

    def test_wechat_signed_wrong_merchant_amount_currency_or_order_are_rejected(self):
        for transaction in ({'mchid':'other'},{'appid':'other'}, {'amount':{'total':1,'currency':'CNY'}},
            {'amount':{'total':2900,'currency':'USD'}},{'amount':{'total':True,'currency':'CNY'}},
            {'out_trade_no':'wrong-order'},{'trade_state':'CLOSED'}):
            headers,raw=self.wechat(transaction)
            with self.subTest(transaction=transaction),self.assertRaises(PaymentError):
                self.gateway.verify_wechat(headers,raw,{**self.order,'method':'wechat'})

    def test_wechat_signed_resource_with_wrong_authentication_tag_is_rejected(self):
        headers,raw=self.wechat()
        envelope=json.loads(raw)
        ciphertext=bytearray(base64.b64decode(envelope['resource']['ciphertext']))
        ciphertext[-1]^=1
        envelope['resource']['ciphertext']=base64.b64encode(ciphertext).decode()
        raw=json.dumps(envelope).encode()
        with self.assertRaises(PaymentError):self.gateway.verify_wechat(self.wechat_headers(raw),raw)

    def test_wechat_replay_returns_identical_evidence_without_credit_side_effect(self):
        headers,raw=self.wechat()
        self.assertEqual(self.gateway.verify_wechat(headers,raw),self.gateway.verify_wechat(headers,raw))
        self.http.post.assert_not_called()

    def test_manual_bank_and_admin_contact_never_claim_payment_success(self):
        gateway=PaymentGateway({**self.env,'YINGXU_BANK_ACCOUNT_NAME':'测试收款方','YINGXU_BANK_ACCOUNT_NUMBER':'TEST-ONLY-ACCOUNT','YINGXU_BANK_NAME':'测试银行'},http=self.http)
        for method in ('bank','admin_contact'):
            checkout=gateway.create_checkout({**self.order,'method':method})
            self.assertEqual(checkout['mode'],'manual')
            self.assertNotIn('paid',checkout)
        self.http.post.assert_not_called()

    def test_alipay_checkout_signs_request_and_verifies_original_response_bytes(self):
        response_value={'code':'10000','msg':'Success','out_trade_no':self.order['id'],'qr_code':'https://qr.alipay.example/synthetic'}
        signed=json.dumps(response_value,ensure_ascii=False,indent=1).encode()
        raw=b'{"alipay_trade_precreate_response":'+signed+b',"sign":'+json.dumps(self.sign(signed)).encode()+b'}'
        def reply(url,**kwargs):
            self.assertEqual(url,'https://openapi.alipay.com/gateway.do')
            params=kwargs['data']
            self.merchant_key.public_key().verify(base64.b64decode(params['sign']),_canonical(params),padding.PKCS1v15(),hashes.SHA256())
            self.assertEqual(json.loads(params['biz_content'])['total_amount'],'29.00')
            return SimpleNamespace(status_code=200,content=raw)
        self.http.post=Mock(side_effect=reply)
        checkout=self.gateway.create_checkout(self.order)
        self.assertEqual(checkout['qr_code'],response_value['qr_code'])
        self.assertEqual(checkout['mode'],'automatic')
        self.assertEqual(checkout['checkout_reference'],self.order['id'])

    def test_untrusted_alipay_checkout_response_is_not_shown(self):
        raw=json.dumps({'alipay_trade_precreate_response':{'code':'10000','out_trade_no':self.order['id'],'qr_code':'unsafe'},'sign':'invalid'}).encode()
        self.http.post=Mock(return_value=SimpleNamespace(status_code=200,content=raw))
        with self.assertRaises(PaymentError):self.gateway.create_checkout(self.order)

    def test_wechat_native_checkout_signs_exact_request_and_verifies_response(self):
        raw=b'{"code_url":"weixin://wxpay/bizpayurl?pr=synthetic"}'
        def reply(url,**kwargs):
            self.assertEqual(url,'https://api.mch.weixin.qq.com/v3/pay/transactions/native')
            self.assertEqual(json.loads(kwargs['data'])['amount'],{'total':2900,'currency':'CNY'})
            self.assertIn('WECHATPAY2-SHA256-RSA2048',kwargs['headers']['Authorization'])
            fields=dict(re.findall(r'([a-z_]+)="([^"]*)"',kwargs['headers']['Authorization']))
            signed=b'POST\n/v3/pay/transactions/native\n'+fields['timestamp'].encode()+b'\n'+fields['nonce_str'].encode()+b'\n'+kwargs['data']+b'\n'
            self.merchant_key.public_key().verify(base64.b64decode(fields['signature']),signed,padding.PKCS1v15(),hashes.SHA256())
            return SimpleNamespace(status_code=200,content=raw,headers=self.wechat_headers(raw))
        self.http.post=Mock(side_effect=reply)
        checkout=self.gateway.create_checkout({**self.order,'method':'wechat'})
        self.assertTrue(checkout['qr_code'].startswith('weixin://'))
        self.assertEqual(checkout['expires_at'],(self.now+900)*1000)

    def test_bank_and_automatic_orders_reject_invalid_snapshot_before_network(self):
        for patch in ({'amount_minor':29.5},{'amount_minor':True},{'amount_minor':0},{'currency':'USD'},{'id':'bad'}):
            with self.subTest(patch=patch),self.assertRaises(PaymentError):self.gateway.create_checkout({**self.order,**patch})
        self.http.post.assert_not_called()


if __name__=='__main__':unittest.main()
