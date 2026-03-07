from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal
from tui.config import list_conf_dir, has_targets, has_remotes
from tui.jobs import job_manager
from tui.widgets import ConfirmDialog, DocsPanel


class BackupScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="backup-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("← Back", id="btn-back", classes="back-btn", can_focus=False)
                    yield Static("Backup", id="screen-title")
                if not targets:
                    yield Static("No sources configured. Add a source first.")
                else:
                    yield Static("Source:")
                    yield Select(
                        [(t, t) for t in targets],
                        id="backup-target",
                        prompt="Select source",
                    )
                    yield Static("Destination:")
                    yield Select(
                        [("Default (all)", "")] + [(r, r) for r in remotes],
                        id="backup-remote",
                        prompt="Select destination",
                        value="",
                    )
                    with Horizontal(id="backup-buttons"):
                        yield Button("Run Backup", variant="primary", id="btn-backup")
                        yield Button("Backup All", variant="warning", id="btn-backup-all")
            yield DocsPanel.for_screen("backup-screen")
        yield Footer()

    def on_screen_resume(self) -> None:
        self._refresh_selects()

    def _refresh_selects(self) -> None:
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        try:
            ts = self.query_one("#backup-target", Select)
            old_target = ts.value
            ts.set_options([(t, t) for t in targets])
            if old_target in targets:
                ts.value = old_target
        except Exception:
            pass
        try:
            rs = self.query_one("#backup-remote", Select)
            old_remote = rs.value
            rs.set_options([("Default (all)", "")] + [(r, r) for r in remotes])
            if old_remote == "" or old_remote in remotes:
                rs.value = old_remote
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-backup":
            target_sel = self.query_one("#backup-target", Select)
            if not isinstance(target_sel.value, str):
                self.notify("Please select a source", severity="error")
                return
            target = str(target_sel.value)
            remote_sel = self.query_one("#backup-remote", Select)
            remote = str(remote_sel.value) if isinstance(remote_sel.value, str) else ""
            msg = f"Run backup for source '{target}'?"
            if remote:
                msg += f"\nDestination: {remote}"
            self.app.push_screen(
                ConfirmDialog(msg, "Confirm Backup"),
                callback=lambda ok: self._do_backup(target, remote) if ok else None,
            )
        elif event.button.id == "btn-backup-all":
            self.app.push_screen(
                ConfirmDialog("Backup ALL sources now?", "Confirm Backup"),
                callback=lambda ok: self._do_backup_all() if ok else None,
            )

    def _do_backup(self, target: str, remote: str) -> None:
        job = job_manager.create_job("backup", f"Backup: {target}")
        args = ["backup", f"--source={target}"]
        if remote:
            args.append(f"--destination={remote}")
        job_manager.start_job(self.app, job, *args)
        self.app.switch_screen("running_tasks")

    def _do_backup_all(self) -> None:
        job = job_manager.create_job("backup", "Backup All Targets")
        job_manager.start_job(self.app, job, "backup", "--all")
        self.app.switch_screen("running_tasks")

    def action_go_back(self) -> None:
        self.app.pop_screen()
