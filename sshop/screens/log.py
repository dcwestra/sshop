from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static
from textual.containers import Vertical

from sshop.config import load_aliases, load_history, load_tunnels, load_snippets
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


def _exit_markup(code: str) -> str:
    if code == "0":
        return "[#9ece6a]0[/#9ece6a]"
    return f"[#e0af68]{code}[/#e0af68]"


class LogScreen(Screen):
    BINDINGS = [
        Binding("escape,q", "dismiss", "Back"),
        Binding("c", "clear_filter", "Clear filter", show=False),
    ]

    def __init__(self, alias_filter: str | None = None):
        super().__init__()
        self._filter = alias_filter

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="log-header")
        with Vertical(id="log-body"):
            yield Static(" [bold]Connection Log[/bold]", id="log-title")
            yield Input(placeholder="filter by alias…", id="log-filter")
            yield DataTable(id="log-table", cursor_type="row", zebra_stripes=True)
        yield KeyBar(rows=[[
            ("c", "clear filter"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        try:
            self.query_one("#log-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        table = self.query_one("#log-table", DataTable)
        table.add_columns("TIMESTAMP", "ALIAS", "DURATION", "EXIT")
        if self._filter:
            self.query_one("#log-filter", Input).value = self._filter
        self._load(self._filter)

    def _load(self, alias_filter: str | None = None) -> None:
        entries = load_history(alias_filter or None)
        table = self.query_one("#log-table", DataTable)
        table.clear()
        for e in entries:
            table.add_row(
                f"[dim]{e['timestamp']}[/dim]",
                f"[bold #7dcfff]{e['alias']}[/bold #7dcfff]",
                e["duration"],
                _exit_markup(e["exit_code"]),
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        self._load(event.value.strip() or None)

    def action_clear_filter(self) -> None:
        self.query_one("#log-filter", Input).value = ""
