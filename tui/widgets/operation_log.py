from __future__ import annotations
import asyncio
from pathlib import Path

from rich.spinner import Spinner as RichSpinner
from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import RichLog, Button, Static
from textual.containers import Vertical, Horizontal
from textual.timer import Timer


class SpinnerWidget(Static):
    """Animated spinner using Rich's Spinner renderable."""

    def __init__(self, style: str = "dots", **kwargs):
        super().__init__("", **kwargs)
        self._spinner = RichSpinner(style, text=" Running...")
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(1 / 12, self._tick)

    def _tick(self) -> None:
        self.update(self._spinner)

    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
        self.update("✅")


class OperationLog(ModalScreen[None]):

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str = "Operation Output", show_spinner: bool = True, job_id: str | None = None):
        super().__init__()
        self._title = title
        self._show_spinner = show_spinner
        self._job_id = job_id
        self._mounted_event = asyncio.Event()
        self._buffer: list[str] = []
        self._poll_timer: Timer | None = None
        self._file_pos: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="op-log"):
            yield Static(self._title, id="ol-title")
            yield RichLog(id="ol-log", wrap=True, highlight=True, markup=True)
            with Horizontal(id="ol-footer"):
                yield Button("Close", variant="primary", id="ol-close")
                if self._show_spinner:
                    yield SpinnerWidget("arrow3", id="ol-spinner")

    def on_mount(self) -> None:
        log = self.query_one("#ol-log", RichLog)
        if self._job_id:
            from tui.jobs import job_manager
            job = job_manager.get_job(self._job_id)
            if job:
                # Load existing content from log file
                if job._log_file and Path(job._log_file).is_file():
                    try:
                        content = Path(job._log_file).read_text()
                        self._file_pos = len(content.encode())
                        for line in content.splitlines():
                            self._write_to_log(log, line)
                    except OSError:
                        pass
                elif job.output:
                    for line in job.output:
                        self._write_to_log(log, line)
                if job.status != "running":
                    self.finish()
                else:
                    self._poll_timer = self.set_interval(0.3, self._poll_job)
        # Flush any buffered writes
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

    def finish(self) -> None:
        try:
            self.query_one("#ol-spinner", SpinnerWidget).stop()
        except Exception:
            pass

    def write(self, text: str) -> None:
        if not self._mounted_event.is_set():
            self._buffer.append(text)
            return
        try:
            log = self.query_one("#ol-log", RichLog)
            self._write_to_log(log, text)
        except Exception:
            self._buffer.append(text)

    def _poll_job(self) -> None:
        from tui.jobs import job_manager
        job = job_manager.get_job(self._job_id)
        if not job:
            return
        try:
            log = self.query_one("#ol-log", RichLog)
        except Exception:
            return
        # Read new content directly from log file
        if job._log_file and Path(job._log_file).is_file():
            try:
                with open(job._log_file, "r") as f:
                    f.seek(self._file_pos)
                    new_data = f.read()
                    if new_data:
                        self._file_pos += len(new_data.encode())
                        for line in new_data.splitlines():
                            self._write_to_log(log, line)
            except OSError:
                pass
        if job.status != "running":
            if job.return_code == 0:
                self._write_to_log(log, "\n[green]Operation completed successfully.[/green]")
            else:
                self._write_to_log(log, f"\n[red]Operation failed (exit code {job.return_code}).[/red]")
            self.finish()
            if self._poll_timer:
                self._poll_timer.stop()
