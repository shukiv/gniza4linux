import json

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal
from textual.work import work

from tui.backend import run_cli
from tui.config import list_conf_dir
from tui.widgets import DocsPanel


class HealthScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="health-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("\u2190 Back", id="btn-back", classes="back-btn")
                    yield Static("Health Check", id="screen-title")
                yield DataTable(id="health-table")
                with Horizontal(id="health-buttons"):
                    yield Button("Check", variant="primary", id="btn-check")
                    yield Button("Refresh", id="btn-refresh")
                yield Static("", id="health-result")
            yield DocsPanel.for_screen("health-screen")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#health-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Destination")
        table.cursor_type = "row"

        remotes = list_conf_dir("remotes.d")
        if not remotes:
            self.notify("No destinations configured", severity="warning")
            return

        for name in remotes:
            table.add_row(name, key=name)

    def _selected_name(self) -> str | None:
        table = self.query_one("#health-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-check":
            name = self._selected_name()
            if name:
                self._run_check(name)
            else:
                self.notify("Select a destination first", severity="warning")
        elif event.button.id == "btn-refresh":
            self._refresh_table()
            self.query_one("#health-result", Static).update("")
            self.notify("Destination list refreshed")

    @work(exclusive=True)
    async def _run_check(self, name: str) -> None:
        result_widget = self.query_one("#health-result", Static)
        result_widget.update(f"Checking {name}...")

        try:
            rc, stdout, stderr = await run_cli(
                "health", f"--destination={name}", "--json",
            )
            if rc == 0 and stdout.strip():
                data = json.loads(stdout.strip())
                lines = []
                lines.append(f"Destination: {name}")
                lines.append(f"Status: {data.get('status', 'unknown')}")
                if "connectivity" in data:
                    lines.append(f"Connectivity: {data['connectivity']}")
                if "disk_usage" in data:
                    lines.append(f"Disk Usage: {data['disk_usage']}")
                if "disk_total" in data:
                    lines.append(f"Disk Total: {data['disk_total']}")
                if "disk_free" in data:
                    lines.append(f"Disk Free: {data['disk_free']}")
                if "snapshot_count" in data:
                    lines.append(f"Snapshots: {data['snapshot_count']}")
                if "errors" in data and data["errors"]:
                    lines.append(f"Errors: {', '.join(data['errors'])}")
                result_widget.update("\n".join(lines))
            else:
                result_widget.update(f"Health check failed: {stderr.strip() or 'unknown error'}")
        except json.JSONDecodeError:
            result_widget.update("Invalid response from health check")
        except Exception as e:
            result_widget.update(f"Error: {e}")

    def action_go_back(self) -> None:
        self.app.pop_screen()
