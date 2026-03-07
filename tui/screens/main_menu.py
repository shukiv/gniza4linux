from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, OptionList
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.widgets.option_list import Option
from textual.containers import Horizontal, Vertical

from tui.jobs import job_manager

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
    ("targets", "Sources"),
    ("remotes", "Destinations"),
    None,
    ("backup", "Backup"),
    ("restore", "Restore"),
    ("running_tasks", "Running Tasks"),
    None,
    ("schedule", "Schedules"),
    ("snapshots", "Snapshots"),
    ("logs", "Logs"),
    ("settings", "Settings"),
    None,
    ("quit", "Quit"),
]

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class MainMenuScreen(Screen):

    BINDINGS = [("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            yield Static(LOGO, id="logo", markup=True)
            menu_items = []
            for item in MENU_ITEMS:
                if item is None:
                    menu_items.append(None)
                else:
                    mid, label = item
                    menu_items.append(Option(label, id=mid))
            yield OptionList(*menu_items, id="menu-list")
        yield Footer()

    def on_mount(self) -> None:
        self._update_layout()
        self.query_one("#menu-list", OptionList).focus()
        self._spinner_idx = 0
        self._update_running_label()
        self._spinner_timer = self.set_interval(1, self._tick_spinner)

    def on_resize(self) -> None:
        self._update_layout()

    def _update_layout(self) -> None:
        width = self.app.size.width
        logo = self.query_one("#logo")
        layout = self.query_one("#main-layout")
        logo.display = width >= 100
        if width < 100:
            layout.styles.layout = "vertical"
            layout.styles.align = ("center", "top")
            layout.styles.overflow_y = "auto"
        else:
            layout.styles.layout = "horizontal"
            layout.styles.align = ("center", "middle")
            layout.styles.overflow_y = "hidden"

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        self._update_running_label()

    def _update_running_label(self) -> None:
        count = job_manager.running_count()
        menu = self.query_one("#menu-list", OptionList)
        # Find the running_tasks option index
        for idx in range(menu.option_count):
            opt = menu.get_option_at_index(idx)
            if opt.id == "running_tasks":
                if count > 0:
                    spinner = SPINNER_FRAMES[self._spinner_idx]
                    label = f"{spinner} Running Tasks ({count})"
                else:
                    label = "Running Tasks"
                menu.replace_option_prompt(opt.id, label)
                break

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id == "quit":
            self.app.exit()
        elif option_id:
            self.app.push_screen(option_id)

    def action_quit_app(self) -> None:
        self.app.exit()
