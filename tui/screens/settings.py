from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select
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
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="settings-screen"):
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
                    yield Static("Extra rsync options:")
                    yield Input(value=settings.rsync_extra_opts, id="set-rsyncopts")
                with Vertical(classes="settings-section", id="section-email"):
                    yield Static("Notification Email:")
                    yield Input(value=settings.notify_email, id="set-email")
                    yield Static("Notify On:")
                    yield Select(
                        [("Always", "always"), ("Failure only", "failure"), ("Never", "never")],
                        id="set-notifyon",
                        value=settings.notify_on,
                    )
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
                    yield Static("API Key:")
                    yield Input(value=settings.web_api_key, password=True, id="set-web-key")
                with Horizontal(id="set-buttons"):
                    yield Button("Save", variant="primary", id="btn-save")
                    yield Button("Send Test Email", id="btn-test-email")
            yield DocsPanel.for_screen("settings-screen")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#section-general").border_title = "General"
        self.query_one("#section-email").border_title = "Email Notifications"
        self.query_one("#section-ssh").border_title = "SSH"
        self.query_one("#section-web").border_title = "Web Dashboard"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-save":
            self._save()
        elif event.button.id == "btn-test-email":
            self._save()
            self._send_test_email()

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
            ssh_timeout=self.query_one("#set-sshtimeout", Input).value.strip() or "30",
            ssh_retries=self.query_one("#set-sshretries", Input).value.strip() or "3",
            rsync_extra_opts=self.query_one("#set-rsyncopts", Input).value.strip(),
            disk_usage_threshold=self.query_one("#set-diskthreshold", Input).value.strip() or "95",
            web_port=self.query_one("#set-web-port", Input).value.strip() or "2323",
            web_host=self.query_one("#set-web-host", Input).value.strip() or "0.0.0.0",
            web_api_key=self.query_one("#set-web-key", Input).value,
        )
        conf_path = CONFIG_DIR / "gniza.conf"
        write_conf(conf_path, settings.to_conf())
        self.notify("Settings saved.")

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

    def action_go_back(self) -> None:
        self.app.pop_screen()
