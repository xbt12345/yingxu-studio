"""Save the requested H3 duration while retaining the model's latent grid."""
import copy
import math


GRID = 'max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17'
# source hash, seconds source, latent grid, conditioning, decoded image/audio,
# CreateVideo and final SaveVideo. These are reviewed compiled source contracts.
CONTRACTS = {
    'local-card-55': ('13d646fa7dd7669d9b1ac2792ba1029889284bce7bd35d15b8172a2cf9a589f1',
                      '105:111', '105:107', '105:104', ['105:10', 0], ['105:23', 0], '105:91', '92'),
    'local-card-58': ('cd02a64bdf7ef7e28d91aad6731b7eea7e115a84504b4ad03dc0d2f742de0053',
                      '31', '21', '18', ['6', 0], ['6', 1], '9', '4'),
    'local-card-63': ('0455d4a25ad67f328b077c8f031c0b71f5e8d90f185af5e219f813072f2caf05',
                      '27', '14', '28', ['30', 0], ['23', 0], '26', '1'),
    'local-card-64': ('2aee949e9b20edabc0971eb08d106eb27cee0e11a45d7383afb1e00333530bdc',
                      '133', '132', '131', ['122', 0], ['121', 0], '130', '92'),
}


def preserve_h3_duration(graph, spec):
    wid = spec.get('id')
    if wid not in CONTRACTS:
        return []
    digest, seconds, grid, cond, image, audio, create, save = CONTRACTS[wid]
    if spec.get('source_hash') != digest or spec.get('outputs') != [save]:
        raise ValueError('视频时长适配的来源或输出已改变，需要重新审查。')
    candidate = copy.deepcopy(graph)

    def match(nid, cls, **inputs):
        node = candidate.get(nid, {})
        if node.get('class_type') != cls or any(node.get('inputs', {}).get(k) != v for k, v in inputs.items()):
            raise ValueError('视频时长适配未匹配已审节点或连线。')
        return node['inputs']

    grid_inputs=match(grid, 'ComfyMathExpression', expression=GRID)
    seconds_binding=grid_inputs.get('values.a')
    def valid_seconds_binding(value):
        return value==[seconds,0] or (wid=='local-card-64' and type(value) in (int,float) and math.isfinite(value) and value>=0)
    if not valid_seconds_binding(seconds_binding):
        raise ValueError('视频时长适配的秒数来源已改变。')
    if seconds in candidate:
        match(seconds, 'PrimitiveFloat')
    elif seconds_binding==[seconds,0]:
        raise ValueError('视频时长适配缺少秒数节点。')
    match(cond, 'MiniMaxH3ImageToVideo', length=[grid, 1])
    match(save, 'SaveVideo', video=[create, 0])
    ci = match(create, 'CreateVideo', fps=24)
    prefix = 'yingxu_review74_requested_duration'
    injected = {
        prefix+'_frames': {'class_type': 'ComfyMathExpression', 'inputs': {
            'expression': 'max(5, round(a * 24))', 'values.a': copy.deepcopy(seconds_binding)}},
        prefix+'_seconds': {'class_type': 'ComfyMathExpression', 'inputs': {
            'expression': 'a / 24', 'values.a': [prefix+'_frames', 1]}},
        prefix+'_images': {'class_type': 'ImageFromBatch', 'inputs': {
            'image': image, 'batch_index': 0, 'length': [prefix+'_frames', 1]}},
        prefix+'_audio': {'class_type': 'TrimAudioDuration', 'inputs': {
            'audio': audio, 'start_index': 0, 'duration': [prefix+'_seconds', 0]}},
    }
    previous=candidate[create].get('_meta',{}).get('yingxu_requested_duration')
    evidence = {'id': 'review74-h3-save-requested-duration', 'source_hash': digest,
                'fps': 24, 'minimum_frames': 5, 'seconds_source': seconds,
                'create_video': create, 'output': save, 'latent_grid_unchanged': True,
                'seconds_binding': copy.deepcopy(seconds_binding)}
    if previous is not None:
        if (not isinstance(previous,dict) or not valid_seconds_binding(previous.get('seconds_binding')) or
                {k:v for k,v in previous.items() if k!='seconds_binding'}!={k:v for k,v in evidence.items() if k!='seconds_binding'}):
            raise ValueError('视频时长适配的绑定记录已改变。')
    for nid, node in injected.items():
        if nid in candidate:
            expected=copy.deepcopy(node['inputs'])
            if nid==prefix+'_frames' and previous is not None:
                expected['values.a']=previous['seconds_binding']
            if previous is None or candidate[nid].get('class_type') != node['class_type'] or candidate[nid].get('inputs') != expected:
                raise ValueError('视频时长适配的保存记录已改变。')
            candidate[nid]['inputs']=copy.deepcopy(node['inputs'])
        else:
            candidate[nid] = {**node, '_meta': {'title': '保留用户选择的视频时长'}}
    for key, original, replacement in [('images', image, [prefix+'_images', 0]),
                                        ('audio', audio, [prefix+'_audio', 0])]:
        if ci.get(key) not in (original, replacement):
            raise ValueError('视频时长适配不能覆盖未审查的保存来源。')
        ci[key] = replacement
    candidate[create].setdefault('_meta', {})['yingxu_requested_duration'] = copy.deepcopy(evidence)
    graph.clear()
    graph.update(candidate)
    return [evidence]
