from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, OptionList
from textual.widgets.option_list import Option
from textual.containers import Horizontal, Vertical

LOGO = """\
[green]▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓          ▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
            ▓▓▓▓▓▓▓▓▓▓
              ▓▓▓▓▓▓
                ▓▓
[/green]
  GNIZA - Linux Backup Manager
"""

MENU_ITEMS = [
    ("backup", "Backup"),
    ("restore", "Restore"),
    ("running_tasks", "Running Tasks"),
    ("targets", "Targets"),
    ("remotes", "Remotes"),
    ("schedule", "Schedules"),
    ("snapshots", "Snapshots Browser"),
    ("logs", "Logs"),
    ("settings", "Settings"),
    ("quit", "Quit"),
]


class MainMenuScreen(Screen):

    BINDINGS = [("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            yield Static(LOGO, id="logo", markup=True)
            menu_items = []
            for mid, label in MENU_ITEMS:
                menu_items.append(Option(label, id=mid))
                if mid == "running_tasks":
                    menu_items.append(None)
            yield OptionList(*menu_items, id="menu-list")
        yield Footer()

    def on_mount(self) -> None:
        self._update_logo_visibility()
        self.query_one("#menu-list", OptionList).focus()

    def on_resize(self) -> None:
        self._update_logo_visibility()

    def _update_logo_visibility(self) -> None:
        logo = self.query_one("#logo")
        logo.display = self.app.size.width >= 80

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "quit":
            self.app.exit()
        elif option_id:
            self.app.push_screen(option_id)

    def action_quit_app(self) -> None:
        self.app.exit()
