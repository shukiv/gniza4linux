from __future__ import annotations
from typing import Optional

from pathlib import Path

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Static, Button, Input
from textual.containers import Horizontal, Vertical


class _DirOnly(DirectoryTree):
    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir()]


class FolderPicker(ModalScreen[Optional[str]]):

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str = "Select folder", start: str = "/"):
        super().__init__()
        self._title = title
        self._start = start

    def compose(self) -> ComposeResult:
        with Vertical(id="folder-picker"):
            yield Static(self._title, id="fp-title")
            with Horizontal(id="fp-search-row"):
                yield Input(placeholder="Go to path (e.g. /var/www)", id="fp-search")
                yield Button("Go", id="fp-go", variant="primary")
            yield _DirOnly(self._start, id="fp-tree")
            with Horizontal(id="fp-new-row"):
                yield Input(placeholder="New folder name", id="fp-new-name")
                yield Button("Create Folder", id="fp-create")
            with Horizontal(id="fp-buttons"):
                yield Button("Select", variant="primary", id="fp-select")
                yield Button("Cancel", variant="default", id="fp-cancel")

    def _get_selected_path(self) -> Path | None:
        tree = self.query_one("#fp-tree", DirectoryTree)
        node = tree.cursor_node
        if node and node.data and node.data.path:
            return node.data.path.resolve()
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fp-select":
            path = self._get_selected_path()
            self.dismiss(str(path) if path else None)
        elif event.button.id == "fp-go":
            self._go_to_path()
        elif event.button.id == "fp-create":
            self._create_folder()
        else:
            self.dismiss(None)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#fp-search", Input).value = str(event.path.resolve())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fp-search":
            self._go_to_path()

    def _go_to_path(self) -> None:
        raw = self.query_one("#fp-search", Input).value.strip()
        if not raw:
            return
        target = Path(raw).expanduser().resolve()
        if not target.is_dir():
            self.notify(f"Not a directory: {target}", severity="error")
            return
        # Replace the tree with a new root
        tree = self.query_one("#fp-tree", _DirOnly)
        tree.path = target
        tree.reload()

    def _create_folder(self) -> None:
        name = self.query_one("#fp-new-name", Input).value.strip()
        if not name:
            self.notify("Enter a folder name", severity="error")
            return
        if "/" in name or "\0" in name:
            self.notify("Invalid folder name", severity="error")
            return
        parent = self._get_selected_path()
        if not parent:
            parent = Path(self._start)
        new_dir = parent / name
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            self.notify(f"Created: {new_dir}")
            tree = self.query_one("#fp-tree", DirectoryTree)
            tree.reload()
            self.query_one("#fp-new-name", Input).value = ""
        except OSError as e:
            self.notify(f"Failed: {e}", severity="error")

    def action_cancel(self) -> None:
        self.dismiss(None)
