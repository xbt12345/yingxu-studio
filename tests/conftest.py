"""Run historical regressions against only the shipped website artifacts."""
from unittest.mock import patch

import pytest

from public_fixtures import public_template_path, runtime


@pytest.fixture(autouse=True, scope='session')
def public_workflows_only():
    # Session scope includes unittest setUpClass, where some templates are read.
    with patch.object(runtime, 'template_path', public_template_path), \
            patch('requests.sessions.Session.request', side_effect=AssertionError('Tests must stay offline')):
        yield
