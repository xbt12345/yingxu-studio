"""Compile the owner's saved graphs using the card's actual node definitions.

No /prompt request is sent. Unresolved inputs fail closed, with per-file evidence.
Raw graphs and credentials remain private; only sanitized API templates ship.
"""
import copy
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from build_workflow_interfaces import Graph, edges, widget_bindings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / 'private/research/card-20261004'


class CompileError(ValueError):
    pass


class Compiler:
    def __init__(self, raw, schemas):
        self.raw, self.schemas = copy.deepcopy(raw), schemas
        self.normalized = []
        self.migrate_renamed_nodes(self.raw)
        raw = self.raw
        self.defs = {d['id']: (i, d) for i, d in enumerate(raw.get('definitions', {}).get('subgraphs', []))}
        self.nodes, self.contexts, self.links, self.link_ids, self.parents = {}, {}, {}, {}, {}
        self.aliases, self.target_map = defaultdict(list), defaultdict(list)
        self.compiled, self.busy = {}, set()
        self.add_scope(raw, '', None, None)

    def migrate_renamed_nodes(self, graph):
        # Upstream ComfyUI-multimodal migrated these two classes without changing
        # named sockets or output ordering. Never remap widgets by new position:
        # prompt/system_prompt swapped positions in the new VisionChat UI.
        renames = {'MultimodalChat': 'VisionChat', 'MultimodalQwen38Loader': 'Qwen38VLLoader'}
        for node in graph.get('nodes', []):
            old = node.get('type')
            new = renames.get(old)
            if new and old not in self.schemas and new in self.schemas:
                named = {key: value for key, (value, _) in widget_bindings(node).items()}
                if node.get('widgets_values') and not named:
                    raise CompileError(f'Cannot safely migrate named widgets of {node["id"]} ({old})')
                if old == 'MultimodalChat' and named.get('thinking_mode') in ('backend_default', 'thinking', 'instruct'):
                    before = named['thinking_mode']
                    named['thinking_mode'] = {'backend_default': 'auto', 'thinking': 'medium', 'instruct': 'off'}[before]
                    self.normalized.append({'node': str(node['id']), 'input': 'thinking_mode', 'reason': 'upstream legacy reasoning choice mapping', 'from': before, 'to': named['thinking_mode']})
                node['widgets_values_named'] = named
                node['type'] = new
                for socket in node.get('inputs', []) + node.get('outputs', []):
                    if socket.get('type') == 'MLLM_BACKEND':
                        socket['type'] = 'VISION_LLM_BACKEND'
                self.normalized.append({'node': str(node['id']), 'input': 'class_type', 'reason': 'upstream compatible node-class rename; preserve named widgets and output slots', 'from': old, 'to': new})
        for definition in graph.get('definitions', {}).get('subgraphs', []):
            self.migrate_renamed_nodes(definition)

    def add_scope(self, graph, prefix, parent, instance):
        self.parents[prefix] = (parent, instance)
        scope_nodes = {str(n['id']): n for n in graph.get('nodes', [])}
        self.contexts[prefix] = scope_nodes
        self.links[prefix] = {(str(dst), int(slot)): (str(src), int(out)) for src, out, dst, slot in edges(graph)}
        self.link_ids[prefix] = {str(link['id'] if isinstance(link, dict) else link[0]):
                                (str(link['origin_id']), int(link['origin_slot'])) if isinstance(link, dict) else (str(link[1]), int(link[2]))
                                for link in graph.get('links', [])}
        for key, node in scope_nodes.items():
            nid = prefix + key
            self.nodes[nid] = (prefix, node)
            alias = nid if not prefix else f"sub{self.defs[self.nodes[instance][1]['type']][0]}/{key}"
            self.aliases[alias].append(nid)
            if node['type'] in self.defs:
                _, definition = self.defs[node['type']]
                self.add_scope(definition, nid + ':', prefix, nid)

    def bindings(self, node):
        out = {key: value for key, (value, _) in widget_bindings(node).items()}
        if out:
            return self.migrated_widgets(node, out)
        # Positional widgets are matched to saved widget sockets, including the
        # extra seed mode and upload buttons that never become API inputs.
        vals = node.get('widgets_values', [])
        if not isinstance(vals, list):
            return {}
        names = [x.get('widget', {}).get('name') for x in node.get('inputs', []) if x.get('widget')]
        meaningful = [x for x in vals if not (isinstance(x, str) and x in ('fixed', 'randomize', 'increment', 'decrement'))]
        if len(meaningful) >= len(names) and names:
            return self.migrated_widgets(node, dict(zip(names, meaningful)))
        return {}

    def migrated_widgets(self, node, values):
        # Older KJ guide widgets serialized an index (0), while current Comfy
        # requires a string guide count with dotted dynamic children. Migrate
        # only the unambiguous one-guide shape, never guess arbitrary graphs.
        if node['type'] == 'LTXVAddGuideMulti' and values.get('num_guides') == 0:
            images = [inp['name'] for inp in node.get('inputs', [])
                      if re.fullmatch(r'image_\d+', inp['name']) and inp.get('link') is not None]
            if images == ['image_1']:
                values['num_guides'] = '1'
        return values

    def remember(self, key, nid, field):
        item = {'node': nid, 'input': field}
        if item not in self.target_map[key]:
            self.target_map[key].append(item)

    def input_value(self, nid, key):
        prefix, node = self.nodes[nid]
        index = next((i for i, inp in enumerate(node.get('inputs', [])) if inp['name'] == key), None)
        if index is None and node['type'] == 'LTXVAddGuideMulti' and key.startswith('num_guides.'):
            legacy_key = key.split('.', 1)[1]
            index = next((i for i, inp in enumerate(node.get('inputs', [])) if inp['name'] == legacy_key), None)
        edge = self.edge(prefix, node, index)
        if edge:
            src, slot = edge
            if src == '-10':
                parent, instance = self.parents[prefix]
                if not instance:
                    raise CompileError(f'Boundary input without an instance: {nid}.{key}')
                outer = self.nodes[instance][1]
                name = outer.get('inputs', [])[slot]['name']
                value, origins = self.input_value(instance, name)
                return value, origins + [instance + ':' + name]
            return self.source(prefix + src, slot), []
        vals = self.bindings(node)
        if key in vals:
            return vals[key], [nid + ':' + key]
        raise KeyError(key)

    def edge(self, prefix, node, index):
        if index is None:
            return None
        inp = node.get('inputs', [])[index]
        if inp.get('link') is not None:
            return self.link_ids[prefix].get(str(inp['link']))
        return None

    def source(self, nid, slot):
        if nid.endswith(':-10'):
            prefix = nid[:-3]
            parent, instance = self.parents[prefix]
            name = self.nodes[instance][1].get('inputs', [])[slot]['name']
            return self.input_value(instance, name)[0]
        if nid not in self.nodes:
            raise CompileError(f'Missing source node {nid}')
        prefix, node = self.nodes[nid]
        typ = node['type']
        if typ in self.defs and node.get('mode', 0) == 4:
            output_type = node.get('outputs', [])[slot].get('type')
            candidates = [edge for (key, i), edge in self.links[prefix].items() if key == str(node['id']) and (node['inputs'][i].get('type') == output_type or output_type in node['inputs'][i].get('type', '').split(','))]
            if len(candidates) == 1:
                return self.source(prefix + candidates[0][0], candidates[0][1])
            raise CompileError(f'Unresolved bypass {nid} ({typ})')
        if typ in self.defs:
            child = nid + ':'
            edge = self.links[child].get(('-20', slot))
            if not edge:
                raise CompileError(f'Missing subgraph output {nid}:{slot}')
            if edge[0] == '-10':
                name = node.get('inputs', [])[edge[1]]['name']
                return self.input_value(nid, name)[0]
            return self.source(child + edge[0], edge[1])
        if typ in ('Reroute', 'SetNode', 'GetNode', 'PrimitiveNode') or node.get('mode', 0) == 4:
            if typ == 'PrimitiveNode':
                return node.get('widgets_values', [None])[0]
            if typ == 'GetNode':
                name = node.get('widgets_values', [None])[0]
                matches = [prefix + key for key, n in self.contexts[prefix].items() if n['type'] == 'SetNode' and n.get('widgets_values', [None])[0] == name]
                if len(matches) != 1:
                    raise CompileError(f'Ambiguous broadcast {nid}')
                return self.source(matches[0], slot)
            output_type = node.get('outputs', [{}])[slot].get('type') if slot < len(node.get('outputs', [])) else '*'
            candidates = []
            for index, inp in enumerate(node.get('inputs', [])):
                edge = self.edge(prefix, node, index)
                if edge and (typ in ('Reroute', 'SetNode') or inp.get('type') in (output_type, '*') or output_type in inp.get('type', '').split(',')):
                    candidates.append(edge)
            if not candidates:
                raise CompileError(f'Unresolved bypass {nid} ({typ})')
            selected = candidates[min(slot, len(candidates) - 1)]
            return self.source(prefix + selected[0], selected[1])
        if node.get('mode', 0) == 2:
            raise CompileError(f'Disabled input reached: {nid}')
        self.compile_node(nid)
        return [nid, slot]

    def specs(self, node, definition):
        values = self.bindings(node)
        sockets = {x['name']: x for x in node.get('inputs', [])}
        result = {}

        def expand(mapping, required, prefix=''):
            for key, spec in mapping.items():
                full = prefix + key
                typ = spec[0]
                options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                if typ == 'COMFY_AUTOGROW_V3':
                    template = options.get('template', {})
                    leaf = next(iter(template.get('input', {}).get('required', {}).values()), ['*'])
                    names = template.get('names', []) or [template.get('prefix', '') + str(i) for i in range(template.get('max', 0))]
                    for name in names:
                        result[full + '.' + name] = (leaf, False)
                    continue
                result[full] = (spec, required)
                if typ == 'COMFY_DYNAMICCOMBO_V3':
                    choices = options.get('options', [])
                    selected = values.get(full, options.get('default', choices[0]['key'] if choices else None))
                    choice = next((x for x in choices if x['key'] == selected), None)
                    if choice:
                        for section in ('required', 'optional'):
                            expand(choice.get('inputs', {}).get(section, {}), section == 'required', full + '.')
        for section in ('required', 'optional'):
            expand(definition.get('input', {}).get(section, {}), section == 'required')
        return result

    def compile_node(self, nid):
        if nid in self.compiled:
            return
        if nid in self.busy:
            raise CompileError(f'Cycle must use an execution-aware loop node: {nid}')
        prefix, node = self.nodes[nid]
        typ = node['type']
        if typ not in self.schemas:
            raise CompileError(f'Card node unavailable: {typ}')
        self.busy.add(nid)
        definition = self.schemas[typ]
        inputs = {}
        for key, (spec, required) in self.specs(node, definition).items():
            try:
                value, origins = self.input_value(nid, key)
            except (KeyError, CompileError) as error:
                if isinstance(error, CompileError):
                    if not required and ('Unresolved bypass' in str(error) or 'Disabled input' in str(error)):
                        continue
                    if 'Unresolved bypass' not in str(error) or key not in self.bindings(node):
                        raise
                    value, origins = self.bindings(node)[key], [nid + ':' + key]
                    inputs[key] = value
                    self.remember(nid + ':' + key, nid, key)
                    continue
                options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                # Virtual input broadcasters must be unambiguous and in scope.
                matches = []
                for src_key, source_node in self.contexts[prefix].items():
                    if source_node['type'] in ('Anything Everywhere', 'Anything Everywhere3') and source_node.get('mode', 0) == 0:
                        for i, inp in enumerate(source_node.get('inputs', [])):
                            edge = self.edge(prefix, source_node, i)
                            if edge and inp.get('type') == spec[0]:
                                matches.append(edge)
                if len(matches) == 1:
                    value, origins = self.source(prefix + matches[0][0], matches[0][1]), []
                elif 'default' in options:
                    value, origins = options['default'], []
                elif spec[0] == 'COMFY_DYNAMICCOMBO_V3' and options.get('options'):
                    value, origins = options['options'][0]['key'], []
                elif not required:
                    continue
                else:
                    raise CompileError(f'Missing required input {nid}.{key} ({typ})') from None
            original = value
            if not isinstance(value, (list, dict)) and spec[0] == 'BOOLEAN' and isinstance(value, str):
                booleans = {'true': True, 'false': False, 'enabled': True, 'disabled': False}
                if value.lower() in booleans:
                    value = booleans[value.lower()]
                elif value == '' and (typ, key) in (('WanVideoSampler', 'batched_cfg'), ('JoinStringMulti', 'return_list')):
                    value = False
            if typ == 'PreviewBridge' and key == 'block' and isinstance(value, dict) and 'filename' in value:
                value = False  # clipspace preview state occupies this old widget position
            if typ in ('Int', 'Float') and key == 'Number' and isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)  # these exact node classes parse STRING numbers
            if typ == 'LTXVAddGuideMulti' and key == 'num_guides' and value == '1' and node.get('widgets_values') == [0]:
                original = 0
            if value != original or type(value) is not type(original):
                self.normalized.append({'node': nid, 'input': key, 'reason': 'saved widget representation migrated to current card input type',
                                        'from': '[preview metadata]' if isinstance(original, dict) else original, 'to': value})
            inputs[key] = value
            self.remember(nid + ':' + key, nid, key)
            for origin in origins:
                self.remember(origin, nid, key)
        self.compiled[nid] = {'class_type': typ, 'inputs': inputs, '_meta': {'title': node.get('title', typ)}}
        self.busy.remove(nid)

    def outputs(self, kind):
        selected = []
        for nid, (_, node) in self.nodes.items():
            if not self.active(nid):
                continue
            typ = node['type']
            if re.search(r'SaveImage|SaveVideo|VideoCombine|SaveAudio|SaveAnimated', typ, re.I) or (kind == 'text' and re.search(r'ShowText|showAnything|TextPreview', typ, re.I)):
                selected.append(nid)
        if not selected:
            selected = [nid for nid, (_, n) in self.nodes.items() if self.active(nid) and re.search(r'PreviewImage|PreviewAudio', n['type'], re.I)]
        if not selected:
            raise CompileError('No active result node')
        for nid in selected:
            self.compile_node(nid)
        return selected

    def active(self, nid):
        prefix, node = self.nodes[nid]
        if node.get('mode', 0) != 0:
            return False
        while prefix:
            parent, instance = self.parents[prefix]
            if self.nodes[instance][1].get('mode', 0) != 0:
                return False
            prefix = parent
        return True

    def targets(self, surface, key):
        result = []
        for nid in self.aliases.get(surface, [surface]):
            items = self.target_map.get(nid + ':' + key, [])
            if not items and nid in self.compiled and key in self.compiled[nid]['inputs']:
                items = [{'node': nid, 'input': key}]
            for item in items:
                if item not in result:
                    result.append(item)
        return result

    def input_spec(self, target):
        nid, key = target['node'], target['input']
        if nid not in self.nodes or nid not in self.compiled:
            return None
        node = self.nodes[nid][1]
        return self.specs(node, self.schemas[node['type']]).get(key, (None, False))[0]

    def dependency_errors(self):
        result = []
        for nid, node in self.compiled.items():
            for key, value in node['inputs'].items():
                spec = self.input_spec({'node': nid, 'input': key})
                if not spec or isinstance(value, (list, dict)) or key in ('image', 'video', 'file', 'audio', 'path'):
                    continue
                opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                choices = spec[0] if isinstance(spec[0], list) else opts.get('options') if spec[0] == 'COMBO' else None
                if choices and value not in choices:
                    matches = []
                    if isinstance(value, str):
                        if any(part in key for part in ('lora', 'clip_name', 'unet_name', 'vae_name', 'ckpt_name')):
                            basename = value.replace('\\', '/').split('/')[-1]
                            matches = [o for o in choices if isinstance(o, str) and o.replace('\\', '/').split('/')[-1] == basename]
                        else:
                            symbolic = value.split(' — ')[0].split(' [')[0]
                            matches = [o for o in choices if isinstance(o, str) and o.split(' — ')[0].split(' [')[0] == symbolic]
                    if len(matches) == 1:
                        node['inputs'][key] = matches[0]
                        self.normalized.append({'node': nid, 'input': key, 'reason': 'unique card path or unchanged enum key', 'from': value, 'to': matches[0]})
                    else:
                        result.append(f'节点 {nid}（{node["class_type"]}）不支持源图的 {key} 默认值；请修复算力端模型或节点版本')
        return result


def sanitize(graph, editable_texts, media):
    out = copy.deepcopy(graph)
    credential_sources = set()
    for nid, node in out.items():
        if node['class_type'] == 'PointsEditor':
            # Saved point/bbox widgets describe the owner's original footage.
            # They are user material state, not reusable pipeline instructions.
            for key in ('points_store', 'coordinates', 'neg_coordinates', 'bbox_store', 'bboxes'):
                if key in node['inputs']:
                    node['inputs'][key] = '{"positive":[],"negative":[]}' if key == 'points_store' else '[]'
        for key, value in list(node['inputs'].items()):
            if re.search(r'api.?key|password|token|secret|authorization', key, re.I):
                if isinstance(value, list) and len(value) == 2:
                    credential_sources.add(str(value[0]))
                else:
                    node['inputs'][key] = ''
            elif isinstance(value, str) and re.fullmatch(r'sk-[\w-]{16,}', value):
                node['inputs'][key] = ''
            if key == 'filename_prefix':
                node['inputs'][key] = 'yingxu/result'
    for nid in credential_sources:
        for key, value in out.get(nid, {}).get('inputs', {}).items():
            if isinstance(value, str):
                out[nid]['inputs'][key] = ''
    for field in editable_texts:
        if field.get('preserveWhenEmpty'):
            continue
        for target in field['targets']:
            out[target['node']]['inputs'][target['input']] = ''
    for slot in media:
        for target in slot['targets']:
            if not target.get('valueMode'):
                out[target['node']]['inputs'][target['input']] = ''
    return out


def main():
    schemas = json.loads((CACHE / 'object_info.json').read_text('utf-8'))
    names = json.loads((CACHE / 'files.json').read_text('utf-8'))
    catalog = json.loads((ROOT / 'public/local-catalog.json').read_text('utf-8'))['workflows']
    interfaces = json.loads((ROOT / 'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
    downloaded = {f"local-card-{row['index']}": row['sha256']
                  for row in json.loads((CACHE / 'snapshot.json').read_text('utf-8'))['files']}
    changed = [entry['id'] for entry in catalog if entry['id'].startswith('local-card-')
               and downloaded.get(entry['id']) != interfaces[entry['id']]['sourceHash']]
    if changed:
        raise CompileError('Downloaded source differs from reviewed interface; rebuild and review bindings first: ' + ', '.join(changed))
    from adapters import CATALOG_WORKFLOWS
    legacy = {w['id'] for w in CATALOG_WORKFLOWS}
    registry, audit = {}, []
    for entry in catalog:
        wid = entry['id']
        if not wid.startswith('local-card-'):
            continue
        index = int(wid.rsplit('-', 1)[-1])
        raw_path = CACHE / f'graph-{index:03}.json'
        raw = json.loads(raw_path.read_text('utf-8'))
        cfg = interfaces[wid]
        spec = {key: entry[key] for key in ('id', 'name', 'output')}
        spec.update(source=names[index], source_hash=cfg['sourceHash'], adapter='generic', template=wid + '.api.json', controls=[], texts=[], media=[], apiProfiles=[], outputs=[])
        errors, excluded = [], []
        if wid in legacy:
            audit.append({**spec, 'validation': 'legacy-adapter', 'controls': len(cfg['controls']), 'texts': len(cfg['texts']), 'media': len(cfg['media'])})
            continue
        try:
            compiler = Compiler(raw, schemas)
            spec['outputs'] = compiler.outputs(entry['output'])
            # Surface fields are mapped after every active branch has compiled.
            for control in cfg['controls']:
                c = copy.deepcopy(control)
                targets = []
                for source in c.get('members', [c]):
                    derived = source.get('derived', c.get('derived'))
                    if derived:
                        nid, key = derived['targetId'].rsplit(':', 1)
                        mapped = compiler.targets(nid, key)
                        c['transform'] = {k: v for k, v in derived.items() if k != 'targetId'}
                    else:
                        mapped = [t for old in source.get('targets', []) for t in compiler.targets(old['node'], old['input'])]
                    targets.extend(t for t in mapped if t not in targets)
                if not targets:
                    targets = compiler.targets(c.get('nodeId', ''), c['key'])
                    if not targets:
                        excluded.append({'id': c['id'], 'reason': 'not on compiled active output path'})
                        continue
                c['targets'] = targets
                if c.get('kind') == 'points':
                    c['transform'] = {'operation': 'points'}
                    recipe = c.get('previewRecipe', {})
                    spec['pointsRecipe'] = {
                        'slotId': c.get('mediaSlotId', '1084'),
                        'longSideControlId': recipe.get('longSideControlId', '1105:value'),
                        'longSide': recipe.get('longSide', 1280), 'multiple': recipe.get('multiple', 32),
                        'sourceMultiple': recipe.get('sourceMultiple', 8),
                        'node': targets[0]['node'],
                        'negativeTarget': {'node': '1062', 'input': 'negative_points'},
                    }
                    # The saved source connects only the positive output. The
                    # reviewed point tool also exposes the existing SeC negative
                    # input; keep both behaviours backed by the real node schema.
                    if '1062' not in compiler.compiled or 'negative_points' not in schemas[compiler.compiled['1062']['class_type']].get('input', {}).get('optional', {}):
                        raise CompileError('Subject tracking negative-point input is unavailable')
                    compiler.compiled['1062']['inputs']['negative_points'] = [targets[0]['node'], 1]
                    point_inputs = compiler.compiled[targets[0]['node']]['inputs']
                    for key in ('coordinates', 'neg_coordinates', 'bbox_store', 'bboxes'):
                        point_inputs[key] = '[]'
                    point_inputs['points_store'] = '{"positive":[],"negative":[]}'
                concrete_specs = [compiler.input_spec(t) for t in targets]
                opts = [s[1] if s and len(s) > 1 and isinstance(s[1], dict) else {} for s in concrete_specs]
                # These utility nodes parse numbers from a STRING socket. The
                # user still edits a numeric field, and submission must preserve
                # that exact protocol instead of sending a JSON number.
                if c.get('type') == 'number' and not c.get('transform') and all(
                    s and s[0] == 'STRING' and t['input'] == 'Number'
                    and compiler.compiled[t['node']]['class_type'] in ('Int', 'Float')
                    for t, s in zip(targets, concrete_specs)
                ):
                    c['transform'] = {'operation': 'number-string'}
                    c['integer'] = all(compiler.compiled[t['node']]['class_type'] == 'Int' for t in targets)
                    for default_key in ('value', 'default'):
                        if isinstance(c.get(default_key), str):
                            c[default_key] = int(c[default_key]) if c['integer'] else float(c[default_key])
                if c.get('type') == 'number' and not c.get('transform'):
                    lows = [o['min'] for o in opts if 'min' in o]
                    highs = [o['max'] for o in opts if 'max' in o]
                    if lows:
                        c['min'] = max(c.get('min', max(lows)), max(lows))
                    if highs:
                        c['max'] = min(c.get('max', min(highs)), min(highs))
                    if all(s and s[0] == 'INT' for s in concrete_specs):
                        c['integer'] = True
                    actual_steps = [o['step'] for o in opts if isinstance(o.get('step'), (int, float)) and o['step'] > 0]
                    if actual_steps:
                        c['step'] = max(actual_steps)
                    if c['kind'] == 'seed':
                        c['min'] = max(0, c.get('min', 0))
                if len(concrete_specs) == 1 and concrete_specs[0]:
                    actual = concrete_specs[0]
                    choices = actual[0] if isinstance(actual[0], list) else opts[0].get('options') if actual[0] == 'COMBO' else None
                    if choices and c['kind'] in ('ratio', 'choice', 'task'):
                        c['options'] = choices
                        c.pop('customRange', None)
                # Width/height compound selectors need an explicit split.
                if c['id'] == 'site:size':
                    c['transform'] = {'operation': 'size', 'axisByTarget': {t['node'] + '.' + t['input']: ('width' if i == 0 else 'height') for i, t in enumerate(targets)}}
                spec['controls'].append(c)
            for field in cfg['texts']:
                nid, key = field['id'].rsplit(':', 1)
                targets = compiler.targets(nid, key)
                if not targets:
                    # User text from a virtual Primitive is bound to its real consumers.
                    graph = Graph(raw)
                    targets = [t for dest, name in graph.targets(nid, key) for t in compiler.targets(dest, name)]
                if not targets:
                    excluded.append({'id': field['id'], 'reason': 'not on compiled active output path'})
                else:
                    fixed_instruction = key in ('role', 'system_prompt') or '扩写指令' in field.get('label', '')
                    spec['texts'].append({**field, 'targets': targets, 'default': '', 'preserveWhenEmpty': fixed_instruction})
            for slot in cfg['media']:
                source_id = slot.get('sourceNodeId', slot['id'])
                targets = []
                for nid in compiler.aliases.get(source_id, [source_id]):
                    if nid in compiler.compiled:
                        node = compiler.compiled[nid]
                        key = next((key for key in ('image', 'video', 'file', 'audio', 'path') if key in node['inputs']), None)
                        if key:
                            targets.append({'node': nid, 'input': key})
                socket_targets = slot.get('targets') or ([slot['target']] if slot.get('target') else [])
                if not targets and socket_targets:
                    for target in socket_targets:
                        for nid in compiler.aliases.get(target['node'], [target['node']]):
                            if nid in compiler.compiled:
                                targets.append({'node': nid, 'input': target['input'], 'valueMode': 'loader', 'inputType': 'IMAGE' if slot['kind'] == 'image' else 'AUDIO', 'optional': True})
                if not targets:
                    excluded.append({'id': slot['id'], 'reason': 'not on compiled active output path'})
                else:
                    spec['media'].append({**slot, 'targets': targets, 'required': not slot.get('optional', False)})
            for profile in cfg.get('apiProfiles', []):
                new = copy.deepcopy(profile)
                new['bindings'] = {}
                for key, bind in profile.get('bindings', {}).items():
                    mapped = compiler.targets(bind['node'], bind['input'])
                    if mapped:
                        new['bindings'][key] = mapped[0] if len(mapped) == 1 else mapped
                    else:
                        excluded.append({'id': profile['id'] + '.' + key, 'reason': 'not on compiled active output path'})
                if new['bindings']:
                    spec['apiProfiles'].append(new)
            errors.extend(compiler.dependency_errors())
            if wid == 'local-card-125':
                spec['constraints'] = [{'type': 'nonzero-size', 'width': '225:value', 'height': '226:value'}]
            spec['normalizations'] = compiler.normalized
            spec['external_api_account'] = bool(spec['apiProfiles']) or any(
                re.search(r'Comfly|VisionAPI|LLMAPI|MultimodalChat|PromptEnhancer', node['class_type'], re.I)
                for node in compiler.compiled.values())
            # Save full private values for the owner, sanitize the portable copy.
            private_dir = ROOT / 'private/card-compiled'
            private_dir.mkdir(exist_ok=True)
            (private_dir / spec['template']).write_text(json.dumps(compiler.compiled, ensure_ascii=False, indent=2), 'utf-8')
            public_graph = sanitize(compiler.compiled, spec['texts'], spec['media'])
            (ROOT / 'workflows/api' / spec['template']).write_text(json.dumps(public_graph, ensure_ascii=False, indent=2), 'utf-8', newline='\n')
            spec['node_count'] = len(compiler.compiled)
        except (CompileError, KeyError, IndexError, TypeError) as e:
            if isinstance(e, CompileError) and str(e).startswith('Card node unavailable:'):
                graph = Graph(raw)
                frontend_only = {'Reroute', 'SetNode', 'GetNode', 'PrimitiveNode', 'Note', 'MarkdownNote'}
                missing = sorted({node['type'] for nid, node in graph.nodes.items()
                                  if nid in graph.reachable and graph.enabled(nid)
                                  and node['type'] not in schemas and node['type'] not in graph.defs
                                  and node['type'] not in frontend_only})
                spec['missing_nodes'] = missing
                errors.append('算力卡缺少节点：' + '、'.join(missing))
            else:
                errors.append(str(e))
        spec['validation'] = 'blocked' if errors else 'structural-verified'
        spec['blocking_reason'] = '；'.join(errors) if errors else ''
        spec['excluded'] = excluded
        registry[wid] = spec
        audit.append({**spec, 'errors': errors})
    registry_path = ROOT / 'workflows/compiled-registry.json'
    registry_path.write_text(json.dumps({'version': 1, 'workflows': registry}, ensure_ascii=False, indent=2), 'utf-8', newline='\n')
    manifest_path = ROOT / 'workflows/manifest.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    manifest['workflows'] = [entry for entry in manifest['workflows'] if entry['id'] not in registry]
    for spec in registry.values():
        if spec['validation'] != 'structural-verified':
            continue
        path = ROOT / 'workflows/api' / spec['template']
        graph = json.loads(path.read_text('utf-8'))
        model_keys = ('lora_name', 'clip_name', 'unet_name', 'vae_name', 'ckpt_name', 'model_name', 'model')
        models = sorted({value for node in graph.values() for key, value in node['inputs'].items()
                         if key in model_keys and isinstance(value, str) and value})
        manifest['workflows'].append({
            **{key: spec[key] for key in ('id', 'name', 'output', 'template', 'source_hash')},
            'template_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'requires_custom_api': spec['external_api_account'],
            'node_types': sorted({node['class_type'] for node in graph.values()}),
            'models': models, 'validation': spec['validation'],
        })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8', newline='\n')
    dest = ROOT / 'private/review70'
    dest.mkdir(exist_ok=True)
    (dest / 'compile-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'card_catalog_entries': len(audit), 'legacy': len(legacy), 'compiled': sum(s['validation'] == 'structural-verified' for s in registry.values()), 'blocked': {k: v['blocking_reason'] for k, v in registry.items() if v['validation'] == 'blocked'}}, ensure_ascii=True))


if __name__ == '__main__':
    main()
