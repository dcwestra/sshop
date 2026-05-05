from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


def _kb(key: str, desc: str) -> str:
    return f"[bold #7aa2f7 on #2a2b3d] {key} [/] [#565f89]{desc}[/]"


_ROW1 = [
    ("a", "add"), ("t", "tunnels"), ("s", "snippets"), ("l", "log"),
    ("G", "ssh agent"), ("b", "backup"), ("m", "templates"), ("u", "key audit"),
    ("?", "help"), ("q", "quit"),
]


class KeyBar(Widget):
    DEFAULT_CSS = """
    KeyBar {
        height: auto;
        background: #13141f;
        border-top: solid #2a2b3d;
        padding: 0 1;
        layout: vertical;
    }
    KeyBar Static {
        height: 1;
        background: #13141f;
        color: #c0caf5;
    }
    """

    def __init__(
        self,
        rows: list[list[tuple[str, str]]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._rows = rows if rows is not None else [_ROW1]

    def compose(self) -> ComposeResult:
        for row in self._rows:
            yield Static("  ".join(_kb(k, d) for k, d in row))
