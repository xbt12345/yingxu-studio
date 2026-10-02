"""Compile six owner Flux UI graphs to executable ComfyUI API graphs.

Only active SaveImage ancestry is included. Subgraphs are expanded against their
saved definitions; node schemas come from the running card, never guessed.
"""
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_workflow_interfaces import Graph, widget_bindings

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'private/research/card-20260923'
OUTPUT = ROOT / 'private/platform-compiled'
BASE = os.environ.get('CHENYU_CARD_URL') or json.loads((ROOT / 'private/backend.json').read_text('utf-8'))['card_url']
BASE = BASE.rstrip('/')
TARGETS = {11: ('62', '147'), 15: ('135',), 16: ('26',),
           17: ('9', '94'), 18: ('9', '94'), 20: ('15',)}


def compile_graph(number):
    raw = json.loads((SOURCE / f'graph-{number:03}.json').read_text('utf-8'))
    graph = Graph(raw)
    schemas = {}
    compiled = {}
    definitions = graph.defs

    def schema(typ):
        if typ not in schemas:
            response = requests.get(BASE + '/object_info/' + requests.utils.quote(typ, safe=''), timeout=30)
            response.raise_for_status()
            schemas[typ] = response.json().get(typ)
            if not schemas[typ]:
                raise ValueError(f'Card node unavailable: {typ}')
        return schemas[typ]

    def incoming(nid, slot, source_context=None):
        matches = [(src, out) for src, out, target in graph.ins[nid]
                   if target == slot and (source_context is None or graph.context.get(src) == source_context)]
        if len(matches) != 1:
            raise ValueError(f'{number}: expected one link to {nid}:{slot}, got {matches}')
        return matches[0]

    def source(nid, slot, consumer):
        node = graph.nodes[nid]
        typ = node['type']
        if typ in definitions:
            child_context = definitions[typ][0]
            if graph.context[consumer] == child_context:
                src, out = incoming(nid, slot, graph.context[nid])
            else:
                src, out = incoming(nid, slot, child_context)
            return source(src, out, nid)
        if typ == 'Reroute':
            src, out = incoming(nid, 0)
            return source(src, out, nid)
        if typ == 'PrimitiveNode':
            return node['widgets_values'][0]
        if node.get('mode', 0) == 4:
            output_type = node.get('outputs', [])[slot].get('type')
            candidates = [(i, item) for i, item in enumerate(node.get('inputs', []))
                          if item.get('type') in (output_type, '*') and item.get('link') is not None]
            if len(candidates) != 1:
                raise ValueError(f'{number}: cannot bypass {nid} {typ}: {candidates}')
            upstream, upstream_slot = incoming(nid, candidates[0][0])
            return source(upstream, upstream_slot, nid)
        if node.get('mode', 0) == 2:
            raise ValueError(f'{number}: disabled node reached: {nid} {typ}')
        compile_node(nid)
        return [nid, slot]

    def compile_node(nid):
        if nid in compiled:
            return
        node = graph.nodes[nid]
        typ = node['type']
        definition = schema(typ)
        bindings = widget_bindings(node)
        if typ == 'Seed (rgthree)':
            bindings['seed'] = (node['widgets_values'][0], 0)
        inputs = {}
        for section in ('required', 'optional'):
            for key, spec in definition.get('input', {}).get(section, {}).items():
                index = next((i for i, item in enumerate(node.get('inputs', [])) if item['name'] == key), None)
                edges = [(src, out) for src, out, target in graph.ins[nid]
                         if target == index and not src.endswith('/-10')] if index is not None else []
                if len(edges) > 1:
                    raise ValueError(f'{number}: ambiguous input {nid}.{key}: {edges}')
                if edges:
                    inputs[key] = source(*edges[0], nid)
                elif key in bindings:
                    inputs[key] = bindings[key][0]
                elif section == 'required':
                    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                    if 'default' in options:
                        inputs[key] = options['default']
                    else:
                        raise ValueError(f'{number}: missing required {nid}.{key} ({typ})')
        compiled[nid] = {'class_type': typ, 'inputs': inputs,
                         '_meta': {'title': node.get('title', typ)}}

    for sink in TARGETS[number]:
        compile_node(sink)
    return compiled


if __name__ == '__main__':
    OUTPUT.mkdir(exist_ok=True)
    for number in TARGETS:
        compiled = compile_graph(number)
        dest = OUTPUT / f'local-card-{number}.api.json'
        dest.write_text(json.dumps(compiled, ensure_ascii=False, indent=2), 'utf-8')
        print(number, len(compiled), dest)
