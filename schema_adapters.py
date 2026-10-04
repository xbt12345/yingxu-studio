"""Execute reviewed workflow contracts without accepting client node bindings.

The compiler owns the registry and concrete API targets. Browsers send stable
control, text and media-slot IDs; saved jobs retain the exact reviewed contract
so a later catalog rebuild cannot change the meaning of a rerun.
"""
import copy
import json
import math
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from adapters import prune
from configuration import ROOT, WORKFLOW_DIR, workflow_path

REGISTRY_PATH = ROOT / 'workflows/compiled-registry.json'


def registry():
    try:
        raw = json.loads(REGISTRY_PATH.read_text('utf-8'))
    except FileNotFoundError:
        return {}
    entries = raw.get('workflows', {})
    if not isinstance(entries, dict):
        raise ValueError('工作流执行目录格式不正确。')
    return {key: value for key, value in entries.items()
            if isinstance(value, dict) and value.get('adapter') == 'generic'}


def manifest(workflow_id):
    return registry().get(workflow_id)


def template_path(spec):
    name = spec.get('template', spec['id'] + '.api.json')
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.api.json'):
        raise ValueError('工作流模板路径不正确。')
    card_private=ROOT / 'private/card-compiled' / name
    if card_private.is_file():
        return card_private
    # Respect the same owner-private override contract as the original adapters.
    configured = workflow_path(spec['id'])
    return configured if configured.is_file() else WORKFLOW_DIR / name


def require_ready(spec):
    if spec.get('validation') == 'blocked':
        raise ValueError(spec.get('blocking_reason') or '此工作流仍有未确认的输入，暂不能提交。')
    if spec.get('validation') != 'structural-verified':
        raise ValueError('此工作流的执行参数尚未通过结构检查。')


def _known_mapping(value, fields, noun):
    if not isinstance(value, dict) or set(value) - {item['id'] for item in fields}:
        raise ValueError(f'{noun}包含不属于此工作流的项目，请刷新后重试。')


def _number(value):
    if not isinstance(value,(int,float)) or isinstance(value,bool):return False
    try:return math.isfinite(value)
    except OverflowError:return False


def validate_points(value):
    try:points=json.loads(value)
    except (ValueError,TypeError):raise ValueError('主体选点格式不正确，请重新选择。') from None
    if not isinstance(points,dict) or set(points)!={'positive','negative'}:
        raise ValueError('主体选点需要包含主体点与排除点。')
    for kind in ('positive','negative'):
        items=points[kind]
        if not isinstance(items,list) or len(items)>12:
            raise ValueError('主体点和排除点各最多 12 个。')
        for point in items:
            if not isinstance(point,dict) or set(point)!={'x','y'} or any(not _number(point[key]) or not 0<=point[key]<=1 for key in ('x','y')):
                raise ValueError('请选择画面范围内的主体点。')
    if not points['positive']:
        raise ValueError('请先在原视频的人物主体上添加至少一个主体点。')
    return points


def validate_indices(value):
    """Reviewed person-index controls only; blank means all detected people."""
    if not isinstance(value,str) or len(value)>6000 or '\x00' in value:
        raise ValueError('处理对象索引需要有效文字；留空处理全部，或填写 0,2,3。')
    value=value.strip().replace('，',',')
    if not value:return ''
    parts=[part.strip()for part in value.split(',')]
    if any(not re.fullmatch(r'[0-9]+',part)for part in parts):
        raise ValueError('处理对象索引只支持逗号分隔的非负整数，例如 0,2,3；留空处理全部。')
    # Preserve the selected order without sending duplicate object indices.
    return ','.join(dict.fromkeys(part.lstrip('0')or'0'for part in parts))


def _random_seed(field, previous=None):
    maximum = min(int(field.get('max', 9007199254740991)), 9007199254740991)
    minimum = max(0, int(field.get('min', 0)))
    if maximum < minimum:
        raise ValueError('随机种子的范围不正确。')
    # Keep each redraw different when the node allows more than one seed.
    span = maximum - minimum + 1
    value = minimum + secrets.randbelow(span)
    if span > 1 and value == previous:
        value = minimum + (value - minimum + 1) % span
    return value


def validate_values(spec, supplied):
    fields = spec.get('controls', [])
    _known_mapping(supplied, fields, '创作参数')
    result = {}
    for field in fields:
        value = supplied.get(field['id'], field.get('value'))
        label = field.get('label') or field.get('key') or '参数'
        kind = field.get('kind')
        if kind == 'seed' and value == -1 and not isinstance(value, bool):
            value = _random_seed(field)
        typ = field.get('type')
        if typ == 'number' or kind == 'seed':
            if not _number(value):
                raise ValueError(f'{label}需要有效数字。')
            if field.get('integer') and int(value) != value:
                raise ValueError(f'{label}需要整数。')
            if kind == 'seed' and (int(value) != value or not 0 <= value <= 9007199254740991):
                raise ValueError(f'{label}需要有效整数。')
            minimum, maximum = field.get('min'), field.get('max')
            if minimum is not None and value < minimum or maximum is not None and value > maximum:
                raise ValueError(f'{label}超出支持范围。')
            step = field.get('step')
            if _number(step) and step > 0 and value != field.get('value'):
                origin=minimum if _number(minimum) else 0
                count = (value-origin) / step
                if abs(count - round(count)) > 1e-6:
                    raise ValueError(f'{label}的调整步长为 {step}。')
        elif typ in ('checkbox', 'boolean'):
            if not isinstance(value, bool):
                raise ValueError(f'{label}需要开关值。')
        else:
            if not isinstance(value, str) or len(value) > 6000 or '\x00' in value:
                raise ValueError(f'{label}需要有效文字。')
        if kind=='indices':value=validate_indices(value)
        options = field.get('options')
        allowed = [option.get('value') if isinstance(option, dict) else option for option in options or []]
        custom = field.get('customRange')
        if options and value not in allowed and not custom:
            raise ValueError(f'请选择支持的{label}。')
        if custom and _number(value):
            minimum, maximum, step = custom.get('min'), custom.get('max'), custom.get('step')
            if minimum is not None and value < minimum or maximum is not None and value > maximum:
                raise ValueError(f'{label}超出自定义范围。')
            if _number(step) and step > 0:
                origin=minimum if _number(minimum) else 0
                count=(value-origin)/step
                if abs(count-round(count))>1e-6:raise ValueError(f'{label}的调整步长为 {step}。')
        if kind=='points':validate_points(value)
        result[field['id']] = value
    for constraint in spec.get('constraints',[]):
        if constraint.get('type')!='nonzero-size':raise ValueError('工作流的参数组合约束未完成审查。')
        width,height=(result.get(constraint.get(key))for key in ('width','height'))
        if not _number(width)or not _number(height):raise ValueError('画面尺寸约束未完成审查。')
        if width==0 and height==0:raise ValueError('输出宽度和高度不能同时为 0；请至少填写一边，另一边可填 0 自动保持比例。')
    return result


def validate_texts(spec, supplied, prompt='', negative=''):
    fields = spec.get('texts', [])
    _known_mapping(supplied, fields, '描述')
    first = {role: next((item['id'] for item in fields if item.get('role') == role), None)
             for role in ('prompt', 'negative')}
    result = {}
    for field in fields:
        fallback = prompt if field['id'] == first['prompt'] else negative if field['id'] == first['negative'] else ''
        value = supplied.get(field['id'], fallback or field.get('default', field.get('value', '')))
        if not isinstance(value, str) or len(value) > 6000 or '\x00' in value:
            raise ValueError('描述需要是 6000 字以内的文字。')
        if field.get('required') and not value.strip():
            raise ValueError('请填写' + (field.get('label') or '创作描述') + '。')
        result[field['id']] = value
    return result


def validate_assets(spec, supplied):
    """Values are resolved server asset records, never remote paths from a browser."""
    fields = spec.get('media', [])
    _known_mapping(supplied, fields, '参考素材')
    for field in fields:
        record = supplied.get(field['id'])
        if record is None:
            if field.get('required', not field.get('optional', False)):
                raise ValueError('请先添加' + (field.get('label') or '参考素材') + '。')
            continue
        if not isinstance(record, dict) or record.get('kind') != field['kind']:
            raise ValueError((field.get('label') or '参考素材') + '的文件类型不匹配。')
    return supplied


def _targets(field):
    targets = field.get('targets', [])
    if not isinstance(targets, list) or not targets:
        raise ValueError('工作流参数没有已确认的执行绑定。')
    return targets


def _put(graph, target, value):
    node, key = str(target['node']), target['input']
    if node not in graph or not isinstance(key, str):
        raise ValueError('工作流执行参数已经变化，请重新审查后接入。')
    inputs = graph[node].get('inputs', {})
    if key not in inputs and not target.get('optional') and not target.get('valueMode') == 'loader':
        raise ValueError('工作流执行参数不存在，请重新审查后接入。')
    inputs[key] = value
    graph[node]['inputs'] = inputs


def _control_values(field, value, values, geometry=None):
    transform = field.get('transform') or field.get('derived')
    if not transform:
        return [(target, value) for target in _targets(field)]
    operation = transform.get('operation')
    if operation=='number-string':
        if not _number(value):raise ValueError('此数值参数需要有效数字。')
        if field.get('integer') and int(value)!=value:raise ValueError('此数值参数需要整数。')
        encoded=str(int(value)) if field.get('integer') else str(value)
        return [(target,encoded)for target in _targets(field)]
    if operation=='points':
        points=validate_points(value)
        if not geometry or not all(isinstance(geometry.get(key),int) and geometry[key]>0 for key in ('width','height')):
            raise ValueError('无法确定主体点选的处理画面尺寸，请重新导入原视频。')
        node=geometry.get('node')
        if not node:raise ValueError('主体点选的执行节点尚未确认。')
        absolute={kind:[{'x':min(geometry['width']-1,round(point['x']*geometry['width'])),
                         'y':min(geometry['height']-1,round(point['y']*geometry['height']))}for point in points[kind]]for kind in ('positive','negative')}
        encoded={'coordinates':json.dumps(absolute['positive'],separators=(',',':')),
                 'neg_coordinates':json.dumps(absolute['negative'],separators=(',',':')),
                 'points_store':json.dumps(absolute,separators=(',',':')),
                 'bboxes':'[]','bbox_store':'[]','normalize':False}
        bindings=[({'node':str(node),'input':key},data)for key,data in encoded.items()]
        if geometry.get('negativeTarget'):
            bindings.append((geometry['negativeTarget'],[str(node),1]))
        return bindings
    if operation == 'frames':
        fps = transform.get('fps')
        if not _number(fps) or fps <= 0:
            raise ValueError('工作流未确认帧率，不能将秒数换成帧数。')
        return [(target, round(value * fps)) for target in _targets(field)]
    if operation == 'audio-end':
        start = values.get(transform.get('startId'))
        if not _number(start) or not _number(value) or value <= start:
            raise ValueError('音频终点需要晚于起点。')
        return [(target, value - start) for target in _targets(field)]
    if operation == 'size':
        match = re.fullmatch(r'(\d{1,5})[x×](\d{1,5})', value)
        if not match:
            raise ValueError('画面尺寸需填写宽×高。')
        width, height = map(int, match.groups())
        custom = field.get('customRange') or {}
        for side in (width, height):
            if custom.get('min') is not None and side < custom['min'] or custom.get('max') is not None and side > custom['max']:
                raise ValueError('画面尺寸超出支持范围。')
            if custom.get('step') and side % custom['step']:
                raise ValueError('画面尺寸不符合步长要求。')
        result = []
        for target in _targets(field):
            axis = target.get('axis') or transform.get('axisByTarget', {}).get(str(target['node']) + '.' + target['input'])
            if axis not in ('width', 'height'):
                raise ValueError('画面尺寸的宽高绑定尚未确认。')
            result.append((target, width if axis == 'width' else height))
        return result
    raise ValueError('此参数的转换方式尚未完成审查。')


def _prefixes(graph, outputs, job_id):
    for index, node in enumerate(outputs):
        inputs = graph.get(str(node), {}).get('inputs', {})
        if 'filename_prefix' in inputs:
            inputs['filename_prefix'] = 'yingxu/' + job_id + ('/result-' + str(index + 1) if len(outputs) > 1 else '')


def bind_assets(graph, spec, records):
    validate_assets(spec, records)
    for field in spec.get('media', []):
        record = records.get(field['id'])
        for target in _targets(field):
            if record is None:
                # Optional ports must be annotated by the compiler. Never delete
                # a required loader input and leave a graph that cannot execute.
                if not target.get('optional'):
                    raise ValueError('可选素材端口未完成结构审查。')
                graph.get(str(target['node']), {}).get('inputs', {}).pop(target['input'], None)
                continue
            if target.get('valueMode') == 'loader':
                if field['kind'] != 'image':
                    raise ValueError('此素材端口尚无已确认的文件加载器。')
                loader = 'yingxu-upload-' + re.sub(r'[^a-zA-Z0-9_-]', '_', field['id'])
                graph[loader] = {'class_type': 'LoadImage', 'inputs': {'image': record['remote']}}
                _put(graph, target, [loader, int(target.get('outputIndex', 0))])
            else:
                _put(graph, target, record['remote'])
    return graph


def bind_api_profiles(graph, spec, profiles):
    fields = spec.get('apiProfiles', [])
    _known_mapping(profiles, fields, 'API 配置')
    for field in fields:
        if field['id'] not in profiles:
            continue
        choice = profiles[field['id']]
        if not isinstance(choice, dict) or set(choice)-{'mode', 'base_url', 'model', 'api_key'} or not {'mode','model','api_key'}<=set(choice) or choice.get('mode') != 'custom':
            raise ValueError('请检查自有 API 配置。')
        base, model, key = (choice.get(k,'').strip() if isinstance(choice.get(k), str) else '' for k in ('base_url', 'model', 'api_key'))
        parsed = urlsplit(base)
        key_only=field.get('keyOnly') or not field.get('bindings',{}).get('baseUrl')
        if not key_only and (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or len(base) > 400):
            raise ValueError('Base URL 需要是有效的 HTTP 或 HTTPS 地址。')
        if not model or len(model) > 120 or not key or len(key) > 500:
            raise ValueError('请填写有效的 Model 和 API key。')
        model_options=field.get('modelOptions')
        if model_options and model not in [option.get('value') if isinstance(option,dict) else option for option in model_options]:
            raise ValueError('请选择此节点支持的 Model。')
        for name, value in [('baseUrl', base), ('model', model), ('apiKey', key)]:
            if name=='baseUrl' and key_only:continue
            binding = field.get('bindings', {}).get(name)
            targets = binding if isinstance(binding, list) else [binding]
            for target in targets:
                if not isinstance(target, dict):
                    raise ValueError('API 输入绑定尚未完成审查。')
                _put(graph, target, value)
    return graph


def build(spec, supplied_values, supplied_texts, records, profiles, job_id, prompt='', negative='',geometry=None):
    require_ready(spec)
    values = validate_values(spec, supplied_values)
    texts = validate_texts(spec, supplied_texts, prompt, negative)
    graph = json.loads(template_path(spec).read_text('utf-8'))
    for field in spec.get('controls', []):
        for target, value in _control_values(field, values[field['id']], values,geometry):
            _put(graph, target, value)
    for field in spec.get('texts', []):
        if field.get('preserveWhenEmpty') and not texts[field['id']].strip():
            continue
        for target in _targets(field):
            _put(graph, target, texts[field['id']])
    bind_assets(graph, spec, records)
    bind_api_profiles(graph, spec, profiles)
    _prefixes(graph, spec['outputs'], job_id)
    graph = prune(graph, spec['outputs'])
    return graph, values, texts


def rerun(original, records, job_id):
    """Keep the saved graph and credentials; redraw only reviewed random seeds."""
    spec = original['schema_spec']
    graph = copy.deepcopy(original['graph'])
    values = copy.deepcopy(original['catalog_values'])
    for field in spec.get('controls', []):
        if field.get('kind') != 'seed':
            continue
        value = _random_seed(field, values.get(field['id']))
        values[field['id']] = value
        for target, adjusted in _control_values(field, value, values):
            _put(graph, target, adjusted)
    bind_assets(graph, spec, records)
    _prefixes(graph, spec['outputs'], job_id)
    return prune(graph, spec['outputs']), values
