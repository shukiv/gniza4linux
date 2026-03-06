from pathlib import Path
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, RichLog
from textual.containers import Vertical, Horizontal

from tui.config import LOG_DIR


class LogsScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="logs-screen"):
            yield Static("Logs", id="screen-title")
            yield DataTable(id="logs-table")
            with Horizontal(id="logs-buttons"):
                yield Button("View", variant="primary", id="btn-view")
                yield Button("Status", id="btn-status")
                yield Button("Back", id="btn-back")
            yield RichLog(id="log-viewer", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#logs-table", DataTable)
        table.clear(columns=True)
        table.add_columns("File", "Size")
        log_dir = Path(LOG_DIR)
        if not log_dir.is_dir():
            return
        logs = sorted(log_dir.glob("gniza-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        for f in logs:
            size = f.stat().st_size
            if size >= 1048576:
                size_str = f"{size / 1048576:.1f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            table.add_row(f.name, size_str, key=f.name)

    def _selected_log(self) -> str | None:
        table = self.query_one("#logs-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-view":
            name = self._selected_log()
            if name:
                self._view_log(name)
            else:
                self.notify("Select a log file first", severity="warning")
        elif event.button.id == "btn-status":
            self._show_status()

    def _view_log(self, name: str) -> None:
        filepath = (Path(LOG_DIR) / name).resolve()
        if not filepath.is_relative_to(Path(LOG_DIR).resolve()):
            self.notify("Invalid log path", severity="error")
            return
        viewer = self.query_one("#log-viewer", RichLog)
        viewer.clear()
        if filepath.is_file():
            content = filepath.read_text()
            viewer.write(content)
        else:
            viewer.write(f"File not found: {filepath}")

    def _show_status(self) -> None:
        viewer = self.query_one("#log-viewer", RichLog)
        viewer.clear()
        log_dir = Path(LOG_DIR)
        viewer.write("Backup Status Overview")
        viewer.write("=" * 40)
        if not log_dir.is_dir():
            viewer.write("Log directory does not exist.")
            return
        logs = sorted(log_dir.glob("gniza-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if logs:
            latest = logs[0]
            from datetime import datetime
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            viewer.write(f"Last log: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            last_line = ""
            with open(latest) as f:
                for line in f:
                    last_line = line.rstrip()
            if last_line:
                viewer.write(f"Last entry: {last_line}")
        else:
            viewer.write("No backup logs found.")
        viewer.write(f"Log files: {len(logs)}")
        total = sum(f.stat().st_size for f in logs)
        if total >= 1048576:
            viewer.write(f"Total size: {total / 1048576:.1f} MB")
        elif total >= 1024:
            viewer.write(f"Total size: {total / 1024:.1f} KB")
        else:
            viewer.write(f"Total size: {total} B")

    def action_go_back(self) -> None:
        self.app.pop_screen()
