from __future__ import annotations

import re
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Vertical

from sshop import engine
from sshop.config import load_aliases, load_tunnels, load_snippets
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


class BackupScreen(Screen):
    BINDINGS = [
        Binding("enter,r", "restore", "Restore"),
        Binding("escape,q", "dismiss", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self._backups: list[str] = []

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="backup-header")
        with Vertical(id="backup-body"):
            yield Static(" [bold]Backups[/bold]", id="backup-title")
            yield DataTable(id="backup-table", cursor_type="row", zebra_stripes=True)
        yield KeyBar(rows=[[
            ("↵", "restore"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        try:
            self.query_one("#backup-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        table = self.query_one("#backup-table", DataTable)
        table.add_columns("#", "BACKUP")
        self._load()

    def _load(self) -> None:
        _, raw = engine.backup_list()
        table = self.query_one("#backup-table", DataTable)
        table.clear()
        self._backups = []

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(\d+)\)\s+(.+)", line)
            if m:
                n, name = m.group(1), m.group(2)
                self._backups.append(n)
                table.add_row(
                    f"[dim]{n}[/dim]",
                    f"[#7dcfff]{name}[/#7dcfff]",
                    key=n,
                )

        if not self._backups:
            table.add_row("—", "[dim]No backups found[/dim]")

    def _focused_n(self) -> str | None:
        table = self.query_one("#backup-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._backups):
            return self._backups[idx]
        return None

    def action_restore(self) -> None:
        n = self._focused_n()
        if n:
            code, msg = engine.backup_restore(int(n))
            self.notify(
                msg.strip() or f"Restored backup #{n}",
                severity="information" if code == 0 else "error",
            )
