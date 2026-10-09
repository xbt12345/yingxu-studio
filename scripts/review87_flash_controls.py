"""Source-pinned video-upscaling controls, with native loader/output semantics.

These helpers never create execution nodes or modify saved API templates.
Custom dimensions configure VHS input frames; subsequent upscaling still applies.
Output loops repeat the finished video and soundtrack without model inference.
"""
from __future__ import annotations

import copy
import math


POLICIES = {
    'local-card-44': {'hash': '529adc28dd6788d55b7358f31f533a737c11da5b10deec4c81bea63dd18cc800',
                      'loader': '5099', 'resize': '5158:5120', 'sourceResize': 'sub0/5120',
                      'resizeSource': ['5099', 0], 'side': 'longest', 'multiple': 8,
                      'sinks': ['5069', '5135'], 'sizing': 'ltx-encoded-input-dimensions',
                      'intermediate': '5158:5026', 'roundNode': '5158:5085'},
    'local-card-45': {'hash': 'e9c061de44e449dcb59e76cd5f5cdb5ac39e488b3ae1a078f26e1449db6bc169',
                      'loader': '34', 'resize': '50:26', 'sourceResize': 'sub0/26',
                      'resizeSource': ['34', 0], 'side': 'longest', 'multiple': 8,
                      'sinks': ['37', '24'], 'sizing': 'ltx-encoded-input-dimensions',
                      'intermediate': '50:38', 'roundNode': '50:40'},
    'local-card-46': {'hash': '09721c7ecf536bcda5e07f038d4fb223de8db67c48e3e38e844f219bdf6f0e5c',
                      'loader': '5141', 'resize': None, 'multiple': 32,
                      'sinks': ['5104', '5131'], 'sizing': 'ltx-outpaint-size-with-margins',
                      'padNode': '5149', 'intermediate': '5167:5146', 'roundNode': '5167:5147',
                      'backgroundNode': '5167:5148', 'imageSizeNode': '5167:5114',
                      'latentNode': '5167:5109', 'padDefault': {'left': 324, 'right': 324, 'top': 0, 'bottom': 0}},
    'local-card-60': {'hash': '6efa2411b5e5f4211054ea8b51e4b2e53adc053a57c55c7c7d866f485caecb48',
                      'loader': '359', 'resize': '362', 'resizeSource': ['360', 0],
                      'side': 'longest', 'multiple': 32, 'sinks': ['347', '330'],
                      'sizing': 'h3-processing-size'},
    'local-card-118': {'hash': 'a66e533d5c4c2f2e3605dd3b26e32f1c63730a91c4837eed333091f40f14f1ec',
                      'loader': '13', 'resize': '26', 'resizeSource': ['13', 0],
                      'side': 'total_pixel(kilo pixel)', 'multiple': 8, 'sinks': ['24'],
                      'sizing': 'flash-input-times-scale', 'scaleId': '42:scale', 'defaultScale': 2},
    'local-card-119': {'hash': '110d7f6bab4e5a2a4d1880c6ece2db2ca92b3e3c10f301c8ce1dafe73de14f7f',
                      'loader': '507', 'resize': '499', 'resizeSource': ['507', 0],
                      'side': 'total_pixel(kilo pixel)', 'multiple': 8, 'sinks': ['502'],
                      'sizing': 'flash-input-times-scale', 'scaleId': '531:scale', 'defaultScale': 2},
    'local-card-120': {'hash': 'b8ab76162041b1893180996f3badbdc26eaa82be7fa63b913de4a7ebef2b65e2',
                      'loader': '18', 'resize': '9', 'resizeSource': ['18', 0],
                      'side': 'total_pixel(kilo pixel)', 'multiple': 16, 'sinks': ['3'],
                      'sizing': 'flash-input-times-scale', 'scaleId': '19:scale', 'defaultScale': 4},
    'local-card-121': {'hash': '9f7c6e6b8bfe7cf14ea33a3b763f02b0415ca155d8c5b531a8deaa40b3fa5882',
                      'loader': '15', 'resize': '20', 'resizeSource': ['15', 0],
                      'side': 'longest', 'multiple': 8, 'sinks': ['9'],
                      'sizing': 'upscale-model-controls-final-size'},
    'local-card-122': {'hash': '0036eac90c054211b9507171597c8486415ca4b2504d4cbf33c373e36e269f91',
                      'loader': '25', 'resize': None, 'multiple': 8, 'sinks': ['28'],
                      'sizing': 'seedvr-short-edge-controls-final-size'},
    'local-card-123': {'hash': '5c46f4ef6b61dfa42edead5da785672bc87253f4b20315f83fd2505f1d0dfdf1',
                      'loader': '18', 'resize': '13', 'resizeSource': ['18', 0],
                      'side': 'total_pixel(kilo pixel)', 'multiple': 8, 'sinks': ['16'],
                      'sizing': 'flash-input-times-scale', 'scaleId': '1:scale', 'defaultScale': 2},
}


def _identity(wid, source_hash):
    if source_hash != POLICIES[wid]['hash']:
        raise ValueError('视频放大工作流源码已经变化，请重新审查尺寸与循环规则。')


def _int(value, label, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + '需要填写有效整数。')
    if value != int(value) or not 0 <= value <= maximum:
        raise ValueError(label + '超出已确认的整数范围。')
    return int(value)


def flash_loop_metadata(wid):
    policy = POLICIES.get(wid)
    if policy is None:
        return []
    return [{'controlId': policy['sinks'][0] + ':loop_count', 'sink': sink,
             'format': 'video/h264-mp4', 'audioLink': [policy['loader'], 2],
             'trimToAudio': False, 'nativeInput': 'loop_count',
             'semantics': 'repeat-finished-audio-video', 'audioRepeats': True,
             'playsFormula': 'loop_count+1', 'audioSemantics': 'repeat-complete-audio-video',
             'nativeRange': {'min': 0, 'max': 100, 'step': 1}}
            for sink in policy['sinks']]


def reviewed_flash_controls(wid):
    policy = POLICIES.get(wid)
    if policy is None:
        return []
    result = []
    for axis in ('width', 'height'):
        result.append({'id': policy['loader'] + ':custom_' + axis, 'nodeId': policy['loader'],
                       'node': 'VHS_LoadVideo', 'key': 'custom_' + axis,
                       'label': '处理宽度' if axis == 'width' else '处理高度',
                       'kind': 'resolution', 'type': 'number', 'value': 0,
                       'min': 0, 'max': 8192, 'step': 1, 'integer': True,
                       'dimensionGroup': 'video-size', 'dimensionAxis': axis,
                       'help': '0沿用比例；放大前尺寸',
                       'title': ('输入帧尺寸，0沿用原比例；Flash结果再乘放大倍率。' if
                                 policy['sizing'] == 'flash-input-times-scale' else
                                 '原视频处理宽高；成片尺寸还会加上原扩展边距。' if
                                 policy['sizing'] == 'ltx-outpaint-size-with-margins' else
                                 '输入处理尺寸；最终尺寸仍由原工作流的模型或输出短边决定。'),
                       'targets': [{'node': policy['loader'], 'input': 'custom_' + axis}]})
    result.append({'id': policy['sinks'][0] + ':loop_count', 'nodeId': policy['sinks'][0],
                   'node': 'VHS_VideoCombine', 'key': 'loop_count', 'label': '输出循环次数',
                   'kind': 'loop', 'type': 'number', 'value': 0, 'min': 0, 'max': 100,
                   'step': 1, 'integer': True, 'uiGroup': 'output',
                   'help': '0不循环；音画同步重复',
                   'title': '填写1会额外重复1遍，总共播放2遍；完整重复音画，不重复生成。',
                   'targets': [{'node': sink, 'input': 'loop_count'} for sink in policy['sinks']]})
    return result


def _source_guard(wid, graph):
    policy = POLICIES[wid]
    if hasattr(graph, 'nodes'):
        nodes = graph.nodes
        classes = {str(k): v.get('type') for k, v in nodes.items()}
        reachable = graph.reachable
    elif isinstance(graph.get('nodes'), list):
        from scripts.build_workflow_interfaces import Graph
        return _source_guard(wid, Graph(graph))
    else:
        nodes = graph
        classes = {str(k): v.get('class_type') for k, v in nodes.items() if isinstance(v, dict)}
        reachable = set(nodes)
    required = {policy['loader']: 'VHS_LoadVideo',
                **{sink: 'VHS_VideoCombine' for sink in policy['sinks']}}
    if policy['resize']:
        required[policy.get('sourceResize', policy['resize'])] = 'LayerUtility: ImageScaleByAspectRatio V2'
    if policy.get('padNode'):
        required[policy['padNode']] = 'ImagePadKJ'
    if any(classes.get(key) != cls or key not in reachable for key, cls in required.items()):
        raise ValueError('视频放大工作流的真实输入或输出路径已经变化。')


def reviewed_flash_config(workflow, config, *, graph=None):
    wid = workflow if isinstance(workflow, str) else workflow['id']
    result = copy.deepcopy(config)
    if wid not in POLICIES:
        return result
    _identity(wid, result.get('sourceHash', result.get('source_hash')))
    if graph is not None:
        _source_guard(wid, graph)
    previous = {field['id']: field for field in result.setdefault('controls', [])}
    for field in reviewed_flash_controls(wid):
        existing = previous.get(field['id'])
        if existing:
            if existing.get('targets') != field['targets'] or existing.get('value') != field['value']:
                raise ValueError('视频放大尺寸或循环的已保存绑定已经变化。')
            existing.update(copy.deepcopy(field))
        else:
            result['controls'].append(copy.deepcopy(field))
    if wid == 'local-card-60' and '363:value' in previous:
        previous['363:value']['help'] = '自定义处理尺寸优先'
    long_id = {'local-card-44': '5154:value', 'local-card-45': '53:value'}.get(wid)
    if long_id in previous:
        previous[long_id]['help'] = '自定义处理尺寸优先'
    result['outputLoopPolicies'] = flash_loop_metadata(wid)
    result['videoSizePolicy'] = {'kind': 'review87-flash-vhs-dimensions',
                                'slotId': POLICIES[wid]['loader'],
                                'widthControlId': POLICIES[wid]['loader'] + ':custom_width',
                                'heightControlId': POLICIES[wid]['loader'] + ':custom_height',
                                'sourceMultiple': 8, 'layerMultiple': POLICIES[wid]['multiple'],
                                'rounding': 'floor-center-cover' if POLICIES[wid].get('padNode') else 'ceil-layer',
                                'customBypassesNativeResize': bool(POLICIES[wid]['resize']),
                                'sizing': POLICIES[wid]['sizing']}
    return result


def finalize_flash_schema(spec, *, template=None):
    """Run after native compiler mapping; do not relax registered bounds."""
    wid = spec.get('id')
    if wid not in POLICIES:
        return spec
    _identity(wid, spec.get('source_hash', spec.get('sourceHash')))
    if template is not None:
        _execution_guard(wid, template)
    result = copy.deepcopy(spec)
    result['outputLoopPolicies'] = flash_loop_metadata(wid)
    result['videoSizePolicy'] = reviewed_flash_config(wid, {'sourceHash': POLICIES[wid]['hash'], 'controls': []})['videoSizePolicy']
    expected = {f['id']: f for f in reviewed_flash_controls(wid)}
    for field in result.get('controls', []):
        if field['id'] in expected and field['targets'] != expected[field['id']]['targets']:
            raise ValueError('视频放大的原生尺寸或循环端口映射已经变化。')
    if not set(expected).issubset({field['id'] for field in result.get('controls', [])}):
        raise ValueError('视频放大的已审查尺寸或循环控件缺失。')
    return result


def _execution_guard(wid, graph):
    policy = POLICIES[wid]
    loader = graph.get(policy['loader'], {})
    if loader.get('class_type') != 'VHS_LoadVideo' or loader.get('inputs', {}).get('format') != 'AnimateDiff':
        raise ValueError('视频放大的原生视频加载节点已经变化。')
    if policy['resize']:
        node = graph.get(policy['resize'], {})
        inputs = node.get('inputs', {})
        if (node.get('class_type') != 'LayerUtility: ImageScaleByAspectRatio V2' or
                inputs.get('image') != policy['resizeSource'] or
                inputs.get('aspect_ratio') != 'original' or
                inputs.get('round_to_multiple') != str(policy['multiple']) or
                inputs.get('scale_to_side') not in (policy['side'], 'None')):
            raise ValueError('视频放大的后续尺寸转换路径已经变化。')
    if policy.get('intermediate'):
        intermediary = graph.get(policy['intermediate'], {})
        inputs = intermediary.get('inputs', {})
        source = policy['resize'] if policy['resize'] else policy['padNode']
        if (intermediary.get('class_type') != 'ResizeImageMaskNode' or
                inputs.get('input') != [source, 0] or inputs.get('resize_type') != 'scale by multiplier' or
                inputs.get('resize_type.multiplier') != 1):
            raise ValueError('LTX中间缩放会覆盖自定义尺寸，请重新审查。')
        round_node = graph.get(policy['roundNode'], {})
        inputs = round_node.get('inputs', {})
        if (round_node.get('class_type') != 'ResizeImageMaskNode' or
                inputs.get('input') != [policy['intermediate'], 0] or inputs.get('resize_type') != 'scale to multiple' or
                inputs.get('resize_type.multiple') != policy['multiple']):
            raise ValueError('LTX像素对齐规则已经变化，请重新审查。')
    if policy.get('padNode'):
        pad = graph.get(policy['padNode'], {})
        if pad.get('class_type') != 'ImagePadKJ' or pad.get('inputs', {}).get('image') != [policy['loader'], 0]:
            raise ValueError('LTX视频扩展的原始边距输入链路已经变化。')
        if 'target_width' in pad['inputs'] or 'target_height' in pad['inputs'] or pad['inputs'].get('extra_padding') != 0:
            raise ValueError('LTX视频扩展存在额外尺寸覆盖，请重新审查。')
        background = graph.get(policy['backgroundNode'], {})
        image_size = graph.get(policy['imageSizeNode'], {})
        latent = graph.get(policy['latentNode'], {})
        if (background.get('class_type') != 'ResizeImageMaskNode' or
                background.get('inputs', {}).get('resize_type') != 'match size' or
                background['inputs'].get('resize_type.match') != [policy['roundNode'], 0] or
                image_size.get('class_type') != 'GetImageSize' or
                image_size.get('inputs', {}).get('image') != [policy['roundNode'], 0] or
                latent.get('class_type') != 'EmptyLTXVLatentVideo' or
                any(latent.get('inputs', {}).get(axis) != [policy['imageSizeNode'], port]
                    for axis, port in [('width', 0), ('height', 1)])):
            raise ValueError('LTX视频扩展的背景与模型尺寸链路已经变化。')
    for sink in policy['sinks']:
        node = graph.get(sink, {})
        inputs = node.get('inputs', {})
        if (node.get('class_type') != 'VHS_VideoCombine' or inputs.get('format') != 'video/h264-mp4' or
                inputs.get('audio') != [policy['loader'], 2] or inputs.get('pingpong') is not False):
            raise ValueError('视频放大的输出循环或原音轨路径已经变化。')


def apply_flash_control_projection(graph, spec, values):
    """Call after scalar writes and reviewed repairs, before prune/queue."""
    wid = spec.get('id')
    if wid not in POLICIES:
        return graph
    _identity(wid, spec.get('source_hash', spec.get('sourceHash')))
    _execution_guard(wid, graph)
    policy = POLICIES[wid]
    result = copy.deepcopy(graph)
    inputs = result[policy['loader']]['inputs']
    width = _int(values.get(policy['loader'] + ':custom_width', inputs.get('custom_width', 0)), '处理宽度', 8192)
    height = _int(values.get(policy['loader'] + ':custom_height', inputs.get('custom_height', 0)), '处理高度', 8192)
    if any(0 < edge < 8 for edge in (width, height)):
        raise ValueError('非零处理尺寸至少需要8像素；0沿用原比例。')
    inputs.update(custom_width=width, custom_height=height)
    if (width or height) and policy['resize']:
        result[policy['resize']]['inputs']['scale_to_side'] = 'None'
    if width and height:
        derive_flash_processing_geometry(spec, values, width, height)
    loop_id = policy['sinks'][0] + ':loop_count'
    loop = _int(values.get(loop_id, result[policy['sinks'][0]]['inputs'].get('loop_count', 0)), '输出循环次数', 100)
    for sink in policy['sinks']:
        output = result[sink]['inputs']
        if loop and output.get('trim_to_audio', False) is not False:
            raise ValueError('按音频裁切会取消重复画面；请保持原音轨裁切关闭后再设置输出循环。')
        output['loop_count'] = loop
    return result


def derive_flash_processing_geometry(spec, values, source_width, source_height):
    """CPU preflight for custom VHS center-cover sizing, not final output size."""
    wid = spec.get('id')
    if wid not in POLICIES:
        raise ValueError('此工作流没有已审查的视频放大尺寸路径。')
    _identity(wid, spec.get('source_hash', spec.get('sourceHash')))
    policy = POLICIES[wid]
    sw, sh = _int(source_width, '原视频宽度', 100000000), _int(source_height, '原视频高度', 100000000)
    if not sw or not sh:
        raise ValueError('原视频缺少有效宽高。')
    width = _int(values.get(policy['loader'] + ':custom_width', 0), '处理宽度', 8192)
    height = _int(values.get(policy['loader'] + ':custom_height', 0), '处理高度', 8192)
    if not (width or height):
        return None  # Preserve the complete authored processing path/default.
    tw, th = ((width, height) if width and height else
              (width, sh * width / sw) if width else (sw * height / sh, height))
    load_width, load_height = int(tw / 8 + .5) * 8, int(th / 8 + .5) * 8
    if min(load_width, load_height) < 8:
        raise ValueError('自定义宽高与原比例组合过小，无法形成有效视频画面。')
    multiple = policy['multiple'] if policy['resize'] or policy.get('padNode') else 1
    if policy.get('padNode'):
        pad_values = {axis: _int(values.get(policy['padNode'] + ':' + axis, default), '扩展边距', 16384)
                      for axis, default in policy['padDefault'].items()}
        padded_width = load_width + pad_values['left'] + pad_values['right']
        padded_height = load_height + pad_values['top'] + pad_values['bottom']
    else:
        padded_width, padded_height = load_width, load_height
    if policy.get('padNode'):
        # Native ResizeImageMaskNode.scale_to_multiple_cover floors each edge
        # then center-cover crops; it does not use LayerStyle's ceil rule.
        processing_width, processing_height = padded_width // multiple * multiple, padded_height // multiple * multiple
        if not processing_width or not processing_height:
            processing_width, processing_height = padded_width, padded_height
    else:
        processing_width, processing_height = math.ceil(padded_width / multiple) * multiple, math.ceil(padded_height / multiple) * multiple
    if policy.get('padNode') and (min(processing_width, processing_height) < 64 or max(processing_width, processing_height) > 16384):
        raise ValueError('LTX扩展边距与处理宽高合计后，两边需要在64至16384像素之间。')
    if wid == 'local-card-60' and min(processing_width, processing_height) < 32:
        raise ValueError('H3视频处理尺寸至少需要32×32像素。')
    if policy['sizing'] == 'flash-input-times-scale':
        field = next((f for f in spec.get('controls', []) if f['id'] == policy['scaleId']), {})
        scale_factor = _int(values.get(policy['scaleId'], field.get('value', policy['defaultScale'])), '放大倍率', 4)
        # Both pinned FlashVSR sources clamp their target edge to >=128;
        # scaling an input edge below128 cannot supply the requested pixels.
        if scale_factor < 2 or min(processing_width, processing_height) * scale_factor < 128:
            raise ValueError('Flash处理尺寸过小；乘以放大倍率后，两边至少需要128像素。')
    scale = max(load_width / sw, load_height / sh)
    crop_width, crop_height = load_width / scale, load_height / scale
    return {'width': processing_width, 'height': processing_height,
            'sourceWidth': sw, 'sourceHeight': sh,
            'crop': {'x': (sw - crop_width) / 2, 'y': (sh - crop_height) / 2,
                     'width': crop_width, 'height': crop_height},
            'sizing': policy['sizing'], 'isFinalOutputSize': False}
