import re
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, Input, Select, SelectionList
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

HOURLY_INTERVALS = [
    ("Every Hour", "1"),
    ("Every 2 Hours", "2"),
    ("Every 3 Hours", "3"),
    ("Every 4 Hours", "4"),
    ("Every 6 Hours", "6"),
    ("Every 8 Hours", "8"),
    ("Every 12 Hours", "12"),
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
            yield Static("Schedule Hours:", classes="sched-hourly-field")
            yield Select(HOURLY_INTERVALS, id="sched-interval", value="1", classes="sched-hourly-field")
            yield Static("Time (HH:MM):", classes="sched-time-field")
            yield Input(id="sched-time", value="02:00", placeholder="02:00", classes="sched-time-field")
            yield Static("Schedule Days:", classes="sched-daily-days-field")
            yield SelectionList[str](
                ("Sunday", "0"),
                ("Monday", "1"),
                ("Tuesday", "2"),
                ("Wednesday", "3"),
                ("Thursday", "4"),
                ("Friday", "5"),
                ("Saturday", "6"),
                id="sched-daily-days",
                classes="sched-daily-days-field",
            )
            yield Static("Schedule Day:", classes="sched-weekly-day-field")
            yield Select(
                [("Sunday", "0"), ("Monday", "1"), ("Tuesday", "2"), ("Wednesday", "3"),
                 ("Thursday", "4"), ("Friday", "5"), ("Saturday", "6")],
                id="sched-weekly-day",
                value="0",
                classes="sched-weekly-day-field",
            )
            yield Static("Schedule Day:", classes="sched-monthly-field")
            yield Select(
                [("1st of the month", "1"), ("7th of the month", "7"),
                 ("14th of the month", "14"), ("21st of the month", "21"),
                 ("28th of the month", "28")],
                id="sched-monthly-day",
                value="1",
                classes="sched-monthly-field",
            )
            yield Static("Custom cron (5 fields):", classes="sched-cron-field")
            yield Input(id="sched-cron", placeholder="0 2 * * *", classes="sched-cron-field")
            yield Static("Targets (empty=all):")
            yield SelectionList[str](
                *self._build_target_choices(),
                id="sched-targets",
            )
            yield Static("Remotes (empty=all):")
            yield SelectionList[str](
                *self._build_remote_choices(),
                id="sched-remotes",
            )
        yield Footer()

    def _build_target_choices(self) -> list[tuple[str, str]]:
        return [(name, name) for name in list_conf_dir("targets.d")]

    def _build_remote_choices(self) -> list[tuple[str, str]]:
        return [(name, name) for name in list_conf_dir("remotes.d")]

    def on_mount(self) -> None:
        self._refresh_table()
        self._update_type_visibility()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sched-type":
            self._update_type_visibility()

    def _update_type_visibility(self) -> None:
        type_sel = self.query_one("#sched-type", Select)
        stype = str(type_sel.value) if isinstance(type_sel.value, str) else "daily"
        for w in self.query(".sched-hourly-field"):
            w.display = stype == "hourly"
        for w in self.query(".sched-time-field"):
            w.display = stype in ("daily", "weekly", "monthly")
        for w in self.query(".sched-daily-days-field"):
            w.display = stype == "daily"
        for w in self.query(".sched-weekly-day-field"):
            w.display = stype == "weekly"
        for w in self.query(".sched-monthly-field"):
            w.display = stype == "monthly"
        for w in self.query(".sched-cron-field"):
            w.display = stype == "custom"

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
        if stype == "hourly":
            interval_sel = self.query_one("#sched-interval", Select)
            day_val = str(interval_sel.value) if isinstance(interval_sel.value, str) else "1"
        elif stype == "daily":
            selected_days = sorted(self.query_one("#sched-daily-days", SelectionList).selected)
            day_val = ",".join(selected_days)
        elif stype == "weekly":
            wday_sel = self.query_one("#sched-weekly-day", Select)
            day_val = str(wday_sel.value) if isinstance(wday_sel.value, str) else "0"
        elif stype == "monthly":
            mday_sel = self.query_one("#sched-monthly-day", Select)
            day_val = str(mday_sel.value) if isinstance(mday_sel.value, str) else "1"
        else:
            day_val = ""
        sched = Schedule(
            name=name,
            schedule=stype,
            time=self.query_one("#sched-time", Input).value.strip() or "02:00",
            day=day_val,
            cron=self.query_one("#sched-cron", Input).value.strip(),
            targets=",".join(self.query_one("#sched-targets", SelectionList).selected),
            remotes=",".join(self.query_one("#sched-remotes", SelectionList).selected),
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
