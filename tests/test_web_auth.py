"""Tests for web authentication."""
import pytest
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def app(tmp_path):
    """Create a test Flask app with temporary config."""
    conf_dir = tmp_path / "gniza"
    conf_dir.mkdir()
    (conf_dir / "targets.d").mkdir()
    (conf_dir / "remotes.d").mkdir()
    (conf_dir / "schedules.d").mkdir()

    gniza_conf = conf_dir / "gniza.conf"
    gniza_conf.write_text('WEB_API_KEY="testkey123"\nRETENTION_COUNT="30"\n')

    log_dir = tmp_path / "log"
    log_dir.mkdir()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    import lib.config

    orig_config = lib.config.CONFIG_DIR
    orig_log = lib.config.LOG_DIR
    orig_work = lib.config.WORK_DIR

    lib.config.CONFIG_DIR = conf_dir
    lib.config.LOG_DIR = log_dir
    lib.config.WORK_DIR = work_dir

    from web.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    yield app

    lib.config.CONFIG_DIR = orig_config
    lib.config.LOG_DIR = orig_log
    lib.config.WORK_DIR = orig_work


@pytest.fixture
def client(app):
    return app.test_client()


def test_login_page_accessible(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_protected_route_redirects(client):
    resp = client.get("/backup/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_success(client):
    resp = client.post("/login", data={"token": "testkey123"})
    assert resp.status_code == 302
    assert "/login" not in resp.headers.get("Location", "")


def test_login_failure(client):
    resp = client.post("/login", data={"token": "wrong"})
    assert resp.status_code == 200
    assert b"Invalid password" in resp.data or b"invalid" in resp.data.lower()


def test_authenticated_access(client):
    client.post("/login", data={"token": "testkey123"})
    resp = client.get("/backup/")
    assert resp.status_code == 200
