from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, RichLog
from textual.containers import Vertical, Horizontal
from textual.timer import Timer

from tui.jobs import job_manager
from tui.widgets import ConfirmDialog


class RunningTasksScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="running-tasks-screen"):
            yield Static("Running Tasks", id="screen-title")
            yield DataTable(id="rt-table")
            with Horizontal(id="rt-buttons"):
                yield Button("View Log", variant="primary", id="btn-rt-view")
                yield Button("Kill Job", variant="error", id="btn-rt-kill")
                yield Button("Clear Finished", variant="warning", id="btn-rt-clear")
                yield Button("Back", id="btn-rt-back")
            yield RichLog(id="rt-log-viewer", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rt-table", DataTable)
        table.add_columns("Status", "Job", "Started", "Duration")
        table.cursor_type = "row"
        self._refresh_table()
        self._timer = self.set_interval(1, self._refresh_table)
        self._log_timer: Timer | None = None
        self._viewing_job_id: str | None = None
        self._log_file_pos: int = 0

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

    def _refresh_table(self) -> None:
        job_manager.check_reconnected()
        table = self.query_one("#rt-table", DataTable)
        old_row = table.cursor_coordinate.row if table.row_count > 0 else 0
        table.clear()
        for job in job_manager.list_jobs():
            if job.status == "running":
                icon = "... "
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
        if event.button.id == "btn-rt-back":
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
        # Load existing content from log file
        if job._log_file and Path(job._log_file).is_file():
            try:
                content = Path(job._log_file).read_text()
                self._log_file_pos = len(content.encode())
                for line in content.splitlines():
                    log_viewer.write(line)
            except OSError:
                pass
        elif job.output:
            for line in job.output:
                log_viewer.write(line)
        # Start polling for new content if job is running
        if self._log_timer:
            self._log_timer.stop()
        if job.status == "running":
            self._log_timer = self.set_interval(0.3, self._poll_log)

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
                with open(job._log_file, "r") as f:
                    f.seek(self._log_file_pos)
                    new_data = f.read()
                    if new_data:
                        self._log_file_pos += len(new_data.encode())
                        for line in new_data.splitlines():
                            log_viewer.write(line)
            except OSError:
                pass
        if job.status != "running":
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
