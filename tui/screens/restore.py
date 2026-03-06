from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, Input, RadioSet, RadioButton, Switch
from textual.containers import Vertical, Horizontal
from textual import work, on

from tui.config import list_conf_dir, parse_conf, CONFIG_DIR
from tui.backend import run_cli
from tui.jobs import job_manager
from tui.widgets import ConfirmDialog, FolderPicker


class RestoreScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        with Vertical(id="restore-screen"):
            yield Static("Restore", id="screen-title")
            if not targets or not remotes:
                yield Static("Both targets and remotes must be configured for restore.")
            else:
                yield Static("Target:")
                yield Select([(t, t) for t in targets], id="restore-target", prompt="Select target")
                yield Static("Remote:")
                yield Select([(r, r) for r in remotes], id="restore-remote", prompt="Select remote")
                yield Static("Snapshot:")
                yield Select([], id="restore-snapshot", prompt="Select target and remote first")
                yield Static("Restore location:")
                with RadioSet(id="restore-location"):
                    yield RadioButton("In-place (original)", value=True)
                    yield RadioButton("Custom directory")
                with Horizontal(id="restore-dest-row"):
                    yield Input(placeholder="Destination directory (e.g. /tmp/restore)", id="restore-dest")
                    yield Button("Browse...", id="btn-browse-dest")
                with Horizontal(id="restore-mysql-row"):
                    yield Static("Restore MySQL databases:")
                    yield Switch(value=True, id="restore-mysql-switch")
                with Horizontal(id="restore-buttons"):
                    yield Button("Restore", variant="primary", id="btn-restore")
                    yield Button("Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.query_one("#restore-mysql-row").display = False
        except Exception:
            pass

    @on(Select.Changed, "#restore-target")
    def _on_target_changed(self, event: Select.Changed) -> None:
        self._try_load_snapshots()
        self._update_mysql_visibility()

    @on(Select.Changed, "#restore-remote")
    def _on_remote_changed(self, event: Select.Changed) -> None:
        self._try_load_snapshots()

    def _update_mysql_visibility(self) -> None:
        try:
            target_sel = self.query_one("#restore-target", Select)
            mysql_row = self.query_one("#restore-mysql-row")
            if isinstance(target_sel.value, str):
                data = parse_conf(CONFIG_DIR / "targets.d" / f"{target_sel.value}.conf")
                mysql_row.display = data.get("TARGET_MYSQL_ENABLED", "no") == "yes"
            else:
                mysql_row.display = False
        except Exception:
            pass

    @work
    async def _try_load_snapshots(self) -> None:
        try:
            target_sel = self.query_one("#restore-target", Select)
            remote_sel = self.query_one("#restore-remote", Select)
        except Exception:
            return
        if not isinstance(target_sel.value, str) or not isinstance(remote_sel.value, str):
            return
        target = str(target_sel.value)
        remote = str(remote_sel.value)
        snap_sel = self.query_one("#restore-snapshot", Select)
        snap_sel.set_options([])
        self.notify(f"Loading snapshots for {target}/{remote}...")
        rc, stdout, stderr = await run_cli("snapshots", "list", f"--target={target}", f"--remote={remote}")
        lines = [l.strip() for l in stdout.splitlines() if l.strip() and not l.startswith("===")]
        if lines:
            snap_sel.set_options([(s, s) for s in lines])
        else:
            self.notify("No snapshots found", severity="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-browse-dest":
            self.app.push_screen(
                FolderPicker("Select destination directory"),
                callback=self._dest_selected,
            )
        elif event.button.id == "btn-restore":
            self._start_restore()

    def _dest_selected(self, path: str | None) -> None:
        if path:
            self.query_one("#restore-dest", Input).value = path

    def _start_restore(self) -> None:
        target_sel = self.query_one("#restore-target", Select)
        remote_sel = self.query_one("#restore-remote", Select)
        snap_sel = self.query_one("#restore-snapshot", Select)
        if not isinstance(target_sel.value, str):
            self.notify("Select a target", severity="error")
            return
        if not isinstance(remote_sel.value, str):
            self.notify("Select a remote", severity="error")
            return
        if not isinstance(snap_sel.value, str):
            self.notify("Select a snapshot", severity="error")
            return
        target = str(target_sel.value)
        remote = str(remote_sel.value)
        snapshot = str(snap_sel.value)
        radio = self.query_one("#restore-location", RadioSet)
        dest_input = self.query_one("#restore-dest", Input)
        dest = "" if radio.pressed_index == 0 else dest_input.value
        try:
            restore_mysql = self.query_one("#restore-mysql-switch", Switch).value
        except Exception:
            restore_mysql = True
        skip_mysql = not restore_mysql
        msg = f"Restore snapshot?\n\nTarget: {target}\nRemote: {remote}\nSnapshot: {snapshot}"
        if dest:
            msg += f"\nDestination: {dest}"
        else:
            msg += "\nLocation: In-place"
        if skip_mysql:
            msg += "\nMySQL: Skip"
        self.app.push_screen(
            ConfirmDialog(msg, "Confirm Restore"),
            callback=lambda ok: self._do_restore(target, remote, snapshot, dest, skip_mysql) if ok else None,
        )

    @work
    async def _do_restore(self, target: str, remote: str, snapshot: str, dest: str, skip_mysql: bool = False) -> None:
        job = job_manager.create_job("restore", f"Restore: {target}")
        self.notify("Restore started -- view in Running Tasks")
        args = ["restore", f"--target={target}", f"--remote={remote}", f"--snapshot={snapshot}"]
        if dest:
            args.append(f"--dest={dest}")
        if skip_mysql:
            args.append("--skip-mysql")
        rc = await job_manager.run_job(self.app, job, *args)
        if rc == 0:
            self.notify("Restore completed successfully", severity="information")
        else:
            self.notify(f"Restore failed (exit code {rc})", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()
