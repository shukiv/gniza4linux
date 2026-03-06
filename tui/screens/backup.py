from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, has_targets, has_remotes
from tui.backend import stream_cli
from tui.widgets import ConfirmDialog, OperationLog


class BackupScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        with Vertical(id="backup-screen"):
            yield Static("Backup", id="screen-title")
            if not targets:
                yield Static("No targets configured. Add a target first.")
            else:
                yield Static("Target:")
                yield Select(
                    [(t, t) for t in targets],
                    id="backup-target",
                    prompt="Select target",
                )
                yield Static("Remote (optional):")
                yield Select(
                    [("Default (all)", "")] + [(r, r) for r in remotes],
                    id="backup-remote",
                    prompt="Select remote",
                    value="",
                )
                with Horizontal(id="backup-buttons"):
                    yield Button("Run Backup", variant="primary", id="btn-backup")
                    yield Button("Backup All", variant="warning", id="btn-backup-all")
                    yield Button("Back", id="btn-back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        with open("/tmp/gniza_debug.log", "a") as f:
            f.write(f"on_button_pressed: {event.button.id}\n")
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-backup":
            target_sel = self.query_one("#backup-target", Select)
            if not isinstance(target_sel.value, str):
                self.notify("Please select a target", severity="error")
                return
            target = str(target_sel.value)
            remote_sel = self.query_one("#backup-remote", Select)
            remote = str(remote_sel.value) if isinstance(remote_sel.value, str) else ""
            # Skip ConfirmDialog — go straight to OperationLog for debugging
            self._confirmed_backup(target, remote)
        elif event.button.id == "btn-backup-all":
            self.app.push_screen(
                ConfirmDialog("Backup ALL targets now?", "Confirm Backup"),
                callback=lambda ok: self._confirmed_backup_all() if ok else None,
            )

    def _confirmed_backup(self, target: str, remote: str) -> None:
        import traceback
        dbg = open("/tmp/gniza_debug.log", "a")
        dbg.write("=== _confirmed_backup called ===\n")
        dbg.write(f"target={target} remote={remote}\n")
        try:
            log_screen = OperationLog(f"Backup: {target}")
            dbg.write("OperationLog created\n")
            self.app.push_screen(log_screen)
            dbg.write("push_screen called\n")
            self._run_backup(log_screen, target, remote)
            dbg.write("_run_backup started\n")
        except Exception as e:
            dbg.write(f"ERROR: {e}\n")
            dbg.write(traceback.format_exc())
        dbg.close()

    def _confirmed_backup_all(self) -> None:
        log_screen = OperationLog("Backup All Targets")
        self.app.push_screen(log_screen)
        self._run_backup_all(log_screen)

    @work
    async def _run_backup(self, log_screen: OperationLog, target: str, remote: str) -> None:
        args = ["backup", f"--target={target}"]
        if remote:
            args.append(f"--remote={remote}")
        rc = await stream_cli(log_screen.write, *args)
        if rc == 0:
            log_screen.write("\n[green]Backup completed successfully.[/green]")
        else:
            log_screen.write(f"\n[red]Backup failed (exit code {rc}).[/red]")
        log_screen.finish()

    @work
    async def _run_backup_all(self, log_screen: OperationLog) -> None:
        rc = await stream_cli(log_screen.write, "backup", "--all")
        if rc == 0:
            log_screen.write("\n[green]All backups completed.[/green]")
        else:
            log_screen.write(f"\n[red]Backup failed (exit code {rc}).[/red]")
        log_screen.finish()

    def action_go_back(self) -> None:
        self.app.pop_screen()
