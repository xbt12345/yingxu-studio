"""Authenticated HTTP boundary and atomic integration with the existing studio."""
from contextvars import ContextVar
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import threading
import time
import base64
import io
from typing import Literal

from fastapi import HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from platform_accounts import PlatformAccounts, AccountError
from payment_gateway import PaymentGateway, PaymentError
from platform_pricing import load_pricing_policy, creation_quote, enrich_workflow_quote, PricingValidationError
from deployment_access import railway_origin

CURRENT_USER = ContextVar('yingxu_account', default=None)
SUBMISSION_IDENTITY = ContextVar('yingxu_submission_identity', default=None)
EXPECTED_CREDITS = ContextVar('yingxu_expected_credits', default=None)
COOKIE = 'yingxu_session'


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=256)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class RechargeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    package_id: str = Field(min_length=1, max_length=100)
    method: str = Field(default='admin_contact', max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PackageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    credits: int = Field(gt=0, strict=True)
    amount_minor: int = Field(gt=0, strict=True)
    enabled: bool = False


class PriceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workflow_id: str = Field(min_length=1, max_length=100)
    credits: int = Field(ge=0, strict=True)


class CreationQuoteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = Field(min_length=1, max_length=100, strict=True)
    kind: Literal['image', 'video']
    quality: str = Field(min_length=1, max_length=20, strict=True)
    count: int = Field(ge=1, le=8, strict=True)
    duration: int | None = Field(ge=4, le=15, strict=True)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    payment_reference: str = Field(min_length=3, max_length=200)


class UserChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: str | None = None
    disabled: bool | None = None


class UserCreationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=80, strict=True)
    password: str = Field(min_length=10, max_length=128, strict=True)
    role: Literal['user','admin'] = 'user'


class CreditAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    delta: int = Field(strict=True, ge=-PlatformAccounts.MAX_CREDITS, le=PlatformAccounts.MAX_CREDITS)
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r'^[A-Za-z0-9_.:-]+$')

class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: str
    note: str = Field(min_length=3, max_length=1000)
    refund_reference: str | None = Field(default=None, max_length=200)


class GenerationReviewDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: str
    confirmation_reference: str = Field(min_length=3, max_length=200)
    note: str = Field(min_length=3, max_length=1000)


def public_user(user):
    return {k:v for k,v in {**user, 'available':user['balance']}.items()
            if k not in ('csrf_token', 'session_expires_at')}


class PlatformIntegration:
    def __init__(self, backend):
        self.backend = backend
        self._stores = {}
        self._owners = {}
        self._lock = threading.RLock()
        self.gateway = PaymentGateway()
        self.accounts()

    def accounts(self):
        # Tests and isolated deployments can replace DATA_DIR without crossing data.
        key = (str(self.backend.DB), str(self.backend.PRIVATE))
        with self._lock:
            if key not in self._stores:
                path = Path(self.backend.PRIVATE)/'platform-config.json'
                store = PlatformAccounts(self.backend.DB, self.backend.PRIVATE,
                    config_path=path if path.exists() else None)
                owner = store.bootstrap_admin()
                store.migrate_legacy_resources(owner['id'])
                from platform_pricing_seed import seed_reviewed_pricing
                seed_reviewed_pricing(store, owner['id'])
                self._owners[key] = owner['id']
                self._stores[key] = store
            return self._stores[key]

    def workflow_options(self):
        options = {}
        for workflow in list(self.backend.WORKFLOWS) + list(getattr(self.backend,'CATALOG_WORKFLOWS',())):
            options[workflow['id']] = {'id':workflow['id'],'name':workflow.get('name') or workflow['id']}
        for identifier,spec in self.backend.schema_adapters.registry().items():
            if spec.get('validation') != 'structural-verified':
                continue
            options.setdefault(identifier,{'id':identifier,'name':spec.get('name') or identifier})
        return list(options.values())

    def require_user(self, request=None, admin=False):
        user = getattr(request.state, 'account', None) if request is not None else CURRENT_USER.get()
        if not user:
            raise HTTPException(401, '请先登录。')
        if admin and user['role'] != 'admin':
            raise HTTPException(403, '仅管理员可以进行此操作。')
        return user

    def check_resource(self, kind, identifier):
        user = CURRENT_USER.get()
        if user and not self.accounts().owns_resource(user['id'], kind, identifier):
            raise HTTPException(404, '找不到当前账户的资源。')

    def visible_jobs(self, records):
        user = CURRENT_USER.get()
        if not user:
            return records  # Internal recovery workers operate across all accounts.
        ids = set(self.accounts().resource_ids(user['id'], 'job'))
        return [j for j in records if j['id'] in ids]

    def grant_asset(self, identifier, connection=None):
        user = CURRENT_USER.get()
        if user:
            self.accounts().grant_resource(user['id'], 'asset', identifier, connection=connection)

    def remember_asset(self, record, connection=None):
        user = CURRENT_USER.get()
        if not user:return
        accounts = self.accounts()
        if connection is None:
            with accounts.transaction() as db:
                accounts.grant_resource(user['id'],'asset',record['id'],connection=db)
                accounts.remember_asset(user['id'],record,connection=db)
        else:
            accounts.grant_resource(user['id'],'asset',record['id'],connection=connection)
            accounts.remember_asset(user['id'],record,connection=connection)

    def asset_details(self, record):
        user = CURRENT_USER.get()
        return {**record,**self.accounts().asset_metadata(user['id'],record['id'])} if user else record

    def registration_limit(self, request):
        client = request.client.host if request.client else 'unknown'
        key = 'signup-ip:'+hashlib.sha256(client.encode()).hexdigest()
        now = int(time.time())
        with self.accounts().transaction() as db:
            count = db.execute('SELECT count(*) FROM platform_auth_attempts WHERE key=? AND attempted_at>?', (key,now-600)).fetchone()[0]
            if count >= 10:raise AccountError(429,'registration_limited','注册请求过于频繁，请稍后重试。')
            db.execute('INSERT INTO platform_auth_attempts(key,attempted_at) VALUES(?,?)',(key,now))

    def prepare_submission(self, body, original_id=None):
        user = CURRENT_USER.get()
        if not user:
            SUBMISSION_IDENTITY.set(None)
            return
        data = body.model_dump(mode='json')
        raw_token = data.pop('token')
        fingerprint = hashlib.sha256(json.dumps({'input':data, 'rerun_of':original_id},
            ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        scoped = hashlib.sha256((user['id']+'\0'+raw_token).encode()).hexdigest()
        if user['role'] != 'admin' and any(
                p.get('base_url') for p in getattr(body, 'api_profiles', {}).values() if isinstance(p, dict)):
            raise HTTPException(403, '自定义 API 地址须由管理员核对；可以继续使用已配置的服务。')
        workflow_id = getattr(body, 'workflow_id', None)
        if workflow_id is None:
            workflow_id = self.backend.job(original_id)['workflow_id']
        # Check duplicates before price changes or balance checks can invalidate retries.
        with self.backend.database() as db:
            old = db.execute('SELECT data FROM jobs WHERE token=?', (scoped,)).fetchone()
        SUBMISSION_IDENTITY.set({'owner_id':user['id'], 'client_token':raw_token,
            'request_fingerprint':fingerprint, 'scoped_token':scoped})
        body.token = scoped
        if old:
            self.checked_replay(old[0])
            return
        quote = self.accounts().pricing(workflow_id)
        if not quote['configured']:
            raise HTTPException(409, '管理员尚未设置此工具的积分费用；免费演示仍可使用。')
        if EXPECTED_CREDITS.get() != str(quote['credits']):
            raise HTTPException(409, '积分报价已更新，请刷新费用提示后再提交。')
        SUBMISSION_IDENTITY.get()['quoted_credits'] = quote['credits']

    def checked_replay(self, data):
        record = json.loads(data) if isinstance(data, str) else data
        identity = SUBMISSION_IDENTITY.get()
        if identity and (record.get('owner_id') != identity['owner_id'] or
                record.get('request_fingerprint') != identity['request_fingerprint']):
            raise HTTPException(409, '同一提交编号不能用于不同参数，请重新提交。')
        return record

    def persist_job(self, record):
        identity = SUBMISSION_IDENTITY.get()
        if not identity:
            with self.backend.lock, self.backend.database() as db:
                db.execute('INSERT INTO jobs(id,token,data) VALUES(?,?,?)',
                    (record['id'], record['token'], json.dumps(record, ensure_ascii=False)))
            return record
        record.update({k:v for k,v in identity.items() if k not in ('scoped_token','quoted_credits')})
        accounts = self.accounts()
        with self.backend.lock, accounts.transaction() as db:
            old = db.execute('SELECT data FROM jobs WHERE token=?', (record['token'],)).fetchone()
            if old:
                replay = self.checked_replay(old[0])
                return {**replay, '_platform_replay':True}
            if accounts.pricing(record['workflow_id'], connection=db)['credits'] != identity['quoted_credits']:
                raise HTTPException(409, '积分价格在准备期间发生变化，请确认新报价后重新提交。')
            reservation = accounts.reserve(identity['owner_id'], record['id'], record['workflow_id'], connection=db)
            record['credit_cost'] = reservation['credits']
            db.execute('INSERT INTO jobs(id,token,data) VALUES(?,?,?)',
                (record['id'], record['token'], json.dumps(record, ensure_ascii=False)))
            accounts.grant_resource(identity['owner_id'], 'job', record['id'], connection=db)
        return record

    def track_saved_job(self, record, connection):
        accounts = self.accounts()
        user = CURRENT_USER.get()
        key = (str(self.backend.DB), str(self.backend.PRIVATE))
        owner = record.get('owner_id') or (user['id'] if user else self._owners[key])
        previous_factory = connection.row_factory
        connection.row_factory = sqlite3.Row
        try:
            accounts.grant_resource(owner, 'job', record['id'], connection=connection)
            self.settle_record(record, connection=connection)
        finally:
            connection.row_factory = previous_factory

    def settle_record(self, record, connection=None):
        accounts = self.accounts()
        status = record.get('status')
        if status == 'done':
            accounts.settle(record['id'], connection=connection)
        elif status == 'cancelled' or status == 'failed' and record.get('failure_phase') != 'output':
            accounts.release(record['id'], connection=connection)
        # Unknown, output retrieval failures and abandoned local tracking retain holds.

    def install(self, app):
        @app.exception_handler(RequestValidationError)
        async def credential_validation_error(request, error):
            credential_paths = {'/api/account/login','/api/account/register',
                                '/api/account/password','/api/admin/users'}
            if request.method == 'POST' and request.url.path in credential_paths:
                # Pydantic includes submitted values by default; credentials must
                # never be echoed, even when a field or an extra property is bad.
                return JSONResponse({'detail':[{key:item[key] for key in ('loc','msg','type') if key in item}
                                              for item in error.errors()]},status_code=422)
            return await request_validation_exception_handler(request,error)

        @app.exception_handler(AccountError)
        async def account_error(request, error):
            return JSONResponse({'detail':error.message, 'code':error.code}, error.status)

        @app.exception_handler(PaymentError)
        async def payment_error(request, error):
            return JSONResponse({'detail':str(error), 'code':error.code}, 409)

        public_api = {'/api/account/login', '/api/account/register', '/api/workflows',
                      '/api/catalog-connections'}
        webhooks = {'/api/payments/webhooks/alipay', '/api/payments/webhooks/wechat'}

        @app.middleware('http')
        async def account_boundary(request, call_next):
            path = request.url.path
            if not path.startswith('/api'):
                return await call_next(request)
            # Verified payment notifications use signatures, never browser cookies.
            if path in webhooks:
                return await call_next(request)
            origin = request.headers.get('origin')
            unsafe = request.method not in ('GET', 'HEAD', 'OPTIONS')
            # Railway terminates HTTPS before forwarding to the internal HTTP
            # listener. Use its configured domain, never caller-supplied proxy
            # headers, as the public origin for account and CSRF checks.
            expected_origin = railway_origin() or str(request.base_url).rstrip('/')
            if unsafe and (not origin or origin.rstrip('/') != expected_origin):
                return JSONResponse({'detail':'请从当前网站进行此操作。', 'code':'invalid_origin'}, 403)
            if path in public_api:
                if path == '/api/account/register':
                    try:self.registration_limit(request)
                    except AccountError as error:return JSONResponse({'detail':error.message,'code':error.code},error.status)
                return await call_next(request)
            try:
                user = self.accounts().resolve_session(request.cookies.get(COOKIE))
                expected = request.headers.get('X-Platform-Account')
                if expected and expected != user['id']:
                    raise AccountError(409, 'account_changed', '账户已切换，请刷新页面后继续。')
                if unsafe:
                    self.accounts().require_csrf(request.cookies.get(COOKIE), request.headers.get('X-CSRF-Token'))
                if path.startswith('/api/admin/') and user['role'] != 'admin':
                    raise AccountError(403, 'admin_required', '仅管理员可以进行此操作。')
                request.state.account = user
                token = CURRENT_USER.set(user)
                quote_token = EXPECTED_CREDITS.set(request.headers.get('X-Expected-Credits'))
                try:
                    match = re.match(r'^/api/(jobs|media|assets)/([^/]+)', path)
                    if match:
                        kind = 'asset' if match.group(1) == 'assets' else 'job'
                        self.check_resource(kind, match.group(2))
                    if path == '/api/local-directory' and user['role'] != 'admin':
                        raise HTTPException(403, '本机目录选择仅限管理员使用。')
                    response = await call_next(request)
                    response.headers['Cache-Control'] = 'no-store'
                    response.headers['X-Content-Type-Options'] = 'nosniff'
                    return response
                finally:
                    CURRENT_USER.reset(token)
                    EXPECTED_CREDITS.reset(quote_token)
            except AccountError as error:
                return JSONResponse({'detail':error.message, 'code':error.code}, error.status)
            except HTTPException as error:
                return JSONResponse({'detail':error.detail}, error.status_code)

        @app.post('/api/account/register')
        def register(body:Credentials, request:Request):
            user = self.accounts().register(body.username, body.password)
            session = self.accounts().create_session(user['id'])
            return login_response(session, request)

        @app.post('/api/account/login')
        def login(body:Credentials, request:Request):
            accounts = self.accounts()
            attempt = request.client.host if request.client else 'unknown'
            if hasattr(accounts, 'login'):
                session = accounts.login(body.username, body.password, attempt_key=attempt)
            else:
                session = accounts.create_session(accounts.authenticate(body.username, body.password, attempt_key=attempt)['id'])
            return login_response(session, request)

        def login_response(session, request):
            response = JSONResponse({'user':public_user(session['user']), 'csrf_token':session['csrf_token']})
            response.set_cookie(COOKIE, session['token'], httponly=True, samesite='lax',
                secure=bool(railway_origin()) or request.url.scheme == 'https',
                max_age=self.accounts().SESSION_SECONDS, path='/')
            response.headers['Cache-Control'] = 'no-store'
            return response

        @app.get('/api/account/me')
        def me(request:Request):
            user = self.require_user(request)
            return {'user':public_user(user), 'csrf_token':user['csrf_token']}

        @app.post('/api/account/logout')
        def logout(request:Request):
            self.accounts().logout(request.cookies.get(COOKIE))
            response = JSONResponse({'logged_out':True})
            response.delete_cookie(COOKIE, path='/')
            return response

        @app.post('/api/account/password')
        def change_password(body:PasswordChange, request:Request):
            return self.accounts().change_password(self.require_user(request)['id'], body.current_password, body.new_password)

        @app.get('/api/account/dashboard')
        def dashboard(request:Request):
            user = self.require_user(request)
            accounts = self.accounts()
            methods = self.gateway.methods()
            automatic = any(m['enabled'] and m['automatic'] for m in methods)
            manual = any(m['enabled'] and not m['automatic'] for m in methods)
            enabled = accounts.config['payment_mode'] == 'manual' and bool(accounts.packages()) and (automatic or manual)
            status = {**accounts.payment_status(), 'enabled':enabled,
                'mode':('mixed' if automatic and manual else 'automatic' if automatic else 'manual') if enabled else 'disabled',
                'automatic_payments':automatic,
                'message':('自动支付经服务端核验后到账；人工充值经管理员核对收款后到账。' if automatic else
                    '充值订单须经管理员核对实际收款后到账。') if enabled else '管理员尚未配置可用的充值套餐。'}
            return {'user':public_user(accounts.account(user['id'])), 'packages':accounts.packages(),
                'orders':accounts.list_orders(user['id']), 'ledger':accounts.ledger(user['id']),
                'methods':methods, 'contact':accounts.config['payment_instructions'],
                'pricing':[], 'payment_status':status,
                'credit_policy':load_pricing_policy()['credit_policy']}

        @app.get('/api/account/pricing-policy')
        def pricing_policy(request:Request):
            self.require_user(request)
            return load_pricing_policy()

        @app.post('/api/account/creation-quote')
        def quote_creation(body:CreationQuoteRequest, request:Request):
            self.require_user(request)
            try:
                return creation_quote(**body.model_dump())
            except PricingValidationError as error:
                raise HTTPException(422, str(error)) from error

        @app.get('/api/account/quote/{workflow_id}')
        def quote(workflow_id:str, request:Request):
            self.require_user(request)
            return enrich_workflow_quote(self.accounts().pricing(workflow_id))

        @app.post('/api/account/orders')
        def create_order(body:RechargeRequest, request:Request):
            user = self.require_user(request)
            method = next((m for m in self.gateway.methods() if m['id'] == body.method), None)
            if not method or not method['enabled']:
                raise HTTPException(409, '此充值渠道尚未配置，请选择联系管理员。')
            accounts = self.accounts()
            order = accounts.create_order(user['id'], body.package_id, body.idempotency_key, body.method)
            if order['status'] != 'pending':
                return {'order':order}
            if method['automatic']:
                accounts.mark_order_checkout(order['id'], body.method, order['id'])
            checkout = self.gateway.create_checkout(order)
            if checkout.get('qr_code'):
                import qrcode
                image=qrcode.make(checkout['qr_code']);buffer=io.BytesIO();image.save(buffer,format='PNG')
                checkout['qr_code_image']='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
            return {'order':accounts.get_order(order['id'], user['id']), 'checkout':checkout}

        @app.get('/api/account/orders/{id}')
        def read_order(id:str, request:Request):
            return {'order':self.accounts().get_order(id, self.require_user(request)['id'])}

        @app.post('/api/account/orders/{id}/cancel')
        def cancel_order(id:str, request:Request):
            return self.accounts().cancel_order(self.require_user(request)['id'], id)

        @app.get('/api/admin/dashboard')
        def admin_dashboard(request:Request):
            user = self.require_user(request, admin=True)
            accounts = self.accounts()
            return {'users':[public_user(u) for u in accounts.list_accounts(user['id'])],
                'orders':accounts.list_orders(actor_id=user['id']), 'packages':accounts.packages(user['id']),
                'pricing':accounts.list_pricing(user['id']), 'payment_reviews':accounts.list_payment_reviews(user['id']),
                'generation_reviews':accounts.list_generation_reviews(user['id']),
                'stats':accounts.admin_stats(user['id']), 'workflow_options':self.workflow_options(),
                'credit_policy':load_pricing_policy()['credit_policy']}

        @app.get('/api/admin/audit')
        def read_audit(request:Request):
            return {'audit':self.accounts().admin_audit(self.require_user(request,admin=True)['id'])}

        @app.get('/api/admin/users')
        def read_users(request:Request, query:str=Query(default='',max_length=80),
                role:str=Query(default='all',pattern=r'^(all|user|admin)$'),
                state:str=Query(default='all',pattern=r'^(all|enabled|disabled)$'),
                limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0,le=PlatformAccounts.MAX_CREDITS)):
            result = self.accounts().query_accounts(self.require_user(request,admin=True)['id'],
                query=query,role=role,state=state,limit=limit,offset=offset)
            return {**result,'users':[public_user(user) for user in result['users']]}

        @app.get('/api/admin/users/{id}/ledger')
        def read_user_ledger(id:str, request:Request):
            actor = self.require_user(request,admin=True)['id']
            accounts = self.accounts()
            ledger = accounts.admin_ledger(actor,id)
            return {'user':public_user(accounts.account(id)), 'ledger':ledger}

        @app.post('/api/admin/users')
        def create_user(body:UserCreationRequest, request:Request):
            actor = self.require_user(request,admin=True)['id']
            user = self.accounts().admin_create_user(actor,body.username,body.password,body.role)
            return {'user':public_user(user)}

        @app.post('/api/admin/users/{id}/credits')
        def adjust_user_credits(id:str, body:CreditAdjustmentRequest, request:Request):
            accounts = self.accounts()
            adjustment = accounts.adjust_credits(self.require_user(request,admin=True)['id'],id,
                body.delta,body.reason,body.idempotency_key)
            return {'user':public_user(accounts.account(id)), 'adjustment':adjustment}

        @app.post('/api/admin/packages')
        def set_package(body:PackageRequest, request:Request):
            return self.accounts().configure_package(self.require_user(request, admin=True)['id'],
                body.id, body.title, body.credits, body.amount_minor, body.enabled)

        @app.post('/api/admin/pricing')
        def set_price(body:PriceRequest, request:Request):
            actor = self.require_user(request, admin=True)['id']
            identifiers = {w['id'] for w in self.workflow_options()}
            if body.workflow_id not in identifiers:
                raise HTTPException(400, '请填写平台已有的真实工作流编号。')
            return self.accounts().configure_pricing(actor, body.workflow_id, body.credits)

        @app.post('/api/admin/orders/{id}/confirm')
        def confirm_order(id:str, body:Confirmation, request:Request):
            return self.accounts().confirm_order(self.require_user(request, admin=True)['id'], id, body.payment_reference)

        @app.post('/api/admin/users/{id}')
        def change_user(id:str, body:UserChange, request:Request):
            actor = self.require_user(request, admin=True)['id']
            if (body.role is None) == (body.disabled is None):
                raise HTTPException(400, '一次只修改账号权限或使用状态，避免部分操作成功。')
            if body.role is not None:
                self.accounts().set_role(actor, id, body.role)
            if body.disabled is not None:
                self.accounts().disable_account(actor, id, body.disabled)
            return public_user(self.accounts().account(id))

        @app.post('/api/admin/payment-reviews/{id}/resolve')
        def resolve_review(id:str, body:ReviewDecision, request:Request):
            return self.accounts().resolve_payment_review(self.require_user(request,admin=True)['id'],
                id,body.decision,body.note,refund_reference=body.refund_reference)

        @app.post('/api/admin/generation-reviews/{id}/resolve')
        def resolve_generation_review(id:str, body:GenerationReviewDecision, request:Request):
            return self.accounts().resolve_generation_review(self.require_user(request,admin=True)['id'],
                id,body.decision,body.confirmation_reference,body.note)

        @app.post('/api/payments/webhooks/alipay')
        async def alipay_notification(request:Request):
            try:
                if len(await request.body()) > 64*1024:return Response('failure',status_code=400,media_type='text/plain')
                form = await request.form()
                result = self.gateway.verify_alipay(form)
                self.accounts().credit_verified_order(result['id'], result['provider'], result['amount_minor'], result['currency'], result['transaction_id'])
                return Response('success', media_type='text/plain')
            except (PaymentError, AccountError):
                return Response('failure', status_code=400, media_type='text/plain')

        @app.post('/api/payments/webhooks/wechat')
        async def wechat_notification(request:Request):
            try:
                raw = await request.body()
                if len(raw) > 64*1024:
                    return JSONResponse({'code':'FAIL','message':'通知过大'}, 400)
                result = self.gateway.verify_wechat(request.headers, raw)
                self.accounts().credit_verified_order(result['id'], result['provider'], result['amount_minor'], result['currency'], result['transaction_id'])
                return Response(status_code=204)
            except (PaymentError, AccountError):
                return JSONResponse({'code':'FAIL','message':'通知校验失败'}, 400)


def install_platform(app, backend):
    integration = PlatformIntegration(backend)
    integration.install(app)
    return integration
