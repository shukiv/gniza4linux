from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from textual.containers import Vertical, Center

LOGO = """\
  [green]
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593          \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  [/green]
  gniza - Linux Backup Manager
"""


class MainMenuScreen(Screen):

    BINDINGS = [("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="main-menu"):
                yield Static(LOGO, id="logo", markup=True)
                yield Button("Backup", id="menu-backup", variant="primary")
                yield Button("Restore", id="menu-restore")
                yield Button("Targets", id="menu-targets")
                yield Button("Remotes", id="menu-remotes")
                yield Button("Snapshots", id="menu-snapshots")
                yield Button("Verify", id="menu-verify")
                yield Button("Retention", id="menu-retention")
                yield Button("Schedules", id="menu-schedule")
                yield Button("Logs", id="menu-logs")
                yield Button("Settings", id="menu-settings")
                yield Button("Quit", id="menu-quit", variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_map = {
            "menu-backup": "backup",
            "menu-restore": "restore",
            "menu-targets": "targets",
            "menu-remotes": "remotes",
            "menu-snapshots": "snapshots",
            "menu-verify": "verify",
            "menu-retention": "retention",
            "menu-schedule": "schedule",
            "menu-logs": "logs",
            "menu-settings": "settings",
        }
        if event.button.id == "menu-quit":
            self.app.exit()
        elif event.button.id in button_map:
            self.app.push_screen(button_map[event.button.id])

    def action_quit_app(self) -> None:
        self.app.exit()
