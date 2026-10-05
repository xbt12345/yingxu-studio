"""Native upper bounds for twelve source-pinned legacy Seed(rgthree) inputs."""
import json
from copy import deepcopy
from configuration import workflow_path

NATIVE_SEED_MAX=1125899906842624
# source hash, public field ID, real adapter seed node, unchanged source default,
# unchanged public fan-out targets (the legacy adapter writes the source node).
NATIVE_SEED_LIMITS={
 'local-card-11':('7187415a3c6356f0e08fef5d4fad85711a8b8924fe1f24b3fcc29b82c2323a82','157:widget_0','157',569254798548715,('95','151')),
 'local-card-1':('fbac8d2ce1b8a6e693df3b09b73581f298fd0ea83a19d7e45a71b23fb0bd1b78','476:seed','476',82699899253102,('476',)),
 'local-card-2':('815d61d4572bc26b5b48887b81898a320b0b9ef59bceb92f7872914a27ebf7b4','536:seed','536',464514344583800,('536',)),
 'local-card-3':('de7a0f266cbe0ad9a55b11ab2773432ae3c89c06287b6a445c3bad4d57d72cbe','558:seed','558',464514344583800,('558',)),
 'local-card-10':('3f9a342cb1e531341c814e8d2957a204478c4a9d5e59dba4b853e39c9b630aa3','75:widget_0','75',939420269158328,('18','101','107')),
 'local-card-12':('f92ee25a601ac4c605a55a7fbf1d4d94a07171b2435aedf58a83d315004cadbe','158:seed','158',233142225574857,('158',)),
 'local-card-84':('70cd011f73d8d258352a0016c26d0aae4425d1ac922de94d55b17e74b8db8976','515:seed','515',464514344583800,('515',)),
 'local-card-104':('37c0484ccf564d9e5769c2aadbef0cec6ebcde95b38ed69df12fa9d66507cd74','116:seed','116',752166193025910,('116',)),
 'local-card-109':('28d3c6cd298a1f5d348807ac1caf72c9b92057bec8179bcc400c1a881a7ff6bc','57:seed','57',752166193025910,('57','48','51')),
 'local-card-128':('090f7382dcc16a1e83fdf5a79d98b82047b878afb33585a713b503792aa3bf2e','57:seed','57',752166193025910,('57','48','51')),
 'local-card-129':('9c180931c17ca7d0fadc0f15bdac5c7e1df4bbfa0d1773a9aab1f2aa5a1b7c89','116:seed','116',752166193025910,('116',)),
 'local-card-130':('9496874c21af745f76cf41b7c8184558b90bb7c44b6a1b4fd97389fc77ec36a9','5:seed','5',572148531282190,('5',))}


def reviewed_native_seed_limits(workflow,controls,*,graph=None,source_hash=None,derived=None):
    contract=NATIVE_SEED_LIMITS.get(workflow.get('id'))
    if contract is None:return controls
    expected,fid,nid,value,target_nodes=contract
    if source_hash!=expected:raise ValueError('原生种子范围的来源已改变。')
    fields=[f for f in controls if f.get('id')==fid]
    targets=[{'node':node,'input':'seed'}for node in target_nodes]
    if (len(fields)!=1 or fields[0].get('kind')!='seed' or fields[0].get('value')!=value or
        fields[0].get('nodeId',fields[0]['id'].split(':')[0])!=nid or fields[0].get('targets')!=targets):
        raise ValueError('原生种子控件与真实来源未匹配。')
    field=fields[0]
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        node=graph.nodes.get(nid,{})
        source_value=widget_bindings(node).get('seed',(None,))[0]
        if fid.endswith(':widget_0'):
            # These two pinned sources have an implicit rgthree seed widget.
            values=node.get('widgets_values')
            if node.get('inputs')!=[] or values!=[value,'','','']:
                raise ValueError('隐式原生种子控件已改变。')
            source_value=values[0]
        if (node.get('type')!='Seed (rgthree)' or nid not in graph.reachable or
            not graph.editable(nid,'seed') or source_value!=value):
            raise ValueError('原生种子节点或原默认值已改变。')
        template=json.loads(workflow_path(workflow['id']).read_text(encoding='utf-8'))
        actual=template.get(nid,{})
        if actual.get('class_type')!='Seed (rgthree)' or actual.get('inputs',{}).get('seed')!=value:
            raise ValueError('实际执行模板的原生种子节点已改变。')
    else:
        proofs=[f for f in (derived or {}).get('controls',[])if f.get('id')==fid]
        if ((derived or {}).get('sourceHash')!=expected or len(proofs)!=1 or
            proofs[0].get('max')!=NATIVE_SEED_MAX or
            proofs[0].get('nodeId',proofs[0]['id'].split(':')[0])!=nid or
            any(proofs[0].get(k)!=field.get(k)for k in ('id','key','value','targets','members'))):
            raise ValueError('缺少原生种子上界的同源证明。')
    result=deepcopy(controls)
    next(f for f in result if f['id']==fid)['max']=NATIVE_SEED_MAX
    return result


def validate_legacy_native_seed(workflow,supplied):
    """Preflight only the twelve legacy routes; their normal logic stays intact."""
    contract=NATIVE_SEED_LIMITS.get(workflow.get('id'))
    if contract is None:return
    if workflow.get('source_hash')!=contract[0]:
        raise ValueError('原生种子范围的来源已改变。')
    value=supplied.get('seed',-1)
    if isinstance(value,bool) or not isinstance(value,int) or not -1<=value<=NATIVE_SEED_MAX:
        raise ValueError('随机种子需为 -1 到 1125899906842624 之间的整数。')
