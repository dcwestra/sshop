from __future__ import annotations

import subprocess
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static
from textual.containers import Horizontal, Vertical

from sshop import engine

OKSSH_BIN = engine.OKSSH_BIN
_CLI_ENV = engine._CLI_ENV


class AddEditScreen(Screen):
    """
    Launches okssh add / okssh edit in the terminal (via suspend).
    The form is handled by okssh's own wizard — we just hand off.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Back"),
    ]

    def __init__(self, alias_name: str | None = None):
        super().__init__()
        self._alias = alias_name

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="add-edit-body"):
            if self._alias:
                yield Static(
                    f"\n  [bold]Editing alias:[/bold] [cyan]{self._alias}[/cyan]\n\n"
                    f"  This will open the okssh edit wizard in your terminal.\n",
                    id="info"
                )
            else:
                yield Static(
                    "\n  [bold]Add new alias[/bold]\n\n"
                    "  This will open the okssh add wizard in your terminal.\n"
                    "  To register a key [italic]sent to you[/italic] (no keygen), use Import Key.\n",
                    id="info"
                )
            with Horizontal(id="buttons"):
                if self._alias:
                    yield Button("Open Edit Wizard", variant="primary", id="btn-go")
                else:
                    yield Button("Open Add Wizard", variant="primary", id="btn-go")
                    yield Button("Import Key File", variant="success", id="btn-import")
                yield Button("Cancel", variant="default", id="btn-cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-go":
            args = ["edit", self._alias] if self._alias else ["add"]
            with self.app.suspend():
                subprocess.run([OKSSH_BIN, *args], env=_CLI_ENV)
            self.dismiss(True)
        elif event.button.id == "btn-import":
            from sshop.screens.import_key import ImportKeyScreen
            self.app.push_screen(ImportKeyScreen(), callback=lambda _: self.dismiss(True))
        elif event.button.id == "btn-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
