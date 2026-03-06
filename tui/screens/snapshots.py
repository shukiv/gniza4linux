from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, DataTable
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir
from tui.backend import run_cli
from tui.widgets import OperationLog


class SnapshotsScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        with Vertical(id="snapshots-screen"):
            yield Static("Snapshots", id="screen-title")
            if not targets or not remotes:
                yield Static("Targets and remotes must be configured to browse snapshots.")
            else:
                yield Static("Target:")
                yield Select([(t, t) for t in targets], id="snap-target", prompt="Select target")
                yield Static("Remote:")
                yield Select([(r, r) for r in remotes], id="snap-remote", prompt="Select remote")
                yield Button("Load Snapshots", id="btn-load", variant="primary")
                yield DataTable(id="snap-table")
                with Horizontal(id="snapshots-buttons"):
                    yield Button("Browse Files", id="btn-browse")
                    yield Button("Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        try:
            table = self.query_one("#snap-table", DataTable)
            table.add_columns("Snapshot")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-load":
            self._load_snapshots()
        elif event.button.id == "btn-browse":
            self._browse_snapshot()

    def _selected_snapshot(self) -> str | None:
        try:
            table = self.query_one("#snap-table", DataTable)
            if table.cursor_row is not None and table.row_count > 0:
                row_key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
                # The snapshot name is in the first (only) column
                return str(table.get_cell(row_key, "Snapshot"))
            return None
        except Exception:
            return None

    @work
    async def _load_snapshots(self) -> None:
        target_sel = self.query_one("#snap-target", Select)
        remote_sel = self.query_one("#snap-remote", Select)
        if not isinstance(target_sel.value, str) or not isinstance(remote_sel.value, str):
            self.notify("Select target and remote first", severity="error")
            return
        target = str(target_sel.value)
        remote = str(remote_sel.value)
        rc, stdout, stderr = await run_cli("snapshots", "list", f"--target={target}", f"--remote={remote}")
        table = self.query_one("#snap-table", DataTable)
        table.clear()
        lines = [l.strip() for l in stdout.splitlines() if l.strip() and not l.startswith("===")]
        if lines:
            for s in lines:
                table.add_row(s, key=s)
        else:
            self.notify("No snapshots found", severity="warning")
            if stderr:
                self.notify(stderr.strip(), severity="error")

    @work
    async def _browse_snapshot(self) -> None:
        target_sel = self.query_one("#snap-target", Select)
        remote_sel = self.query_one("#snap-remote", Select)
        if not isinstance(target_sel.value, str) or not isinstance(remote_sel.value, str):
            self.notify("Select target and remote first", severity="error")
            return
        snapshot = self._selected_snapshot()
        if not snapshot:
            self.notify("Select a snapshot first", severity="warning")
            return
        target = str(target_sel.value)
        remote = str(remote_sel.value)
        log_screen = OperationLog(f"Files: {target}/{snapshot}", show_spinner=False)
        self.app.push_screen(log_screen)
        rc, stdout, stderr = await run_cli(
            "snapshots", "browse", f"--target={target}", f"--remote={remote}", f"--snapshot={snapshot}"
        )
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        if not stdout and not stderr:
            log_screen.write("No files found.")

    def action_go_back(self) -> None:
        self.app.pop_screen()
