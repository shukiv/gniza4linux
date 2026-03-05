import re
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select
from textual.containers import Vertical, Horizontal

from tui.config import parse_conf, write_conf, CONFIG_DIR, list_conf_dir
from tui.models import Target
from tui.widgets import FolderPicker

_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,31}$')


class TargetEditScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, name: str = ""):
        super().__init__()
        self._edit_name = name
        self._is_new = not name

    def compose(self) -> ComposeResult:
        yield Header()
        title = "Add Target" if self._is_new else f"Edit Target: {self._edit_name}"
        target = Target()
        if not self._is_new:
            data = parse_conf(CONFIG_DIR / "targets.d" / f"{self._edit_name}.conf")
            target = Target.from_conf(self._edit_name, data)

        with Vertical(id="target-edit"):
            yield Static(title, id="screen-title")
            if self._is_new:
                yield Static("Name:")
                yield Input(value="", placeholder="Target name", id="te-name")
            yield Static("Folders (comma-separated):")
            yield Input(value=target.folders, placeholder="/path1,/path2", id="te-folders")
            yield Button("Browse...", id="btn-browse")
            yield Static("Exclude patterns:")
            yield Input(value=target.exclude, placeholder="*.tmp,*.log", id="te-exclude")
            yield Static("Remote override:")
            yield Input(value=target.remote, placeholder="Leave empty for default", id="te-remote")
            yield Static("Retention override:")
            yield Input(value=target.retention, placeholder="Leave empty for default", id="te-retention")
            yield Static("Pre-backup hook:")
            yield Input(value=target.pre_hook, placeholder="Command to run before backup", id="te-prehook")
            yield Static("Post-backup hook:")
            yield Input(value=target.post_hook, placeholder="Command to run after backup", id="te-posthook")
            yield Static("Enabled:")
            yield Select(
                [("Yes", "yes"), ("No", "no")],
                value="yes" if target.enabled == "yes" else "no",
                id="te-enabled",
            )
            with Horizontal(id="te-buttons"):
                yield Button("Save", variant="primary", id="btn-save")
                yield Button("Cancel", id="btn-cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-browse":
            self.app.push_screen(
                FolderPicker("Select folder to back up"),
                callback=self._folder_selected,
            )
        elif event.button.id == "btn-save":
            self._save()

    def _folder_selected(self, path: str | None) -> None:
        if path:
            folders_input = self.query_one("#te-folders", Input)
            current = folders_input.value.strip()
            if current:
                existing = [f.strip() for f in current.split(",")]
                if path not in existing:
                    folders_input.value = current + "," + path
            else:
                folders_input.value = path

    def _save(self) -> None:
        if self._is_new:
            name = self.query_one("#te-name", Input).value.strip()
            if not name:
                self.notify("Name is required", severity="error")
                return
            if not _NAME_RE.match(name):
                self.notify("Invalid name. Use letters, digits, _ - (max 32 chars, start with letter).", severity="error")
                return
            conf = CONFIG_DIR / "targets.d" / f"{name}.conf"
            if conf.exists():
                self.notify(f"Target '{name}' already exists.", severity="error")
                return
        else:
            name = self._edit_name

        folders = self.query_one("#te-folders", Input).value.strip()
        if not folders:
            self.notify("At least one folder is required", severity="error")
            return

        target = Target(
            name=name,
            folders=folders,
            exclude=self.query_one("#te-exclude", Input).value.strip(),
            remote=self.query_one("#te-remote", Input).value.strip(),
            retention=self.query_one("#te-retention", Input).value.strip(),
            pre_hook=self.query_one("#te-prehook", Input).value.strip(),
            post_hook=self.query_one("#te-posthook", Input).value.strip(),
            enabled=str(self.query_one("#te-enabled", Select).value),
        )
        conf = CONFIG_DIR / "targets.d" / f"{name}.conf"
        write_conf(conf, target.to_conf())
        self.notify(f"Target '{name}' saved.")
        self.dismiss(name)

    def action_go_back(self) -> None:
        self.dismiss(None)
