from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import RichLog, Button, Static
from textual.containers import Vertical


class OperationLog(ModalScreen[None]):

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str = "Operation Output"):
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="op-log"):
            yield Static(self._title, id="ol-title")
            yield RichLog(id="ol-log", wrap=True, highlight=True, markup=True)
            yield Button("Close", variant="primary", id="ol-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def write(self, text: str) -> None:
        self.query_one("#ol-log", RichLog).write(text)
