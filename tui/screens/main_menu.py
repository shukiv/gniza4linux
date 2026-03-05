from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, OptionList
from textual.widgets.option_list import Option
from textual.containers import Horizontal, Vertical

LOGO = """\
  [green]
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593          \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  \u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593
  [/green]
  gniza - Linux Backup Manager
"""

MENU_ITEMS = [
    ("backup", "Backup"),
    ("restore", "Restore"),
    ("targets", "Targets"),
    ("remotes", "Remotes"),
    ("snapshots", "Snapshots"),
    ("verify", "Verify"),
    ("retention", "Retention"),
    ("schedule", "Schedules"),
    ("logs", "Logs"),
    ("settings", "Settings"),
    ("quit", "Quit"),
]


class MainMenuScreen(Screen):

    BINDINGS = [("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-layout"):
            with Vertical(id="logo-panel"):
                yield Static(LOGO, id="logo", markup=True)
            with Vertical(id="menu-panel"):
                yield OptionList(
                    *[Option(label, id=mid) for mid, label in MENU_ITEMS],
                    id="menu-list",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "quit":
            self.app.exit()
        elif option_id:
            self.app.push_screen(option_id)

    def action_quit_app(self) -> None:
        self.app.exit()
