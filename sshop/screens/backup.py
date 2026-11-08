from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.widgets import Button, DataTable, Label, Static
from textual.containers import Grid, Vertical

from sshop import engine
from sshop.markup import cell, m, plain
from sshop.worker import run_blocking
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
        table = self.query_one("#backup-table", DataTable)
        table.add_columns("#", "BACKUP")
        self._load()

    def _load(self) -> None:
        # `okssh backup` in a worker — never block the UI on a subprocess
        run_blocking(self, engine.backup_list, lambda res: self._redraw(res[1]))

    def _redraw(self, raw: str) -> None:
        table = self.query_one("#backup-table", DataTable)
        table.clear()
        self._backups = []
        for n, name in engine.parse_backup_list(raw):
            self._backups.append(n)
            table.add_row(cell(n, "dim"), cell(name, "#7dcfff"), key=n)
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
        if not confirmed:
            return

        def _done(res: tuple[int, str]) -> None:
            self.notify(
                plain(res[1]).strip() or f"Restored backup #{n}",
                severity="information" if res[0] == 0 else "error",
                markup=False,
            )
            # restoring snapshots the current config first — the list changed
            self._load()

        run_blocking(self, lambda: engine.backup_restore(int(n)), _done)


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
            yield Label(m(
                "Restore backup [bold]#$n[/bold]?\n"
                "[dim]This will overwrite your current ~/.ssh/config[/dim]",
                n=self._backup_n,
            ))
            yield Button("Restore", variant="warning", id="btn-yes")
            yield Button("Cancel", variant="default", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def key_escape(self) -> None:
        self.dismiss(False)
