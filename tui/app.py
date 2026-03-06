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
from tui.screens.retention import RetentionScreen
from tui.screens.schedule import ScheduleScreen
from tui.screens.schedule_edit import ScheduleEditScreen
from tui.screens.logs import LogsScreen
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
        "retention": RetentionScreen,
        "schedule": ScheduleScreen,
        "schedule_edit": ScheduleEditScreen,
        "logs": LogsScreen,
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

    def on_job_finished(self, message: JobFinished) -> None:
        job = job_manager.get_job(message.job_id)
        if not job:
            return
        if message.return_code == 0:
            self.notify(f"{job.label} completed successfully")
        else:
            self.notify(f"{job.label} failed (exit code {message.return_code})", severity="error")

    # Width threshold for auto-hiding the docs panel
    DOCS_AUTO_HIDE_WIDTH = 100

    def action_toggle_docs(self) -> None:
        try:
            panel = self.screen.query_one("#docs-panel")
            panel.display = not panel.display
            panel._user_toggled = True
        except NoMatches:
            pass

    # Width threshold for switching docs panel to bottom
    DOCS_VERTICAL_WIDTH = 80

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
        if not getattr(panel, "_user_toggled", False):
            panel.display = width >= self.DOCS_AUTO_HIDE_WIDTH
        # Switch layout direction based on width
        try:
            container = self.screen.query_one(".screen-with-docs")
        except NoMatches:
            return
        if width < self.DOCS_VERTICAL_WIDTH:
            container.styles.layout = "vertical"
            panel.styles.width = "100%"
            panel.styles.min_width = None
            panel.styles.max_height = "40%"
        else:
            container.styles.layout = "horizontal"
            panel.styles.width = "30%"
            panel.styles.min_width = 30
            panel.styles.max_height = None

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
