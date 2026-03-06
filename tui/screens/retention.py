from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, Input
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, parse_conf, update_conf_key, CONFIG_DIR
from tui.backend import stream_cli
from tui.widgets import ConfirmDialog, OperationLog


class RetentionScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        targets = list_conf_dir("targets.d")
        conf = parse_conf(CONFIG_DIR / "gniza.conf")
        current_count = conf.get("RETENTION_COUNT", "30")
        with Vertical(id="retention-screen"):
            yield Static("Retention Cleanup", id="screen-title")
            if not targets:
                yield Static("No targets configured.")
            else:
                yield Static("Target:")
                yield Select(
                    [(t, t) for t in targets],
                    id="ret-target",
                    prompt="Select target",
                )
                with Horizontal(id="ret-buttons"):
                    yield Button("Run Cleanup", variant="primary", id="btn-cleanup")
                    yield Button("Cleanup All", variant="warning", id="btn-cleanup-all")
            yield Static("")
            yield Static("Default retention count:")
            with Horizontal():
                yield Input(value=current_count, id="ret-count", placeholder="30")
                yield Button("Save", id="btn-save-count")
            yield Button("Back", id="btn-back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-cleanup":
            target_sel = self.query_one("#ret-target", Select)
            if not isinstance(target_sel.value, str):
                self.notify("Select a target first", severity="error")
                return
            target = str(target_sel.value)
            self.app.push_screen(
                ConfirmDialog(f"Run retention cleanup for '{target}'?", "Confirm"),
                callback=lambda ok: self._do_cleanup(target) if ok else None,
            )
        elif event.button.id == "btn-cleanup-all":
            self.app.push_screen(
                ConfirmDialog("Run retention cleanup for ALL targets?", "Confirm"),
                callback=lambda ok: self._do_cleanup_all() if ok else None,
            )
        elif event.button.id == "btn-save-count":
            val = self.query_one("#ret-count", Input).value.strip()
            if not val.isdigit() or int(val) < 1:
                self.notify("Retention count must be a positive integer.", severity="error")
                return
            update_conf_key(CONFIG_DIR / "gniza.conf", "RETENTION_COUNT", val)
            self.notify(f"Retention count set to {val}.")

    @work
    async def _do_cleanup(self, target: str) -> None:
        log_screen = OperationLog(f"Retention: {target}")
        self.app.push_screen(log_screen)
        await log_screen.wait_ready()
        rc = await stream_cli(log_screen.write, "retention", f"--target={target}")
        if rc == 0:
            log_screen.write("\n[green]Cleanup completed.[/green]")
        else:
            log_screen.write(f"\n[red]Cleanup failed (exit code {rc}).[/red]")
        log_screen.finish()

    @work
    async def _do_cleanup_all(self) -> None:
        log_screen = OperationLog("Retention: All Targets")
        self.app.push_screen(log_screen)
        await log_screen.wait_ready()
        rc = await stream_cli(log_screen.write, "retention", "--all")
        if rc == 0:
            log_screen.write("\n[green]All cleanups completed.[/green]")
        else:
            log_screen.write(f"\n[red]Cleanup failed (exit code {rc}).[/red]")
        log_screen.finish()

    def action_go_back(self) -> None:
        self.app.pop_screen()
