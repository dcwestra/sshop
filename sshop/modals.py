"""Small input modals shared across screens.

Titles, labels and messages are shown as literal text (or as a Content the
caller built with sshop.markup.m) — never parsed as markup, because they
carry alias names, groups and okssh output.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll

from sshop.markup import m


def _as_content(value: str | Content | Text) -> Content | Text:
    """Plain str → literal Content; Content/Text pass through."""
    return Content(value) if isinstance(value, str) else value


class _InputModal(ModalScreen[str | None]):
    """Base for single-input modals. Returns the entered value or None on cancel."""

    DEFAULT_CSS = """
    _InputModal {
        align: center middle;
    }
    _InputModal > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }
    _InputModal Label {
        margin-bottom: 1;
    }
    _InputModal Input {
        margin-bottom: 1;
    }
    _InputModal #btn-row {
        height: 3;
        align-horizontal: right;
    }
    _InputModal Button {
        margin-left: 1;
        min-width: 10;
    }
    """

    def __init__(self, title: str, label: str, placeholder: str = "", default: str = ""):
        super().__init__()
        self._title = title
        self._label = label
        self._placeholder = placeholder
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(m("[bold]$t[/bold]", t=self._title))
            yield Label(Content(self._label))
            yield Input(value=self._default, placeholder=self._placeholder, id="modal-input")
            with Horizontal(id="btn-row"):
                yield Button("OK", variant="primary", id="btn-ok")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            val = self.query_one("#modal-input", Input).value.strip()
            self.dismiss(val if val else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        self.dismiss(val if val else None)

    def key_escape(self) -> None:
        self.dismiss(None)


class RenameModal(_InputModal):
    def __init__(self, current_name: str):
        super().__init__(
            title=f"Rename alias: {current_name}",
            label="New alias name",
            placeholder="new-alias-name",
            default=current_name,
        )


class CloneModal(_InputModal):
    def __init__(self, src_name: str):
        super().__init__(
            title=f"Clone alias: {src_name}",
            label="New alias name",
            placeholder="new-alias-name",
        )


class RunCmdModal(_InputModal):
    def __init__(self, alias: str):
        super().__init__(
            title=f"Run remote command on: {alias}",
            label="Command",
            placeholder="e.g. df -h",
        )


class ThresholdModal(_InputModal):
    def __init__(self, current: int | None):
        cur_str = "off" if current is None else str(current)
        super().__init__(
            title="Key rotation threshold",
            label=f"Days before flagging (current: {cur_str}) — type 'off' to disable, blank to keep",
            placeholder=cur_str,
            default=cur_str,
        )


class ConfirmModal(ModalScreen[bool]):
    """Generic yes/no confirmation. Returns True if confirmed.

    message: plain text, or a Content built with sshop.markup.m() when it
    needs styling around user-supplied names."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Grid {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 1 2;
        width: 54;
        height: 10;
        border: solid $error;
        background: $surface;
    }
    ConfirmModal Label {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }
    ConfirmModal Button { width: 100%; }
    """

    def __init__(self, message: str | Content, confirm_label: str = "Confirm"):
        super().__init__()
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label(_as_content(self._message))
            yield Button(self._confirm_label, variant="error", id="btn-yes")
            yield Button("Cancel", variant="default", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def key_escape(self) -> None:
        self.dismiss(False)


class TagModal(ModalScreen):
    """Manage group tags for an alias. Returns ('tag'|'untag', group) or None."""

    DEFAULT_CSS = """
    TagModal {
        align: center middle;
    }
    TagModal > Vertical {
        width: 62;
        height: auto;
        padding: 1 2;
        border: solid #7aa2f7;
        background: $surface;
    }
    TagModal #current-label {
        color: #565f89;
        margin-bottom: 1;
    }
    TagModal Input {
        margin-bottom: 1;
    }
    TagModal #btn-row {
        height: 3;
        align-horizontal: right;
    }
    TagModal Button {
        margin-left: 1;
        min-width: 10;
    }
    """

    def __init__(self, alias: str, current_groups: str):
        super().__init__()
        self._alias = alias
        self._current = current_groups

    def compose(self) -> ComposeResult:
        current_txt = self._current if self._current else "(no groups)"
        with Vertical():
            yield Static(m("[bold #ff9e64]Manage groups[/bold #ff9e64]  [dim]→[/dim]  [bold]$a[/bold]",
                           a=self._alias))
            yield Static(m("Current: [#7dcfff]$g[/#7dcfff]", g=current_txt), id="current-label")
            yield Input(placeholder="group name, e.g. homelab", id="modal-input")
            with Horizontal(id="btn-row"):
                yield Button("Add tag", variant="success", id="btn-add")
                yield Button("Remove tag", variant="error", id="btn-rm")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def _value(self) -> str:
        return self.query_one("#modal-input", Input).value.strip()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        v = self._value()
        if event.button.id == "btn-add":
            self.dismiss(("tag", v) if v else None)
        elif event.button.id == "btn-rm":
            self.dismiss(("untag", v) if v else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        v = self._value()
        self.dismiss(("tag", v) if v else None)

    def key_escape(self) -> None:
        self.dismiss(None)


class ExportFormatModal(ModalScreen):
    """Pick export format: okssh's portable export file or an Ansible inventory.
    Returns "okssh", "ansible" or None."""

    DEFAULT_CSS = """
    ExportFormatModal {
        align: center middle;
    }
    ExportFormatModal > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid #7aa2f7;
        background: $surface;
    }
    ExportFormatModal #btn-row {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }
    ExportFormatModal Button {
        margin-left: 1;
        min-width: 14;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[bold #ff9e64]Export aliases[/bold #ff9e64]")
            yield Static("\n[dim]Saved to your home folder and shown here.\n"
                         "okssh export → re-import with okssh import <file>[/dim]")
            with Horizontal(id="btn-row"):
                yield Button("okssh export", variant="primary", id="btn-okssh")
                yield Button("Ansible inventory", variant="success", id="btn-ansible")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-okssh":
            self.dismiss("okssh")
        elif event.button.id == "btn-ansible":
            self.dismiss("ansible")
        else:
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


_OUTPUT_CSS = """
{cls} {{
    align: center middle;
}}
{cls} > Vertical {{
    width: 90%;
    max-width: 110;
    height: 80%;
    padding: 1 2;
    border: solid $primary;
    background: $surface;
}}
{cls} #output-scroll {{
    height: 1fr;
    border: none;
}}
{cls} #output-scroll:focus {{
    background-tint: $foreground 3%;
}}
{cls} #btn-row {{
    height: 3;
    margin-top: 1;
}}
"""


class OutputModal(ModalScreen):
    """Scrollable command output with a Close button.

    content: a str is treated as okssh output (ANSI colours rendered, never
    markup); pass a Text/Content to show pre-styled text such as help."""

    BINDINGS = [Binding("q", "close", "Close", show=False)]
    DEFAULT_CSS = _OUTPUT_CSS.format(cls="OutputModal") + """
    OutputModal #btn-row { align-horizontal: right; }
    """

    def __init__(self, title: str, content: str | Text | Content):
        super().__init__()
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        body = Text.from_ansi(self._content) if isinstance(self._content, str) else self._content
        with Vertical():
            yield Static(m("[bold]$t[/bold]", t=self._title))
            with VerticalScroll(id="output-scroll"):
                yield Static(body, id="output")
            with Horizontal(id="btn-row"):
                yield Button("Close", variant="primary", id="btn-close")

    def on_mount(self) -> None:
        # focus the scroll area so ↑/↓/PgUp/PgDn/Home/End scroll right away
        self.query_one("#output-scroll", VerticalScroll).focus()

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()

    def key_escape(self) -> None:
        self.dismiss()


class AuditOutputModal(ModalScreen[bool]):
    """Key audit results (scrollable) with a 'Set Threshold' button."""

    BINDINGS = [Binding("q", "close", "Close", show=False)]
    DEFAULT_CSS = _OUTPUT_CSS.format(cls="AuditOutputModal") + """
    AuditOutputModal #btn-row { align-horizontal: left; }
    AuditOutputModal #btn-close { dock: right; }
    """

    def __init__(self, content: str):
        super().__init__()
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[bold]Key Audit[/bold]")
            with VerticalScroll(id="output-scroll"):
                yield Static(Text.from_ansi(self._content), id="output")
            with Horizontal(id="btn-row"):
                yield Button("Set Threshold", variant="default", id="btn-threshold")
                yield Button("Close", variant="primary", id="btn-close")

    def on_mount(self) -> None:
        self.query_one("#output-scroll", VerticalScroll).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-threshold")

    def action_close(self) -> None:
        self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)
