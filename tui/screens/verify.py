from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir
from tui.backend import stream_cli
from tui.widgets import ConfirmDialog, OperationLog


class VerifyScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        targets = list_conf_dir("targets.d")
        with Vertical(id="verify-screen"):
            yield Static("Verify Backups", id="screen-title")
            if not targets:
                yield Static("No targets configured.")
            else:
                yield Static("Target:")
                yield Select(
                    [(t, t) for t in targets],
                    id="verify-target",
                    prompt="Select target",
                )
                with Horizontal(id="verify-buttons"):
                    yield Button("Verify Selected", variant="primary", id="btn-verify")
                    yield Button("Verify All", variant="warning", id="btn-verify-all")
                    yield Button("Back", id="btn-back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-verify":
            target_sel = self.query_one("#verify-target", Select)
            if target_sel.value is Select.BLANK:
                self.notify("Select a target first", severity="error")
                return
            self._do_verify(str(target_sel.value))
        elif event.button.id == "btn-verify-all":
            self._do_verify_all()

    @work
    async def _do_verify(self, target: str) -> None:
        log_screen = OperationLog(f"Verify: {target}")
        self.app.push_screen(log_screen)
        rc = await stream_cli(log_screen.write, "verify", f"--target={target}")
        if rc == 0:
            log_screen.write("\n[green]Verification completed successfully.[/green]")
        else:
            log_screen.write(f"\n[red]Verification failed (exit code {rc}).[/red]")

    @work
    async def _do_verify_all(self) -> None:
        log_screen = OperationLog("Verify All Targets")
        self.app.push_screen(log_screen)
        rc = await stream_cli(log_screen.write, "verify", "--all")
        if rc == 0:
            log_screen.write("\n[green]All verifications completed.[/green]")
        else:
            log_screen.write(f"\n[red]Verification failed (exit code {rc}).[/red]")

    def action_go_back(self) -> None:
        self.app.pop_screen()
