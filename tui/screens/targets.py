from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal
from textual.events import Click

from tui.config import list_conf_dir, parse_conf, CONFIG_DIR
from tui.widgets import ConfirmDialog, DocsPanel


class TargetsScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="targets-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("← Back", id="btn-back", classes="back-btn")
                    yield Static("Sources", id="screen-title")
                yield DataTable(id="targets-table")
                with Horizontal(id="targets-buttons"):
                    yield Button("Add", variant="primary", id="btn-add")
                    yield Button("Edit", id="btn-edit")
                    yield Button("Delete", variant="error", id="btn-delete")
            yield DocsPanel.for_screen("targets-screen")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#targets-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Folders", "Enabled")
        targets = list_conf_dir("targets.d")
        for name in targets:
            data = parse_conf(CONFIG_DIR / "targets.d" / f"{name}.conf")
            table.add_row(
                name,
                data.get("TARGET_FOLDERS", ""),
                data.get("TARGET_ENABLED", "yes"),
                key=name,
            )

    def _selected_target(self) -> str | None:
        table = self.query_one("#targets-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_key = table.get_row_at(table.cursor_row)
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            self.app.push_screen("target_edit", callback=lambda _: self._refresh_table())
        elif event.button.id == "btn-edit":
            name = self._selected_target()
            if name:
                from tui.screens.target_edit import TargetEditScreen
                self.app.push_screen(TargetEditScreen(name), callback=lambda _: self._refresh_table())
            else:
                self.notify("Select a source first", severity="warning")
        elif event.button.id == "btn-delete":
            name = self._selected_target()
            if name:
                self.app.push_screen(
                    ConfirmDialog(f"Delete source '{name}'? This cannot be undone.", "Delete Source"),
                    callback=lambda ok: self._delete_target(name) if ok else None,
                )
            else:
                self.notify("Select a source first", severity="warning")

    def _delete_target(self, name: str) -> None:
        conf = CONFIG_DIR / "targets.d" / f"{name}.conf"
        if conf.is_file():
            conf.unlink()
            self.notify(f"Source '{name}' deleted.")
        self._refresh_table()

    def on_click(self, event: Click) -> None:
        if event.widget.id == "btn-back":
            self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
