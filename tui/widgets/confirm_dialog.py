from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static, Button
from textual.containers import Horizontal, Vertical


class ConfirmDialog(ModalScreen[bool]):

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str, title: str = "Confirm"):
        super().__init__()
        self._message = message
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._title, id="cd-title")
            yield Static(self._message, id="cd-message")
            with Horizontal(id="cd-buttons"):
                yield Button("Yes", variant="primary", id="cd-yes")
                yield Button("No", variant="default", id="cd-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "cd-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)
