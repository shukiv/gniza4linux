import re
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select, SelectionList
from textual.containers import Vertical, Horizontal

from tui.config import list_conf_dir, parse_conf, write_conf, CONFIG_DIR
from tui.models import Schedule
from tui.widgets import DocsPanel

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


class ScheduleEditScreen(Screen):

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str = ""):
        super().__init__()
        self._edit_name = name
        self._is_new = not name

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        title = "Add Schedule" if self._is_new else f"Edit Schedule: {self._edit_name}"
        sched = Schedule()
        if not self._is_new:
            data = parse_conf(CONFIG_DIR / "schedules.d" / f"{self._edit_name}.conf")
            sched = Schedule.from_conf(self._edit_name, data)

        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="schedule-edit"):
                yield Static(title, id="screen-title")
                if self._is_new:
                    yield Static("Name:")
                    yield Input(value="", placeholder="Schedule name", id="sched-name")
                yield Static("Type:")
                yield Select(SCHEDULE_TYPES, id="sched-type", value=sched.schedule)
                yield Static("Schedule Hours:", classes="sched-hourly-field")
                yield Select(
                    HOURLY_INTERVALS,
                    id="sched-interval",
                    value=sched.day if sched.schedule == "hourly" and sched.day else "1",
                    classes="sched-hourly-field",
                )
                yield Static("Time (HH:MM):", classes="sched-time-field")
                yield Input(
                    id="sched-time",
                    value=sched.time,
                    placeholder="02:00",
                    classes="sched-time-field",
                )
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
                    value=sched.day if sched.schedule == "weekly" and sched.day else "0",
                    classes="sched-weekly-day-field",
                )
                yield Static("Schedule Day:", classes="sched-monthly-field")
                yield Select(
                    [("1st of the month", "1"), ("7th of the month", "7"),
                     ("14th of the month", "14"), ("21st of the month", "21"),
                     ("28th of the month", "28")],
                    id="sched-monthly-day",
                    value=sched.day if sched.schedule == "monthly" and sched.day else "1",
                    classes="sched-monthly-field",
                )
                yield Static("Custom cron (5 fields):", classes="sched-cron-field")
                yield Input(
                    id="sched-cron",
                    value=sched.cron,
                    placeholder="0 2 * * *",
                    classes="sched-cron-field",
                )
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
                with Horizontal(id="sched-edit-buttons"):
                    yield Button("Save", variant="primary", id="btn-save")
                    yield Button("Cancel", id="btn-cancel")
            yield DocsPanel.for_screen("schedule-edit")
        yield Footer()

    def _build_target_choices(self) -> list[tuple[str, str]]:
        return [(name, name) for name in list_conf_dir("targets.d")]

    def _build_remote_choices(self) -> list[tuple[str, str]]:
        return [(name, name) for name in list_conf_dir("remotes.d")]

    def on_mount(self) -> None:
        self._update_type_visibility()
        if not self._is_new:
            self._load_selections()

    def _load_selections(self) -> None:
        """Pre-select items in SelectionLists when editing."""
        data = parse_conf(CONFIG_DIR / "schedules.d" / f"{self._edit_name}.conf")
        sched = Schedule.from_conf(self._edit_name, data)
        # Daily days
        if sched.schedule == "daily" and sched.day:
            days_list = self.query_one("#sched-daily-days", SelectionList)
            day_vals = set(sched.day.split(","))
            for idx in range(days_list.option_count):
                opt = days_list.get_option_at_index(idx)
                if opt.value in day_vals:
                    days_list.select(opt.value)
        # Targets
        if sched.targets:
            target_vals = set(sched.targets.split(","))
            tlist = self.query_one("#sched-targets", SelectionList)
            for idx in range(tlist.option_count):
                opt = tlist.get_option_at_index(idx)
                if opt.value in target_vals:
                    tlist.select(opt.value)
        # Remotes
        if sched.remotes:
            remote_vals = set(sched.remotes.split(","))
            rlist = self.query_one("#sched-remotes", SelectionList)
            for idx in range(rlist.option_count):
                opt = rlist.get_option_at_index(idx)
                if opt.value in remote_vals:
                    rlist.select(opt.value)

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-save":
            self._save()

    def _save(self) -> None:
        if self._is_new:
            name = self.query_one("#sched-name", Input).value.strip()
            if not name:
                self.notify("Name is required", severity="error")
                return
            if not _NAME_RE.match(name):
                self.notify("Invalid name. Use letters, digits, _ - (max 32 chars, start with letter).", severity="error")
                return
            conf = CONFIG_DIR / "schedules.d" / f"{name}.conf"
            if conf.exists():
                self.notify(f"Schedule '{name}' already exists.", severity="error")
                return
        else:
            name = self._edit_name

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
        conf = CONFIG_DIR / "schedules.d" / f"{name}.conf"
        write_conf(conf, sched.to_conf())
        self.notify(f"Schedule '{name}' saved.")
        self.dismiss(name)

    def action_cancel(self) -> None:
        self.dismiss(None)
