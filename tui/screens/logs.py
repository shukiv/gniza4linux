import re
from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, RichLog
from textual.widgets._rich_log import Strip
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from tui.jobs import job_manager
from tui.config import LOG_DIR
from tui.widgets import DocsPanel


class _SafeRichLog(RichLog):
    """RichLog that guards against negative y in render_line (Textual bug)."""

    def render_line(self, y: int) -> Strip:
        if y < 0 or not self.lines:
            return Strip.blank(self.size.width)
        return super().render_line(y)


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

    def _format_duration(self, job) -> str:
        if not job.finished_at or not job.started_at:
            return "--"
        secs = int((job.finished_at - job.started_at).total_seconds())
        if secs < 60:
            return f"{secs}s"
        mins, s = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m {s}s"
        hours, m = divmod(mins, 60)
        return f"{hours}h {m}m"

    def _format_size(self, job) -> str:
        if not job._log_file:
            return "--"
        try:
            size = Path(job._log_file).stat().st_size
        except OSError:
            return "--"
        if size >= 1048576:
            return f"{size / 1048576:.1f} MB"
        elif size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"

    def _refresh_table(self) -> None:
        job_manager.reload_registry()
        table = self.query_one("#logs-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Status", "Label", "Started", "Duration", "Size")
        table.cursor_type = "row"

        jobs = job_manager.list_jobs()
        finished = [j for j in jobs if j.status not in ("running", "queued")]
        finished.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)

        for job in finished[:20]:
            if job.status == "success":
                status = "Success"
            elif job.status == "failed":
                status = "Failed"
            elif job.status == "skipped":
                status = "Skipped"
            elif job.status == "unknown":
                status = "Unknown"
            else:
                status = job.status.capitalize()
            started = job.started_at.strftime("%Y-%m-%d %H:%M:%S")
            table.add_row(
                status, job.label, started,
                self._format_duration(job), self._format_size(job),
                key=job.id,
            )

    def _selected_job_id(self) -> str | None:
        table = self.query_one("#logs-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-view":
            job_id = self._selected_job_id()
            if job_id:
                self._open_log(job_id)
            else:
                self.notify("Select a job first", severity="warning")
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

    def _open_log(self, job_id: str) -> None:
        job = job_manager.get_job(job_id)
        if not job or not job._log_file:
            self.notify("Log file not found", severity="warning")
            self._hide_pager()
            return
        filepath = Path(job._log_file).resolve()
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
