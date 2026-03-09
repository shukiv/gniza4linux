from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal

from tui.config import LOG_DIR
from tui.widgets import DocsPanel


class EmailLogScreen(Screen):

    BINDINGS = [("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(classes="screen-with-docs"):
            with Vertical(id="email-log-screen"):
                with Horizontal(id="title-bar"):
                    yield Button("\u2190 Back", id="btn-back", classes="back-btn")
                    yield Static("Email Log", id="screen-title")
                yield DataTable(id="email-log-table")
                with Horizontal(id="email-log-buttons"):
                    yield Button("Refresh", id="btn-refresh")
            yield DocsPanel.for_screen("email-log-screen")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _parse_email_log(self):
        log_file = Path(LOG_DIR) / "email.log"
        if not log_file.is_file():
            return []
        entries = []
        try:
            with open(log_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(" | ", 3)
                    if len(parts) == 4:
                        entries.append({
                            "date": parts[0],
                            "status": parts[1],
                            "recipients": parts[2],
                            "subject": parts[3],
                        })
        except OSError:
            pass
        entries.reverse()
        return entries

    def _refresh_table(self) -> None:
        table = self.query_one("#email-log-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Date", "Status", "Recipients", "Subject")
        table.cursor_type = "row"

        entries = self._parse_email_log()
        if not entries:
            self.notify("No email log entries", severity="information")
            return

        for entry in entries:
            table.add_row(
                entry["date"], entry["status"],
                entry["recipients"], entry["subject"],
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.app.pop_screen()
        elif event.button.id == "btn-refresh":
            self._refresh_table()
            self.notify("Email log refreshed")

    def action_go_back(self) -> None:
        self.app.pop_screen()
