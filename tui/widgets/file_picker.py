from pathlib import Path

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Static, Button
from textual.containers import Horizontal, Vertical


class FilePicker(ModalScreen[str | None]):

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str = "Select file", start: str = "/"):
        super().__init__()
        self._title = title
        self._start = start

    def compose(self) -> ComposeResult:
        with Vertical(id="file-picker"):
            yield Static(self._title, id="fip-title")
            yield DirectoryTree(self._start, id="fip-tree")
            with Horizontal(id="fip-buttons"):
                yield Button("Select", variant="primary", id="fip-select")
                yield Button("Cancel", variant="default", id="fip-cancel")

    def _get_selected_path(self) -> Path | None:
        tree = self.query_one("#fip-tree", DirectoryTree)
        node = tree.cursor_node
        if node and node.data and node.data.path:
            return node.data.path
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fip-select":
            path = self._get_selected_path()
            if path and path.is_file():
                self.dismiss(str(path))
            elif path and path.is_dir():
                self.notify("Please select a file, not a directory", severity="warning")
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
