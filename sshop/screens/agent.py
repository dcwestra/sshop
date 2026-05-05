from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Vertical

from sshop import engine
from sshop.config import load_aliases, load_tunnels, load_snippets
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


class AgentScreen(Screen):
    BINDINGS = [
        Binding("a", "add_key", "Add key"),
        Binding("D", "remove_key", "Remove", show=False),
        Binding("c", "clear", "Clear all", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("escape,q", "dismiss", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self._aliases: list[str] = []

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="agent-header")
        with Vertical(id="agent-body"):
            yield Static(" [bold]SSH Agent[/bold]", id="agent-title")
            yield DataTable(id="agent-table", cursor_type="row", zebra_stripes=True)
        yield KeyBar(rows=[[
            ("a", "add key"), ("D", "remove"), ("c", "clear all"),
            ("r", "refresh"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        try:
            self.query_one("#agent-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        table = self.query_one("#agent-table", DataTable)
        table.add_columns("ALIAS", "STATUS")
        self._load()

    def _load(self) -> None:
        self._aliases = [a.name for a in load_aliases()]
        _, raw = engine.agent_list()

        loaded: set[str] = set()
        for alias in self._aliases:
            if alias in raw:
                loaded.add(alias)

        table = self.query_one("#agent-table", DataTable)
        table.clear()
        for alias in self._aliases:
            status = "[#9ece6a]● loaded[/#9ece6a]" if alias in loaded else "[dim]○ not loaded[/dim]"
            table.add_row(f"[bold]{alias}[/bold]", status, key=alias)

    def _focused_alias(self) -> str | None:
        table = self.query_one("#agent-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._aliases):
            return self._aliases[idx]
        return None

    def action_add_key(self) -> None:
        alias = self._focused_alias()
        if alias:
            code, msg = engine.agent_add(alias)
            self.notify(msg.strip() or f"Added {alias} key to agent",
                        severity="information" if code == 0 else "error")
            self._load()

    def action_remove_key(self) -> None:
        alias = self._focused_alias()
        if alias:
            code, msg = engine.agent_rm(alias)
            self.notify(msg.strip() or f"Removed {alias} key from agent",
                        severity="information" if code == 0 else "error")
            self._load()

    def action_clear(self) -> None:
        code, msg = engine.agent_clear()
        self.notify(msg.strip() or "Agent cleared",
                    severity="information" if code == 0 else "error")
        self._load()

    def action_refresh(self) -> None:
        self._load()
