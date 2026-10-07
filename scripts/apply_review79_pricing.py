"""Explicit, one-time Review 79 price setup; the default is read-only.

This command operates on an already initialized account database. It never
constructs PlatformAccounts, bootstraps an account, migrates tables, or starts
the server. Existing administrator prices/packages always take precedence.
"""
import argparse
import ast
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from platform_accounts import PlatformAccounts

MARKER = 'review79_pricing_seed'
EVENT = 'status.messages:execution_start→execution_success'
SOURCES = frozenset(('main_workspace', 'historical_acceptance'))
ALLOWED_TABLES = frozenset(('platform_prices', 'platform_packages',
                          'platform_metadata', 'platform_admin_audit'))


class SetupError(ValueError):
    """A setup input or preserved-data invariant failed before commit."""


def _require(condition, message):
    if not condition:
        raise SetupError(message)


def _json(path):
    return json.loads(Path(path).read_text('utf-8-sig'), parse_float=Decimal)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _decimal(value):
    _require(type(value) in (int, float, Decimal, str), '无效的耗时数值。')
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise SetupError('无效的耗时数值。') from error
    _require(number.is_finite() and number > 0, '耗时必须为有限正数。')
    return number


def current_connected_ids(root=ROOT):
    """Read current adapter/registry contracts without importing server config."""
    root = Path(root)
    tree = ast.parse((root / 'adapters.py').read_text('utf-8-sig'))
    ids = set()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id in ('WORKFLOWS', 'CATALOG_WORKFLOWS')
            for target in statement.targets
        ):
            continue
        for node in ast.walk(statement.value):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'dict':
                for keyword in node.keywords:
                    if keyword.arg == 'id' and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                        ids.add(keyword.value.value)
    registry = _json(root / 'workflows/compiled-registry.json').get('workflows', {})
    _require(isinstance(registry, dict), '当前执行目录无效。')
    ids.update(key for key, spec in registry.items() if isinstance(spec, dict)
               and spec.get('adapter') == 'generic' and spec.get('validation') == 'structural-verified')
    return ids


def _receipt(sample, private_dir):
    job_id = sample['job_id']
    parts = Path(sample.get('source', '')).parts
    tier = sample.get('source_tier')
    expected_main = ('private', 'receipts', job_id + '.json')
    expected_history = (len(parts) == 4 and parts[0] == 'private'
                        and re.fullmatch(r'review\d+-runtime', parts[1])
                        and parts[2:] == ('receipts', job_id + '.json'))
    _require((tier == 'main_workspace' and parts == expected_main)
             or (tier == 'historical_acceptance' and expected_history), '历史回执来源不符合审查范围。')
    private_dir = Path(private_dir).resolve()
    path = private_dir.joinpath(*parts[1:]).resolve()
    _require(path.is_relative_to(private_dir), '回执路径越过私有数据目录。')
    raw = path.read_bytes()
    _require(_sha(raw) == sample.get('receipt_sha256'), '历史回执与审查摘要不一致。')
    receipt = json.loads(raw.decode('utf-8-sig'))
    status = receipt.get('status', {})
    _require(status.get('completed') is True and status.get('status_str') == 'success', '回执不是成功执行。')
    messages = status.get('messages', [])
    starts = [item[1] for item in messages if isinstance(item, list) and len(item) == 2 and item[0] == 'execution_start']
    successes = [item[1] for item in messages if isinstance(item, list) and len(item) == 2 and item[0] == 'execution_success']
    _require(len(starts) == 1 and len(successes) == 1, '执行时间事件不唯一。')
    start, success = starts[0], successes[0]
    _require(isinstance(start, dict) and isinstance(success, dict), '执行时间事件无效。')
    prompt_id = start.get('prompt_id')
    _require(isinstance(prompt_id, str) and prompt_id and prompt_id == success.get('prompt_id'), '执行事件不属于同一次任务。')
    start_ms, success_ms, duration_ms = (sample.get('start_timestamp_ms'),
                                       sample.get('success_timestamp_ms'), sample.get('duration_ms'))
    _require(all(type(number) is int and number > 0 for number in (start_ms, success_ms, duration_ms))
             and success_ms - start_ms == duration_ms
             and start.get('timestamp') == start_ms and success.get('timestamp') == success_ms,
             '执行毫秒数与回执不一致。')
    _require(_decimal(sample.get('seconds')) == Decimal(duration_ms) / 1000, '样本秒数与毫秒数不一致。')
    cached, nodes = sample.get('cached_node_count'), sample.get('graph_node_count')
    _require(type(nodes) is int and nodes > 0 and type(cached) is int and 0 <= cached < nodes,
             '完整缓存或未知执行图不能用于耗时定价。')
    compatibility = sample.get('compatibility', {})
    historical_hash = compatibility.get('historical_execution_graph_sha256', '')
    _require(compatibility.get('compatible') is True and compatibility.get('reason') == 'offline_rebuild_matches'
             and re.fullmatch(r'[a-f0-9]{64}', historical_hash)
             and historical_hash == compatibility.get('current_rebuilt_graph_sha256'),
             '样本没有当前执行图兼容性证据。')
    return prompt_id


def validate_inputs(audit, policy, private_dir, connected_ids):
    """Validate every selected sample and calculate exact cent-rounded medians."""
    _require(isinstance(audit, dict) and isinstance(policy, dict), '配置与审查文件须为对象。')
    credit_policy = policy.get('credit_policy', {})
    _require(credit_policy.get('currency') == 'CNY'
             and type(credit_policy.get('credits_per_yuan')) is int
             and credit_policy['credits_per_yuan'] == 100
             and credit_policy.get('rounding') == 'ceil_to_fen', '积分兑换口径不符合已确认设置。')
    candidates = audit.get('apply_candidates')
    count = policy.get('workflow_pricing', {}).get('eligible_count')
    _require(isinstance(candidates, list) and type(count) is int and count > 0 and len(candidates) == count,
             '候选数量与公开定价策略不一致。')
    samples = audit.get('samples')
    _require(isinstance(samples, list), '缺少历史样本。')
    by_job = {}
    for sample in samples:
        _require(isinstance(sample, dict) and isinstance(sample.get('job_id'), str)
                 and re.fullmatch(r'[a-f0-9]{32}', sample['job_id']), '样本任务编号无效。')
        _require(sample['job_id'] not in by_job, '历史任务样本重复。')
        by_job[sample['job_id']] = sample
    prices, seen_ids, seen_jobs, seen_prompts = [], set(), set(), set()
    for candidate in candidates:
        _require(isinstance(candidate, dict), '候选工作流无效。')
        workflow_id = candidate.get('id')
        PlatformAccounts._identifier(workflow_id, '工作流编号')
        _require(workflow_id not in seen_ids and workflow_id in connected_ids,
                 '候选工作流重复或不在当前可执行目录。')
        seen_ids.add(workflow_id)
        _require(candidate.get('current_graph_compatible') is True
                 and candidate.get('current_catalog_status') == 'connected'
                 and candidate.get('source') in SOURCES and candidate.get('source_event') == EVENT,
                 '候选工作流没有可靠的当前执行耗时依据。')
        jobs = candidate.get('job_ids')
        _require(isinstance(jobs, list) and jobs and type(candidate.get('samples')) is int
                 and candidate['samples'] == len(jobs) and len(set(jobs)) == len(jobs), '候选样本数量或唯一性不一致。')
        selected = []
        for job_id in jobs:
            sample = by_job.get(job_id)
            _require(job_id not in seen_jobs and sample is not None
                     and sample.get('workflow_id') == workflow_id and sample.get('source_tier') == candidate['source'],
                     '候选引用了重复、缺失或其他来源的样本。')
            seen_jobs.add(job_id)
            prompt_id = _receipt(sample, private_dir)
            _require(prompt_id not in seen_prompts, '同次远程执行不能重复计入定价样本。')
            seen_prompts.add(prompt_id)
            selected.append(sample['duration_ms'])
        if candidate['source'] == 'historical_acceptance':
            _require(not any(sample.get('workflow_id') == workflow_id
                             and sample.get('source_tier') == 'main_workspace'
                             and sample.get('compatibility', {}).get('compatible') is True
                             for sample in samples), '可用主库历史优先于验收历史。')
        selected.sort()
        midpoint = len(selected) // 2
        median_ms = Decimal(selected[midpoint]) if len(selected) % 2 else Decimal(selected[midpoint - 1] + selected[midpoint]) / 2
        median_seconds = median_ms / 1000
        _require(_decimal(candidate.get('median_seconds')) == median_seconds, '候选中位数与成功执行样本不一致。')
        credits = int((median_ms / 6000).to_integral_value(rounding=ROUND_CEILING))
        _require(type(candidate.get('credits')) is int and type(candidate.get('amount_minor')) is int
                 and candidate['credits'] == candidate['amount_minor'] == credits, '候选费用未按每六秒一积分向上取整。')
        PlatformAccounts._integer(credits, '工作流积分', 1)
        prices.append({'workflow_id': workflow_id, 'credits': credits,
                       'samples': len(jobs), 'median_seconds': str(median_seconds), 'source': candidate['source']})
    packages, seen_packages = [], set()
    _require(isinstance(policy.get('recharge_packages'), list) and policy['recharge_packages'], '缺少积分套餐。')
    for package in policy['recharge_packages']:
        _require(isinstance(package, dict), '积分套餐无效。')
        PlatformAccounts._identifier(package.get('id'), '套餐编号')
        _require(package['id'] not in seen_packages, '积分套餐编号重复。')
        seen_packages.add(package['id'])
        _require(isinstance(package.get('title'), str) and 1 <= len(package['title'].strip()) <= 80
                 and package.get('currency') == 'CNY' and type(package.get('enabled')) is bool, '套餐名称、币种或状态无效。')
        credits = PlatformAccounts._integer(package.get('credits'), '套餐积分', 1)
        amount = PlatformAccounts._integer(package.get('amount_minor'), '套餐金额', 1)
        _require(credits == amount, '套餐不符合每元一百积分的兑换口径。')
        packages.append({'id': package['id'], 'title': package['title'].strip(), 'credits': credits,
                         'amount_minor': amount, 'currency': 'CNY', 'enabled': package['enabled']})
    return prices, packages


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def protected_fingerprints(db):
    """Only counts and hashes leave the process, never account/media row values."""
    summary = {}
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for name in tables:
        if name in ALLOWED_TABLES:
            continue
        query = 'SELECT * FROM ' + _quoted(name)
        if name == 'sqlite_sequence':
            query += " WHERE name != 'platform_admin_audit'"
        cursor = db.execute(query)
        columns = [column[0] for column in cursor.description]
        rows = [json.dumps(list(row), ensure_ascii=True, separators=(',', ':'),
                           default=lambda value: {'bytes_sha256': _sha(value)}) for row in cursor]
        rows.sort()
        summary[name] = {'count': len(rows), 'sha256': _sha(json.dumps([columns, rows], separators=(',', ':')).encode())}
    # Existing metadata is also preserved, except for the explicitly added marker.
    rows = [list(row) for row in db.execute('SELECT key,value FROM platform_metadata WHERE key != ? ORDER BY key', (MARKER,))]
    summary['platform_metadata_existing'] = {'count': len(rows), 'sha256': _sha(json.dumps(rows, ensure_ascii=True).encode())}
    return summary


@contextmanager
def readonly_database(path):
    path = Path(path).resolve()
    _require(path.is_file(), '账户数据库不存在，不能自动初始化。')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def _plan(db, prices, packages):
    old_prices = {row['workflow_id']: row['credits'] for row in db.execute('SELECT workflow_id,credits FROM platform_prices')}
    old_packages = {row['id']: dict(row) for row in db.execute('SELECT * FROM platform_packages')}
    insert_prices = [item for item in prices if item['workflow_id'] not in old_prices]
    insert_packages = [item for item in packages if item['id'] not in old_packages]
    report = {'candidate_prices': len(prices), 'candidate_packages': len(packages),
              'prices_inserted': len(insert_prices), 'packages_inserted': len(insert_packages),
              'prices_preserved': len(prices) - len(insert_prices), 'packages_preserved': len(packages) - len(insert_packages),
              'different_prices_preserved': sum(item['workflow_id'] in old_prices and old_prices[item['workflow_id']] != item['credits'] for item in prices),
              'different_packages_preserved': sum(item['id'] in old_packages and any(old_packages[item['id']][key] != value for key, value in item.items()) for item in packages)}
    return insert_prices, insert_packages, report


def apply_setup(db_path, private_dir, audit_path, policy_path, backup_dir, *, apply=False, connected_ids=None):
    db_path, private_dir, backup_dir = Path(db_path).resolve(), Path(private_dir).resolve(), Path(backup_dir).resolve()
    # This early return must not touch inputs, backups, schema, or audit rows.
    with readonly_database(db_path) as db:
        marker = db.execute('SELECT value FROM platform_metadata WHERE key = ?', (MARKER,)).fetchone()
        if marker is not None:
            return {'status': 'already_applied', 'writes': 0}
    audit_bytes, policy_bytes = Path(audit_path).read_bytes(), Path(policy_path).read_bytes()
    audit = json.loads(audit_bytes.decode('utf-8-sig'), parse_float=Decimal)
    policy = json.loads(policy_bytes.decode('utf-8-sig'), parse_float=Decimal)
    prices, packages = validate_inputs(audit, policy, private_dir,
                                      current_connected_ids() if connected_ids is None else set(connected_ids))
    with readonly_database(db_path) as db:
        _, _, report = _plan(db, prices, packages)
        protected = protected_fingerprints(db)
        admins = list(db.execute("SELECT id FROM platform_accounts WHERE role='admin' AND enabled=1"))
        _require(len(admins) == 1, '需要唯一现存且启用的管理员作为配置审计人。')
        if not apply:
            return {'status': 'dry_run', 'writes': 0, **report, 'protected_before': protected, 'protected_after': protected}
    # Bind only the existing store primitives; __init__ performs migrations.
    accounts = PlatformAccounts.__new__(PlatformAccounts)
    accounts.db_path, accounts.private_dir, accounts.clock = db_path, private_dir, time.time
    with accounts.transaction() as db:
        if db.execute('SELECT 1 FROM platform_metadata WHERE key = ?', (MARKER,)).fetchone():
            return {'status': 'already_applied', 'writes': 0}
        admins = list(db.execute("SELECT id FROM platform_accounts WHERE role='admin' AND enabled=1"))
        _require(len(admins) == 1, '需要唯一现存且启用的管理员作为配置审计人。')
        actor_id = admins[0]['id']
        accounts._admin(db, actor_id)
        _require(Path(audit_path).read_bytes() == audit_bytes and Path(policy_path).read_bytes() == policy_bytes,
                 '审查输入在验证后发生变化，不能应用旧候选。')
        insert_prices, insert_packages, report = _plan(db, prices, packages)
        before = protected_fingerprints(db)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / ('workspace-before-review79-pricing-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.sqlite3')
        _require(backup_path.resolve() != db_path, '备份路径不能覆盖数据库。')
        # A second read-only connection backs up the committed snapshot while
        # BEGIN IMMEDIATE prevents another writer from changing that snapshot.
        with readonly_database(db_path) as source:
            with closing(sqlite3.connect(backup_path)) as destination:
                source.backup(destination)
        now = accounts._now()
        for item in insert_prices:
            db.execute('INSERT INTO platform_prices(workflow_id,credits,updated_by,updated_at) VALUES(?,?,?,?)',
                       (item['workflow_id'], item['credits'], actor_id, now))
            accounts._audit(db, actor_id, 'configure_pricing', item['workflow_id'],
                            {key: value for key, value in item.items() if key != 'workflow_id'})
        for item in insert_packages:
            db.execute('INSERT INTO platform_packages(id,title,credits,amount_minor,currency,enabled,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                       (item['id'], item['title'], item['credits'], item['amount_minor'], item['currency'], int(item['enabled']), actor_id, now))
            accounts._audit(db, actor_id, 'configure_package', item['id'],
                            {key: value for key, value in item.items() if key != 'id'})
        after = protected_fingerprints(db)
        _require(before == after, '受保护的账户、积分、订单或作品数据发生变化，事务已撤销。')
        result = {'status': 'applied', **report, 'backup_path': str(backup_path),
                  'protected_before': before, 'protected_after': after,
                  'audit_sha256': _sha(audit_bytes), 'policy_sha256': _sha(policy_bytes)}
        accounts._audit(db, actor_id, MARKER, MARKER, report)
        db.execute('INSERT INTO platform_metadata(key,value) VALUES(?,?)',
                   (MARKER, json.dumps(result, ensure_ascii=False, separators=(',', ':'))))
    summary_path = backup_path.with_suffix('.json')
    try:
        summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        result['summary_path'] = str(summary_path)
    except OSError:
        # The transaction is already committed; recovery proof also lives in
        # the marker. Do not misreport this successful seed as rolled back.
        result['summary_warning'] = '摘要文件未写入；完整核验摘要已保存于数据库 seed marker。'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Review 79 定价配置；默认只读，--apply 才写入。')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--db', type=Path, default=ROOT / 'private/workspace.sqlite3')
    parser.add_argument('--private', type=Path, default=ROOT / 'private')
    parser.add_argument('--audit', type=Path, default=ROOT / 'docs/workflow-time-pricing-audit-2026-10-07.json')
    parser.add_argument('--policy', type=Path, default=ROOT / 'public/pricing-policy.json')
    parser.add_argument('--backup-dir', type=Path, default=ROOT / 'private/review79-pricing-backups')
    arguments = parser.parse_args(argv)
    try:
        result = apply_setup(arguments.db, arguments.private, arguments.audit, arguments.policy,
                             arguments.backup_dir, apply=arguments.apply)
    except Exception as error:
        print(json.dumps({'status': 'error', 'code': type(error).__name__,
                          'message': '配置没有提交。请检查审查输入、回执和本地数据库。'}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
