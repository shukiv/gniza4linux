from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Header, Footer, Static, Button
from textual.containers import Horizontal, Vertical
from pathlib import Path


class _DirOnly(DirectoryTree):
    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir()]


class FolderPicker(ModalScreen[str | None]):

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str = "Select folder", start: str = "/"):
        super().__init__()
        self._title = title
        self._start = start

    def compose(self) -> ComposeResult:
        with Vertical(id="folder-picker"):
            yield Static(self._title, id="fp-title")
            yield _DirOnly(self._start, id="fp-tree")
            with Horizontal(id="fp-buttons"):
                yield Button("Select", variant="primary", id="fp-select")
                yield Button("Cancel", variant="default", id="fp-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fp-select":
            tree = self.query_one("#fp-tree", DirectoryTree)
            node = tree.cursor_node
            if node and node.data and node.data.path:
                self.dismiss(str(node.data.path))
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
