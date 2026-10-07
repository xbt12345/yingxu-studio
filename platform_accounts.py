"""Local account, ownership and credit ledger primitives.

This module owns no HTTP routes and performs no payment or generation requests.
Every balance change is transactional and has an append-only ledger entry. A
browser returning from a payment page is never a source of financial truth.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid


class AccountError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    legacy_owner INTEGER NOT NULL DEFAULT 0 CHECK(legacy_owner IN (0, 1)),
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
    held INTEGER NOT NULL DEFAULT 0 CHECK(held >= 0),
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    csrf_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_session_owner ON platform_sessions(account_id);
CREATE TABLE IF NOT EXISTS platform_auth_attempts (
    key TEXT NOT NULL,
    attempted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_attempt_key ON platform_auth_attempts(key, attempted_at);
CREATE TABLE IF NOT EXISTS platform_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_resource_owners (
    kind TEXT NOT NULL CHECK(kind IN ('job', 'asset')),
    resource_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    created_at INTEGER NOT NULL,
    PRIMARY KEY(kind, resource_id, account_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS platform_one_job_owner
    ON platform_resource_owners(resource_id) WHERE kind = 'job';
CREATE TABLE IF NOT EXISTS platform_asset_metadata (
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    asset_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY(account_id, asset_id)
);
CREATE TABLE IF NOT EXISTS platform_prices (
    workflow_id TEXT PRIMARY KEY,
    credits INTEGER NOT NULL CHECK(credits >= 0),
    updated_by TEXT REFERENCES platform_accounts(id),
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_packages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    credits INTEGER NOT NULL CHECK(credits > 0),
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    currency TEXT NOT NULL CHECK(currency = 'CNY'),
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    updated_by TEXT REFERENCES platform_accounts(id),
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_orders (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    package_id TEXT NOT NULL,
    package_title TEXT NOT NULL,
    credits INTEGER NOT NULL CHECK(credits > 0),
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    currency TEXT NOT NULL CHECK(currency = 'CNY'),
    payment_method TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'confirmed', 'cancelled', 'expired')),
    idempotency_key TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    confirmed_at INTEGER,
    confirmed_by TEXT REFERENCES platform_accounts(id),
    confirmation_reference TEXT,
    payment_reference_key TEXT UNIQUE,
    checkout_reference TEXT UNIQUE,
    checkout_created_at INTEGER,
    UNIQUE(account_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS platform_orders_owner ON platform_orders(account_id, created_at);
CREATE TABLE IF NOT EXISTS platform_reservations (
    job_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    workflow_id TEXT NOT NULL,
    credits INTEGER NOT NULL CHECK(credits >= 0),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK(attempt >= 1),
    status TEXT NOT NULL CHECK(status IN ('held', 'settled', 'released')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    event_key TEXT NOT NULL UNIQUE,
    event TEXT NOT NULL CHECK(event IN ('recharge', 'reserve', 'settle', 'release', 'adjustment')),
    amount INTEGER NOT NULL,
    held_amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
    held_after INTEGER NOT NULL CHECK(held_after >= 0),
    resource_id TEXT NOT NULL,
    actor_id TEXT REFERENCES platform_accounts(id),
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS platform_ledger_owner ON platform_ledger(account_id, id);
CREATE TRIGGER IF NOT EXISTS platform_ledger_no_update BEFORE UPDATE ON platform_ledger
BEGIN SELECT RAISE(ABORT, 'credit ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS platform_ledger_no_delete BEFORE DELETE ON platform_ledger
BEGIN SELECT RAISE(ABORT, 'credit ledger is append-only'); END;
CREATE TABLE IF NOT EXISTS platform_admin_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT NOT NULL REFERENCES platform_accounts(id),
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS platform_audit_no_update BEFORE UPDATE ON platform_admin_audit
BEGIN SELECT RAISE(ABORT, 'admin audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS platform_audit_no_delete BEFORE DELETE ON platform_admin_audit
BEGIN SELECT RAISE(ABORT, 'admin audit is append-only'); END;
CREATE TABLE IF NOT EXISTS platform_credit_adjustments (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL REFERENCES platform_accounts(id),
    account_id TEXT NOT NULL REFERENCES platform_accounts(id),
    delta INTEGER NOT NULL CHECK(delta != 0),
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    ledger_id INTEGER NOT NULL UNIQUE,
    balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
    held_after INTEGER NOT NULL CHECK(held_after >= 0),
    created_at INTEGER NOT NULL,
    UNIQUE(actor_id, idempotency_key)
);
CREATE TRIGGER IF NOT EXISTS platform_adjustment_no_update BEFORE UPDATE ON platform_credit_adjustments
BEGIN SELECT RAISE(ABORT, 'credit adjustment is append-only'); END;
CREATE TRIGGER IF NOT EXISTS platform_adjustment_no_delete BEFORE DELETE ON platform_credit_adjustments
BEGIN SELECT RAISE(ABORT, 'credit adjustment is append-only'); END;
CREATE TABLE IF NOT EXISTS platform_payment_reviews (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    method TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    payment_reference TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS platform_review_no_update BEFORE UPDATE ON platform_payment_reviews
BEGIN SELECT RAISE(ABORT, 'payment evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS platform_review_no_delete BEFORE DELETE ON platform_payment_reviews
BEGIN SELECT RAISE(ABORT, 'payment evidence is append-only'); END;
CREATE TABLE IF NOT EXISTS platform_payment_resolutions (
    review_id TEXT PRIMARY KEY REFERENCES platform_payment_reviews(id),
    decision TEXT NOT NULL CHECK(decision IN ('credit', 'refund_recorded')),
    actor_id TEXT NOT NULL REFERENCES platform_accounts(id),
    note TEXT NOT NULL,
    refund_reference TEXT UNIQUE,
    created_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS platform_resolution_no_update BEFORE UPDATE ON platform_payment_resolutions
BEGIN SELECT RAISE(ABORT, 'payment resolution is append-only'); END;
CREATE TRIGGER IF NOT EXISTS platform_resolution_no_delete BEFORE DELETE ON platform_payment_resolutions
BEGIN SELECT RAISE(ABORT, 'payment resolution is append-only'); END;
"""


class PlatformAccounts:
    PAYMENT_METHODS = frozenset(('alipay', 'wechat', 'bank', 'admin_contact'))
    SESSION_SECONDS = 7 * 24 * 60 * 60
    MAX_CREDITS = 1_000_000_000

    def __init__(self, db_path, private_dir, config=None, config_path=None,
                 password_rounds=600_000, clock=time.time):
        self.db_path = Path(db_path)
        self.private_dir = Path(private_dir)
        self.clock = clock
        self.password_rounds = max(100_000, int(password_rounds))
        self.config = self._load_config(config, config_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.private_dir.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)
        self._ensure_adjustment_ledger()
        self._dummy_password_hash = self._hash_password(secrets.token_urlsafe(32))

    def _ensure_adjustment_ledger(self):
        """Widen the old CHECK atomically, keeping every ledger ID and balance.

        SQLite cannot add an allowed CHECK value in place. The original ledger
        has no incoming foreign keys; its append-only protections are restored
        in this same transaction before another writer can observe the table.
        """
        with self.transaction() as db:
            definition = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='platform_ledger'").fetchone()[0]
            if "'adjustment'" in definition:
                return
            old_sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='platform_ledger'").fetchone()
            db.execute("""CREATE TABLE platform_ledger_adjustment_migration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL REFERENCES platform_accounts(id),
                event_key TEXT NOT NULL UNIQUE,
                event TEXT NOT NULL CHECK(event IN ('recharge','reserve','settle','release','adjustment')),
                amount INTEGER NOT NULL, held_amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
                held_after INTEGER NOT NULL CHECK(held_after >= 0),
                resource_id TEXT NOT NULL,
                actor_id TEXT REFERENCES platform_accounts(id), created_at INTEGER NOT NULL
            )""")
            db.execute('INSERT INTO platform_ledger_adjustment_migration SELECT * FROM platform_ledger')
            db.execute('DROP TABLE platform_ledger')
            db.execute('ALTER TABLE platform_ledger_adjustment_migration RENAME TO platform_ledger')
            if old_sequence is not None:
                db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='platform_ledger'", (old_sequence[0],))
            db.execute('CREATE INDEX platform_ledger_owner ON platform_ledger(account_id,id)')
            db.execute("CREATE TRIGGER platform_ledger_no_update BEFORE UPDATE ON platform_ledger BEGIN SELECT RAISE(ABORT,'credit ledger is append-only'); END")
            db.execute("CREATE TRIGGER platform_ledger_no_delete BEFORE DELETE ON platform_ledger BEGIN SELECT RAISE(ABORT,'credit ledger is append-only'); END")

    @staticmethod
    def _load_config(config, config_path):
        if config_path is not None:
            if config is not None:
                raise AccountError(500, 'invalid_config', '账户配置来源重复。')
            try:
                config = json.loads(Path(config_path).read_text('utf-8-sig'))
            except (OSError, ValueError) as error:
                raise AccountError(500, 'invalid_config', '账户配置文件无法读取，请检查服务端配置。') from error
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise AccountError(500, 'invalid_config', '账户配置必须为对象。')
        default = config.get('default_job_cost', 0)
        mode = config.get('payment_mode', 'manual')
        if type(default) is not int or not 0 <= default <= PlatformAccounts.MAX_CREDITS:
            raise AccountError(500, 'invalid_config', '默认积分费用必须为非负整数。')
        if mode not in ('disabled', 'manual'):
            raise AccountError(500, 'invalid_config', '尚未接入自动支付渠道，不能启用自动到账。')
        contacts = config.get('payment_instructions', {})
        if not isinstance(contacts, dict) or any(
            key not in PlatformAccounts.PAYMENT_METHODS or not isinstance(value, str) or len(value) > 2000
            for key, value in contacts.items()
        ):
            raise AccountError(500, 'invalid_config', '充值说明配置无效。')
        return {'default_job_cost': default, 'payment_mode': mode,
                'payment_instructions': dict(contacts)}

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA busy_timeout = 15000')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @contextmanager
    def _write(self, connection=None):
        if connection is not None:
            if not connection.in_transaction:
                raise AccountError(500, 'transaction_required', '账户事务必须与任务保存共用已开启的事务。')
            previous_factory = connection.row_factory
            connection.row_factory = sqlite3.Row
            try:
                yield connection
            finally:
                connection.row_factory = previous_factory
        else:
            with self.transaction() as db:
                yield db

    def _now(self):
        return int(self.clock())

    @staticmethod
    def _row(row, description='账户'):
        if row is None:
            raise AccountError(404, 'not_found', f'找不到{description}。')
        return dict(row)

    @staticmethod
    def _username(username):
        if not isinstance(username, str):
            raise AccountError(400, 'invalid_username', '请输入账户名。')
        username = unicodedata.normalize('NFKC', username).strip()
        if not 3 <= len(username) <= 80 or not all(c.isalnum() or c in '_.@+-' for c in username):
            raise AccountError(400, 'invalid_username', '账户名需为 3 至 80 个字母、数字、汉字或常用邮箱符号。')
        return username, username.casefold()

    @staticmethod
    def _password(password):
        if not isinstance(password, str) or not 10 <= len(password) <= 128 or not password.strip():
            raise AccountError(400, 'invalid_password', '密码长度需为 10 至 128 个字符。')
        try:
            password.encode('utf-8')
        except UnicodeError as error:
            raise AccountError(400, 'invalid_password', '密码字符格式无效。') from error
        return password

    @staticmethod
    def _integer(value, name, minimum=0):
        if type(value) is not int or not minimum <= value <= PlatformAccounts.MAX_CREDITS:
            raise AccountError(400, 'invalid_amount', f'{name}需为 {minimum} 至 {PlatformAccounts.MAX_CREDITS} 的整数。')
        return value

    @staticmethod
    def _identifier(value, name):
        if not isinstance(value, str) or not 1 <= len(value) <= 160 or not re.fullmatch(r'[A-Za-z0-9_.:/-]+', value):
            raise AccountError(400, 'invalid_identifier', f'{name}格式无效。')
        return value

    def _hash_password(self, password):
        salt = secrets.token_bytes(24)
        result = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, self.password_rounds)
        return f'pbkdf2_sha256${self.password_rounds}${salt.hex()}${result.hex()}'

    @staticmethod
    def _verify_password(password, encoded):
        try:
            algorithm, rounds, salt, expected = encoded.split('$')
            if algorithm != 'pbkdf2_sha256' or not 100_000 <= int(rounds) <= 2_000_000:
                return False
            calculated = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(rounds))
            return hmac.compare_digest(calculated, bytes.fromhex(expected))
        except (AttributeError, TypeError, ValueError, UnicodeError):
            return False

    @staticmethod
    def _public(row):
        value = dict(row)
        value.pop('password_hash', None)
        value.pop('username_key', None)
        value['enabled'] = bool(value['enabled'])
        value['legacy_owner'] = bool(value['legacy_owner'])
        return value

    def _account(self, db, account_id, enabled=True):
        row = self._row(db.execute('SELECT * FROM platform_accounts WHERE id = ?', (account_id,)).fetchone())
        if enabled and not row['enabled']:
            raise AccountError(403, 'account_disabled', '该账户已停用。')
        return row

    def _admin(self, db, actor_id):
        actor = self._account(db, actor_id)
        if actor['role'] != 'admin':
            raise AccountError(403, 'admin_required', '此操作需要管理员权限。')
        return actor

    def _audit(self, db, actor_id, action, target, data=None):
        db.execute('INSERT INTO platform_admin_audit(actor_id, action, target, data, created_at) VALUES(?,?,?,?,?)',
                   (actor_id, action, target, json.dumps(data or {}, ensure_ascii=False), self._now()))

    def register(self, username, password):
        username, key = self._username(username)
        password_hash = self._hash_password(self._password(password))
        account_id = 'u-' + uuid.uuid4().hex
        try:
            with self.transaction() as db:
                db.execute('INSERT INTO platform_accounts(id,username,username_key,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                           (account_id, username, key, password_hash, 'user', self._now()))
                return self._public(self._account(db, account_id))
        except sqlite3.IntegrityError as error:
            raise AccountError(409, 'username_taken', '该账户名已被使用。') from error

    def admin_create_user(self, actor_id, username, password, role='user'):
        """Create an enabled, unfunded account without signing in its owner."""
        with self.transaction() as db:
            self._admin(db, actor_id)
            if role not in ('user', 'admin'):
                raise AccountError(400, 'invalid_role', '账户权限无效。')
            username, key = self._username(username)
            password_hash = self._hash_password(self._password(password))
            account_id = 'u-' + uuid.uuid4().hex
            try:
                db.execute('''INSERT INTO platform_accounts
                    (id,username,username_key,password_hash,role,created_at)
                    VALUES(?,?,?,?,?,?)''',
                    (account_id, username, key, password_hash, role, self._now()))
            except sqlite3.IntegrityError as error:
                if db.execute('SELECT 1 FROM platform_accounts WHERE username_key=?', (key,)).fetchone():
                    raise AccountError(409, 'username_taken', '该账户名已被使用。') from error
                raise
            self._audit(db, actor_id, 'create_user', account_id,
                        {'username':username, 'role':role, 'enabled':True})
            return self._public(self._account(db, account_id))

    def authenticate(self, username, password, attempt_key='local'):
        return self._authenticate(username, password, attempt_key, with_session=False)

    def login(self, username, password, attempt_key='local'):
        """Verify password and issue its session in the same DB transaction."""
        return self._authenticate(username, password, attempt_key, with_session=True)

    def _authenticate(self, username, password, attempt_key, with_session):
        # Keep the externally visible failure independent of whether a name exists.
        try:
            _, key = self._username(username)
        except AccountError:
            key = str(username).casefold()[:80].encode('utf-8', errors='replace').decode('utf-8')
        if not isinstance(password, str) or len(password) > 128:
            password = ''
        rate_key = hashlib.sha256((key + '\0' + str(attempt_key)[:200]).encode('utf-8', errors='replace')).hexdigest()
        address_key = hashlib.sha256(('login-address\0' + str(attempt_key)[:200]).encode('utf-8', errors='replace')).hexdigest()
        now = self._now()
        with self.transaction() as db:
            db.execute('DELETE FROM platform_auth_attempts WHERE attempted_at < ?', (now - 900,))
            attempts = db.execute('SELECT COUNT(*) FROM platform_auth_attempts WHERE key = ?', (rate_key,)).fetchone()[0]
            address_attempts = db.execute('SELECT COUNT(*) FROM platform_auth_attempts WHERE key = ?', (address_key,)).fetchone()[0]
            if attempts >= 8 or address_attempts >= 40:
                raise AccountError(429, 'login_throttled', '登录尝试过于频繁，请稍后再试。')
            db.execute('INSERT INTO platform_auth_attempts(key,attempted_at) VALUES(?,?)', (address_key, now))
            # Commit failures separately: raising inside this transaction would roll them back.
            row = db.execute('SELECT * FROM platform_accounts WHERE username_key = ?', (key,)).fetchone()
            encoded = row['password_hash'] if row is not None else self._dummy_password_hash
            valid = self._verify_password(password, encoded) and row is not None and row['enabled']
            if valid:
                db.execute('DELETE FROM platform_auth_attempts WHERE key = ?', (rate_key,))
                result = self._new_session(db, self._public(row), self.SESSION_SECONDS) if with_session else self._public(row)
            else:
                db.execute('INSERT INTO platform_auth_attempts(key,attempted_at) VALUES(?,?)', (rate_key, now))
                result = None
        if result is None:
            raise AccountError(401, 'invalid_credentials', '账户名或密码不正确。')
        return result

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    @staticmethod
    def _csrf(token):
        return hmac.new(token.encode('ascii'), b'yingxu-session-csrf-v1', hashlib.sha256).hexdigest()

    def create_session(self, account_id, lifetime=None):
        lifetime = self.SESSION_SECONDS if lifetime is None else lifetime
        if type(lifetime) is not int or not 1 <= lifetime <= 30 * 86400:
            raise AccountError(400, 'invalid_expiry', '会话期限无效。')
        with self.transaction() as db:
            account = self._public(self._account(db, account_id))
            return self._new_session(db, account, lifetime)

    def _new_session(self, db, account, lifetime):
        token = secrets.token_urlsafe(48)
        csrf = self._csrf(token)
        now = self._now()
        db.execute('DELETE FROM platform_sessions WHERE expires_at <= ?', (now,))
        db.execute('INSERT INTO platform_sessions VALUES(?,?,?,?,?)',
                   (self._token_hash(token), account['id'], self._token_hash(csrf), now, now + lifetime))
        return {'token': token, 'csrf_token': csrf, 'expires_at': now + lifetime, 'user': account}

    def resolve_session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{64}', token):
            raise AccountError(401, 'login_required', '请先登录。')
        with self.connection() as db:
            row = db.execute('SELECT * FROM platform_sessions WHERE token_hash = ? AND expires_at > ?',
                             (self._token_hash(token), self._now())).fetchone()
            if row is None:
                raise AccountError(401, 'login_required', '登录已过期，请重新登录。')
            user = self._public(self._account(db, row['account_id']))
        # Derived from the unpredictable HttpOnly session cookie. /me can return a
        # fresh readable CSRF value without persisting or exposing the session token.
        return {**user, 'csrf_token': self._csrf(token), 'session_expires_at': row['expires_at']}

    def require_csrf(self, token, csrf):
        user = self.resolve_session(token)
        if not isinstance(csrf, str) or not re.fullmatch(r'[a-f0-9]{64}', csrf) or not hmac.compare_digest(user['csrf_token'], csrf):
            raise AccountError(403, 'csrf_failed', '安全校验已失效，请刷新页面后重试。')
        return user

    def logout(self, token):
        if isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{64}', token):
            with self.transaction() as db:
                db.execute('DELETE FROM platform_sessions WHERE token_hash = ?', (self._token_hash(token),))

    def account(self, account_id):
        with self.connection() as db:
            return self._public(self._account(db, account_id, enabled=False))

    def list_accounts(self, actor_id, limit=100):
        with self.connection() as db:
            self._admin(db, actor_id)
            return [self._public(row) for row in db.execute('SELECT * FROM platform_accounts ORDER BY created_at DESC, id LIMIT ?', (min(max(int(limit), 1), 500),))]

    def query_accounts(self, actor_id, query='', role='all', state='all', limit=50, offset=0):
        if not isinstance(query,str) or len(query)>80 or role not in ('all','user','admin') or state not in ('all','enabled','disabled'):
            raise AccountError(400,'invalid_account_filter','账号筛选条件无效。')
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=self.MAX_CREDITS:
            raise AccountError(400,'invalid_pagination','账号分页参数无效。')
        where,parameters = [],[]
        if query.strip():
            literal = unicodedata.normalize('NFKC',query.strip()).casefold()
            literal = literal.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            where.append("username_key LIKE ? ESCAPE '\\'")
            parameters.append('%'+literal+'%')
        if role!='all':
            where.append('role=?');parameters.append(role)
        if state!='all':
            where.append('enabled=?');parameters.append(int(state=='enabled'))
        clause = ' WHERE '+' AND '.join(where) if where else ''
        with self.connection() as db:
            db.execute('BEGIN')  # One read snapshot for authority, total and page.
            self._admin(db,actor_id)
            total = db.execute('SELECT COUNT(*) FROM platform_accounts'+clause,parameters).fetchone()[0]
            rows = db.execute('SELECT * FROM platform_accounts'+clause+' ORDER BY created_at DESC,id LIMIT ? OFFSET ?',parameters+[limit,offset])
            return {'users':[self._public(row) for row in rows], 'total':total,'limit':limit,'offset':offset}

    def admin_stats(self, actor_id):
        with self.connection() as db:
            self._admin(db, actor_id)
            totals = dict(db.execute('''SELECT COUNT(*) AS users,
                COALESCE(SUM(enabled),0) AS enabled_users,
                COALESCE(SUM(balance),0) AS available_credits,
                COALESCE(SUM(held),0) AS held_credits FROM platform_accounts''').fetchone())
            totals['pending_orders'] = db.execute("SELECT COUNT(*) FROM platform_orders WHERE status='pending' AND expires_at>?", (self._now(),)).fetchone()[0]
            return totals

    def admin_audit(self, actor_id, limit=100):
        # Expose audit metadata only, never account rows, session hashes or graphs.
        allowed = {'role','disabled','credits','amount_minor','title','enabled',
                   'confirmation_reference','decision','note','refund_reference',
                   'previous_status','workflow_id','delta','reason','idempotency_key',
                   'balance_after','held_after','ledger_id','adjustment_id','username'}
        with self.connection() as db:
            self._admin(db, actor_id)
            result = []
            for row in db.execute('''SELECT audit.*,account.username AS actor_username
                    FROM platform_admin_audit audit LEFT JOIN platform_accounts account
                    ON account.id=audit.actor_id ORDER BY audit.id DESC LIMIT ?''',
                    (min(max(int(limit),1),500),)):
                entry = dict(row)
                try:
                    data = json.loads(entry['data'])
                except (TypeError, ValueError):
                    data = {}
                entry['data'] = {key:value for key,value in data.items()
                                 if key in allowed and (value is None or type(value) in (str,int,bool))} if isinstance(data,dict) else {}
                result.append(entry)
            return result

    def adjust_credits(self, actor_id, target_id, delta, reason, idempotency_key):
        if type(delta) is not int or delta == 0 or not -self.MAX_CREDITS <= delta <= self.MAX_CREDITS:
            raise AccountError(400, 'invalid_adjustment', '积分调整需为非零整数，且不能超过积分上限。')
        if not isinstance(reason,str) or not 3 <= len(reason.strip()) <= 1000:
            raise AccountError(400, 'adjustment_reason_required', '请填写 3 至 1000 个字符的调整原因。')
        if not isinstance(idempotency_key,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,128}',idempotency_key):
            raise AccountError(400, 'invalid_idempotency_key', '积分调整请求编号无效。')
        reason = reason.strip()
        with self.transaction() as db:
            self._admin(db,actor_id)
            existing = db.execute('SELECT * FROM platform_credit_adjustments WHERE actor_id=? AND idempotency_key=?', (actor_id,idempotency_key)).fetchone()
            if existing is not None:
                if existing['account_id'] != target_id or existing['delta'] != delta or existing['reason'] != reason:
                    raise AccountError(409, 'adjustment_conflict', '同一调整编号不能用于不同账户、积分或原因。')
                return {**dict(existing),'already_applied':True}
            target = self._account(db,target_id,enabled=False)
            if target['balance'] + delta < 0:
                raise AccountError(409, 'insufficient_credits', '扣减不能超过账户可用积分，冻结积分不能直接修改。')
            if target['balance'] + target['held'] + delta > self.MAX_CREDITS:
                raise AccountError(409, 'balance_limit', '调整后账户总积分超过上限。')
            adjustment_id = 'ca-' + uuid.uuid4().hex
            event_key = 'adjustment:' + hashlib.sha256((actor_id+'\0'+idempotency_key).encode()).hexdigest()
            db.execute('UPDATE platform_accounts SET balance=balance+? WHERE id=?', (delta,target_id))
            ledger_id = self._entry(db,target_id,event_key,'adjustment',delta,0,adjustment_id,actor_id)
            now = self._now()
            db.execute('''INSERT INTO platform_credit_adjustments
                (id,actor_id,account_id,delta,reason,idempotency_key,ledger_id,balance_after,held_after,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (adjustment_id,actor_id,target_id,delta,reason,idempotency_key,
                    ledger_id,target['balance']+delta,target['held'],now))
            self._audit(db,actor_id,'adjust_credits',target_id,
                {'adjustment_id':adjustment_id,'delta':delta,'reason':reason,
                 'idempotency_key':idempotency_key,'ledger_id':ledger_id,
                 'balance_after':target['balance']+delta,'held_after':target['held']})
            return {**dict(db.execute('SELECT * FROM platform_credit_adjustments WHERE id=?', (adjustment_id,)).fetchone()),'already_applied':False}

    def admin_ledger(self, actor_id, account_id, limit=100):
        with self.connection() as db:
            self._admin(db,actor_id)
            self._account(db,account_id,enabled=False)
            return [dict(row) for row in db.execute('''SELECT ledger.*,adjustment.reason
                FROM platform_ledger ledger LEFT JOIN platform_credit_adjustments adjustment
                ON adjustment.ledger_id=ledger.id WHERE ledger.account_id=?
                ORDER BY ledger.id DESC LIMIT ?''', (account_id,min(max(int(limit),1),500)))]

    def _preserve_admin(self, db, target):
        if target['role'] == 'admin' and target['enabled']:
            count = db.execute("SELECT COUNT(*) FROM platform_accounts WHERE role = 'admin' AND enabled = 1").fetchone()[0]
            if count <= 1:
                raise AccountError(409, 'last_admin', '不能停用或降级唯一可用的管理员。')

    def set_role(self, actor_id, target_id, role):
        if role not in ('user', 'admin'):
            raise AccountError(400, 'invalid_role', '账户角色无效。')
        with self.transaction() as db:
            self._admin(db, actor_id)
            target = self._account(db, target_id, enabled=False)
            if target['role'] != role:
                if role != 'admin':
                    self._preserve_admin(db, target)
                db.execute('UPDATE platform_accounts SET role = ? WHERE id = ?', (role, target_id))
                self._audit(db, actor_id, 'set_role', target_id, {'role': role})
            return self._public(self._account(db, target_id, enabled=False))

    def disable_account(self, actor_id, target_id, disabled=True):
        if type(disabled) is not bool:
            raise AccountError(400, 'invalid_status', '账户状态无效。')
        with self.transaction() as db:
            self._admin(db, actor_id)
            target = self._account(db, target_id, enabled=False)
            if disabled:
                self._preserve_admin(db, target)
                db.execute('DELETE FROM platform_sessions WHERE account_id = ?', (target_id,))
            db.execute('UPDATE platform_accounts SET enabled = ? WHERE id = ?', (int(not disabled), target_id))
            self._audit(db, actor_id, 'disable_account', target_id, {'disabled': disabled})
            return self._public(self._account(db, target_id, enabled=False))

    def change_password(self, account_id, current_password, new_password):
        encoded = self._hash_password(self._password(new_password))
        with self.transaction() as db:
            account = self._account(db, account_id)
            if not self._verify_password(current_password, account['password_hash']):
                raise AccountError(401, 'invalid_credentials', '当前密码不正确。')
            db.execute('UPDATE platform_accounts SET password_hash = ? WHERE id = ?', (encoded, account_id))
            db.execute('DELETE FROM platform_sessions WHERE account_id = ?', (account_id,))
        return {'changed': True, 'sessions_revoked': True}

    def bootstrap_admin(self):
        credential_path = self.private_dir / 'admin-bootstrap.json'
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM platform_accounts WHERE legacy_owner = 1 AND role = 'admin' ORDER BY created_at LIMIT 1").fetchone()
            if existing is not None:
                return self._public(existing)
            # A preexisting administrator must never cause another hidden bootstrap.
            existing = db.execute("SELECT * FROM platform_accounts WHERE role = 'admin' ORDER BY created_at LIMIT 1").fetchone()
            if existing is not None:
                return self._public(existing)
            if credential_path.exists():
                try:
                    credential = json.loads(credential_path.read_text('utf-8'))
                    username, key = self._username(credential['username'])
                    password = self._password(credential['password'])
                    account_id = self._identifier(credential['account_id'], '管理员编号')
                except (OSError, ValueError, KeyError, AccountError) as error:
                    raise AccountError(500, 'bootstrap_unavailable', '管理员初始化凭据无法读取，请检查 private 目录。') from error
            else:
                username = 'admin-' + secrets.token_hex(6)
                _, key = self._username(username)
                password = secrets.token_urlsafe(32)
                account_id = 'u-' + uuid.uuid4().hex
                credential = {'account_id': account_id, 'username': username, 'password': password,
                              'notice': '本机初始化凭据。请登录后立即更换密码，勿公开或上传此文件。'}
                # Exclusive creation prevents a second process replacing the only
                # credential. Keep the file if a DB rollback happens: next start
                # can recover this same administrator rather than generate a new one.
                descriptor = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                    json.dump(credential, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
            db.execute('INSERT INTO platform_accounts(id,username,username_key,password_hash,role,legacy_owner,created_at) VALUES(?,?,?,?,?,1,?)',
                       (account_id, username, key, self._hash_password(password), 'admin', self._now()))
            return self._public(self._account(db, account_id))

    def migrate_legacy_resources(self, owner_id):
        counts = {'jobs': 0, 'assets': 0}
        with self.transaction() as db:
            owner = self._admin(db, owner_id)
            completed = db.execute("SELECT value FROM platform_metadata WHERE key = 'legacy_migration_complete'").fetchone()
            if completed:
                # A one-time schema upgrade may add private asset metadata after
                # ownership was already migrated. Never assign new resources.
                self._migrate_legacy_asset_metadata(db, completed['value'])
                return counts
            if not owner['legacy_owner']:
                raise AccountError(403, 'legacy_owner_required', '旧数据只允许迁移给本机初始化管理员。')
            for table, kind in (('jobs', 'job'), ('assets', 'asset')):
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone():
                    continue
                cursor = db.execute(f'''INSERT INTO platform_resource_owners(kind,resource_id,account_id,created_at)
                    SELECT ?, legacy.id, ?, ? FROM {table} legacy
                    WHERE NOT EXISTS(SELECT 1 FROM platform_resource_owners own WHERE own.kind = ? AND own.resource_id = legacy.id)''',
                                    (kind, owner_id, self._now(), kind))
                counts[table] = cursor.rowcount
            self._migrate_legacy_asset_metadata(db, owner_id)
            db.execute("INSERT INTO platform_metadata(key,value) VALUES('legacy_migration_complete',?)", (owner_id,))
        return counts

    def _migrate_legacy_asset_metadata(self, db, owner_id):
        if db.execute("SELECT 1 FROM platform_metadata WHERE key = 'legacy_asset_metadata_complete'").fetchone():
            return
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assets'").fetchone():
            rows = db.execute('''SELECT asset.id,asset.data FROM assets asset
                JOIN platform_resource_owners own ON own.resource_id=asset.id AND own.kind='asset' AND own.account_id=?
                WHERE NOT EXISTS(SELECT 1 FROM platform_asset_metadata meta WHERE meta.asset_id=asset.id AND meta.account_id=?)
                AND NOT EXISTS(SELECT 1 FROM platform_resource_owners other WHERE other.kind='asset'
                    AND other.resource_id=asset.id AND other.account_id != ?)''', (owner_id, owner_id, owner_id)).fetchall()
            for row in rows:
                try:
                    record = json.loads(row['data'])
                    if isinstance(record, dict):
                        self.remember_asset(owner_id, {**record, 'id': row['id']}, connection=db, _allow_disabled=True)
                except (TypeError, ValueError, AccountError):
                    # Invalid legacy display data must not become another user's
                    # metadata or prevent ownership migration from completing.
                    continue
        db.execute("INSERT INTO platform_metadata(key,value) VALUES('legacy_asset_metadata_complete',?)", (owner_id,))

    def grant_resource(self, account_id, kind, resource_id, connection=None):
        if kind not in ('job', 'asset'):
            raise AccountError(400, 'invalid_resource', '资源类型无效。')
        self._identifier(resource_id, '资源编号')
        with self._write(connection) as db:
            self._account(db, account_id)
            if kind == 'job':
                row = db.execute("SELECT account_id FROM platform_resource_owners WHERE kind = 'job' AND resource_id = ?", (resource_id,)).fetchone()
                if row and row['account_id'] != account_id:
                    raise AccountError(409, 'resource_owned', '该任务已属于其他账户。')
            db.execute('INSERT OR IGNORE INTO platform_resource_owners VALUES(?,?,?,?)', (kind, resource_id, account_id, self._now()))
        return {'kind': kind, 'resource_id': resource_id, 'account_id': account_id}

    def owns_resource(self, account_id, kind, resource_id, connection=None):
        if connection is not None:
            return bool(connection.execute('SELECT 1 FROM platform_resource_owners WHERE kind = ? AND resource_id = ? AND account_id = ?', (kind, resource_id, account_id)).fetchone())
        with self.connection() as db:
            return self.owns_resource(account_id, kind, resource_id, connection=db)

    def resource_ids(self, account_id, kind):
        with self.connection() as db:
            self._account(db, account_id)
            return [row[0] for row in db.execute('SELECT resource_id FROM platform_resource_owners WHERE kind = ? AND account_id = ?', (kind, account_id))]

    def remember_asset(self, account_id, record, connection=None, _allow_disabled=False):
        """Keep account display names and provenance out of global content data."""
        if not isinstance(record, dict):
            raise AccountError(400, 'invalid_asset_metadata', '素材信息格式无效。')
        asset_id = self._identifier(record.get('id'), '素材编号')
        value = {'name': '素材', 'original_asset_id': None, 'annotation_mode': None}
        name = record.get('name')
        if isinstance(name, str) and name.strip():
            value['name'] = ''.join(c for c in name.strip() if ord(c) >= 32)[:255] or '素材'
        original = record.get('original_asset_id')
        if original is not None:
            value['original_asset_id'] = self._identifier(original, '原素材编号')
        annotation = record.get('annotation_mode')
        if annotation is not None:
            if not isinstance(annotation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', annotation):
                raise AccountError(400, 'invalid_asset_metadata', '素材标注方式无效。')
            value['annotation_mode'] = annotation
        with self._write(connection) as db:
            self._account(db, account_id, enabled=not _allow_disabled)
            db.execute('INSERT INTO platform_asset_metadata(account_id,asset_id,data) VALUES(?,?,?) ON CONFLICT(account_id,asset_id) DO UPDATE SET data=excluded.data',
                       (account_id, asset_id, json.dumps(value, ensure_ascii=False)))
        return value

    def asset_metadata(self, account_id, asset_id):
        with self.connection() as db:
            self._account(db, account_id)
            row = db.execute('SELECT data FROM platform_asset_metadata WHERE account_id=? AND asset_id=?', (account_id, asset_id)).fetchone()
            if row:
                return json.loads(row['data'])
        # Explicit nulls overwrite any global provenance when the HTTP boundary
        # merges this over content metadata; do not inherit a different uploader.
        return {'name': '素材', 'original_asset_id': None, 'annotation_mode': None}

    def configure_pricing(self, actor_id, workflow_id, credits):
        self._identifier(workflow_id, '工作流编号')
        credits = self._integer(credits, '积分费用')
        with self.transaction() as db:
            self._admin(db, actor_id)
            db.execute('INSERT INTO platform_prices VALUES(?,?,?,?) ON CONFLICT(workflow_id) DO UPDATE SET credits=excluded.credits,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
                       (workflow_id, credits, actor_id, self._now()))
            self._audit(db, actor_id, 'configure_pricing', workflow_id, {'credits': credits})
        return self.pricing(workflow_id)

    def pricing(self, workflow_id, connection=None):
        if connection is not None:
            row = connection.execute('SELECT credits FROM platform_prices WHERE workflow_id = ?', (workflow_id,)).fetchone()
            return {'workflow_id': workflow_id, 'credits': row['credits'] if row else self.config['default_job_cost'], 'configured': row is not None}
        with self.connection() as db:
            return self.pricing(workflow_id, connection=db)

    def list_pricing(self, actor_id):
        with self.connection() as db:
            self._admin(db, actor_id)
            return [dict(row) for row in db.execute('SELECT * FROM platform_prices ORDER BY workflow_id')]

    def delete_pricing(self, actor_id, workflow_id):
        with self.transaction() as db:
            self._admin(db, actor_id)
            db.execute('DELETE FROM platform_prices WHERE workflow_id = ?', (workflow_id,))
            self._audit(db, actor_id, 'delete_pricing', workflow_id)
        return self.pricing(workflow_id)

    def configure_package(self, actor_id, package_id, title, credits, amount_minor, enabled=False, currency='CNY'):
        self._identifier(package_id, '套餐编号')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise AccountError(400, 'invalid_title', '套餐名称需为 1 至 80 个字符。')
        self._integer(credits, '套餐积分', 1)
        self._integer(amount_minor, '人民币金额（分）', 1)
        if type(enabled) is not bool or currency != 'CNY':
            raise AccountError(400, 'invalid_package', '套餐状态或币种无效。')
        with self.transaction() as db:
            self._admin(db, actor_id)
            db.execute('INSERT INTO platform_packages VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,credits=excluded.credits,amount_minor=excluded.amount_minor,currency=excluded.currency,enabled=excluded.enabled,updated_by=excluded.updated_by,updated_at=excluded.updated_at',
                       (package_id, title.strip(), credits, amount_minor, currency, int(enabled), actor_id, self._now()))
            self._audit(db, actor_id, 'configure_package', package_id, {'title': title.strip(), 'credits': credits, 'amount_minor': amount_minor, 'enabled': enabled})
        return {'id': package_id, 'title': title.strip(), 'credits': credits, 'amount_minor': amount_minor, 'currency': currency, 'enabled': enabled}

    def delete_package(self, actor_id, package_id):
        with self.transaction() as db:
            self._admin(db, actor_id)
            row = self._row(db.execute('SELECT * FROM platform_packages WHERE id = ?', (package_id,)).fetchone(), '套餐')
            db.execute('UPDATE platform_packages SET enabled = 0,updated_by = ?,updated_at = ? WHERE id = ?', (actor_id, self._now(), package_id))
            self._audit(db, actor_id, 'disable_package', package_id)
        return {**row, 'enabled': False}

    def packages(self, actor_id=None):
        with self.connection() as db:
            if actor_id is not None:
                self._admin(db, actor_id)
            rows = db.execute('SELECT * FROM platform_packages ' + ('' if actor_id is not None else 'WHERE enabled = 1 ') + 'ORDER BY amount_minor, id')
            return [{**dict(row), 'enabled': bool(row['enabled'])} for row in rows]

    def payment_status(self):
        packages = self.packages()
        enabled = self.config['payment_mode'] == 'manual' and bool(packages)
        return {'enabled': enabled, 'mode': 'manual' if enabled else 'disabled',
                'automatic_payments': False, 'payment_methods': sorted(self.PAYMENT_METHODS),
                'instructions': self.config['payment_instructions'],
                'message': '充值订单须经管理员核对实际收款后到账。' if enabled else '管理员尚未配置可用的充值套餐。'}

    def create_order(self, account_id, package_id, idempotency_key, payment_method='admin_contact'):
        if not isinstance(idempotency_key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,120}', idempotency_key):
            raise AccountError(400, 'invalid_idempotency_key', '订单请求编号无效。')
        if payment_method not in self.PAYMENT_METHODS:
            raise AccountError(400, 'invalid_payment_method', '充值方式无效。')
        now = self._now()
        with self.transaction() as db:
            self._account(db, account_id)
            existing = db.execute('SELECT * FROM platform_orders WHERE account_id = ? AND idempotency_key = ?', (account_id, idempotency_key)).fetchone()
            if existing:
                if existing['package_id'] != package_id or existing['payment_method'] != payment_method:
                    raise AccountError(409, 'idempotency_conflict', '同一订单请求编号不能用于不同套餐或充值方式。')
                return self._public_order(existing)
            if self.config['payment_mode'] != 'manual':
                raise AccountError(503, 'payments_disabled', '充值渠道尚未启用。')
            package = db.execute('SELECT * FROM platform_packages WHERE id = ? AND enabled = 1', (package_id,)).fetchone()
            if not package:
                raise AccountError(409, 'package_unavailable', '该充值套餐尚未启用或已下架。')
            order_id = uuid.uuid4().hex
            db.execute('INSERT INTO platform_orders(id,account_id,package_id,package_title,credits,amount_minor,currency,payment_method,status,idempotency_key,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (order_id, account_id, package_id, package['title'], package['credits'], package['amount_minor'], package['currency'], payment_method, 'pending', idempotency_key, now, now + 86400))
            return self._public_order(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone())

    @staticmethod
    def _public_order(row):
        value = dict(row)
        value['method'] = value['payment_method']
        value.pop('payment_reference_key', None)
        return value

    def get_order(self, order_id, account_id=None):
        with self.connection() as db:
            if account_id is not None:
                self._account(db, account_id)
                row = db.execute('SELECT * FROM platform_orders WHERE id = ? AND account_id = ?', (order_id, account_id)).fetchone()
            else:
                row = db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone()
            return self._public_order(self._row(row, '充值订单'))

    def mark_order_checkout(self, order_id, method, checkout_reference):
        """Trusted server call made before requesting a provider checkout.

        Even if a gateway request times out, the order stays reserved for that
        provider. Cancel it and create another order rather than manually credit
        a payment whose notification might arrive later.
        """
        if method not in ('alipay', 'wechat'):
            raise AccountError(400, 'invalid_payment_method', '该方式不支持自动收款。')
        self._identifier(checkout_reference, '收款请求编号')
        with self.transaction() as db:
            order = self._row(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone(), '充值订单')
            if order['payment_method'] != method or order['status'] != 'pending' or order['expires_at'] <= self._now():
                raise AccountError(409, 'order_not_pending', '订单状态或充值方式不允许发起收款。')
            if order['checkout_reference'] is not None:
                if order['checkout_reference'] != checkout_reference:
                    raise AccountError(409, 'checkout_conflict', '此订单已经使用另一收款请求。')
                return self._public_order(order)
            db.execute('UPDATE platform_orders SET checkout_reference = ?,checkout_created_at = ? WHERE id = ?', (checkout_reference, self._now(), order_id))
            return self._public_order(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone())

    def list_orders(self, account_id=None, actor_id=None, limit=100):
        limit = min(max(int(limit), 1), 500)
        with self.transaction() as db:
            if actor_id is not None:
                self._admin(db, actor_id)
            elif account_id is not None:
                self._account(db, account_id)
            else:
                raise AccountError(403, 'admin_required', '查看所有订单需要管理员权限。')
            db.execute("UPDATE platform_orders SET status = 'expired' WHERE status = 'pending' AND expires_at <= ?", (self._now(),))
            if account_id is not None:
                rows = db.execute('SELECT * FROM platform_orders WHERE account_id = ? ORDER BY created_at DESC, id DESC LIMIT ?', (account_id, limit))
            else:
                rows = db.execute('SELECT * FROM platform_orders ORDER BY created_at DESC, id DESC LIMIT ?', (limit,))
            return [self._public_order(row) for row in rows]

    def cancel_order(self, account_id, order_id):
        with self.transaction() as db:
            self._account(db, account_id)
            order = self._row(db.execute('SELECT * FROM platform_orders WHERE id = ? AND account_id = ?', (order_id, account_id)).fetchone(), '充值订单')
            if order['status'] == 'confirmed':
                raise AccountError(409, 'order_confirmed', '订单已到账，不能取消。')
            if order['status'] == 'pending':
                db.execute("UPDATE platform_orders SET status = 'cancelled' WHERE id = ?", (order_id,))
                order['status'] = 'cancelled'
            return self._public_order(order)

    def _entry(self, db, account_id, event_key, event, amount, held_amount, resource_id, actor_id=None):
        account = self._account(db, account_id, enabled=False)
        return db.execute('INSERT INTO platform_ledger(account_id,event_key,event,amount,held_amount,balance_after,held_after,resource_id,actor_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (account_id, event_key, event, amount, held_amount, account['balance'], account['held'], resource_id, actor_id, self._now())).lastrowid

    def confirm_order(self, actor_id, order_id, confirmation_reference):
        if not isinstance(confirmation_reference, str) or not 3 <= len(confirmation_reference.strip()) <= 200:
            raise AccountError(400, 'confirmation_required', '请输入核实收款后的唯一凭证编号。')
        reference = confirmation_reference.strip()
        with self.transaction() as db:
            self._admin(db, actor_id)
            order = self._row(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone(), '充值订单')
            if order['checkout_reference'] is not None:
                raise AccountError(409, 'automatic_checkout_exists', '此订单已发起自动收款，须由支付通知确认，不能手工重复入账。')
            if order['status'] == 'confirmed':
                if order['confirmation_reference'] != reference:
                    raise AccountError(409, 'confirmation_conflict', '该订单已经使用另一凭证确认到账。')
                return self._public_order(order)
            if order['status'] != 'pending' or order['expires_at'] <= self._now():
                raise AccountError(409, 'order_not_pending', '该订单已取消或过期，不能确认到账。')
            account = self._account(db, order['account_id'])
            if account['balance'] + account['held'] + order['credits'] > self.MAX_CREDITS:
                raise AccountError(409, 'balance_limit', '账户积分余额超过可用上限。')
            reference_key = order['payment_method'] + ':' + reference
            if db.execute('SELECT 1 FROM platform_orders WHERE payment_reference_key = ?', (reference_key,)).fetchone():
                raise AccountError(409, 'receipt_reused', '该收款凭证已经用于另一笔订单。')
            db.execute('UPDATE platform_accounts SET balance = balance + ? WHERE id = ?', (order['credits'], order['account_id']))
            now = self._now()
            db.execute("UPDATE platform_orders SET status='confirmed',confirmed_at=?,confirmed_by=?,confirmation_reference=?,payment_reference_key=? WHERE id=?", (now, actor_id, reference, reference_key, order_id))
            self._entry(db, order['account_id'], 'recharge:' + order_id, 'recharge', order['credits'], 0, order_id, actor_id)
            self._audit(db, actor_id, 'confirm_order', order_id, {'confirmation_reference': reference, 'credits': order['credits'], 'amount_minor': order['amount_minor']})
            return self._public_order(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone())

    def credit_verified_order(self, order_id, method, amount_minor, currency, payment_reference):
        try:
            return self._credit_verified_order(order_id, method, amount_minor, currency, payment_reference)
        except AccountError as error:
            # Callback signatures are verified by the HTTP adapter. Preserve
            # authenticated payment evidence even when a late or conflicting
            # notification cannot safely be credited automatically.
            if (method in ('alipay', 'wechat') and type(amount_minor) is int and amount_minor > 0
                    and isinstance(currency, str) and len(currency) <= 16
                    and isinstance(payment_reference, str) and 3 <= len(payment_reference) <= 200
                    and isinstance(order_id, str) and len(order_id) <= 160):
                self._record_payment_review(order_id, method, amount_minor, currency, payment_reference, error.code)
            raise

    def _credit_verified_order(self, order_id, method, amount_minor, currency, payment_reference):
        """Trusted callback only: root verifies provider signature before calling.

        The amount, owner and credits come from the frozen server order, and
        provider transaction identifiers are unique within their provider scope.
        No frontend route may call this merely because a redirect says success.
        """
        if method not in ('alipay', 'wechat'):
            raise AccountError(400, 'invalid_payment_method', '自动到账渠道无效。')
        self._integer(amount_minor, '实际收款金额', 1)
        if currency != 'CNY' or not isinstance(payment_reference, str) or not 3 <= len(payment_reference) <= 200:
            raise AccountError(400, 'invalid_payment', '支付凭证或币种无效。')
        reference_key = method + ':' + payment_reference
        with self.transaction() as db:
            if self._refund_recorded(db, method, payment_reference):
                raise AccountError(409, 'payment_refunded', '该交易已登记实际退款，不能再次入账。')
            order = self._row(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone(), '充值订单')
            if order['payment_method'] != method or order['amount_minor'] != amount_minor or order['currency'] != currency:
                raise AccountError(409, 'payment_mismatch', '支付通知与订单的充值方式、金额或币种不匹配。')
            if not order['checkout_reference']:
                raise AccountError(409, 'checkout_missing', '该订单尚未发起服务端自动收款请求。')
            if order['status'] == 'confirmed':
                if order['payment_reference_key'] != reference_key:
                    raise AccountError(409, 'confirmation_conflict', '该订单已经使用另一凭证到账。')
                return self._public_order(order)
            if order['status'] != 'pending' or order['expires_at'] <= self._now():
                raise AccountError(409, 'order_not_pending', '订单已取消或过期，需人工核对支付退款。')
            if db.execute('SELECT 1 FROM platform_orders WHERE payment_reference_key = ?', (reference_key,)).fetchone():
                raise AccountError(409, 'receipt_reused', '该支付交易已经用于另一笔订单。')
            account = self._account(db, order['account_id'])
            if account['balance'] + account['held'] + order['credits'] > self.MAX_CREDITS:
                raise AccountError(409, 'balance_limit', '账户积分余额超过可用上限。')
            db.execute('UPDATE platform_accounts SET balance = balance + ? WHERE id = ?', (order['credits'], order['account_id']))
            db.execute("UPDATE platform_orders SET status='confirmed',confirmed_at=?,confirmation_reference=?,payment_reference_key=? WHERE id=?", (self._now(), payment_reference, reference_key, order_id))
            self._entry(db, order['account_id'], 'recharge:' + order_id, 'recharge', order['credits'], 0, order_id)
            return self._public_order(db.execute('SELECT * FROM platform_orders WHERE id = ?', (order_id,)).fetchone())

    def _record_payment_review(self, order_id, method, amount_minor, currency, reference, reason):
        frozen = json.dumps([order_id, method, amount_minor, currency, reference], ensure_ascii=False)
        review_id = hashlib.sha256(frozen.encode('utf-8')).hexdigest()
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO platform_payment_reviews VALUES(?,?,?,?,?,?,?,?)',
                       (review_id, order_id, method, amount_minor, currency, reference, reason, self._now()))
        return review_id

    @staticmethod
    def _refund_recorded(db, method, reference):
        return bool(db.execute('''SELECT 1 FROM platform_payment_reviews review
            JOIN platform_payment_resolutions resolution ON resolution.review_id = review.id
            WHERE review.method=? AND review.payment_reference=? AND resolution.decision='refund_recorded' ''', (method, reference)).fetchone())

    def list_payment_reviews(self, actor_id, limit=100, include_resolved=False):
        with self.connection() as db:
            self._admin(db, actor_id)
            query = '''SELECT review.*, resolution.decision, resolution.note, resolution.refund_reference,
                resolution.actor_id AS resolved_by, resolution.created_at AS resolved_at
                FROM platform_payment_reviews review
                LEFT JOIN platform_payment_resolutions resolution ON resolution.review_id = review.id'''
            if not include_resolved:
                query += ' WHERE resolution.review_id IS NULL'
            query += ' ORDER BY review.created_at DESC,review.id LIMIT ?'
            return [dict(row) for row in db.execute(query, (min(max(int(limit), 1), 500),))]

    def resolve_payment_review(self, actor_id, review_id, decision, note, refund_reference=None):
        if decision not in ('credit', 'refund_recorded') or not isinstance(note, str) or not 3 <= len(note.strip()) <= 1000:
            raise AccountError(400, 'review_note_required', '请填写核对结果及说明。')
        if decision == 'refund_recorded':
            if not isinstance(refund_reference, str) or not 3 <= len(refund_reference.strip()) <= 200:
                raise AccountError(400, 'refund_reference_required', '请填写已经实际完成的线下退款凭证编号。')
            refund_reference = refund_reference.strip()
        else:
            refund_reference = None
        with self.transaction() as db:
            self._admin(db, actor_id)
            review = self._row(db.execute('SELECT * FROM platform_payment_reviews WHERE id=?', (review_id,)).fetchone(), '支付异常记录')
            existing = db.execute('SELECT * FROM platform_payment_resolutions WHERE review_id=?', (review_id,)).fetchone()
            if existing:
                if existing['decision'] != decision or existing['refund_reference'] != refund_reference:
                    raise AccountError(409, 'review_already_resolved', '该支付异常已经按其他方式处理。')
                return dict(existing)
            if decision == 'credit':
                if self._refund_recorded(db, review['method'], review['payment_reference']):
                    raise AccountError(409, 'payment_refunded', '该交易已登记实际退款，不能再次入账。')
                order = self._row(db.execute('SELECT * FROM platform_orders WHERE id=?', (review['order_id'],)).fetchone(), '充值订单')
                if (order['payment_method'] != review['method'] or order['amount_minor'] != review['amount_minor']
                        or order['currency'] != review['currency'] or not order['checkout_reference']):
                    raise AccountError(409, 'payment_mismatch', '收款凭证与冻结订单不匹配，不能直接入账。')
                key = review['method'] + ':' + review['payment_reference']
                other = db.execute('SELECT id FROM platform_orders WHERE payment_reference_key=?', (key,)).fetchone()
                if other and other['id'] != order['id']:
                    raise AccountError(409, 'receipt_reused', '该支付交易已用于另一笔订单。')
                if order['status'] == 'confirmed' and order['payment_reference_key'] != key:
                    raise AccountError(409, 'confirmation_conflict', '订单已使用另一交易到账，应核对重复付款。')
                if order['status'] != 'confirmed':
                    account = self._account(db, order['account_id'])
                    if account['balance'] + account['held'] + order['credits'] > self.MAX_CREDITS:
                        raise AccountError(409, 'balance_limit', '账户积分余额超过可用上限。')
                    db.execute('UPDATE platform_accounts SET balance=balance+? WHERE id=?', (order['credits'], order['account_id']))
                    db.execute("UPDATE platform_orders SET status='confirmed',confirmed_at=?,confirmed_by=?,confirmation_reference=?,payment_reference_key=? WHERE id=?", (self._now(), actor_id, review['payment_reference'], key, order['id']))
                    self._entry(db, order['account_id'], 'recharge:' + order['id'], 'recharge', order['credits'], 0, order['id'], actor_id)
            else:
                key = review['method'] + ':' + review['payment_reference']
                if db.execute('SELECT 1 FROM platform_orders WHERE payment_reference_key=?', (key,)).fetchone():
                    raise AccountError(409, 'payment_already_credited', '该交易已经入账，退款须另行办理积分冲正。')
                if db.execute('SELECT 1 FROM platform_payment_resolutions WHERE refund_reference=?', (refund_reference,)).fetchone():
                    raise AccountError(409, 'refund_reference_reused', '该退款凭证已经用于另一条异常记录。')
            db.execute('INSERT INTO platform_payment_resolutions VALUES(?,?,?,?,?,?)', (review_id, decision, actor_id, note.strip(), refund_reference, self._now()))
            self._audit(db, actor_id, 'resolve_payment_review', review_id, {'decision': decision, 'note': note.strip(), 'refund_reference': refund_reference})
            return dict(db.execute('SELECT * FROM platform_payment_resolutions WHERE review_id=?', (review_id,)).fetchone())

    def reserve(self, account_id, job_id, workflow_id, connection=None, retry_released=False):
        self._identifier(job_id, '任务编号')
        self._identifier(workflow_id, '工作流编号')
        with self._write(connection) as db:
            self._account(db, account_id)
            existing = db.execute('SELECT * FROM platform_reservations WHERE job_id = ?', (job_id,)).fetchone()
            if existing:
                existing = dict(existing)
                if existing['account_id'] != account_id or existing['workflow_id'] != workflow_id:
                    raise AccountError(409, 'reservation_conflict', '该任务已使用其他账户或工作流计费。')
                if existing['status'] != 'released':
                    return existing
                if not retry_released:
                    raise AccountError(409, 'reservation_released', '该任务的预扣已释放，重试必须重新确认预扣。')
                credits, attempt = existing['credits'], existing['attempt'] + 1
            else:
                credits, attempt = self.pricing(workflow_id, connection=db)['credits'], 1
            changed = db.execute('UPDATE platform_accounts SET balance = balance - ?,held = held + ? WHERE id = ? AND enabled = 1 AND balance >= ?',
                                 (credits, credits, account_id, credits)).rowcount
            if not changed:
                raise AccountError(402, 'insufficient_credits', '积分不足，请充值后再生成。')
            now = self._now()
            db.execute("INSERT INTO platform_reservations VALUES(?,?,?,?,?,'held',?,?) ON CONFLICT(job_id) DO UPDATE SET attempt=excluded.attempt,status='held',updated_at=excluded.updated_at",
                       (job_id, account_id, workflow_id, credits, attempt, now, now))
            self._entry(db, account_id, f'reserve:{job_id}:{attempt}', 'reserve', -credits, credits, job_id)
            return dict(db.execute('SELECT * FROM platform_reservations WHERE job_id = ?', (job_id,)).fetchone())

    def reservation(self, job_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM platform_reservations WHERE job_id = ?', (job_id,)).fetchone()
            return dict(row) if row else None

    def _finish(self, job_id, release, connection=None):
        with self._write(connection) as db:
            row = db.execute('SELECT * FROM platform_reservations WHERE job_id = ?', (job_id,)).fetchone()
            if row is None:
                return None  # Legacy tasks were never charged.
            reservation = dict(row)
            if reservation['status'] != 'held':
                return reservation  # First terminal transition wins; never refund a settled task.
            credits, owner = reservation['credits'], reservation['account_id']
            status = 'released' if release else 'settled'
            if release:
                db.execute('UPDATE platform_accounts SET balance=balance+?,held=held-? WHERE id=?', (credits, credits, owner))
            else:
                db.execute('UPDATE platform_accounts SET held=held-? WHERE id=?', (credits, owner))
            db.execute('UPDATE platform_reservations SET status=?,updated_at=? WHERE job_id=?', (status, self._now(), job_id))
            self._entry(db, owner, f'{status}:{job_id}:{reservation["attempt"]}', 'release' if release else 'settle', credits if release else 0, -credits, job_id)
            reservation.update(status=status, updated_at=self._now())
            return reservation

    def settle(self, job_id, connection=None):
        return self._finish(job_id, release=False, connection=connection)

    def release(self, job_id, connection=None):
        return self._finish(job_id, release=True, connection=connection)

    @staticmethod
    def _generation_review_eligible(record):
        return (record.get('status') in ('unknown', 'abandoned') or
                record.get('status') == 'failed' and record.get('failure_phase') == 'output')

    def list_generation_reviews(self, actor_id, limit=100):
        """Pending consumption reviews expose metadata, never prompts or graphs."""
        with self.connection() as db:
            self._admin(db, actor_id)
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
                return []
            rows = db.execute('''SELECT reservation.*, account.username, job.data
                FROM platform_reservations reservation
                JOIN platform_accounts account ON account.id=reservation.account_id
                JOIN jobs job ON job.id=reservation.job_id
                WHERE reservation.status='held'
                ORDER BY reservation.updated_at DESC, reservation.job_id''')
            result = []
            maximum = min(max(int(limit), 1), 500)
            for row in rows:
                try:
                    record = json.loads(row['data'])
                except (TypeError, ValueError):
                    continue
                if not isinstance(record, dict) or not self._generation_review_eligible(record):
                    continue
                result.append({'job_id': row['job_id'], 'workflow_id': row['workflow_id'],
                               'account_id': row['account_id'], 'username': row['username'],
                               'status': record['status'], 'prompt_id': record.get('prompt_id'),
                               'credits': row['credits'], 'created_at': row['created_at'],
                               'updated_at': row['updated_at']})
                if len(result) >= maximum:
                    break
            return result

    def resolve_generation_review(self, actor_id, job_id, decision, confirmation_reference, note):
        """Record an administrator's verified compute-consumption decision.

        Releasing local credits never claims an external provider refunded money
        or stopped a task. Normal queued/running work cannot be changed here.
        """
        if decision not in ('settle', 'release'):
            raise AccountError(400, 'invalid_decision', '任务核对结果无效。')
        if not isinstance(confirmation_reference, str) or not 3 <= len(confirmation_reference.strip()) <= 200:
            raise AccountError(400, 'confirmation_required', '请输入真实核对依据的凭证编号。')
        if not isinstance(note, str) or not 3 <= len(note.strip()) <= 1000:
            raise AccountError(400, 'review_note_required', '请填写核对依据及说明。')
        final_status = 'settled' if decision == 'settle' else 'released'
        with self.transaction() as db:
            self._admin(db, actor_id)
            reservation = self._row(db.execute('SELECT * FROM platform_reservations WHERE job_id=?', (job_id,)).fetchone(), '任务预扣记录')
            if reservation['status'] != 'held':
                if reservation['status'] != final_status:
                    raise AccountError(409, 'review_already_resolved', '此任务积分已按另一结果处理，不能反向改账。')
                return {**reservation, 'decision': decision, 'already_resolved': True}
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
                raise AccountError(409, 'generation_review_unavailable', '任务信息无法读取，不能核对积分。')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
            try:
                record = json.loads(row['data']) if row is not None else None
            except (TypeError, ValueError) as error:
                raise AccountError(409, 'generation_review_unavailable', '任务信息无法读取，不能核对积分。') from error
            if not isinstance(record, dict) or not self._generation_review_eligible(record):
                raise AccountError(409, 'generation_review_not_pending', '该任务不是待核对状态；不能在此停止正常排队或运行。')
            resolved = self._finish(job_id, release=decision == 'release', connection=db)
            self._audit(db, actor_id, 'resolve_generation_review', job_id,
                        {'decision': decision, 'confirmation_reference': confirmation_reference.strip(),
                         'note': note.strip(), 'previous_status': record['status'],
                         'credits': reservation['credits'], 'workflow_id': reservation['workflow_id']})
            return {**resolved, 'decision': decision, 'already_resolved': False}

    def ledger(self, account_id, limit=100):
        with self.connection() as db:
            self._account(db, account_id, enabled=False)
            return [dict(row) for row in db.execute('SELECT * FROM platform_ledger WHERE account_id=? ORDER BY id DESC LIMIT ?', (account_id, min(max(int(limit), 1), 500)))]
