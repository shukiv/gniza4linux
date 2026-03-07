import re
from datetime import datetime

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, DataTable
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir
from tui.backend import run_cli
from tui.widgets import SnapshotBrowser, DocsPanel


def _format_snapshot_ts(ts: str) -> str:
    """Format '2026-03-06T140706' as '2026-03-06 14:07:06'."""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


class SnapshotsScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="snapshots-screen"):
                yield Button("← Back", id="btn-back", classes="back-btn")
                yield Static("Snapshots Browser", id="screen-title")
                if not targets or not remotes:
                    yield Static("Sources and destinations must be configured to browse snapshots.")
                else:
                    yield Static("Source:")
                    yield Select([(t, t) for t in targets], id="snap-target", prompt="Select source")
                    yield Static("Destination:")
                    yield Select([(r, r) for r in remotes], id="snap-remote", prompt="Select destination")
                    yield Button("Load Snapshots", id="btn-load", variant="primary")
                    yield DataTable(id="snap-table")
                    with Horizontal(id="snapshots-buttons"):
                        yield Button("Browse Files", id="btn-browse")
            yield DocsPanel.for_screen("snapshots-screen")
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
                return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
            return None
        except Exception:
            return None

    @work
    async def _load_snapshots(self) -> None:
        target_sel = self.query_one("#snap-target", Select)
        remote_sel = self.query_one("#snap-remote", Select)
        if not isinstance(target_sel.value, str) or not isinstance(remote_sel.value, str):
            self.notify("Select source and destination first", severity="error")
            return
        target = str(target_sel.value)
        remote = str(remote_sel.value)
        rc, stdout, stderr = await run_cli("snapshots", "list", f"--source={target}", f"--destination={remote}")
        table = self.query_one("#snap-table", DataTable)
        table.clear()
        lines = [l.strip() for l in stdout.splitlines() if l.strip() and not l.startswith("===")]
        if lines:
            for s in lines:
                table.add_row(_format_snapshot_ts(s), key=s)
        else:
            self.notify("No snapshots found", severity="warning")
            if stderr:
                self.notify(stderr.strip(), severity="error")

    @work
    async def _browse_snapshot(self) -> None:
        target_sel = self.query_one("#snap-target", Select)
        remote_sel = self.query_one("#snap-remote", Select)
        if not isinstance(target_sel.value, str) or not isinstance(remote_sel.value, str):
            self.notify("Select source and destination first", severity="error")
            return
        snapshot = self._selected_snapshot()
        if not snapshot:
            self.notify("Select a snapshot first", severity="warning")
            return
        target = str(target_sel.value)
        remote = str(remote_sel.value)

        self.notify("Loading files...")
        rc, stdout, stderr = await run_cli(
            "snapshots", "browse", f"--source={target}", f"--destination={remote}", f"--snapshot={snapshot}"
        )

        # Parse file list, strip remote prefix to get relative paths
        # Paths look like: /remote/base/.../snapshots/<timestamp>/etc/foo.conf
        # We want everything after the snapshot timestamp directory
        files = []
        pattern = re.compile(re.escape(snapshot) + r"/(.*)")
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            m = pattern.search(line)
            if m:
                files.append(m.group(1))
            else:
                files.append(line)

        if not files:
            self.notify("No files found in snapshot", severity="warning")
            return

        browser = SnapshotBrowser(f"{target} / {snapshot}", files)
        self.app.push_screen(browser)

    def action_go_back(self) -> None:
        self.app.pop_screen()
