from __future__ import annotations

import re
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.widgets import Button, DataTable, Label, Static
from textual.containers import Grid, Vertical

from sshop import engine
from sshop.config import load_aliases, load_tunnels, load_snippets
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


class BackupScreen(Screen):
    BINDINGS = [
        Binding("r", "restore", "Restore"),
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_restore()

    def action_restore(self) -> None:
        n = self._focused_n()
        if n:
            self.app.push_screen(
                ConfirmRestore(n),
                callback=lambda confirmed: self._on_restore_confirmed(confirmed, n),
            )

    def _on_restore_confirmed(self, confirmed: bool, n: str) -> None:
        if confirmed:
            code, msg = engine.backup_restore(int(n))
            self.notify(
                msg.strip() or f"Restored backup #{n}",
                severity="information" if code == 0 else "error",
            )


class ConfirmRestore(ModalScreen[bool]):

    DEFAULT_CSS = """
    ConfirmRestore {
        align: center middle;
    }
    ConfirmRestore > Grid {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 1 2;
        width: 54;
        height: 10;
        border: solid $warning;
        background: $surface;
    }
    ConfirmRestore Label {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }
    ConfirmRestore Button { width: 100%; }
    """

    def __init__(self, backup_n: str):
        super().__init__()
        self._backup_n = backup_n

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label(
                f"Restore backup [bold]#{self._backup_n}[/bold]?\n"
                f"[dim]This will overwrite your current ~/.ssh/config[/dim]"
            )
            yield Button("Restore", variant="warning", id="btn-yes")
            yield Button("Cancel", variant="default", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")
