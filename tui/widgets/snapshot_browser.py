from __future__ import annotations

from pathlib import PurePosixPath
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Tree, Static, Button
from textual.containers import Vertical, Horizontal


class SnapshotBrowser(ModalScreen[None]):
    """Modal file browser for remote snapshot contents."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str, file_list: list[str]):
        super().__init__()
        self._title = title
        self._file_list = file_list

    def compose(self) -> ComposeResult:
        with Vertical(id="snapshot-browser"):
            yield Static(self._title, id="sb-title")
            yield Tree("snapshot", id="sb-tree")
            with Horizontal(id="sb-buttons"):
                yield Button("Close", variant="primary", id="sb-close")

    def on_mount(self) -> None:
        tree = self.query_one("#sb-tree", Tree)
        tree.root.expand()
        self._build_tree(tree)

    def _build_tree(self, tree: Tree) -> None:
        # Build a nested dict from file paths
        root: dict = {}
        for filepath in self._file_list:
            filepath = filepath.strip()
            if not filepath:
                continue
            parts = PurePosixPath(filepath).parts
            node = root
            for part in parts:
                if part not in node:
                    node[part] = {}
                node = node[part]

        # Add to tree widget recursively
        self._add_nodes(tree.root, root)
        tree.root.expand_all()

    def _add_nodes(self, parent, structure: dict) -> None:
        # Sort: directories first, then files
        dirs = sorted(k for k, v in structure.items() if v)
        files = sorted(k for k, v in structure.items() if not v)
        for name in dirs:
            branch = parent.add(f"[bold]{name}/[/bold]")
            self._add_nodes(branch, structure[name])
        for name in files:
            parent.add_leaf(name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
