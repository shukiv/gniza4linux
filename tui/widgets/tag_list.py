"""Tag list widget — displays items as removable tags with an add input."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Static


class TagList(Widget):
    """A list of tags with add/remove functionality."""

    class Changed(Message):
        """Posted when the tag list changes."""
        def __init__(self, tag_list: "TagList") -> None:
            super().__init__()
            self.tag_list = tag_list

    DEFAULT_CSS = """
    TagList {
        height: auto;
        layout: vertical;
    }
    TagList .tag-items {
        height: auto;
        layout: vertical;
    }
    TagList .tag-row {
        height: 1;
        layout: horizontal;
    }
    TagList .tag-item {
        height: 1;
        width: 1fr;
        background: $primary-background;
        color: $text;
        padding: 0 1;
    }
    TagList .tag-remove {
        min-width: 3;
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
        color: $error;
        border: none;
    }
    TagList .tag-input-row {
        height: 3;
    }
    TagList .tag-input-row Input {
        width: 1fr;
    }
    TagList .tag-btn-row {
        height: 3;
        layout: horizontal;
    }
    TagList .tag-btn-row Button {
        min-width: 10;
        margin: 0 1 0 0;
    }
    """

    def __init__(
        self,
        items: list[str] | None = None,
        placeholder: str = "/path/to/folder",
        widget_id: str | None = None,
        show_browse: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(id=widget_id, **kwargs)
        self._items: list[str] = list(items or [])
        self._placeholder = placeholder
        self._show_browse = show_browse

    def compose(self) -> ComposeResult:
        with Vertical(classes="tag-items", id="tag-items-container"):
            for i, item in enumerate(self._items):
                with Horizontal(classes="tag-row"):
                    yield Button("✕", classes="tag-remove", id=f"tag-rm-{i}")
                    yield Static(f"{item}", classes="tag-item", id=f"tag-{i}")
        yield Input(placeholder=self._placeholder, id="tag-input", classes="tag-input-row")
        with Horizontal(classes="tag-btn-row"):
            yield Button("Add", id="tag-add-btn", variant="default")
            if self._show_browse:
                yield Button("Browse...", id="btn-browse", variant="default")

    @property
    def items(self) -> list[str]:
        return list(self._items)

    @property
    def value(self) -> str:
        """Return comma-separated string of all items."""
        return ",".join(self._items)

    def add_item(self, item: str) -> None:
        item = item.strip()
        if item and item not in self._items:
            self._items.append(item)
            self._rebuild_tags()
            self.post_message(self.Changed(self))

    def remove_item(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._rebuild_tags()
            self.post_message(self.Changed(self))

    def _rebuild_tags(self) -> None:
        container = self.query_one("#tag-items-container")
        container.remove_children()
        for i, item in enumerate(self._items):
            row = Horizontal(classes="tag-row")
            container.mount(row)
            row.mount(Button("✕", classes="tag-remove", id=f"tag-rm-{i}"))
            row.mount(Static(f"{item}", classes="tag-item", id=f"tag-{i}"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tag-add-btn":
            inp = self.query_one("#tag-input", Input)
            self.add_item(inp.value)
            inp.value = ""
            event.stop()
        elif event.button.id and event.button.id.startswith("tag-rm-"):
            idx = int(event.button.id.split("-")[-1])
            self.remove_item(idx)
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tag-input":
            self.add_item(event.value)
            event.input.value = ""
            event.stop()
