from textual.app import App

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

    def on_job_finished(self, message: JobFinished) -> None:
        job = job_manager.get_job(message.job_id)
        if not job:
            return
        if message.return_code == 0:
            self.notify(f"{job.label} completed successfully")
        else:
            self.notify(f"{job.label} failed (exit code {message.return_code})", severity="error")

    async def action_quit(self) -> None:
        job_manager.kill_running()
        self.exit()
