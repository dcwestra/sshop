from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Vertical

from sshop import engine
from sshop.config import load_aliases
from sshop.markup import cell, m, plain
from sshop.worker import run_blocking
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
        table = self.query_one("#agent-table", DataTable)
        table.add_columns("ALIAS", "STATUS")
        self._load()

    def _load(self) -> None:
        """Alias list from disk now; `okssh agent list` in a worker (it runs
        ssh-add — never on the UI thread)."""
        self._aliases = [a.name for a in load_aliases()]
        self._redraw(None)
        run_blocking(self, engine.agent_list, lambda res: self._redraw(res[1]))

    def _redraw(self, raw: str | None) -> None:
        loaded = engine.parse_agent_list(raw, self._aliases) if raw is not None else set()
        table = self.query_one("#agent-table", DataTable)
        cur = table.cursor_row
        table.clear()
        for alias in self._aliases:
            if raw is None:
                status = "[dim]…[/dim]"
            elif alias in loaded:
                status = "[#9ece6a]● loaded[/#9ece6a]"
            else:
                status = "[dim]○ not loaded[/dim]"
            table.add_row(cell(alias, "bold"), status, key=alias)
        if 0 <= cur < len(self._aliases):
            table.move_cursor(row=cur)

    def _focused_alias(self) -> str | None:
        table = self.query_one("#agent-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._aliases):
            return self._aliases[idx]
        return None

    def _after(self, result: tuple[int, str], fallback: str) -> None:
        code, msg = result
        self.notify(plain(msg).strip() or fallback,
                    severity="information" if code == 0 else "error", markup=False)
        self._load()

    def action_add_key(self) -> None:
        alias = self._focused_alias()
        if alias:
            run_blocking(self, lambda: engine.agent_add(alias),
                         lambda res: self._after(res, f"Added {alias} key to agent"))

    def action_remove_key(self) -> None:
        alias = self._focused_alias()
        if alias:
            run_blocking(self, lambda: engine.agent_rm(alias),
                         lambda res: self._after(res, f"Removed {alias} key from agent"))

    def action_clear(self) -> None:
        from sshop.modals import ConfirmModal
        self.app.push_screen(
            ConfirmModal(m("Remove [bold]all[/bold] keys from ssh-agent?"), confirm_label="Clear"),
            callback=lambda ok: run_blocking(
                self, engine.agent_clear, lambda res: self._after(res, "Agent cleared"),
            ) if ok else None,
        )

    def action_refresh(self) -> None:
        self._load()
