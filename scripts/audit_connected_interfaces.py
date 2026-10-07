"""Check the 32 legacy catalog forms against their adapter contracts, offline.

Generic and primary forms are audited separately; this script does not claim
the legacy adapter list is the complete current ready workflow inventory.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters import CATALOG_WORKFLOWS, build_graph, manifest, settings_for  # noqa: E402

IDS = [int(workflow['id'].split('-')[-1]) for workflow in CATALOG_WORKFLOWS]


def custom_sample(field):
    """Choose within the reviewed unit/range, including branch-specific MP keys."""
    limits = field['customRange']
    minimum, maximum, step = limits['min'], limits['max'], limits['step']
    if field['key'] == 'size':
        edge = int(minimum + step * min(4, int((maximum - minimum) / step)))
        return f'{edge}x{edge}'
    sample = minimum + step * min(4, int((maximum - minimum) / step))
    return round(sample, 10)


def main():
    interfaces = json.loads((ROOT / 'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']
    errors = []
    for number in IDS:
        ident = f'local-card-{number}'
        workflow, ui = manifest(ident), interfaces[ident]
        if workflow['source_hash'] != ui['sourceHash']:
            errors.append(f'{ident}: source hash mismatch')
        controls = ui['controls']
        if len({f['key'] for f in controls}) != len(controls):
            errors.append(f'{ident}: duplicate request key')
        baseline = {f['key']: f['value'] for f in controls}
        if number in (11, 15, 16, 17, 18, 20):
            # The editor sends one normalized seed key to these comparison APIs.
            seed = next(f for f in controls if f['kind'] == 'seed')
            baseline.pop(seed['key'], None)
            baseline['seed'] = seed['value']
        variants = [('default', baseline)]
        for field in controls:
            if field['kind'] == 'seed' and number in (11, 15, 16, 17, 18, 20):
                continue
            for item in field.get('options') or []:
                if isinstance(item, dict) and item.get('disabled'):
                    continue
                variants.append((field['id'], {**baseline, field['key']: item.get('value') if isinstance(item, dict) else item}))
            custom = field.get('customRange')
            if custom:
                sample = custom_sample(field)
                variants.append((field['id'] + ' custom', {**baseline, field['key']: sample}))
        for label, supplied in variants:
            try:
                settings_for(workflow, supplied)
            except (ValueError, TypeError, KeyError) as exc:
                errors.append(f'{ident} {label}: {exc}')
        try:
            images = [{'kind': 'image', 'remote': f'a{i}.png'} for i in range(workflow['minImages'])]
            graph = build_graph(ident, '一只蓝色陶瓷杯', '', settings_for(workflow, baseline), images, 'audit')
            outputs = [node for node in graph.values() if node['class_type'].startswith('SaveImage')]
            if len(outputs) != {11: 2, 12: 3, 17: 2, 18: 2}.get(number, 1):
                errors.append(f'{ident}: unexpected output branches: {len(outputs)}')
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f'{ident} graph: {exc}')
        print(f'{ident}: {len(controls)} controls, {len(variants)} accepted inputs')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        raise SystemExit(1)
    print(f'PASS: {len(IDS)} legacy catalog workflows; UI defaults, enabled options and custom ranges match their adapters (not the full ready inventory)')


if __name__ == '__main__':
    main()
