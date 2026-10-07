"""Trusted payment evidence; wallet changes belong to the transactional ledger.

Only Alipay RSA2 notifications and WeChat APIv3 signed/encrypted notifications
can produce automatic payment evidence. Browser redirects never credit money.
Protocol sources: official alipay/alipay-sdk-python-all SignatureUtils.py and
wechatpay-apiv3/wechatpay-php README callback verification example.
"""
import base64
import binascii
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

import requests

try:
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature, InvalidTag
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_AVAILABLE=True
except ImportError:
    CRYPTO_AVAILABLE=False


class PaymentError(ValueError):
    def __init__(self,code,message):
        super().__init__(message)
        self.code=code


def _fail(code='invalid_payment',message='支付通知验证失败。'):
    raise PaymentError(code,message)


def _text(value,maximum=256):
    if not isinstance(value,str) or not value or len(value)>maximum or '\x00' in value:_fail()
    return value


def _json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:_fail('ambiguous_payment','支付报文包含重复字段。')
            result[key]=value
        return result
    try:
        value=json.loads(raw,object_pairs_hook=unique)
        if not isinstance(value,dict):_fail()
        return value
    except (ValueError,UnicodeError,TypeError):_fail()


def _single_values(values,lower=False):
    pairs=values.multi_items() if hasattr(values,'multi_items') else values.items() if hasattr(values,'items') else values
    result={}
    try:
        for key,value in pairs:
            if not isinstance(key,str) or not isinstance(value,str):_fail()
            key=key.lower() if lower else key
            if key in result:_fail('ambiguous_payment','支付报文包含重复字段。')
            if len(key)>256 or len(value)>65536:_fail()
            result[key]=value
    except (TypeError,ValueError):_fail()
    return result


def _base64(value):
    try:return base64.b64decode(_text(value,262144),validate=True)
    except (binascii.Error,ValueError):_fail()


def _canonical(values,callback=False):
    excluded={'sign','sign_type'} if callback else {'sign'}
    return '&'.join(f'{key}={values[key]}' for key in sorted(values)
                    if key not in excluded and values[key]!='').encode('utf-8')


def _verify(key,signature,message):
    try:key.verify(_base64(signature),message,padding.PKCS1v15(),hashes.SHA256())
    except (InvalidSignature,ValueError,TypeError):_fail('invalid_signature','支付签名验证失败。')


def _minor(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,10}(?:\.[0-9]{1,2})?',value):_fail('invalid_amount','支付金额无效。')
    whole,_,fraction=value.partition('.')
    return int(whole)*100+int(fraction.ljust(2,'0') or '0')


def _order(order,provider=None):
    if not isinstance(order,dict):_fail('invalid_order','充值订单无效。')
    identifier=_text(order.get('id'),64)
    method=order.get('method',order.get('payment_method'))
    amount=order.get('amount_minor')
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,64}',identifier) or isinstance(amount,bool) or not isinstance(amount,int) or not 0<amount<=10_000_000_000:
        _fail('invalid_order','充值订单无效。')
    if order.get('currency')!='CNY' or provider and method!=provider:_fail('order_mismatch','支付渠道或币种与订单不一致。')
    return identifier,method,amount


def validate_order(payment,order):
    """Compare with the saved order; callers must not use a browser order body."""
    identifier,method,amount=_order(order,payment.get('provider'))
    if (payment.get('id')!=identifier or payment.get('amount_minor')!=amount
            or payment.get('currency')!=order['currency']):
        _fail('order_mismatch','支付金额或订单编号与充值订单不一致。')
    return payment


class PaymentGateway:
    def __init__(self,environ=None,*,http=None,clock=None):
        self.env=os.environ if environ is None else environ
        self.http=requests if http is None else http
        self.clock=time.time if clock is None else clock

    def _setting(self,name):
        value=self.env.get('YINGXU_'+name,'')
        return value.strip() if isinstance(value,str) else ''

    def _key(self,name,private=False):
        if not CRYPTO_AVAILABLE:return None
        pem=self._setting(name+'_PEM')
        path=self._setting(name+'_PATH')
        try:
            if not pem and path:
                source=Path(path)
                if source.stat().st_size>65536:return None
                pem=source.read_text('utf-8')
            if not pem:return None
            raw=pem.replace('\\n','\n').encode('utf-8')
            if private:key=serialization.load_pem_private_key(raw,password=None)
            elif b'BEGIN CERTIFICATE' in raw:key=x509.load_pem_x509_certificate(raw).public_key()
            else:key=serialization.load_pem_public_key(raw)
            if not isinstance(key,rsa.RSAPrivateKey if private else rsa.RSAPublicKey) or key.key_size<2048:return None
            return key
        except (OSError,ValueError,TypeError):return None

    def _notify_url(self,provider):
        url=self._setting(provider.upper()+'_NOTIFY_URL')
        try:
            parsed=urlsplit(url)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:return ''
            if parsed.hostname in ('localhost','127.0.0.1','::1'):return ''
            return url
        except ValueError:return ''

    def _verification_ready(self,provider):
        if provider=='alipay':
            return bool(self._setting('ALIPAY_APP_ID') and self._setting('ALIPAY_SELLER_ID') and self._key('ALIPAY_PUBLIC_KEY'))
        if provider=='wechat':
            return bool(self._setting('WECHAT_APP_ID') and self._setting('WECHAT_MCH_ID')
                        and len(self._setting('WECHAT_API_V3_KEY').encode('utf-8'))==32
                        and self._setting('WECHAT_PLATFORM_SERIAL') and self._key('WECHAT_PLATFORM_PUBLIC_KEY'))
        return False

    def enabled(self,provider):
        if provider in ('alipay','wechat'):
            return bool(self._verification_ready(provider) and self._notify_url(provider)
                        and self._key(provider.upper()+'_PRIVATE_KEY',private=True)
                        and (provider!='wechat' or self._setting('WECHAT_MERCHANT_SERIAL')))
        if provider=='bank':return all(self._setting(key) for key in ('BANK_ACCOUNT_NAME','BANK_ACCOUNT_NUMBER','BANK_NAME'))
        return provider=='admin_contact'

    def methods(self):
        labels={'alipay':'支付宝','wechat':'微信支付','bank':'银行卡转账','admin_contact':'联系管理员'}
        return [{'id':method,'method':method,'label':label,'enabled':self.enabled(method),
                 'automatic':method in ('alipay','wechat'),
                 'message':('支付渠道尚未配置，可联系管理员充值。' if not self.enabled(method)
                            else '收到支付平台验签通知后自动到账。' if method in ('alipay','wechat')
                            else '由管理员核对真实到账后入账。')}
                for method,label in labels.items()]

    available_methods=methods

    def create_checkout(self,order):
        identifier,provider,amount=_order(order)
        if not self.enabled(provider):_fail('payment_disabled','此支付渠道尚未配置，请联系管理员充值。')
        if provider in ('bank','admin_contact'):
            result={'provider':provider,'mode':'manual','checkout_reference':identifier,
                    'instructions':'请保留充值订单号。管理员核对实际到账后，积分才会入账。',
                    'contact':self._setting('RECHARGE_CONTACT')}
            if provider=='bank':result.update(account_name=self._setting('BANK_ACCOUNT_NAME'),account_number=self._setting('BANK_ACCOUNT_NUMBER'),bank_name=self._setting('BANK_NAME'))
            return result
        expires=self.clock()+900
        if provider=='alipay':
            key=self._key('ALIPAY_PRIVATE_KEY',private=True)
            params={'app_id':self._setting('ALIPAY_APP_ID'),'method':'alipay.trade.precreate','format':'JSON',
                    'charset':'utf-8','sign_type':'RSA2','version':'1.0',
                    'timestamp':datetime.fromtimestamp(self.clock(),timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),
                    'notify_url':self._notify_url(provider),
                    'biz_content':json.dumps({'out_trade_no':identifier,'total_amount':f'{amount//100}.{amount%100:02d}',
                        'subject':'映序积分充值','timeout_express':'15m'},ensure_ascii=False,separators=(',',':'))}
            params['sign']=base64.b64encode(key.sign(_canonical(params),padding.PKCS1v15(),hashes.SHA256())).decode('ascii')
            reply=self._post('https://openapi.alipay.com/gateway.do',data=params)
            raw=reply.content
            data=_json(raw)
            response=data.get('alipay_trade_precreate_response')
            # Alipay signs the original nested JSON, including its whitespace.
            try:
                text=raw.decode('utf-8')
                match=re.search(r'"alipay_trade_precreate_response"\s*:\s*',text)
                if not match:_fail()
                start=match.end()
                _,end=json.JSONDecoder().raw_decode(text[start:])
                signed=text[start:start+end].encode('utf-8')
                _verify(self._key('ALIPAY_PUBLIC_KEY'),data.get('sign'),signed)
            except (UnicodeError,ValueError,TypeError):_fail('invalid_signature','支付下单响应验证失败。')
            if not isinstance(response,dict) or response.get('code')!='10000':_fail('checkout_failed','支付宝未能创建收款订单，请稍后重试。')
            if response.get('out_trade_no')!=identifier:_fail('order_mismatch','支付下单响应与充值订单不一致。')
            qr=_text(response.get('qr_code'),2048)
        else:
            if len(identifier)>32:_fail('invalid_order','微信支付订单号超过允许长度。')
            endpoint='/v3/pay/transactions/native'
            body=json.dumps({'appid':self._setting('WECHAT_APP_ID'),'mchid':self._setting('WECHAT_MCH_ID'),
                'description':'映序积分充值','out_trade_no':identifier,'notify_url':self._notify_url(provider),
                'time_expire':datetime.fromtimestamp(expires,timezone.utc).isoformat(timespec='seconds'),
                'amount':{'total':amount,'currency':'CNY'}},ensure_ascii=False,separators=(',',':')).encode('utf-8')
            timestamp=str(int(self.clock()));nonce=secrets.token_hex(16)
            signature=base64.b64encode(self._key('WECHAT_PRIVATE_KEY',private=True).sign(
                b'POST\n'+endpoint.encode()+b'\n'+timestamp.encode()+b'\n'+nonce.encode()+b'\n'+body+b'\n',
                padding.PKCS1v15(),hashes.SHA256())).decode('ascii')
            authorization=('WECHATPAY2-SHA256-RSA2048 '+f'mchid="{self._setting("WECHAT_MCH_ID")}",nonce_str="{nonce}",'
                           f'timestamp="{timestamp}",serial_no="{self._setting("WECHAT_MERCHANT_SERIAL")}",signature="{signature}"')
            reply=self._post('https://api.mch.weixin.qq.com'+endpoint,data=body,
                headers={'Authorization':authorization,'Content-Type':'application/json','Accept':'application/json'})
            self._verify_wechat_message(reply.headers,reply.content)
            qr=_text(_json(reply.content).get('code_url'),2048)
        return {'provider':provider,'mode':'automatic','qr_code':qr,'checkout_reference':identifier,'expires_at':int(expires*1000)}

    def _post(self,url,**kwargs):
        try:
            response=self.http.post(url,timeout=(10,20),**kwargs)
            if not 200<=response.status_code<300:_fail('checkout_failed','支付平台未能创建订单，请稍后重试。')
            if len(response.content)>262144:_fail()
            return response
        except requests.RequestException:_fail('checkout_unconfirmed','支付下单暂未确认，请保留订单并稍后重试。')

    def verify_alipay(self,form,order=None):
        if not self._verification_ready('alipay'):_fail('payment_disabled','支付宝验签尚未配置。')
        values=_single_values(form)
        if values.get('sign_type')!='RSA2' or values.get('charset','utf-8').lower()!='utf-8':_fail('invalid_signature','仅支持 RSA2 UTF-8 支付通知。')
        _verify(self._key('ALIPAY_PUBLIC_KEY'),values.get('sign'),_canonical(values,callback=True))
        if values.get('app_id')!=self._setting('ALIPAY_APP_ID') or values.get('seller_id')!=self._setting('ALIPAY_SELLER_ID'):_fail('merchant_mismatch','支付收款商户不匹配。')
        if values.get('notify_type')!='trade_status_sync' or values.get('trade_status') not in ('TRADE_SUCCESS','TRADE_FINISHED'):_fail('payment_not_success','支付平台尚未确认支付成功。')
        if values.get('currency','CNY')!='CNY':_fail('order_mismatch','支付币种不匹配。')
        payment={'provider':'alipay','id':_text(values.get('out_trade_no'),64),
                 'amount_minor':_minor(values.get('total_amount')),'currency':'CNY',
                 'transaction_id':_text(values.get('trade_no'),128)}
        if payment['amount_minor']<=0:_fail('invalid_amount','支付金额无效。')
        return validate_order(payment,order) if order is not None else payment

    def _verify_wechat_message(self,headers,raw_body):
        values=_single_values(headers,lower=True)
        if not isinstance(raw_body,bytes) or len(raw_body)>262144:_fail()
        serial=_text(values.get('wechatpay-serial'),128)
        if serial!=self._setting('WECHAT_PLATFORM_SERIAL'):_fail('unknown_payment_key','微信支付验签证书或公钥标识不匹配。')
        timestamp=_text(values.get('wechatpay-timestamp'),20)
        if not re.fullmatch(r'[0-9]{1,12}',timestamp) or abs(self.clock()-int(timestamp))>300:_fail('expired_payment_signature','支付通知签名时间无效。')
        nonce=_text(values.get('wechatpay-nonce'),128)
        _verify(self._key('WECHAT_PLATFORM_PUBLIC_KEY'),values.get('wechatpay-signature'),timestamp.encode()+b'\n'+nonce.encode()+b'\n'+raw_body+b'\n')

    def verify_wechat(self,headers,raw_body,order=None):
        if not self._verification_ready('wechat'):_fail('payment_disabled','微信支付验签尚未配置。')
        self._verify_wechat_message(headers,raw_body)
        envelope=_json(raw_body)
        resource=envelope.get('resource')
        if envelope.get('event_type')!='TRANSACTION.SUCCESS' or envelope.get('resource_type')!='encrypt-resource' or not isinstance(resource,dict):_fail('payment_not_success','支付平台尚未确认支付成功。')
        if resource.get('algorithm')!='AEAD_AES_256_GCM':_fail()
        try:
            nonce=_text(resource.get('nonce'),64).encode('utf-8')
            associated=resource.get('associated_data','')
            if not isinstance(associated,str) or len(associated)>256:_fail()
            decrypted=AESGCM(self._setting('WECHAT_API_V3_KEY').encode('utf-8')).decrypt(nonce,_base64(resource.get('ciphertext')),associated.encode('utf-8'))
            transaction=_json(decrypted)
        except (InvalidTag,ValueError,TypeError):_fail('invalid_payment_resource','支付通知解密失败。')
        if transaction.get('appid')!=self._setting('WECHAT_APP_ID') or transaction.get('mchid')!=self._setting('WECHAT_MCH_ID'):_fail('merchant_mismatch','支付收款商户不匹配。')
        if transaction.get('trade_state')!='SUCCESS':_fail('payment_not_success','支付平台尚未确认支付成功。')
        amount=transaction.get('amount')
        if not isinstance(amount,dict) or isinstance(amount.get('total'),bool) or not isinstance(amount.get('total'),int) or amount['total']<=0 or amount.get('currency')!='CNY':_fail('invalid_amount','支付金额或币种无效。')
        payment={'provider':'wechat','id':_text(transaction.get('out_trade_no'),32),
                 'amount_minor':amount['total'],'currency':'CNY','transaction_id':_text(transaction.get('transaction_id'),128)}
        return validate_order(payment,order) if order is not None else payment
