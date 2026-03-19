import os
import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select, Switch, Collapsible
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from textual import work

from tui.config import parse_conf, write_conf, CONFIG_DIR
from tui.models import AppSettings
from tui.backend import run_cli
from tui.widgets import DocsPanel, OperationLog


class SettingsScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        conf = parse_conf(CONFIG_DIR / "gniza.conf")
        settings = AppSettings.from_conf(conf)
        self._version = "unknown"
        gniza_dir = os.environ.get("GNIZA_DIR", str(Path(__file__).resolve().parent.parent.parent))
        constants_path = Path(gniza_dir) / "lib" / "constants.sh"
        if constants_path.exists():
            for line in constants_path.read_text().splitlines():
                if line.startswith("readonly GNIZA4LINUX_VERSION="):
                    self._version = line.split('"')[1]
                    break
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="settings-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("← Back", id="btn-back", classes="back-btn")
                    yield Static("Settings", id="screen-title")
                with Vertical(classes="settings-section", id="section-general"):
                    yield Static("Log Level:")
                    yield Select(
                        [("Debug", "debug"), ("Info", "info"), ("Warning", "warn"), ("Error", "error")],
                        id="set-loglevel",
                        value=settings.log_level.lower(),
                    )
                    yield Static("Log Retention (days):")
                    yield Input(value=settings.log_retain, id="set-logretain")
                    yield Static("Default Retention Count:")
                    yield Input(value=settings.retention_count, id="set-retention")
                    yield Static("Default Bandwidth Limit (KB/s, 0=unlimited):")
                    yield Input(value=settings.bwlimit, id="set-bwlimit")
                    yield Static("Disk Usage Threshold (%, 0=disable):")
                    yield Input(value=settings.disk_usage_threshold, id="set-diskthreshold")
                    yield Static("Simultaneous Jobs (0=unlimited):")
                    yield Input(value=settings.max_concurrent_jobs, id="set-maxjobs")
                    yield Static("Working Directory (empty = default):")
                    yield Input(value=settings.work_dir, placeholder="auto-detected", id="set-workdir")
                    yield Static("Extra rsync options:")
                    yield Input(value=settings.rsync_extra_opts, id="set-rsyncopts")
                    yield Static("Rsync Compression:")
                    yield Select(
                        [("Off", "no"), ("zlib (default)", "zlib"), ("zstd (faster)", "zstd")],
                        id="set-rsynccompress",
                        value=settings.rsync_compress if settings.rsync_compress in ("no", "zlib", "zstd") else "no",
                    )
                    yield Static("Rsync Checksum (detect changes by content):")
                    yield Switch(value=settings.rsync_checksum == "yes", id="set-rsyncchecksum")
                with Vertical(classes="settings-section", id="section-notifications"):
                    yield Static("Notify On:")
                    yield Select(
                        [("Always", "always"), ("Failure only", "failure"), ("Never", "never")],
                        id="set-notifyon",
                        value=settings.notify_on,
                    )
                    yield Static("Stale Alert Hours (0=disabled):")
                    yield Input(value=settings.stale_alert_hours, id="set-stale-hours")
                    with Collapsible(title="Email (SMTP)", collapsed=True):
                        yield Static("Notification Email:")
                        yield Input(value=settings.notify_email, id="set-email")
                        yield Static("SMTP Host:")
                        yield Input(value=settings.smtp_host, id="set-smtphost")
                        yield Static("SMTP Port:")
                        yield Input(value=settings.smtp_port, id="set-smtpport")
                        yield Static("SMTP User:")
                        yield Input(value=settings.smtp_user, id="set-smtpuser")
                        yield Static("SMTP Password:")
                        yield Input(value=settings.smtp_password, password=True, id="set-smtppass")
                        yield Static("SMTP From:")
                        yield Input(value=settings.smtp_from, id="set-smtpfrom")
                        yield Static("SMTP Security:")
                        yield Select(
                            [("TLS", "tls"), ("SSL", "ssl"), ("None", "none")],
                            id="set-smtpsec",
                            value=settings.smtp_security,
                        )
                        yield Button("Test Email", id="btn-test-email")
                    with Collapsible(title="Telegram", collapsed=True):
                        yield Static("Bot Token:")
                        yield Input(value=settings.telegram_bot_token, password=True, id="set-tg-token")
                        yield Static("Chat ID:")
                        yield Input(value=settings.telegram_chat_id, id="set-tg-chatid")
                        yield Button("Test Telegram", id="btn-test-telegram")
                    with Collapsible(title="Webhook (Slack / Discord)", collapsed=True):
                        yield Static("Webhook URL:")
                        yield Input(value=settings.webhook_url, id="set-webhook-url")
                        yield Static("Type:")
                        yield Select(
                            [("Slack", "slack"), ("Discord", "discord"), ("Generic", "generic")],
                            id="set-webhook-type",
                            value=settings.webhook_type if settings.webhook_type in ("slack", "discord", "generic") else "slack",
                        )
                        yield Button("Test Webhook", id="btn-test-webhook")
                    with Collapsible(title="ntfy", collapsed=True):
                        yield Static("ntfy URL:")
                        yield Input(value=settings.ntfy_url, id="set-ntfy-url")
                        yield Static("Auth Token (optional):")
                        yield Input(value=settings.ntfy_token, password=True, id="set-ntfy-token")
                        yield Static("Default Priority:")
                        yield Select(
                            [("Min", "min"), ("Low", "low"), ("Default", "default"), ("High", "high"), ("Urgent", "urgent")],
                            id="set-ntfy-priority",
                            value=settings.ntfy_priority if settings.ntfy_priority in ("min", "low", "default", "high", "urgent") else "default",
                        )
                        yield Button("Test ntfy", id="btn-test-ntfy")
                    with Collapsible(title="Healthchecks.io", collapsed=True):
                        yield Static("Ping URL:")
                        yield Input(value=settings.healthchecks_url, id="set-hc-url")
                        yield Button("Test Healthcheck", id="btn-test-healthcheck")
                with Vertical(classes="settings-section", id="section-ssh"):
                    yield Static("SSH Timeout:")
                    yield Input(value=settings.ssh_timeout, id="set-sshtimeout")
                    yield Static("SSH Retries:")
                    yield Input(value=settings.ssh_retries, id="set-sshretries")
                with Vertical(classes="settings-section", id="section-web"):
                    yield Static("Port:")
                    yield Input(value=settings.web_port, id="set-web-port")
                    yield Static("Host:")
                    yield Input(value=settings.web_host, id="set-web-host")
                    yield Static("Password:")
                    yield Input(value=settings.web_api_key, password=True, id="set-web-key")
                with Vertical(classes="settings-section", id="section-update"):
                    yield Static(f"gniza v{self._version}")
                    yield Button("Check for Updates", id="btn-check-update")
                    yield Button("Update Now", variant="warning", id="btn-update-now")
                with Horizontal(id="set-buttons"):
                    yield Button("Save", variant="primary", id="btn-save")
            yield DocsPanel.for_screen("settings-screen")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#section-general").border_title = "General"
        self.query_one("#section-notifications").border_title = "Notifications"
        self.query_one("#section-ssh").border_title = "SSH"
        self.query_one("#section-web").border_title = "Web Dashboard"
        self.query_one("#section-update").border_title = "Update"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-save":
            self._save()
        elif event.button.id == "btn-test-email":
            self._save()
            self._send_test_email()
        elif event.button.id == "btn-test-telegram":
            self._save()
            self._send_test_notification("telegram")
        elif event.button.id == "btn-test-webhook":
            self._save()
            self._send_test_notification("webhook")
        elif event.button.id == "btn-test-ntfy":
            self._save()
            self._send_test_notification("ntfy")
        elif event.button.id == "btn-test-healthcheck":
            self._save()
            self._send_test_notification("healthcheck")
        elif event.button.id == "btn-check-update":
            self._check_for_update()
        elif event.button.id == "btn-update-now":
            self._apply_update()

    def _get_select_val(self, sel_id: str, default: str) -> str:
        sel = self.query_one(sel_id, Select)
        return str(sel.value) if isinstance(sel.value, str) else default

    def _save(self) -> None:
        settings = AppSettings(
            log_level=self._get_select_val("#set-loglevel", "info"),
            log_retain=self.query_one("#set-logretain", Input).value.strip() or "30",
            retention_count=self.query_one("#set-retention", Input).value.strip() or "7",
            bwlimit=self.query_one("#set-bwlimit", Input).value.strip() or "0",
            notify_email=self.query_one("#set-email", Input).value.strip(),
            notify_on=self._get_select_val("#set-notifyon", "failure"),
            smtp_host=self.query_one("#set-smtphost", Input).value.strip(),
            smtp_port=self.query_one("#set-smtpport", Input).value.strip() or "587",
            smtp_user=self.query_one("#set-smtpuser", Input).value.strip(),
            smtp_password=self.query_one("#set-smtppass", Input).value,
            smtp_from=self.query_one("#set-smtpfrom", Input).value.strip(),
            smtp_security=self._get_select_val("#set-smtpsec", "tls"),
            telegram_bot_token=self.query_one("#set-tg-token", Input).value,
            telegram_chat_id=self.query_one("#set-tg-chatid", Input).value.strip(),
            webhook_url=self.query_one("#set-webhook-url", Input).value.strip(),
            webhook_type=self._get_select_val("#set-webhook-type", "slack"),
            ntfy_url=self.query_one("#set-ntfy-url", Input).value.strip(),
            ntfy_token=self.query_one("#set-ntfy-token", Input).value,
            ntfy_priority=self._get_select_val("#set-ntfy-priority", "default"),
            healthchecks_url=self.query_one("#set-hc-url", Input).value.strip(),
            stale_alert_hours=self.query_one("#set-stale-hours", Input).value.strip() or "0",
            ssh_timeout=self.query_one("#set-sshtimeout", Input).value.strip() or "30",
            ssh_retries=self.query_one("#set-sshretries", Input).value.strip() or "3",
            rsync_extra_opts=self.query_one("#set-rsyncopts", Input).value.strip(),
            rsync_compress=self._get_select_val("#set-rsynccompress", "no"),
            rsync_checksum="yes" if self.query_one("#set-rsyncchecksum", Switch).value else "no",
            disk_usage_threshold=self.query_one("#set-diskthreshold", Input).value.strip() or "95",
            max_concurrent_jobs=self.query_one("#set-maxjobs", Input).value.strip() or "1",
            work_dir=self.query_one("#set-workdir", Input).value.strip(),
            web_port=self.query_one("#set-web-port", Input).value.strip() or "2323",
            web_host=self.query_one("#set-web-host", Input).value.strip() or "0.0.0.0",
            web_api_key=self.query_one("#set-web-key", Input).value,
        )
        conf_path = CONFIG_DIR / "gniza.conf"
        old_data = parse_conf(conf_path)
        old_api_key = old_data.get("WEB_API_KEY", "")
        write_conf(conf_path, settings.to_conf())

        import hmac
        if not hmac.compare_digest(settings.web_api_key, old_api_key):
            self.notify("Settings saved. Restarting web service (password changed)...")
            self._restart_web_service()
        else:
            self.notify("Settings saved.")

    @work(thread=True)
    def _restart_web_service(self) -> None:
        """Restart gniza-web in a background thread (don't block TUI)."""
        import time
        time.sleep(1)  # brief delay so the config write completes
        if os.geteuid() == 0:
            subprocess.run(["systemctl", "restart", "gniza-web"], check=False, timeout=10)
        else:
            subprocess.run(["systemctl", "--user", "restart", "gniza-web"], check=False, timeout=10)

    @work
    async def _send_test_email(self) -> None:
        log_screen = OperationLog("Send Test Email", show_spinner=True)
        self.app.push_screen(log_screen)
        log_screen.write("Sending test email...")
        rc, stdout, stderr = await run_cli("test-email")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        log_screen.finish()

    @work
    async def _send_test_notification(self, channel: str) -> None:
        label = channel.title()
        log_screen = OperationLog(f"Test {label} Notification", show_spinner=True)
        self.app.push_screen(log_screen)
        log_screen.write(f"Sending test {channel} notification...")
        rc, stdout, stderr = await run_cli("test-notification", channel)
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        log_screen.finish()

    @work
    async def _check_for_update(self) -> None:
        log_screen = OperationLog("Check for Updates", show_spinner=True)
        self.app.push_screen(log_screen)
        log_screen.write("Checking for updates...")
        rc, stdout, stderr = await run_cli("update", "--check")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        log_screen.finish()

    @work
    async def _apply_update(self) -> None:
        log_screen = OperationLog("Update gniza", show_spinner=True)
        self.app.push_screen(log_screen)
        log_screen.write("Applying update...")
        rc, stdout, stderr = await run_cli("update")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        log_screen.finish()

    def action_go_back(self) -> None:
        self.app.pop_screen()
