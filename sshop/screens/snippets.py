from __future__ import annotations

import subprocess
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, SelectionList, Static
from textual.containers import Horizontal, Vertical

from sshop import engine
from sshop.config import Snippet, load_aliases, load_snippets, load_tunnels
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar

OKSSH_BIN = engine.OKSSH_BIN


class _RunOnModal(ModalScreen[list[str] | None]):
    """Pick one or more aliases to run a snippet on. Multiple = parallel."""

    BINDINGS = [
        Binding("enter", "confirm", "Run"),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    _RunOnModal {
        align: center middle;
    }
    _RunOnModal > Vertical {
        width: 60;
        height: auto;
        max-height: 80vh;
        padding: 1 2;
        border: solid #7aa2f7;
        background: $surface;
    }
    _RunOnModal #modal-title {
        margin-bottom: 1;
    }
    _RunOnModal SelectionList {
        height: auto;
        max-height: 20;
        border: none;
    }
    _RunOnModal #btn-row {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }
    _RunOnModal Button {
        margin-left: 1;
        min-width: 10;
    }
    """

    def __init__(self, snippet_name: str, aliases: list[str]):
        super().__init__()
        self._snippet_name = snippet_name
        self._aliases = aliases

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"[bold #ff9e64]Run:[/bold #ff9e64]  [bold]{self._snippet_name}[/bold]\n"
                f"[dim]Select target host(s) — multiple = parallel[/dim]",
                id="modal-title",
            )
            yield SelectionList(
                *[(a, a, False) for a in self._aliases],
                id="alias-list",
            )
            with Horizontal(id="btn-row"):
                yield Button("Run", variant="primary", id="btn-run")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#alias-list", SelectionList).focus()

    def action_confirm(self) -> None:
        selected = list(self.query_one("#alias-list", SelectionList).selected)
        self.dismiss(selected if selected else None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            self.action_confirm()
        else:
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


class SnippetsScreen(Screen):
    BINDINGS = [
        Binding("r", "run_snippet", "Run"),
        Binding("g", "run_group", "Run on group", show=False),
        Binding("e", "edit_snippet", "Edit", show=False),
        Binding("a", "add", "Add"),
        Binding("D", "delete", "Delete", show=False),
        Binding("escape,q", "dismiss", "Back"),
    ]

    def __init__(self, focused_alias: str | None = None):
        super().__init__()
        self._snippets: list[Snippet] = []
        self._focused_alias = focused_alias

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="snip-header")
        with Horizontal(id="snip-body"):
            with Vertical(id="snip-list-pane"):
                yield Static(" [bold]Snippets[/bold]", id="snip-title")
                yield DataTable(id="snip-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="snip-detail-pane"):
                yield Static("", id="snip-detail")
        yield KeyBar(rows=[[
            ("r", "run"), ("g", "run group"),
            ("e", "edit"), ("a", "add"), ("D", "delete"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        alias_label = self._focused_alias or "(none)"
        try:
            self.query_one("#snip-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        self.query_one("#snip-title", Static).update(
            f" [bold]Snippets[/bold]"
            f"  [dim]alias:[/dim] [#7dcfff]{alias_label}[/#7dcfff]"
        )
        table = self.query_one("#snip-table", DataTable)
        table.add_columns("NAME", "GROUP", "DESCRIPTION")
        self._load()

    def _load(self) -> None:
        self._snippets = load_snippets()
        table = self.query_one("#snip-table", DataTable)
        table.clear()
        for s in self._snippets:
            table.add_row(
                f"[bold]{s.name}[/bold]",
                f"[#7dcfff]{s.group}[/#7dcfff]" if s.group else "[dim]—[/dim]",
                s.description or "[dim]—[/dim]",
                key=s.name,
            )
        self._update_detail()

    def _focused_snippet(self) -> Snippet | None:
        table = self.query_one("#snip-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._snippets):
            return self._snippets[idx]
        return None

    def _update_detail(self) -> None:
        s = self._focused_snippet()
        detail = self.query_one("#snip-detail", Static)
        if not s:
            detail.update("")
            return
        rule = "[#2a2b3d]" + "─" * 26 + "[/#2a2b3d]"
        sudo_note = "  [#e0af68]requires sudo[/#e0af68]\n" if s.use_sudo == "1" else ""
        detail.update(
            f"[bold #ff9e64]{s.name}[/bold #ff9e64]\n\n"
            f"  [dim]group[/dim]  {f'[#7dcfff]{s.group}[/#7dcfff]' if s.group else '[dim]—[/dim]'}\n"
            f"  [dim] desc[/dim]  {s.description or '[dim]—[/dim]'}\n"
            f"{sudo_note}\n"
            f"{rule}\n"
            f"[#9ece6a]{s.command}[/#9ece6a]\n"
        )

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def action_run_snippet(self) -> None:
        s = self._focused_snippet()
        if not s:
            return
        aliases = [a.name for a in load_aliases()]
        self.app.push_screen(
            _RunOnModal(s.name, aliases),
            callback=lambda targets: self._on_run_targets(s.name, targets),
        )

    def _on_run_targets(self, snip_name: str, targets: list[str] | None) -> None:
        if not targets:
            return
        cmd = [OKSSH_BIN, "snip", "run", snip_name] + targets
        if len(targets) > 1:
            cmd.append("--parallel")
        with self.app.suspend():
            subprocess.run(cmd)

    def action_edit_snippet(self) -> None:
        s = self._focused_snippet()
        if s:
            with self.app.suspend():
                subprocess.run([OKSSH_BIN, "snip", "edit", s.name])
            self._load()

    def action_run_group(self) -> None:
        s = self._focused_snippet()
        if not s:
            return
        from sshop.modals import _InputModal
        self.app.push_screen(
            _InputModal(
                title=f"Run '{s.name}' on group",
                label="Group name",
                placeholder="e.g. homelab",
            ),
            callback=lambda grp: self._on_run_group(s.name, grp),
        )

    def _on_run_group(self, snip_name: str, group: str | None) -> None:
        if group:
            with self.app.suspend():
                subprocess.run([OKSSH_BIN, "snip", "run", snip_name, "--group", group])

    def action_add(self) -> None:
        with self.app.suspend():
            subprocess.run([OKSSH_BIN, "snip", "add"])
        self._load()

    def action_delete(self) -> None:
        s = self._focused_snippet()
        if s:
            with self.app.suspend():
                subprocess.run([OKSSH_BIN, "snip", "rm", s.name])
            self._load()
