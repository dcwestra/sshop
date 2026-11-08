from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, SelectionList, Static
from textual.widgets.selection_list import Selection
from textual.containers import Horizontal, Vertical

from sshop import engine
from sshop.config import Snippet, load_aliases, load_bootstrapped_aliases, load_snippets
from sshop.markup import cell, m, plain
from sshop.worker import run_blocking
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


class _PickList(SelectionList):
    """SelectionList where Enter confirms the modal (Space still toggles).
    Plain SelectionList binds Enter to toggle, so a screen-level Enter
    binding never fired while the list had focus."""

    BINDINGS = [Binding("enter", "submit", "Confirm", show=False)]

    def action_submit(self) -> None:
        self.screen.action_confirm()

    def highlighted_value(self) -> str | None:
        if self.highlighted is None:
            return None
        return self.get_option_at_index(self.highlighted).value


_PICKER_CSS = """
{cls} {{
    align: center middle;
}}
{cls} > Vertical {{
    width: 60;
    height: auto;
    max-height: 80vh;
    padding: 1 2;
    border: solid {border};
    background: $surface;
}}
{cls} #modal-title {{
    margin-bottom: 1;
}}
{cls} SelectionList {{
    height: auto;
    max-height: 20;
    border: none;
}}
{cls} #btn-row {{
    height: 3;
    align-horizontal: right;
    margin-top: 1;
}}
{cls} Button {{
    margin-left: 1;
    min-width: 10;
}}
"""


def _selections(names: list[str], preselect: str | None = None) -> list[Selection]:
    # Content(...) so names render literally
    return [Selection(Content(n), n, n == preselect) for n in names]


class _RunOnModal(ModalScreen[list[str] | None]):
    """Pick one or more aliases to run a snippet on. Multiple = parallel.
    Enter runs on the ticked hosts — or on the highlighted one if none is
    ticked."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = _PICKER_CSS.format(cls="_RunOnModal", border="#7aa2f7")

    def __init__(self, snippet_name: str, aliases: list[str], preselect: str | None = None):
        super().__init__()
        self._snippet_name = snippet_name
        self._aliases = aliases
        self._preselect = preselect

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                m("[bold #ff9e64]Run:[/bold #ff9e64]  [bold]$s[/bold]\n"
                  "[dim]Space ticks hosts (several = parallel) · Enter runs[/dim]",
                  s=self._snippet_name),
                id="modal-title",
            )
            yield _PickList(*_selections(self._aliases, self._preselect), id="alias-list")
            with Horizontal(id="btn-row"):
                yield Button("Run", variant="primary", id="btn-run")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        lst = self.query_one("#alias-list", _PickList)
        lst.focus()
        if self._preselect in self._aliases:
            lst.highlighted = self._aliases.index(self._preselect)

    def action_confirm(self) -> None:
        lst = self.query_one("#alias-list", _PickList)
        selected = list(lst.selected)
        if not selected and lst.highlighted_value():
            selected = [lst.highlighted_value()]
        self.dismiss(selected or None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            self.action_confirm()
        else:
            self.dismiss(None)


class _PushToModal(ModalScreen[list[str] | None]):
    """Pick bootstrapped hosts to push the snippet list to. Enter / "Push
    selected" push to the ticked hosts, or to ALL of them if none is ticked."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = _PICKER_CSS.format(cls="_PushToModal", border="#9ece6a")

    def __init__(self, hosts: list[str]):
        super().__init__()
        self._hosts = hosts

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "[bold #9ece6a]Push snippets[/bold #9ece6a]\n"
                "[dim]Space ticks hosts · Enter pushes (none ticked = all)[/dim]",
                id="modal-title",
            )
            yield _PickList(*_selections(self._hosts), id="host-list")
            with Horizontal(id="btn-row"):
                yield Button("Push all", variant="success", id="btn-all")
                yield Button("Push selected", variant="primary", id="btn-push")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#host-list", _PickList).focus()

    def action_confirm(self) -> None:
        selected = list(self.query_one("#host-list", _PickList).selected)
        self.dismiss(selected or self._hosts)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-all":
            self.dismiss(self._hosts)
        elif event.button.id == "btn-push":
            self.action_confirm()
        else:
            self.dismiss(None)


class SnippetsScreen(Screen):
    BINDINGS = [
        Binding("r", "run_snippet", "Run"),
        Binding("g", "run_group", "Run on group", show=False),
        Binding("e", "edit_snippet", "Edit", show=False),
        Binding("a", "add", "Add"),
        Binding("P", "push_snippets", "Push/sync", show=False),
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
            ("e", "edit"), ("a", "add"), ("P", "push/sync"), ("D", "delete"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        self.query_one("#snip-title", Static).update(m(
            " [bold]Snippets[/bold]  [dim]alias:[/dim] [#7dcfff]$a[/#7dcfff]",
            a=self._focused_alias or "(none)",
        ))
        table = self.query_one("#snip-table", DataTable)
        table.add_columns("NAME", "SUDO", "DESCRIPTION")
        self._load()

    def _load(self) -> None:
        cur = self._focused_snippet()
        cur_name = cur.name if cur else None
        self._snippets = load_snippets()
        table = self.query_one("#snip-table", DataTable)
        table.clear()
        for s in self._snippets:
            table.add_row(
                cell(s.name, "bold"),
                cell("sudo", "#e0af68") if s.use_sudo == "yes" else cell("—", "dim"),
                cell(s.description) if s.description else cell("—", "dim"),
                key=s.name,
            )
        if cur_name:
            for i, s in enumerate(self._snippets):
                if s.name == cur_name:
                    table.move_cursor(row=i)
                    break
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
        sudo_note = "  [#e0af68]requires sudo[/#e0af68]\n" if s.use_sudo == "yes" else ""
        # commands are full of brackets ("[ -f x ]", "grep [a-z]") — $-slots
        # keep them literal
        detail.update(m(
            "[bold #ff9e64]$name[/bold #ff9e64]\n\n"
            "  [dim] desc[/dim]  $desc\n"
            + sudo_note + "\n" + rule + "\n"
            "[#9ece6a]$cmd[/#9ece6a]\n",
            name=s.name, desc=s.description or "—", cmd=s.command,
        ))

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def action_run_snippet(self) -> None:
        s = self._focused_snippet()
        if not s:
            return
        aliases = [a.name for a in load_aliases()]
        self.app.push_screen(
            _RunOnModal(s.name, aliases, preselect=self._focused_alias),
            callback=lambda targets: self._on_run_targets(s.name, targets),
        )

    def _on_run_targets(self, snip_name: str, targets: list[str] | None) -> None:
        if not targets:
            return
        with self.app.suspend():
            engine.snip_run_targets(snip_name, targets, parallel=len(targets) > 1)

    def action_push_snippets(self) -> None:
        hosts = load_bootstrapped_aliases()
        if not hosts:
            self.notify("No bootstrapped hosts found", severity="warning")
            return
        self.app.push_screen(
            _PushToModal(hosts),
            callback=lambda targets: self._on_push_targets(targets),
        )

    def _on_push_targets(self, targets: list[str] | None) -> None:
        if not targets:
            return
        with self.app.suspend():
            engine.snip_push(targets)

    def action_edit_snippet(self) -> None:
        s = self._focused_snippet()
        if s:
            with self.app.suspend():
                engine.snip_edit(s.name)
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
                engine.snip_run_group(snip_name, group)

    def action_add(self) -> None:
        with self.app.suspend():
            engine.snip_add()
        self._load()

    def action_delete(self) -> None:
        s = self._focused_snippet()
        if not s:
            return
        from sshop.modals import ConfirmModal
        self.app.push_screen(
            ConfirmModal(m("Delete snippet [bold]$s[/bold]?", s=s.name), confirm_label="Delete"),
            callback=lambda ok: self._on_delete_confirmed(ok, s.name),
        )

    def _on_delete_confirmed(self, confirmed: bool, name: str) -> None:
        if not confirmed:
            return

        def _done(res: tuple[int, str]) -> None:
            code, msg = res
            if code == 0:
                self.notify(f"Deleted snippet '{name}'", markup=False)
            else:
                self.notify(f"Error: {plain(msg).strip()}", severity="error", markup=False)
            self._load()

        run_blocking(self, lambda: engine.snip_delete(name), _done)
