"""Check a checkout without the owner's files; --probe checks your own ComfyUI."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_files():
    manifest = json.loads((ROOT / 'workflows/manifest.json').read_text('utf-8'))['workflows']
    for entry in manifest:
        path = ROOT / 'workflows/api' / entry['template']
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['template_sha256']:
            raise ValueError(f"Template changed without updating manifest: {entry['id']}")
        graph = json.loads(path.read_text('utf-8'))
        if not graph or any(not isinstance(n, dict) or 'class_type' not in n for n in graph.values()):
            raise ValueError(f"Invalid API template: {entry['id']}")
    catalog = json.loads((ROOT / 'public/local-catalog.json').read_text('utf-8'))['workflows']
    interfaces = json.loads((ROOT / 'public/workflow-interfaces.json').read_text('utf-8'))['workflows']
    for entry in catalog:
        if entry['id'] not in interfaces:
            raise ValueError(f"Missing UI schema: {entry['id']}")
    # Check literal relative imports and HTML resources before publishing Pages.
    for path in (ROOT / 'public').rglob('*'):
        if path.suffix not in ('.js', '.html', '.css'):
            continue
        source = path.read_text('utf-8-sig')
        if path.suffix == '.js':
            refs = re.findall(r"(?:from\s*|import\s*)['\"](\.[^'\"]+)['\"]", source)
        elif path.suffix == '.html':
            refs = re.findall(r'(?:src|href)=[\"\']([^\"\']+)[\"\']', source)
        else:
            refs = re.findall(r'url\([\"\']?([^\s\)\"\']+)', source)
        for ref in refs:
            ref = ref.split('?', 1)[0].split('#', 1)[0]
            if not ref or re.match(r'(?:https?:|data:|blob:|mailto:|/)', ref) or '${' in ref:
                continue
            if not (path.parent / ref).is_file():
                raise ValueError(f'Missing resource: {path.relative_to(ROOT)} -> {ref}')
    print(f'OK: {len(catalog)} workflow interfaces, {len(manifest)} API templates, static resources present.')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true', help='Check node types on your configured ComfyUI; does not generate or charge.')
    args = parser.parse_args()
    manifest = check_files()
    if args.probe:
        import os
        import requests
        from configuration import ROOT as config_root  # Loads .env, without printing credentials.
        base = os.environ.get('CHENYU_CARD_URL', '').rstrip('/')
        if not base:
            parser.error('Set CHENYU_CARD_URL in .env first.')
        response = requests.get(base + '/object_info', timeout=30)
        response.raise_for_status()
        available = response.json()
        missing = {entry['id']: sorted(set(entry['node_types']) - available.keys()) for entry in manifest}
        missing = {key: value for key, value in missing.items() if value}
        print(json.dumps({'missing_node_types': missing}, ensure_ascii=False, indent=2))
        print('Model files, API credits and generation results still need separate verification.')
        if missing:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
