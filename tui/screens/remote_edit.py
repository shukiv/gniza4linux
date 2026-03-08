import os
import re
import subprocess
from pathlib import Path
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select, RadioSet, RadioButton
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from tui.config import parse_conf, write_conf, CONFIG_DIR
from tui.models import Remote
from tui.widgets import FilePicker, DocsPanel, RemoteFolderPicker
from tui.widgets.folder_picker import FolderPicker

_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,31}$')

REMOTE_TYPES = [("SSH", "ssh"), ("Local", "local"), ("S3", "s3"), ("Google Drive", "gdrive")]


_TYPE_MAP = {"SSH": "ssh", "Local": "local", "S3": "s3", "Google Drive": "gdrive"}


class RemoteEditScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, name: str = ""):
        super().__init__()
        self._edit_name = name
        self._is_new = not name

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        title = "Add Destination" if self._is_new else f"Edit Destination: {self._edit_name}"
        remote = Remote()
        if not self._is_new:
            data = parse_conf(CONFIG_DIR / "remotes.d" / f"{self._edit_name}.conf")
            remote = Remote.from_conf(self._edit_name, data)

        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="remote-edit"):
                yield Static(title, id="screen-title")
                yield Static("Type:")
                with RadioSet(id="re-type"):
                    yield RadioButton("SSH", value=remote.type == "ssh")
                    yield RadioButton("Local", value=remote.type == "local")
                    yield RadioButton("S3", value=remote.type == "s3")
                    yield RadioButton("Google Drive", value=remote.type == "gdrive")
                if self._is_new:
                    yield Static("Name:")
                    yield Input(value="", placeholder="Remote name", id="re-name")
                # SSH fields
                yield Static("Host:", id="lbl-host", classes="ssh-field")
                yield Input(value=remote.host, placeholder="hostname or IP", id="re-host", classes="ssh-field")
                yield Static("Port:", id="lbl-port", classes="ssh-field")
                yield Input(value=remote.port, placeholder="22", id="re-port", classes="ssh-field")
                yield Static("User:", id="lbl-user", classes="ssh-field")
                yield Input(value=remote.user, placeholder="root", id="re-user", classes="ssh-field")
                yield Static("Auth method:", id="lbl-auth", classes="ssh-field")
                yield Select(
                    [("SSH Key", "key"), ("Password", "password")],
                    id="re-auth",
                    value=remote.auth_method,
                    classes="ssh-field",
                )
                yield Static("SSH Key path:", id="lbl-key", classes="ssh-field ssh-key-field")
                with Horizontal(id="re-key-row", classes="ssh-field ssh-key-field"):
                    yield Input(value=remote.key, placeholder="~/.ssh/id_rsa", id="re-key")
                    yield Button("Browse...", id="btn-browse-key")
                yield Static("Password:", id="lbl-password", classes="ssh-field ssh-password-field")
                yield Input(value=remote.password, placeholder="SSH password", password=True, id="re-password", classes="ssh-field ssh-password-field")
                # Common fields
                yield Static("Base path:")
                with Horizontal(id="re-base-row"):
                    yield Input(value=remote.base, placeholder="/backups", id="re-base")
                    yield Button("Browse...", id="btn-browse-base")
                yield Static("Bandwidth limit (KB/s, 0=unlimited):")
                yield Input(value=remote.bwlimit, placeholder="0", id="re-bwlimit")
                # S3 fields
                yield Static("S3 Bucket:", id="lbl-s3bucket", classes="s3-field")
                yield Input(value=remote.s3_bucket, placeholder="bucket-name", id="re-s3bucket", classes="s3-field")
                yield Static("S3 Region:", id="lbl-s3region", classes="s3-field")
                yield Input(value=remote.s3_region, placeholder="us-east-1", id="re-s3region", classes="s3-field")
                yield Static("S3 Endpoint:", id="lbl-s3endpoint", classes="s3-field")
                yield Input(value=remote.s3_endpoint, placeholder="Leave empty for AWS", id="re-s3endpoint", classes="s3-field")
                yield Static("Access Key ID:", id="lbl-s3key", classes="s3-field")
                yield Input(value=remote.s3_access_key_id, id="re-s3key", classes="s3-field")
                yield Static("Secret Access Key:", id="lbl-s3secret", classes="s3-field")
                yield Input(value=remote.s3_secret_access_key, password=True, id="re-s3secret", classes="s3-field")
                # GDrive fields
                yield Static("Service Account JSON:", id="lbl-gdsa", classes="gdrive-field")
                yield Input(value=remote.gdrive_sa_file, placeholder="/path/to/sa.json", id="re-gdsa", classes="gdrive-field")
                yield Static("Root Folder ID:", id="lbl-gdfolder", classes="gdrive-field")
                yield Input(value=remote.gdrive_root_folder_id, id="re-gdfolder", classes="gdrive-field")
                with Horizontal(id="re-buttons"):
                    yield Button("Test & Save", variant="primary", id="btn-save")
                    yield Button("Cancel", id="btn-cancel")
            yield DocsPanel.for_screen("remote-edit")
        yield Footer()

    def on_mount(self) -> None:
        self._update_field_visibility()

    def _get_remote_type(self) -> str:
        radio = self.query_one("#re-type", RadioSet)
        label = str(radio.pressed_button.label) if radio.pressed_button else "SSH"
        return _TYPE_MAP.get(label, "ssh")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "re-auth":
            self._update_field_visibility()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "re-type":
            self._update_field_visibility()

    def _update_field_visibility(self) -> None:
        rtype = self._get_remote_type()
        is_ssh = rtype == "ssh"
        for w in self.query(".ssh-field"):
            w.display = is_ssh
        for w in self.query(".s3-field"):
            w.display = rtype == "s3"
        for w in self.query(".gdrive-field"):
            w.display = rtype == "gdrive"
        # Toggle key vs password fields based on auth method
        if is_ssh:
            auth_sel = self.query_one("#re-auth", Select)
            auth = str(auth_sel.value) if isinstance(auth_sel.value, str) else "key"
            for w in self.query(".ssh-key-field"):
                w.display = auth == "key"
            for w in self.query(".ssh-password-field"):
                w.display = auth == "password"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-browse-key":
            self.app.push_screen(
                FilePicker("Select SSH key file", start=str(Path.home() / ".ssh")),
                callback=self._key_file_selected,
            )
        elif event.button.id == "btn-browse-base":
            self._browse_base_path()
        elif event.button.id == "btn-save":
            self._save()

    def _key_file_selected(self, path: str | None) -> None:
        if path:
            self.query_one("#re-key", Input).value = path

    def _browse_base_path(self) -> None:
        rtype = self._get_remote_type()
        current_base = self.query_one("#re-base", Input).value.strip() or "/"
        if rtype == "local":
            self.app.push_screen(
                FolderPicker("Select base path", start=current_base),
                callback=self._base_path_selected,
            )
        elif rtype == "ssh":
            host = self.query_one("#re-host", Input).value.strip()
            if not host:
                self.notify("Enter a host first", severity="error")
                return
            port = self.query_one("#re-port", Input).value.strip() or "22"
            user = self.query_one("#re-user", Input).value.strip() or "root"
            auth_sel = self.query_one("#re-auth", Select)
            auth = str(auth_sel.value) if isinstance(auth_sel.value, str) else "key"
            key = self.query_one("#re-key", Input).value.strip() if auth == "key" else ""
            password = self.query_one("#re-password", Input).value if auth == "password" else ""
            self.app.push_screen(
                RemoteFolderPicker(
                    host=host, port=port, user=user,
                    auth_method=auth, key=key, password=password,
                ),
                callback=self._base_path_selected,
            )
        else:
            self.notify("Browse not available for this destination type", severity="warning")

    def _base_path_selected(self, path: str | None) -> None:
        if path:
            self.query_one("#re-base", Input).value = path

    def _save(self) -> None:
        if self._is_new:
            name = self.query_one("#re-name", Input).value.strip()
            if not name:
                self.notify("Name is required", severity="error")
                return
            if not _NAME_RE.match(name):
                self.notify("Invalid name.", severity="error")
                return
            if (CONFIG_DIR / "remotes.d" / f"{name}.conf").exists():
                self.notify(f"Destination '{name}' already exists.", severity="error")
                return
        else:
            name = self._edit_name

        rtype = self._get_remote_type()

        remote = Remote(
            name=name,
            type=rtype,
            host=self.query_one("#re-host", Input).value.strip(),
            port=self.query_one("#re-port", Input).value.strip() or "22",
            user=self.query_one("#re-user", Input).value.strip() or "root",
            auth_method=str(self.query_one("#re-auth", Select).value) if isinstance(self.query_one("#re-auth", Select).value, str) else "key",
            key=self.query_one("#re-key", Input).value.strip(),
            password=self.query_one("#re-password", Input).value,
            base=self.query_one("#re-base", Input).value.strip() or "/backups",
            bwlimit=self.query_one("#re-bwlimit", Input).value.strip() or "0",
            s3_bucket=self.query_one("#re-s3bucket", Input).value.strip(),
            s3_region=self.query_one("#re-s3region", Input).value.strip() or "us-east-1",
            s3_endpoint=self.query_one("#re-s3endpoint", Input).value.strip(),
            s3_access_key_id=self.query_one("#re-s3key", Input).value.strip(),
            s3_secret_access_key=self.query_one("#re-s3secret", Input).value,
            gdrive_sa_file=self.query_one("#re-gdsa", Input).value.strip(),
            gdrive_root_folder_id=self.query_one("#re-gdfolder", Input).value.strip(),
        )

        if rtype == "ssh" and not remote.host:
            self.notify("Host is required for SSH destinations", severity="error")
            return

        if not self._test_remote(remote):
            return

        conf = CONFIG_DIR / "remotes.d" / f"{name}.conf"
        write_conf(conf, remote.to_conf())
        self.notify(f"Destination '{name}' saved.")
        self.dismiss(name)

    def _ssh_cmd(self, host, port="22", user="root", key="", password=""):
        ssh_opts = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-p", port or "22",
        ]
        if key:
            ssh_opts += ["-i", key]
        ssh_opts.append(f"{user}@{host}")
        if password:
            return ["sshpass", "-p", password] + ssh_opts
        return ssh_opts

    def _test_remote(self, remote: Remote) -> bool:
        if remote.type == "local":
            base = remote.base or "/backups"
            try:
                os.makedirs(base, exist_ok=True)
            except OSError as e:
                self.notify(f"Cannot create base path '{base}': {e}", severity="error")
                return False
            return True

        if remote.type == "ssh":
            self.notify("Testing SSH connection...")
            key = remote.key if remote.auth_method == "key" else ""
            password = remote.password if remote.auth_method == "password" else ""
            cmd = self._ssh_cmd(remote.host, remote.port, remote.user, key, password)
            base = remote.base or "/backups"
            try:
                result = subprocess.run(cmd + ["echo", "ok"], capture_output=True, text=True, timeout=15)
                if result.returncode != 0:
                    self.notify(f"SSH connection failed: {result.stderr.strip() or 'unknown error'}", severity="error")
                    return False
            except subprocess.TimeoutExpired:
                self.notify("SSH connection timed out", severity="error")
                return False
            except OSError as e:
                self.notify(f"SSH connection failed: {e}", severity="error")
                return False
            try:
                result = subprocess.run(cmd + ["mkdir", "-p", base], capture_output=True, text=True, timeout=15)
                if result.returncode != 0:
                    self.notify(f"Failed to create base path: {result.stderr.strip()}", severity="error")
                    return False
            except (subprocess.TimeoutExpired, OSError) as e:
                self.notify(f"Failed to create base path: {e}", severity="error")
                return False
            try:
                test_file = f"{base}/validation_success.txt"
                result = subprocess.run(
                    cmd + ["sh", "-c", f'echo "gniza validation" > {test_file}'],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode != 0:
                    self.notify(f"Failed to write test file: {result.stderr.strip()}", severity="error")
                    return False
            except (subprocess.TimeoutExpired, OSError) as e:
                self.notify(f"Failed to write test file: {e}", severity="error")
                return False
            return True

        if remote.type == "s3":
            self.notify("Testing S3 connection...")
            from tui.rclone_test import test_rclone_s3
            ok, err = test_rclone_s3(
                bucket=remote.s3_bucket,
                region=remote.s3_region,
                endpoint=remote.s3_endpoint,
                access_key_id=remote.s3_access_key_id,
                secret_access_key=remote.s3_secret_access_key,
            )
            if not ok:
                self.notify(f"S3 test failed: {err}", severity="error")
                return False
            return True

        if remote.type == "gdrive":
            self.notify("Testing Google Drive connection...")
            from tui.rclone_test import test_rclone_gdrive
            ok, err = test_rclone_gdrive(
                sa_file=remote.gdrive_sa_file,
                root_folder_id=remote.gdrive_root_folder_id,
            )
            if not ok:
                self.notify(f"Google Drive test failed: {err}", severity="error")
                return False
            return True

        return True

    def action_go_back(self) -> None:
        self.dismiss(None)
