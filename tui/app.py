from textual.app import App
from textual.css.query import NoMatches
from textual.events import Resize

from tui.config import has_remotes, has_targets
from tui.screens.main_menu import MainMenuScreen
from tui.screens.backup import BackupScreen
from tui.screens.restore import RestoreScreen
from tui.screens.targets import TargetsScreen
from tui.screens.target_edit import TargetEditScreen
from tui.screens.remotes import RemotesScreen
from tui.screens.remote_edit import RemoteEditScreen
from tui.screens.snapshots import SnapshotsScreen
from tui.screens.schedule import ScheduleScreen
from tui.screens.schedule_edit import ScheduleEditScreen
from tui.screens.logs import LogsScreen
from tui.screens.email_log import EmailLogScreen
from tui.screens.health import HealthScreen
from tui.screens.retention import RetentionScreen
from tui.screens.settings import SettingsScreen
from tui.screens.wizard import WizardScreen
from tui.screens.running_tasks import RunningTasksScreen
from tui.jobs import job_manager, JobFinished


class GnizaApp(App):

    TITLE = "GNIZA - Linux Backup Manager"
    CSS_PATH = "gniza.tcss"
    BINDINGS = [("f1", "toggle_docs", "Help")]

    SCREENS = {
        "main": MainMenuScreen,
        "backup": BackupScreen,
        "restore": RestoreScreen,
        "running_tasks": RunningTasksScreen,
        "targets": TargetsScreen,
        "target_edit": TargetEditScreen,
        "remotes": RemotesScreen,
        "remote_edit": RemoteEditScreen,
        "snapshots": SnapshotsScreen,
        "schedule": ScheduleScreen,
        "schedule_edit": ScheduleEditScreen,
        "logs": LogsScreen,
        "email_log": EmailLogScreen,
        "health": HealthScreen,
        "retention": RetentionScreen,
        "settings": SettingsScreen,
        "wizard": WizardScreen,
    }

    def on_mount(self) -> None:
        if not has_remotes() or not has_targets():
            self.push_screen("wizard")
        else:
            self.push_screen("main")
        # Start tailing log files for any jobs that were running
        # when the TUI was last closed
        job_manager.start_tailing_reconnected(self)
        # Periodic health check: detect dead jobs, dispatch queue, sync registry
        self.set_interval(3, self._job_health_check)

    def _job_health_check(self) -> None:
        """App-level periodic job health check. Runs on all screens."""
        job_manager.reload_registry()
        job_manager.check_reconnected()
        job_manager._dispatch_queue(self)

    def on_job_finished(self, message: JobFinished) -> None:
        job = job_manager.get_job(message.job_id)
        if not job:
            return
        if job.status == "skipped":
            self.notify(f"{job.label} — all targets skipped", severity="warning")
        elif message.return_code == 0:
            self.notify(f"{job.label} completed successfully")
        else:
            self.notify(f"{job.label} failed (exit code {message.return_code})", severity="error")

    # Below this width: hide inline panel, F1 opens modal instead
    DOCS_MODAL_WIDTH = 80

    def action_toggle_docs(self) -> None:
        if self.size.width < self.DOCS_MODAL_WIDTH:
            self._open_help_modal()
        else:
            try:
                panel = self.screen.query_one("#docs-panel")
                panel.display = not panel.display
            except NoMatches:
                pass

    def _open_help_modal(self) -> None:
        from tui.widgets import HelpModal
        from tui.docs import SCREEN_DOCS
        try:
            panel = self.screen.query_one("#docs-panel")
            content = panel._content
        except NoMatches:
            content = "No documentation available for this screen."
        self.push_screen(HelpModal(content))

    def on_resize(self, event: Resize) -> None:
        self._update_docs_layout(event.size.width)

    def on_screen_resume(self) -> None:
        """Re-evaluate docs panel layout when switching screens."""
        self._update_docs_layout(self.size.width)

    def _update_docs_layout(self, width: int) -> None:
        try:
            panel = self.screen.query_one("#docs-panel")
        except NoMatches:
            return
        if width < self.DOCS_MODAL_WIDTH:
            panel.display = False
        else:
            panel.display = True

    async def action_quit(self) -> None:
        if job_manager.running_count() > 0:
            from tui.widgets import ConfirmDialog
            self.push_screen(
                ConfirmDialog(
                    f"{job_manager.running_count()} job(s) still running.\nQuit and let them continue in background?",
                    "Confirm Quit",
                ),
                callback=lambda ok: self._do_quit(kill=False) if ok else None,
            )
        else:
            self.exit()

    def _do_quit(self, kill: bool = False) -> None:
        if kill:
            job_manager.kill_running()
        self.exit()
