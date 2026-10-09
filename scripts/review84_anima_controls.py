"""Expose the authored Anima sampling branches without flattening their switch.

The saved Turbo decision selects a LoRA, a step primitive and a CFG primitive
together. Keep that graph intact: the form edits the existing Boolean and the
two existing step primitives; only the active branch's step field is visible.
No sampler default, original graph, or output node is changed here.
"""
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TURBO_LORA = 'Anima/anima-turbo-lora-v0.2.safetensors'
CONTRACTS = {
    'local-card-86': {
        'hash': '922411c5bbd74ab1f0e2b0eae6c4bed3969e5f0726a48b4e1f47889cf92c6d97',
        'parent': '88', 'toggle': '705', 'standard': 30,
        'definition': '147b517e-5ea6-4fba-84f7-46851be6e4ce',
    },
    'local-card-87': {
        'hash': 'e29eba1112190b34dd5f850f07bf6a08f65000b49c58d550168b482f71aff0cf',
        'parent': '699', 'toggle': '711', 'standard': 40,
        'definition': '7d03d70e-2957-4296-99bd-9e0552c4cac8',
    },
    'local-card-88': {
        'hash': 'decef080f7c2764939b6520e8663dc18e3b166a32e7bdd9d2c84f6f71f32933c',
        'parent': '88', 'toggle': '693', 'standard': 40,
        'definition': '147b517e-5ea6-4fba-84f7-46851be6e4ce',
    },
}


def _fields(contract):
    toggle = contract['toggle'] + ':value'
    result = [{
        'id': toggle, 'nodeId': contract['toggle'], 'key': 'turbo_enabled',
        'node': 'easy boolean', 'kind': 'toggle', 'type': 'checkbox',
        'label': 'Turbo 加速', 'value': True,
        'targets': [{'node': contract['toggle'], 'input': 'value'}],
        'help': '少量步数，缩短生成时间',
        'accelerationTechnology': 'Anima Turbo LoRA v0.2',
    }]
    for nid, key, default, enabled, presets in (
        ('sub0/107', 'standard_steps', contract['standard'], False, [20, 30, 40]),
        ('sub0/108', 'turbo_steps', 8, True, [4, 8, 12]),
    ):
        result.append({
            'id': nid + ':value', 'nodeId': nid, 'key': key,
            'node': 'PrimitiveInt', 'kind': 'steps', 'type': 'number',
            'label': '生成步数', 'value': default,
            'min': 1, 'max': 10000, 'step': 1, 'integer': True,
            'targets': [{'node': nid, 'input': 'value'}],
            'help': '更多步数，通常更细致更慢', 'presets': presets,
            'visibleWhen': {'controlId': toggle, 'equals': enabled, 'defaultValue': True},
            'constraintSources': [{'node': 'sub0/106', 'input': 'steps'}],
        })
    return result


def _edge(graph, source, destination, port, *, output=0):
    inputs = graph.nodes.get(destination, {}).get('inputs', [])
    index = next((i for i, item in enumerate(inputs) if item.get('name') == port), None)
    if (index is None or source not in graph.reachable or destination not in graph.reachable
            or (destination, index, output) not in graph.out.get(source, [])):
        raise ValueError('Anima 步数与加速分支的有效连线已改变。')


def _check_graph(graph, contract):
    from build_workflow_interfaces import widget_bindings
    parent = contract['parent']
    expected_types = {
        contract['toggle']: 'easy boolean', parent: contract['definition'],
        'sub0/106': 'KSampler', 'sub0/107': 'PrimitiveInt',
        'sub0/108': 'PrimitiveInt', 'sub0/109': 'LoraLoaderModelOnly',
        'sub0/110': 'ComfySwitchNode', 'sub0/111': 'ComfySwitchNode',
        'sub0/112': 'PrimitiveFloat', 'sub0/113': 'ComfySwitchNode',
        'sub0/114': 'PrimitiveFloat', 'sub0/115': 'PrimitiveBoolean',
        'sub0/87': 'AnimaLLLiteApply',
    }
    for nid, kind in expected_types.items():
        node = graph.nodes.get(nid, {})
        if node.get('type') != kind or nid not in graph.reachable or node.get('mode', 0) != 0:
            raise ValueError('Anima 步数与加速分支的节点类型或启用状态已改变。')
    for nid, key, default in (
        (contract['toggle'], 'value', True),
        ('sub0/107', 'value', contract['standard']), ('sub0/108', 'value', 8),
        ('sub0/112', 'value', 4), ('sub0/114', 'value', 1),
        ('sub0/109', 'strength_model', 1), (parent, 'lora_name', TURBO_LORA),
    ):
        actual = widget_bindings(graph.nodes[nid]).get(key, (None,))[0]
        if type(actual) is not type(default) or actual != default:
            raise ValueError('Anima 步数、加速默认值或真实 LoRA 已改变。')
    for field in _fields(contract):
        if not graph.editable(field['nodeId'], 'value'):
            raise ValueError('Anima 可编辑标量源已经变成链接输入。')
    for source, destination, port in (
        (contract['toggle'], parent, 'value'), (parent, 'sub0/115', 'value'),
        ('sub0/115', 'sub0/110', 'switch'), ('sub0/115', 'sub0/111', 'switch'),
        ('sub0/115', 'sub0/113', 'switch'),
        ('sub0/87', 'sub0/109', 'model'),
        ('sub0/87', 'sub0/110', 'on_false'), ('sub0/109', 'sub0/110', 'on_true'),
        ('sub0/107', 'sub0/111', 'on_false'), ('sub0/108', 'sub0/111', 'on_true'),
        ('sub0/112', 'sub0/113', 'on_false'), ('sub0/114', 'sub0/113', 'on_true'),
        ('sub0/110', 'sub0/106', 'model'), ('sub0/111', 'sub0/106', 'steps'),
        ('sub0/113', 'sub0/106', 'cfg'),
    ):
        _edge(graph, source, destination, port, output=13 if source == parent else 0)
    info = json.loads((ROOT / 'private/research/card-20261004/object_info.json').read_text('utf-8'))
    native = info['KSampler']['input']['required']['steps']
    if (native[0], native[1].get('min'), native[1].get('max')) != ('INT', 1, 10000):
        raise ValueError('Anima 生成步数的已安装采样节点范围已改变。')
    if info['easy boolean']['input']['required']['value'][0] != 'BOOLEAN':
        raise ValueError('Anima 加速开关的已安装节点类型已改变。')


def reviewed_anima_controls(workflow, controls, *, graph=None, source_hash=None, derived=None):
    contract = CONTRACTS.get(workflow.get('id'))
    if contract is None:
        return controls
    if source_hash != contract['hash']:
        raise ValueError('Anima 步数与加速的原始来源已改变，需要重新审查。')
    expected = _fields(contract)
    if graph is not None:
        _check_graph(graph, contract)
    else:
        if (derived or {}).get('sourceHash') != source_hash:
            raise ValueError('Anima 步数与加速缺少同源证明。')
        for field in expected:
            matches = [item for item in derived.get('controls', []) if item.get('id') == field['id']]
            if len(matches) != 1 or any(matches[0].get(key) != value for key, value in field.items()):
                raise ValueError('Anima 步数与加速的源参数证明未匹配。')
    ids = {field['id'] for field in expected}
    result = [deepcopy(field) for field in controls if field.get('id') not in ids]
    # Put decisions before the existing seed; the original field keeps its data.
    position = next((index for index, field in enumerate(result) if field.get('kind') == 'seed'), len(result))
    result[position:position] = expected
    return result
