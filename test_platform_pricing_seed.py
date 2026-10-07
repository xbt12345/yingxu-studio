"""Published pricing seed tests: isolated stores, shipped graphs, no providers."""
from copy import deepcopy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from platform_accounts import PlatformAccounts, AccountError
import platform_pricing_seed as seed

ROOT=Path(__file__).resolve().parent


class PublishedPricingSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pricing-publish-test-')
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.private=self.folder/'private'
        self.store=PlatformAccounts(self.folder/'workspace.sqlite3',self.private,password_rounds=100_000)
        self.owner=self.store.bootstrap_admin()
        self.store.migrate_legacy_resources(self.owner['id'])
        self.plan=json.loads(seed.PLAN_PATH.read_text('utf-8'))
        self.plan_path=self.folder/'published.json'
        self.write_plan()

    def write_plan(self):
        self.plan_path.write_text(json.dumps(self.plan,ensure_ascii=False),'utf-8')

    def apply(self,**kwargs):
        return seed.seed_reviewed_pricing(self.store,self.owner['id'],plan_path=self.plan_path,**kwargs)

    def fingerprints(self):
        with self.store.connection()as db:
            return seed.protected_fingerprints(db)

    def counts(self):
        with self.store.connection()as db:
            return tuple(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]for table in ('platform_prices','platform_packages','platform_admin_audit'))

    def funded_history(self):
        user=self.store.register('fixture-member','fixture-member-password')
        self.store.adjust_credits(self.owner['id'],user['id'],100,'fixture funded','fixture-credit-adjustment')
        self.store.configure_pricing(self.owner['id'],'existing-workflow',12)
        self.store.reserve(user['id'],'held-existing-job','existing-workflow')
        self.store.configure_package(self.owner['id'],'existing-package','existing',50,50,enabled=True)
        self.store.create_order(user['id'],'existing-package','pending-existing-order')
        with self.store.transaction()as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, token TEXT, data TEXT)')
            db.execute('CREATE TABLE assets(id TEXT PRIMARY KEY, data TEXT)')
            db.execute('INSERT INTO jobs VALUES(?,?,?)',('held-existing-job','private-token','{"prompt":"original"}'))
            db.execute('INSERT INTO assets VALUES(?,?)',('original-media','{"source":"original"}'))
            db.execute('INSERT INTO platform_metadata VALUES(?,?)',('unrelated','keep-original'))
        return user

    def assert_rolled_back(self,before,counts):
        self.assertEqual(before,self.fingerprints())
        self.assertEqual(counts,self.counts())
        with self.store.connection()as db:
            self.assertIsNone(db.execute('SELECT 1 FROM platform_metadata WHERE key=?',(seed.MARKER,)).fetchone())

    def test_new_cloud_has_exact_approved_prices_packages_backup_and_zero_credit_changes(self):
        before=self.fingerprints()
        report=self.apply()
        self.assertEqual(('applied',93,6),(report['status'],report['prices_inserted'],report['packages_inserted']))
        self.assertEqual((93,6,100),self.counts())
        self.assertEqual(before,self.fingerprints())
        self.assertEqual(14,self.store.pricing('h3-reference')['credits'])
        self.assertEqual(11,self.store.pricing('bernini-edit')['credits'])
        self.assertFalse(self.store.pricing('local-card-31')['configured'])
        self.assertFalse(self.store.pricing('local-card-105')['configured'])
        with closing(sqlite3.connect(report['backup_path']))as db:
            self.assertEqual(before,seed.protected_fingerprints(db))
            self.assertEqual(0,db.execute('SELECT COUNT(*) FROM platform_prices').fetchone()[0])
            self.assertIsNone(db.execute('SELECT 1 FROM platform_metadata WHERE key=?',(seed.MARKER,)).fetchone())

    def test_funded_accounts_held_credits_jobs_assets_ledgers_orders_are_preserved(self):
        user=self.funded_history();before=self.fingerprints()
        self.apply()
        self.assertEqual(before,self.fingerprints())
        with self.store.connection()as db:
            self.assertEqual((88,12),tuple(db.execute('SELECT balance,held FROM platform_accounts WHERE id=?',(user['id'],)).fetchone()))

    def test_existing_manual_prices_packages_never_overwritten_or_reenabled(self):
        self.store.configure_pricing(self.owner['id'],'h3-reference',999)
        self.store.configure_pricing(self.owner['id'],'outside-reviewed-history',0)
        self.store.configure_package(self.owner['id'],'credits-5000','custom disabled',250,200,enabled=False)
        with self.store.connection()as db:existing=seed._existing_rows(db)
        report=self.apply()
        self.assertEqual((92,5,1,1),(report['prices_inserted'],report['packages_inserted'],report['prices_preserved'],report['packages_preserved']))
        with self.store.connection()as db:self.assertTrue(seed._preserved_rows(existing,seed._existing_rows(db)))
        self.assertEqual(999,self.store.pricing('h3-reference')['credits'])
        custom=next(p for p in self.store.packages(self.owner['id'])if p['id']=='credits-5000')
        self.assertEqual(('custom disabled',250,200,False),(custom['title'],custom['credits'],custom['amount_minor'],custom['enabled']))

    def test_multiple_admins_use_explicit_bootstrap_owner_for_audit(self):
        second=self.store.admin_create_user(self.owner['id'],'fixture-second-admin','fixture-second-admin-password','admin')
        self.assertNotEqual(self.owner['id'],second['id'])
        self.apply()
        with self.store.connection()as db:
            self.assertEqual({self.owner['id']},{r[0]for r in db.execute('SELECT DISTINCT updated_by FROM platform_prices')})
            self.assertEqual(self.owner['id'],db.execute('SELECT actor_id FROM platform_admin_audit WHERE action=?',(seed.MARKER,)).fetchone()[0])

    def test_any_existing_marker_skips_plan_read_backup_validation_and_all_writes(self):
        with self.store.transaction()as db:db.execute('INSERT INTO platform_metadata VALUES(?,?)',(seed.MARKER,'local explicit setup marker'))
        self.plan_path.unlink()
        before=self.store.db_path.read_bytes();counts=self.counts()
        with patch.object(seed,'validate_plan',side_effect=AssertionError('Must not inspect old seed inputs')),patch.object(seed,'_backup',side_effect=AssertionError('Must not make backup')):
            self.assertEqual({'status':'already_applied','writes':0},self.apply())
        self.assertEqual(before,self.store.db_path.read_bytes())
        self.assertEqual(counts,self.counts())
        self.assertFalse((self.private/'pricing-init-backups').exists())

    def test_repeat_preserves_manual_changes_deletion_and_disabled_package(self):
        self.apply()
        self.store.configure_pricing(self.owner['id'],'bernini-edit',77)
        self.store.delete_pricing(self.owner['id'],'h3-reference')
        self.store.configure_package(self.owner['id'],'credits-5000','changed',100,90,enabled=False)
        before=self.store.db_path.read_bytes();counts=self.counts()
        backups=sorted(p.name for p in (self.private/'pricing-init-backups').iterdir())
        self.assertEqual({'status':'already_applied','writes':0},self.apply())
        self.assertEqual(before,self.store.db_path.read_bytes())
        self.assertEqual(counts,self.counts())
        self.assertFalse(self.store.pricing('h3-reference')['configured'])
        self.assertEqual(77,self.store.pricing('bernini-edit')['credits'])
        self.assertEqual(backups,sorted(p.name for p in (self.private/'pricing-init-backups').iterdir()))

    def test_concurrent_first_initialization_commits_only_once(self):
        with ThreadPoolExecutor(max_workers=2)as pool:
            reports=list(pool.map(lambda _:self.apply(),range(2)))
        self.assertEqual({'applied','already_applied'},{report['status']for report in reports})
        self.assertEqual((93,6,100),self.counts())
        self.assertEqual(1,len(list((self.private/'pricing-init-backups').glob('*.sqlite3'))))

    def test_coherent_but_unapproved_price_or_package_change_is_rejected(self):
        self.plan['prices'][0].update(credits=20,median_seconds='120')
        self.write_plan()
        with self.assertRaises(seed.PricingSeedError):self.apply()
        self.plan=json.loads(seed.PLAN_PATH.read_text('utf-8'))
        self.plan['packages'][0].update(credits=6000,amount_minor=6000)
        self.write_plan()
        with self.assertRaises(seed.PricingSeedError):self.apply()
        self.assertFalse((self.private/'pricing-init-backups').exists())

    def test_bad_counts_fields_rounding_types_ids_and_contract_hash_reject_before_backup(self):
        mutations=[lambda p:p['prices'].pop(),lambda p:p['packages'].pop(),
          lambda p:p['prices'][0].update(credits=True),lambda p:p['prices'][0].update(credits=999),
          lambda p:p['prices'][0].update(median_seconds='NaN'),lambda p:p['prices'][0].update(samples=0),
          lambda p:p['prices'][1].update(workflow_id=p['prices'][0]['workflow_id']),
          lambda p:p['prices'][0].update(workflow_id='local-card-31'),
          lambda p:p['prices'][0].update(source_hash='0'*64),lambda p:p['prices'][0].update(template_sha256='0'*64),
          lambda p:p['prices'][0].update(job_ids=['must-not-be-published']),
          lambda p:p['packages'][0].update(amount_minor=1),lambda p:p['packages'][0].update(enabled=1),
          lambda p:p['packages'][1].update(id=p['packages'][0]['id'])]
        original=deepcopy(self.plan);before=self.fingerprints();counts=self.counts()
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.plan=deepcopy(original);mutate(self.plan);self.write_plan()
                with self.assertRaises(seed.PricingSeedError):self.apply()
                self.assert_rolled_back(before,counts)
                self.assertFalse((self.private/'pricing-init-backups').exists())

    def test_changed_template_bytes_or_manifest_source_fail_closed(self):
        deployed=self.folder/'deployment';(deployed/'workflows/api').mkdir(parents=True)
        shutil.copyfile(ROOT/'adapters.py',deployed/'adapters.py')
        for name in ('compiled-registry.json','manifest.json'):
            shutil.copyfile(ROOT/'workflows'/name,deployed/'workflows'/name)
        manifest=json.loads((deployed/'workflows/manifest.json').read_text('utf-8'))
        by_id={row['id']:row for row in manifest['workflows']}
        for price in self.plan['prices']:
            name=by_id[price['workflow_id']]['template']
            shutil.copyfile(ROOT/'workflows/api'/name,deployed/'workflows/api'/name)
        changed=deployed/'workflows/api/h3-reference.api.json'
        changed.write_bytes(changed.read_bytes()+b'\n')
        with self.assertRaises(seed.PricingSeedError):self.apply(root=deployed)
        shutil.copyfile(ROOT/'workflows/api/h3-reference.api.json',changed)
        by_id['bernini-edit']['source_hash']='0'*64
        (deployed/'workflows/manifest.json').write_text(json.dumps(manifest),'utf-8')
        with self.assertRaises(seed.PricingSeedError):self.apply(root=deployed)
        self.assertFalse((self.private/'pricing-init-backups').exists())

    def test_non_admin_actor_is_rejected_before_backup(self):
        user=self.store.register('fixture-no-admin','fixture-no-admin-password')
        with self.assertRaises(AccountError):seed.seed_reviewed_pricing(self.store,user['id'],plan_path=self.plan_path)
        self.assertFalse((self.private/'pricing-init-backups').exists())

    def test_audit_failure_rolls_back_config_marker_and_data(self):
        self.funded_history();before=self.fingerprints();counts=self.counts()
        original=self.store._audit;calls=[]
        def broken(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('injected audit failure')
            return original(*args,**kwargs)
        with patch.object(self.store,'_audit',side_effect=broken):
            with self.assertRaises(RuntimeError):self.apply()
        self.assert_rolled_back(before,counts)

    def test_unexpected_balance_held_jobs_assets_orders_or_ledger_triggers_rollback(self):
        self.funded_history()
        bodies=["UPDATE platform_accounts SET balance=balance+1 WHERE role='user'",
          "UPDATE platform_accounts SET held=held+1 WHERE role='user'",
          "UPDATE jobs SET data='unexpected'", "UPDATE assets SET data='unexpected'",
          'UPDATE platform_orders SET amount_minor=amount_minor+1',
          "INSERT INTO platform_ledger(account_id,event_key,event,amount,held_amount,balance_after,held_after,resource_id,actor_id,created_at) SELECT id,'unexpected-'||NEW.workflow_id,'recharge',0,0,balance,held,'unexpected',id,0 FROM platform_accounts LIMIT 1"]
        for body in bodies:
            with self.subTest(body=body):
                with self.store.transaction()as db:db.execute('CREATE TRIGGER bad_seed AFTER INSERT ON platform_prices BEGIN '+body+'; END')
                before=self.fingerprints();counts=self.counts()
                with self.assertRaises(seed.PricingSeedError):self.apply()
                self.assert_rolled_back(before,counts)
                with self.store.transaction()as db:db.execute('DROP TRIGGER bad_seed')

    def test_final_marker_trigger_is_included_in_protection_check(self):
        with self.store.transaction()as db:db.execute("CREATE TRIGGER bad_marker AFTER INSERT ON platform_metadata WHEN NEW.key='review79_pricing_seed' BEGIN UPDATE platform_accounts SET held=held+1; END")
        before=self.fingerprints();counts=self.counts()
        with self.assertRaises(seed.PricingSeedError):self.apply()
        self.assert_rolled_back(before,counts)

    def test_trigger_cannot_change_existing_admin_prices_or_reenable_packages(self):
        self.store.configure_pricing(self.owner['id'],'h3-reference',555)
        self.store.configure_package(self.owner['id'],'credits-5000','disabled',10,10,enabled=False)
        with self.store.transaction()as db:db.execute("CREATE TRIGGER bad_setting AFTER INSERT ON platform_prices BEGIN UPDATE platform_packages SET enabled=1 WHERE id='credits-5000'; UPDATE platform_prices SET credits=556 WHERE workflow_id='h3-reference'; END")
        before=self.fingerprints();counts=self.counts()
        with self.assertRaises(seed.PricingSeedError):self.apply()
        self.assert_rolled_back(before,counts)
        self.assertEqual(555,self.store.pricing('h3-reference')['credits'])
        self.assertFalse(next(p for p in self.store.packages(self.owner['id'])if p['id']=='credits-5000')['enabled'])

    def test_published_plan_and_runtime_code_have_no_private_evidence_dependency(self):
        raw=seed.PLAN_PATH.read_text('utf-8')
        for forbidden in ('job_ids','receipt_sha256','source_tier','private/','prompt_id','start_timestamp_ms','C:\\Users'):
            self.assertNotIn(forbidden,raw)
        original=Path.read_bytes
        def prohibit_receipts(path):
            if path.is_relative_to(ROOT/'private') or path.is_relative_to(ROOT/'docs'):
                raise AssertionError('Runtime pricing must not read original private evidence')
            return original(path)
        with patch.object(Path,'read_bytes',prohibit_receipts),patch.object(PlatformAccounts,'__init__',side_effect=AssertionError('Cannot construct another store')):
            report=self.apply()
        self.assertNotIn('private-token',json.dumps(report))

    def test_platform_accounts_startup_seeds_after_bootstrap_and_migration_once(self):
        from types import SimpleNamespace
        sys.path.insert(0,str(ROOT/'private/runtime'))
        import platform_api
        events=[]
        class StartupAccounts(PlatformAccounts):
            def __init__(self,*args,**kwargs):
                kwargs['password_rounds']=100_000
                super().__init__(*args,**kwargs)
            def bootstrap_admin(self):
                events.append('bootstrap')
                return super().bootstrap_admin()
            def migrate_legacy_resources(self,owner_id):
                events.append('migration')
                return super().migrate_legacy_resources(owner_id)
        original=seed.seed_reviewed_pricing
        def initialize(store,actor_id):
            events.append('pricing')
            return original(store,actor_id)
        backend=SimpleNamespace(DB=self.store.db_path,PRIVATE=self.private)
        with patch.object(platform_api,'PlatformAccounts',StartupAccounts),patch.object(platform_api,'PaymentGateway',return_value=SimpleNamespace()),patch.object(seed,'seed_reviewed_pricing',side_effect=initialize):
            integration=platform_api.PlatformIntegration(backend)
            first=integration.accounts()
            self.assertIs(first,integration.accounts())
        self.assertEqual(['bootstrap','migration','pricing'],events)
        self.assertEqual((93,6,100),self.counts())


if __name__=='__main__':
    unittest.main()
