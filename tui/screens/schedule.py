from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, parse_conf, update_conf_key, CONFIG_DIR
from tui.models import Schedule
from tui.backend import run_cli
from tui.widgets import ConfirmDialog, OperationLog


class ScheduleScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="schedule-screen"):
            yield Static("Schedules", id="screen-title")
            yield DataTable(id="sched-table")
            with Horizontal(id="sched-buttons"):
                yield Button("Add", variant="primary", id="btn-add")
                yield Button("Edit", id="btn-edit")
                yield Button("Toggle Active", variant="warning", id="btn-toggle")
                yield Button("Delete", variant="error", id="btn-delete")
                yield Button("Show crontab", id="btn-show")
                yield Button("Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#sched-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Active", "Type", "Time", "Targets", "Remotes")
        schedules = list_conf_dir("schedules.d")
        for name in schedules:
            data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
            s = Schedule.from_conf(name, data)
            active = "✅" if s.active == "yes" else "❌"
            table.add_row(name, active, s.schedule, s.time, s.targets or "all", s.remotes or "all", key=name)

    def _selected_schedule(self) -> str | None:
        table = self.query_one("#sched-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-add":
            from tui.screens.schedule_edit import ScheduleEditScreen
            self.app.push_screen(ScheduleEditScreen(), callback=lambda _: self._refresh_table())
        elif event.button.id == "btn-edit":
            name = self._selected_schedule()
            if name:
                from tui.screens.schedule_edit import ScheduleEditScreen
                self.app.push_screen(ScheduleEditScreen(name), callback=lambda _: self._refresh_table())
            else:
                self.notify("Select a schedule first", severity="warning")
        elif event.button.id == "btn-delete":
            name = self._selected_schedule()
            if name:
                self.app.push_screen(
                    ConfirmDialog(f"Delete schedule '{name}'?", "Delete Schedule"),
                    callback=lambda ok: self._delete_schedule(name) if ok else None,
                )
            else:
                self.notify("Select a schedule first", severity="warning")
        elif event.button.id == "btn-toggle":
            name = self._selected_schedule()
            if name:
                self._toggle_active(name)
            else:
                self.notify("Select a schedule first", severity="warning")
        elif event.button.id == "btn-show":
            self._show_crontab()

    def _toggle_active(self, name: str) -> None:
        conf = CONFIG_DIR / "schedules.d" / f"{name}.conf"
        data = parse_conf(conf)
        current = data.get("SCHEDULE_ACTIVE", "yes")
        new_val = "no" if current == "yes" else "yes"
        update_conf_key(conf, "SCHEDULE_ACTIVE", new_val)
        state = "activated" if new_val == "yes" else "deactivated"
        self.notify(f"Schedule '{name}' {state}")
        self._refresh_table()
        self._sync_crontab()

    @work
    async def _sync_crontab(self) -> None:
        """Reinstall crontab with only active schedules."""
        # Check if any schedule is active
        has_active = False
        for name in list_conf_dir("schedules.d"):
            data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
            if data.get("SCHEDULE_ACTIVE", "yes") == "yes":
                has_active = True
                break
        if has_active:
            rc, stdout, stderr = await run_cli("schedule", "install")
        else:
            rc, stdout, stderr = await run_cli("schedule", "remove")
        if rc != 0:
            self.notify(f"Crontab sync failed: {stderr or stdout}", severity="error")

    def _delete_schedule(self, name: str) -> None:
        conf = CONFIG_DIR / "schedules.d" / f"{name}.conf"
        if conf.is_file():
            conf.unlink()
            self.notify(f"Schedule '{name}' deleted.")
        self._refresh_table()
        self._sync_crontab()

    @work
    async def _install_schedules(self) -> None:
        rc, stdout, stderr = await run_cli("schedule", "install")
        if rc == 0:
            self.notify("Schedules installed to crontab")
        else:
            self.notify(f"Failed to install: {stderr or stdout}", severity="error")

    @work
    async def _remove_schedules(self) -> None:
        rc, stdout, stderr = await run_cli("schedule", "remove")
        if rc == 0:
            self.notify("Schedules removed from crontab")
        else:
            self.notify(f"Failed to remove: {stderr or stdout}", severity="error")

    @work
    async def _show_crontab(self) -> None:
        log_screen = OperationLog("Current Crontab")
        self.app.push_screen(log_screen)
        rc, stdout, stderr = await run_cli("schedule", "show")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        log_screen.finish()

    def action_go_back(self) -> None:
        self.app.pop_screen()
