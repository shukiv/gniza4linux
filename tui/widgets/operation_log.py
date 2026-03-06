from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import RichLog, Button, Static
from textual.containers import Vertical


class OperationLog(ModalScreen[None]):

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str = "Operation Output"):
        super().__init__()
        self._title = title
        self._running = True

    def compose(self) -> ComposeResult:
        with Vertical(id="op-log"):
            yield Static(self._title, id="ol-title")
            yield Static("Running...", id="ol-status")
            yield Button("Close", variant="primary", id="ol-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def finish(self) -> None:
        self._running = False
        try:
            self.query_one("#ol-status", Static).update("Done ✅")
        except Exception:
            pass

    def write(self, text: str) -> None:
        try:
            self.query_one("#ol-status", Static).update(text)
        except Exception:
            pass
