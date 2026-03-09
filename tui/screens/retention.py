from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from tui.config import CONFIG_DIR, list_conf_dir, parse_conf, update_conf_key
from tui.jobs import job_manager
from tui.widgets import ConfirmDialog, DocsPanel


class RetentionScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="retention-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("\u2190 Back", id="btn-back", classes="back-btn")
                    yield Static("Retention Management", id="screen-title")
                yield Static("Default Retention Count:", id="retention-label")
                yield Input(id="retention-input", placeholder="e.g. 7")
                with Horizontal(id="retention-save-bar"):
                    yield Button("Save Default", variant="primary", id="btn-save")
                yield Static("Run Retention Cleanup:", id="cleanup-label")
                yield Select([], id="source-select", allow_blank=True)
                with Horizontal(id="retention-run-bar"):
                    yield Button("Run Cleanup", variant="warning", id="btn-cleanup")
            yield DocsPanel.for_screen("retention-screen")
        yield Footer()

    def on_mount(self) -> None:
        data = parse_conf(CONFIG_DIR / "gniza.conf")
        retention_count = data.get("RETENTION_COUNT", "7")
        self.query_one("#retention-input", Input).value = retention_count

        targets = list_conf_dir("targets.d")
        options = [("All Sources", "__all__")] + [(t, t) for t in targets]
        select = self.query_one("#source-select", Select)
        select.set_options(options)
        select.value = "__all__"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-save":
            self._save_default()
        elif event.button.id == "btn-cleanup":
            self._confirm_cleanup()

    def _save_default(self) -> None:
        value = self.query_one("#retention-input", Input).value.strip()
        if not value.isdigit() or int(value) < 1:
            self.notify("Retention count must be a positive number.", severity="error")
            return
        update_conf_key(CONFIG_DIR / "gniza.conf", "RETENTION_COUNT", value)
        self.notify(f"Default retention count set to {value}.")

    def _confirm_cleanup(self) -> None:
        select = self.query_one("#source-select", Select)
        source = select.value
        if source == "__all__":
            msg = "Run retention cleanup on ALL sources?"
        else:
            msg = f"Run retention cleanup on source: {source}?"
        self.app.push_screen(
            ConfirmDialog(msg, "Confirm Cleanup"),
            callback=lambda ok: self._do_cleanup(source) if ok else None,
        )

    def _do_cleanup(self, source) -> None:
        if source == "__all__":
            label = "Retention (all)"
            job = job_manager.create_job("retention", label)
            job_manager.start_job(self.app, job, "retention", "--all")
        else:
            label = f"Retention {source}"
            job = job_manager.create_job("retention", label)
            job_manager.start_job(self.app, job, "retention", f"--source={source}")
        self.app.switch_screen("running_tasks")

    def action_go_back(self) -> None:
        self.app.pop_screen()
