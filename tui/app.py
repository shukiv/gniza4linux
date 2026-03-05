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
from tui.screens.verify import VerifyScreen
from tui.screens.retention import RetentionScreen
from tui.screens.schedule import ScheduleScreen
from tui.screens.logs import LogsScreen
from tui.screens.settings import SettingsScreen
from tui.screens.wizard import WizardScreen


class GnizaApp(App):

    TITLE = "gniza - Linux Backup Manager"
    CSS_PATH = "gniza.tcss"

    SCREENS = {
        "main": MainMenuScreen,
        "backup": BackupScreen,
        "restore": RestoreScreen,
        "targets": TargetsScreen,
        "target_edit": TargetEditScreen,
        "remotes": RemotesScreen,
        "remote_edit": RemoteEditScreen,
        "snapshots": SnapshotsScreen,
        "verify": VerifyScreen,
        "retention": RetentionScreen,
        "schedule": ScheduleScreen,
        "logs": LogsScreen,
        "settings": SettingsScreen,
        "wizard": WizardScreen,
    }

    def on_mount(self) -> None:
        if not has_remotes() or not has_targets():
            self.push_screen("wizard")
        else:
            self.push_screen("main")
