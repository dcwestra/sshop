from __future__ import annotations

from pathlib import Path
from textual.app import App, ComposeResult
from textual.binding import Binding

from sshop.screens.home import HomeScreen

CSS_PATH = Path(__file__).parent.parent / "sshop.tcss"


class SshopApp(App):
    CSS_PATH = str(CSS_PATH)
    TITLE = "sshop"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())



def main() -> None:
    SshopApp().run()


if __name__ == "__main__":
    main()
