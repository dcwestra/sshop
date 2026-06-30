from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Vertical

from sshop import engine
from sshop.config import Tunnel, load_aliases, load_tunnels, load_snippets
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar

_TYPE_COLOR = {
    "local":  "#7dcfff",
    "remote": "#bb9af7",
    "socks":  "#e0af68",
}


class TunnelsScreen(Screen):
    BINDINGS = [
        Binding("s", "start", "Start"),
        Binding("S", "stop", "Stop"),
        Binding("a", "add", "Add"),
        Binding("D", "delete", "Delete", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("escape,q", "dismiss", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self._tunnels: list[Tunnel] = []

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="tunnel-header")
        with Vertical(id="tunnel-body"):
            yield Static(" [bold]Tunnels[/bold]", id="tunnel-title")
            yield DataTable(id="tunnel-table", cursor_type="row", zebra_stripes=True)
        yield KeyBar(rows=[[
            ("s", "start"), ("S", "stop"), ("a", "add"),
            ("D", "delete"), ("r", "refresh"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        try:
            self.query_one("#tunnel-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        table = self.query_one("#tunnel-table", DataTable)
        table.add_columns("NAME", "ALIAS", "TYPE", "FORWARD SPEC", "AUTO")
        self._load()

    def _load(self) -> None:
        self._tunnels = load_tunnels()
        table = self.query_one("#tunnel-table", DataTable)
        table.clear()
        for t in self._tunnels:
            color = _TYPE_COLOR.get(t.tunnel_type, "#c0caf5")
            table.add_row(
                f"[bold]{t.name}[/bold]",
                f"[#7dcfff]{t.alias}[/#7dcfff]",
                f"[{color}]{t.tunnel_type}[/{color}]",
                t.forward_spec,
                "[#9ece6a]✓[/#9ece6a]" if t.auto_start == "1" else "[dim]—[/dim]",
                key=t.name,
            )

    def _focused_tunnel(self) -> Tunnel | None:
        table = self.query_one("#tunnel-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._tunnels):
            return self._tunnels[idx]
        return None

    def action_start(self) -> None:
        t = self._focused_tunnel()
        if t:
            code, msg = engine.tunnel_start(t.name)
            self.notify(msg.strip() or f"Started {t.name}",
                        severity="information" if code == 0 else "error")

    def action_stop(self) -> None:
        t = self._focused_tunnel()
        if t:
            code, msg = engine.tunnel_stop(t.name)
            self.notify(msg.strip() or f"Stopped {t.name}",
                        severity="information" if code == 0 else "error")

    def action_add(self) -> None:
        with self.app.suspend():
            engine.tunnel_add()
        self._load()

    def action_delete(self) -> None:
        t = self._focused_tunnel()
        if t:
            code, msg = engine.tunnel_remove(t.name)
            if code == 0:
                self.notify(f"Removed {t.name}")
                self._load()
            else:
                self.notify(f"Error: {msg}", severity="error")

    def action_refresh(self) -> None:
        self._load()
