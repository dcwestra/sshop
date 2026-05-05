from __future__ import annotations

import datetime
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal


class StatsHeader(Widget):
    DEFAULT_CSS = """
    StatsHeader {
        height: 2;
        layout: vertical;
        background: #13141f;
        border-bottom: solid #2a2b3d;
    }
    StatsHeader #hdr-top {
        height: 1;
        background: #13141f;
    }
    StatsHeader #hdr-title {
        width: 1fr;
        height: 1;
        content-align: left middle;
        padding: 0 2;
    }
    StatsHeader #hdr-clock {
        width: auto;
        height: 1;
        content-align: right middle;
        padding: 0 2;
    }
    StatsHeader #hdr-stats {
        height: 1;
        content-align: left middle;
        padding: 0 2;
        background: #1a1b26;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="hdr-top"):
            yield Static(
                "[bold #ff9e64]⚡ ssh[/bold #ff9e64][dim #ff9e64]op[/dim #ff9e64]"
                "[dim #565f89]  —  SSH, sorted.[/dim #565f89]",
                id="hdr-title",
            )
            yield Static("", id="hdr-clock")
        yield Static("", id="hdr-stats")

    def on_mount(self) -> None:
        self.set_interval(1, self._tick)
        self._tick()
        self.update_stats(0, 0, 0)

    def update_stats(self, aliases: int, tunnels: int, snippets: int) -> None:
        sep = "  [#2a2b3d]·[/#2a2b3d]  "
        self.query_one("#hdr-stats", Static).update(
            f"[bold #7dcfff]{aliases}[/bold #7dcfff] [dim #7dcfff]aliases[/dim #7dcfff]"
            f"{sep}"
            f"[bold #9ece6a]{tunnels}[/bold #9ece6a] [dim #9ece6a]tunnels[/dim #9ece6a]"
            f"{sep}"
            f"[bold #bb9af7]{snippets}[/bold #bb9af7] [dim #bb9af7]snippets[/dim #bb9af7]"
        )

    def _tick(self) -> None:
        now = datetime.datetime.now()
        self.query_one("#hdr-clock", Static).update(
            f"[#565f89]{now.strftime('%a %d %b')}[/#565f89]"
            f"  [bold #7aa2f7]{now.strftime('%H:%M:%S')}[/bold #7aa2f7]  "
        )
