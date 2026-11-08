from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Horizontal, Vertical

from sshop import engine
from sshop.config import Template, load_templates
from sshop.markup import cell, m, plain
from sshop.worker import run_blocking
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


class TemplateDetail(Static):
    DEFAULT_CSS = """
    TemplateDetail {
        width: 1fr;
        height: 100%;
        padding: 1 2;
        border: solid $primary-darken-2;
        overflow-y: auto;
    }
    """

    def show(self, t: Template | None) -> None:
        if t is None:
            self.update("")
            return
        rule = "[#2a2b3d]" + "─" * 26 + "[/#2a2b3d]"
        # (label, value, style) — values go in via $-slots, never as markup
        rows = [
            ("user",  t.user or "(prompt on add)", "" if t.user else "dim"),
            ("port",  t.port or "22", ""),
            ("group", t.group or "—", "#7dcfff" if t.group else "dim"),
            ("key",   t.key_type or "ed25519", "#bb9af7" if t.key_type else ""),
            ("note",  t.note or "—", "dim"),
            ("alive", t.server_alive_interval or "—", "" if t.server_alive_interval else "dim"),
        ]
        content = m("[bold #ff9e64]$n[/bold #ff9e64]\n" + rule + "\n\n", n=t.name)
        for k, v, style in rows:
            line = f"  [dim]{k:>5}[/dim]  " + (f"[{style}]$v[/{style}]" if style else "$v") + "\n"
            content = content + m(line, v=v)
        content = content + m("\n" + rule + "\n"
                              "  [bold #7aa2f7] D[/bold #7aa2f7]  [#565f89]delete template[/#565f89]\n")
        self.update(content)


class TemplatesScreen(Screen):
    BINDINGS = [
        Binding("D", "delete", "Delete", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("escape,q", "dismiss", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self._templates: list[Template] = []

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="tmpl-header")
        with Horizontal(id="tmpl-layout"):
            with Vertical(id="tmpl-list-pane"):
                yield Static(
                    " [bold]Templates[/bold]  [dim]—[/dim]"
                    "  [dim]D[/dim] delete  [dim]esc[/dim] back",
                    id="tmpl-title",
                )
                yield DataTable(id="tmpl-table", cursor_type="row", zebra_stripes=True)
            yield TemplateDetail(id="tmpl-detail")
        yield KeyBar(rows=[[
            ("D", "delete"), ("r", "refresh"), ("q", "back"),
        ]])

    def on_mount(self) -> None:
        table = self.query_one("#tmpl-table", DataTable)
        table.add_columns("NAME", "USER", "PORT", "GROUP", "KEY TYPE")
        self._load()

    def _load(self) -> None:
        self._templates = load_templates()
        table = self.query_one("#tmpl-table", DataTable)
        table.clear()
        if not self._templates:
            self.query_one("#tmpl-detail", TemplateDetail).show(None)
            return
        for t in self._templates:
            table.add_row(
                cell(t.name, "bold"),
                cell(t.user) if t.user else cell("(prompt)", "dim"),
                cell(t.port or "22"),
                cell(t.group, "#7dcfff") if t.group else cell("—", "dim"),
                cell(t.key_type, "#bb9af7") if t.key_type else cell("ed25519"),
                key=t.name,
            )
        if self._templates:
            self.query_one("#tmpl-detail", TemplateDetail).show(self._templates[0])

    def _focused_template(self) -> Template | None:
        table = self.query_one("#tmpl-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._templates):
            return self._templates[idx]
        return None

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        t = self._focused_template()
        self.query_one("#tmpl-detail", TemplateDetail).show(t)

    def action_delete(self) -> None:
        t = self._focused_template()
        if not t:
            return
        name = t.name
        from sshop.modals import ConfirmModal
        self.app.push_screen(
            ConfirmModal(m("Delete template [bold]$n[/bold]?", n=name), confirm_label="Delete"),
            callback=lambda ok: self._on_delete_confirmed(ok, name),
        )

    def _on_delete_confirmed(self, confirmed: bool, name: str) -> None:
        if not confirmed:
            return

        def _done(res: tuple[int, str]) -> None:
            code, msg = res
            if code == 0:
                self.notify(f"Removed template '{name}'", markup=False)
                self._load()
            else:
                self.notify(f"Error: {plain(msg).strip()}", severity="error", markup=False)

        run_blocking(self, lambda: engine.template_remove(name), _done)

    def action_refresh(self) -> None:
        self._load()
