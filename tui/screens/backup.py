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
            msg = f"Run backup for target '{target}'?"
            if remote:
                msg += f"\nRemote: {remote}"
            self.app.push_screen(
                ConfirmDialog(msg, "Confirm Backup"),
                callback=lambda ok: self._do_backup(target, remote) if ok else None,
            )
        elif event.button.id == "btn-backup-all":
            self.app.push_screen(
                ConfirmDialog("Backup ALL targets now?", "Confirm Backup"),
                callback=lambda ok: self._do_backup_all() if ok else None,
            )

    @work
    async def _do_backup(self, target: str, remote: str) -> None:
        log_screen = OperationLog(f"Backup: {target}")
        self.app.push_screen(log_screen)
        args = ["backup", f"--target={target}"]
        if remote:
            args.append(f"--remote={remote}")
        rc = await stream_cli(log_screen.write, *args)
        if rc == 0:
            log_screen.write("\n[green]Backup completed successfully.[/green]")
        else:
            log_screen.write(f"\n[red]Backup failed (exit code {rc}).[/red]")

    @work
    async def _do_backup_all(self) -> None:
        log_screen = OperationLog("Backup All Targets")
        self.app.push_screen(log_screen)
        rc = await stream_cli(log_screen.write, "backup", "--all")
        if rc == 0:
            log_screen.write("\n[green]All backups completed.[/green]")
        else:
            log_screen.write(f"\n[red]Backup failed (exit code {rc}).[/red]")

    def action_go_back(self) -> None:
        self.app.pop_screen()
