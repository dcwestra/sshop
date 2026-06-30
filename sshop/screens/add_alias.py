from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static
from textual.containers import Horizontal, ScrollableContainer

from sshop import engine
from sshop.config import load_aliases, load_tunnels, load_snippets
from sshop.screens.import_key import _FilePicker
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar

_KEY_TYPES = [("ed25519 (recommended)", "ed25519"), ("rsa", "rsa"), ("ecdsa", "ecdsa")]
_KEY_SOURCE = [("Generate a new key", "generate"), ("Import an existing key", "import")]


def _row(label: str, widget_id: str, placeholder: str = "", value: str = "") -> ComposeResult:
    yield Label(label, classes="aa-label")
    yield Input(value=value, placeholder=placeholder, id=widget_id, classes="aa-input")


class AddAliasScreen(Screen):

    BINDINGS = [
        Binding("f5", "browse", "Browse key", show=False),
        Binding("escape", "dismiss", "Cancel"),
    ]

    DEFAULT_CSS = """
    AddAliasScreen #aa-body {
        height: 1fr;
        padding: 1 2;
    }
    AddAliasScreen #aa-title {
        height: 1;
        margin-bottom: 1;
        color: #c0caf5;
    }
    AddAliasScreen .aa-row {
        height: 3;
        margin-bottom: 1;
    }
    AddAliasScreen .aa-label {
        width: 14;
        height: 3;
        content-align: right middle;
        padding-right: 1;
        color: #565f89;
    }
    AddAliasScreen .aa-input {
        width: 1fr;
    }
    AddAliasScreen .aa-select {
        width: 1fr;
    }
    AddAliasScreen #aa-divider {
        height: 1;
        border-top: dashed #2a2b3d;
        margin: 1 0;
    }
    AddAliasScreen #aa-keyfile-row {
        height: 3;
        margin-bottom: 1;
    }
    AddAliasScreen #aa-keyfile-input {
        width: 1fr;
    }
    AddAliasScreen #btn-browse {
        width: 12;
        margin-left: 1;
    }
    AddAliasScreen #gen-section {
        height: auto;
    }
    AddAliasScreen #imp-section {
        height: auto;
    }
    AddAliasScreen #aa-buttons {
        height: 3;
        margin-top: 1;
        padding-left: 15;
    }
    AddAliasScreen #aa-buttons Button {
        margin-right: 2;
    }
    AddAliasScreen #aa-opt-label {
        height: 1;
        color: #565f89;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="aa-header")
        with ScrollableContainer(id="aa-body"):
            yield Static(" [bold]Add SSH Alias[/bold]", id="aa-title")

            # ── connection details ─────────────────────────────────────────────
            with Horizontal(classes="aa-row"):
                yield from _row("Alias", "aa-alias", "work-server")
            with Horizontal(classes="aa-row"):
                yield from _row("Hostname", "aa-host", "192.168.1.100")
            with Horizontal(classes="aa-row"):
                yield from _row("Port", "aa-port", "22", value="22")
            with Horizontal(classes="aa-row"):
                yield from _row("Username", "aa-user", "ubuntu")

            # ── key source toggle ──────────────────────────────────────────────
            with Horizontal(classes="aa-row"):
                yield Label("Key source", classes="aa-label")
                yield Select(_KEY_SOURCE, value="generate", id="aa-key-source",
                             classes="aa-select", allow_blank=False)

            # generate section
            with ScrollableContainer(id="gen-section"):
                with Horizontal(classes="aa-row"):
                    yield Label("Key type", classes="aa-label")
                    yield Select(_KEY_TYPES, value="ed25519", id="aa-key-type",
                                 classes="aa-select", allow_blank=False)
                with Horizontal(classes="aa-row"):
                    yield Label("Password", classes="aa-label")
                    yield Input(placeholder="remote login password (used once for ssh-copy-id)",
                                id="aa-password", password=True, classes="aa-input")

            # import section (hidden by default)
            with ScrollableContainer(id="imp-section"):
                with Horizontal(classes="aa-row", id="aa-keyfile-row"):
                    yield Label("Key file", classes="aa-label")
                    yield Input(placeholder="~/Downloads/server_key.pem",
                                id="aa-keyfile-input", classes="aa-input")
                    yield Button("Browse", id="btn-browse", variant="default")

            # ── optional fields ────────────────────────────────────────────────
            yield Static(" Optional", id="aa-opt-label")
            with Horizontal(classes="aa-row"):
                yield from _row("Note", "aa-note", "short description")
            with Horizontal(classes="aa-row"):
                yield from _row("Group(s)", "aa-group", "work,homelab")
            with Horizontal(classes="aa-row"):
                yield from _row("Jump host", "aa-jump", "bastion")

            with Horizontal(id="aa-buttons"):
                yield Button("Add Alias", variant="success", id="btn-add")
                yield Button("Cancel", variant="default", id="btn-cancel")

        yield KeyBar(rows=[[("F5", "browse key"), ("↵", "add"), ("Esc", "cancel")]])

    def on_mount(self) -> None:
        try:
            self.query_one("#aa-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        # import section hidden until user switches
        self.query_one("#imp-section").display = False
        self.query_one("#aa-alias", Input).focus()

    # ── key source toggle ─────────────────────────────────────────────────────

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "aa-key-source":
            is_import = event.value == "import"
            self.query_one("#gen-section").display = not is_import
            self.query_one("#imp-section").display = is_import

    # ── file browser ──────────────────────────────────────────────────────────

    def action_browse(self) -> None:
        current = self.query_one("#aa-keyfile-input", Input).value.strip()
        start = str(Path(current).parent) if current and Path(current).parent.exists() else "~"
        self.app.push_screen(_FilePicker(start), self._on_file_picked)

    def _on_file_picked(self, path: str | None) -> None:
        if path:
            self.query_one("#aa-keyfile-input", Input).value = path

    # ── buttons ───────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            self.action_browse()
        elif event.button.id == "btn-add":
            self._do_add()
        elif event.button.id == "btn-cancel":
            self.dismiss(False)

    # ── submit ────────────────────────────────────────────────────────────────

    def _do_add(self) -> None:
        alias   = self.query_one("#aa-alias",  Input).value.strip()
        host    = self.query_one("#aa-host",   Input).value.strip()
        port_s  = self.query_one("#aa-port",   Input).value.strip()
        user    = self.query_one("#aa-user",   Input).value.strip()
        note    = self.query_one("#aa-note",   Input).value.strip()
        group   = self.query_one("#aa-group",  Input).value.strip()
        jump    = self.query_one("#aa-jump",   Input).value.strip()

        source_sel = self.query_one("#aa-key-source", Select)
        is_import  = source_sel.value == "import"

        if is_import:
            key_file = self.query_one("#aa-keyfile-input", Input).value.strip()
            key_type = ""
            password = ""
        else:
            key_file = ""
            key_type = str(self.query_one("#aa-key-type", Select).value or "ed25519")
            password = self.query_one("#aa-password", Input).value

        # Validate required fields
        errors = []
        if not alias:
            errors.append("Alias is required")
        if not host:
            errors.append("Hostname is required")
        if not user:
            errors.append("Username is required")
        if is_import:
            if not key_file:
                errors.append("Key file path is required")
            else:
                expanded = key_file.replace("~", str(Path.home()), 1)
                if not Path(expanded).exists():
                    errors.append(f"Key file not found: {key_file}")
        else:
            if not password:
                errors.append("Password is required for ssh-copy-id")
        if errors:
            self.notify("\n".join(errors), severity="error", timeout=6)
            return

        port = int(port_s) if port_s.isdigit() else 22

        # Disable the Add button to prevent double-submit during ssh-copy-id
        btn = self.query_one("#btn-add", Button)
        btn.disabled = True
        btn.label = "Working…"

        self.run_worker(
            self._run_add(alias, host, user, port, key_type, password, key_file, note, group, jump),
            exclusive=True,
        )

    async def _run_add(
        self,
        alias: str, host: str, user: str, port: int,
        key_type: str, password: str, key_file: str,
        note: str, group: str, jump: str,
    ) -> None:
        import asyncio
        loop = asyncio.get_event_loop()
        code, msg = await loop.run_in_executor(
            None,
            lambda: engine.add_alias(
                alias=alias, host=host, user=user, port=port,
                key_type=key_type, password=password, key_file=key_file,
                note=note, group=group, jump=jump,
            ),
        )
        self.app.call_from_thread(self._on_add_done, code, msg, alias)

    def _on_add_done(self, code: int, msg: str, alias: str) -> None:
        btn = self.query_one("#btn-add", Button)
        btn.disabled = False
        btn.label = "Add Alias"
        if code == 0:
            self.notify(f"Added [bold]{alias}[/bold]", severity="information")
            self.dismiss(True)
        else:
            self.notify(msg.strip() or "Add failed", severity="error", timeout=10)
