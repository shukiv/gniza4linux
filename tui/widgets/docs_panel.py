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

    def on_mount(self) -> None:
        self.app.call_later(self._apply_layout)

    def on_resize(self) -> None:
        self._apply_layout()

    def _apply_layout(self) -> None:
        width = self.app.size.width
        try:
            container = self.screen.query_one(".screen-with-docs")
        except Exception:
            return
        if width < 80:
            container.styles.layout = "vertical"
            self.styles.width = "100%"
            self.styles.min_width = None
            self.styles.max_height = "40%"
        else:
            container.styles.layout = "horizontal"
            self.styles.width = "30%"
            self.styles.min_width = 30
            self.styles.max_height = None

    @classmethod
    def for_screen(cls, screen_id: str) -> "DocsPanel":
        text = SCREEN_DOCS.get(screen_id, "No documentation available for this screen.")
        return cls(content=text)
