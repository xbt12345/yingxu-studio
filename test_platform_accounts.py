"""Account and ledger tests use disposable DBs; never touch the studio store."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from platform_accounts import AccountError, PlatformAccounts, SCHEMA


class PlatformAccountsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.now = [1_790_000_000]
        self.accounts = PlatformAccounts(self.directory / 'workspace.sqlite3', self.directory / 'private',
                                         password_rounds=100_000, clock=lambda: self.now[0])
        self.admin = self.accounts.bootstrap_admin()
        self.user = self.accounts.register('test-user', 'good-password-for-tests')

    def assert_error(self, code, action):
        with self.assertRaises(AccountError) as caught:
            action()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def funded(self, credits=100, amount_minor=1000, method='admin_contact'):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', credits, amount_minor, enabled=True)
        order = self.accounts.create_order(self.user['id'], 'test-pack', 'fund-test-0001', method)
        self.accounts.confirm_order(self.admin['id'], order['id'], 'verified-receipt-0001')
        return order

    def parallel(self, count, action):
        barrier = threading.Barrier(count)

        def run(index):
            barrier.wait()
            try:
                return action(index)
            except AccountError as error:
                return error

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(run, range(count)))

    def test_regular_registration_hashes_password_and_never_claims_admin(self):
        self.assertEqual('user', self.user['role'])
        same = self.accounts.register('other-user', 'good-password-for-tests')
        with self.accounts.connection() as db:
            hashes = [row['password_hash'] for row in db.execute('SELECT password_hash FROM platform_accounts WHERE id IN (?,?)', (self.user['id'], same['id']))]
        self.assertEqual(2, len(set(hashes)))
        self.assertTrue(all(value.startswith('pbkdf2_sha256$100000$') for value in hashes))
        self.assertTrue(all('good-password-for-tests' not in value for value in hashes))
        self.assertNotIn('password_hash', self.user)
        self.assert_error('username_taken', lambda: self.accounts.register('TEST-USER', 'second-good-password'))
        self.assert_error('invalid_password', lambda: self.accounts.register('short-user', 'short'))

    def test_admin_creates_zero_balance_user_without_sessions_or_private_response(self):
        password = 'new-account-password-123'
        created = self.accounts.admin_create_user(self.admin['id'], 'created-user', password)
        self.assertEqual(('user',True,False,0,0),
                         (created['role'],created['enabled'],created['legacy_owner'],created['balance'],created['held']))
        self.assertEqual(self.now[0],created['created_at'])
        self.assertNotIn('password_hash',created)
        self.assertNotIn('username_key',created)
        self.assertNotIn(password,json.dumps(created))
        with self.accounts.connection() as db:
            stored = dict(db.execute('SELECT * FROM platform_accounts WHERE id=?',(created['id'],)).fetchone())
            self.assertTrue(stored['password_hash'].startswith('pbkdf2_sha256$100000$'))
            self.assertNotIn(password,stored['password_hash'])
            for table in ('platform_sessions','platform_ledger','platform_resource_owners'):
                self.assertEqual(0,db.execute(f'SELECT COUNT(*) FROM {table} WHERE account_id=?',(created['id'],)).fetchone()[0])
        self.assertEqual(created['id'],self.accounts.authenticate('CREATED-USER',password)['id'])
        audit = self.accounts.admin_audit(self.admin['id'])[0]
        self.assertEqual(('create_user',created['id'],self.admin['id']),
                         (audit['action'],audit['target'],audit['actor_id']))
        self.assertEqual({'username':'created-user','role':'user','enabled':True},audit['data'])
        self.assertNotIn(password,json.dumps(audit))

    def test_admin_can_create_an_explicit_administrator_without_legacy_ownership(self):
        created = self.accounts.admin_create_user(self.admin['id'],'second-admin','new-admin-password-123','admin')
        self.assertEqual('admin',created['role'])
        self.assertFalse(created['legacy_owner'])
        self.assertTrue(created['enabled'])
        self.assertEqual(0,created['balance']+created['held'])
        with self.accounts.connection() as db:
            self.assertEqual(0,db.execute('SELECT COUNT(*) FROM platform_sessions WHERE account_id=?',(created['id'],)).fetchone()[0])

    def test_admin_creation_normalizes_unicode_and_rejects_existing_registration_names(self):
        created = self.accounts.admin_create_user(self.admin['id'],'  Ｎｅｗ．Ｕｓｅｒ  ','new-account-password-123')
        self.assertEqual('New.User',created['username'])
        self.assert_error('username_taken',lambda:self.accounts.admin_create_user(self.admin['id'],'new.user','another-password-123'))
        self.assert_error('username_taken',lambda:self.accounts.admin_create_user(self.admin['id'],'ＴＥＳＴ－ＵＳＥＲ','another-password-123'))
        self.assertEqual(3,len(self.accounts.list_accounts(self.admin['id'])))
        self.assertEqual(1,len(self.accounts.admin_audit(self.admin['id'])))

    def test_admin_creation_concurrent_duplicate_name_creates_and_audits_once(self):
        results = self.parallel(4,lambda index:self.accounts.admin_create_user(self.admin['id'],
                              'CONCURRENT-USER' if index%2 else 'ｃｏｎｃｕｒｒｅｎｔ－ｕｓｅｒ','new-account-password-123'))
        self.assertEqual(1,len([result for result in results if isinstance(result,dict)]))
        self.assertEqual(3,len([result for result in results if isinstance(result,AccountError) and result.code=='username_taken']))
        self.assertEqual(1,len(self.accounts.admin_audit(self.admin['id'])))

    def test_admin_creation_rechecks_live_authority_and_rejects_normal_or_disabled_actors(self):
        self.assert_error('admin_required',lambda:self.accounts.admin_create_user(self.user['id'],'forbidden-user','new-account-password-123','admin'))
        alternate = self.accounts.admin_create_user(self.admin['id'],'alternate-admin','new-account-password-123','admin')
        self.accounts.disable_account(self.admin['id'],alternate['id'],True)
        self.assert_error('account_disabled',lambda:self.accounts.admin_create_user(alternate['id'],'forbidden-user','new-account-password-123'))
        self.accounts.disable_account(self.admin['id'],alternate['id'],False)
        self.accounts.set_role(self.admin['id'],alternate['id'],'user')
        self.assert_error('admin_required',lambda:self.accounts.admin_create_user(alternate['id'],'forbidden-user','new-account-password-123'))
        with self.accounts.connection() as db:
            self.assertIsNone(db.execute("SELECT id FROM platform_accounts WHERE username='forbidden-user'").fetchone())

    def test_admin_creation_uses_existing_username_and_password_validators(self):
        for username in ('ab','invalid name','invalid/name','a'*81,None,123):
            with self.subTest(username=username):
                self.assert_error('invalid_username',lambda:self.accounts.admin_create_user(self.admin['id'],username,'new-account-password-123'))
        for password in ('short',' '*10,'a'*129,None,123,'bad-surrogate-\ud800-password'):
            with self.subTest(password_type=type(password).__name__):
                self.assert_error('invalid_password',lambda:self.accounts.admin_create_user(self.admin['id'],'valid-name',password))
        for role in ('superadmin','',None,True):
            with self.subTest(role=role):
                self.assert_error('invalid_role',lambda:self.accounts.admin_create_user(self.admin['id'],'valid-name','new-account-password-123',role))
        self.assertEqual(2,len(self.accounts.list_accounts(self.admin['id'])))
        self.assertEqual([],self.accounts.admin_audit(self.admin['id']))

    def test_admin_creation_audit_failure_rolls_back_account_and_preserves_the_original_error(self):
        for error in (RuntimeError('audit storage unavailable'),sqlite3.IntegrityError('audit insert rejected')):
            with self.subTest(error_type=type(error).__name__):
                with patch.object(self.accounts,'_audit',side_effect=error),self.assertRaises(type(error)) as caught:
                    self.accounts.admin_create_user(self.admin['id'],'rollback-user','new-account-password-123')
                self.assertIs(error,caught.exception)
                self.assertEqual(2,len(self.accounts.list_accounts(self.admin['id'])))
                self.assertEqual([],self.accounts.admin_audit(self.admin['id']))
        created = self.accounts.admin_create_user(self.admin['id'],'rollback-user','new-account-password-123')
        self.assertEqual(1,len(self.accounts.admin_audit(self.admin['id'])))
        self.assertEqual('rollback-user',created['username'])

    def test_bootstrap_is_private_once_and_survives_restart(self):
        path = self.directory / 'private' / 'admin-bootstrap.json'
        before = path.read_bytes()
        credentials = json.loads(before)
        authenticated = self.accounts.authenticate(credentials['username'], credentials['password'])
        self.assertEqual(self.admin['id'], authenticated['id'])
        self.assertTrue(authenticated['legacy_owner'])
        reloaded = PlatformAccounts(self.directory / 'workspace.sqlite3', self.directory / 'private', password_rounds=100_000)
        self.assertEqual(self.admin['id'], reloaded.bootstrap_admin()['id'])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(2, len(reloaded.list_accounts(self.admin['id'])))

    def test_no_administrator_from_first_public_registration(self):
        alternate = PlatformAccounts(self.directory / 'fresh.sqlite3', self.directory / 'new-private', password_rounds=100_000)
        first = alternate.register('first-user', 'long-good-password')
        self.assertEqual('user', first['role'])
        self.assertFalse(first['legacy_owner'])
        self.assert_error('admin_required', lambda: alternate.configure_pricing(first['id'], 'workflow-one', 0))

    def test_sessions_are_hashed_expire_and_require_csrf(self):
        session = self.accounts.create_session(self.user['id'], lifetime=30)
        self.assertEqual(self.user['id'], self.accounts.resolve_session(session['token'])['id'])
        self.assertEqual(session['csrf_token'], self.accounts.resolve_session(session['token'])['csrf_token'])
        self.assertEqual(self.user['id'], self.accounts.require_csrf(session['token'], session['csrf_token'])['id'])
        self.assert_error('csrf_failed', lambda: self.accounts.require_csrf(session['token'], 'invalid'))
        self.assert_error('csrf_failed', lambda: self.accounts.require_csrf(session['token'], '无效安全令牌'))
        with self.accounts.connection() as db:
            stored = dict(db.execute('SELECT * FROM platform_sessions').fetchone())
        self.assertNotIn(session['token'], stored.values())
        self.assertNotIn(session['csrf_token'], stored.values())
        self.now[0] += 30
        self.assert_error('login_required', lambda: self.accounts.resolve_session(session['token']))
        new = self.accounts.create_session(self.user['id'])
        self.accounts.logout(new['token'])
        self.assert_error('login_required', lambda: self.accounts.resolve_session(new['token']))

    def test_password_change_revokes_sessions_and_disabled_account_is_denied(self):
        session = self.accounts.create_session(self.user['id'])
        self.assert_error('invalid_credentials', lambda: self.accounts.change_password(self.user['id'], 'wrong-password', 'new-good-password'))
        self.accounts.change_password(self.user['id'], 'good-password-for-tests', 'new-good-password')
        self.assert_error('login_required', lambda: self.accounts.resolve_session(session['token']))
        self.assert_error('invalid_credentials', lambda: self.accounts.authenticate('test-user', 'good-password-for-tests'))
        self.assertEqual(self.user['id'], self.accounts.authenticate('test-user', 'new-good-password')['id'])
        replacement = self.accounts.create_session(self.user['id'])
        self.accounts.disable_account(self.admin['id'], self.user['id'])
        self.assert_error('login_required', lambda: self.accounts.resolve_session(replacement['token']))
        self.assert_error('account_disabled', lambda: self.accounts.create_session(self.user['id']))
        self.assert_error('invalid_credentials', lambda: self.accounts.authenticate('test-user', 'new-good-password'))
        self.accounts.disable_account(self.admin['id'], self.user['id'], disabled=False)
        self.assertEqual(self.user['id'], self.accounts.authenticate('test-user', 'new-good-password')['id'])

    def test_login_and_password_change_cannot_leave_old_password_session_valid(self):
        results = self.parallel(2, lambda index: self.accounts.login('test-user', 'good-password-for-tests') if index == 0 else self.accounts.change_password(self.user['id'], 'good-password-for-tests', 'new-good-password'))
        login = results[0]
        if not isinstance(login, AccountError):
            self.assert_error('login_required', lambda: self.accounts.resolve_session(login['token']))
        else:
            self.assertEqual('invalid_credentials', login.code)
        new = self.accounts.login('test-user', 'new-good-password')
        self.assertEqual(self.user['id'], new['user']['id'])

    def test_invalid_unicode_password_returns_controlled_failure(self):
        self.assert_error('invalid_password', lambda: self.accounts.register('unicode-user', 'invalid-\ud800-pass'))
        self.assert_error('invalid_credentials', lambda: self.accounts.login('test-user', 'invalid-\ud800-pass'))
        self.assert_error('invalid_credentials', lambda: self.accounts.login('\ud800bad-user', 'good-password-for-tests'))

    def test_login_attempts_persist_and_are_bounded(self):
        for _ in range(8):
            self.assert_error('invalid_credentials', lambda: self.accounts.authenticate('test-user', 'wrong-password', attempt_key='test-ip'))
        self.assert_error('login_throttled', lambda: self.accounts.authenticate('test-user', 'good-password-for-tests', attempt_key='test-ip'))
        reloaded = PlatformAccounts(self.directory / 'workspace.sqlite3', self.directory / 'private', password_rounds=100_000, clock=lambda: self.now[0])
        self.assert_error('login_throttled', lambda: reloaded.authenticate('test-user', 'good-password-for-tests', attempt_key='test-ip'))
        self.now[0] += 901
        self.assertEqual(self.user['id'], reloaded.authenticate('test-user', 'good-password-for-tests', attempt_key='test-ip')['id'])

    def test_login_address_limit_cannot_be_bypassed_with_rotating_usernames(self):
        for index in range(40):
            self.assert_error('invalid_credentials', lambda: self.accounts.login(f'unknown-{index}', 'wrong-password', attempt_key='single-test-ip'))
        self.assert_error('login_throttled', lambda: self.accounts.login('test-user', 'good-password-for-tests', attempt_key='single-test-ip'))
        # A separate IP is independently usable; expiry releases the first one.
        self.assertEqual(self.user['id'], self.accounts.login('test-user', 'good-password-for-tests', attempt_key='other-test-ip')['user']['id'])
        self.now[0] += 901
        self.assertEqual(self.user['id'], self.accounts.login('test-user', 'good-password-for-tests', attempt_key='single-test-ip')['user']['id'])

    def test_last_admin_and_user_privilege_escalation_are_denied(self):
        self.assert_error('admin_required', lambda: self.accounts.set_role(self.user['id'], self.user['id'], 'admin'))
        self.assert_error('last_admin', lambda: self.accounts.set_role(self.admin['id'], self.admin['id'], 'user'))
        self.assert_error('last_admin', lambda: self.accounts.disable_account(self.admin['id'], self.admin['id']))
        self.accounts.set_role(self.admin['id'], self.user['id'], 'admin')
        self.accounts.set_role(self.admin['id'], self.admin['id'], 'user')
        self.assertEqual('user', self.accounts.account(self.admin['id'])['role'])

    def test_legacy_migration_preserves_old_rows_and_does_not_steal_ownership(self):
        with self.accounts.transaction() as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, token TEXT, data TEXT)')
            db.execute('CREATE TABLE assets(id TEXT PRIMARY KEY, data TEXT)')
            db.execute('INSERT INTO jobs VALUES(?,?,?)', ('old-job', 'untouched-token', '{"original":true}'))
            db.execute('INSERT INTO jobs VALUES(?,?,?)', ('new-job', 'other-token', '{"original":true}'))
            db.execute('INSERT INTO assets VALUES(?,?)', ('old-asset', '{"original":true}'))
            self.accounts.grant_resource(self.user['id'], 'job', 'new-job', connection=db)
        self.assertEqual({'jobs': 1, 'assets': 1}, self.accounts.migrate_legacy_resources(self.admin['id']))
        self.assertEqual({'jobs': 0, 'assets': 0}, self.accounts.migrate_legacy_resources(self.admin['id']))
        self.assertTrue(self.accounts.owns_resource(self.admin['id'], 'job', 'old-job'))
        self.assertFalse(self.accounts.owns_resource(self.user['id'], 'job', 'old-job'))
        self.assertTrue(self.accounts.owns_resource(self.user['id'], 'job', 'new-job'))
        with self.accounts.connection() as db:
            self.assertEqual(('untouched-token', '{"original":true}'), tuple(db.execute('SELECT token,data FROM jobs WHERE id = ?', ('old-job',)).fetchone()))
        with self.accounts.transaction() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?)', ('later-unowned-job', 'untouched-token-two', '{}'))
        self.assertEqual({'jobs': 0, 'assets': 0}, self.accounts.migrate_legacy_resources(self.admin['id']))
        self.assertFalse(self.accounts.owns_resource(self.admin['id'], 'job', 'later-unowned-job'))

    def test_jobs_have_one_owner_but_deduplicated_assets_can_have_several(self):
        self.accounts.grant_resource(self.admin['id'], 'job', 'owned-job')
        self.assert_error('resource_owned', lambda: self.accounts.grant_resource(self.user['id'], 'job', 'owned-job'))
        for account in (self.admin, self.user):
            self.accounts.grant_resource(account['id'], 'asset', 'same-content-hash')
            self.accounts.grant_resource(account['id'], 'asset', 'same-content-hash')
            self.assertTrue(self.accounts.owns_resource(account['id'], 'asset', 'same-content-hash'))

    def test_same_content_asset_name_and_provenance_are_private_to_each_account(self):
        shared = 'a' * 64
        self.accounts.grant_resource(self.admin['id'], 'asset', shared)
        self.accounts.grant_resource(self.user['id'], 'asset', shared)
        self.accounts.remember_asset(self.admin['id'], {'id': shared, 'name': 'A的私密文件.png', 'original_asset_id': 'b' * 64,
                                                       'annotation_mode': 'mask', 'remote': 'must-not-be-copied-A', 'width': 42})
        self.accounts.remember_asset(self.user['id'], {'id': shared, 'name': 'B的新名称.png', 'original_asset_id': 'c' * 64,
                                                      'annotation_mode': 'points', 'remote': 'must-not-be-copied-B', 'width': 99})
        private_a = self.accounts.asset_metadata(self.admin['id'], shared)
        private_b = self.accounts.asset_metadata(self.user['id'], shared)
        self.assertEqual({'name': 'A的私密文件.png', 'original_asset_id': 'b' * 64, 'annotation_mode': 'mask'}, private_a)
        self.assertEqual({'name': 'B的新名称.png', 'original_asset_id': 'c' * 64, 'annotation_mode': 'points'}, private_b)
        self.assertNotIn('remote', private_a)
        self.assertNotIn('width', private_b)
        self.accounts.remember_asset(self.user['id'], {'id': shared, 'name': 'B后来再次命名.png'})
        self.assertEqual(private_a, self.accounts.asset_metadata(self.admin['id'], shared))
        self.assertIsNone(self.accounts.asset_metadata(self.user['id'], shared)['original_asset_id'])

    def test_missing_asset_metadata_explicitly_clears_global_uploader_provenance(self):
        shared = 'a' * 64
        global_record = {'id': shared, 'name': '另一个用户的名字.png', 'original_asset_id': 'b' * 64,
                         'annotation_mode': 'mask', 'remote': 'immutable-remote', 'kind': 'image'}
        merged = {**global_record, **self.accounts.asset_metadata(self.user['id'], shared)}
        self.assertEqual('素材', merged['name'])
        self.assertIsNone(merged['original_asset_id'])
        self.assertIsNone(merged['annotation_mode'])
        self.assertEqual('immutable-remote', merged['remote'])
        self.assertEqual('image', merged['kind'])

    def test_asset_metadata_and_owner_rollback_with_upload_transaction(self):
        shared = 'a' * 64
        with self.assertRaises(RuntimeError):
            with self.accounts.transaction() as db:
                self.accounts.grant_resource(self.user['id'], 'asset', shared, connection=db)
                self.accounts.remember_asset(self.user['id'], {'id': shared, 'name': 'rollback.png'}, connection=db)
                raise RuntimeError('failed upload registration')
        self.assertFalse(self.accounts.owns_resource(self.user['id'], 'asset', shared))
        self.assertEqual('素材', self.accounts.asset_metadata(self.user['id'], shared)['name'])

    def test_legacy_asset_metadata_migrates_once_without_changing_global_rows(self):
        shared = 'a' * 64
        original = json.dumps({'id': shared, 'name': '旧私密素材.png', 'original_asset_id': 'b' * 64,
                               'annotation_mode': 'mask', 'remote': 'old-remote'}, ensure_ascii=False)
        with self.accounts.transaction() as db:
            db.execute('CREATE TABLE assets(id TEXT PRIMARY KEY, data TEXT)')
            db.execute('INSERT INTO assets VALUES(?,?)', (shared, original))
        self.accounts.migrate_legacy_resources(self.admin['id'])
        self.assertEqual({'name': '旧私密素材.png', 'original_asset_id': 'b' * 64, 'annotation_mode': 'mask'}, self.accounts.asset_metadata(self.admin['id'], shared))
        self.assertEqual('素材', self.accounts.asset_metadata(self.user['id'], shared)['name'])
        with self.accounts.connection() as db:
            self.assertEqual(original, db.execute('SELECT data FROM assets WHERE id=?', (shared,)).fetchone()[0])
        self.accounts.remember_asset(self.admin['id'], {'id': shared, 'name': '管理员更新自己的名字.png'})
        self.accounts.migrate_legacy_resources(self.admin['id'])
        self.assertEqual('管理员更新自己的名字.png', self.accounts.asset_metadata(self.admin['id'], shared)['name'])

    def test_prices_are_integer_admin_owned_and_explicit_zero_is_distinct(self):
        self.assertEqual({'workflow_id': 'workflow-one', 'credits': 0, 'configured': False}, self.accounts.pricing('workflow-one'))
        self.assert_error('admin_required', lambda: self.accounts.configure_pricing(self.user['id'], 'workflow-one', 8))
        self.assert_error('invalid_amount', lambda: self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 1.5))
        self.assert_error('invalid_amount', lambda: self.accounts.configure_pricing(self.admin['id'], 'workflow-one', True))
        self.assert_error('invalid_amount', lambda: self.accounts.configure_pricing(self.admin['id'], 'workflow-one', -1))
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 0)
        self.assertTrue(self.accounts.pricing('workflow-one')['configured'])
        self.assertEqual(0, self.accounts.pricing('workflow-one')['credits'])
        self.accounts.delete_pricing(self.admin['id'], 'workflow-one')
        self.assertFalse(self.accounts.pricing('workflow-one')['configured'])

    def test_recharge_packages_start_unavailable_and_snapshots_are_frozen(self):
        self.assertFalse(self.accounts.payment_status()['enabled'])
        self.assertFalse(self.accounts.payment_status()['automatic_payments'])
        self.assert_error('package_unavailable', lambda: self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one'))
        self.accounts.configure_package(self.admin['id'], 'test-pack', '套餐一', 100, 1000)
        self.assertEqual([], self.accounts.packages())
        self.accounts.configure_package(self.admin['id'], 'test-pack', '套餐一', 100, 1000, enabled=True)
        order = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one', 'bank')
        self.assertEqual(32, len(order['id']))
        self.assertEqual('bank', order['method'])
        self.accounts.configure_package(self.admin['id'], 'test-pack', '新套餐', 999, 9999, enabled=True)
        repeated = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one', 'bank')
        self.assertEqual(order, repeated)
        self.assertEqual(100, repeated['credits'])
        self.assertEqual(1000, repeated['amount_minor'])
        self.assert_error('idempotency_conflict', lambda: self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one', 'wechat'))
        self.assert_error('admin_required', lambda: self.accounts.confirm_order(self.user['id'], order['id'], 'receipt001'))

    def test_confirmation_is_atomic_idempotent_and_receipts_cannot_be_reused(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        order = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one')
        results = self.parallel(6, lambda _: self.accounts.confirm_order(self.admin['id'], order['id'], 'receipt001'))
        self.assertTrue(all(not isinstance(result, AccountError) for result in results))
        self.assertEqual(100, self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(1, len(self.accounts.ledger(self.user['id'])))
        self.assert_error('confirmation_conflict', lambda: self.accounts.confirm_order(self.admin['id'], order['id'], 'different-receipt'))
        other = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-two')
        self.assert_error('receipt_reused', lambda: self.accounts.confirm_order(self.admin['id'], other['id'], 'receipt001'))
        self.assertEqual('pending', self.accounts.get_order(other['id'])['status'])
        self.assertEqual(100, self.accounts.account(self.user['id'])['balance'])

    def test_cancelled_and_expired_orders_do_not_credit(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        cancelled = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one')
        self.accounts.cancel_order(self.user['id'], cancelled['id'])
        self.assert_error('order_not_pending', lambda: self.accounts.confirm_order(self.admin['id'], cancelled['id'], 'receipt001'))
        expired = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-two')
        self.now[0] += 86400
        self.assert_error('order_not_pending', lambda: self.accounts.confirm_order(self.admin['id'], expired['id'], 'receipt002'))
        self.assertEqual('expired', next(row for row in self.accounts.list_orders(self.user['id']) if row['id'] == expired['id'])['status'])
        self.assertEqual(0, self.accounts.account(self.user['id'])['balance'])

    def test_concurrent_orders_with_same_request_create_one_order(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        results = self.parallel(8, lambda _: self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one'))
        self.assertEqual(1, len({result['id'] for result in results}))
        self.assertEqual(1, len(self.accounts.list_orders(self.user['id'])))

    def test_concurrent_reservations_cannot_overdraw_and_releases_are_idempotent(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 80)
        results = self.parallel(8, lambda index: self.accounts.reserve(self.user['id'], f'job-{index}', 'workflow-one'))
        successes = [result for result in results if not isinstance(result, AccountError)]
        self.assertEqual(1, len(successes))
        self.assertTrue(all(result.code == 'insufficient_credits' for result in results if isinstance(result, AccountError)))
        account = self.accounts.account(self.user['id'])
        self.assertEqual((20, 80), (account['balance'], account['held']))
        job = successes[0]['job_id']
        again = self.accounts.reserve(self.user['id'], job, 'workflow-one')
        self.assertEqual(successes[0], again)
        self.parallel(6, lambda _: self.accounts.release(job))
        account = self.accounts.account(self.user['id'])
        self.assertEqual((100, 0), (account['balance'], account['held']))
        self.assertEqual('released', self.accounts.settle(job)['status'])
        self.assertEqual(3, len(self.accounts.ledger(self.user['id'])))

    def test_settlement_race_has_one_terminal_ledger_entry(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        self.accounts.reserve(self.user['id'], 'job-race', 'workflow-one')
        self.parallel(10, lambda index: self.accounts.settle('job-race') if index % 2 else self.accounts.release('job-race'))
        reservation = self.accounts.reservation('job-race')
        account = self.accounts.account(self.user['id'])
        self.assertEqual(0, account['held'])
        self.assertEqual(100 if reservation['status'] == 'released' else 65, account['balance'])
        self.assertEqual(3, len(self.accounts.ledger(self.user['id'])))

    def test_released_retry_uses_price_snapshot_and_requires_explicit_retry(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        self.accounts.reserve(self.user['id'], 'job-retry', 'workflow-one')
        self.accounts.release('job-retry')
        self.assert_error('reservation_released', lambda: self.accounts.reserve(self.user['id'], 'job-retry', 'workflow-one'))
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 90)
        retry = self.accounts.reserve(self.user['id'], 'job-retry', 'workflow-one', retry_released=True)
        self.assertEqual((2, 35), (retry['attempt'], retry['credits']))
        self.accounts.settle('job-retry')
        self.accounts.release('job-retry')
        account = self.accounts.account(self.user['id'])
        self.assertEqual((65, 0), (account['balance'], account['held']))
        self.assertEqual(5, len(self.accounts.ledger(self.user['id'])))

    def test_task_insert_owner_and_reservation_rollback_as_one_transaction(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        with self.accounts.transaction() as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, token TEXT, data TEXT)')
        with self.assertRaises(RuntimeError):
            with self.accounts.transaction() as db:
                db.execute('INSERT INTO jobs VALUES(?,?,?)', ('job-rollback', 'token', '{}'))
                self.accounts.grant_resource(self.user['id'], 'job', 'job-rollback', connection=db)
                self.accounts.reserve(self.user['id'], 'job-rollback', 'workflow-one', connection=db)
                raise RuntimeError('simulated graph dispatch preparation failure')
        self.assertIsNone(self.accounts.reservation('job-rollback'))
        self.assertFalse(self.accounts.owns_resource(self.user['id'], 'job', 'job-rollback'))
        with self.accounts.connection() as db:
            self.assertEqual(0, db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
        self.assertEqual(100, self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(1, len(self.accounts.ledger(self.user['id'])))
        with self.accounts.connection() as db:
            self.assert_error('transaction_required', lambda: self.accounts.reserve(self.user['id'], 'job-invalid', 'workflow-one', connection=db))

    def test_existing_plain_sqlite_connection_can_share_transaction(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        connection = sqlite3.connect(self.directory / 'workspace.sqlite3')
        self.addCleanup(connection.close)
        connection.execute('BEGIN IMMEDIATE')
        self.accounts.reserve(self.user['id'], 'plain-connection-job', 'workflow-one', connection=connection)
        self.accounts.grant_resource(self.user['id'], 'job', 'plain-connection-job', connection=connection)
        self.accounts.settle('plain-connection-job', connection=connection)
        self.assertIsNone(connection.row_factory)
        connection.commit()
        self.assertEqual(65, self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(0, self.accounts.account(self.user['id'])['held'])

    def test_ledger_and_admin_audit_are_append_only(self):
        self.funded()
        with self.accounts.transaction() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE platform_ledger SET amount = 999')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM platform_ledger')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM platform_admin_audit')
        self.assertEqual(100, self.accounts.account(self.user['id'])['balance'])

    def test_invalid_explicit_config_fails_closed(self):
        missing = self.directory / 'missing-config.json'
        self.assert_error('invalid_config', lambda: PlatformAccounts(self.directory / 'bad.sqlite3', self.directory / 'p1', config_path=missing))
        invalid = self.directory / 'invalid-config.json'
        invalid.write_text('{bad-json', encoding='utf-8')
        self.assert_error('invalid_config', lambda: PlatformAccounts(self.directory / 'bad.sqlite3', self.directory / 'p1', config_path=invalid))
        self.assert_error('invalid_config', lambda: PlatformAccounts(self.directory / 'bad.sqlite3', self.directory / 'p1', config={'payment_mode': 'automatic'}))

    def test_automatic_checkout_cannot_also_be_confirmed_manually(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        order = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-one', 'alipay')
        self.assert_error('checkout_missing', lambda: self.accounts.credit_verified_order(order['id'], 'alipay', 1000, 'CNY', 'transaction001'))
        self.accounts.mark_order_checkout(order['id'], 'alipay', order['id'])
        self.assert_error('automatic_checkout_exists', lambda: self.accounts.confirm_order(self.admin['id'], order['id'], 'receipt001'))
        self.assert_error('payment_mismatch', lambda: self.accounts.credit_verified_order(order['id'], 'alipay', 1, 'CNY', 'transaction001'))
        results = self.parallel(6, lambda _: self.accounts.credit_verified_order(order['id'], 'alipay', 1000, 'CNY', 'transaction001'))
        self.assertTrue(all(not isinstance(result, AccountError) for result in results))
        self.assertEqual(100, self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(1, len(self.accounts.ledger(self.user['id'])))
        self.assert_error('automatic_checkout_exists', lambda: self.accounts.confirm_order(self.admin['id'], order['id'], 'transaction001'))

    def test_verified_payment_transactions_are_scoped_and_do_not_credit_closed_orders(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        for index, method in enumerate(('alipay', 'wechat')):
            order = self.accounts.create_order(self.user['id'], 'test-pack', f'checkout-{index}', method)
            self.accounts.mark_order_checkout(order['id'], method, order['id'])
            self.accounts.credit_verified_order(order['id'], method, 1000, 'CNY', 'same-provider-transaction-string')
        self.assertEqual(200, self.accounts.account(self.user['id'])['balance'])
        duplicate = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-next', 'wechat')
        self.accounts.mark_order_checkout(duplicate['id'], 'wechat', duplicate['id'])
        self.assert_error('receipt_reused', lambda: self.accounts.credit_verified_order(duplicate['id'], 'wechat', 1000, 'CNY', 'same-provider-transaction-string'))
        self.accounts.cancel_order(self.user['id'], duplicate['id'])
        self.assert_error('order_not_pending', lambda: self.accounts.credit_verified_order(duplicate['id'], 'wechat', 1000, 'CNY', 'transaction-cancelled'))
        self.assertEqual(200, self.accounts.account(self.user['id'])['balance'])

    def test_late_verified_payment_is_retained_for_controlled_admin_resolution(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        order = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-late', 'wechat')
        self.accounts.mark_order_checkout(order['id'], 'wechat', order['id'])
        self.now[0] += 86401
        for _ in range(2):
            self.assert_error('order_not_pending', lambda: self.accounts.credit_verified_order(order['id'], 'wechat', 1000, 'CNY', 'late-payment-transaction'))
        reviews = self.accounts.list_payment_reviews(self.admin['id'])
        self.assertEqual(1, len(reviews))
        self.assertEqual('order_not_pending', reviews[0]['reason'])
        self.assertEqual(0, self.accounts.account(self.user['id'])['balance'])
        self.assert_error('admin_required', lambda: self.accounts.resolve_payment_review(self.user['id'], reviews[0]['id'], 'credit', 'verified receipt'))
        results = self.parallel(4, lambda _: self.accounts.resolve_payment_review(self.admin['id'], reviews[0]['id'], 'credit', 'confirmed late payment from provider'))
        self.assertTrue(all(not isinstance(result, AccountError) for result in results))
        self.assertEqual(100, self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(1, len(self.accounts.ledger(self.user['id'])))
        self.assertEqual([], self.accounts.list_payment_reviews(self.admin['id']))
        self.assertEqual(1, len(self.accounts.list_payment_reviews(self.admin['id'], include_resolved=True)))

    def test_refund_records_require_receipt_and_never_fake_automatic_refund(self):
        self.accounts.configure_package(self.admin['id'], 'test-pack', '测试套餐', 100, 1000, enabled=True)
        order = self.accounts.create_order(self.user['id'], 'test-pack', 'checkout-refund', 'alipay')
        self.accounts.mark_order_checkout(order['id'], 'alipay', order['id'])
        self.accounts.cancel_order(self.user['id'], order['id'])
        self.assert_error('order_not_pending', lambda: self.accounts.credit_verified_order(order['id'], 'alipay', 1000, 'CNY', 'paid-closed-order'))
        review = self.accounts.list_payment_reviews(self.admin['id'])[0]
        self.assert_error('refund_reference_required', lambda: self.accounts.resolve_payment_review(self.admin['id'], review['id'], 'refund_recorded', 'refund done'))
        result = self.accounts.resolve_payment_review(self.admin['id'], review['id'], 'refund_recorded', 'bank refund independently completed', refund_reference='bank-refund-001')
        self.assertEqual('refund_recorded', result['decision'])
        self.assertEqual('bank-refund-001', result['refund_reference'])
        self.assertEqual(0, self.accounts.account(self.user['id'])['balance'])
        self.assertEqual([], self.accounts.ledger(self.user['id']))
        self.assertEqual('cancelled', self.accounts.get_order(order['id'])['status'])
        with self.accounts.transaction() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM platform_payment_reviews')

    def add_generation_job(self, job_id, status, failure_phase=None):
        record = {'id': job_id, 'workflow_id': 'workflow-one', 'status': status,
                  'prompt_id': 'remote-' + job_id, 'failure_phase': failure_phase,
                  'prompt': 'SECRET-USER-PROMPT', 'graph': {'secret': 'SECRET-GRAPH'},
                  'api_profiles': {'provider': {'api_key': 'SECRET-API-KEY'}}}
        with self.accounts.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, token TEXT, data TEXT)')
            db.execute('INSERT INTO jobs VALUES(?,?,?)', (job_id, job_id + '-token', json.dumps(record)))
            self.accounts.grant_resource(self.user['id'], 'job', job_id, connection=db)
            self.accounts.reserve(self.user['id'], job_id, 'workflow-one', connection=db)
        return record

    def test_generation_review_list_is_admin_only_and_exposes_metadata_only(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 5)
        for job_id, status, phase in [('job-unknown', 'unknown', None), ('job-abandoned', 'abandoned', None),
                                       ('job-output', 'failed', 'output'), ('job-queue', 'queued', None),
                                       ('job-running', 'running', None), ('job-failed', 'failed', None),
                                       ('job-done', 'done', None)]:
            self.add_generation_job(job_id, status, phase)
        self.assert_error('admin_required', lambda: self.accounts.list_generation_reviews(self.user['id']))
        reviews = self.accounts.list_generation_reviews(self.admin['id'])
        self.assertEqual({'job-unknown', 'job-abandoned', 'job-output'}, {row['job_id'] for row in reviews})
        serialized = json.dumps(reviews)
        self.assertNotIn('SECRET', serialized)
        self.assertNotIn('api_profiles', serialized)
        self.assertNotIn('graph', serialized)
        self.assertTrue(all(row['account_id'] == self.user['id'] and row['username'] == 'test-user' and row['credits'] == 5 for row in reviews))

    def test_generation_review_rejects_normal_tasks_and_user_access(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        self.add_generation_job('job-queued', 'queued')
        self.assert_error('admin_required', lambda: self.accounts.resolve_generation_review(self.user['id'], 'job-queued', 'release', 'verified-id', 'verified reason'))
        self.assert_error('generation_review_not_pending', lambda: self.accounts.resolve_generation_review(self.admin['id'], 'job-queued', 'release', 'verified-id', 'verified reason'))
        account = self.accounts.account(self.user['id'])
        self.assertEqual((65, 35), (account['balance'], account['held']))
        self.assertEqual('held', self.accounts.reservation('job-queued')['status'])

    def test_generation_manual_confirmation_is_idempotent_and_cannot_reverse(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        self.add_generation_job('job-unknown', 'unknown')
        self.assert_error('confirmation_required', lambda: self.accounts.resolve_generation_review(self.admin['id'], 'job-unknown', 'settle', 'x', 'verified reason'))
        self.assert_error('review_note_required', lambda: self.accounts.resolve_generation_review(self.admin['id'], 'job-unknown', 'settle', 'verified-id', 'x'))
        results = self.parallel(6, lambda _: self.accounts.resolve_generation_review(self.admin['id'], 'job-unknown', 'settle', 'verified-id', 'confirmed actual compute consumption'))
        self.assertTrue(all(not isinstance(result, AccountError) for result in results))
        account = self.accounts.account(self.user['id'])
        self.assertEqual((65, 0), (account['balance'], account['held']))
        self.assertEqual(3, len(self.accounts.ledger(self.user['id'])))
        self.assert_error('review_already_resolved', lambda: self.accounts.resolve_generation_review(self.admin['id'], 'job-unknown', 'release', 'other-id', 'try reversing prior result'))
        with self.accounts.connection() as db:
            audits = list(db.execute("SELECT data FROM platform_admin_audit WHERE action='resolve_generation_review'"))
        self.assertEqual(1, len(audits))
        self.assertEqual('verified-id', json.loads(audits[0]['data'])['confirmation_reference'])
        self.assertEqual([], self.accounts.list_generation_reviews(self.admin['id']))

    def test_abandoned_and_output_failure_can_release_local_hold_without_provider_refund(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 10)
        for job_id, status, phase in [('job-abandoned', 'abandoned', None), ('job-output', 'failed', 'output')]:
            self.add_generation_job(job_id, status, phase)
            result = self.accounts.resolve_generation_review(self.admin['id'], job_id, 'release', 'verified-' + job_id, 'confirmed local credit release')
            self.assertEqual('released', result['status'])
            self.assertTrue(self.accounts.resolve_generation_review(self.admin['id'], job_id, 'release', 'verified-' + job_id, 'confirmed local credit release')['already_resolved'])
        account = self.accounts.account(self.user['id'])
        self.assertEqual((100, 0), (account['balance'], account['held']))

    def test_generation_decision_and_audit_roll_back_together(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'], 'workflow-one', 35)
        self.add_generation_job('job-unknown', 'unknown')
        with patch.object(self.accounts, '_audit', side_effect=RuntimeError('audit storage unavailable')):
            with self.assertRaises(RuntimeError):
                self.accounts.resolve_generation_review(self.admin['id'], 'job-unknown', 'release', 'verified-id', 'confirmed no compute consumption')
        account = self.accounts.account(self.user['id'])
        self.assertEqual((65, 35), (account['balance'], account['held']))
        self.assertEqual('held', self.accounts.reservation('job-unknown')['status'])
        self.assertEqual(2, len(self.accounts.ledger(self.user['id'])))

    def test_admin_credit_adjustment_is_ledgered_without_changing_held_or_disabled(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'],'workflow-one',35)
        self.accounts.reserve(self.user['id'],'job-adjust-held','workflow-one')
        self.accounts.disable_account(self.admin['id'],self.user['id'],True)
        plus = self.accounts.adjust_credits(self.admin['id'],self.user['id'],15,'核对后补充积分','adjust-plus-0001')
        minus = self.accounts.adjust_credits(self.admin['id'],self.user['id'],-20,'扣回测试补充积分','adjust-minus-0001')
        user = self.accounts.account(self.user['id'])
        self.assertEqual((60,35,False),(user['balance'],user['held'],user['enabled']))
        self.assertFalse(plus['already_applied']);self.assertFalse(minus['already_applied'])
        ledger = self.accounts.admin_ledger(self.admin['id'],self.user['id'])
        self.assertEqual(('adjustment',-20,0,'扣回测试补充积分'),
                         (ledger[0]['event'],ledger[0]['amount'],ledger[0]['held_amount'],ledger[0]['reason']))
        self.assertEqual(self.admin['id'],ledger[0]['actor_id'])
        self.assertEqual(minus['ledger_id'],ledger[0]['id'])
        self.assertEqual('held',self.accounts.reservation('job-adjust-held')['status'])

    def test_adjustment_validates_integer_reason_key_and_live_admin_authority(self):
        for invalid in (True,False,0,1.5,'1',self.accounts.MAX_CREDITS+1,-self.accounts.MAX_CREDITS-1):
            with self.subTest(delta=invalid):
                self.assert_error('invalid_adjustment',lambda:self.accounts.adjust_credits(self.admin['id'],self.user['id'],invalid,'测试调整原因','adjust-valid-0001'))
        for reason in (None,'  ','ab','x'*1001):
            self.assert_error('adjustment_reason_required',lambda:self.accounts.adjust_credits(self.admin['id'],self.user['id'],1,reason,'adjust-valid-0001'))
        for key in (None,'short','contains spaces','x'*129):
            self.assert_error('invalid_idempotency_key',lambda:self.accounts.adjust_credits(self.admin['id'],self.user['id'],1,'测试调整原因',key))
        self.assert_error('admin_required',lambda:self.accounts.adjust_credits(self.user['id'],self.admin['id'],1,'试图越权增加积分','adjust-valid-0001'))
        alternate = self.accounts.register('alternate-admin','good-password-for-tests')
        self.accounts.set_role(self.admin['id'],alternate['id'],'admin')
        self.accounts.disable_account(self.admin['id'],alternate['id'],True)
        self.assert_error('account_disabled',lambda:self.accounts.adjust_credits(alternate['id'],self.user['id'],1,'停用管理员不允许操作','adjust-valid-0001'))
        self.assertEqual([],self.accounts.ledger(self.user['id']))

    def test_adjustment_idempotency_binds_target_delta_reason_within_actor_scope(self):
        first = self.accounts.adjust_credits(self.admin['id'],self.user['id'],10,'测试积分补充','same-adjustment-key')
        repeat = self.accounts.adjust_credits(self.admin['id'],self.user['id'],10,'测试积分补充','same-adjustment-key')
        self.assertEqual(first['id'],repeat['id']);self.assertTrue(repeat['already_applied'])
        for target,delta,reason in ((self.admin['id'],10,'测试积分补充'),(self.user['id'],11,'测试积分补充'),(self.user['id'],10,'另一调整原因')):
            self.assert_error('adjustment_conflict',lambda:self.accounts.adjust_credits(self.admin['id'],target,delta,reason,'same-adjustment-key'))
        other = self.accounts.register('second-admin','good-password-for-tests')
        self.accounts.set_role(self.admin['id'],other['id'],'admin')
        self.accounts.adjust_credits(other['id'],self.user['id'],5,'另一管理员独立调整','same-adjustment-key')
        self.assertEqual(15,self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(2,len(self.accounts.ledger(self.user['id'])))

    def test_concurrent_identical_adjustment_credits_once_and_audits_once(self):
        results = self.parallel(8,lambda _:self.accounts.adjust_credits(self.admin['id'],self.user['id'],20,'并发重试测试调整','concurrent-adjust-0001'))
        self.assertTrue(all(not isinstance(result,AccountError) for result in results))
        self.assertEqual(1,len({result['id'] for result in results}))
        self.assertEqual(1,sum(not result['already_applied'] for result in results))
        self.assertEqual(20,self.accounts.account(self.user['id'])['balance'])
        self.assertEqual(1,len(self.accounts.ledger(self.user['id'])))
        self.assertEqual(1,len([row for row in self.accounts.admin_audit(self.admin['id']) if row['action']=='adjust_credits']))

    def test_parallel_debits_cannot_consume_another_reservation(self):
        self.funded()
        self.accounts.configure_pricing(self.admin['id'],'workflow-one',80)
        self.accounts.reserve(self.user['id'],'job-protected-hold','workflow-one')
        results = self.parallel(6,lambda index:self.accounts.adjust_credits(self.admin['id'],self.user['id'],-15,'并发扣减测试积分',f'parallel-debit-{index}'))
        self.assertEqual(1,sum(not isinstance(result,AccountError) for result in results))
        self.assertTrue(all(result.code=='insufficient_credits' for result in results if isinstance(result,AccountError)))
        account = self.accounts.account(self.user['id'])
        self.assertEqual((5,80),(account['balance'],account['held']))
        self.assertEqual('held',self.accounts.reservation('job-protected-hold')['status'])

    def test_adjustment_ceiling_counts_available_and_held_credits(self):
        self.funded(credits=self.accounts.MAX_CREDITS)
        self.accounts.configure_pricing(self.admin['id'],'workflow-one',20)
        self.accounts.reserve(self.user['id'],'job-max-hold','workflow-one')
        self.assert_error('balance_limit',lambda:self.accounts.adjust_credits(self.admin['id'],self.user['id'],1,'总积分超上限测试','adjust-limit-0001'))
        self.accounts.adjust_credits(self.admin['id'],self.user['id'],-5,'测试减少可用积分','adjust-limit-0002')
        self.accounts.adjust_credits(self.admin['id'],self.user['id'],5,'测试恢复到积分上限','adjust-limit-0003')
        account = self.accounts.account(self.user['id'])
        self.assertEqual(self.accounts.MAX_CREDITS,account['balance']+account['held'])
        self.assertEqual(20,account['held'])

    def test_adjustment_balance_entry_and_audit_roll_back_as_one_transaction(self):
        for method in ('_entry','_audit'):
            with self.subTest(failing=method),patch.object(self.accounts,method,side_effect=RuntimeError('simulated storage failure')):
                with self.assertRaises(RuntimeError):
                    self.accounts.adjust_credits(self.admin['id'],self.user['id'],12,'事务回滚测试积分','adjust-rollback-0001')
            self.assertEqual(0,self.accounts.account(self.user['id'])['balance'])
            self.assertEqual([],self.accounts.ledger(self.user['id']))
            self.assertEqual([],self.accounts.admin_audit(self.admin['id']))
            with self.accounts.connection() as db:
                self.assertEqual(0,db.execute('SELECT COUNT(*) FROM platform_credit_adjustments').fetchone()[0])
        self.assertFalse(self.accounts.adjust_credits(self.admin['id'],self.user['id'],12,'事务回滚测试积分','adjust-rollback-0001')['already_applied'])

    def test_admin_ledger_and_audit_reject_users_and_filter_secret_structures(self):
        self.accounts.adjust_credits(self.admin['id'],self.user['id'],12,'审计元数据测试积分','adjust-audit-0001')
        self.assert_error('admin_required',lambda:self.accounts.admin_ledger(self.user['id'],self.admin['id']))
        self.assert_error('admin_required',lambda:self.accounts.admin_audit(self.user['id']))
        self.assert_error('admin_required',lambda:self.accounts.admin_stats(self.user['id']))
        with self.accounts.transaction() as db:
            self.accounts._audit(db,self.admin['id'],'test-safe-metadata',self.user['id'],
                {'delta':12,'api_key':'SECRET-KEY','graph':{'password':'SECRET-PASSWORD'},'session':'SECRET-SESSION'})
        audit = self.accounts.admin_audit(self.admin['id'])
        self.assertEqual({'delta':12},audit[0]['data'])
        self.assertEqual(self.admin['username'],audit[0]['actor_username'])
        self.assertNotIn('SECRET',json.dumps(audit))

    def test_admin_stats_aggregate_all_accounts_without_list_limit(self):
        with self.accounts.transaction() as db:
            password_hash = db.execute('SELECT password_hash FROM platform_accounts WHERE id=?',(self.user['id'],)).fetchone()[0]
            db.executemany('''INSERT INTO platform_accounts(id,username,username_key,password_hash,role,enabled,balance,held,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',[(f'aggregate-user-{index}',f'aggregate{index}',f'aggregate{index}',password_hash,'user',int(index%2==0),2,3,self.now[0]) for index in range(501)])
        stats = self.accounts.admin_stats(self.admin['id'])
        self.assertEqual(503,stats['users'])
        self.assertEqual(253,stats['enabled_users'])
        self.assertEqual((1002,1503),(stats['available_credits'],stats['held_credits']))
        self.assertEqual(500,len(self.accounts.list_accounts(self.admin['id'],limit=500)))

    def test_account_query_filters_globally_before_paging_and_returns_full_total(self):
        with self.accounts.transaction() as db:
            password_hash = db.execute('SELECT password_hash FROM platform_accounts WHERE id=?',(self.user['id'],)).fetchone()[0]
            db.executemany('''INSERT INTO platform_accounts(id,username,username_key,password_hash,role,enabled,created_at)
                VALUES(?,?,?,?,?,?,?)''',[(f'page-user-{index}',f'aggregate{index}',f'aggregate{index}',password_hash,'user',int(index%2==0),self.now[0]) for index in range(501)])
        page = self.accounts.query_accounts(self.admin['id'],limit=50,offset=500)
        self.assertEqual((503,50,500,3),(page['total'],page['limit'],page['offset'],len(page['users'])))
        self.assertTrue(all('password_hash' not in user and 'username_key' not in user for user in page['users']))
        combined = []
        for offset in range(0,600,100):
            combined.extend(self.accounts.query_accounts(self.admin['id'],limit=100,offset=offset)['users'])
        self.assertEqual(503,len({user['id'] for user in combined}))
        filtered = self.accounts.query_accounts(self.admin['id'],query='ＡＧＧＲＥＧＡＴＥ',role='user',state='disabled',limit=50,offset=240)
        self.assertEqual((250,10),(filtered['total'],len(filtered['users'])))
        self.assertTrue(all(not user['enabled'] and user['role']=='user' for user in filtered['users']))
        self.assertEqual(1,self.accounts.query_accounts(self.admin['id'],role='admin')['total'])

    def test_account_query_search_treats_wildcards_literally_and_rejects_invalid_inputs(self):
        exact = self.accounts.register('literal_name','good-password-for-tests')
        self.accounts.register('literalXname','good-password-for-tests')
        self.assertEqual([exact['id']],[row['id'] for row in self.accounts.query_accounts(self.admin['id'],query='LITERAL_NAME')['users']])
        for literal in ('%','\\','literal%name'):
            self.assertEqual(0,self.accounts.query_accounts(self.admin['id'],query=literal)['total'])
        self.assert_error('admin_required',lambda:self.accounts.query_accounts(self.user['id']))
        for filters in ({'query':'a'*81},{'query':None},{'role':'superadmin'},{'state':'unknown'}):
            self.assert_error('invalid_account_filter',lambda:self.accounts.query_accounts(self.admin['id'],**filters))
        for filters in ({'limit':0},{'limit':101},{'limit':True},{'offset':-1},{'offset':1.5}):
            self.assert_error('invalid_pagination',lambda:self.accounts.query_accounts(self.admin['id'],**filters))

    def legacy_ledger_store(self):
        folder = self.directory/'legacy-migration'
        old_schema = SCHEMA.replace("'release', 'adjustment'","'release'")
        with patch('platform_accounts.SCHEMA',old_schema),patch.object(PlatformAccounts,'_ensure_adjustment_ledger',return_value=None):
            store = PlatformAccounts(folder/'workspace.sqlite3',folder/'private',password_rounds=100_000,clock=lambda:self.now[0])
        admin = store.bootstrap_admin();user = store.register('old-user','good-password-for-tests')
        store.configure_package(admin['id'],'old-pack','历史套餐',100,1000,True)
        order = store.create_order(user['id'],'old-pack','old-order-0001')
        store.confirm_order(admin['id'],order['id'],'verified-old-receipt')
        store.configure_pricing(admin['id'],'old-workflow',17)
        store.reserve(user['id'],'old-job-release','old-workflow');store.release('old-job-release')
        store.reserve(user['id'],'old-job-settle','old-workflow');store.settle('old-job-settle')
        with store.connection() as db:
            rows = [tuple(row) for row in db.execute('SELECT * FROM platform_ledger ORDER BY id')]
            definition = db.execute("SELECT sql FROM sqlite_master WHERE name='platform_ledger'").fetchone()[0]
            db.execute("UPDATE sqlite_sequence SET seq=99 WHERE name='platform_ledger'")
        return store,admin,user,rows,definition

    def test_existing_ledger_schema_upgrade_keeps_history_ids_and_append_only_rules(self):
        old,admin,user,before,definition = self.legacy_ledger_store()
        self.assertNotIn("'adjustment'",definition)
        for _ in range(2):
            upgraded = PlatformAccounts(old.db_path,old.private_dir,password_rounds=100_000)
            with upgraded.connection() as db:
                self.assertEqual(before,[tuple(row) for row in db.execute('SELECT * FROM platform_ledger ORDER BY id')])
                self.assertEqual(99,db.execute("SELECT seq FROM sqlite_sequence WHERE name='platform_ledger'").fetchone()[0])
                for sql in ('UPDATE platform_ledger SET amount=999','DELETE FROM platform_ledger'):
                    with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
                self.assertEqual([],list(db.execute('PRAGMA foreign_key_check')))
        adjustment = upgraded.adjust_credits(admin['id'],user['id'],1,'升级后调整测试积分','after-upgrade-0001')
        self.assertEqual(100,adjustment['ledger_id'])
        with upgraded.connection() as db:
            for sql in ('UPDATE platform_credit_adjustments SET delta=999','DELETE FROM platform_credit_adjustments'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_failed_ledger_upgrade_rolls_back_schema_and_original_history(self):
        old,admin,user,before,definition = self.legacy_ledger_store()
        original_connect = sqlite3.connect
        class FailedMigrationConnection(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql.startswith('ALTER TABLE platform_ledger_adjustment_migration'):
                    raise sqlite3.OperationalError('simulated migration failure')
                return super().execute(sql,*args,**kwargs)
        def connection(*args,**kwargs):
            return original_connect(*args,**kwargs,factory=FailedMigrationConnection)
        with patch('platform_accounts.sqlite3.connect',side_effect=connection),self.assertRaises(sqlite3.OperationalError):
            PlatformAccounts(old.db_path,old.private_dir,password_rounds=100_000)
        with old.connection() as db:
            self.assertEqual(definition,db.execute("SELECT sql FROM sqlite_master WHERE name='platform_ledger'").fetchone()[0])
            self.assertEqual(before,[tuple(row) for row in db.execute('SELECT * FROM platform_ledger ORDER BY id')])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='platform_ledger_adjustment_migration'").fetchone())
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM platform_ledger')
        reloaded = PlatformAccounts(old.db_path,old.private_dir,password_rounds=100_000)
        self.assertEqual(83,reloaded.account(user['id'])['balance'])


if __name__ == '__main__':
    unittest.main()
