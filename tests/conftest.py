"""
Shared pytest fixtures.

env vars are set here (at module import time, before any app import)
so that app.py reads the test database path when first imported.
"""

import os

# Create the instance directory and set an absolute DB path before any imports.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INSTANCE_DIR = os.path.join(_REPO_DIR, "instance")
os.makedirs(_INSTANCE_DIR, exist_ok=True)
_TEST_DB_PATH = os.path.join(_INSTANCE_DIR, "test_tickettoride.db")

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-pytest")
os.environ.setdefault("FLASK_ENV", "testing")

import pytest


# ---------------------------------------------------------------------------
# Pure-logic fixtures — no Flask, no database
# ---------------------------------------------------------------------------

@pytest.fixture
def two_player_specs():
    return [
        {"id": 1, "name": "Alice", "color": "red",  "turn_order": 0},
        {"id": 2, "name": "Bob",   "color": "blue", "turn_order": 1},
    ]


@pytest.fixture
def four_player_specs():
    return [
        {"id": 1, "name": "Alice",   "color": "red",    "turn_order": 0},
        {"id": 2, "name": "Bob",     "color": "blue",   "turn_order": 1},
        {"id": 3, "name": "Charlie", "color": "green",  "turn_order": 2},
        {"id": 4, "name": "Diana",   "color": "yellow", "turn_order": 3},
    ]


# ---------------------------------------------------------------------------
# Flask app fixtures — only imported when actually needed by a test
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def flask_app():
    from app import app as _app, db as _db
    _app.config["TESTING"] = True
    _app.config["WTF_CSRF_ENABLED"] = False
    with _app.app_context():
        _db.create_all()
    yield _app
    # Remove test DB file after the whole session
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


@pytest.fixture
def app_ctx(flask_app):
    with flask_app.app_context():
        yield flask_app


@pytest.fixture
def clean_database(flask_app):
    """Wipe all rows after each test that uses Flask fixtures."""
    from app import db as _db
    yield
    with flask_app.app_context():
        _db.session.rollback()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


@pytest.fixture
def client(flask_app, clean_database):
    """HTTP test client. Uses clean_database so each test starts fresh."""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def socketio_client(flask_app, client):
    from app import socketio as _sio
    sc = _sio.test_client(flask_app, flask_test_client=client)
    yield sc
    sc.disconnect()


# ---------------------------------------------------------------------------
# Pre-built users
# ---------------------------------------------------------------------------

@pytest.fixture
def registered_user(client, app_ctx):
    """Register + log in a user. Returns (client, user)."""
    from app import db as _db
    from models import User
    with app_ctx.app_context():
        user = User(username="testuser", email="test@example.com")
        user.set_password("Password1!")
        _db.session.add(user)
        _db.session.commit()
    client.post("/login", json={"identity": "testuser", "password": "Password1!"})
    with app_ctx.app_context():
        user = User.query.filter_by(username="testuser").first()
        return client, user


@pytest.fixture
def registered_user2(app_ctx):
    """A second registered user (no active session)."""
    from app import db as _db
    from models import User
    with app_ctx.app_context():
        user = User(username="testuser2", email="test2@example.com")
        user.set_password("Password1!")
        _db.session.add(user)
        _db.session.commit()
        return User.query.filter_by(username="testuser2").first()
