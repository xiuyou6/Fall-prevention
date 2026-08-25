import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anbu import create_app  # noqa: E402
from anbu.services import bootstrap_database  # noqa: E402


@pytest.fixture
def app():
    application = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "TESTING": True,
            "RUN_BACKGROUND_WORKER": False,
        }
    )
    with application.app_context():
        bootstrap_database()
        yield application


@pytest.fixture
def client(app):
    return app.test_client()
