"""Expose authored dimensions that actually determine generated output sizes.

Reference-only resizing and sampler internals remain untouched. LayerUtility's
website range is a reviewed cost subset, not its native maximum. MP values keep
their native unit and step; no guessed pixel-base conversion is performed.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

LAYER = 'LayerUtility: ImageScaleByAspectRatio V2'
MP = 'ImageScaleToTotalPixels'
UPSCALE = 'LatentUpscaleBy'


def _field(nid, key, native_key, typ, default, label, *, side=None, multiple=None, ui_group=None):
    if typ == LAYER:
        minimum, maximum, step = 512, 4096, 1
        unit = '千像素' if side == 'total_pixel(kilo pixel)' else 'px'
        options = [1024, 1536, 2048]
    elif typ == MP:
        minimum, maximum, step, unit, options = .01, 16, .01, 'MP', [.5, 1, 1.5, 2, 4]
    else:
        minimum, maximum, step, unit, options = .01, 8, .01, '倍', None
    result = {'id': nid + ':' + native_key, 'nodeId': nid, 'key': key,
              'node': typ, 'kind': 'resolution' if typ != UPSCALE else 'number',
              'type': 'number', 'label': label, 'value': default, 'min': minimum,
              'max': maximum, 'step': step, 'unit': unit,
              'targets': [{'node': nid, 'input': native_key}],
              'help': '沿用原比例，越大越慢' if typ != UPSCALE else '越大，放大重绘越慢'}
    if typ == LAYER:
        result['integer'] = True
    if ui_group is not None:
        result['uiGroup']=ui_group
    if options:
        result.update(customRange={'min': minimum, 'max': maximum, 'step': step}, options=options)
    return {'field': result, 'side': side, 'multiple': multiple}


CONTRACTS = {
 'local-card-5': {'hash': '4c37ca0b7de7de9754bb40eaa749f567df99a5a2eafada1f2a72971aea7e7c9f',
  'fields': [_field('415', 'output_long_side', 'scale_to_length', LAYER, 1024, '输出最长边', side='longest', multiple='8', ui_group='output')],
  'edges': [('415', 3, '410', 'width', 'BerniniConditioning'), ('415', 4, '410', 'height', 'BerniniConditioning'), ('410', 2, '386', 'latent_image', 'KSamplerAdvanced'), ('386', 0, '407', 'latent_image', 'KSamplerAdvanced'), ('407', 0, '392', 'samples', 'VAEDecode'), ('392', 0, '393', 'images', 'GetImageRangeFromBatch'), ('393', 0, '395', 'images', 'VHS_VideoCombine')]},
 'local-card-41': {'hash': 'cbc23fea743b2442ce7785a8871395c1a42ff44f722210f1df4622aaf2dadcdf',
  'fields': [_field('434', 'output_long_side', 'scale_to_length', LAYER, 1024, '输出最长边', side='longest', multiple='32')],
  'edges': [('434', 0, '111', 'image', 'GetImageSize'), ('111', 0, '387', 'width', 'BerniniConditioning'), ('111', 1, '387', 'height', 'BerniniConditioning'), ('387', 2, '384', 'latent_image', 'SamplerCustom'), ('384', 0, '386', 'latent_image', 'SamplerCustom'), ('386', 0, '382', 'samples', 'VAEDecode'), ('382', 0, '443', 'images', 'VHS_VideoCombine')]},
 'local-card-59': {'hash': 'e2fdba9cffa3a634266ce66d0c0c65b47f00676a5c36b24a0d88c362b9e92665',
  'fields': [_field('272', 'output_long_side', 'scale_to_length', LAYER, 1024, '输出最长边', side='longest', multiple='32')],
  'edges': [('272', 0, '271', 'image', 'GetImageSizeAndCount'), ('271', 1, '219', 'width', 'MiniMaxH3ReferenceToVideo'), ('271', 2, '219', 'height', 'MiniMaxH3ReferenceToVideo'), ('219', 1, '215', 'av_latent', 'MiniMaxH3DualClockSamplerT8'), ('219', 1, '206', 'latent_image', 'SamplerCustomAdvanced'), ('215', 1, '206', 'sampler', 'SamplerCustomAdvanced'), ('206', 0, '194', 'av_latent', 'MiniMaxH3AVDecodeT8'), ('194', 0, '190', 'images', 'CreateVideo'), ('190', 0, '191', 'video', 'SaveVideo')]},
 'local-card-12': {'hash': 'f92ee25a601ac4c605a55a7fbf1d4d94a07171b2435aedf58a83d315004cadbe',
  'fields': [_field('142', 'output_pixels', 'scale_to_length', LAYER, 1324, '输出总像素', side='total_pixel(kilo pixel)', multiple='64')],
  'edges': [('142', 3, '83', 'width', 'EmptyFlux2LatentImage'), ('142', 4, '83', 'height', 'EmptyFlux2LatentImage'), ('142', 3, '172', 'width', 'EmptyFlux2LatentImage'), ('142', 4, '172', 'height', 'EmptyFlux2LatentImage'), ('142', 3, '181', 'width', 'EmptyFlux2LatentImage'), ('142', 4, '181', 'height', 'EmptyFlux2LatentImage'), ('83', 0, '95', 'latent_image', 'KSampler'), ('172', 0, '168', 'latent_image', 'KSampler'), ('181', 0, '177', 'latent_image', 'KSampler'), ('95', 0, '17', 'samples', 'VAEDecode'), ('168', 0, '174', 'samples', 'VAEDecode'), ('177', 0, '183', 'samples', 'VAEDecode'), ('17', 0, '62', 'images', 'SaveImage'), ('174', 0, '170', 'images', 'SaveImage'), ('183', 0, '179', 'images', 'SaveImage')]},
 'local-card-16': {'hash': '488bc1847380fc0fdda205de3e42b0c51286d5075c526ed5db471ef205b71947',
  'fields': [_field('38', 'output_long_side', 'scale_to_length', LAYER, 1324, '输出最长边', side='longest', multiple='64')],
  'edges': [('38', 3, '34', 'width', 'EmptyFlux2LatentImage'), ('38', 4, '34', 'height', 'EmptyFlux2LatentImage'), ('34', 0, '17', 'latent_image', 'KSampler'), ('17', 0, '19', 'samples', 'VAEDecode'), ('19', 0, '26', 'images', 'SaveImage')]},
 'local-card-17': {'hash': '6525111eec21bdb4d034bfba9ff4abcc5c5accf70a1fcdffe6808bad5ffb4337',
  'fields': [_field('106', 'model1_megapixels', 'megapixels', MP, 1, '模型 1 输出总像素'), _field('123', 'model2_megapixels', 'megapixels', MP, 1, '模型 2 输出总像素')],
  'edges': [('106', 0, '111', 'image', 'GetImageSize'), ('111', 0, '105', 'width', 'EmptyFlux2LatentImage'), ('111', 1, '105', 'height', 'EmptyFlux2LatentImage'), ('105', 0, '99', 'latent_image', 'SamplerCustomAdvanced'), ('99', 0, '100', 'samples', 'VAEDecode'), ('100', 0, '9', 'images', 'SaveImage'), ('123', 0, '129', 'image', 'GetImageSize'), ('129', 0, '128', 'width', 'EmptyFlux2LatentImage'), ('129', 1, '128', 'height', 'EmptyFlux2LatentImage'), ('128', 0, '116', 'latent_image', 'SamplerCustomAdvanced'), ('116', 0, '117', 'samples', 'VAEDecode'), ('117', 0, '94', 'images', 'SaveImage')]},
 'local-card-18': {'hash': 'cb11a2ca057fa2ef65ca4b0b413d589a8f7cd10717d14a138eb13fa0570f50b1',
  'fields': [_field('111', 'model1_megapixels', 'megapixels', MP, 1, '模型 1 输出总像素'), _field('122', 'model2_megapixels', 'megapixels', MP, 1, '模型 2 输出总像素')],
  'edges': [('111', 0, '113', 'image', 'GetImageSize'), ('113', 0, '110', 'width', 'EmptyFlux2LatentImage'), ('113', 1, '110', 'height', 'EmptyFlux2LatentImage'), ('110', 0, '102', 'latent_image', 'SamplerCustomAdvanced'), ('102', 0, '103', 'samples', 'VAEDecode'), ('103', 0, '9', 'images', 'SaveImage'), ('122', 0, '120', 'image', 'GetImageSize'), ('120', 0, '121', 'width', 'EmptyFlux2LatentImage'), ('120', 1, '121', 'height', 'EmptyFlux2LatentImage'), ('121', 0, '115', 'latent_image', 'SamplerCustomAdvanced'), ('115', 0, '116', 'samples', 'VAEDecode'), ('116', 0, '94', 'images', 'SaveImage')]},
 'local-card-20': {'hash': 'e4083d6210f4e70554db86f8f03f5389c74d85b33f4312818d4ba3c501ab31fb',
  'fields': [_field('32', 'megapixels', 'megapixels', MP, 1, '输出总像素')],
  'edges': [('32', 0, '14', 'image', 'GetImageSize'), ('14', 0, '10', 'width', 'EmptyFlux2LatentImage'), ('14', 1, '10', 'height', 'EmptyFlux2LatentImage'), ('10', 0, '5', 'latent_image', 'SamplerCustomAdvanced'), ('5', 0, '6', 'samples', 'VAEDecode'), ('6', 0, '15', 'images', 'SaveImage')]},
 'local-card-78': {'hash': 'bd512fb31963713cf5889c1955686cc1876d50df245990ad8fac883e619ce039',
  'fields': [_field('39', 'megapixels', 'megapixels', MP, 1.5, '输出总像素')],
  'edges': [('39', 0, '10', 'pixels', 'VAEEncode'), ('10', 0, '14', 'latent_image', 'KSampler'), ('14', 0, '12', 'samples', 'VAEDecode'), ('12', 0, '80', 'images', 'SaveImage')]},
 'local-card-85': {'hash': 'dd292b96f8e6f02fab2ccdb63b9e29b5e95976fbd26b71a8415fc139da571ef1',
  'fields': [_field('55', 'scale_by', 'scale_by', UPSCALE, 1.5, '放大重绘倍率')],
  'edges': [('56', 0, '55', 'samples', UPSCALE), ('55', 0, '63', 'latent_image', 'KSampler'), ('63', 0, '53', 'samples', 'VAEDecode'), ('53', 0, '54', 'images', 'SaveImage')]},
 'local-card-95': {'hash': 'aef44c1ec8a9448ec0385b3ca7315665ac0cb1f1e3bc0db2345a6addfaf1d5ca',
  'fields': [_field('12', 'megapixels', 'megapixels', MP, 1.5, '输出总像素')],
  'edges': [('12', 0, '7', 'image', 'GetImageSize'), ('7', 0, '9', 'width', 'EmptySD3LatentImage'), ('7', 1, '9', 'height', 'EmptySD3LatentImage'), ('9', 0, '8', 'latent_image', 'KSampler'), ('8', 0, '11', 'samples', 'VAEDecode'), ('11', 0, '24', 'images', 'SaveImage')]},
 'local-card-96': {'hash': 'ee3a3ebf4c4672c0d063f704a94bfda82becf4e005aae8b8f15c149acb770896',
  'fields': [_field('20', 'megapixels', 'megapixels', MP, 1.5, '输出总像素')],
  'edges': [('20', 0, '9', 'image', 'GetImageSize'), ('9', 0, '11', 'width', 'EmptySD3LatentImage'), ('9', 1, '11', 'height', 'EmptySD3LatentImage'), ('11', 0, '10', 'latent_image', 'KSampler'), ('10', 0, '19', 'samples', 'VAEDecode'), ('19', 0, '18', 'images', 'SaveImage')]},
 'local-card-114': {'hash': 'ad0d67229a6193376255d3ef01468a20736ba57c1f5e4ebb9ff5d4256bbc4562',
  'fields': [_field('120', 'megapixels', 'megapixels', MP, 1, '输出总像素')],
  'edges': [('120', 0, '126', 'image', 'GetImageSize'), ('126', 0, '125', 'width', 'EmptyFlux2LatentImage'), ('126', 1, '125', 'height', 'EmptyFlux2LatentImage'), ('125', 0, '114', 'latent_image', 'SamplerCustomAdvanced'), ('114', 0, '115', 'samples', 'VAEDecode'), ('115', 0, '110', 'images', 'SaveImage')]},
}

LEGACY = {'local-card-' + str(n) for n in (12, 16, 17, 18, 20, 78, 85)}


def _execution_template(wid):
    from configuration import workflow_path
    from schema_adapters import manifest, template_path
    spec = manifest(wid)
    return json.loads((template_path(spec) if spec else workflow_path(wid)).read_text('utf-8-sig'))


def _check_execution(contract, template):
    for definition in contract['fields']:
        field = definition['field']; target = field['targets'][0]
        node = template.get(target['node'], {})
        if node.get('class_type') != field['node'] or node.get('inputs', {}).get(target['input']) != field['value']:
            raise ValueError('生成尺寸的真实执行默认值已改变。')
        if field['node'] == LAYER:
            inputs = node['inputs']
            if inputs.get('scale_to_side') != definition['side'] or inputs.get('round_to_multiple') != definition['multiple'] or inputs.get('aspect_ratio') != 'original':
                raise ValueError('生成尺寸的单位、比例或取整方式已改变。')
    for src, slot, dst, port, typ in contract['edges']:
        node = template.get(dst, {})
        if node.get('class_type') != typ or node.get('inputs', {}).get(port) != [src, slot]:
            raise ValueError('生成尺寸的真实潜空间或输出连线已改变。')


def reviewed_generation_sizes(workflow, controls, *, graph=None, source_hash=None, derived=None):
    """Apply the same exact source contract to fresh extraction and curated forms."""
    contract = CONTRACTS.get(workflow.get('id'))
    if contract is None:
        return controls
    if source_hash != contract['hash']:
        raise ValueError('生成尺寸参数的原始来源已改变。')
    if graph is not None:
        from build_workflow_interfaces import widget_bindings
        info = json.loads((Path(__file__).resolve().parents[1] / 'private/review72/object_info.json').read_text('utf-8-sig'))
        for definition in contract['fields']:
            field = definition['field']; target = field['targets'][0]
            nid, key = target['node'], target['input']; node = graph.nodes.get(nid, {})
            values = widget_bindings(node)
            if (node.get('type') != field['node'] or node.get('mode', 0) != 0 or nid not in graph.reachable or
                    values.get(key, (None,))[0] != field['value'] or not graph.editable(nid, key) or graph.targets(nid, key) != [(nid, key)]):
                raise ValueError('生成尺寸的原始可编辑默认值或绑定未匹配。')
            if field['node'] == LAYER and (values.get('scale_to_side', (None,))[0] != definition['side'] or
                    values.get('round_to_multiple', (None,))[0] != definition['multiple'] or values.get('aspect_ratio', (None,))[0] != 'original'):
                raise ValueError('生成尺寸的原始单位、比例或取整方式已改变。')
            native = info[field['node']]['input']['required'][key]
            expected = ('INT', 4, 100000000, 1) if field['node'] == LAYER else ('FLOAT', field['min'], field['max'], field['step'])
            if (native[0], native[1].get('min'), native[1].get('max'), native[1].get('step')) != expected:
                raise ValueError('生成尺寸的已安装原生类型或范围已改变。')
        _check_execution(contract, _execution_template(workflow['id']))
    elif (derived or {}).get('sourceHash') != source_hash:
        raise ValueError('缺少生成尺寸的同源参数证明。')
    result = deepcopy(controls)
    for definition in contract['fields']:
        field = deepcopy(definition['field'])
        if graph is None:
            proof = [f for f in (derived or {}).get('controls', []) if f.get('id') == field['id']]
            if len(proof) != 1 or any(proof[0].get(k) != v for k, v in field.items()):
                raise ValueError('生成尺寸的同源默认值或真实绑定已改变。')
        existing = [f for f in result if f.get('id') == field['id']]
        if len(existing) > 1:
            raise ValueError('生成尺寸出现重复入口。')
        if existing:
            existing[0].update(field)
        else:
            result.append(field)
    return result


def legacy_generation_size_keys(wid):
    return {definition['field']['key'] for definition in CONTRACTS.get(wid, {}).get('fields', [])} if wid in LEGACY else set()


def generation_size_settings(wid, supplied):
    """Absent new keys intentionally stay absent for saved legacy tickets."""
    result = {}
    if wid not in LEGACY:
        return result
    for definition in CONTRACTS[wid]['fields']:
        field = definition['field']; key = field['key']
        if key not in supplied:
            continue
        value = supplied[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not field['min'] <= value <= field['max']:
            raise ValueError(field['label'] + '超出允许范围。')
        if field.get('integer') and not isinstance(value, int):
            raise ValueError(field['label'] + '需要填写整数。')
        steps = (value - field['min']) / field['step']
        if abs(steps - round(steps)) > 1e-6:
            raise ValueError(field['label'] + '不符合调整步长。')
        result[key] = value
    return result


def apply_generation_size_settings(wid, template, settings):
    """Change only supplied reviewed leaves; never rewrite old graph defaults."""
    values = generation_size_settings(wid, settings)
    if not values:
        return
    contract = CONTRACTS[wid]
    _check_execution(contract, template)
    for definition in contract['fields']:
        field = definition['field']; key = field['key']
        if key in values:
            target = field['targets'][0]
            template[target['node']]['inputs'][target['input']] = values[key]
