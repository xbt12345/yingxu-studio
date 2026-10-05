"""Build per-workflow UI bindings from the actual graph, without exporting prompt values.

The catalog is a discovery index, not a parameter schema. Only reachable, unlinked
creation inputs are editable. Internal defaults remain in the original graph.
"""
import ast
import hashlib
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def edges(graph):
    for link in graph.get('links', []):
        if isinstance(link, dict):
            yield link['origin_id'], link['origin_slot'], link['target_id'], link['target_slot']
        else:
            yield link[1], link[2], link[3], link[4]


def widget_bindings(node):
    """Recover positional widgets only when actual socket metadata aligns exactly."""
    named = node.get('widgets_values_named')
    vals = node.get('widgets_values', [])
    if isinstance(named, dict):
        return {key: (value, None) for key, value in named.items()}
    if isinstance(vals, dict):
        return {key: (value, None) for key, value in vals.items()}
    names = [i['widget']['name'] for i in node.get('inputs', []) if i.get('widget')]
    indexed = [(i, v) for i, v in enumerate(vals) if not (isinstance(v, str) and v in ['randomize', 'fixed', 'increment', 'decrement'])]
    if len(indexed) != len(names) or len(set(names)) != len(names):
        return {}
    return {name: (value, index) for name, (index, value) in zip(names, indexed)}


class Graph:
    def __init__(self, raw):
        if 'nodes' not in raw:
            ns, ls = [], []
            for nid, entry in raw.items():
                inputs = []
                for key, val in entry.get('inputs', {}).items():
                    inp = {'name': key, 'link': None}
                    if isinstance(val, list) and len(val) == 2:
                        inp['link'] = len(ls)
                        ls.append([len(ls), val[0], val[1], nid, len(inputs), ''])
                    inputs.append(inp)
                ns.append({'id': nid, 'type': entry.get('class_type', ''), 'inputs': inputs,
                           'widgets_values_named': entry.get('inputs', {}), 'mode': 0})
            raw = {'nodes': ns, 'links': ls}
        self.nodes, self.out, self.ins, self.context = {}, defaultdict(list), defaultdict(list), {}
        self.defs = {d['id']: (f'sub{i}/', d) for i, d in enumerate(raw.get('definitions', {}).get('subgraphs', []))}
        self.add(raw, '')
        # Definitions used by live instances only; unused definitions cannot leak controls.
        visited = set()
        for nid, node in list(self.nodes.items()):
            if node.get('type') in self.defs and node.get('mode', 0) not in [2, 4]:
                self.expand(nid, node, visited)
        # KJ Set/Get nodes carry edges by name instead of explicit graph links.
        setters = defaultdict(list)
        for nid, node in self.nodes.items():
            if node['type'] == 'SetNode':
                vals = node.get('widgets_values', [])
                if isinstance(vals, list) and vals:
                    setters[(self.context[nid], str(vals[0]))].append(nid)
        for nid, node in self.nodes.items():
            if node['type'] == 'GetNode':
                vals = node.get('widgets_values', [])
                candidates = setters.get((self.context[nid], str(vals[0])), []) if isinstance(vals, list) and vals else []
                if len(candidates) == 1:
                    self.connect(candidates[0], 0, nid, 0)
        # Explicit broadcast nodes: a missing typed socket is resolved only with
        # one matching broadcaster in this graph. Ambiguity stays unexposed.
        broadcasts = defaultdict(list)
        for nid, node in self.nodes.items():
            if node['type'] in ['Anything Everywhere', 'Anything Everywhere3']:
                for src, oslot, islot in self.ins[nid]:
                    inp = node.get('inputs', [])[islot]
                    broadcasts[(self.context[nid], inp.get('type'))].append(src)
        for nid, node in self.nodes.items():
            for idx, inp in enumerate(node.get('inputs', [])):
                if inp.get('link') is None and not inp.get('widget'):
                    candidates = broadcasts.get((self.context[nid], inp.get('type')), [])
                    if len(candidates) == 1 and candidates[0] != nid:
                        self.connect(candidates[0], 0, nid, idx)
        sinks = [k for k, n in self.nodes.items() if self.enabled(k) and
                 re.search(r'SaveImage|SaveVideo|VideoCombine|ShowText|showAnything|PreviewImage|PreviewAudio|TextPreview|SaveAudio|SaveAnimated', n['type'], re.I)]
        self.reachable = set()
        pending = sinks
        while pending:
            nid = pending.pop()
            if nid in self.reachable:
                continue
            self.reachable.add(nid)
            pending += [src for src, _, _ in self.ins[nid] if self.enabled(src)]

    def enabled(self, nid):
        return nid in self.nodes and self.nodes[nid].get('mode', 0) != 2

    def add(self, graph, prefix):
        for node in graph.get('nodes', []):
            key = prefix + str(node['id'])
            self.nodes[key] = node
            self.context[key] = prefix
        for src, oslot, dst, islot in edges(graph):
            self.connect(prefix + str(src), oslot, prefix + str(dst), islot)

    def connect(self, src, oslot, dst, islot):
        self.out[src].append((dst, islot, oslot))
        self.ins[dst].append((src, oslot, islot))

    def expand(self, nid, node, visited):
        prefix, graph = self.defs[node['type']]
        if prefix not in visited:
            visited.add(prefix)
            self.add(graph, prefix)
            for child in graph.get('nodes', []):
                if child.get('type') in self.defs and child.get('mode', 0) not in [2, 4]:
                    self.expand(prefix + str(child['id']), child, visited)
        for src, oslot, dst, islot in edges(graph):
            if int(src) == -10:
                self.connect(nid, oslot, prefix + str(dst), islot)
            if int(dst) == -20:
                self.connect(prefix + str(src), oslot, nid, islot)

    def editable(self, nid, key):
        if nid not in self.reachable or self.nodes[nid].get('mode', 0) in [2, 4]:
            return False
        inputs = self.nodes[nid].get('inputs', [])
        index = next((i for i, inp in enumerate(inputs) if inp['name'] == key), None)
        # Cross-boundary traversal edges are not widget bindings on a parent
        # instance. Use the actual socket, otherwise output slot 0 would mask
        # a perfectly editable prompt at input slot 0.
        return index is None or inputs[index].get('link') is None

    def targets(self, nid, key):
        """Resolve exposed subgraph widgets and scalar sources to concrete input names."""
        node = self.nodes.get(nid, {})
        if node.get('type') in self.defs:
            prefix, graph = self.defs[node['type']]
            idx = next((i for i, inp in enumerate(node.get('inputs', [])) if inp['name'] == key), None)
            result = []
            for src, oslot, dst, slot in edges(graph):
                if int(src) == -10 and oslot == idx:
                    dest = self.nodes.get(prefix + str(dst), {})
                    names = dest.get('inputs', [])
                    result.append((prefix + str(dst), names[slot]['name'] if slot < len(names) else key))
            return result
        if key in ['value', 'value_1', 'widget_0', 'string'] or node.get('type') == 'CR Prompt Text':
            return [(dst, self.nodes[dst].get('inputs', [])[slot]['name'])
                    for dst, slot, _ in self.out[nid] if dst in self.nodes and
                    slot < len(self.nodes[dst].get('inputs', []))]
        return [(nid, key)]

    def text_role(self, nid, key):
        if re.search(r'negative|反向|负面', key + self.nodes[nid].get('title', ''), re.I):
            return 'negative'
        targets = self.targets(nid, key)
        if targets and all(re.search(r'negative|反向|负面', self.nodes.get(t, {}).get('title', '') + k, re.I) for t, k in targets):
            return 'negative'
        pending, seen, roles = [nid], set(), set()
        while pending:
            src = pending.pop()
            if src in seen:
                continue
            seen.add(src)
            for dst, slot, _ in self.out[src]:
                node = self.nodes.get(dst, {})
                inputs = node.get('inputs', [])
                name = inputs[slot]['name'] if slot < len(inputs) else ''
                if name in ['negative', 'negative_prompt', 'positive', 'positive_prompt']:
                    roles.add('negative' if 'negative' in name else 'prompt')
                elif dst in self.nodes and dst not in seen:
                    pending.append(dst)
        return 'negative' if roles == {'negative'} else 'prompt'

    def media_role(self, nid, workflow, default):
        pending, seen = [nid], set()
        while pending:
            src = pending.pop(0)
            if src in seen:
                continue
            seen.add(src)
            for dst, slot, _ in self.out[src]:
                node = self.nodes.get(dst, {})
                inputs = node.get('inputs', [])
                key = inputs[slot]['name'] if slot < len(inputs) else ''
                if key == 'first_frame':
                    return '首帧'
                if key == 'last_frame':
                    return '尾帧'
                if node.get('type') == 'ColorMatch':
                    return '待调色原图' if key == 'image_target' else '色彩参考图'
                if re.search(r'衣服|服装|换衣', workflow['name']):
                    if key == 'images.image_1':
                        return '人物原图'
                    if key == 'images.image_2':
                        return '服装参考图'
                if key == 'image_a' and node.get('type') == 'Image Comparer (rgthree)':
                    return '待编辑原图'
                if key not in ['mask', 'image_a', 'image_b'] and dst in self.nodes and dst not in seen:
                    pending.append(dst)
        return default


def semantic(graph, f, workflow):
    key, nid = f['key'], f['nodeId']
    typ = graph.nodes.get(nid, {}).get('type', '')
    title = graph.nodes.get(nid, {}).get('title', '')
    targets = graph.targets(nid, key)
    target_keys = {k for _, k in targets}
    effective = target_keys | {key}
    if typ == 'ResolutionSelector' and key == 'megapixels':
        return 'resolution', '输出分辨率（百万像素）'
    if 'end_time' in effective or 'end_seconds' in effective:
        return 'segment', '音频片段终点（分:秒）' if isinstance(f['value'], str) and ':' in f['value'] else '音频片段终点（秒）'
    if workflow['category'] == '动作迁移与舞蹈':
        for names, label in [({'video_frame_offset', 'video_frame_offset_1'}, '动作片段起始帧'), ({'pose_strength','pose_strength_1'}, '动作参考强度'), ({'reference_image_strength','reference_image_strength_1','ref_strength'}, '角色参考强度')]:
            if effective & names:
                return 'motion', label
        if effective & {'length','num_frames'} and (typ in graph.defs or any(re.search('Animate.*ToVideo',graph.nodes.get(t,{}).get('type','')) for t,_ in targets) or re.search('Animate.*ToVideo',typ)):
            return 'motion', '单段生成帧数'
    if workflow['category'] == '参考图与套图' and effective & {'max_count'}:
        return 'count', '套图数量'
    if workflow['category'] == '图像增强与整理':
        if key == 'denoise' and re.search('Sampler',typ):
            return 'restoration', '细节重绘幅度'
        if typ == 'ImageScaleToTotalPixels' and key == 'megapixels':
            return 'resolution', '输出大小（百万像素）'
        if typ == 'easy anythingIndexSwitch' and key == 'index' and any(graph.nodes.get(dst,{}).get('inputs',[])[slot]['name']=='mask' for dst,slot,_ in graph.out[nid] if slot<len(graph.nodes.get(dst,{}).get('inputs',[]))):
            return 'mask', '清理掩膜来源'
    if workflow['category'] == '素材格式工具':
        for keys,label in [({'directory','path'},'本地素材目录'),({'pattern'},'文件匹配规则'),({'index','start_index'},'文件选择索引'),({'frame'},'预览起始帧'),({'image_load_cap'},'读取图片上限（0 为不限）'),({'mode'},'目录读取方式'),({'force_rate'},'读取帧率（0 为原帧率）')]:
            if effective & keys:
                return 'filesystem', label
    if key in ['value','value_1','widget_0','longest_side','max_side_length','long_side','target_long_side'] and effective & {'scale_to_length','longest_side','max_side_length','long_side','target_long_side'} and not re.search('TextEncode|Preprocessor',typ) and workflow['category']!='提示词辅助':
        return 'resolution', '输出最长边（像素）'
    if effective & {'width','height'} and (re.search('Empty.*Latent|ToVideo|ImageGen',typ) or any(re.search('Empty.*Latent|ToVideo',graph.nodes.get(t,{}).get('type','')) for t,_ in targets)):
        return 'resolution', '输出宽度（像素）' if 'width' in effective else '输出高度（像素）'
    if key in ['seed', 'noise_seed', 'random_seed', 'sampling_mode.seed'] or target_keys & {'seed', 'noise_seed', 'random_seed'}:
        return 'seed', '随机种子'
    if key == 'aspect_ratio' and typ == 'ResolutionSelector':
        return 'ratio', '画面比例'
    if key in ['duration', 'duration_seconds', 'seconds']:
        return 'duration', '音频片段时长（秒）' if 'Audio' in typ else '生成时长（秒）'
    if key in ['value', 'value_1', 'widget_0'] and (re.search(r'秒数|seconds|duration', title, re.I) or
        any(re.search(r'秒数|seconds|duration', graph.nodes.get(t, {}).get('title', ''), re.I) for t, _ in targets)):
        return 'duration', '生成时长（秒）'
    if effective & {'offset_seconds', 'start_time', 'start_seconds'}:
        return 'segment', '片段起点（分:秒）' if isinstance(f['value'], str) and ':' in f['value'] else '片段起点（秒）'
    if typ in ['VHS_LoadVideo', 'VHS_LoadVideoPath'] and key in ['skip_first_frames', 'frame_load_cap']:
        return 'segment', {'skip_first_frames': '跳过开头帧数', 'frame_load_cap': '读取帧数上限（0 为不限）'}[key]
    if key == 'scale_by' and re.search(r'放大|超分', workflow['name']):
        return 'upscale', '放大倍率'
    if typ in ['FlashVSRNode', 'FlashVSRNodeAdv'] and key == 'scale':
        return 'upscale', '放大倍率'
    if key in ['value', 'resolution'] and (workflow['category'] in ['图像增强与整理', '视频修复与扩展'] or re.search(r'放大|超分', workflow['name'])) and (typ == 'SeedVR2VideoUpscaler' or any(graph.nodes.get(t, {}).get('type') == 'SeedVR2VideoUpscaler' and k == 'resolution' for t, k in targets)):
        return 'upscale', '输出短边（像素）'
    if typ == 'TTP_Tile_image_size' and key in ['width_factor', 'height_factor']:
        return 'upscale', '宽度放大倍率' if key == 'width_factor' else '高度放大倍率'
    if typ == 'ImagePadForOutpaint' and key in ['left', 'right', 'top', 'bottom']:
        return 'outpaint', {'left':'向左扩展（像素）', 'right':'向右扩展（像素）', 'top':'向上扩展（像素）', 'bottom':'向下扩展（像素）'}[key]
    if re.search(r'ColorMatch|ColorAdjust|ImageColor', typ) and key in ['strength', 'brightness', 'contrast', 'saturation', 'gamma']:
        return 'color', {'strength':'调色强度', 'brightness':'亮度', 'contrast':'对比度', 'saturation':'饱和度', 'gamma':'伽马'}[key]
    if typ == 'QwenMultiangleCameraNode' and key in ['horizontal_angle', 'vertical_angle', 'zoom', 'azimuth', 'elevation', 'distance']:
        return 'camera', {'horizontal_angle':'水平视角', 'vertical_angle':'垂直视角', 'zoom':'镜头距离', 'azimuth':'水平视角', 'elevation':'垂直视角', 'distance':'镜头距离'}[key]
    if key == 'task_type' and typ == 'BerniniStudio':
        return 'task', '编辑任务'
    if typ in ['VHS_VideoCombine', 'CreateVideo'] and key in ['frame_rate', 'fps'] and workflow['category'] == '素材格式工具':
        return 'playback', '播放帧率'
    return None, None


def build():
    catalog = json.loads((ROOT / 'public/local-catalog.json').read_text(encoding='utf-8'))['workflows']
    current_path = ROOT / 'public/workflow-interfaces.json'
    curated = json.loads(current_path.read_text(encoding='utf-8'))['workflows'] if current_path.exists() else {}
    audit = {a['id']: a for a in json.loads((ROOT / 'verification/catalog-audit.json').read_text(encoding='utf-8')) if 'id' in a}
    interfaces, report = {}, []
    for w in catalog:
        raw_bytes = Path(audit[w['id']]['source']).read_bytes()
        graph = Graph(json.loads(raw_bytes.decode('utf-8-sig')))
        controls, hidden = [], []
        fields = []
        for original in w['fields']:
            f = dict(original)
            if f['key'].startswith('widget_'):
                bindings = widget_bindings(graph.nodes.get(f['nodeId'], {}))
                index = int(f['key'].split('_')[1])
                actual = next((k for k, (_, idx) in bindings.items() if idx == index), None)
                if actual:
                    f['key'] = actual
            fields.append(f)
        for nid, node in graph.nodes.items():
            for key, (val, idx) in widget_bindings(node).items():
                if not any(f['nodeId'] == nid and f['key'] == key for f in fields) and (
                    isinstance(val, (int, float, str, bool))):
                    fields.append({'id': nid + ':' + key, 'nodeId': nid, 'key': key,
                                   'label': key, 'node': node.get('title') or node['type'], 'value': val,
                                   'type': 'checkbox' if isinstance(val,bool) else 'number' if isinstance(val, (int, float)) else 'text',
                                   'linked': not graph.editable(nid, key), 'inactive': node.get('mode', 0) in [2, 4]})
        for f in fields:
            reason = 'internal-or-unconfirmed'
            if graph.editable(f['nodeId'], f['key']) and not f['inactive'] and not f['linked']:
                kind, label = semantic(graph, f, w)
                if kind and (f['type'] != 'number' or isinstance(f['value'], (int, float))):
                    controls.append({**f, 'kind': kind, 'label': label,
                                     'targets': [{'node': t, 'input': k} for t, k in graph.targets(f['nodeId'], f['key'])]})
                    continue
            else:
                reason = 'linked-inactive-or-outside-output-path'
            hidden.append({'id': f['id'], 'reason': reason})
        texts = []
        for t in w.get('texts', []):
            nid, key = t['id'].rsplit(':', 1)
            if not graph.editable(nid, key) or key == 'system_prompt':
                continue
            node = graph.nodes[nid]
            if re.search(r'Note|Show|Preview|Markdown|Display|Label', node['type'], re.I):
                continue
            if key in ['prompt', 'text', 'negative_prompt']:
                role = graph.text_role(nid, key)
                texts.append({**t, 'role': role})
        for nid, node in graph.nodes.items():
            if re.search(r'Note|Show|Preview|Markdown|Display|Label', node['type'], re.I):
                continue
            named = widget_bindings(node)
            for key in ['prompt', 'text', 'negative_prompt', 'positive', 'negative']:
                # Named widgets / actual input sockets prove the binding; never
                # export their original prompt text or guess an unnamed widget.
                if (key in named or any(inp['name'] == key and inp.get('widget') for inp in node.get('inputs', []))) and graph.editable(nid, key):
                    if not any(t['id'] == nid + ':' + key for t in texts):
                        texts.append({'id': nid + ':' + key, 'key': key, 'node': node.get('title') or node['type'],
                                      'label': '描述', 'role': graph.text_role(nid, key)})
        # A prompt may be supplied by a primitive upstream, absent from the discovery catalog.
        for nid, node in graph.nodes.items():
            if node['type'] in ['PrimitiveStringMultiline', 'PrimitiveString'] and graph.editable(nid, 'value'):
                targets = graph.targets(nid, 'value')
                if any(k in ['prompt', 'text', 'positive', 'negative_prompt'] for _, k in targets):
                    texts.append({'id': nid + ':value', 'key': 'value', 'node': node.get('title') or '描述',
                                  'label': '描述', 'role': graph.text_role(nid, 'value')})
        media = []
        for slot in w['media']:
            if slot['id'] not in graph.reachable or graph.nodes[slot['id']].get('mode', 0) in [2, 4]:
                continue
            node = graph.nodes[slot['id']]
            title = node.get('title', '')
            role = graph.media_role(slot['id'], w, slot['label'])
            if re.search(r'首帧|first.?frame|start.?image', title, re.I):
                role = '首帧'
            elif re.search(r'尾帧|last.?frame|end.?image', title, re.I):
                role = '尾帧'
            elif re.search(r'背景|background', title, re.I):
                role = '背景参考图' if slot['kind'] == 'image' else '背景素材'
            elif re.search(r'人脸|face', title, re.I):
                role = '人脸参考图'
            elif re.search(r'body', title, re.I):
                role = '身体参考图'
            elif slot['kind'] == 'image' and re.search(r'人物替换|换人|角色', w['name']):
                role = '角色参考图'
            elif slot['kind'] == 'image' and re.search(r'局部重绘|图像标记|去背景', w['name']):
                role = '原图（含蒙版）' if any(k == 'mask' for _, k in graph.targets(slot['id'], 'value')) else '待编辑原图'
            elif slot['kind'] == 'video' and w['category'] in ['动作迁移与舞蹈', '数字人与对口型']:
                role = '动作参考视频'
            media.append({**slot, 'label': role})
        # Primary footage/start frame comes before its reference/end frame.
        media.sort(key=lambda s: 0 if s['label'] in ['首帧', '原视频', '待编辑原图', '人物原图', '待调色原图', '原图（含蒙版）'] else 1)
        # Individual slots are never merged just because their media kind matches.
        counts = Counter(x['label'] for x in media)
        seq = Counter()
        for slot in media:
            seq[slot['label']] += 1
            if counts[slot['label']] > 1:
                slot['label'] += f' {seq[slot["label"]]}'
        label_counts = Counter(c['label'] for c in controls if c['kind'] != 'seed')
        seq = Counter()
        for c in controls:
            label = c['label']
            if c['kind'] == 'seed' or label_counts[label] <= 1:
                continue
            seq[label] += 1
            related = next((s for s in media if s['id'] == c['nodeId'] or any(dst == c['nodeId'] for dst, _, _ in graph.out[s['id']])), None)
            c['label'] = (related['label'] + ' · ' if related else f'分支 {seq[label]} · ') + label
        seeds = [c for c in controls if c['kind'] == 'seed']
        seed_roles = Counter()
        for seed in seeds:
            typ = graph.nodes[seed['nodeId']]['type']
            seed['label'] = '提示词种子' if re.search(r'LLM|Vision|Multimodal|TextGenerate', typ, re.I) else '随机种子'
            seed_roles[seed['label']] += 1
        seq = Counter()
        for seed in seeds:
            role = seed['label']
            seq[role] += 1
            if seed_roles[role] > 1:
                seed['label'] += f' {seq[role]}'
            seed['min'], seed['max'], seed['step'] = 0, 9007199254740991, 1
        camera_nodes = list(dict.fromkeys(c['nodeId'] for c in controls if c['kind'] == 'camera'))
        if len(camera_nodes) > 1:
            for c in controls:
                if c['kind'] == 'camera':
                    c['label'] = f'视角 {camera_nodes.index(c["nodeId"]) + 1} · ' + c['label']
        texts.sort(key=lambda t: (t['role'] != 'prompt', t['id'].startswith('sub'),
                                 not bool(re.search(r'Prompt Text|Manual|正向|正面|描述|PrimitiveString', t['node'], re.I))))
        from workflow_customization import customize
        controls, texts, media, metadata = customize(w, graph, controls, texts, media, source_hash=hashlib.sha256(raw_bytes).hexdigest())
        config = {'sourceHash': hashlib.sha256(raw_bytes).hexdigest(), 'controls': controls,
                  'texts': texts, 'media': media, 'schemaVersion': 2, **metadata}
        # Published forms keep their reviewed labels, field order and bindings
        # across rebuilds while the exact source is unchanged. This also covers
        # generic compiled forms; rebuilding must not relabel a background slot
        # as a second character reference. Refresh only explicit reviewed fixes.
        if w['id'] in curated:
            if curated[w['id']]['sourceHash'] != config['sourceHash']:
                raise RuntimeError(f"{w['id']}: source changed; review connected controls before rebuilding")
            from workflow_customization import refresh_curated_controls
            config = refresh_curated_controls(w, curated[w['id']], config)
            controls, texts, media = config['controls'], config['texts'], config['media']
        interfaces[w['id']] = config
        report.append({'id': w['id'], 'name': w['name'], 'sourceHash': config['sourceHash'],
                       'controls': [{k: c[k] for k in ['id', 'kind', 'label', 'targets']} for c in controls],
                       'texts': texts, 'media': media, 'hidden': hidden,
                       'reachableNodes': len(graph.reachable), **{key: config[key] for key in metadata if key in config}})
    # Exact ResolutionSelector strings come from the real adapter, supplemented
    # by defaults observed on the same node type. Never submit bare guessed ratios.
    ratio_values = {c['value'] for cfg in interfaces.values() for c in cfg['controls'] if c['kind'] == 'ratio'}
    tree = ast.parse((ROOT / 'adapters.py').read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            try:
                values = ast.literal_eval(node)
            except (ValueError, TypeError):
                continue
            if values and all(isinstance(k, str) and re.fullmatch(r'\d+:\d+', k) and isinstance(v, str) and v.startswith(k + ' (') for k, v in values.items()):
                ratio_values.update(values.values())
    ratio_values = sorted(ratio_values)
    for workflow_id, cfg in interfaces.items():
        for c in cfg['controls']:
            if c['kind'] == 'ratio' and not c.get('options'):
                previous = curated.get(workflow_id, {})
                old_control = next((item for item in previous.get('controls', [])
                                    if item['id'] == c['id'] and item['kind'] == 'ratio'), None)
                # Keep the reviewed per-workflow menu if the source graph is
                # unchanged; newly discovered values must not silently widen it.
                if previous.get('sourceHash') == cfg['sourceHash'] and old_control and old_control.get('options'):
                    c['options'] = old_control['options']
                else:
                    c['options'] = ratio_values
    (ROOT / 'public/workflow-interfaces.json').write_text(json.dumps({'version': 1, 'workflows': interfaces}, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'verification/workflow-interface-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'workflows': len(interfaces), 'controls': sum(len(c['controls']) for c in interfaces.values()),
                      'byKind': dict(Counter(c['kind'] for cfg in interfaces.values() for c in cfg['controls'])),
                      'media': sum(len(c['media']) for c in interfaces.values()), 'texts': sum(len(c['texts']) for c in interfaces.values())}, ensure_ascii=False))


if __name__ == '__main__':
    build()
