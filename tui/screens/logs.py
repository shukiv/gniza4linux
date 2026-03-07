import re
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, RichLog
from textual.widgets._rich_log import Strip
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from tui.config import LOG_DIR
from tui.widgets import DocsPanel


class _SafeRichLog(RichLog):
    """RichLog that guards against negative y in render_line (Textual bug)."""

    def render_line(self, y: int) -> Strip:
        if y < 0 or not self.lines:
            return Strip.blank(self.size.width)
        return super().render_line(y)


_LOG_NAME_RE = re.compile(r"gniza-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.log")


def _format_log_name(name: str) -> tuple[str, str]:
    """Format 'gniza-20260306-144516.log' as ('2026-03-06', '14:45:16')."""
    m = _LOG_NAME_RE.match(name)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}", f"{m[4]}:{m[5]}:{m[6]}"
    return name, ""


def _detect_log_status(filepath: Path) -> str:
    """Determine backup status from log file content.

    Only reads last 100 KB for efficiency on large files.
    """
    try:
        size = filepath.stat().st_size
        if size == 0:
            return "Empty"
        with open(filepath, "r") as f:
            if size > 102400:
                f.seek(size - 102400)
                f.readline()
            tail = f.read()
    except OSError:
        return "?"
    if not tail.strip():
        return "Empty"
    has_error = "[ERROR]" in tail or "[FATAL]" in tail
    has_completed = "Backup completed" in tail or "Restore completed" in tail
    has_lock_released = "Lock released" in tail
    if has_completed and not has_error:
        return "Success"
    if has_error:
        return "Failed"
    if has_lock_released:
        return "OK"
    if "is disabled, skipping" in tail:
        return "Skipped"
    return "Interrupted"


def _build_line_index(filepath: Path) -> list[int]:
    """Build an index of byte offsets for each line start. Fast even for large files."""
    offsets = [0]
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            base = offsets[-1] if not offsets else f.tell() - len(chunk)
            start = 0
            while True:
                pos = chunk.find(b"\n", start)
                if pos == -1:
                    break
                offsets.append(base + pos + 1)
                start = pos + 1
    return offsets


class LogsScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]
    LINES_PER_PAGE = 200

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="logs-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("← Back", id="btn-back", classes="back-btn")
                    yield Static("Logs", id="screen-title")
                yield DataTable(id="logs-table")
                with Horizontal(id="logs-buttons"):
                    yield Button("View", variant="primary", id="btn-view")
                    yield Button("Refresh", id="btn-refresh")
                with Horizontal(id="log-pager-buttons"):
                    yield Button("◀ Prev", id="btn-prev-page")
                    yield Static("", id="log-page-info")
                    yield Button("Next ▶", id="btn-next-page")
                yield _SafeRichLog(id="log-viewer", wrap=True, highlight=True)
            yield DocsPanel.for_screen("logs-screen")
        yield Footer()

    def on_mount(self) -> None:
        self._log_filepath: Path | None = None
        self._line_offsets: list[int] = []
        self._total_lines: int = 0
        self._current_page: int = 0
        self._total_pages: int = 0
        self._hide_pager()
        self._refresh_table()

    def _hide_pager(self) -> None:
        self.query_one("#log-pager-buttons").display = False

    def _show_pager(self) -> None:
        self.query_one("#log-pager-buttons").display = self._total_pages > 1

    def _refresh_table(self) -> None:
        table = self.query_one("#logs-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Status", "Date", "Time", "Size")
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
            date_str, time_str = _format_log_name(f.name)
            status = _detect_log_status(f)
            table.add_row(status, date_str, time_str, size_str, key=f.name)

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
                self._open_log(name)
            else:
                self.notify("Select a log file first", severity="warning")
        elif event.button.id == "btn-refresh":
            self._refresh_table()
            self.notify("Log list refreshed")
        elif event.button.id == "btn-prev-page":
            if self._current_page > 0:
                self._current_page -= 1
                self._render_page()
        elif event.button.id == "btn-next-page":
            if self._current_page < self._total_pages - 1:
                self._current_page += 1
                self._render_page()

    def _open_log(self, name: str) -> None:
        filepath = (Path(LOG_DIR) / name).resolve()
        if not filepath.is_relative_to(Path(LOG_DIR).resolve()):
            self.notify("Invalid log path", severity="error")
            return
        if not filepath.is_file():
            viewer = self.query_one("#log-viewer", RichLog)
            viewer.clear()
            viewer.write(f"File not found: {filepath}")
            self._hide_pager()
            return
        self._log_filepath = filepath
        self._line_offsets = _build_line_index(filepath)
        self._total_lines = max(len(self._line_offsets) - 1, 1)
        self._total_pages = max(1, (self._total_lines + self.LINES_PER_PAGE - 1) // self.LINES_PER_PAGE)
        # Start at last page (most recent output)
        self._current_page = self._total_pages - 1
        self._show_pager()
        self._render_page()

    def _render_page(self) -> None:
        viewer = self.query_one("#log-viewer", RichLog)
        viewer.clear()
        if not self._log_filepath:
            return
        start_line = self._current_page * self.LINES_PER_PAGE
        end_line = min(start_line + self.LINES_PER_PAGE, self._total_lines)
        # Seek to the right byte offset and read the lines
        start_byte = self._line_offsets[start_line]
        end_byte = self._line_offsets[end_line] if end_line < len(self._line_offsets) else self._log_filepath.stat().st_size
        with open(self._log_filepath, "r", errors="replace") as f:
            f.seek(start_byte)
            chunk = f.read(end_byte - start_byte)
        for line in chunk.splitlines():
            viewer.write(line)
        # Update page info
        page_info = self.query_one("#log-page-info", Static)
        page_info.update(f" Page {self._current_page + 1}/{self._total_pages} ")
        # Update button states
        self.query_one("#btn-prev-page", Button).disabled = self._current_page == 0
        self.query_one("#btn-next-page", Button).disabled = self._current_page >= self._total_pages - 1

    def action_go_back(self) -> None:
        self.app.pop_screen()
