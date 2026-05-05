from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Horizontal, Vertical

from sshop import engine
from sshop.config import Template, load_templates
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
        rows = [
            ("user",  t.user or "[dim](prompt on add)[/dim]"),
            ("port",  t.port or "22"),
            ("group", f"[#7dcfff]{t.group}[/#7dcfff]" if t.group else "[dim]—[/dim]"),
            ("key",   f"[#bb9af7]{t.key_type}[/#bb9af7]" if t.key_type else "ed25519"),
            ("note",  f"[dim]{t.note}[/dim]" if t.note else "[dim]—[/dim]"),
            ("alive", t.server_alive_interval or "[dim]—[/dim]"),
        ]
        detail = "\n".join(
            f"  [dim]{k:>5}[/dim]  {v}" for k, v in rows
        )
        self.update(
            f"[bold #ff9e64]{t.name}[/bold #ff9e64]\n"
            f"{rule}\n\n"
            f"{detail}\n\n"
            f"{rule}\n"
            f"  [bold #7aa2f7] D[/bold #7aa2f7]  [#565f89]delete template[/#565f89]\n"
        )


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
        try:
            from sshop.config import load_aliases, load_tunnels, load_snippets
            self.query_one("#tmpl-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass

    def _load(self) -> None:
        self._templates = load_templates()
        table = self.query_one("#tmpl-table", DataTable)
        table.clear()
        if not self._templates:
            self.query_one("#tmpl-detail", TemplateDetail).show(None)
            return
        for t in self._templates:
            table.add_row(
                f"[bold]{t.name}[/bold]",
                t.user or "[dim](prompt)[/dim]",
                t.port or "22",
                f"[#7dcfff]{t.group}[/#7dcfff]" if t.group else "[dim]—[/dim]",
                f"[#bb9af7]{t.key_type}[/#bb9af7]" if t.key_type else "ed25519",
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
        code, msg = engine.template_remove(t.name)
        if code == 0:
            self.notify(f"Removed template '{t.name}'")
            self._load()
        else:
            self.notify(f"Error: {msg}", severity="error")

    def action_refresh(self) -> None:
        self._load()
