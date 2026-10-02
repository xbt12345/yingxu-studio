"""Portable configuration; private overrides remain outside the repository."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
DATA_DIR = Path(os.environ.get('YINGXU_DATA_DIR') or ROOT / 'private').resolve()
WORKFLOW_DIR = Path(os.environ.get('YINGXU_WORKFLOW_DIR') or ROOT / 'workflows/api').resolve()


def workflow_path(workflow_id):
    """Prefer an owner's existing API graph; otherwise use the shipped template."""
    legacy = ROOT / 'private'
    if workflow_id.startswith('local-card-'):
        legacy /= 'platform-compiled'
    private_path = legacy / f'{workflow_id}.api.json'
    return private_path if private_path.is_file() else WORKFLOW_DIR / f'{workflow_id}.api.json'
