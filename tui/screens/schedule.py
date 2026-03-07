from datetime import datetime, timedelta

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, parse_conf, update_conf_key, CONFIG_DIR, LOG_DIR
from tui.models import Schedule
from tui.backend import run_cli
from tui.widgets import ConfirmDialog, OperationLog, DocsPanel


class ScheduleScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
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
            yield DocsPanel.for_screen("schedule-screen")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#sched-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Active", "Type", "Time", "Last Run", "Next Run", "Targets", "Remotes")
        last_run = self._get_last_run()
        schedules = list_conf_dir("schedules.d")
        for name in schedules:
            data = parse_conf(CONFIG_DIR / "schedules.d" / f"{name}.conf")
            s = Schedule.from_conf(name, data)
            active = "✅" if s.active == "yes" else "❌"
            next_run = self._calc_next_run(s) if s.active == "yes" else "inactive"
            table.add_row(name, active, s.schedule, s.time, last_run, next_run, s.targets or "all", s.remotes or "all", key=name)

    def _get_last_run(self) -> str:
        """Get the timestamp of the most recent backup log."""
        from pathlib import Path
        log_dir = Path(str(LOG_DIR))
        if not log_dir.is_dir():
            return "never"
        logs = sorted(log_dir.glob("gniza-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return "never"
        mtime = logs[0].stat().st_mtime
        dt = datetime.fromtimestamp(mtime)
        return dt.strftime("%Y-%m-%d %H:%M")

    def _calc_next_run(self, s: Schedule) -> str:
        """Calculate the next run time from schedule config."""
        now = datetime.now()
        try:
            hour, minute = (int(x) for x in s.time.split(":")) if s.time else (2, 0)
        except (ValueError, IndexError):
            hour, minute = 2, 0

        if s.schedule == "hourly":
            next_dt = now.replace(minute=minute, second=0, microsecond=0)
            if next_dt <= now:
                next_dt += timedelta(hours=1)
        elif s.schedule == "daily":
            next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_dt <= now:
                next_dt += timedelta(days=1)
        elif s.schedule == "weekly":
            try:
                target_dow = int(s.day) if s.day else 0
            except ValueError:
                target_dow = 0
            next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_ahead = (target_dow - now.weekday()) % 7
            if days_ahead == 0 and next_dt <= now:
                days_ahead = 7
            next_dt += timedelta(days=days_ahead)
        elif s.schedule == "monthly":
            try:
                target_dom = int(s.day) if s.day else 1
            except ValueError:
                target_dom = 1
            next_dt = now.replace(day=target_dom, hour=hour, minute=minute, second=0, microsecond=0)
            if next_dt <= now:
                if now.month == 12:
                    next_dt = next_dt.replace(year=now.year + 1, month=1)
                else:
                    next_dt = next_dt.replace(month=now.month + 1)
        else:
            return "never"
        return next_dt.strftime("%Y-%m-%d %H:%M")

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
            self.app.push_screen(ScheduleEditScreen(), callback=self._on_schedule_saved)
        elif event.button.id == "btn-edit":
            name = self._selected_schedule()
            if name:
                from tui.screens.schedule_edit import ScheduleEditScreen
                self.app.push_screen(ScheduleEditScreen(name), callback=self._on_schedule_saved)
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

    def _on_schedule_saved(self, result: str | None) -> None:
        self._refresh_table()
        if result is not None:
            self._sync_crontab()

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
        # Warn if cron daemon is not running
        if has_active and not await self._is_cron_running():
            self.notify(
                "Cron daemon is not running — schedules won't execute. "
                "Start it with: sudo systemctl start cron",
                severity="warning",
                timeout=10,
            )

    @staticmethod
    async def _is_cron_running() -> bool:
        """Check if the cron daemon is active."""
        import asyncio
        for svc in ("cron", "crond"):
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "is-active", svc,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0:
                return True
        # Fallback: check for a running process
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-x", "cron",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

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
        log_screen = OperationLog("Current Crontab", show_spinner=False)
        self.app.push_screen(log_screen)
        rc, stdout, stderr = await run_cli("schedule", "show")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        log_screen.finish()

    def action_go_back(self) -> None:
        self.app.pop_screen()
