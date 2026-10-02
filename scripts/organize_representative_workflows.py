"""Prepare real ComfyUI UI graphs for owner review; never queue execution."""
import copy
import hashlib
import json
import re
import uuid
import zipfile
from pathlib import Path

from build_workflow_interfaces import widget_bindings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '代表工作流-ComfyUI审查版'
SELECTION = [1, 79, 2, 92, 58, 52, 56, 67, 0, 60, 103, 34, 136]
EXTRAS = {
    79: [('35', 'value', '套图数量')],
    92: [('47', 'index', '清理掩膜分支'), ('82', 'denoise', '细节重绘幅度'), ('79', 'megapixels', '输出像素总量')],
    0: [('261', 'reference_image_strength_1', '角色参考强度'), ('261', 'pose_strength_1', '动作参考强度'), ('261', 'video_frame_offset_1', '动作片段起始帧'), ('261', 'length', '单段生成帧数')],
    60: [('363', 'value', '输出最长边')],
    103: [('182', 'end_time', '音频片段终点')],
    67: [('305', 'switch', '输出分支选择')],
    136: [('70', 'value', '本地素材目录'), ('62', 'value', '视频选择索引'), ('61', 'mode', '批量读取方式'), ('61', 'pattern', '文件匹配规则')],
}
SPECIAL = {
    1: '长提示词、中文文字生成、画幅与种子；反向提示词为可选输入。',
    79: '一张参考图衍生多张写真；套图数量已同步连接指令条数与拆分上限；提示词与图像生成分别有种子。',
    2: '当前两路图像输入，需区分待编辑原图与修改参考；其余停用图像不能误当必填。',
    92: '掩膜分支选择、清理区域、放大倍率和细节重绘幅度；不同清理路径需要不同交互。',
    58: '视频时长、画幅、种子；包含音视频生成链，需分别呈现播放和音频状态。',
    52: '三路默认参考图及模型支持的可选图像端口、手动描述与视觉 API 辅助；音频加载分支当前停用，不应默认要求上传。',
    56: '首尾帧角色固定、尺寸对齐、时长和种子；两张图片分别连入真实首尾帧端口。',
    67: '原视频、参考图、片段起点、时长、编辑指令及输出分支；保留视频原音频链。',
    0: '角色图与动作视频不可互换；角色/动作参考强度、起始帧、单段长度与可选续段。',
    60: '源视频片段、目标最长边、增强描述与种子；不把细节修复宣传成时长延长。',
    103: '人物图、驱动音频、裁剪起止、分段续生成及各段种子；续段数和批次数有关联，不能独立随意调整。',
    34: '文字润色与图片反推两条分支；自定义模板、各分支种子及 API 配置；结果是文本。',
    136: '本地目录、文件匹配、索引、读取方式、片段限制与播放帧率；默认仅预览，不保存文件。',
}
TEXT_LABELS = {
    (1, '459', 'prompt'): '创作提示词', (2, '518', 'prompt'): '图像修改指令',
    (56, '135', 'prompt'): '动作与过渡描述', (0, '577', 'prompt'): '动作与角色描述',
    (79, '19', 'prompt'): '写真补充要求', (103, '6', 'text'): '人物表演描述',
    (92, '64', 'text'): '细节修复描述', (92, '22', 'value'): '待清理区域描述',
    (34, '1479', 'text'): '文字分支 · 用户描述', (34, '1520', 'text'): '图片分支 · 用户描述',
    (34, '1518', 'text'): '图片分支 · 扩写指令', (34, '1488', 'text'): '文字分支 · 扩写指令',
    (34, '1514', 'prompt'): '文字分支 · 补充要求', (34, '1525', 'prompt'): '图片分支 · 补充要求',
}
INTERNAL_TEXT = {79: {'31', '32', '34'}, 34: {'1492', '1522'}}


def links(graph):
    for l in graph.get('links', []):
        yield ((l['id'], l['origin_id'], l['origin_slot'], l['target_id'], l['target_slot'], l['type'])
               if isinstance(l, dict) else tuple(l))


def append_link(graph, src, os, dst, ts, typ):
    lid = max([x[0] for x in links(graph)] + [graph.get('last_link_id', 0), graph.get('state', {}).get('lastLinkId', 0)]) + 1
    if 'state' in graph:
        graph['links'].append(dict(id=lid, origin_id=src, origin_slot=os, target_id=dst, target_slot=ts, type=typ))
        graph['state']['lastLinkId'] = lid
    else:
        graph['links'].append([lid, src, os, dst, ts, typ])
        graph['last_link_id'] = lid
    return lid


def strip_secrets(obj):
    if isinstance(obj, dict):
        result = {k: ('' if re.fullmatch(r'api[_-]?key|access[_-]?token|authorization', k, re.I) else strip_secrets(v)) for k, v in obj.items()}
        # Positional UI widgets can duplicate a named API credential whose
        # provider does not use an sk- prefix. Redact both representations.
        named=obj.get('widgets_values_named',{})
        secrets={v for k,v in named.items() if re.fullmatch(r'api[_-]?key|access[_-]?token|authorization',k,re.I) and isinstance(v,str) and v} if isinstance(named,dict) else set()
        if secrets and isinstance(obj.get('widgets_values'),list):
            result['widgets_values']=['' if isinstance(v,str) and v in secrets else strip_secrets(v) for v in obj['widgets_values']]
        return result
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    if isinstance(obj, str):
        return re.sub(r'sk-[A-Za-z0-9_-]{12,}', '', obj)
    return obj


def value_of(node, key):
    b = widget_bindings(node)
    if key in b:
        return b[key][0]
    if key == 'value' and node['type'] == 'PrimitiveNode':
        return node['widgets_values'][0]
    if key in ['seed', 'noise_seed'] and node['type'] in ['Seed (rgthree)', 'RandomNoise']:
        return node['widgets_values'][0]
    raise ValueError(f'No proven widget binding: {node["id"]}:{key}')


def stage(node, user_ids):
    if node.get('title','').startswith('API ·'):
        return 1
    if str(node['id']) in user_ids:
        return 0
    typ = node['type']
    if node.get('mode', 0) in [2, 4] or re.search(r'Note|Label', typ):
        return 7
    if re.search(r'Save|Preview|ShowText|showAnything|VideoCombine', typ):
        return 6
    if re.search(r'Decode|CreateVideo|Stitch|Concat|Assy', typ):
        return 5
    if re.search(r'Loader|Provider|Attention|Patch|Cache|SigmaShift|Lora|Spectrum|SemanticBridgeConfig', typ):
        return 3
    if re.search(r'Sampler|Scheduler|Guider|Noise', typ):
        return 4
    return 2


def layout(graph, user_ids, root=False):
    titles = ['01 · 用户输入与常用参数', '02 · API 连接配置', '03 · 预处理与条件', '04 · 模型与内部配置', '05 · 生成与采样', '06 · 解码与合成', '07 · 输出与对比', '08 · 停用分支与原说明']
    colours = ['#355c49', '#4b536b', '#354b62', '#49465a', '#635039', '#415462', '#385c59', '#44444b']
    buckets = [[] for _ in titles]
    byid = {n['id']: n for n in graph['nodes']}
    incoming = {nid: set() for nid in byid}
    for _, src, _, dst, _, _ in links(graph):
        if src in byid and dst in byid:
            incoming[dst].add(src)
    # Topological order within each section, with stable cycle fallback.
    todo, ordered = set(byid), []
    while todo:
        ready = sorted(nid for nid in todo if not incoming[nid].intersection(todo))
        if not ready:
            ready = [min(todo)]
        ordered.extend(ready)
        todo.difference_update(ready)
    for nid in ordered:
        n = byid[nid]
        buckets[stage(n, user_ids)].append(n)
    if root:
        rank = {x: i for i, x in enumerate(user_ids)}
        buckets[0].sort(key=lambda n: rank[str(n['id'])])
    gid = max([g.get('id', 0) or 0 for g in graph.get('groups', [])] + [0])
    graph['groups'] = []
    for si, ns in enumerate(buckets):
        if not ns:
            continue
        x0 = 80 + si * 1060
        heights = [160, 160]
        for i, n in enumerate(ns):
            col = 0 if si == 7 else min(range(2), key=lambda c: heights[c])
            size = n.get('size', [400, 200])
            if isinstance(size, dict):
                size = [size.get('0', 400), size.get('1', 200)]
            width = 450
            min_h = max(90, 55 + 22 * max(len(n.get('inputs', [])), len(n.get('outputs', []))))
            if re.fullmatch(r'[0-9a-f-]{36}', n['type']):
                # Native subgraph instances grow after boundary widgets restore.
                min_h = max(min_h, 100 + 28 * len(n.get('inputs', [])))
            height = max(min_h, min(float(size[1]), 440))
            if si == 6:
                # Output extensions may add text/video widgets after configure.
                height = max(height, 440)
            if si == 7:
                n.setdefault('flags', {})['collapsed'] = True
                height = 50
            else:
                n.setdefault('flags', {})['collapsed'] = False
            n['pos'] = [x0 + 20 + col * 490, heights[col]]
            n['size'] = [width, height]
            n['order'] = ordered.index(n['id'])
            heights[col] += height + 70
        gid += 1
        graph['groups'].append({'id': gid, 'title': titles[si], 'bounding': [x0, 80, 1000, max(heights) - 70], 'color': colours[si], 'font_size': 26, 'flags': {}})
    if 'state' in graph:
        graph['state']['lastGroupId'] = gid
        graph['inputNode']['bounding'] = [-250, 80, 240, max(150, len(graph.get('inputs', [])) * 26 + 60)]
        graph['outputNode']['bounding'] = [6600, 80, 240, max(100, len(graph.get('outputs', [])) * 26 + 60)]
        for i, port in enumerate(graph.get('inputs', [])):
            port['pos'] = [-10, 130 + i * 26]
        for i, port in enumerate(graph.get('outputs', [])):
            port['pos'] = [6600, 130 + i * 26]
    graph.setdefault('extra', {}).pop('reroutes', None)
    graph['extra']['ds'] = {'scale': 0.8, 'offset': [-50, 0]}


def prepare(idx, serial, catalog, cfg):
    source = ROOT / f'private/research/card-20260923/graph-{idx:03}.json'
    original = json.loads(source.read_text(encoding='utf-8-sig'))
    graph = strip_secrets(copy.deepcopy(original))
    nodes = {str(n['id']): n for n in graph['nodes']}
    user_ids, parameters, added = [], [], []
    def user(nid):
        if nid not in user_ids:
            user_ids.append(nid)
    for media in cfg['media']:
        if idx == 136:
            # These are linked filesystem readers, not two upload slots.
            continue
        if media['id'] in nodes:
            user(media['id'])
            nodes[media['id']]['title'] = media['label']
        elif media.get('sourceNodeId') in nodes:
            nid=media['sourceNodeId'];user(nid)
            nodes[nid]['title']=media['label']+' · 默认停用，使用前启用'
    if idx == 136:
        nodes['61']['title'] = '目录文件选择器 · 承接目录与索引'
        nodes['68']['title'] = '视频帧与音频读取 · 自动承接文件路径'
    rows = [(m['nodeId'], m['key'], x['label']) for x in cfg['controls'] for m in x.get('members',[x])]
    for p in cfg.get('apiProfiles',[]):
        for role, title in [('baseUrl','Base URL'),('model','Model 名称'),('apiKey','API key（自行填写）')]:
            bind=p['bindings'][role];node=nodes.get(bind['node'])
            if not node:continue
            socket=next((i for i in node.get('inputs',[]) if i['name']==bind['input']),{})
            if socket.get('link') is not None:
                credential_source=next((src for lid,src,_,_,_,_ in links(graph) if lid==socket['link']),None)
                if credential_source in [n['id'] for n in graph['nodes']]:
                    sn=nodes[str(credential_source)];sn['widgets_values']=[''];sn['widgets_values_named']={'prompt':''};rows.append((str(credential_source),'prompt','API · '+p['label']+' · '+title))
            else:rows.append((bind['node'],bind['input'],'API · '+p['label']+' · '+title))
    for t in cfg['texts']:
        nid = t.get('nodeId', t['id'].rsplit(':', 1)[0])
        if idx == 0 and nid == '579':  # This node contains the API credential, not a creative prompt.
            continue
        if nid in INTERNAL_TEXT.get(idx, set()):
            nodes[nid]['title'] = '固定指令模板 · 通常不改'
            continue
        text_label = t.get('label') or ('反向提示词' if t.get('role') == 'negative' or 'negative' in t['key'] else TEXT_LABELS.get((idx, nid, t['key']), '创作描述'))
        rows.insert(0, (nid, t['key'], text_label))
    rows += EXTRAS.get(idx, [])
    seen = set()
    for nid, key, label in rows:
        if (nid, key) in seen:
            continue
        seen.add((nid, key))
        if nid.startswith('sub'):
            # Expose a proven unlinked subgraph text input via a standard boundary.
            prefix, inner_id = nid.split('/')
            definition = graph.get('definitions', {}).get('subgraphs', [])[int(prefix[3:])]
            inner = next(n for n in definition['nodes'] if str(n['id']) == inner_id)
            value = value_of(inner, key)
            slot = next(i for i, p in enumerate(inner['inputs']) if p.get('widget', {}).get('name') == key or p['name'] == key)
            assert inner['inputs'][slot].get('link') is None
            typ = inner['inputs'][slot].get('type', 'STRING')
            outer = next(n for n in graph['nodes'] if n['type'] == definition['id'] and n.get('mode', 0) == 0)
            new_name = f'review_{inner_id}_{key}'
            new_slot = len(definition['inputs'])
            inner_lid = append_link(definition, -10, new_slot, inner['id'], slot, typ)
            inner['inputs'][slot]['link'] = inner_lid
            inner['inputs'][slot]['widget'] = {'name': key}
            definition['inputs'].append({'id': str(uuid.uuid4()), 'name': new_name, 'type': typ, 'linkIds': [inner_lid], 'label': label, 'pos': [-10, 100]})
            outer['inputs'].append({'name': new_name, 'type': typ, 'widget': {'name': new_name}, 'link': None})
            outer['widgets_values'].append(value)
            outer.setdefault('widgets_values_named', {})[new_name] = value
            # Do not add a partial named map to an existing positional-only node.
            outer.pop('widgets_values_named', None)
            nid, key = str(outer['id']), new_name
        n = nodes[nid]
        value = value_of(n, key)
        standalone = re.search(r'^(PrimitiveString|PrimitiveInt|PrimitiveFloat|PrimitiveBoolean|Text Multiline|Text Multiline|CR Prompt Text|CLIPTextEncode|Seed \(rgthree\)|RandomNoise|ImpactInt|easy int|PrimitiveNode)', n['type'])
        if standalone:
            user(nid)
            n['title'] = label if nid not in [x['id'] for x in cfg['media']] else n.get('title', label)
            parameters.append({'nodeId': nid, 'key': key, 'label': label, 'default': value, 'source': [nid, key], 'native': True})
            continue
        slot = next((i for i, p in enumerate(n.get('inputs', [])) if p.get('widget', {}).get('name') == key or p['name'] == key), None)
        if slot is None or n['inputs'][slot].get('link') is not None:
            raise ValueError(f'Cannot promote bound widget {idx}:{nid}:{key}')
        port = n['inputs'][slot]
        typ = port.get('type', 'STRING' if isinstance(value, str) else 'BOOLEAN' if isinstance(value, bool) else 'INT' if isinstance(value, int) else 'FLOAT')
        port['widget'] = {'name': key}
        new_id = max([x['id'] for x in graph['nodes']] + [graph.get('last_node_id', 0)]) + 1
        lid = append_link(graph, new_id, 0, n['id'], slot, typ)
        port['link'] = lid
        control_mode = 'fixed'
        if key in ['seed', 'noise_seed']:
            control_mode = n.get('widgets_values_named', {}).get('control_after_generate', 'fixed')
            vals = n.get('widgets_values', [])
            if isinstance(vals, list):
                for vi, v in enumerate(vals[:-1]):
                    if v == value and vals[vi+1] in ['fixed', 'randomize', 'increment', 'decrement']:
                        control_mode = vals[vi+1]
                        break
        primitive_type = {'STRING': 'PrimitiveStringMultiline', 'INT': 'PrimitiveInt', 'FLOAT': 'PrimitiveFloat', 'BOOLEAN': 'PrimitiveBoolean'}.get(typ, 'PrimitiveNode')
        has_control = typ == 'INT' or primitive_type == 'PrimitiveNode'
        prim = {'id': new_id, 'type': primitive_type, 'title': label, 'pos': [0, 0], 'size': [450, 120 if typ != 'STRING' else 240], 'flags': {}, 'mode': 0, 'order': 0, 'inputs': [{'name': 'value', 'type': typ, 'widget': {'name': 'value'}, 'link': None}] if primitive_type != 'PrimitiveNode' else [], 'outputs': [{'name': typ, 'type': typ, 'links': [lid], 'slot_index': 0}], 'properties': {'Run widget replace on values': False} if primitive_type == 'PrimitiveNode' else {}, 'widgets_values': [value] + ([control_mode] if has_control else []), 'widgets_values_named': {'value': value}}
        if primitive_type == 'PrimitiveNode':
            prim['outputs'][0]['widget'] = {'name': key}
        if has_control:
            prim['widgets_values_named']['control_after_generate'] = control_mode
        graph['nodes'].append(prim)
        graph['last_node_id'] = new_id
        nodes[str(new_id)] = prim
        user(str(new_id))
        added.append({'id': new_id, 'target': [n['id'], slot], 'key': key, 'value': value})
        parameters.append({'nodeId': str(new_id), 'key': 'value', 'label': label, 'default': value, 'source': [nid, key], 'native': False})
    # Merge same-stage native seed sources by redirecting their outgoing links.
    # Original seed widgets remain parked for recovery but have no authority.
    rewired=set()
    for c in cfg['controls']:
        members=c.get('members',[])
        if len(members)<2:continue
        ps=[next(p for p in parameters if p['source']==[m['nodeId'],m['key']]) for m in members]
        primary=nodes[ps[0]['nodeId']]
        for p in ps[1:]:
            old=nodes[p['nodeId']]
            for link in graph['links']:
                src=link.get('origin_id') if isinstance(link,dict) else link[1]
                if src!=old['id']:continue
                lid=link['id'] if isinstance(link,dict) else link[0]
                if isinstance(link,dict):link['origin_id']=primary['id'];link['origin_slot']=0
                else:link[1]=primary['id'];link[2]=0
                primary['outputs'][0].setdefault('links',[]).append(lid);rewired.add(lid)
            for out in old.get('outputs',[]):out['links']=[]
            old['title']='内部旧种子 · 已由统一种子接管'
            if p['nodeId'] in user_ids:user_ids.remove(p['nodeId'])
            parameters.remove(p)
    layout(graph, user_ids, root=True)
    for definition in graph.get('definitions', {}).get('subgraphs', []):
        layout(definition, [], root=False)
    name = f'{serial:02d}-{catalog["category"]}-{catalog["name"]}.json'
    graph.setdefault('extra', {})['ownerReview'] = {'source': source.name, 'sourceHash': hashlib.sha256(source.read_bytes()).hexdigest(), 'parameters': parameters, 'note': '节点排版与参数入口整理；未运行模型；API 密钥已清空。'}
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    assert {l for l in links(original) if l[0] not in rewired}.issubset(set(links(graph)))
    for n in original['nodes']:
        revised = nodes[str(n['id'])]
        assert n.get('mode', 0) == revised.get('mode', 0)
        assert n['type'] == revised['type']
        old_values = strip_secrets(n.get('widgets_values', []))
        new_values = revised.get('widgets_values', [])
        if idx==0 and str(n['id'])=='579':continue  # Linked API credential is deliberately cleared.
        assert old_values == new_values[:len(old_values)] if isinstance(old_values, list) else old_values == new_values
    for a in added:
        assert nodes[str(a['id'])]['widgets_values'][0] == a['value']
    for ns in [graph['nodes']] + [d['nodes'] for d in graph.get('definitions', {}).get('subgraphs', [])]:
        for i, a in enumerate(ns):
            aw, ah = a['size']; ah = 50 if a.get('flags', {}).get('collapsed') else ah
            for b in ns[i+1:]:
                bw, bh = b['size']; bh = 50 if b.get('flags', {}).get('collapsed') else bh
                assert not (a['pos'][0] < b['pos'][0]+bw and b['pos'][0] < a['pos'][0]+aw and a['pos'][1] < b['pos'][1]+bh and b['pos'][1] < a['pos'][1]+ah)
    return {'number': serial, 'id': catalog['id'], 'title': catalog['name'], 'category': catalog['category'], 'file': name, 'parameters': parameters, 'userNodes': user_ids, 'special': SPECIAL[idx], 'apiProfiles': cfg.get('apiProfiles',[]), 'notes': cfg.get('notes',[]), 'annotation': cfg.get('annotation'), 'sourceHash': hashlib.sha256(source.read_bytes()).hexdigest(), 'originalNodes': len(original['nodes']), 'addedParameterNodes': len(added), 'nodes': len(graph['nodes']), 'source': str(source.relative_to(ROOT))}


def main():
    catalogs = {x['id']: x for x in json.loads((ROOT / 'public/local-catalog.json').read_text(encoding='utf-8'))['workflows']}
    configs = json.loads((ROOT / 'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']
    entries = [prepare(idx, i+1, catalogs[f'local-card-{idx}'], configs[f'local-card-{idx}']) for i, idx in enumerate(SELECTION)]
    (OUT / '审查索引.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = ['# ComfyUI 代表工作流逐项审查', '', '把编号 JSON 拖入 ComfyUI。左侧绿色区域为用户输入与常用参数；随后依次为预处理、模型、生成、解码、输出。停用分支与原说明保留在最右侧；子图内部也已排版。', '', '原始文件保留。审查副本用 ComfyUI 原生值节点集中参数；同一阶段的多个种子已改成一个入口并连接所有对应节点。数字人分段和提示词两分支保留独立种子。API 配置在第二组，Base URL 和 Model 沿用原平台值，密钥清空后须自行配置，平台托管密钥不会导出。需安装各工作流原有的自定义节点和模型。本次没有调用生成模型。', '', '本地审查入口：http://127.0.0.1:8771/review （真实 ComfyUI 前端，仅结构审查；自定义节点定义由原文件重建，不提供执行）。', '', '原生值节点依据：https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_primitive.py', '']
    for e in entries:
        rows += [f'## {e["number"]:02d} · {e["category"]}', '', f'文件：[{e["file"]}]({e["file"]})', '', '集中参数：' + '、'.join(dict.fromkeys(x['label'] for x in e['parameters'])), '', '特殊要求：' + e['special'], '', *(['API：'+ '；'.join(p['label']+' / '+p['baseUrl']+' / '+p['model'] for p in e['apiProfiles']), '密钥入口已集中，导出文件不含平台密钥。',''] if e['apiProfiles'] else []), *(e['notes']+[''] if e['notes'] else []), '审查结论：待用户逐项确认。', '']
    rows += ['## 网站改进顺序', '', '先逐项确认输入角色、特殊控制、分支关系和输出类型，再修改对应网站表单。当前新增识别的重点是套图条数、清理掩膜路径和重绘幅度、动作迁移的参考强度与帧数、S2V 音频终点，以及批量工具的目录/索引。不能直接复制所有技术参数到网站。', '']
    (OUT / 'README.md').write_text('\n'.join(rows), encoding='utf-8')
    with zipfile.ZipFile(ROOT / '代表工作流-ComfyUI审查版.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for p in OUT.glob('*'):
            if p.is_file():
                z.write(p, OUT.name + '/' + p.name)
    print(json.dumps({'workflows': len(entries), 'parameterNodesAdded': sum(e['addedParameterNodes'] for e in entries), 'output': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
