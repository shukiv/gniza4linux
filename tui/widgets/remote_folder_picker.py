import os
import subprocess

from textual.app import ComposeResult
from web.ssh_utils import ssh_cmd
from textual.screen import ModalScreen
from textual.widgets import Tree, Static, Button, Input
from textual.containers import Horizontal, Vertical


class RemoteFolderPicker(ModalScreen[str | None]):
    """Browse directories on a remote SSH host."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        host: str,
        user: str = "root",
        port: str = "22",
        auth_method: str = "key",
        key: str = "",
        password: str = "",
        title: str = "Select remote folder",
    ):
        super().__init__()
        self._title = title
        self._host = host
        self._user = user
        self._port = port
        self._auth_method = auth_method
        self._key = key
        self._password = password

    def compose(self) -> ComposeResult:
        with Vertical(id="folder-picker"):
            yield Static(f"{self._title} ({self._user}@{self._host})", id="fp-title")
            with Horizontal(id="fp-search-row"):
                yield Input(placeholder="Go to path (e.g. /var/www)", id="fp-search")
                yield Button("Go", id="fp-go", variant="primary")
            yield Tree("/", id="fp-remote-tree")
            with Horizontal(id="fp-buttons"):
                yield Button("Select", variant="primary", id="fp-select")
                yield Button("Cancel", variant="default", id="fp-cancel")

    def on_mount(self) -> None:
        tree = self.query_one("#fp-remote-tree", Tree)
        tree.root.data = "/"
        tree.root.set_label("/")
        tree.root.allow_expand = True
        self._load_children(tree.root, "/")

    def _list_dirs(self, path: str) -> list[str]:
        key = self._key if self._auth_method == "key" else ""
        password = self._password if self._auth_method == "password" else ""
        cmd = ssh_cmd(self._host, self._port, self._user, key, password) + [
            f"find {path!r} -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort"
        ]
        env = None
        if self._auth_method == "password" and self._password:
            env = os.environ.copy()
            env["SSHPASS"] = self._password
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, env=env,
            )
            if result.returncode != 0:
                return []
            dirs = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line and line != path:
                    dirs.append(line)
            return dirs
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _load_children(self, node, path: str) -> None:
        dirs = self._list_dirs(path)
        node.remove_children()
        if not dirs:
            return
        for d in dirs:
            name = d.rstrip("/").rsplit("/", 1)[-1]
            child = node.add(name, data=d, allow_expand=True)
            # Add a placeholder so the expand arrow shows
            child.add_leaf("...", data=None)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if node.data is None:
            return
        # Check if children are just the placeholder
        children = list(node.children)
        if len(children) == 1 and children[0].data is None:
            self._load_children(node, node.data)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fp-select":
            tree = self.query_one("#fp-remote-tree", Tree)
            node = tree.cursor_node
            if node and node.data:
                self.dismiss(str(node.data))
            else:
                self.dismiss(None)
        elif event.button.id == "fp-go":
            self._go_to_path()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fp-search":
            self._go_to_path()

    def _go_to_path(self) -> None:
        raw = self.query_one("#fp-search", Input).value.strip()
        if not raw:
            return
        path = raw if raw.startswith("/") else "/" + raw
        dirs = self._list_dirs(path)
        tree = self.query_one("#fp-remote-tree", Tree)
        tree.clear()
        tree.root.data = path
        tree.root.set_label(path)
        if not dirs:
            self.notify(f"No subdirectories in {path}", severity="warning")
            return
        for d in dirs:
            name = d.rstrip("/").rsplit("/", 1)[-1]
            child = tree.root.add(name, data=d, allow_expand=True)
            child.add_leaf("...", data=None)
        tree.root.expand()

    def action_cancel(self) -> None:
        self.dismiss(None)
