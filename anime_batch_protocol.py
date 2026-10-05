"""Source-pinned response framing for card 80's real list-valued prompt split.

The original roles, user description, assets, models and seeds remain intact.
Only a final response-format contract is appended, and malformed batches are
blocked before text conditioning instead of silently becoming one image.
"""
import copy


SOURCE_HASH = '83d4166f18f6215116e365394b1d4a3393fcd069d8afd8b6c29ca0e1247c5a41'
STATE_KEY = 'yingxu_anime_batch_protocol'
PREFIX = 'yingxu_review74_80_protocol'
FORMAT_NODE = PREFIX + '_format'
ROLE_NODE = PREFIX + '_role'
RESPONSE_NODE = PREFIX + '_response'
VALID_NODE = PREFIX + '_valid'
PROMPT_NODE = PREFIX + '_prompt'


class AnimeBatchProtocolError(ValueError):
    pass


def batch_pattern(count):
    """An entire response of exactly count nonblank pipe-separated entries."""
    if type(count) is not int or not 1 <= count <= 1000:
        raise AnimeBatchProtocolError('套图数量必须为 1 到 1000 的整数。')
    # RegexMatch exposes regex_pattern, case_insensitive/multiline/dotall and
    # BOOLEAN in the saved installed registry. Explicit \A/\Z anchor the whole
    # string even if its implementation uses search instead of fullmatch.
    return (r'\A\s*(?!(?i:COMPILATION_ERROR:|ERROR:))[^\s|][^|]*'
            + r'(?:\|\s*[^\s|][^|]*){' + str(count - 1) + r'}\s*\Z')


def _format_contract(count):
    return (
        '以下仅规定机器读取的回复格式，不改变用户的创作目标、风格或参考要求。'
        f'只返回恰好 {count} 条非空、可直接用于图像生成的提示词。'
        '相邻提示词之间只使用一个 ASCII 竖线 |，不要以换行代替分隔符；'
        f'整个回复恰好包含 {count - 1} 个竖线。每条提示词内部不得使用竖线。'
        '不要编号、解释、Markdown、代码块、标题或 Next Scene: 前缀。'
        '不要在开头或结尾添加分隔符，也不要返回空段。'
    )


def _nodes(count):
    return {
        FORMAT_NODE: {'class_type': 'Text Multiline', 'inputs': {'text': _format_contract(count)}},
        ROLE_NODE: {'class_type': 'JoinStringMulti', 'inputs': {
            'inputcount': 2, 'string_1': ['83', 0], 'string_2': [FORMAT_NODE, 0],
            'delimiter': '\n\n', 'return_list': False}},
        RESPONSE_NODE: {'class_type': 'ShowText|pysssss', 'inputs': {'text': ['146', 0]}},
        VALID_NODE: {'class_type': 'RegexMatch', 'inputs': {
            'string': [RESPONSE_NODE, 0], 'regex_pattern': batch_pattern(count),
            'case_insensitive': False, 'multiline': False, 'dotall': False}},
        PROMPT_NODE: {'class_type': 'easy blocker', 'inputs': {
            'continue': [VALID_NODE, 0], 'in': [RESPONSE_NODE, 0]}},
    }


def _state(count):
    return {'id': 'review74-anime-batch-response-protocol', 'source_hash': SOURCE_HASH,
            'count': count, 'original_role': ['83', 0], 'original_split_text': ['146', 0]}


def repair_anime_batch_protocol(spec, graph):
    """Atomically adapt only the reviewed card 80; return safe evidence or None.

    Compiler templates and runtime graphs can bind a new legitimate count.
    Existing injected nodes must first match the previously recorded count;
    arbitrary protocol/consumer drift is never repaired speculatively.
    """
    if spec.get('id') != 'local-card-80':
        return None
    if spec.get('source_hash') != SOURCE_HASH or spec.get('outputs') != ['64']:
        raise AnimeBatchProtocolError('动漫套图来源或输出已改变，需要重新审查。')
    candidate = copy.deepcopy(graph)

    def node(nid, cls, **inputs):
        value = candidate.get(nid, {})
        if value.get('class_type') != cls or any(value.get('inputs', {}).get(k) != v for k, v in inputs.items()):
            raise AnimeBatchProtocolError(f'动漫套图协议未匹配节点 {nid} 的真实连线。')
        return value['inputs']

    node('91', 'Text Multiline')
    node('96', 'Text Multiline')
    node('85', 'CR Integer To String')
    node('86', 'CR Text Replace', text=['91', 0], find1='[条数]', replace1=['85', 0])
    original_role_inputs=node('83', 'JoinStringMulti', inputcount=3, string_1=['96', 0], string_2=['86', 0], string_3=['90', 0], delimiter=' ', return_list=False)
    node('90', 'Text Multiline')
    if set(original_role_inputs)!={'inputcount','string_1','string_2','string_3','delimiter','return_list'}:
        raise AnimeBatchProtocolError('动漫套图的原角色存在未审查的附加输入。')
    api = node('146', 'RH_LLMAPI_NODE', ref_image=['73', 0])
    split = node('87', 'TextSplitByDelimiter', delimiter='|', start_index=0, skip_every=0)
    node('92', 'ShowText|pysssss', text=['87', 0])
    node('45', 'TextEncodeQwenImageEditPlusAdvance_lrzjason', prompt=['92', 0])
    node('64', 'SaveImage', images=['60', 0])
    if not all(isinstance(candidate[nid]['inputs'].get('text'), str) for nid in ('90', '91', '96')):
        raise AnimeBatchProtocolError('动漫套图的原角色文本绑定已改变。')

    def count_value(value):
        if value == ['88', 0]:
            value = node('88', 'ImpactInt')['value']
        batch_pattern(value)
        return value

    count = count_value(split.get('max_count'))
    if count_value(candidate['85']['inputs'].get('int_')) != count:
        raise AnimeBatchProtocolError('套图数量的提示词与拆分绑定不一致。')

    recorded = candidate['146'].get('_meta', {}).get(STATE_KEY)
    if recorded is None:
        if api.get('role') != ['83', 0] or split.get('text') != ['146', 0] or any(nid in candidate for nid in _nodes(count)):
            raise AnimeBatchProtocolError('动漫套图存在未记录的格式接入漂移。')
    else:
        if not isinstance(recorded, dict):
            raise AnimeBatchProtocolError('动漫套图协议记录不完整。')
        previous_count = recorded.get('count')
        batch_pattern(previous_count)
        if recorded != _state(previous_count) or api.get('role') != [ROLE_NODE, 0] or split.get('text') != [PROMPT_NODE, 0]:
            raise AnimeBatchProtocolError('动漫套图协议来源或消费者已改变。')
        for nid, expected in _nodes(previous_count).items():
            node(nid, expected['class_type'], **expected['inputs'])
            if candidate[nid]['inputs'] != expected['inputs']:
                raise AnimeBatchProtocolError('动漫套图协议节点出现未审查的输入。')

    candidate.update(copy.deepcopy(_nodes(count)))
    candidate['146']['inputs']['role'] = [ROLE_NODE, 0]
    candidate['87']['inputs']['text'] = [PROMPT_NODE, 0]
    candidate['146'].setdefault('_meta', {})[STATE_KEY] = _state(count)
    graph.clear()
    graph.update(candidate)
    return {'operation': 'review74-anime-batch-response-protocol', 'source_hash': SOURCE_HASH,
            'count': count, 'delimiter': '|', 'api_response_node': RESPONSE_NODE,
            'validation_node': VALID_NODE, 'prompt_gate_node': PROMPT_NODE,
            'nodes': list(_nodes(count)), 'preserves_original_role_nodes': ['96', '91', '86', '83']}
