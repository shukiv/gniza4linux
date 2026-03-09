from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Button
from tui.docs import SCREEN_DOCS


class HelpModal(ModalScreen[None]):

    BINDINGS = [("escape", "close", "Close"), ("f1", "close", "Close")]

    def __init__(self, content: str):
        super().__init__()
        self._content = content

    def compose(self):
        with VerticalScroll(id="help-modal"):
            yield Static("[bold underline]Help[/]", id="docs-title")
            yield Static(self._content, id="docs-body")
            yield Button("Close", id="help-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class DocsPanel(VerticalScroll):
    DEFAULT_CSS = """
    DocsPanel {
        display: none;
        width: 30%;
        min-width: 30;
        border-left: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, content: str, **kwargs):
        super().__init__(id="docs-panel", **kwargs)
        self._content = content

    def compose(self):
        yield Static("[bold underline]Help[/]", id="docs-title")
        yield Static(self._content, id="docs-body")

    def on_mount(self) -> None:
        # Delay check — at mount time the terminal may not have reported
        # its real size yet (especially in web/mobile via textual-serve).
        self.set_timer(0.3, self._check_show)
        self.set_timer(0.8, self._check_show)

    def on_resize(self) -> None:
        self._check_show()

    def _check_show(self) -> None:
        self.display = self.app.size.width >= 90

    @classmethod
    def for_screen(cls, screen_id: str) -> "DocsPanel":
        text = SCREEN_DOCS.get(screen_id, "No documentation available for this screen.")
        return cls(content=text)
