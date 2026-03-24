"""Security tests -- TDD red-green-refactor for security fixes."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def app(tmp_path):
    """Create a test Flask app with sensitive config values."""
    conf_dir = tmp_path / "gniza"
    conf_dir.mkdir()
    (conf_dir / "targets.d").mkdir()
    (conf_dir / "remotes.d").mkdir()
    (conf_dir / "schedules.d").mkdir()

    gniza_conf = conf_dir / "gniza.conf"
    gniza_conf.write_text(
        'WEB_API_KEY="testkey123"\n'
        'SMTP_PASSWORD="supersecretsmtp"\n'
        'TELEGRAM_BOT_TOKEN="1234567:ABCdefGHIjklMNOpqrsTUVwxyz"\n'
        'NTFY_TOKEN="ntfy_secret_token"\n'
        'RETENTION_COUNT="30"\n'
    )

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
def authed_client(app):
    """Client that is already logged in."""
    client = app.test_client()
    client.post("/login", data={"token": "testkey123"})
    return client


# -- Issue 1: Credentials must NOT appear in HTML form values ----------

class TestCredentialsNotInHTML:
    def test_smtp_password_not_in_settings_html(self, authed_client):
        """SMTP password must not appear in the settings page HTML."""
        resp = authed_client.get("/settings/")
        html = resp.data.decode()
        assert "supersecretsmtp" not in html

    def test_telegram_token_not_in_settings_html(self, authed_client):
        """Telegram bot token must not appear in the settings page HTML."""
        resp = authed_client.get("/settings/")
        html = resp.data.decode()
        assert "1234567:ABCdefGHIjklMNOpqrsTUVwxyz" not in html

    def test_ntfy_token_not_in_settings_html(self, authed_client):
        """ntfy token must not appear in the settings page HTML."""
        resp = authed_client.get("/settings/")
        html = resp.data.decode()
        assert "ntfy_secret_token" not in html

    def test_password_fields_not_echoed(self, authed_client):
        """Password fields should not echo actual values in HTML."""
        resp = authed_client.get("/settings/")
        html = resp.data.decode()
        assert 'value="supersecretsmtp"' not in html
        assert 'value="1234567:ABCdefGHIjklMNOpqrsTUVwxyz"' not in html


# -- Issue 2: CSP must not allow unsafe-inline/unsafe-eval-able code ---

class TestContentSecurityPolicy:
    def test_csp_header_present(self, authed_client):
        """CSP header must be present."""
        resp = authed_client.get("/settings/")
        assert "Content-Security-Policy" in resp.headers

    def test_csp_has_frame_ancestors_none(self, authed_client):
        """CSP must prevent framing (clickjacking)."""
        resp = authed_client.get("/settings/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp

    def test_csp_has_form_action_self(self, authed_client):
        """CSP must restrict form submissions to self."""
        resp = authed_client.get("/settings/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "form-action 'self'" in csp

    def test_csp_script_src_present(self, authed_client):
        """CSP must have a script-src directive."""
        resp = authed_client.get("/settings/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "script-src" in csp


# -- Issue 3: SSHPASS uses tempfile not env ----------------------------

class TestSSHPasswordHandling:
    def test_sshpass_uses_file_not_env_flag(self):
        """SSHOpts with password should use sshpass -f (file) not -e (env)."""
        from lib.ssh import SSHOpts
        ssh = SSHOpts.adhoc("host", password="secret")
        cmd = ssh.ssh_cmd("echo ok")
        assert "sshpass" in cmd
        # -e flag exposes password in /proc/pid/environ, -f is safer
        if "-e" in cmd:
            pytest.fail("sshpass should not use -e flag (password visible in /proc/pid/environ)")


# -- Issue 4: Brute-force rate limiting --------------------------------

class TestBruteForceProtection:
    def test_lockout_after_max_attempts(self, app, tmp_path):
        """Account should lock after max failed login attempts."""
        # Clean lockout state before test
        lockout_file = tmp_path / "work" / "login-attempts.json"
        if lockout_file.exists():
            lockout_file.unlink()

        client = app.test_client()
        for _ in range(6):
            client.post("/login", data={"token": "wrongpassword"})
        # Next attempt with correct password should still be locked
        resp = client.post("/login", data={"token": "testkey123"})
        assert resp.status_code == 200 or resp.status_code == 429
        html = resp.data.decode()
        assert "locked" in html.lower() or "too many" in html.lower() or resp.status_code == 429

        # Clean up lockout state so other tests aren't affected
        if lockout_file.exists():
            lockout_file.unlink()
        # Reset the cached lockout file path
        import web.blueprints.auth as _auth_mod
        _auth_mod._LOCKOUT_FILE = None


# -- Issue 5: Secure cookie defaults ----------------------------------

class TestSecureCookieDefaults:
    def test_session_cookie_httponly(self, app):
        """Session cookie must be HttpOnly."""
        assert app.config.get("SESSION_COOKIE_HTTPONLY", True) is True

    def test_session_cookie_samesite(self, app):
        """Session cookie must have SameSite attribute."""
        samesite = app.config.get("SESSION_COOKIE_SAMESITE", "Lax")
        assert samesite in ("Lax", "Strict")
