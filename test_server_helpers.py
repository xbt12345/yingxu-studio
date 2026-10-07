"""Shared test-only server loader that cannot bootstrap into original data."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent/'private/runtime'))
from fastapi.testclient import TestClient
import configuration
import platform_api
from platform_accounts import PlatformAccounts

ROOT=Path(__file__).resolve().parent
ORIGIN='http://127.0.0.1:8770'


class TestAccounts(PlatformAccounts):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('password_rounds',100_000)
        super().__init__(*args,**kwargs)


def load_server(name):
    temporary=tempfile.TemporaryDirectory(prefix='yingxu-test-import-')
    spec=importlib.util.spec_from_file_location(name,ROOT/'server.py')
    backend=importlib.util.module_from_spec(spec)
    sys.modules[name]=backend
    read=Path.read_text
    def safe_read(path,*args,**kwargs):
        if path==ROOT/'private'/'backend.json':return '{}'
        return read(path,*args,**kwargs)
    try:
        with patch.object(configuration,'DATA_DIR',Path(temporary.name)), \
                patch.dict(os.environ,{'CHENYU_CARD_URL':''}), \
                patch.object(Path,'read_text',safe_read), \
                patch.object(platform_api,'PlatformAccounts',TestAccounts):
            spec.loader.exec_module(backend)
    except BaseException:
        sys.modules.pop(name,None)
        temporary.cleanup()
        raise
    return backend,temporary


def authenticated_client(backend,accounts,user):
    session=accounts.create_session(user['id'])
    client=TestClient(backend.app,base_url=ORIGIN)
    client.cookies.set(platform_api.COOKIE,session['token'])
    client.headers.update({'Origin':ORIGIN,'X-CSRF-Token':session['csrf_token'],
                          'X-Platform-Account':user['id'],'X-Expected-Credits':'0'})
    return client
