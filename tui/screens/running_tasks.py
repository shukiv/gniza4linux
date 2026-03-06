from datetime import datetime

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from textual.containers import Vertical, Horizontal

from tui.jobs import job_manager
from tui.widgets import ConfirmDialog, OperationLog


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
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rt-table", DataTable)
        table.add_columns("Status", "Job", "Started", "Duration")
        table.cursor_type = "row"
        self._refresh_table()
        self._timer = self.set_interval(1, self._refresh_table)

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
        table = self.query_one("#rt-table", DataTable)
        # Preserve cursor position
        old_row = table.cursor_coordinate.row if table.row_count > 0 else 0
        table.clear()
        for job in job_manager.list_jobs():
            if job.status == "running":
                icon = "... "
            elif job.status == "success":
                icon = " ok "
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
            table = self.query_one("#rt-table", DataTable)
            if table.row_count == 0:
                self.notify("No jobs to view", severity="warning")
                return
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            job_id = str(row_key)
            job = job_manager.get_job(job_id)
            if job:
                log_screen = OperationLog(
                    title=job.label,
                    show_spinner=job.status == "running",
                    job_id=job.id,
                )
                self.app.push_screen(log_screen)

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
