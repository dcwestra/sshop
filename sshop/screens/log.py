from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static
from textual.containers import Vertical

from sshop.config import load_history
from sshop.markup import cell
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


def _exit_markup(code: str):
    return cell(code, "#9ece6a" if code == "0" else "#e0af68")


def _duration_str(raw: str) -> str:
    """history.log stores duration as raw seconds."""
    try:
        secs = int(raw)
    except ValueError:
        return raw
    if secs >= 3600:
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    if secs >= 60:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs}s"


class LogScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "dismiss", "Back", show=False),
        Binding("c", "clear_filter", "Clear filter", show=False),
        Binding("/", "focus_filter", "Filter", show=False),
    ]

    def __init__(self, alias_filter: str | None = None):
        super().__init__()
        self._filter = alias_filter
        self._entries: list[dict[str, str]] = []

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="log-header")
        with Vertical(id="log-body"):
            yield Static(" [bold]Connection Log[/bold]", id="log-title")
            yield Input(placeholder="filter by alias… (/ to focus, Esc to leave)", id="log-filter")
            yield DataTable(id="log-table", cursor_type="row", zebra_stripes=True)
        yield KeyBar(rows=[[
            ("/", "filter"), ("c", "clear filter"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        table = self.query_one("#log-table", DataTable)
        table.add_columns("TIMESTAMP", "ALIAS", "DURATION", "EXIT")
        # read once; filtering is in memory (the log grows without bound)
        self._entries = load_history()
        if self._filter:
            self.query_one("#log-filter", Input).value = self._filter
        self._redraw(self._filter)
        # the filter Input is first in the DOM and would otherwise take focus,
        # swallowing q / c as filter text
        table.focus()

    def _redraw(self, alias_filter: str | None = None) -> None:
        needle = (alias_filter or "").lower()
        table = self.query_one("#log-table", DataTable)
        table.clear()
        for e in self._entries:
            if needle and needle not in e["alias"].lower():
                continue
            table.add_row(
                cell(e["timestamp"], "dim"),
                cell(e["alias"], "bold #7dcfff"),
                _duration_str(e["duration"]),
                _exit_markup(e["exit_code"]),
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        self._redraw(event.value.strip() or None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.query_one("#log-table", DataTable).focus()

    def action_focus_filter(self) -> None:
        self.query_one("#log-filter", Input).focus()

    def action_back(self) -> None:
        # Esc in the filter returns to the table; Esc on the table leaves
        if isinstance(self.focused, Input):
            self.query_one("#log-table", DataTable).focus()
        else:
            self.dismiss()

    def action_clear_filter(self) -> None:
        self.query_one("#log-filter", Input).value = ""
