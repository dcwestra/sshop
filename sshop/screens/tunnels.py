from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Vertical

from sshop import engine
from sshop.config import Tunnel, load_tunnels, tunnel_running
from sshop.markup import cell, m, plain
from sshop.worker import run_blocking
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
        table = self.query_one("#tunnel-table", DataTable)
        table.add_columns("NAME", "STATUS", "ALIAS", "TYPE", "FORWARD SPEC")
        self._load()
        # live status: notice tunnels starting/stopping outside this screen
        self.set_interval(3.0, self._check_changes)

    def _state(self) -> tuple:
        return tuple((t.name, tunnel_running(t.name)) for t in load_tunnels())

    def _check_changes(self) -> None:
        state = self._state()
        if state != getattr(self, "_last_state", None):
            self._load()

    def _load(self) -> None:
        cur = self._focused_tunnel()
        cur_name = cur.name if cur else None
        self._tunnels = load_tunnels()
        self._last_state = tuple((t.name, tunnel_running(t.name)) for t in self._tunnels)
        table = self.query_one("#tunnel-table", DataTable)
        table.clear()
        for t in self._tunnels:
            color = _TYPE_COLOR.get(t.tunnel_type, "#c0caf5")
            status = ("[#9ece6a]● running[/#9ece6a]" if tunnel_running(t.name)
                      else "[dim]○ stopped[/dim]")
            table.add_row(
                cell(t.name, "bold"),
                status,
                cell(t.alias, "#7dcfff"),
                cell(t.tunnel_type, color),
                cell(t.forward_spec),
                key=t.name,
            )
        if cur_name:
            for i, t in enumerate(self._tunnels):
                if t.name == cur_name:
                    table.move_cursor(row=i)
                    break

    def _focused_tunnel(self) -> Tunnel | None:
        table = self.query_one("#tunnel-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._tunnels):
            return self._tunnels[idx]
        return None

    def _after(self, result: tuple[int, str], fallback: str) -> None:
        code, msg = result
        self.notify(plain(msg).strip() or fallback,
                    severity="information" if code == 0 else "error", markup=False)
        self._load()

    def action_start(self) -> None:
        t = self._focused_tunnel()
        if t:
            name = t.name
            self.notify(f"Starting {name}…", markup=False)
            run_blocking(self, lambda: engine.tunnel_start(name),
                         lambda res: self._after(res, f"Started {name}"))

    def action_stop(self) -> None:
        t = self._focused_tunnel()
        if t:
            name = t.name
            run_blocking(self, lambda: engine.tunnel_stop(name),
                         lambda res: self._after(res, f"Stopped {name}"))

    def action_add(self) -> None:
        with self.app.suspend():
            engine.tunnel_add()
        self._load()

    def action_delete(self) -> None:
        t = self._focused_tunnel()
        if not t:
            return
        from sshop.modals import ConfirmModal
        name = t.name
        self.app.push_screen(
            ConfirmModal(m("Remove tunnel [bold]$n[/bold]?\n[dim]Stops it first if running[/dim]",
                           n=name),
                         confirm_label="Remove"),
            callback=lambda ok: run_blocking(
                self, lambda: engine.tunnel_remove(name),
                lambda res: self._after(res, f"Removed {name}"),
            ) if ok else None,
        )

    def action_refresh(self) -> None:
        self._load()
