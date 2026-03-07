import re
from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, RichLog, ProgressBar
from textual.widgets._rich_log import Strip
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal
from textual.timer import Timer


class _SafeRichLog(RichLog):
    """RichLog that guards against negative y in render_line (Textual bug)."""

    def render_line(self, y: int) -> Strip:
        if y < 0 or not self.lines:
            return Strip.blank(self.size.width)
        return super().render_line(y)

from tui.jobs import job_manager
from tui.widgets import ConfirmDialog, DocsPanel

_PROGRESS_RE = re.compile(r"(\d+)%")
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class RunningTasksScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="running-tasks-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("← Back", id="btn-back", classes="back-btn")
                    yield Static("Running Tasks", id="screen-title")
                yield DataTable(id="rt-table")
                with Horizontal(id="rt-buttons"):
                    yield Button("View Log", variant="primary", id="btn-rt-view")
                    yield Button("Kill Job", variant="error", id="btn-rt-kill")
                    yield Button("Clear Finished", variant="warning", id="btn-rt-clear")
                yield Static("", id="rt-progress-label")
                yield ProgressBar(id="rt-progress", total=100, show_eta=False)
                yield _SafeRichLog(id="rt-log-viewer", wrap=True, highlight=True)
            yield DocsPanel.for_screen("running-tasks-screen")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rt-table", DataTable)
        table.add_columns("Status", "Job", "Started", "Duration")
        table.cursor_type = "row"
        self._spinner_idx = 0
        self._refresh_table()
        self._timer = self.set_interval(1, self._tick)
        self._log_timer: Timer | None = None
        self._viewing_job_id: str | None = None
        self._log_file_pos: int = 0
        # Hide progress bar initially
        self.query_one("#rt-progress", ProgressBar).display = False
        self.query_one("#rt-progress-label", Static).display = False

    def _format_duration(self, job) -> str:
        end = job.finished_at or datetime.now()
        delta = end - job.started_at
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s"
        mins, s = divmod(secs, 60)
        if mins < 60:
            return f"{mins}m {s}s"
        hours, m = divmod(mins, 60)
        return f"{hours}h {m}m"

    def _tick(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(_SPINNER)
        self._refresh_table()

    def _refresh_table(self) -> None:
        job_manager.check_reconnected()
        table = self.query_one("#rt-table", DataTable)
        old_row = table.cursor_coordinate.row if table.row_count > 0 else 0
        table.clear()
        spinner = _SPINNER[self._spinner_idx]
        jobs = job_manager.list_jobs()
        jobs.sort(key=lambda j: (0 if j.status == "running" else 1, -j.started_at.timestamp()))
        for job in jobs:
            if job.status == "running":
                icon = f" {spinner} "
            elif job.status == "skipped":
                icon = "skip"
            elif job.status == "success":
                icon = " ok "
            elif job.status == "unknown":
                icon = " ?  "
            else:
                icon = " X  "
            started = job.started_at.strftime("%H:%M:%S")
            table.add_row(icon, job.label, started, self._format_duration(job), key=job.id)
        if table.row_count > 0:
            table.move_cursor(row=min(old_row, table.row_count - 1))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-rt-clear":
            job_manager.remove_finished()
            self._refresh_table()
        elif event.button.id == "btn-rt-kill":
            self._kill_selected()
        elif event.button.id == "btn-rt-view":
            self._view_selected_log()

    def _view_selected_log(self) -> None:
        table = self.query_one("#rt-table", DataTable)
        if table.row_count == 0:
            self.notify("No jobs to view", severity="warning")
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        job_id = str(row_key.value if hasattr(row_key, 'value') else row_key)
        job = job_manager.get_job(job_id)
        if not job:
            self.notify("Job not found", severity="warning")
            return
        log_viewer = self.query_one("#rt-log-viewer", RichLog)
        log_viewer.clear()
        self._viewing_job_id = job_id
        self._log_file_pos = 0
        # Reset progress bar
        progress = self.query_one("#rt-progress", ProgressBar)
        label = self.query_one("#rt-progress-label", Static)
        progress.update(progress=0)
        # Load only the tail of the log file (like tail -f)
        if job._log_file and Path(job._log_file).is_file():
            try:
                raw = Path(job._log_file).read_bytes()
                self._log_file_pos = len(raw)
                content = raw.decode(errors="replace")
                # Show only last 100 lines
                lines = content.splitlines()
                if len(lines) > 100:
                    log_viewer.write(f"--- showing last 100 of {len(lines)} lines ---")
                    content = "\n".join(lines[-100:])
                self._process_log_content(content, log_viewer)
            except OSError:
                pass
        elif job.output:
            tail = job.output[-100:] if len(job.output) > 100 else job.output
            if len(job.output) > 100:
                log_viewer.write(f"--- showing last 100 of {len(job.output)} lines ---")
            for line in tail:
                log_viewer.write(line)
        # Show/hide progress bar based on job status
        is_running = job.status == "running"
        progress.display = is_running
        label.display = is_running
        # Start polling for new content if job is running
        if self._log_timer:
            self._log_timer.stop()
        if is_running:
            self._log_timer = self.set_interval(0.3, self._poll_log)

    def _process_log_content(self, content: str, log_viewer: RichLog) -> None:
        """Process log content, extracting rsync progress and writing log lines."""
        # Split on both \n and \r to handle rsync --info=progress2 output
        parts = re.split(r"[\r\n]+", content)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            m = _PROGRESS_RE.search(part)
            if m and ("xfr#" in part or "to-chk=" in part or "MB/s" in part or "kB/s" in part or "GB/s" in part):
                self._update_progress(part)
            else:
                log_viewer.write(part)

    def _update_progress(self, text: str) -> None:
        """Parse rsync progress2 line and update progress bar."""
        m = _PROGRESS_RE.search(text)
        if not m:
            return
        pct = int(m.group(1))
        try:
            progress = self.query_one("#rt-progress", ProgressBar)
            label = self.query_one("#rt-progress-label", Static)
            progress.update(progress=pct)
            # Show the raw progress info as label
            label.update(f"  {text.strip()}")
        except Exception:
            pass

    def _poll_log(self) -> None:
        if not self._viewing_job_id:
            return
        job = job_manager.get_job(self._viewing_job_id)
        if not job:
            if self._log_timer:
                self._log_timer.stop()
            return
        try:
            log_viewer = self.query_one("#rt-log-viewer", RichLog)
        except Exception:
            return
        if job._log_file and Path(job._log_file).is_file():
            try:
                with open(job._log_file, "rb") as f:
                    f.seek(self._log_file_pos)
                    new_raw = f.read()
                    if new_raw:
                        self._log_file_pos += len(new_raw)
                        new_data = new_raw.decode(errors="replace")
                        self._process_log_content(new_data, log_viewer)
            except OSError:
                pass
        if job.status != "running":
            self.query_one("#rt-progress", ProgressBar).display = False
            self.query_one("#rt-progress-label", Static).display = False
            if self._log_timer:
                self._log_timer.stop()

    def _kill_selected(self) -> None:
        table = self.query_one("#rt-table", DataTable)
        if table.row_count == 0:
            self.notify("No jobs to kill", severity="warning")
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        job_id = str(row_key.value if hasattr(row_key, 'value') else row_key)
        job = job_manager.get_job(job_id)
        if not job:
            ids = [j.id for j in job_manager.list_jobs()]
            self.notify(f"Not found: key={row_key!r} ids={ids}", severity="warning")
            return
        if job.status != "running":
            self.notify(f"Job already finished ({job.status})", severity="warning")
            return
        self.app.push_screen(
            ConfirmDialog(f"Kill job '{job.label}'?", "Confirm Kill"),
            callback=lambda ok: self._do_kill(job_id) if ok else None,
        )

    def _do_kill(self, job_id: str) -> None:
        result = job_manager.kill_job(job_id)
        self.notify(f"Kill: {result}")

    def action_go_back(self) -> None:
        self.app.pop_screen()
