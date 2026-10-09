"""Source-guarded H3 mode choices and contiguous, owned reference binding.

Original API templates are never written. Coupled 8/4-step choices use the
authored boolean that switches both LoRA and sampler steps. Reference slots
keep their existing IDs; only each job's supplied images are packed in UI order.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HASHES = {
    'local-card-4': '204e1f8d6eccd1995721ee8f1281a57edd0ee3b86af2edef33ba64bd2afa3549',
    'local-card-6': '5e81e749d5f6221ea97d13091531c40f7a3aedfac8cd6b9a4499c97ca6fc8fda',
    'local-card-52': '5be77a076e8ec3988556a8259499661c6fca728e4a809c093cb6994b3f59ed1b',
    'local-card-53': 'b99da49633bd958e04b67e62e28ac185371e9754f0615349cefed7d8f56f85f1',
    'local-card-58': 'cd02a64bdf7ef7e28d91aad6731b7eea7e115a84504b4ad03dc0d2f742de0053',
    'local-card-62': 'e6ce51bd637da20f8fa3adfd8a8c0afcd7db4224245f0e634a8b124a9b24cafd',
    'local-card-63': '0455d4a25ad67f328b077c8f031c0b71f5e8d90f185af5e219f813072f2caf05',
    'local-card-64': '2aee949e9b20edabc0971eb08d106eb27cee0e11a45d7383afb1e00333530bdc',
    'local-card-65': '25809c9610340136a70db167c36b74101365808cd7ed38bef50a821951be9fdc',
    'local-card-71': '7537b76022fd8d9701c122f092bf5ea0becbedc35d0f7bdec6706b7041c7a824',
}
MODES = {
    # boolean, model switch, steps switch, 8-step constant, 4-step constant,
    # 8-step LoRA node, 4-step LoRA node, actual sampler
    'local-card-4': ('60', '58', '59', '42', '46', '40', '41', '47'),
    'local-card-6': ('60', '58', '59', '42', '46', '40', '41', '47'),
    'local-card-52': ('60', '58', '59', '42', '46', '40', '41', '47'),
    'local-card-58': ('25', '35', '36', '32', '33', '29', '22', '16'),
    'local-card-71': ('26', '39', '40', '35', '36', '30', '21', '28'),
}
REFERENCES = {
    'local-card-4': ('144', 9, ('65', '66', '70'),
                     {'65': ['80:74', 0], '66': ['87:84', 0], '70': ['94:91', 0]}, '160'),
    'local-card-52': ('144', 9, ('65', '66', '70'),
                      {'65': ['80:74', 0], '66': ['87:84', 0], '70': ['94:91', 0]}, '160'),
    'local-card-53': ('136', 3, ('137', '139'),
                      {'137': ['137', 0], '139': ['139', 0]}, None),
    'local-card-62': ('13', 2, ('14',), {'14': ['14', 0]}, None),
}
HIDDEN = {'local-card-63': '6:value', 'local-card-65': '145:value'}
SIX_STEP_PURPOSE = {'local-card-62': '7', 'local-card-64': '124'}
LORAS = {
    8: 'minimax/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',
    4: 'minimax/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors',
}
REVIEWED_OWNER_LORAS = {
    'local-card-4': 'minimax/加速/minimax_h3_fl2v_turbo_4step_v1.1_768p_comfyui_bf16.safetensors',
}


def _identity(wid, source_hash):
    if source_hash != HASHES.get(wid):
        raise ValueError('H3工作流来源已改变，需要重新审查。')


def _template(wid):
    from schema_adapters import manifest, template_path
    spec = manifest(wid)
    path = template_path(spec) if spec else ROOT / 'workflows/api' / (wid + '.api.json')
    return json.loads(path.read_text('utf-8-sig'))


def _node(graph, nid, typ):
    node = graph.get(nid, {})
    if node.get('class_type') != typ:
        raise ValueError('H3执行节点已改变，需要重新审查。')
    return node['inputs']


def _mode_guard(wid, execution):
    boolean, model_switch, step_switch, eight, four, lora8, lora4, sampler = MODES[wid]
    if _node(execution, boolean, 'easy boolean').get('value') is not False:
        raise ValueError('H3加速选择的原始默认值已改变。')
    model = _node(execution, model_switch, 'ComfySwitchNode')
    steps = _node(execution, step_switch, 'ComfySwitchNode')
    if model != {'switch': [boolean, 0], 'on_false': [lora8, 0], 'on_true': [lora4, 0]}:
        raise ValueError('H3加速模型与开关绑定已改变。')
    if steps != {'switch': [boolean, 0], 'on_false': [eight, 0], 'on_true': [four, 0]}:
        raise ValueError('H3加速步数与开关绑定已改变。')
    if _node(execution, eight, 'ImpactInt').get('value') != 8 or _node(execution, four, 'ImpactInt').get('value') != 4:
        raise ValueError('H3匹配的4/8步常量已改变。')
    for nid, count in ((lora8, 8), (lora4, 4)):
        params = _node(execution, nid, 'LoraLoaderModelOnly')
        permitted = {LORAS[count]}
        if count == 4 and wid in REVIEWED_OWNER_LORAS:
            permitted.add(REVIEWED_OWNER_LORAS[wid])
        if params.get('lora_name') not in permitted or params.get('strength_model') != 1:
            raise ValueError('H3加速LoRA与对应步数不匹配。')
    if _node(execution, sampler, 'MiniMaxH3DualClockSamplerT8').get('steps') != [step_switch, 0]:
        raise ValueError('H3采样器未接收已审查的步数选择。')
    current = execution[sampler]['inputs']['model'][0]
    visited = set()
    while current != model_switch and current not in visited:
        visited.add(current)
        node = execution.get(current, {})
        value = node.get('inputs', {}).get('model')
        if node.get('class_type') not in ('ModelPreviewOverrideKJ', 'ModelAttentionBackend', 'MiniMaxH3MemoryEfficientSageAttentionPatch', 'Lora Loader Stack (rgthree)') or not isinstance(value, list) or len(value) != 2:
            raise ValueError('H3最终采样模型未接收已审查的LoRA切换。')
        current = value[0]
    if current != model_switch:
        raise ValueError('H3加速模型路径存在不受支持的循环。')


def reviewed_h3_config(workflow, config, *, graph=None):
    """Apply to both fresh and curated UI configurations, without graph edits."""
    wid = workflow['id']
    if wid not in HASHES:
        return deepcopy(config)
    _identity(wid, config.get('sourceHash'))
    result = deepcopy(config)
    execution = _template(wid)
    if wid in MODES:
        _mode_guard(wid, execution)
        boolean = MODES[wid][0]
        if graph is not None:
            from scripts.build_workflow_interfaces import widget_bindings
            original = graph.nodes.get(boolean, {})
            if original.get('type') != 'easy boolean' or original.get('mode', 0) != 0 or boolean not in graph.reachable or widget_bindings(original).get('value', (None,))[0] is not False:
                raise ValueError('H3加速控件的原始布尔输入未匹配。')
        fid = boolean + ':value'
        field = {'id': fid, 'nodeId': boolean, 'node': 'easy boolean', 'key': 'value',
                 'kind': 'mode', 'type': 'checkbox', 'value': False, 'label': '加速步数',
                 'targets': [{'node': boolean, 'input': 'value'}],
                 'options': [{'value': False, 'label': '8 步', 'help': '原版配置'},
                             {'value': True, 'label': '4 步', 'help': '切换匹配的加速模型'}],
                 'help': '同时切换对应模型与步数'}
        existing = next((f for f in result['controls'] if f['id'] == fid), None)
        if existing:
            if existing.get('targets') != field['targets'] or existing.get('value') is not False:
                raise ValueError('H3加速选择的已保存默认值或绑定已改变。')
            existing.update(field)
        else:
            result['controls'].append(field)
    if wid in REFERENCES:
        consumer, cap, primary, links, batch = REFERENCES[wid]
        _node(execution, consumer, 'MiniMaxH3ReferenceToVideo')
        expected = list(primary) + [consumer + ':ref_image_' + str(i) for i in range(len(primary), cap)]
        actual = [f['id'] for f in result['media']]
        if actual != expected:
            raise ValueError('H3参考图的真实端口清单或顺序已改变。')
        if graph is not None:
            ports = [i['name'] for i in graph.nodes.get(consumer, {}).get('inputs', []) if re.fullmatch(r'ref_images\.ref_image_\d+', i['name'])]
            if len(ports) != cap:
                raise ValueError('H3原图的参考端口上限已改变。')
        for i, slot in enumerate(result['media']):
            slot.update(required=i == 0, optional=i != 0)
            if i != 0:
                slot['label'] = '参考图片 ' + str(i + 1)
        result['referencePolicy'] = {**result.get('referencePolicy', {}),
                                     'mode': 'graph-ports', 'presentation': 'progressive',
                                     'minImages': 1, 'maxImages': cap, 'imageSlots': cap,
                                     'help': '至少1张，按需添加'}
    if wid in HIDDEN:
        field = next((f for f in result['controls'] if f['id'] == HIDDEN[wid]), None)
        if field is None:
            raise ValueError('需要收起的H3最长边真实绑定缺失。')
        field['hidden'] = True
    if wid in SIX_STEP_PURPOSE:
        if _node(execution, SIX_STEP_PURPOSE[wid], 'BasicScheduler').get('steps') != 6:
            raise ValueError('H3原6步采样配置已改变。')
        result['purpose'] = '4步加速模型，原配置使用6步采样'
    return result


def bind_reviewed_h3_assets(graph, spec, records):
    """Optional hook at bind_assets entry; True means this group was fully bound.

    The hook replaces only this reviewed group of image bindings. It packs
    original LoadImage/preprocessing links and supplied optional loaders in
    schema slot order, sharing that same order with the authored prompt helper.
    Other workflows return False and follow the unchanged generic binder.
    """
    wid = spec.get('id')
    if wid not in REFERENCES:
        return False
    _identity(wid, spec.get('source_hash'))
    consumer, cap, primary, links, batch = REFERENCES[wid]
    fields = spec.get('media', [])
    expected = list(primary) + [consumer + ':ref_image_' + str(i) for i in range(len(primary), cap)]
    if [f['id'] for f in fields] != expected or set(records) - set(expected):
        raise ValueError('H3参考图清单已改变或含有未支持的素材。')
    if len(records) > cap or not records.get(primary[0]):
        raise ValueError('请先添加参考图片1。')
    model = _node(graph, consumer, 'MiniMaxH3ReferenceToVideo')
    supplied_links = []
    for field in fields:
        fid = field['id']; record = records.get(fid)
        if record is None:
            continue
        if not isinstance(record, dict) or record.get('kind') != 'image' or not isinstance(record.get('remote'), str) or not record['remote']:
            raise ValueError('H3参考图片的文件类型或运行端素材记录不匹配。')
        if fid in primary:
            if field.get('targets') != [{'node': fid, 'input': 'image'}]:
                raise ValueError('H3原参考图加载绑定已改变。')
            _node(graph, fid, 'LoadImage')['image'] = record['remote']
            reference = links[fid]
            if reference[0] not in graph:
                raise ValueError('H3原参考图预处理分支缺失。')
            supplied_links.append(deepcopy(reference))
        else:
            targets = field.get('targets', [])
            port = 'ref_images.ref_image_' + fid.rsplit('_', 1)[1]
            if len(targets) != 1 or targets[0].get('node') != consumer or targets[0].get('input') != port or targets[0].get('valueMode') != 'loader' or not targets[0].get('optional'):
                raise ValueError('H3新增参考图的真实可选端口绑定已改变。')
            loader = 'yingxu-upload-' + re.sub(r'[^a-zA-Z0-9_-]', '_', fid)
            graph[loader] = {'class_type': 'LoadImage', 'inputs': {'image': record['remote']}}
            supplied_links.append([loader, 0])
    for key in list(model):
        if re.fullmatch(r'ref_images\.ref_image_\d+', key):
            del model[key]
    for i, link in enumerate(supplied_links):
        model['ref_images.ref_image_' + str(i)] = link
    if batch is not None:
        inputs = _node(graph, batch, 'ImpactMakeImageBatch')
        if any(not re.fullmatch(r'image\d+', key) for key in inputs):
            raise ValueError('H3提示词图片批次存在未审查输入。')
        inputs.clear()
        inputs.update({'image' + str(i + 1): deepcopy(link) for i, link in enumerate(supplied_links)})
    return True
