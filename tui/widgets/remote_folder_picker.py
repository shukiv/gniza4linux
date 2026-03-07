import subprocess

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Tree, Static, Button
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

    def _ssh_cmd(self) -> list[str]:
        ssh_opts = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-p", self._port,
        ]
        if self._auth_method == "key" and self._key:
            ssh_opts += ["-i", self._key]
        ssh_opts.append(f"{self._user}@{self._host}")
        if self._auth_method == "password" and self._password:
            return ["sshpass", "-p", self._password] + ssh_opts
        return ssh_opts

    def _list_dirs(self, path: str) -> list[str]:
        cmd = self._ssh_cmd() + [
            f"find {path!r} -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort"
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
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
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
