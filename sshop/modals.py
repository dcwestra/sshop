"""Small input modals shared across screens."""

from __future__ import annotations

import re

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static
from textual.containers import Grid, Vertical

_ANSI_RE = re.compile(r'\x1b(?:\[[0-9;]*[mKGHFJsun]|[^[[])|[\x00-\x08\x0b-\x1f\x7f]')


def _render(content: str) -> Text:
    """Convert okssh ANSI output to a Rich Text object for clean modal display."""
    return Text.from_ansi(content)


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
        from textual.containers import Horizontal
        with Vertical():
            yield Static(f"[bold]{self._title}[/bold]")
            yield Label(self._label)
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
        from textual.containers import Horizontal
        current_txt = self._current if self._current else "(no groups)"
        with Vertical():
            yield Static(f"[bold #ff9e64]Manage groups[/bold #ff9e64]  [dim]→[/dim]  [bold]{self._alias}[/bold]")
            yield Static(f"Current: [#7dcfff]{current_txt}[/#7dcfff]", id="current-label")
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
    """Pick export format: normal SSH config or Ansible inventory."""

    DEFAULT_CSS = """
    ExportFormatModal {
        align: center middle;
    }
    ExportFormatModal > Vertical {
        width: 50;
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
        from textual.containers import Horizontal
        with Vertical():
            yield Static("[bold #ff9e64]Export aliases[/bold #ff9e64]")
            yield Static("\n[dim]Choose export format:[/dim]")
            with Horizontal(id="btn-row"):
                yield Button("SSH config", variant="primary", id="btn-ssh")
                yield Button("Ansible inventory", variant="success", id="btn-ansible")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ssh":
            self.dismiss("ssh")
        elif event.button.id == "btn-ansible":
            self.dismiss("ansible")
        else:
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


class OutputModal(ModalScreen):
    """Display command output with a Close button."""

    DEFAULT_CSS = """
    OutputModal {
        align: center middle;
    }
    OutputModal > Vertical {
        width: 80;
        height: 30;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }
    OutputModal Static#output {
        height: 1fr;
        overflow-y: auto;
    }
    OutputModal #btn-row {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }
    """

    def __init__(self, title: str, content: str):
        super().__init__()
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal
        with Vertical():
            yield Static(f"[bold]{self._title}[/bold]")
            yield Static(_render(self._content), id="output")
            with Horizontal(id="btn-row"):
                yield Button("Close", variant="primary", id="btn-close")

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        self.dismiss()

    def key_escape(self) -> None:
        self.dismiss()


class AuditOutputModal(ModalScreen[bool]):
    """Key audit results with a 'Set Threshold' button alongside Close."""

    DEFAULT_CSS = """
    AuditOutputModal {
        align: center middle;
    }
    AuditOutputModal > Vertical {
        width: 80;
        height: 30;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }
    AuditOutputModal Static#output {
        height: 1fr;
        overflow-y: auto;
    }
    AuditOutputModal #btn-row {
        height: 3;
        align-horizontal: left;
        margin-top: 1;
    }
    AuditOutputModal #btn-close {
        dock: right;
    }
    """

    def __init__(self, content: str):
        super().__init__()
        self._content = content

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal
        with Vertical():
            yield Static("[bold]Key Audit[/bold]")
            yield Static(_render(self._content), id="output")
            with Horizontal(id="btn-row"):
                yield Button("Set Threshold", variant="default", id="btn-threshold")
                yield Button("Close", variant="primary", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-threshold")

    def key_escape(self) -> None:
        self.dismiss(False)
