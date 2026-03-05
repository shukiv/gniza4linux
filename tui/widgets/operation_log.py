import asyncio

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import RichLog, Button, Static
from textual.containers import Vertical


class OperationLog(ModalScreen[None]):

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str = "Operation Output"):
        super().__init__()
        self._title = title
        self._mounted_event = asyncio.Event()
        self._buffer: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="op-log"):
            yield Static(self._title, id="ol-title")
            yield RichLog(id="ol-log", wrap=True, highlight=True, markup=True)
            yield Button("Close", variant="primary", id="ol-close")

    def on_mount(self) -> None:
        # Flush any buffered writes
        log = self.query_one("#ol-log", RichLog)
        for text in self._buffer:
            self._write_to_log(log, text)
        self._buffer.clear()
        self._mounted_event.set()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def _write_to_log(self, log: RichLog, text: str) -> None:
        if "[" in text and "[/" in text:
            log.write(Text.from_markup(text))
        else:
            log.write(text)

    def write(self, text: str) -> None:
        if not self._mounted_event.is_set():
            self._buffer.append(text)
            return
        try:
            log = self.query_one("#ol-log", RichLog)
            self._write_to_log(log, text)
        except Exception:
            self._buffer.append(text)
