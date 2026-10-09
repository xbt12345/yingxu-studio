"""Keep the reviewed portrait LLM's three protocol texts out of user input.

The UI submits one set-wide creative request. The three joined role constants
are pipeline instructions, not one prompt per output image. Exact source and
consumer checks protect both current submissions and saved pre-review jobs.
"""
from copy import deepcopy


CONTRACTS = {
    'local-card-80': {
        'source_hash': '83d4166f18f6215116e365394b1d4a3393fcd069d8afd8b6c29ca0e1247c5a41',
        'internal': ('96', '91', '90'), 'user': '146', 'count': '88',
        'replace': '86', 'integer': '85', 'join': '83', 'split': '87',
        'shown': '92', 'encoder': '45', 'sampler': '38', 'decode': '60', 'save': '64',
        'reference': '73',
    },
    'local-card-81': {
        'source_hash': '464d4f11f25c8a5eb2747e4e0855f02cfe412089f8513188e30380b47b756a67',
        'internal': ('285', '306', '271'), 'user': '308', 'count': '297',
        'replace': '288', 'integer': '294', 'join': '270', 'split': '287',
        'shown': '290', 'encoder': '303', 'sampler': '280', 'decode': '284', 'save': '291',
        'reference': '281',
    },
}
USER_LABEL = '套图创作要求'
USER_HELP = '按数量自动生成不同描述'


def _contract(workflow, source_hash=None):
    contract = CONTRACTS.get(workflow.get('id'))
    if not contract:
        return None
    actual = source_hash if source_hash is not None else workflow.get('source_hash', workflow.get('sourceHash'))
    if actual != contract['source_hash']:
        raise ValueError('写真套图来源已改变，需要重新审查内部文本。')
    return contract


def _count_targets(c):
    return [{'node': c['integer'], 'input': 'int_'}, {'node': c['split'], 'input': 'max_count'}]


def _same_targets(actual, expected):
    return isinstance(actual, list) and len(actual) == len(expected) and all(t in actual for t in expected)


def _check_spec(spec, c):
    if spec.get('outputs') != [c['save']]:
        raise ValueError('写真套图输出已改变，需要重新审查内部文本。')
    internal_ids = {nid + ':text' for nid in c['internal']}
    fields = spec.get('texts', [])
    for field in fields:
        targets = field.get('targets', [])
        protected = [target for target in targets if str(target.get('node')) in c['internal']]
        if field.get('id') in internal_ids:
            nid = field['id'].rsplit(':', 1)[0]
            if targets != [{'node': nid, 'input': 'text'}]:
                raise ValueError('写真套图内部文本绑定已改变。')
        elif protected:
            raise ValueError('创作描述不能绑定到写真套图内部模板。')
    users = [f for f in fields if f.get('id') == c['user'] + ':prompt']
    if len(users) != 1 or users[0].get('targets') != [{'node': c['user'], 'input': 'prompt'}]:
        raise ValueError('写真套图用户描述绑定已改变。')
    counts = [f for f in spec.get('controls', []) if f.get('id') == c['count'] + ':value']
    if len(counts) != 1 or not _same_targets(counts[0].get('targets'), _count_targets(c)):
        raise ValueError('写真套图数量绑定已改变。')
    for field in spec.get('controls', []):
        if any(str(target.get('node')) in c['internal'] for target in field.get('targets', [])):
            raise ValueError('创作参数不能绑定到写真套图内部模板。')
    for profile in spec.get('apiProfiles', []):
        if any(str(target.get('node')) in c['internal'] for target in profile.get('bindings', {}).values()):
            raise ValueError('API 配置不能绑定到写真套图内部模板。')
    return internal_ids


def portrait_text_input(spec, supplied):
    """Return a text-only contract and ignore only the six old template IDs.

    Older clients may still submit those IDs. They can never become overrides;
    every unrelated unknown text ID keeps the ordinary validation error.
    """
    c = _contract(spec)
    if c is None:
        return spec, supplied
    protected = _check_spec(spec, c)
    reviewed = deepcopy(spec)
    reviewed['texts'] = [f for f in reviewed['texts'] if f['id'] not in protected]
    if isinstance(supplied, dict):
        supplied = {key: value for key, value in supplied.items() if key not in protected}
    return reviewed, supplied


def _source_graph(graph):
    if isinstance(graph, dict):
        return graph
    from build_workflow_interfaces import widget_bindings
    api = {}
    for nid, node in graph.nodes.items():
        if nid not in graph.reachable or not graph.enabled(nid):
            continue
        inputs = {key: value[0] for key, value in widget_bindings(node).items()}
        for origin, output, slot in graph.ins[nid]:
            if slot < len(node.get('inputs', [])):
                inputs[node['inputs'][slot]['name']] = [origin, output]
        api[nid] = {'class_type': node['type'], 'inputs': inputs}
    return api


def _check_graph(graph, c, *, require_templates=False):
    def node(nid, typ, **inputs):
        value = graph.get(nid, {})
        if value.get('class_type') != typ or any(value.get('inputs', {}).get(k) != v for k, v in inputs.items()):
            raise ValueError('写真套图内部文本的真实执行分支已改变。')
        return value.get('inputs', {})

    for nid in c['internal']:
        value = node(nid, 'Text Multiline').get('text')
        if not isinstance(value, str) or require_templates and not value.strip():
            raise ValueError('写真套图内部模板缺失，需要恢复原编译模板。')
    node(c['replace'], 'CR Text Replace', text=[c['internal'][1], 0], find1='[条数]', replace1=[c['integer'], 0])
    integer = node(c['integer'], 'CR Integer To String')
    node(c['join'], 'JoinStringMulti', inputcount=3, string_1=[c['internal'][0], 0],
         string_2=[c['replace'], 0], string_3=[c['internal'][2], 0], delimiter=' ', return_list=False)
    user = node(c['user'], 'RH_LLMAPI_NODE', ref_image=[c['reference'], 0])
    split = node(c['split'], 'TextSplitByDelimiter', delimiter='|', start_index=0, skip_every=0)
    def count_value(value):
        if value == [c['count'], 0]:
            value = node(c['count'], 'ImpactInt').get('value')
        if type(value) is not int or not 1 <= value <= 1000:
            raise ValueError('套图数量需要是 1 到 1000 的整数。')
        return value
    if count_value(integer.get('int_')) != count_value(split.get('max_count')):
        raise ValueError('写真套图数量与描述拆分绑定不一致。')
    expected_role, expected_split = [c['join'], 0], [c['user'], 0]
    if c['user'] == '146' and 'yingxu_anime_batch_protocol' in graph[c['user']].get('_meta', {}):
        # The existing repair validates its complete recorded protocol later.
        # Recognize only its exact source consumer paths here, never invent one.
        expected_role = ['yingxu_review74_80_protocol_role', 0]
        expected_split = ['yingxu_review74_80_protocol_prompt', 0]
        node('yingxu_review74_80_protocol_role', 'JoinStringMulti', string_1=[c['join'], 0])
        node('yingxu_review74_80_protocol_prompt', 'easy blocker', **{'in': ['yingxu_review74_80_protocol_response', 0]})
        node('yingxu_review74_80_protocol_response', 'ShowText|pysssss', text=[c['user'], 0])
    if user.get('role') != expected_role or split.get('text') != expected_split:
        raise ValueError('写真套图内部模板的消费者已改变。')
    node(c['shown'], 'ShowText|pysssss', text=[c['split'], 0])
    node(c['encoder'], 'TextEncodeQwenImageEditPlusAdvance_lrzjason', prompt=[c['shown'], 0])
    node(c['sampler'], 'KSampler', positive=[c['encoder'], 0], latent_image=[c['encoder'], 1])
    node(c['decode'], 'VAEDecode', samples=[c['sampler'], 0])
    node(c['save'], 'SaveImage', images=[c['decode'], 0])


def restore_portrait_templates(spec, graph, template):
    """Restore only protected role text values on an exact current/saved graph.

    No user description, count, seed, API profile or material is restored. A
    drifted binding fails before any mutation, including on old job records.
    """
    c = _contract(spec)
    if c is None:
        return graph
    _check_spec(spec, c)
    _check_graph(graph, c)
    _check_graph(template, c, require_templates=True)
    for nid in c['internal']:
        graph[nid]['inputs']['text'] = template[nid]['inputs']['text']
    return graph


def reviewed_portrait_controls(workflow, controls, texts, *, graph=None,
                               source_hash=None, derived=None):
    """Fresh/curated UI annotation hook; keep real IDs, values and targets."""
    c = _contract(workflow, source_hash)
    if c is None:
        return controls, texts
    if graph is not None:
        _check_graph(_source_graph(graph), c, require_templates=True)
    elif not isinstance(derived, dict) or derived.get('sourceHash') != c['source_hash']:
        raise ValueError('缺少写真套图同源接口证明。')
    reviewed_controls, reviewed_texts = deepcopy(controls), deepcopy(texts)
    protected = {nid + ':text' for nid in c['internal']}
    reviewed_texts = [field for field in reviewed_texts if field['id'] not in protected]
    users = [f for f in reviewed_texts if f.get('id') == c['user'] + ':prompt']
    if len(users) != 1 or users[0].get('key') != 'prompt':
        raise ValueError('写真套图用户描述入口已改变。')
    users[0].update(label=USER_LABEL, help=USER_HELP)
    counts = [f for f in reviewed_controls if f.get('id') == c['count'] + ':value']
    if len(counts) != 1 or not _same_targets(counts[0].get('targets'), _count_targets(c)):
        raise ValueError('写真套图数量入口已改变。')
    counts[0].update(min=1, max=1000, step=1, integer=True)
    return reviewed_controls, reviewed_texts
