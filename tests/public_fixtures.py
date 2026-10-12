"""Offline test fixtures that never load the developer's private workspace."""
import atexit
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Configuration normally loads .env at import time. Tests supply all state.
with patch('dotenv.load_dotenv', return_value=False):
    import configuration
    import schema_adapters as runtime


def public_template_path(spec):
    name = spec.get('template', spec['id'] + '.api.json')
    if Path(name).name != name:
        raise ValueError('Test template must be a public basename')
    path = ROOT / 'workflows' / 'api' / name
    if not path.is_file():
        raise AssertionError(f'Missing published workflow: {name}')
    return path


def historical_path(relative):
    """Explicit opt-in for unshipped author/node evidence, never private fallback."""
    folder = os.environ.get('YINGXU_HISTORICAL_TEST_FIXTURES')
    if not folder:
        raise unittest.SkipTest(
            'Historical author/native snapshot is not a deployment dependency; '
            'set YINGXU_HISTORICAL_TEST_FIXTURES to an explicit evidence export.'
        )
    root = Path(folder).resolve()
    path = (root / relative).resolve()
    path.relative_to(root)
    if not path.exists():
        raise unittest.SkipTest(f'Historical evidence export lacks {relative}')
    return path


def isolated_server(name):
    """Import real server functions with a disposable database and no .env/config."""
    with patch('dotenv.load_dotenv', return_value=False):
        import platform_api
        from platform_accounts import PlatformAccounts

    class TestAccounts(PlatformAccounts):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('password_rounds', 100_000)
            super().__init__(*args, **kwargs)

    class PublicImportPath(list):
        def insert(self, index, value):
            if Path(value).resolve() != (ROOT / 'private' / 'runtime').resolve():
                super().insert(index, value)

    temporary = tempfile.TemporaryDirectory(prefix='yingxu-public-tests-')
    spec = importlib.util.spec_from_file_location(name, ROOT / 'server.py')
    backend = importlib.util.module_from_spec(spec)
    sys.modules[name] = backend
    original_read = Path.read_text

    def safe_read(path, *args, **kwargs):
        if path == ROOT / 'private' / 'backend.json':
            return '{}'
        return original_read(path, *args, **kwargs)

    try:
        with patch.object(configuration, 'DATA_DIR', Path(temporary.name)), \
                patch.dict(os.environ, {'CHENYU_CARD_URL': '', 'YINGXU_LOCAL_MODE': '0'}), \
                patch.object(Path, 'read_text', safe_read), \
                patch.object(sys, 'path', PublicImportPath(sys.path)), \
                patch.object(platform_api, 'PlatformAccounts', TestAccounts), \
                patch('requests.sessions.Session.request', side_effect=AssertionError('Tests must stay offline')):
            spec.loader.exec_module(backend)
    except BaseException:
        sys.modules.pop(name, None)
        temporary.cleanup()
        raise
    atexit.register(temporary.cleanup)
    return backend
