"""One-time pricing setup tests use isolated databases and receipt fixtures."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from platform_accounts import PlatformAccounts
from scripts.apply_review79_pricing import (EVENT, MARKER, SetupError, apply_setup,
                                           protected_fingerprints, readonly_database,
                                           validate_inputs)


class PricingSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / 'private'
        self.db_path = self.root / 'workspace.sqlite3'
        self.backups = self.root / 'backups'
        self.accounts = PlatformAccounts(self.db_path, self.private, password_rounds=100_000)
        self.admin = self.accounts.bootstrap_admin()
        self.user = self.accounts.register('isolated-pricing-user', 'isolated-pricing-password')
        self.accounts.adjust_credits(self.admin['id'], self.user['id'], 100, 'test fixture', 'pricing-fixture-100')
        self.accounts.configure_pricing(self.admin['id'], 'existing-workflow', 12)
        self.accounts.reserve(self.user['id'], 'held-job', 'existing-workflow')
        self.accounts.configure_package(self.admin['id'], 'existing-package', 'existing', 50, 50, enabled=True)
        self.accounts.create_order(self.user['id'], 'existing-package', 'pending-fixture-01')
        with self.accounts.transaction() as db:
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY, token TEXT, data TEXT)')
            db.execute('CREATE TABLE assets(id TEXT PRIMARY KEY, data TEXT)')
            db.execute('INSERT INTO jobs VALUES(?,?,?)', ('held-job', 'private-token-fixture', '{"prompt":"unchanged"}'))
            db.execute('INSERT INTO assets VALUES(?,?)', ('saved-asset', '{"source":"unchanged"}'))
            db.execute('INSERT INTO platform_metadata VALUES(?,?)', ('unrelated', 'preserve this value'))
        self.audit = {'apply_candidates': [], 'samples': []}
        for workflow_id, duration in (('workflow-a', 6000), ('workflow-b', 6001)):
            sample = self.sample(workflow_id, duration)
            self.audit['samples'].append(sample)
            self.audit['apply_candidates'].append(self.candidate(workflow_id, [sample]))
        self.policy = {
            'credit_policy': {'currency': 'CNY', 'credits_per_yuan': 100, 'rounding': 'ceil_to_fen'},
            'workflow_pricing': {'eligible_count': 2},
            'recharge_packages': [
                {'id': 'credits-5000', 'title': '轻量体验', 'credits': 5000, 'amount_minor': 5000, 'currency': 'CNY', 'enabled': True},
                {'id': 'credits-7500', 'title': '日常创作', 'credits': 7500, 'amount_minor': 7500, 'currency': 'CNY', 'enabled': True},
            ],
        }
        self.audit_path, self.policy_path = self.root / 'audit.json', self.root / 'policy.json'
        self.write_inputs()

    def sample(self, workflow_id, duration, *, tier='main_workspace', prompt_id=None):
        job_id, start = uuid.uuid4().hex, 1_790_000_000_000
        prompt_id = prompt_id or str(uuid.uuid4())
        relative = 'receipts' if tier == 'main_workspace' else 'review70-runtime/receipts'
        receipt_path = self.private / relative / (job_id + '.json')
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {'outputs': {}, 'status': {'status_str': 'success', 'completed': True, 'messages': [
            ['execution_start', {'prompt_id': prompt_id, 'timestamp': start}],
            ['execution_success', {'prompt_id': prompt_id, 'timestamp': start + duration}],
        ]}}
        raw = json.dumps(receipt).encode('utf-8')
        receipt_path.write_bytes(raw)
        graph_hash = hashlib.sha256(workflow_id.encode()).hexdigest()
        return {'job_id': job_id, 'workflow_id': workflow_id, 'source_tier': tier,
                'source': 'private/' + relative + '/' + job_id + '.json',
                'duration_ms': duration, 'seconds': duration / 1000,
                'start_timestamp_ms': start, 'success_timestamp_ms': start + duration,
                'cached_node_count': 1, 'graph_node_count': 3,
                'receipt_sha256': hashlib.sha256(raw).hexdigest(),
                'compatibility': {'compatible': True, 'reason': 'offline_rebuild_matches',
                                  'historical_execution_graph_sha256': graph_hash,
                                  'current_rebuilt_graph_sha256': graph_hash}}

    @staticmethod
    def candidate(workflow_id, samples):
        durations = sorted(sample['duration_ms'] for sample in samples)
        midpoint = len(durations) // 2
        median = durations[midpoint] if len(durations) % 2 else (durations[midpoint - 1] + durations[midpoint]) / 2
        credits = math.ceil(median / 6000)
        return {'id': workflow_id, 'samples': len(samples), 'job_ids': [sample['job_id'] for sample in samples],
                'source': samples[0]['source_tier'], 'source_event': EVENT,
                'median_seconds': median / 1000, 'credits': credits, 'amount_minor': credits,
                'current_graph_compatible': True, 'current_catalog_status': 'connected'}

    def write_inputs(self):
        self.audit_path.write_text(json.dumps(self.audit), 'utf-8')
        self.policy_path.write_text(json.dumps(self.policy), 'utf-8')

    def run_setup(self, *, apply=False):
        return apply_setup(self.db_path, self.private, self.audit_path, self.policy_path, self.backups,
                           apply=apply, connected_ids={'workflow-a', 'workflow-b'})

    def fingerprints(self):
        with readonly_database(self.db_path) as db:
            return protected_fingerprints(db)

    def test_default_is_read_only_and_makes_no_backup_or_marker(self):
        before = self.db_path.read_bytes()
        with patch.object(PlatformAccounts, '__init__', side_effect=AssertionError('No store initialization')):
            report = self.run_setup()
        self.assertEqual('dry_run', report['status'])
        self.assertEqual((0, 2, 2), (report['writes'], report['prices_inserted'], report['packages_inserted']))
        self.assertEqual(before, self.db_path.read_bytes())
        self.assertFalse(self.backups.exists())
        self.assertEqual(report['protected_before'], report['protected_after'])

    def test_atomic_apply_has_backup_audit_and_preserves_funded_held_accounts_and_media(self):
        before = self.fingerprints()
        with readonly_database(self.db_path) as db:
            audits_before = db.execute('SELECT COUNT(*) FROM platform_admin_audit').fetchone()[0]
        report = self.run_setup(apply=True)
        self.assertEqual('applied', report['status'])
        self.assertEqual(before, self.fingerprints())
        self.assertEqual(before, report['protected_before'])
        self.assertEqual(before, report['protected_after'])
        self.assertTrue(Path(report['summary_path']).is_file())
        with readonly_database(report['backup_path']) as db:
            self.assertEqual(before, protected_fingerprints(db))
            self.assertEqual(1, db.execute('SELECT COUNT(*) FROM platform_prices').fetchone()[0])
            self.assertIsNone(db.execute('SELECT value FROM platform_metadata WHERE key=?', (MARKER,)).fetchone())
        with readonly_database(self.db_path) as db:
            self.assertEqual([('workflow-a', 1), ('workflow-b', 2)],
                             [tuple(row) for row in db.execute("SELECT workflow_id,credits FROM platform_prices WHERE workflow_id LIKE 'workflow-%' ORDER BY workflow_id")])
            self.assertEqual((88, 12), tuple(db.execute('SELECT balance,held FROM platform_accounts WHERE id=?', (self.user['id'],)).fetchone()))
            self.assertEqual(audits_before + 5, db.execute('SELECT COUNT(*) FROM platform_admin_audit').fetchone()[0])
            marker = json.loads(db.execute('SELECT value FROM platform_metadata WHERE key=?', (MARKER,)).fetchone()[0])
            self.assertEqual('applied', marker['status'])
        self.assertNotIn('isolated-pricing-user', json.dumps(report))
        self.assertNotIn('private-token-fixture', json.dumps(report))
        self.assertNotIn('"prompt"', json.dumps(report))

    def test_existing_administrator_configuration_is_kept_even_when_different(self):
        self.accounts.configure_pricing(self.admin['id'], 'workflow-a', 42)
        self.accounts.configure_package(self.admin['id'], 'credits-5000', 'custom package', 250, 200, enabled=False)
        report = self.run_setup(apply=True)
        self.assertEqual((1, 1, 1, 1), (report['prices_inserted'], report['packages_inserted'],
                                      report['different_prices_preserved'], report['different_packages_preserved']))
        self.assertEqual(42, self.accounts.pricing('workflow-a')['credits'])
        package = next(item for item in self.accounts.packages(self.admin['id']) if item['id'] == 'credits-5000')
        self.assertEqual(('custom package', 250, 200, False),
                         (package['title'], package['credits'], package['amount_minor'], package['enabled']))

    def test_completed_marker_prevents_any_write_or_override_after_manual_edit(self):
        self.run_setup(apply=True)
        self.accounts.configure_pricing(self.admin['id'], 'workflow-a', 77)
        before, files = self.db_path.read_bytes(), sorted(path.name for path in self.backups.iterdir())
        self.audit_path.unlink()
        self.policy_path.unlink()
        with patch.object(PlatformAccounts, '__init__', side_effect=AssertionError('No initialization')):
            report = self.run_setup(apply=True)
        self.assertEqual({'status': 'already_applied', 'writes': 0}, report)
        self.assertEqual(before, self.db_path.read_bytes())
        self.assertEqual(files, sorted(path.name for path in self.backups.iterdir()))
        self.assertEqual(77, self.accounts.pricing('workflow-a')['credits'])

    def test_audit_failure_rolls_back_all_prices_packages_and_marker(self):
        before = self.fingerprints()
        calls, original = [], PlatformAccounts._audit

        def fail_after_first(store, db, *arguments, **keywords):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('fixture audit failure')
            return original(store, db, *arguments, **keywords)

        with patch.object(PlatformAccounts, '_audit', fail_after_first):
            with self.assertRaises(RuntimeError):
                self.run_setup(apply=True)
        self.assertEqual(before, self.fingerprints())
        with readonly_database(self.db_path) as db:
            self.assertEqual(1, db.execute('SELECT COUNT(*) FROM platform_prices').fetchone()[0])
            self.assertEqual(1, db.execute('SELECT COUNT(*) FROM platform_packages').fetchone()[0])
            self.assertIsNone(db.execute('SELECT 1 FROM platform_metadata WHERE key=?', (MARKER,)).fetchone())

    def test_unexpected_balance_trigger_is_detected_and_rolled_back(self):
        with self.accounts.transaction() as db:
            db.execute("CREATE TRIGGER pricing_bad_trigger AFTER INSERT ON platform_prices BEGIN UPDATE platform_accounts SET balance=balance+1 WHERE role='user'; END")
        before = self.fingerprints()
        with self.assertRaises(SetupError):
            self.run_setup(apply=True)
        self.assertEqual(before, self.fingerprints())
        self.assertFalse(self.accounts.pricing('workflow-a')['configured'])

    def test_incorrect_cent_rounding_is_rejected_before_backup(self):
        self.audit['apply_candidates'][1]['credits'] = 1
        self.audit['apply_candidates'][1]['amount_minor'] = 1
        self.write_inputs()
        with self.assertRaises(SetupError):
            self.run_setup(apply=True)
        self.assertFalse(self.backups.exists())

    def test_even_sample_median_preserves_fractional_millisecond_boundary(self):
        first, second = self.sample('workflow-a', 6000), self.sample('workflow-a', 6001)
        self.audit['samples'] = [first, second, self.audit['samples'][1]]
        self.audit['apply_candidates'][0] = self.candidate('workflow-a', [first, second])
        prices, _ = validate_inputs(self.audit, self.policy, self.private, {'workflow-a', 'workflow-b'})
        self.assertEqual(('6.0005', 2), (prices[0]['median_seconds'], prices[0]['credits']))

    def test_receipt_changed_after_audit_is_rejected(self):
        sample = self.audit['samples'][0]
        receipt = self.private / 'receipts' / (sample['job_id'] + '.json')
        receipt.write_text('{}', 'utf-8')
        with self.assertRaises(SetupError):
            self.run_setup(apply=True)
        self.assertFalse(self.backups.exists())

    def test_duplicate_task_or_workflow_and_disconnected_catalog_are_rejected(self):
        for mutate in (
            lambda audit: audit['samples'].append(deepcopy(audit['samples'][0])),
            lambda audit: audit['apply_candidates'].__setitem__(1, deepcopy(audit['apply_candidates'][0])),
            lambda audit: audit['apply_candidates'][0].__setitem__('current_catalog_status', 'demo'),
            lambda audit: audit['apply_candidates'][0].__setitem__('current_graph_compatible', False),
        ):
            audit = deepcopy(self.audit)
            mutate(audit)
            with self.assertRaises(SetupError):
                validate_inputs(audit, self.policy, self.private, {'workflow-a', 'workflow-b'})
        with self.assertRaises(SetupError):
            validate_inputs(self.audit, self.policy, self.private, {'workflow-a'})

    def test_bad_package_conversion_or_duplicate_id_is_rejected(self):
        for mutate in (
            lambda policy: policy['recharge_packages'][0].__setitem__('credits', 5001),
            lambda policy: policy['recharge_packages'].__setitem__(1, deepcopy(policy['recharge_packages'][0])),
            lambda policy: policy['credit_policy'].__setitem__('credits_per_yuan', 10),
        ):
            policy = deepcopy(self.policy)
            mutate(policy)
            with self.assertRaises(SetupError):
                validate_inputs(self.audit, policy, self.private, {'workflow-a', 'workflow-b'})

    def test_requires_unique_enabled_admin_and_never_bootstraps_another(self):
        with self.accounts.transaction() as db:
            db.execute("UPDATE platform_accounts SET role='admin' WHERE id=?", (self.user['id'],))
        before = self.db_path.read_bytes()
        with self.assertRaises(SetupError):
            self.run_setup(apply=True)
        self.assertEqual(before, self.db_path.read_bytes())
        self.assertFalse(self.backups.exists())


if __name__ == '__main__':
    unittest.main()
