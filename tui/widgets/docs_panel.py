from textual.containers import VerticalScroll
from textual.widgets import Static
from tui.docs import SCREEN_DOCS


class DocsPanel(VerticalScroll):
    DEFAULT_CSS = """
    DocsPanel {
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

    @classmethod
    def for_screen(cls, screen_id: str) -> "DocsPanel":
        text = SCREEN_DOCS.get(screen_id, "No documentation available for this screen.")
        return cls(content=text)
