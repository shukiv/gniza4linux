from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from textual.containers import Vertical, Horizontal
from textual import work

from tui.config import list_conf_dir, parse_conf, CONFIG_DIR
from tui.backend import run_cli
from tui.widgets import ConfirmDialog, OperationLog


class RemotesScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="remotes-screen"):
            yield Static("Remotes", id="screen-title")
            yield DataTable(id="remotes-table")
            with Horizontal(id="remotes-buttons"):
                yield Button("Add", variant="primary", id="btn-add")
                yield Button("Edit", id="btn-edit")
                yield Button("Test", variant="warning", id="btn-test")
                yield Button("Delete", variant="error", id="btn-delete")
                yield Button("Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#remotes-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Type", "Host/Path")
        remotes = list_conf_dir("remotes.d")
        for name in remotes:
            data = parse_conf(CONFIG_DIR / "remotes.d" / f"{name}.conf")
            rtype = data.get("REMOTE_TYPE", "ssh")
            if rtype == "ssh":
                loc = f"{data.get('REMOTE_USER', 'root')}@{data.get('REMOTE_HOST', '')}:{data.get('REMOTE_BASE', '')}"
            elif rtype == "local":
                loc = data.get("REMOTE_BASE", "")
            elif rtype == "s3":
                loc = f"s3://{data.get('S3_BUCKET', '')}{data.get('REMOTE_BASE', '')}"
            else:
                loc = data.get("REMOTE_BASE", "")
            table.add_row(name, rtype, loc, key=name)

    def _selected_remote(self) -> str | None:
        table = self.query_one("#remotes-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-add":
            self.app.push_screen("remote_edit", callback=lambda _: self._refresh_table())
        elif event.button.id == "btn-edit":
            name = self._selected_remote()
            if name:
                from tui.screens.remote_edit import RemoteEditScreen
                self.app.push_screen(RemoteEditScreen(name), callback=lambda _: self._refresh_table())
            else:
                self.notify("Select a remote first", severity="warning")
        elif event.button.id == "btn-test":
            name = self._selected_remote()
            if name:
                self._test_remote(name)
            else:
                self.notify("Select a remote first", severity="warning")
        elif event.button.id == "btn-delete":
            name = self._selected_remote()
            if name:
                self.app.push_screen(
                    ConfirmDialog(f"Delete remote '{name}'? This cannot be undone.", "Delete Remote"),
                    callback=lambda ok: self._delete_remote(name) if ok else None,
                )
            else:
                self.notify("Select a remote first", severity="warning")

    @work
    async def _test_remote(self, name: str) -> None:
        log_screen = OperationLog(f"Testing Remote: {name}")
        self.app.push_screen(log_screen)
        await log_screen.wait_ready()
        rc, stdout, stderr = await run_cli("remotes", "test", f"--name={name}")
        if stdout:
            log_screen.write(stdout)
        if stderr:
            log_screen.write(stderr)
        if rc == 0:
            log_screen.write("\n[green]Connection test passed.[/green]")
        else:
            log_screen.write(f"\n[red]Connection test failed (exit code {rc}).[/red]")
        log_screen.finish()

    def _delete_remote(self, name: str) -> None:
        conf = CONFIG_DIR / "remotes.d" / f"{name}.conf"
        if conf.is_file():
            conf.unlink()
            self.notify(f"Remote '{name}' deleted.")
        self._refresh_table()

    def action_go_back(self) -> None:
        self.app.pop_screen()
