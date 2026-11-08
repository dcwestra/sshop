from __future__ import annotations

from pathlib import Path
from textual.app import App
from textual.binding import Binding

from sshop.screens.home import HomeScreen

CSS_PATH = Path(__file__).parent.parent / "sshop.tcss"


class SshopApp(App):
    CSS_PATH = str(CSS_PATH)
    TITLE = "sshop"

    # (visible aliases, tunnels, snippets) — refreshed by HomeScreen on every
    # reload; StatsHeader on other screens reads it instead of re-parsing
    stats_counts: tuple[int, int, int] | None = None

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


def main() -> None:
    SshopApp().run()


if __name__ == "__main__":
    main()
