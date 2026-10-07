"""Publish the approved Review79 prices once, without private runtime evidence.

Existing installations share the explicit setup's marker. Administrator edits,
including deletion after initialization, are authoritative on later starts.
"""
import ast
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid
from platform_accounts import PlatformAccounts

ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / 'workflows/platform-pricing-seed.json'
MARKER = 'review79_pricing_seed'
PRICE_COUNT = 93
PACKAGE_COUNT = 6
# Canonical JSON binds the approved prices/packages without retaining receipts.
APPROVED_PLAN_SHA256 = 'b2e0cb4e32b7546d6a1e4b61ed9f0891b59cd78d1f7732b849afa7f2f6696f92'
ALLOWED_TABLES = frozenset(('platform_prices', 'platform_packages', 'platform_metadata', 'platform_admin_audit'))


class PricingSeedError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise PricingSeedError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def current_contracts(root=ROOT):
    """Inspect shipped adapters/registry without importing the server or config."""
    root = Path(root)
    contracts = {}
    tree = ast.parse((root / 'adapters.py').read_text('utf-8-sig'))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or not any(isinstance(t, ast.Name) and t.id in ('WORKFLOWS','CATALOG_WORKFLOWS') for t in statement.targets):
            continue
        for call in statement.value.elts:
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != 'dict':
                raise PricingSeedError('部署工作流适配器目录格式无效。')
            literals = {k.arg:k.value.value for k in call.keywords if isinstance(k.value, ast.Constant)}
            identifier = literals.get('id')
            _require(isinstance(identifier,str) and identifier not in contracts,'部署工作流编号重复或无效。')
            source_hash = literals.get('source_hash')
            _require(source_hash is not None or identifier in ('h3-reference','bernini-edit'),'工作流缺少已确认源身份。')
            contracts[identifier] = {'source_hash':source_hash,'template':identifier+'.api.json'}
    registry = _json(root / 'workflows/compiled-registry.json').get('workflows')
    _require(isinstance(registry,dict),'部署执行目录格式无效。')
    for identifier,spec in registry.items():
        if not isinstance(spec,dict) or spec.get('adapter')!='generic' or spec.get('validation')!='structural-verified':
            continue
        _require(identifier not in contracts and spec.get('id')==identifier,'部署执行合同编号重复或不一致。')
        contracts[identifier] = {'source_hash':spec.get('source_hash'),'template':spec.get('template')}
    return contracts


def validate_plan(plan, root=ROOT):
    """Require approved sizes, exact contract identity and current portable bytes."""
    _require(isinstance(plan,dict) and set(plan)=={'version','marker','credit_policy','prices','packages'},'部署定价计划字段无效。')
    digest=_sha(json.dumps(plan,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())
    _require(digest==APPROVED_PLAN_SHA256,'部署定价计划与已确认发布内容不一致。')
    _require(type(plan['version'])is int and plan['version']==1 and plan['marker']==MARKER,'部署定价计划版本无效。')
    _require(plan['credit_policy']=={'currency':'CNY','credits_per_yuan':100,'rounding':'ceil_to_fen'},'部署积分口径无效。')
    prices,packages=plan['prices'],plan['packages']
    _require(isinstance(prices,list) and len(prices)==PRICE_COUNT and isinstance(packages,list) and len(packages)==PACKAGE_COUNT,'部署已确认定价数量不一致。')
    contracts=current_contracts(root)
    raw_manifest=_json(Path(root)/'workflows/manifest.json').get('workflows')
    _require(isinstance(raw_manifest,list),'部署模板清单格式无效。')
    manifest={}
    for entry in raw_manifest:
        _require(isinstance(entry,dict) and isinstance(entry.get('id'),str) and entry['id']not in manifest,'部署模板清单重复或无效。')
        manifest[entry['id']]=entry
    seen=set()
    for price in prices:
        _require(isinstance(price,dict) and set(price)=={'workflow_id','credits','source_hash','template_sha256','samples','median_seconds'},'部署定价项目字段无效。')
        identifier=price['workflow_id']
        _require(isinstance(identifier,str) and identifier not in seen and identifier in contracts and identifier in manifest,'部署定价不属于已接入工作流。')
        seen.add(identifier)
        _require(type(price['credits'])is int and 1<=price['credits']<=PlatformAccounts.MAX_CREDITS and type(price['samples'])is int and price['samples']>0,'部署积分或样本数无效。')
        try:median=Decimal(price['median_seconds'])if isinstance(price['median_seconds'],str)else Decimal('NaN')
        except InvalidOperation:median=Decimal('NaN')
        _require(median.is_finite() and median>0 and price['credits']==int((median/6).to_integral_value(rounding=ROUND_CEILING)),'部署费用不符合已确认耗时口径。')
        source_hash=price['source_hash']
        _require(source_hash==contracts[identifier]['source_hash']==manifest[identifier].get('source_hash'),'部署工作流源身份已变化。')
        _require(source_hash is None and identifier in ('h3-reference','bernini-edit') or isinstance(source_hash,str) and re.fullmatch('[a-f0-9]{64}',source_hash),'部署工作流源身份无效。')
        template=contracts[identifier]['template']
        _require(isinstance(template,str) and Path(template).name==template and template.endswith('.api.json') and template==manifest[identifier].get('template'),'部署执行模板名称不一致。')
        folder=(Path(root)/'workflows/api').resolve()
        path=(folder/template).resolve()
        _require(path.is_relative_to(folder) and path.is_file(),'部署执行模板缺失或越过目录。')
        digest=price['template_sha256']
        _require(isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest) and digest==manifest[identifier].get('template_sha256')==_sha(path.read_bytes()),'部署执行模板与已审查定价不一致。')
    seen=set()
    for package in packages:
        _require(isinstance(package,dict) and set(package)=={'id','title','credits','amount_minor','currency','enabled'},'部署积分套餐字段无效。')
        identifier=package['id']
        _require(isinstance(identifier,str) and re.fullmatch('[A-Za-z0-9_.:-]{1,100}',identifier) and identifier not in seen,'部署套餐编号重复或无效。')
        seen.add(identifier)
        _require(isinstance(package['title'],str) and 1<=len(package['title'].strip())<=80 and package['title']==package['title'].strip(),'部署套餐名称无效。')
        _require(type(package['credits'])is int and 1<=package['credits']<=PlatformAccounts.MAX_CREDITS and type(package['amount_minor'])is int and package['credits']==package['amount_minor'] and package['currency']=='CNY' and type(package['enabled'])is bool,'部署套餐金额或积分口径无效。')
    return prices,packages


def _quoted(name):
    return '"'+name.replace('"','""')+'"'


def protected_fingerprints(db):
    result={}
    for (name,)in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name in ALLOWED_TABLES:continue
        sql='SELECT * FROM '+_quoted(name)
        if name=='sqlite_sequence':sql+=" WHERE name != 'platform_admin_audit'"
        cursor=db.execute(sql)
        columns=[col[0]for col in cursor.description]
        rows=sorted(json.dumps(list(row),ensure_ascii=True,separators=(',',':'),default=lambda value:{'bytes_sha256':_sha(value)})for row in cursor)
        result[name]={'count':len(rows),'sha256':_sha(json.dumps([columns,rows],separators=(',',':')).encode())}
    rows=[list(row)for row in db.execute('SELECT key,value FROM platform_metadata WHERE key != ? ORDER BY key',(MARKER,))]
    result['platform_metadata_existing']={'count':len(rows),'sha256':_sha(json.dumps(rows,ensure_ascii=True).encode())}
    return result


def _existing_rows(db):
    return {table:{str(row[0]):tuple(row)for row in db.execute('SELECT * FROM '+_quoted(table))}
            for table in ('platform_prices','platform_packages','platform_admin_audit')}


def _preserved_rows(before,after):
    return all(after[table].get(key)==row for table,rows in before.items()for key,row in rows.items())


def _backup(store, before, existing):
    private=Path(store.private_dir).resolve()
    _require(not private.is_relative_to((ROOT/'public').resolve()),'定价备份不能保存在公开目录。')
    directory=(private/'pricing-init-backups').resolve()
    _require(directory.is_relative_to(private),'定价备份目录越过私有数据目录。')
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/('workspace-before-pricing-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex+'.sqlite3')
    source=sqlite3.connect(Path(store.db_path).resolve().as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=15)
    source.row_factory=sqlite3.Row
    with closing(source),closing(sqlite3.connect(path))as destination:
        source.backup(destination)
        destination.row_factory=sqlite3.Row
        _require(protected_fingerprints(destination)==before and _existing_rows(destination)==existing,'定价备份核验失败。')
    return path


def seed_reviewed_pricing(store, actor_id, *, plan_path=PLAN_PATH, root=ROOT):
    """Called only after account bootstrap and legacy ownership migration."""
    with store.connection()as db:
        if db.execute('SELECT 1 FROM platform_metadata WHERE key=?',(MARKER,)).fetchone():
            return {'status':'already_applied','writes':0}
    raw=Path(plan_path).read_bytes()
    plan=json.loads(raw.decode('utf-8-sig'))
    prices,packages=validate_plan(plan,root)
    with store.transaction()as db:
        if db.execute('SELECT 1 FROM platform_metadata WHERE key=?',(MARKER,)).fetchone():
            return {'status':'already_applied','writes':0}
        store._admin(db,actor_id)
        _require(Path(plan_path).read_bytes()==raw,'部署定价计划在检查后发生变化。')
        # Recheck current manifest/template bytes while holding the writer lock.
        validate_plan(plan,root)
        before=protected_fingerprints(db)
        existing=_existing_rows(db)
        insert_prices=[p for p in prices if p['workflow_id']not in existing['platform_prices']]
        insert_packages=[p for p in packages if p['id']not in existing['platform_packages']]
        backup=_backup(store,before,existing)
        now=store._now()
        for price in insert_prices:
            db.execute('INSERT INTO platform_prices(workflow_id,credits,updated_by,updated_at) VALUES(?,?,?,?)',(price['workflow_id'],price['credits'],actor_id,now))
            store._audit(db,actor_id,'configure_pricing',price['workflow_id'],{'credits':price['credits'],'source':'reviewed_release_seed'})
        for package in insert_packages:
            db.execute('INSERT INTO platform_packages(id,title,credits,amount_minor,currency,enabled,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)',(package['id'],package['title'],package['credits'],package['amount_minor'],package['currency'],int(package['enabled']),actor_id,now))
            store._audit(db,actor_id,'configure_package',package['id'],{k:v for k,v in package.items()if k!='id'})
        report={'status':'applied','prices_inserted':len(insert_prices),'packages_inserted':len(insert_packages),'prices_preserved':len(prices)-len(insert_prices),'packages_preserved':len(packages)-len(insert_packages),'plan_sha256':_sha(raw),'backup_path':str(backup)}
        store._audit(db,actor_id,MARKER,MARKER,{k:v for k,v in report.items()if k!='backup_path'})
        # Marker and its triggers are covered by the final checks as well.
        marker_value=json.dumps(report,ensure_ascii=False,separators=(',',':'))
        db.execute('INSERT INTO platform_metadata(key,value) VALUES(?,?)',(MARKER,marker_value))
        after=protected_fingerprints(db)
        _require(before==after and _preserved_rows(existing,_existing_rows(db)),'受保护的账户、积分、订单、作品或管理员设置发生变化，定价初始化已撤销。')
        expected_prices=set(existing['platform_prices'])|{p['workflow_id']for p in insert_prices}
        expected_packages=set(existing['platform_packages'])|{p['id']for p in insert_packages}
        actual=_existing_rows(db)
        _require(set(actual['platform_prices'])==expected_prices and set(actual['platform_packages'])==expected_packages,'定价初始化触发了未授权的配置修改。')
        _require(len(actual['platform_admin_audit'])==len(existing['platform_admin_audit'])+len(insert_prices)+len(insert_packages)+1,'定价初始化触发了未授权的审计记录。')
        stored_marker=db.execute('SELECT value FROM platform_metadata WHERE key=?',(MARKER,)).fetchone()
        _require(stored_marker is not None and stored_marker[0]==marker_value,'定价初始化标记被意外修改。')
        for price in insert_prices:
            _require(actual['platform_prices'][price['workflow_id']]==(price['workflow_id'],price['credits'],actor_id,now),'新增工作流价格被意外修改。')
        for package in insert_packages:
            _require(actual['platform_packages'][package['id']]==(package['id'],package['title'],package['credits'],package['amount_minor'],package['currency'],int(package['enabled']),actor_id,now),'新增积分套餐被意外修改。')
    return report
