from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, Static
from textual.containers import Horizontal, ScrollableContainer, Vertical

from sshop import engine
from sshop.config import load_aliases, load_tunnels, load_snippets
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


class _FilePicker(ModalScreen[str | None]):
    """Browse the filesystem and return a selected file path."""

    BINDINGS = [Binding("escape", "dismiss_none", "Cancel")]

    DEFAULT_CSS = """
    _FilePicker {
        align: center middle;
    }
    _FilePicker > Vertical {
        width: 70;
        height: 28;
        border: round #7aa2f7;
        background: #1a1b26;
        padding: 0 1;
    }
    _FilePicker #picker-title {
        height: 1;
        padding: 0 1;
        color: #7aa2f7;
        background: #13141f;
    }
    _FilePicker DirectoryTree {
        height: 1fr;
        background: #1a1b26;
        border: none;
    }
    _FilePicker #picker-hint {
        height: 1;
        color: #565f89;
        content-align: center middle;
    }
    """

    def __init__(self, start: str = "~"):
        super().__init__()
        self._start = str(Path(start).expanduser())

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(" Browse — select key file", id="picker-title")
            yield DirectoryTree(self._start, id="picker-tree")
            yield Static("Enter to select  •  Esc to cancel", id="picker-hint")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


# ── field row helper ──────────────────────────────────────────────────────────

def _field(label: str, id: str, placeholder: str = "", value: str = "") -> ComposeResult:
    yield Label(label, classes="ik-label")
    yield Input(value=value, placeholder=placeholder, id=id, classes="ik-input")


# ── main screen ───────────────────────────────────────────────────────────────

class ImportKeyScreen(Screen):

    BINDINGS = [
        Binding("f5", "browse", "Browse", show=False),
        Binding("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    ImportKeyScreen #ik-body {
        height: 1fr;
        padding: 1 2;
    }
    ImportKeyScreen .ik-row {
        height: 3;
        margin-bottom: 1;
    }
    ImportKeyScreen .ik-label {
        width: 12;
        height: 3;
        content-align: right middle;
        padding-right: 1;
        color: #565f89;
    }
    ImportKeyScreen .ik-input {
        width: 1fr;
    }
    ImportKeyScreen #ik-keyfile-row {
        height: 3;
        margin-bottom: 1;
    }
    ImportKeyScreen #ik-keyfile-input {
        width: 1fr;
    }
    ImportKeyScreen #btn-browse {
        width: 12;
        margin-left: 1;
    }
    ImportKeyScreen #ik-hint {
        height: 1;
        color: #565f89;
        margin-bottom: 1;
        padding-left: 13;
    }
    ImportKeyScreen #ik-buttons {
        height: 3;
        margin-top: 1;
        padding-left: 13;
    }
    ImportKeyScreen #ik-buttons Button {
        margin-right: 2;
    }
    """

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="ik-header")
        with ScrollableContainer(id="ik-body"):
            yield Static(" [bold]Import SSH Key[/bold]", id="ik-title")
            yield Static(
                "Paste a path, drag a file from your file manager, or press [bold]F5[/bold] to browse.",
                id="ik-hint",
            )

            with Horizontal(classes="ik-row", id="ik-keyfile-row"):
                yield Label("Key file", classes="ik-label")
                yield Input(placeholder="~/Downloads/server_key.pem", id="ik-keyfile-input")
                yield Button("Browse", id="btn-browse", variant="default")

            with Horizontal(classes="ik-row"):
                yield from _field("Alias", "ik-alias", "work-server")
            with Horizontal(classes="ik-row"):
                yield from _field("Hostname", "ik-host", "192.168.1.100")
            with Horizontal(classes="ik-row"):
                yield from _field("Port", "ik-port", "22", value="22")
            with Horizontal(classes="ik-row"):
                yield from _field("Username", "ik-user", "ubuntu")
            with Horizontal(classes="ik-row"):
                yield from _field("Note", "ik-note", "optional description")
            with Horizontal(classes="ik-row"):
                yield from _field("Group(s)", "ik-group", "work,homelab")

            with Horizontal(id="ik-buttons"):
                yield Button("Import", variant="success", id="btn-import")
                yield Button("Cancel", variant="default", id="btn-cancel")

        yield KeyBar(rows=[[
            ("F5", "browse"), ("↵", "import"), ("Esc", "cancel"),
        ]])

    def on_mount(self) -> None:
        try:
            self.query_one("#ik-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        self.query_one("#ik-keyfile-input", Input).focus()

    # ── file browser ──────────────────────────────────────────────────────────

    def action_browse(self) -> None:
        current = self.query_one("#ik-keyfile-input", Input).value.strip()
        start = str(Path(current).parent) if current and Path(current).parent.exists() else "~"
        self.app.push_screen(_FilePicker(start), self._on_file_picked)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-import":
            self._do_import()
        elif event.button.id == "btn-cancel":
            self.dismiss(False)

    def _on_file_picked(self, path: str | None) -> None:
        if path:
            self.query_one("#ik-keyfile-input", Input).value = path

    # ── import ────────────────────────────────────────────────────────────────

    def _do_import(self) -> None:
        key_file = self.query_one("#ik-keyfile-input", Input).value.strip()
        alias    = self.query_one("#ik-alias",         Input).value.strip()
        host     = self.query_one("#ik-host",          Input).value.strip()
        port_s   = self.query_one("#ik-port",          Input).value.strip()
        user     = self.query_one("#ik-user",          Input).value.strip()
        note     = self.query_one("#ik-note",          Input).value.strip()
        group    = self.query_one("#ik-group",         Input).value.strip()

        # Validate required fields
        errors = []
        if not key_file:
            errors.append("Key file path is required")
        elif not Path(key_file.replace("~", str(Path.home()))).exists():
            errors.append(f"Key file not found: {key_file}")
        if not alias:
            errors.append("Alias is required")
        if not host:
            errors.append("Hostname is required")
        if not user:
            errors.append("Username is required")
        if errors:
            self.notify("\n".join(errors), severity="error", timeout=6)
            return

        port = int(port_s) if port_s.isdigit() else 22

        code, msg = engine.import_key(
            alias=alias,
            key_file=key_file,
            host=host,
            user=user,
            port=port,
            note=note,
            group=group,
        )
        if code == 0:
            self.notify(f"Imported key for [bold]{alias}[/bold]", severity="information")
            self.dismiss(True)
        else:
            self.notify(msg.strip() or "Import failed", severity="error", timeout=8)
