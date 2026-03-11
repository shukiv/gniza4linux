import os
import re
import subprocess
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Input, Select, RadioSet, RadioButton
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from tui.config import parse_conf, write_conf, CONFIG_DIR
from web.ssh_utils import ssh_cmd
from tui.models import Target
from tui.widgets import FolderPicker, RemoteFolderPicker, DocsPanel, TagList

_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,31}$')


class TargetEditScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, name: str = ""):
        super().__init__()
        self._edit_name = name
        self._is_new = not name

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        title = "Add Source" if self._is_new else f"Edit Source: {self._edit_name}"
        target = Target()
        if not self._is_new:
            data = parse_conf(CONFIG_DIR / "targets.d" / f"{self._edit_name}.conf")
            target = Target.from_conf(self._edit_name, data)

        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="target-edit"):
                yield Static(title, id="screen-title")
                yield Static("--- Source ---", classes="section-label")
                yield Static("Source Type:")
                with RadioSet(id="te-source-type"):
                    yield RadioButton("Local", value=target.source_type == "local")
                    yield RadioButton("SSH", value=target.source_type == "ssh")
                    yield RadioButton("S3", value=target.source_type == "s3")
                    yield RadioButton("Google Drive", value=target.source_type == "gdrive")
                if self._is_new:
                    yield Static("Name:")
                    yield Input(value="", placeholder="Target name", id="te-name")
                yield Static("Source Host:", classes="source-field source-ssh-field")
                yield Input(value=target.source_host, placeholder="hostname or IP", id="te-source-host", classes="source-field source-ssh-field")
                yield Static("Source Port:", classes="source-field source-ssh-field")
                yield Input(value=target.source_port, placeholder="22", id="te-source-port", classes="source-field source-ssh-field")
                yield Static("Source User:", classes="source-field source-ssh-field")
                yield Input(value=target.source_user, placeholder="root", id="te-source-user", classes="source-field source-ssh-field")
                yield Static("Auth Method:", classes="source-field source-ssh-field")
                yield Select(
                    [("SSH Key", "key"), ("Password", "password")],
                    value=target.source_auth_method,
                    id="te-source-auth-method",
                    classes="source-field source-ssh-field",
                )
                yield Static("SSH Key Path:", classes="source-field source-ssh-field source-key-field")
                yield Input(value=target.source_key, placeholder="/root/.ssh/id_rsa", id="te-source-key", classes="source-field source-ssh-field source-key-field")
                yield Static("Password:", classes="source-field source-ssh-field source-password-field")
                yield Input(value=target.source_password, placeholder="SSH password", password=True, id="te-source-password", classes="source-field source-ssh-field source-password-field")
                yield Static("S3 Bucket:", classes="source-field source-s3-field")
                yield Input(value=target.source_s3_bucket, placeholder="my-bucket", id="te-source-s3-bucket", classes="source-field source-s3-field")
                yield Static("S3 Region:", classes="source-field source-s3-field")
                yield Input(value=target.source_s3_region, placeholder="us-east-1", id="te-source-s3-region", classes="source-field source-s3-field")
                yield Static("S3 Endpoint:", classes="source-field source-s3-field")
                yield Input(value=target.source_s3_endpoint, placeholder="https://s3.amazonaws.com", id="te-source-s3-endpoint", classes="source-field source-s3-field")
                yield Static("S3 Access Key:", classes="source-field source-s3-field")
                yield Input(value=target.source_s3_access_key_id, placeholder="AKIA...", id="te-source-s3-access-key", classes="source-field source-s3-field")
                yield Static("S3 Secret Key:", classes="source-field source-s3-field")
                yield Input(value=target.source_s3_secret_access_key, placeholder="secret", password=True, id="te-source-s3-secret-key", classes="source-field source-s3-field")
                yield Static("Service Account File:", classes="source-field source-gdrive-field")
                yield Input(value=target.source_gdrive_sa_file, placeholder="/path/to/sa.json", id="te-source-gdrive-sa-file", classes="source-field source-gdrive-field")
                yield Static("Root Folder ID:", classes="source-field source-gdrive-field")
                yield Input(value=target.source_gdrive_root_folder_id, placeholder="folder ID", id="te-source-gdrive-root-folder-id", classes="source-field source-gdrive-field")
                yield Static("Folders:")
                folder_items = [f.strip() for f in target.folders.split(",") if f.strip()]
                yield TagList(items=folder_items, placeholder="/path/to/folder", widget_id="te-folders", show_browse=True)
                yield Static("Include patterns:")
                yield Input(value=target.include, placeholder="*.conf,docs/", id="te-include")
                yield Static("Exclude patterns:")
                yield Input(value=target.exclude, placeholder="*.tmp,*.log", id="te-exclude")
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
                yield Static("--- MySQL Backup ---", classes="section-label mysql-section")
                yield Static("MySQL Enabled:", classes="mysql-section")
                yield Select(
                    [("No", "no"), ("Yes", "yes")],
                    value=target.mysql_enabled,
                    id="te-mysql-enabled",
                    classes="mysql-section",
                )
                yield Static("MySQL Mode:", classes="mysql-field")
                yield Select(
                    [("All databases", "all"), ("Specific databases", "specific")],
                    value=target.mysql_mode,
                    id="te-mysql-mode",
                    classes="mysql-field",
                )
                yield Static("Databases (comma-separated):", classes="mysql-field mysql-select-field")
                yield Input(value=target.mysql_databases, placeholder="db1,db2", id="te-mysql-databases", classes="mysql-field mysql-select-field")
                yield Static("Exclude databases (comma-separated):", classes="mysql-field mysql-all-field")
                yield Input(value=target.mysql_exclude, placeholder="test_db,dev_db", id="te-mysql-exclude", classes="mysql-field mysql-all-field")
                yield Static("MySQL User:", classes="mysql-field")
                yield Input(value=target.mysql_user, placeholder="Leave empty for socket/~/.my.cnf auth", id="te-mysql-user", classes="mysql-field")
                yield Static("MySQL Password:", classes="mysql-field")
                yield Input(value=target.mysql_password, placeholder="Leave empty for socket/~/.my.cnf auth", password=True, id="te-mysql-password", classes="mysql-field")
                yield Static("MySQL Host:", classes="mysql-field")
                yield Input(value=target.mysql_host, placeholder="localhost", id="te-mysql-host", classes="mysql-field")
                yield Static("MySQL Port:", classes="mysql-field")
                yield Input(value=target.mysql_port, placeholder="3306", id="te-mysql-port", classes="mysql-field")
                yield Static("MySQL Extra Options:", classes="mysql-field")
                yield Input(value=target.mysql_extra_opts, placeholder="--single-transaction --routines --triggers", id="te-mysql-extra-opts", classes="mysql-field")
                with Horizontal(id="te-buttons"):
                    yield Button("Test & Save", variant="primary", id="btn-save")
                    yield Button("Cancel", id="btn-cancel")
            yield DocsPanel.for_screen("target-edit")
        yield Footer()

    def on_mount(self) -> None:
        self._update_mysql_visibility()
        self._update_source_visibility()

    _SOURCE_TYPE_MAP = {"Local": "local", "SSH": "ssh", "S3": "s3", "Google Drive": "gdrive"}
    _SOURCE_TYPE_RMAP = {v: k for k, v in _SOURCE_TYPE_MAP.items()}

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("te-mysql-enabled", "te-mysql-mode"):
            self._update_mysql_visibility()
        elif event.select.id == "te-source-auth-method":
            self._update_source_visibility()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "te-source-type":
            self._update_source_visibility()

    def _update_mysql_visibility(self) -> None:
        enabled = str(self.query_one("#te-mysql-enabled", Select).value)
        is_enabled = enabled == "yes"
        for w in self.query(".mysql-field"):
            w.display = is_enabled
        if is_enabled:
            mode = str(self.query_one("#te-mysql-mode", Select).value)
            for w in self.query(".mysql-select-field"):
                w.display = mode == "specific"
            for w in self.query(".mysql-all-field"):
                w.display = mode == "all"

    def _get_source_type(self) -> str:
        radio = self.query_one("#te-source-type", RadioSet)
        label = str(radio.pressed_button.label) if radio.pressed_button else "Local"
        return self._SOURCE_TYPE_MAP.get(label, "local")

    def _update_source_visibility(self) -> None:
        source_type = self._get_source_type()
        is_remote = source_type != "local"
        # Hide all source fields first
        for w in self.query(".source-field"):
            w.display = False
        # Show fields for selected source type
        if source_type == "ssh":
            for w in self.query(".source-ssh-field"):
                w.display = True
            # Toggle key/password based on auth method
            auth = str(self.query_one("#te-source-auth-method", Select).value)
            for w in self.query(".source-key-field"):
                w.display = auth == "key"
            for w in self.query(".source-password-field"):
                w.display = auth == "password"
        elif source_type == "s3":
            for w in self.query(".source-s3-field"):
                w.display = True
        elif source_type == "gdrive":
            for w in self.query(".source-gdrive-field"):
                w.display = True
        # Hide MySQL section for S3/GDrive (no MySQL on cloud sources)
        show_mysql = source_type in ("local", "ssh")
        for w in self.query(".mysql-section"):
            w.display = show_mysql
        if show_mysql:
            self._update_mysql_visibility()
        else:
            for w in self.query(".mysql-field"):
                w.display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-browse":
            source_type = self._get_source_type()
            if source_type == "ssh":
                host = self.query_one("#te-source-host", Input).value.strip()
                if not host:
                    self.notify("Enter Source Host first", severity="error")
                    return
                self.app.push_screen(
                    RemoteFolderPicker(
                        host=host,
                        user=self.query_one("#te-source-user", Input).value.strip() or "root",
                        port=self.query_one("#te-source-port", Input).value.strip() or "22",
                        auth_method=str(self.query_one("#te-source-auth-method", Select).value),
                        key=self.query_one("#te-source-key", Input).value.strip(),
                        password=self.query_one("#te-source-password", Input).value.strip(),
                    ),
                    callback=self._folder_selected,
                )
            else:
                self.app.push_screen(
                    FolderPicker("Select folder to back up"),
                    callback=self._folder_selected,
                )
        elif event.button.id == "btn-save":
            self._save()

    def _folder_selected(self, path: str | None) -> None:
        if path:
            self.query_one("#te-folders", TagList).add_item(path)

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

        folders = self.query_one("#te-folders", TagList).value
        mysql_enabled = str(self.query_one("#te-mysql-enabled", Select).value)
        source_type = self._get_source_type()
        if not folders and mysql_enabled != "yes" and source_type == "local":
            self.notify("At least one folder or MySQL backup is required", severity="error")
            return
        if source_type != "local" and not folders:
            self.notify("At least one remote path is required", severity="error")
            return

        target = Target(
            name=name,
            folders=folders,
            exclude=self.query_one("#te-exclude", Input).value.strip(),
            include=self.query_one("#te-include", Input).value.strip(),
            remote="",
            pre_hook=self.query_one("#te-prehook", Input).value.strip(),
            post_hook=self.query_one("#te-posthook", Input).value.strip(),
            enabled=str(self.query_one("#te-enabled", Select).value),
            source_type=source_type,
            source_host=self.query_one("#te-source-host", Input).value.strip(),
            source_port=self.query_one("#te-source-port", Input).value.strip(),
            source_user=self.query_one("#te-source-user", Input).value.strip(),
            source_auth_method=str(self.query_one("#te-source-auth-method", Select).value),
            source_key=self.query_one("#te-source-key", Input).value.strip(),
            source_password=self.query_one("#te-source-password", Input).value.strip(),
            source_s3_bucket=self.query_one("#te-source-s3-bucket", Input).value.strip(),
            source_s3_region=self.query_one("#te-source-s3-region", Input).value.strip(),
            source_s3_endpoint=self.query_one("#te-source-s3-endpoint", Input).value.strip(),
            source_s3_access_key_id=self.query_one("#te-source-s3-access-key", Input).value.strip(),
            source_s3_secret_access_key=self.query_one("#te-source-s3-secret-key", Input).value.strip(),
            source_gdrive_sa_file=self.query_one("#te-source-gdrive-sa-file", Input).value.strip(),
            source_gdrive_root_folder_id=self.query_one("#te-source-gdrive-root-folder-id", Input).value.strip(),
            mysql_enabled=mysql_enabled,
            mysql_mode=str(self.query_one("#te-mysql-mode", Select).value),
            mysql_databases=self.query_one("#te-mysql-databases", Input).value.strip(),
            mysql_exclude=self.query_one("#te-mysql-exclude", Input).value.strip(),
            mysql_user=self.query_one("#te-mysql-user", Input).value.strip(),
            mysql_password=self.query_one("#te-mysql-password", Input).value.strip(),
            mysql_host=self.query_one("#te-mysql-host", Input).value.strip(),
            mysql_port=self.query_one("#te-mysql-port", Input).value.strip(),
            mysql_extra_opts=self.query_one("#te-mysql-extra-opts", Input).value.strip(),
        )

        if not self._test_source(target):
            return

        conf = CONFIG_DIR / "targets.d" / f"{name}.conf"
        write_conf(conf, target.to_conf())
        self.notify(f"Target '{name}' saved.")
        self.dismiss(name)

    def _test_source(self, target: Target) -> bool:
        if target.source_type == "local":
            if target.folders:
                folder_list = [f.strip() for f in target.folders.split(",") if f.strip()]
                missing = [f for f in folder_list if not os.path.isdir(f)]
                if missing:
                    self.notify(f"Warning: folders not found: {', '.join(missing)}", severity="warning")
            return True

        if target.source_type == "ssh":
            self.notify("Testing SSH connection...")
            host = target.source_host
            port = target.source_port or "22"
            user = target.source_user or "root"
            key = target.source_key if target.source_auth_method == "key" else ""
            password = target.source_password if target.source_auth_method == "password" else ""
            cmd = ssh_cmd(host, port, user, key, password)
            env = None
            if password:
                env = os.environ.copy()
                env["SSHPASS"] = password
            try:
                result = subprocess.run(cmd + ["echo", "ok"], capture_output=True, text=True, timeout=15, env=env)
                if result.returncode != 0:
                    self.notify(f"SSH connection failed: {result.stderr.strip() or 'unknown error'}", severity="error")
                    return False
            except subprocess.TimeoutExpired:
                self.notify("SSH connection timed out", severity="error")
                return False
            except OSError as e:
                self.notify(f"SSH connection failed: {e}", severity="error")
                return False
            if target.folders:
                folder_list = [f.strip() for f in target.folders.split(",") if f.strip()]
                try:
                    result = subprocess.run(
                        cmd + ["test", "-d", folder_list[0]],
                        capture_output=True, text=True, timeout=15, env=env,
                    )
                    if result.returncode != 0:
                        self.notify(f"Warning: folder '{folder_list[0]}' not accessible on remote", severity="warning")
                except (subprocess.TimeoutExpired, OSError):
                    pass
            return True

        if target.source_type == "s3":
            self.notify("Testing S3 connection...")
            from tui.rclone_test import test_rclone_s3
            ok, err = test_rclone_s3(
                bucket=target.source_s3_bucket,
                region=target.source_s3_region,
                endpoint=target.source_s3_endpoint,
                access_key_id=target.source_s3_access_key_id,
                secret_access_key=target.source_s3_secret_access_key,
                provider=target.source_s3_provider,
            )
            if not ok:
                self.notify(f"S3 test failed: {err}", severity="error")
                return False
            return True

        if target.source_type == "gdrive":
            self.notify("Testing Google Drive connection...")
            from tui.rclone_test import test_rclone_gdrive
            ok, err = test_rclone_gdrive(
                sa_file=target.source_gdrive_sa_file,
                root_folder_id=target.source_gdrive_root_folder_id,
            )
            if not ok:
                self.notify(f"Google Drive test failed: {err}", severity="error")
                return False
            return True

        return True

    def action_go_back(self) -> None:
        self.dismiss(None)
