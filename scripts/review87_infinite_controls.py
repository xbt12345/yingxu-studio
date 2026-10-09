"""Pinned InfiniteTalk audio labels and per-speaker reference-region bindings.

The optional speaker masks are required by the currently installed multi-person
attention implementation. They are constructed on the real resized reference
canvas, in audio input order. Original source and API files are never changed.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = {
    'local-card-98': {'hash': 'f17d75d4d430df62b7a0c7e786292b7ff03b09dc386a9f28be131e49de12f421', 'outputs': ['26', '29'], 'audio': ['15', 0]},
    'local-card-99': {'hash': 'd3d16934b5df389e6b0a6b8f8f8411c7f88bba4b188a5b79906701fb33792969', 'outputs': ['334', '131'], 'audio': ['159', 0]},
    'local-card-100': {'hash': 'f8ab4453f2e456b4aa398908963f75fbdc9a76ffb881ca5576ce2c82dcf807be', 'outputs': ['334', '131'], 'audio': ['159', 0]},
    'local-card-101': {'hash': '7b4ca346e0bc88d03b7039cf96eb2e10b4d5d8271ba96525fdb422cfaa1801b5', 'outputs': ['131'], 'audio': ['194', 1]},
}
OUTPUT_LOOP_POLICIES = {
    wid: [{'controlId': contract['outputs'][0] + ':loop_count', 'node': sink,
           'format': 'video/h264-mp4', 'audio': contract['audio'], 'trimToAudio': False,
           'min': 0, 'max': 100, 'semantics': 'repeat-finished-audio-video',
           'playsFormula': 'loop_count+1', 'audioSemantics': 'repeat-complete-audio-video'}
          for sink in contract['outputs']] for wid, contract in CONTRACTS.items()
}
REFERENCE_GEOMETRY_POLICIES = {
    wid: {'kind': 'review87-infinite-reference-geometry', 'slotId': '358' if wid == 'local-card-100' else '284',
          'mediaKind': 'video' if wid == 'local-card-100' else 'image',
          'longSideControlId': '321:value', 'defaultLongSide': 832,
          'sourceMultiple': 8 if wid == 'local-card-100' else 1, 'layerMultiple': 16,
          'scaleNode': '307', 'sizeNode': '291', 'modelNode': '192',
          'widthLimits': {'min': 64, 'max': 2048, 'step': 8},
          'heightLimits': {'min': 64, 'max': 29048, 'step': 8}}
    for wid in ('local-card-99', 'local-card-100', 'local-card-101')
}
SPEAKER_CONTROL_ID = '194:speaker_regions'
SPEAKER_RECIPE = {
    'controlId': SPEAKER_CONTROL_ID, 'mediaSlotId': '284', 'speakerCount': 2,
    'coordinateSpace': 'normalized-reference', 'referenceImage': ['291', 0],
    'widthSource': ['291', 1], 'heightSource': ['291', 2],
    'target': {'node': '194', 'input': 'ref_target_masks', 'optional': True},
    'audioSlots': ['125', '357'], 'audioInputs': ['audio_1', 'audio_2'],
    'maskClasses': ['MathExpression|pysssss', 'SolidMask', 'MaskComposite', 'MaskBatchMulti'],
    'pixelMapping': 'floor(left/top), ceil(right/bottom), on actual resized reference',
    'allowPartialOverlap': True, 'required': True,
}


def _identity(wid, source_hash):
    if source_hash != CONTRACTS[wid]['hash']:
        raise ValueError('InfiniteTalk 工作流来源已改变，需要重新审查。')


def _inputs(graph, nid, cls):
    node = graph.get(nid, {})
    if node.get('class_type') != cls:
        raise ValueError('InfiniteTalk 执行节点已改变，需要重新审查。')
    return node.get('inputs', {})


def _source_guard(wid, cfg, graph):
    _identity(wid, cfg.get('sourceHash'))
    nodes = graph.nodes if hasattr(graph, 'nodes') else {str(n['id']): n for n in graph['nodes']}
    if any(nodes.get(nid, {}).get('type') != 'VHS_VideoCombine' for nid in CONTRACTS[wid]['outputs']):
        raise ValueError('数字人循环的原始输出节点已改变。')
    if wid == 'local-card-98':
        if nodes.get('15', {}).get('type') != 'AudioCropProcessUTK':
            raise ValueError('S2V 数字人原始音频链路已改变。')
        return
    for nid, cls in [('159', 'AudioCrop'), ('194', 'MultiTalkWav2VecEmbeds'),
                     ('192', 'WanVideoImageToVideoMultiTalk'), ('291', 'GetImageSizeAndCount')]:
        if nodes.get(nid, {}).get('type') != cls:
            raise ValueError('InfiniteTalk 音频或参考画面原始节点已改变。')
    if wid == 'local-card-101':
        for nid, cls in [('359', 'AudioCrop'), ('367', 'Float'), ('131', 'VHS_VideoCombine')]:
            if nodes.get(nid, {}).get('type') != cls:
                raise ValueError('双人 InfiniteTalk 原始绑定已改变。')


def speaker_field():
    return {
        'id': SPEAKER_CONTROL_ID, 'nodeId': '194', 'key': 'speaker_regions',
        'node': 'MultiTalkWav2VecEmbeds', 'kind': 'speaker_regions', 'type': 'text',
        'label': '音频对应的人物区域', 'value': '[]', 'linked': False, 'inactive': False,
        'mediaSlotId': '284', 'speakerCount': 2,
        'targets': [deepcopy(SPEAKER_RECIPE['target'])],
        'derived': {'operation': 'speaker-regions', 'targetId': '194:ref_target_masks'},
        'speakerRegionsRecipe': deepcopy(SPEAKER_RECIPE),
        'help': '按两路音频分别框选人物',
        'uiGroup': 'subject',
    }


def loop_field(wid):
    sinks = CONTRACTS[wid]['outputs']
    return {'id': sinks[0] + ':loop_count', 'nodeId': sinks[0], 'key': 'loop_count',
            'node': 'VHS_VideoCombine', 'label': '输出循环次数', 'kind': 'loop',
            'type': 'number', 'value': 0, 'min': 0, 'max': 100, 'step': 1, 'integer': True,
            'targets': [{'node': sink, 'input': 'loop_count'} for sink in sinks],
            'help': '0不循环；音画同步重复',
            'title': '填写1会额外重复1遍，总共播放2遍；本地重复成片，画面与声音一起循环。',
            'uiGroup': 'output'}


def _reference_guard(wid, template):
    policy = REFERENCE_GEOMETRY_POLICIES[wid]
    source = [policy['slotId'], 0]
    values = _inputs(template, '307', 'LayerUtility: ImageScaleByAspectRatio V2')
    expected = {'aspect_ratio': 'original', 'proportional_width': 1, 'proportional_height': 1,
                'fit': 'crop', 'round_to_multiple': '16', 'scale_to_side': 'longest',
                'scale_to_length': ['321', 0], 'image': source}
    if any(values.get(key) != value for key, value in expected.items()):
        raise ValueError('InfiniteTalk 原始比例与最长边转换路径已改变。')
    if _inputs(template, '291', 'GetImageSizeAndCount').get('image') != ['307', 0]:
        raise ValueError('InfiniteTalk 参考图宽高来源已改变。')
    dims = _inputs(template, '192', 'WanVideoImageToVideoMultiTalk')
    if dims.get('width') != ['291', 1] or dims.get('height') != ['291', 2]:
        raise ValueError('InfiniteTalk 模型宽高没有共享参考图尺寸。')
    if wid == 'local-card-100':
        loader = _inputs(template, '358', 'VHS_LoadVideo')
        if any(loader.get(key) != value for key, value in {'format': 'AnimateDiff', 'custom_width': 0, 'custom_height': 0}.items()):
            raise ValueError('InfiniteTalk 参考视频载入尺寸规则已改变。')


def _loop_guard(wid, template):
    for sink in CONTRACTS[wid]['outputs']:
        inputs = _inputs(template, sink, 'VHS_VideoCombine')
        if inputs.get('format') != 'video/h264-mp4' or inputs.get('loop_count') != 0 or inputs.get('audio') != CONTRACTS[wid]['audio']:
            raise ValueError('数字人原始循环或输出音轨绑定已改变。')


def reviewed_infinite_config(workflow, cfg, graph):
    wid = workflow['id'] if isinstance(workflow, dict) else workflow
    if wid not in CONTRACTS:
        return cfg
    _source_guard(wid, cfg, graph)
    cfg = deepcopy(cfg)
    for field in cfg.get('controls', []):
        if field['id'] in ('159:start_time', '359:start_time'):
            prefix = '音频 2 · ' if field['id'].startswith('359:') else '音频 1 · ' if wid == 'local-card-101' else ''
            field.update(label=prefix + '片段起点（分:秒）', kind='segment', timecodeInput='integer-seconds-or-mm:ss',
                         help='音频裁剪起始位置', title='从上传的驱动音频这一时刻开始裁剪。')
        elif field['id'] in ('159:end_time', '365:value'):
            prefix = '两路音频 · ' if wid == 'local-card-101' else ''
            field.update(label=prefix + '片段终点（分:秒）', kind='segment', timecodeInput='integer-seconds-or-mm:ss',
                         help='音频终点，须晚于起点', title='上传音频中的结束位置，需晚于起点；不是生成时长。')
        elif field['id'] == '321:value':
            field['title'] = '8与16为放大时每批处理的帧数，按边长自动切换；不是生成采样步数。'
            field['help'] = '8/16帧自动批处理' if wid != 'local-card-101' else '按参考图比例处理'
            field['max'] = min(field.get('max', 2048), 2048)
    field = loop_field(wid)
    existing = next((f for f in cfg['controls'] if f['id'] == field['id']), None)
    if existing is not None and (existing.get('targets') != field['targets'] or existing.get('value') != 0):
        raise ValueError('数字人已保存循环绑定与原始零默认不一致。')
    cfg['controls'] = [f for f in cfg['controls'] if f['id'] != field['id']] + [field]
    cfg['outputLoopPolicies'] = deepcopy(OUTPUT_LOOP_POLICIES[wid])
    if wid in REFERENCE_GEOMETRY_POLICIES:
        cfg['infiniteReferenceGeometry'] = deepcopy(REFERENCE_GEOMETRY_POLICIES[wid])
    if wid == 'local-card-101':
        cfg['controls'] = [f for f in cfg.get('controls', []) if f['id'] != SPEAKER_CONTROL_ID] + [speaker_field()]
        cfg['speakerRegionsRecipe'] = deepcopy(SPEAKER_RECIPE)
    return cfg


def _multi_guard(graph, allow_repaired_fps=False):
    if _inputs(graph, '192', 'WanVideoImageToVideoMultiTalk').get('start_image') != ['291', 0]:
        raise ValueError('双人参考图处理画面已改变。')
    dims = _inputs(graph, '192', 'WanVideoImageToVideoMultiTalk')
    if dims.get('width') != ['291', 1] or dims.get('height') != ['291', 2]:
        raise ValueError('双人人物区域不能确认实际处理宽高。')
    if _inputs(graph, '291', 'GetImageSizeAndCount').get('image') != ['307', 0]:
        raise ValueError('双人参考尺寸图像链路已改变。')
    if _inputs(graph, '307', 'LayerUtility: ImageScaleByAspectRatio V2').get('image') != ['284', 0]:
        raise ValueError('双人参考图的源图绑定已改变。')
    embeds = _inputs(graph, '194', 'MultiTalkWav2VecEmbeds')
    if any(embeds.get(k) != v for k, v in {'audio_1': ['170', 3], 'audio_2': ['358', 3], 'fps': ['367', 0], 'multi_audio_type': 'para'}.items()):
        raise ValueError('双人音频顺序、混合模式或帧率链路已改变。')
    if _inputs(graph, '367', 'Float').get('Number') != '25':
        raise ValueError('双人 InfiniteTalk 原始帧率值已改变。')
    if _inputs(graph, '368', 'CM_FloatToInt').get('a') != ['367', 0] or _inputs(graph, '354', 'CM_IntBinaryOperation').get('a') != ['368', 0]:
        raise ValueError('双人帧数换算与帧率没有共享原始常量。')
    output = _inputs(graph, '131', 'VHS_VideoCombine')
    permitted = [16, ['367', 0]] if allow_repaired_fps else [16]
    if output.get('frame_rate') not in permitted or output.get('audio') != ['194', 1]:
        raise ValueError('双人输出音轨或帧率绑定已改变。')


def _native_mask_contract(schemas):
    fields = {
        'MathExpression|pysssss': ({'expression': 'STRING', 'a': '*'}, 'INT'),
        'SolidMask': ({'value': 'FLOAT', 'width': 'INT', 'height': 'INT'}, 'MASK'),
        'MaskComposite': ({'destination': 'MASK', 'source': 'MASK', 'x': 'INT', 'y': 'INT'}, 'MASK'),
        'MaskBatchMulti': ({'inputcount': 'INT', 'mask_1': 'MASK', 'mask_2': 'MASK'}, 'MASK'),
    }
    for cls, (expected, output) in fields.items():
        schema = schemas.get(cls, {})
        inputs = schema.get('input', {})
        actual = {**inputs.get('required', {}), **inputs.get('optional', {})}
        if not schema.get('output') or schema['output'][0] != output or any(actual.get(key, [None])[0] != typ for key, typ in expected.items()):
            raise ValueError('双人人物区域所需原生节点缺失或接口已改变：' + cls)
        if cls == 'MaskComposite':
            operation = actual.get('operation', [None])
            choices = operation[0] if isinstance(operation[0], list) else operation[1].get('options', []) if len(operation) > 1 else []
            if 'add' not in choices:
                raise ValueError('双人人物区域掩膜合成操作不可用。')


def finalize_infinite_schema(spec, template, cfg=None, schemas=None):
    """Call after compiled controls/native intersection; template stays immutable."""
    wid = spec.get('id')
    if wid not in CONTRACTS:
        return spec
    _identity(wid, spec.get('source_hash'))
    spec = deepcopy(spec)
    _loop_guard(wid, template)
    loop = loop_field(wid)
    spec['controls'] = [f for f in spec.get('controls', []) if f['id'] != loop['id']] + [loop]
    spec['outputLoopPolicies'] = deepcopy(OUTPUT_LOOP_POLICIES[wid])
    if wid in REFERENCE_GEOMETRY_POLICIES:
        _reference_guard(wid, template)
        spec['infiniteReferenceGeometry'] = deepcopy(REFERENCE_GEOMETRY_POLICIES[wid])
        for field in spec.get('controls', []):
            if field['id'] == '321:value':
                field['max'] = min(field.get('max', 2048), 2048)
    if wid == 'local-card-101':
        _multi_guard(template)
        if schemas is not None:
            _native_mask_contract(schemas)
        field = speaker_field()
        field['transform'] = {'operation': 'speaker-regions'}
        spec['controls'] = [f for f in spec.get('controls', []) if f['id'] != SPEAKER_CONTROL_ID] + [field]
        spec['speakerRegionsRecipe'] = deepcopy(SPEAKER_RECIPE)
        spec['review87_infinite'] = {'fpsRepair': {'node': '131', 'input': 'frame_rate', 'from': 16, 'to': ['367', 0]},
                                    'failure': 'missing per-speaker ref_target_masks at MultiTalkWav2VecEmbeds194',
                                    'liveVerified': False}
        spec['excluded'] = [f for f in spec.get('excluded', []) if f.get('id') != SPEAKER_CONTROL_ID]
    return spec


def validate_speaker_regions(raw):
    if isinstance(raw, str):
        if len(raw) > 6000:
            raise ValueError('人物区域数据过长，请重新框选。')
        try:
            boxes = json.loads(raw)
        except (ValueError, TypeError):
            raise ValueError('人物区域格式不正确，请重新框选。') from None
    else:
        boxes = raw
    if not isinstance(boxes, list) or len(boxes) != 2:
        raise ValueError('请分别框选音频 1 和音频 2 对应的人物区域。')
    normalized = []
    for box in boxes:
        if not isinstance(box, dict) or set(box) != {'x', 'y', 'width', 'height'}:
            raise ValueError('人物区域需要完整矩形，请重新框选。')
        try:
            valid_numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box.values())
        except OverflowError:
            valid_numbers = False
        if not valid_numbers:
            raise ValueError('人物区域坐标需要有效数字。')
        x, y, width, height = (box[k] for k in ('x', 'y', 'width', 'height'))
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width <= x or y + height <= y or x + width > 1 + 1e-12 or y + height > 1 + 1e-12:
            raise ValueError('人物区域不能为空或超出参考图。')
        normalized.append({k: float(box[k]) for k in ('x', 'y', 'width', 'height')})
    if all(abs(normalized[0][key] - normalized[1][key]) <= 1e-12 for key in ('x', 'y', 'width', 'height')):
        raise ValueError('两路音频需要对应两个不同人物区域。')
    return normalized


def _runtime_node(graph, nid, cls, inputs):
    if nid in graph and graph[nid].get('_meta', {}).get('review87_speaker_regions') is not True:
        raise ValueError('人物区域执行节点名称冲突，请重新审查。')
    graph[nid] = {'class_type': cls, 'inputs': inputs,
                  '_meta': {'title': cls, 'review87_speaker_regions': True}}


def map_speaker_regions(boxes, geometry):
    """Map original-photo boxes through the verified center-cover crop once."""
    boxes = validate_speaker_regions(boxes)
    if not isinstance(geometry, dict) or geometry.get('workflowId') != 'local-card-101' or geometry.get('sourceHash') != CONTRACTS['local-card-101']['hash'] or geometry.get('pipeline') != REFERENCE_GEOMETRY_POLICIES['local-card-101']['kind']:
        raise ValueError('无法确认人物区域对应的真实处理画面，请重新导入参考图。')
    crop = geometry.get('crop')
    target = geometry.get('target')
    if not isinstance(crop, dict) or set(crop) != {'x', 'y', 'width', 'height'} or not isinstance(target, dict) or any(not isinstance(target.get(axis), int) or isinstance(target.get(axis), bool) or target[axis] < 64 for axis in ('width', 'height')):
        raise ValueError('人物区域的处理裁切与宽高数据不完整。')
    try:
        valid = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in crop.values())
    except OverflowError:
        valid = False
    if not valid or crop['x'] < 0 or crop['y'] < 0 or crop['width'] <= 0 or crop['height'] <= 0 or crop['x'] + crop['width'] > 1 + 1e-12 or crop['y'] + crop['height'] > 1 + 1e-12:
        raise ValueError('人物区域的处理裁切超出原始参考图。')
    mapped = []
    for box in boxes:
        left, top = max(box['x'], crop['x']), max(box['y'], crop['y'])
        right = min(box['x'] + box['width'], crop['x'] + crop['width'])
        bottom = min(box['y'] + box['height'], crop['y'] + crop['height'])
        if right <= left or bottom <= top:
            raise ValueError('人物区域完全落在处理裁切外，请重新框选或调整尺寸。')
        mapped.append({'x': max(0., (left - crop['x']) / crop['width']),
                       'y': max(0., (top - crop['y']) / crop['height']),
                       'width': (right - left) / crop['width'],
                       'height': (bottom - top) / crop['height']})
    return validate_speaker_regions(mapped)


def apply_infinite_speaker_regions(graph, spec, values, geometry=None):
    """Call after ordinary scalar binding. Mutates this job graph only.

    No client node IDs or pixel dimensions are used. Partial overlap is allowed;
    missing, empty, identical and out-of-image boxes are rejected before queueing.
    """
    if spec.get('id') != 'local-card-101':
        return graph
    _identity(spec['id'], spec.get('source_hash'))
    if spec.get('speakerRegionsRecipe') != SPEAKER_RECIPE:
        raise ValueError('双人人物区域执行契约已改变。')
    _multi_guard(graph, allow_repaired_fps=True)
    original_boxes = validate_speaker_regions(values.get(SPEAKER_CONTROL_ID, '[]') if isinstance(values, dict) else values)
    boxes = map_speaker_regions(original_boxes, geometry)
    width, height = ['291', 1], ['291', 2]
    _runtime_node(graph, 'review87_speaker_blank', 'SolidMask', {'value': 0., 'width': width, 'height': height})
    masks = []
    for index, box in enumerate(boxes, 1):
        stem = f'review87_speaker_{index}'
        for axis, source in (('x', width), ('y', height)):
            low = box[axis]
            high = min(1., low + box['width' if axis == 'x' else 'height'])
            _runtime_node(graph, stem + '_' + axis, 'MathExpression|pysssss',
                          {'expression': f'floor({low!r} * a)', 'a': source})
            _runtime_node(graph, stem + '_' + ('width' if axis == 'x' else 'height'), 'MathExpression|pysssss',
                          {'expression': f'ceil({high!r} * a) - floor({low!r} * a)', 'a': source})
        _runtime_node(graph, stem + '_solid', 'SolidMask',
                      {'value': 1., 'width': [stem + '_width', 0], 'height': [stem + '_height', 0]})
        _runtime_node(graph, stem + '_mask', 'MaskComposite',
                      {'destination': ['review87_speaker_blank', 0], 'source': [stem + '_solid', 0],
                       'x': [stem + '_x', 0], 'y': [stem + '_y', 0], 'operation': 'add'})
        masks.append([stem + '_mask', 0])
    _runtime_node(graph, 'review87_speakers', 'MaskBatchMulti',
                  {'inputcount': 2, 'mask_1': masks[0], 'mask_2': masks[1]})
    graph['194']['inputs']['ref_target_masks'] = ['review87_speakers', 0]
    graph['131']['inputs']['frame_rate'] = ['367', 0]
    graph['194'].setdefault('_meta', {})['review87_speaker_geometry'] = {
        'sourceHash': spec['source_hash'], 'originalBoxes': original_boxes,
        'crop': deepcopy(geometry['crop']), 'mappedBoxes': boxes, 'target': deepcopy(geometry['target'])}
    return graph


def derive_infinite_reference_geometry(spec, values, imagewidth, imageheight):
    """Exact source-to-model size checks, before upload or GPU queue submission."""
    wid = spec.get('id')
    if wid not in REFERENCE_GEOMETRY_POLICIES:
        raise ValueError('此工作流没有已审查的 InfiniteTalk 参考画面尺寸路径。')
    _identity(wid, spec.get('source_hash'))
    policy = REFERENCE_GEOMETRY_POLICIES[wid]
    if spec.get('infiniteReferenceGeometry') != policy:
        raise ValueError('InfiniteTalk 参考画面尺寸契约已改变。')
    for side in (imagewidth, imageheight):
        if not isinstance(side, int) or isinstance(side, bool) or side <= 0:
            raise ValueError('无法读取参考素材的实际宽高，请重新导入。')
    length = values.get(policy['longSideControlId'], policy['defaultLongSide'])
    try:
        valid = not isinstance(length, bool) and isinstance(length, (int, float)) and math.isfinite(length) and int(length) == length and 4 <= length <= 2048
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('InfiniteTalk 处理最长边需为4到2048之间的整数。')
    source_width, source_height = imagewidth, imageheight
    multiple = policy['sourceMultiple']
    if multiple > 1:
        source_width = int(source_width / multiple + .5) * multiple
        source_height = int(source_height / multiple + .5) * multiple
    if min(source_width, source_height) <= 0:
        raise ValueError('参考素材太小，无法形成有效的视频帧。')
    if source_width > source_height:
        width, height = int(length), int(length * source_height / source_width)
    else:
        width, height = int(length * source_width / source_height), int(length)
    multiple = policy['layerMultiple']
    width, height = math.ceil(width / multiple) * multiple, math.ceil(height / multiple) * multiple
    for axis, side in (('width', width), ('height', height)):
        limits = policy[axis + 'Limits']
        if not limits['min'] <= side <= limits['max'] or side % limits['step']:
            raise ValueError('参考图比例会使 InfiniteTalk 处理宽高超出模型范围；请裁剪素材或调整最长边，宽高至少64像素且宽度不超过2048。')
    def cover_crop(sw, sh, tw, th):
        factor = max(tw / sw, th / sh)
        cw, ch = tw / factor, th / factor
        return {'x': (sw - cw) / 2 / sw, 'y': (sh - ch) / 2 / sh, 'width': cw / sw, 'height': ch / sh}
    first = cover_crop(imagewidth, imageheight, source_width, source_height)
    second = cover_crop(source_width, source_height, width, height)
    crop = {'x': first['x'] + second['x'] * first['width'],
            'y': first['y'] + second['y'] * first['height'],
            'width': second['width'] * first['width'], 'height': second['height'] * first['height']}
    return {'width': width, 'height': height, 'workflowId': wid, 'sourceHash': spec['source_hash'],
            'pipeline': policy['kind'], 'original': {'width': imagewidth, 'height': imageheight}, 'crop': crop,
            'source': {'width': source_width, 'height': source_height},
            'target': {'width': width, 'height': height}, 'fit': 'center-cover'}


def verify_upscale_batch_semantics(graph):
    """Original 99/100 automatic VRAM batch heuristic; it is not diffusion steps."""
    expected = {
        '331': ('ImpactInt', {'value': 8}), '332': ('ImpactInt', {'value': 16}),
        '338': ('ImpactInt', {'value': 1000}),
        '339': ('easy compare', {'a': ['321', 0], 'b': ['338', 0], 'comparison': 'a >= b'}),
        '337': ('easy ifElse', {'boolean': ['339', 0], 'on_true': ['331', 0], 'on_false': ['332', 0]}),
    }
    for nid, (cls, inputs) in expected.items():
        if _inputs(graph, nid, cls) != inputs:
            raise ValueError('InfiniteTalk 原始放大批量自动配置已改变。')
    if _inputs(graph, '330', 'ImageUpscaleWithModelBatched').get('per_batch') != ['337', 0]:
        raise ValueError('InfiniteTalk 的 8 / 16 不是已审查放大批量。')
    return {'role': 'upscale frames per GPU batch', 'thresholdLongestEdge': 1000,
            'atOrAbove': 8, 'below': 16, 'samplingSteps': _inputs(graph, '128', 'WanVideoSampler')['steps']}
