from __future__ import annotations

import datetime
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal


class StatsHeader(Widget):
    DEFAULT_CSS = """
    StatsHeader {
        height: 3;
        layout: vertical;
        background: #13141f;
        border-bottom: solid #2a2b3d;
        align: center middle;
    }
    StatsHeader #hdr-top {
        width: 100%;
        height: 1;
    }
    StatsHeader #hdr-title {
        width: 1fr;
        height: 1;
        align: left middle;
        padding: 0 2;
    }
    StatsHeader #hdr-stats {
        width: 1fr;
        height: 1;
        align: center middle;
    }
    StatsHeader #hdr-clock {
        width: 1fr;
        height: 1;
        align: right middle;
        padding: 0 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="hdr-top"):
            yield Static(
                "[bold #ff9e64]⚡ ssh[/bold #ff9e64][dim #ff9e64]op[/dim #ff9e64]"
                "[dim #565f89]  —  SSH operations, sorted.[/dim #565f89]",
                id="hdr-title",
            )
            yield Static("", id="hdr-stats")
            yield Static("", id="hdr-clock")

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
