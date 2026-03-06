from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, has_targets, has_remotes
from tui.jobs import job_manager
from tui.widgets import ConfirmDialog


class BackupScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
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
        job = job_manager.create_job("backup", f"Backup: {target}")
        self.notify("Backup started -- view in Running Tasks")
        args = ["backup", f"--target={target}"]
        if remote:
            args.append(f"--remote={remote}")
        await job_manager.run_job(self.app, job, *args)

    @work
    async def _do_backup_all(self) -> None:
        job = job_manager.create_job("backup", "Backup All Targets")
        self.notify("Backup All started -- view in Running Tasks")
        await job_manager.run_job(self.app, job, "backup", "--all")

    def action_go_back(self) -> None:
        self.app.pop_screen()
