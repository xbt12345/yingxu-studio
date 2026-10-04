"""Read-only snapshot of the configured card. Raw user graphs stay private."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]


def snapshot(base, destination):
    destination.mkdir(parents=True, exist_ok=True)
    response = requests.get(base.rstrip('/') + '/userdata', params={'dir': 'workflows', 'recurse': 'true'}, timeout=45)
    response.raise_for_status()
    names = response.json()
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError('The card did not return a workflow file list.')
    (destination / 'files.json').write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding='utf-8')
    response = requests.get(base.rstrip('/') + '/object_info', timeout=60)
    response.raise_for_status()
    schemas = response.json()
    (destination / 'object_info.json').write_text(json.dumps(schemas, ensure_ascii=False), encoding='utf-8')

    def download(pair):
        index, name = pair
        response = requests.get(base.rstrip('/') + '/userdata/' + quote('workflows/' + name, safe=''), timeout=60)
        response.raise_for_status()
        graph = response.json()
        data = json.dumps(graph, ensure_ascii=False, indent=2)
        (destination / f'graph-{index:03}.json').write_text(data, encoding='utf-8')
        return {'index': index, 'path': name, 'bytes': len(response.content), 'sha256': hashlib.sha256(response.content).hexdigest(), 'valid_graph': isinstance(graph, dict)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(download, enumerate(names)))
    (destination / 'snapshot.json').write_text(json.dumps({'files': rows, 'node_types': len(schemas)}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'files': len(rows), 'node_types': len(schemas), 'destination': str(destination)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', default=str(ROOT / 'private/research/card-20261004'))
    args = parser.parse_args()
    config_path = ROOT / 'private/backend.json'
    config = json.loads(config_path.read_text('utf-8')) if config_path.exists() else {}
    base = os.environ.get('CHENYU_CARD_URL') or config.get('card_url')
    if not base:
        raise SystemExit('Set CHENYU_CARD_URL to the card to inspect.')
    print(json.dumps(snapshot(base, Path(args.destination)), ensure_ascii=True))
