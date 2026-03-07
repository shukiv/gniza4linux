from datetime import datetime

from rich.text import Text
from textual.reactive import Reactive
from textual.widgets import Header, Static
from textual.widgets._header import HeaderIcon, HeaderTitle, HeaderClock, HeaderClockSpace

from tui.jobs import job_manager


class HeaderTaskClock(HeaderClock):
    """Clock widget that also shows running task count."""

    DEFAULT_CSS = """
    HeaderTaskClock {
        background: $foreground-darken-1 5%;
        color: $foreground;
        text-opacity: 85%;
        content-align: center middle;
        dock: right;
        width: auto;
        min-width: 10;
        padding: 0 1;
    }
    """

    time_format: Reactive[str] = Reactive("%X")

    def render(self):
        clock = datetime.now().time().strftime(self.time_format)
        running = job_manager.running_count()
        queued = sum(1 for j in job_manager.list_jobs() if j.status == "queued")
        if running > 0 or queued > 0:
            parts: list[tuple[str, str] | str] = [("Tasks ", "bold")]
            if running > 0:
                parts.append((f"({running})", "bold yellow"))
            if queued > 0:
                if running > 0:
                    parts.append(" ")
                parts.append((f"+{queued} queued", "bold dim"))
            parts.append("  ")
            parts.append(clock)
            return Text.assemble(*parts)
        return Text(clock)


class GnizaHeader(Header):

    def compose(self):
        yield HeaderIcon().data_bind(Header.icon)
        yield HeaderTitle()
        yield (
            HeaderTaskClock().data_bind(Header.time_format)
            if self._show_clock
            else HeaderClockSpace()
        )
