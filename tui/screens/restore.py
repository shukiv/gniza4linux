from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, Input, RadioSet, RadioButton, Switch
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from textual import work, on

import os

from tui.config import list_conf_dir, parse_conf, CONFIG_DIR
from tui.backend import run_cli
from tui.jobs import job_manager
from tui.widgets import ConfirmDialog, FolderPicker, DocsPanel

_FORBIDDEN_DEST_PREFIXES = ("/", "/root", "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/lib", "/boot", "/dev", "/proc", "/sys", "/etc", "/lib", "/lib64")


class RestoreScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="restore-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("← Back", id="btn-back", classes="back-btn")
                    yield Static("Restore", id="screen-title")
                if not targets or not remotes:
                    yield Static("Both sources and destinations must be configured for restore.")
                else:
                    yield Static("Source:")
                    yield Select([(t, t) for t in targets], id="restore-target", prompt="Select source")
                    yield Static("Destination:")
                    yield Select([(r, r) for r in remotes], id="restore-remote", prompt="Select destination")
                    yield Static("Snapshot:")
                    yield Select([], id="restore-snapshot", prompt="Select source and destination first")
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
                    with Horizontal(id="restore-pgsql-row"):
                        yield Static("Restore PostgreSQL databases:")
                        yield Switch(value=True, id="restore-pgsql-switch")
                    with Horizontal(id="restore-buttons"):
                        yield Button("Restore", variant="primary", id="btn-restore")
            yield DocsPanel.for_screen("restore-screen")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.query_one("#restore-mysql-row").display = False
        except Exception:
            pass
        try:
            self.query_one("#restore-pgsql-row").display = False
        except Exception:
            pass

    @on(Select.Changed, "#restore-target")
    def _on_target_changed(self, event: Select.Changed) -> None:
        self._try_load_snapshots()
        self._update_mysql_visibility()
        self._update_pgsql_visibility()

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

    def _update_pgsql_visibility(self) -> None:
        try:
            target_sel = self.query_one("#restore-target", Select)
            pgsql_row = self.query_one("#restore-pgsql-row")
            if isinstance(target_sel.value, str):
                data = parse_conf(CONFIG_DIR / "targets.d" / f"{target_sel.value}.conf")
                pgsql_row.display = data.get("TARGET_POSTGRESQL_ENABLED", "no") == "yes"
            else:
                pgsql_row.display = False
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
        rc, stdout, stderr = await run_cli("snapshots", "list", f"--source={target}", f"--destination={remote}")
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
            self.notify("Select a source", severity="error")
            return
        if not isinstance(remote_sel.value, str):
            self.notify("Select a destination", severity="error")
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
        if dest:
            if not os.path.isabs(dest):
                self.notify("Destination must be an absolute path.", severity="error")
                return
            if ".." in dest.split(os.sep):
                self.notify("Destination must not contain '..' components.", severity="error")
                return
            resolved = os.path.realpath(dest)
            for prefix in _FORBIDDEN_DEST_PREFIXES:
                if resolved == prefix or resolved.startswith(prefix + "/"):
                    self.notify(f"Destination must not point to system directory '{prefix}'.", severity="error")
                    return
        try:
            restore_mysql = self.query_one("#restore-mysql-switch", Switch).value
        except Exception:
            restore_mysql = True
        skip_mysql = not restore_mysql
        try:
            restore_pgsql = self.query_one("#restore-pgsql-switch", Switch).value
        except Exception:
            restore_pgsql = True
        skip_pgsql = not restore_pgsql
        msg = f"Restore snapshot?\n\nSource: {target}\nDestination: {remote}\nSnapshot: {snapshot}"
        if dest:
            msg += f"\nDestination: {dest}"
        else:
            msg += "\nLocation: In-place"
        if skip_mysql:
            msg += "\nMySQL: Skip"
        if skip_pgsql:
            msg += "\nPostgreSQL: Skip"
        self.app.push_screen(
            ConfirmDialog(msg, "Confirm Restore"),
            callback=lambda ok: self._do_restore(target, remote, snapshot, dest, skip_mysql, skip_pgsql) if ok else None,
        )

    def _do_restore(self, target: str, remote: str, snapshot: str, dest: str, skip_mysql: bool = False, skip_pgsql: bool = False) -> None:
        job = job_manager.create_job("restore", f"Restore: {target}")
        args = ["restore", f"--source={target}", f"--destination={remote}", f"--snapshot={snapshot}"]
        if dest:
            args.append(f"--dest={dest}")
        if skip_mysql:
            args.append("--skip-mysql")
        if skip_pgsql:
            args.append("--skip-postgresql")
        job_manager.start_job(self.app, job, *args)
        self.app.switch_screen("running_tasks")

    def action_go_back(self) -> None:
        self.app.pop_screen()
