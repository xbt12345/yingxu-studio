"""Source-pinned SCAIL modes and optional pixel dimensions.

Zero is an authored-chain sentinel for BOTH dimensions, never a native SCAIL
width/height. Positive custom dimensions update preprocessing, reference resize
and model embeddings together. API templates remain unchanged.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = {
    'local-card-22': {
        'hash': 'a56c5ea4fe32da4688b1e60040a51f886320b71917c5a80ef4baf6cd5b731404',
        'scale': '602', 'reference': '89', 'embeds': '347', 'length': '116',
        'loader': '112',
        'indices': {'197:object_indices': '动作与参考图的人物', '579:object_indices': '参考图保留人物'},
        'mask': '197', 'driving_track': '79', 'reference_track': '81', 'reference_mask': '579',
    },
    'local-card-23': {
        'hash': 'e51c07d0d9c2b2c15c9e5a54c8bbc38420d2fc139582485ecadc0173d739d386',
        'scale': '560', 'reference': '519', 'embeds': '529', 'length': '571',
        'loader': '552',
        'indices': {'527:object_indices': '动作与参考图的人物'},
        'mask': '527', 'driving_track': '503', 'reference_track': '504',
        'mode_source': '575', 'mode_targets': ('527', '529'),
    },
}
DIMENSION_LIMITS = {'min': 0, 'nonzeroMin': 64, 'max': 8096, 'step': 32, 'integer': True}


def _incoming(graph, nid, name):
    node = graph.nodes.get(nid, {})
    index = next((i for i, port in enumerate(node.get('inputs', [])) if port.get('name') == name), None)
    found = [(src, slot) for src, slot, dst in graph.ins.get(nid, []) if dst == index]
    return found[0] if len(found) == 1 else None


def _endpoint(graph, incoming):
    seen = set()
    while incoming and incoming[0] not in seen:
        nid, index = incoming
        seen.add(nid)
        node = graph.nodes.get(nid, {})
        if node.get('type') not in ('SetNode', 'GetNode', 'Reroute'):
            return nid, index
        parents = graph.ins.get(nid, [])
        if len(parents) != 1:
            return None
        incoming = parents[0][0], parents[0][1]
    return None


def _prove_source(workflow_id, graph, source_hash):
    c = CONTRACTS[workflow_id]
    if source_hash != c['hash']:
        raise ValueError('SCAIL工作流源文件已改变，不能沿用尺寸与模式审查。')
    from build_workflow_interfaces import widget_bindings
    for nid, typ in ((c['scale'], 'LayerUtility: ImageScaleByAspectRatio V2'),
                     (c['reference'], 'ImageResizeKJv2'), (c['embeds'], 'WanAnimatePlus SCAIL_2 Embeds')):
        if graph.nodes.get(nid, {}).get('type') != typ or nid not in graph.reachable:
            raise ValueError('SCAIL尺寸链路节点或输出可达性已改变。')
    scale = widget_bindings(graph.nodes[c['scale']])
    expected = {'aspect_ratio': 'original', 'proportional_width': 1, 'proportional_height': 1,
                'round_to_multiple': '16', 'scale_to_side': 'longest', 'scale_to_length': 1024}
    if any(scale.get(key, (None,))[0] != value for key, value in expected.items()):
        raise ValueError('SCAIL原始尺寸比例或默认值已改变。')
    if _endpoint(graph, _incoming(graph, c['scale'], 'scale_to_length')) != (c['length'], 0):
        raise ValueError('SCAIL原始最长边控制已改变。')
    length = graph.nodes.get(c['length'], {})
    if length.get('type') != 'INTConstant' or widget_bindings(length).get('value', (None,))[0] != 1024:
        raise ValueError('SCAIL原始最长边默认值已改变。')
    for nid in (c['reference'], c['embeds']):
        for axis, slot in (('width', 3), ('height', 4)):
            if _endpoint(graph, _incoming(graph, nid, axis)) != (c['scale'], slot):
                raise ValueError('SCAIL宽高共享链路已改变。')
    for track, image in ((c['driving_track'], c['scale']), (c['reference_track'], c['reference'])):
        node = graph.nodes.get(track, {})
        if (node.get('type') != 'SAM3_VideoTrack' or
                widget_bindings(node).get('max_objects', (None,))[0] != 1 or
                _endpoint(graph, _incoming(graph, track, 'images')) != (image, 0)):
            raise ValueError('SCAIL人物检测对象或数量已改变。')
    if graph.nodes.get(c['mask'], {}).get('type') != 'SCAIL2ColoredMaskV2' or any(
            _endpoint(graph, _incoming(graph, c['mask'], name)) != (c[track], 0)
            for name, track in (('driving_track_data', 'driving_track'), ('ref_track_data', 'reference_track'))):
        raise ValueError('SCAIL人物选择没有同时绑定动作与参考图检测。')
    if c.get('reference_mask') and (graph.nodes.get(c['reference_mask'], {}).get('type') != 'SAM3_TrackToMask' or
            _endpoint(graph, _incoming(graph, c['reference_mask'], 'track_data')) != (c['reference_track'], 0)):
        raise ValueError('SCAIL参考图保留人物的检测绑定已改变。')
    if 'mode_source' in c:
        source = c['mode_source']
        if graph.nodes.get(source, {}).get('type') != 'PrimitiveBoolean' or widget_bindings(graph.nodes[source]).get('value', (None,))[0] is not False:
            raise ValueError('SCAIL模式的原始布尔值已改变。')
        for nid in c['mode_targets']:
            if _endpoint(graph, _incoming(graph, nid, 'replacement_mode')) != (source, 0):
                raise ValueError('SCAIL模式没有同时连接对象掩膜与生成条件。')


def _mode_control(c):
    return {'id': c['mode_source']+':value', 'nodeId': c['mode_source'], 'key': 'replacement_mode',
            'node': 'PrimitiveBoolean', 'kind': 'mode', 'type': 'checkbox', 'value': False,
            'label': '创作模式', 'targets': [{'node': c['mode_source'], 'input': 'value'}],
            'controlledTargets': [{'node': nid, 'input': 'replacement_mode'} for nid in c['mode_targets']],
            'options': [{'value': False, 'label': '动作迁移', 'help': '让参考人物跟随视频动作'},
                        {'value': True, 'label': '人物替换', 'help': '用参考人物替换视频中的人物'}]}


def _dimension_control(c, axis):
    return {'id': c['embeds']+':'+axis, 'nodeId': c['embeds'], 'key': axis,
            'node': 'WanAnimatePlus SCAIL_2 Embeds', 'kind': 'resolution', 'type': 'number',
            'value': 0, 'label': '输出'+('宽度' if axis == 'width' else '高度'), 'unit': 'px',
            **DIMENSION_LIMITS, 'dimensionGroup': 'video-size', 'dimensionAxis': axis,
            'targets': [{'node': c['embeds'], 'input': axis}],
            'help': '双0沿用；宽高须成对填',
            'displayHelp': '均填0沿用原配置；自定义需同时填两边，范围64–8096，须为32的倍数。',
            'title': '0不是模型的原生宽高，而是保留原尺寸链路。自定义尺寸会同步动作视频、参考图和生成条件。',
            'reviewedTransform': 'scail-paired-size',
            'nativeMinimum': 64, 'zeroMeaning': 'both-zero-preserves-authored-linked-dimensions'}


def reviewed_scail_controls(workflow, controls, *, graph=None, source_hash=None, derived=None):
    wid = workflow.get('id');c = CONTRACTS.get(wid)
    if not c:
        return controls
    if graph is not None:
        _prove_source(wid, graph, source_hash)
    elif source_hash != c['hash'] or (derived or {}).get('sourceHash') != source_hash:
        raise ValueError('SCAIL控件缺少同源审查证明。')
    new = [_dimension_control(c, axis) for axis in ('width', 'height')]
    if 'mode_source' in c:
        new.insert(0, _mode_control(c))
    if graph is None:
        for wanted in new:
            proofs = [f for f in (derived or {}).get('controls', []) if f.get('id') == wanted['id']]
            protected = ('key', 'kind', 'type', 'value', 'targets', 'controlledTargets', 'reviewedTransform', 'dimensionGroup', 'min', 'max', 'step', 'integer', 'nativeMinimum')
            if len(proofs) != 1 or any(proofs[0].get(key) != wanted.get(key) for key in protected):
                raise ValueError('SCAIL模式或可选宽高的同源证明已改变。')
    result = deepcopy(controls)
    identifiers = {f['id'] for f in new}
    if len([f for f in result if f['id'] in identifiers]) != len({f['id'] for f in result if f['id'] in identifiers}):
        raise ValueError('SCAIL新增控件出现重复。')
    result = [f for f in result if f['id'] not in identifiers]
    result.extend(new)
    for field in result:
        if field['id'] == c['length']+':value':
            field['help'] = '自定义宽高优先'
        if field['id'] in c['indices']:
            field.update(label=c['indices'][field['id']], help='选择检测到的人物',
                         displayHelp='编号从0开始；留空选全部检测人物', placeholder='自动选择；或填0',
                         title='当前最多跟踪1人；编号以检测结果为准，不按画面左右猜编号。')
    return result


def _prove_template(template, c):
    for nid, typ in ((c['scale'], 'LayerUtility: ImageScaleByAspectRatio V2'),
                     (c['reference'], 'ImageResizeKJv2'), (c['embeds'], 'WanAnimatePlus SCAIL_2 Embeds')):
        if template.get(nid, {}).get('class_type') != typ:
            raise ValueError('SCAIL执行模板的尺寸节点已改变。')
    scale = template[c['scale']]['inputs']
    if any(scale.get(key) != value for key, value in {'aspect_ratio': 'original', 'proportional_width': 1,
            'proportional_height': 1, 'round_to_multiple': '16', 'scale_to_side': 'longest',
            'scale_to_length': [c['length'], 0]}.items()):
        raise ValueError('SCAIL执行模板的原尺寸配置已改变。')
    if template.get(c['length'], {}).get('class_type') != 'INTConstant' or template[c['length']]['inputs'].get('value') != 1024:
        raise ValueError('SCAIL执行模板最长边的原默认值已改变。')
    for nid in (c['reference'], c['embeds']):
        if any(template[nid]['inputs'].get(axis) != [c['scale'], slot] for axis, slot in (('width', 3), ('height', 4))):
            raise ValueError('SCAIL执行模板的共享宽高链已改变。')
    if 'mode_source' in c:
        source = c['mode_source']
        if template.get(source, {}).get('class_type') != 'PrimitiveBoolean' or template[source]['inputs'].get('value') is not False:
            raise ValueError('SCAIL执行模板的原模式已改变。')
        if any(template[nid]['inputs'].get('replacement_mode') != [source, 0] for nid in c['mode_targets']):
            raise ValueError('SCAIL执行模板模式没有同时作用于两处。')


def _template(spec, supplied=None):
    if supplied is not None:
        return supplied
    from schema_adapters import template_path
    return json.loads(template_path(spec).read_text(encoding='utf-8'))


def finalize_scail_schema(spec, *, template=None):
    """Post-compiler injection preserves zero sentinel instead of native min=64.

    Call after native constraint intersection. Targets are real model ports; the
    runtime transform consumes the sentinel before any graph reaches the card.
    """
    wid = spec.get('id');c = CONTRACTS.get(wid)
    if not c:
        return spec
    if spec.get('source_hash') != c['hash']:
        raise ValueError('SCAIL编译控件的源指纹已改变。')
    _prove_template(_template(spec, template), c)
    result = deepcopy(spec)
    wanted = [_dimension_control(c, axis) for axis in ('width', 'height')]
    if 'mode_source' in c:
        wanted.insert(0, _mode_control(c))
    for field in wanted:
        existing = [f for f in result['controls'] if f['id'] == field['id']]
        if len(existing) > 1 or existing and existing[0].get('targets') != field['targets']:
            raise ValueError('SCAIL编译控件端口已改变。')
        result['controls'] = [f for f in result['controls'] if f['id'] != field['id']]
        result['controls'].append(field)
    result['scail_dimensions'] = {'width': c['embeds']+':width', 'height': c['embeds']+':height',
                                 'source_hash': c['hash'], 'min_nonzero': 64, 'max': 8096, 'multiple': 32}
    constraint = {'type': 'paired-size', 'width': c['embeds']+':width', 'height': c['embeds']+':height',
                  'min_nonzero': 64, 'max': 8096, 'multiple': 32}
    constraints = result.setdefault('constraints', [])
    matches = [item for item in constraints if item.get('type') == 'paired-size' and
               (item.get('width') == constraint['width'] or item.get('height') == constraint['height'])]
    if matches and (len(matches) != 1 or matches[0] != constraint):
        raise ValueError('SCAIL成对尺寸约束已改变。')
    if not matches:
        constraints.append(constraint)
    return result


def scail_dimension_values(spec, values):
    c = CONTRACTS.get(spec.get('id'))
    if not c:
        return None
    width, height = (values.get(c['embeds']+':'+axis, 0) for axis in ('width', 'height'))
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 8096 or not math.isfinite(v) or int(v) != v for v in (width, height)):
        raise ValueError('SCAIL宽高需要填写整数像素。')
    if width == 0 and height == 0:
        return 0, 0
    if any(v < 64 or v > 8096 or v % 32 for v in (width, height)):
        raise ValueError('SCAIL宽高需同时填写64–8096的32倍数；均填0才沿用原配置。')
    return int(width), int(height)


def derive_scail_processing_geometry(spec, values, sourceSize):
    """Read-only preflight of the actual SCAIL processing dimensions.

    sourceSize is the decoded video's {width,height}, never client metadata.
    A zero pair keeps VHS round8 -> the authored Layer ceil16 -> SCAIL's
    internal floor32. A Layer result such as1536x880 therefore stays legal and
    becomes1536x864; this helper does not change the original rounding/graph.
    Positive paired dimensions retain the existing64..8096/multiple32 contract.
    Call before upload/queue; only return facts, never bind these as new inputs.
    """
    wid = spec.get('id'); c = CONTRACTS.get(wid)
    if c is None:
        raise ValueError('此工作流没有已审查的SCAIL处理尺寸路径。')
    if spec.get('source_hash') != c['hash']:
        raise ValueError('SCAIL实际尺寸预检的源指纹已经变化。')
    expected = {'width': c['embeds']+':width', 'height': c['embeds']+':height',
                'source_hash': c['hash'], 'min_nonzero': 64, 'max': 8096, 'multiple': 32}
    if spec.get('scail_dimensions') != expected:
        raise ValueError('SCAIL实际尺寸预检缺少对应的已审查尺寸契约。')
    if not isinstance(values, dict):
        raise ValueError('SCAIL尺寸参数需要有效记录。')
    if not isinstance(sourceSize, dict):
        raise ValueError('无法读取动作参考视频的实际尺寸，请重新导入。')
    sw, sh = sourceSize.get('width'), sourceSize.get('height')
    if any(isinstance(side, bool) or not isinstance(side, int) or not 1 <= side <= 100000000 for side in (sw, sh)):
        raise ValueError('动作参考视频缺少有效宽高，请重新导入。')
    authored = _template(spec)
    _prove_template(authored, c)
    loader = authored.get(c['loader'], {})
    source_link = authored[c['scale']].get('inputs', {}).get('image')
    if (loader.get('class_type') != 'VHS_LoadVideo' or source_link != [c['loader'], 0] or
            any(loader.get('inputs', {}).get(key) != value for key, value in
                {'format':'AnimateDiff', 'custom_width':0, 'custom_height':0}.items())):
        raise ValueError('SCAIL原视频载入或尺寸前处理链路已经变化。')
    load_width, load_height = int(sw / 8 + .5) * 8, int(sh / 8 + .5) * 8
    if min(load_width, load_height) <= 0:
        raise ValueError('动作参考视频尺寸过小，无法形成有效帧。')
    width, height = scail_dimension_values(spec, values)
    custom = bool(width or height)
    if custom:
        layer_width, layer_height = width, height
    else:
        field = next((f for f in spec.get('controls', []) if f['id'] == c['length']+':value'), {})
        longest = values.get(c['length']+':value', field.get('value', 1024))
        if (isinstance(longest, bool) or not isinstance(longest, (int,float)) or
                not 4 <= longest <= 100000000 or not math.isfinite(longest) or int(longest) != longest):
            raise ValueError('SCAIL处理最长边需要有效整数。')
        if load_width >= load_height:
            layer_width, layer_height = int(longest), int(longest * load_height / load_width)
        else:
            layer_width, layer_height = int(longest * load_width / load_height), int(longest)
        layer_width = math.ceil(layer_width / 16) * 16
        layer_height = math.ceil(layer_height / 16) * 16
    target_width = (layer_width // 32) * 32
    target_height = (layer_height // 32) * 32
    if min(target_width, target_height) < 64:
        raise ValueError('动作参考视频的比例或最长边使SCAIL实际宽高小于64像素，请调整最长边或成对自定义宽高。')
    if max(target_width, target_height) > 8096:
        raise ValueError('SCAIL实际处理宽高不能超过8096像素，请减小最长边或成对自定义宽高。')
    return {'workflowId': wid, 'sourceHash': c['hash'], 'mediaSlotId': c['loader'], 'custom': custom,
            'original': {'width': sw, 'height': sh},
            'source': {'width': load_width, 'height': load_height},
            'layerTarget': {'width': layer_width, 'height': layer_height},
            'target': {'width': target_width, 'height': target_height},
            'sourceMultiple': 8, 'layerMultiple': 32 if custom else 16, 'nativeMultiple': 32,
            'defaultChainPreserved': not custom}


def apply_scail_output_size(graph, spec, values, *, template=None):
    """Call in schema_adapters.build AFTER scalar writes and BEFORE prune.

    On legacy drafts (fields absent), BOTH zero retains the original dynamic
    chain and any changed longest-edge value. No template or source is written.
    """
    c = CONTRACTS.get(spec.get('id'))
    if not c:
        return graph
    if spec.get('source_hash') != c['hash']:
        raise ValueError('SCAIL运行尺寸的源指纹已改变。')
    authored = _template(spec, template)
    _prove_template(authored, c)
    dimensions = scail_dimension_values(spec, values)
    width, height = dimensions
    for nid in (c['scale'], c['reference'], c['embeds']):
        if graph.get(nid, {}).get('class_type') != authored[nid]['class_type']:
            raise ValueError('SCAIL运行尺寸节点不匹配。')
    scale = graph[c['scale']]['inputs']
    source_keys = ('aspect_ratio', 'proportional_width', 'proportional_height', 'round_to_multiple', 'scale_to_side', 'scale_to_length')
    if width == height == 0:
        # Compiler maps the authored INTConstant control to the scale input.
        # Restore its source link while retaining the validated historical
        # longest-edge value in the actual constant, instead of resetting1024.
        bound_length = values.get(c['length']+':value')
        if bound_length is not None:
            if (isinstance(bound_length, bool) or not isinstance(bound_length, (int, float)) or
                    not math.isfinite(bound_length) or int(bound_length) != bound_length or
                    not 4 <= bound_length <= 100000000):
                raise ValueError('SCAIL原最长边需要有效整数。')
            if graph.get(c['length'], {}).get('class_type') != 'INTConstant':
                raise ValueError('SCAIL运行最长边节点不匹配。')
            graph[c['length']]['inputs']['value'] = int(bound_length)
        for key in source_keys:
            scale[key] = deepcopy(authored[c['scale']]['inputs'][key])
        for nid in (c['reference'], c['embeds']):
            for axis in ('width', 'height'):
                graph[nid]['inputs'][axis] = deepcopy(authored[nid]['inputs'][axis])
    else:
        scale.update(aspect_ratio='custom', proportional_width=width, proportional_height=height,
                     round_to_multiple='32', scale_to_side='longest', scale_to_length=max(width, height))
        for nid in (c['reference'], c['embeds']):
            graph[nid]['inputs'].update(width=width, height=height)
    return graph
