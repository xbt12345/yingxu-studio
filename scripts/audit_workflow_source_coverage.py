"""Trace every catalog workflow's candidate editable inputs to its UI schema.

This is an independent check of the graph-driven interface builder: a candidate
is identified from the original graph, then matched to a visible field, a
documented composite, or a source-aware conversion. Unmatched candidates must
be reviewed individually rather than silently counted as complete.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from build_workflow_interfaces import Graph, semantic, widget_bindings
from build_local_catalog import fingerprint
from workflow_customization import INTERNAL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters import CATALOG_WORKFLOWS  # noqa: E402
CONNECTED_IDS = {item['id'] for item in CATALOG_WORKFLOWS}


def field_candidates(workflow, graph):
    fields = []
    for original in workflow['fields']:
        field = dict(original)
        if field['key'].startswith('widget_'):
            index = int(field['key'].split('_')[1])
            bindings = widget_bindings(graph.nodes.get(field['nodeId'], {}))
            actual = next((key for key, (_, position) in bindings.items() if position == index), None)
            if actual:
                field['key'] = actual
        fields.append(field)
    for node_id, node in graph.nodes.items():
        for key, (value, _) in widget_bindings(node).items():
            if any(field['nodeId'] == node_id and field['key'] == key for field in fields):
                continue
            if not isinstance(value, (int, float, str, bool)):
                continue
            fields.append({'id': node_id + ':' + key, 'nodeId': node_id, 'key': key,
                           'value': value, 'type': 'checkbox' if isinstance(value, bool) else
                           'number' if isinstance(value, (int, float)) else 'text',
                           'linked': not graph.editable(node_id, key),
                           'inactive': node.get('mode', 0) in (2, 4)})
    for field in fields:
        if field.get('inactive') or field.get('linked') or not graph.editable(field['nodeId'], field['key']):
            continue
        kind, label = semantic(graph, field, workflow)
        if kind and (field['type'] != 'number' or isinstance(field['value'], (int, float))):
            yield {'id': field['id'], 'kind': kind, 'label': label,
                   'nodeType': graph.nodes[field['nodeId']]['type'],
                   'key': field['key'], 'targets': [{'node': node, 'input': key}
                                                  for node, key in graph.targets(field['nodeId'], field['key'])]}


def classify(candidate, controls):
    if any(control['id'] == candidate['id'] for control in controls):
        return 'direct'
    if any(any(member['id'] == candidate['id'] for member in control.get('members', []))
           for control in controls):
        return 'merged-member'
    if any(control.get('derived', {}).get('targetId') == candidate['id'] for control in controls):
        return 'unit-conversion'
    if candidate['nodeType'] == 'PrimitiveInt' and candidate['key'] == 'value':
        role = {item['input'] for item in candidate['targets']} & {'width', 'height'}
        if len(role) == 1 and any(control['id'] == 'site:size' and control['kind'] == 'ratio' and
                                  {'node': candidate['id'].split(':')[0], 'input': 'value'} in control['targets']
                                  for control in controls):
            return 'width-height-composite'
    own_targets = {(item['node'], item['input']) for item in candidate['targets']}
    if own_targets and any(own_targets & {(item['node'], item['input']) for item in control.get('targets', [])}
                           for control in controls):
        return 'composite-target'
    return 'unmatched'


def text_candidates(workflow, graph):
    ids = set()
    for item in workflow.get('texts', []):
        node_id, key = item['id'].rsplit(':', 1)
        if graph.editable(node_id, key) and key != 'system_prompt' and not re.search(
                r'Note|Show|Preview|Markdown|Display|Label', graph.nodes[node_id]['type'], re.I):
            if key in ('prompt', 'text', 'negative_prompt'):
                ids.add(item['id'])
    for node_id, node in graph.nodes.items():
        if re.search(r'Note|Show|Preview|Markdown|Display|Label', node['type'], re.I):
            continue
        named = widget_bindings(node)
        for key in ('prompt', 'text', 'negative_prompt', 'positive', 'negative'):
            if (key in named or any(inp['name'] == key and inp.get('widget') for inp in node.get('inputs', []))) \
                    and graph.editable(node_id, key):
                ids.add(node_id + ':' + key)
        if node['type'] in ('PrimitiveStringMultiline', 'PrimitiveString') and graph.editable(node_id, 'value'):
            if any(key in ('prompt', 'text', 'positive', 'negative_prompt')
                   for _, key in graph.targets(node_id, 'value')):
                ids.add(node_id + ':value')
    return sorted(ids)


def media_candidates(graph):
    pattern = re.compile(r'LoadImage|ImageLoader|LoadImages|LoadVideo|VideoLoader|LoadAudio|AudioLoader', re.I)
    return sorted(node_id for node_id, node in graph.nodes.items()
                  if node_id in graph.reachable and graph.enabled(node_id) and pattern.search(node['type']))


def text_coverage(workflow_id, text_id, graph, config):
    if any(item['id'] == text_id for item in config['texts']):
        return 'direct'
    node_id, key = text_id.rsplit(':', 1)
    if any(any(target == {'node': node_id, 'input': key} for target in item.get('targets', []))
           for item in config['texts']):
        return 'merged-prompt'
    if any(item['id'] == text_id and item['kind'] == 'segment' for item in config['controls']):
        return 'typed-timecode'
    index = int(workflow_id.split('-')[-1]) if workflow_id.startswith('local-card-') else -1
    if node_id in INTERNAL.get(index, set()):
        return 'internal-template'
    if any(target_key == 'api_key' for _, target_key in graph.targets(node_id, key)):
        return 'credential-source'
    node = graph.nodes[node_id]
    if node['type'] == 'RH_LLMAPI_NODE' and all('Show' in graph.nodes[dst]['type'] or
            'show' in graph.nodes[dst]['type'] for dst, _, _ in graph.out[node_id]):
        return 'preview-only'
    return 'unmatched'


def media_coverage(workflow, node_id, graph, config, compiled):
    if any(item['id'] == node_id or item.get('sourceNodeId') == node_id for item in config['media']):
        return 'direct'
    if workflow['category'] == '素材格式工具' and graph.nodes[node_id]['type'] in (
            'LoadVideoBatchFrame', 'VHS_LoadVideoPath', 'LoadImageListFromDir //Inspire'):
        return 'directory-field'
    if compiled is not None:
        if node_id not in compiled:
            return 'pruned-from-execution'
        return 'unmatched-execution-input'
    # Catalog-only workflows have no executable server graph. Preserve the
    # distinction between source examples and verified generation inputs.
    return 'catalog-only-unverified'


def main():
    catalog = json.loads((ROOT / 'public/local-catalog.json').read_text(encoding='utf-8'))['workflows']
    schemas = json.loads((ROOT / 'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']
    sources = {item['id']: item for item in json.loads((ROOT / 'verification/catalog-audit.json').read_text(encoding='utf-8')) if 'id' in item}
    rows = []
    for workflow in catalog:
        workflow_id = workflow['id']
        config = schemas[workflow_id]
        source = Path(sources[workflow_id]['source'])
        raw_bytes = source.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        raw = json.loads(raw_bytes.decode('utf-8-sig'))
        catalog_raw = raw
        if not raw.get('nodes') and raw and all(isinstance(value, dict) and 'class_type' in value for value in raw.values()):
            catalog_raw = {'nodes': [dict(id=node_id, type=value['class_type'], **value)
                                     for node_id, value in raw.items()], 'links': []}
        semantic_fingerprint = fingerprint(catalog_raw)
        if actual_hash != config['sourceHash']:
            raise AssertionError(f'{workflow_id}: source hash mismatch')
        graph = Graph(raw)
        candidates = list(field_candidates(workflow, graph))
        findings = [{**candidate, 'coverage': classify(candidate, config['controls'])} for candidate in candidates]
        source_texts = text_candidates(workflow, graph)
        source_media = media_candidates(graph)
        compiled_path = ROOT / 'private/platform-compiled' / f'{workflow_id}.api.json'
        compiled = json.loads(compiled_path.read_text(encoding='utf-8')) if workflow_id in CONNECTED_IDS and compiled_path.exists() else None
        if workflow_id in CONNECTED_IDS and compiled is None:
            raise AssertionError(f'{workflow_id}: connected manifest has no compiled graph')
        text_findings = [{'id': text_id, 'coverage': text_coverage(workflow_id, text_id, graph, config)}
                         for text_id in source_texts]
        media_findings = [{'id': node_id, 'nodeType': graph.nodes[node_id]['type'],
                           'coverage': media_coverage(workflow, node_id, graph, config, compiled)}
                          for node_id in source_media]
        rows.append({'id': workflow_id, 'name': workflow['name'], 'category': workflow['category'],
                     'source': str(source), 'sha256': actual_hash,
                     'catalogFingerprintMatches': semantic_fingerprint == sources[workflow_id]['sha256'],
                     'execution': 'connected-compiled' if compiled is not None else 'catalog-only',
                     'reachableNodes': len(graph.reachable),
                     'candidateControls': len(candidates), 'visibleControls': len(config['controls']),
                     'visibleTexts': len(config['texts']), 'visibleMedia': len(config['media']),
                     'textFindings': text_findings, 'mediaFindings': media_findings,
                     'unmatchedTexts': [item['id'] for item in text_findings if item['coverage'] == 'unmatched'],
                     'unmatchedMedia': [item['id'] for item in media_findings
                                        if item['coverage'] == 'unmatched-execution-input'],
                     'findings': findings})
    unmatched = [{'workflow': row['id'], 'name': row['name'], **finding}
                 for row in rows for finding in row['findings'] if finding['coverage'] == 'unmatched']
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'private/review61/source-coverage.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'scope': 'source graph numeric and enum candidates vs UI schema',
                               'workflows': rows, 'unmatched': unmatched}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'workflows': len(rows), 'connected': sum(r['execution'] == 'connected-compiled' for r in rows),
                      'candidates': sum(r['candidateControls'] for r in rows),
                      'catalogFingerprintDrift': [r['id'] for r in rows if not r['catalogFingerprintMatches']],
                      'unmatched': len(unmatched), 'unmatchedFields': [f"{x['workflow']}:{x['id']}" for x in unmatched],
                      'unmatchedTexts': {r['id']: r['unmatchedTexts'] for r in rows if r['unmatchedTexts']},
                      'unmatchedMedia': {r['id']: r['unmatchedMedia'] for r in rows if r['unmatchedMedia']},
                      'catalogOnlyMediaCandidates': sum(item['coverage'] == 'catalog-only-unverified'
                                                       for row in rows for item in row['mediaFindings'])},
                     ensure_ascii=False))
    return 0 if not unmatched and not any(r['unmatchedTexts'] or r['unmatchedMedia'] or
                                          not r['catalogFingerprintMatches'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
