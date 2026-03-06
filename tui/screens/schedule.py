import re
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, Input, Select
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, parse_conf, write_conf, CONFIG_DIR
from tui.models import Schedule
from tui.backend import run_cli
from tui.widgets import ConfirmDialog, OperationLog

_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,31}$')

SCHEDULE_TYPES = [
    ("Hourly", "hourly"),
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Monthly", "monthly"),
    ("Custom cron", "custom"),
]


class ScheduleScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="schedule-screen"):
            yield Static("Schedules", id="screen-title")
            yield DataTable(id="sched-table")
            with Horizontal(id="sched-buttons"):
                yield Button("Add", variant="primary", id="btn-add")
                yield Button("Delete", variant="error", id="btn-delete")
                yield Button("Install to crontab", id="btn-install")
                yield Button("Remove from crontab", id="btn-remove")
                yield Button("Show crontab", id="btn-show")
                yield Button("Back", id="btn-back")
            yield Static("", id="sched-divider")
            yield Static("Add Schedule", id="sched-add-title")
            yield Static("Name:")
            yield Input(id="sched-name", placeholder="Schedule name")
            yield Static("Type:")
            yield Select(SCHEDULE_TYPES, id="sched-type", value="daily")
            yield Static("Time (HH:MM):")
            yield Input(id="sched-time", value="02:00", placeholder="02:00")
            yield Static("Day (0=Sun for weekly, 1-28 for monthly):")
            yield Input(id="sched-day", placeholder="Leave empty if not needed")
            yield Static("Custom cron (5 fields):")
            yield Input(id="sched-cron", placeholder="0 2 * * *")
            yield Static("Targets (comma-separated, empty=all):")
            yield Input(id="sched-targets", placeholder="")
            yield Static("Remotes (comma-separated, empty=all):")
            yield Input(id="sched-remotes", placeholder="")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#sched-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Type", "Time", "Targets", "Remotes")
        schedules = list_conf_dir("schedules.d")
        for name in schedules:
            data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
            s = Schedule.from_conf(name, data)
            table.add_row(name, s.schedule, s.time, s.targets or "all", s.remotes or "all", key=name)

    def _selected_schedule(self) -> str | None:
        table = self.query_one("#sched-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-add":
            self._add_schedule()
        elif event.button.id == "btn-delete":
            name = self._selected_schedule()
            if name:
                self.app.push_screen(
                    ConfirmDialog(f"Delete schedule '{name}'?", "Delete Schedule"),
                    callback=lambda ok: self._delete_schedule(name) if ok else None,
                )
            else:
                self.notify("Select a schedule first", severity="warning")
        elif event.button.id == "btn-install":
            self._install_schedules()
        elif event.button.id == "btn-remove":
            self._remove_schedules()
        elif event.button.id == "btn-show":
            self._show_crontab()

    def _add_schedule(self) -> None:
        name = self.query_one("#sched-name", Input).value.strip()
        if not name:
            self.notify("Name is required", severity="error")
            return
        if not _NAME_RE.match(name):
            self.notify("Invalid name.", severity="error")
            return
        conf = CONFIG_DIR / "schedules.d" / f"{name}.conf"
        if conf.exists():
            self.notify(f"Schedule '{name}' already exists.", severity="error")
            return
        type_sel = self.query_one("#sched-type", Select)
        stype = str(type_sel.value) if isinstance(type_sel.value, str) else "daily"
        sched = Schedule(
            name=name,
            schedule=stype,
            time=self.query_one("#sched-time", Input).value.strip() or "02:00",
            day=self.query_one("#sched-day", Input).value.strip(),
            cron=self.query_one("#sched-cron", Input).value.strip(),
            targets=self.query_one("#sched-targets", Input).value.strip(),
            remotes=self.query_one("#sched-remotes", Input).value.strip(),
        )
        write_conf(conf, sched.to_conf())
        self.notify(f"Schedule '{name}' created.")
        self._refresh_table()
        self.query_one("#sched-name", Input).value = ""

    def _delete_schedule(self, name: str) -> None:
        conf = CONFIG_DIR / "schedules.d" / f"{name}.conf"
        if conf.is_file():
            conf.unlink()
            self.notify(f"Schedule '{name}' deleted.")
        self._refresh_table()

    @work
    async def _install_schedules(self) -> None:
        log_screen = OperationLog("Install Schedules")
        self.app.push_screen(log_screen)
        rc, stdout, stderr = await run_cli("schedule", "install")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)

    @work
    async def _remove_schedules(self) -> None:
        log_screen = OperationLog("Remove Schedules")
        self.app.push_screen(log_screen)
        rc, stdout, stderr = await run_cli("schedule", "remove")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)

    @work
    async def _show_crontab(self) -> None:
        log_screen = OperationLog("Current Crontab")
        self.app.push_screen(log_screen)
        rc, stdout, stderr = await run_cli("schedule", "show")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)

    def action_go_back(self) -> None:
        self.app.pop_screen()
