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
    """Launches okssh edit in the terminal for an existing alias."""

    BINDINGS = [
        Binding("escape", "cancel", "Back"),
    ]

    def __init__(self, alias_name: str):
        super().__init__()
        self._alias = alias_name

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="add-edit-body"):
            yield Static(
                f"\n  [bold]Editing alias:[/bold] [cyan]{self._alias}[/cyan]\n\n"
                f"  This will open the okssh edit wizard in your terminal.\n",
                id="info"
            )
            with Horizontal(id="buttons"):
                yield Button("Open Edit Wizard", variant="primary", id="btn-go")
                yield Button("Cancel", variant="default", id="btn-cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-go":
            with self.app.suspend():
                subprocess.run([OKSSH_BIN, "edit", self._alias], env=_CLI_ENV)
            self.dismiss(True)
        elif event.button.id == "btn-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
