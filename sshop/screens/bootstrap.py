from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, DataTable, Static
from textual.containers import Horizontal, Vertical

from sshop import engine
from sshop.config import Alias, load_aliases
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


def _bootstrap_status(alias_name: str) -> str:
    """Read the bootstrap install date from preferences, or empty string."""
    from sshop.config import _parse_preferences
    prefs = _parse_preferences()
    return prefs.get(f"bootstrap_{alias_name}", "")


class BootstrapScreen(Screen):
    """Bootstrap management for a single alias: install, update, connect+profile, remove."""

    BINDINGS = [
        Binding("i", "install", "Install", show=False),
        Binding("u", "update", "Update snippets", show=False),
        Binding("P", "connect_profile", "Connect+profile", show=False),
        Binding("R", "remove", "Remove", show=False),
        Binding("escape,q", "dismiss", "Back"),
    ]

    def __init__(self, alias: Alias):
        super().__init__()
        self._alias = alias
        self._installed: str = ""

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="bs-header")
        with Vertical(id="bs-body"):
            yield Static("", id="bs-status")
            with Horizontal(id="bs-buttons"):
                yield Button("Install / update profile", variant="primary", id="btn-install")
                yield Button("Sync snippets", variant="default", id="btn-update")
                yield Button("Connect with profile", variant="default", id="btn-profile")
                yield Button("Remove", variant="error", id="btn-remove")
            yield Static("", id="bs-output")
        yield KeyBar(rows=[[
            ("i", "install"), ("u", "sync snippets"), ("P", "connect+profile"),
            ("R", "remove"), ("q", "back"),
        ]])

    DEFAULT_CSS = """
    BootstrapScreen #bs-body {
        height: 1fr;
        padding: 1 2;
    }
    BootstrapScreen #bs-status {
        height: auto;
        padding: 1 0;
        color: #c0caf5;
    }
    BootstrapScreen #bs-buttons {
        height: auto;
        margin-bottom: 1;
    }
    BootstrapScreen #bs-buttons Button {
        margin-right: 1;
    }
    BootstrapScreen #bs-output {
        height: 1fr;
        border: solid #2a2b3d;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def on_mount(self) -> None:
        try:
            from sshop.config import load_aliases, load_tunnels, load_snippets
            self.query_one("#bs-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        self._refresh_status()

    def _refresh_status(self) -> None:
        self._installed = _bootstrap_status(self._alias.name)
        status_widget = self.query_one("#bs-status", Static)
        if self._installed:
            status_widget.update(
                f"[bold #ff9e64]Bootstrap — {self._alias.name}[/bold #ff9e64]\n\n"
                f"  [#9ece6a]✓  Installed[/#9ece6a]  [dim]{self._installed}[/dim]\n\n"
                f"  host  [#c0caf5]{self._alias.hostname}[/#c0caf5]  "
                f"  user  [#c0caf5]{self._alias.user or '(default)'}[/#c0caf5]\n\n"
                f"  [dim]Ctrl+X s  →  fzf snippet picker active on remote[/dim]"
            )
        else:
            status_widget.update(
                f"[bold #ff9e64]Bootstrap — {self._alias.name}[/bold #ff9e64]\n\n"
                f"  [#565f89]○  Not installed[/#565f89]\n\n"
                f"  host  [#c0caf5]{self._alias.hostname}[/#c0caf5]  "
                f"  user  [#c0caf5]{self._alias.user or '(default)'}[/#c0caf5]\n\n"
                f"  [dim]Install to deploy Ctrl+X s fzf snippet picker to the remote shell.[/dim]"
            )
        self.query_one("#bs-output", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_map = {
            "btn-install":  self.action_install,
            "btn-update":   self.action_update,
            "btn-profile":  self.action_connect_profile,
            "btn-remove":   self.action_remove,
        }
        if event.button.id in btn_map:
            btn_map[event.button.id]()

    def action_install(self) -> None:
        self.query_one("#bs-output", Static).update(
            "[dim]Running bootstrap install — this may take a moment…[/dim]"
        )
        with self.app.suspend():
            engine.bootstrap_install(self._alias.name)
        self._refresh_status()
        self.notify(f"Bootstrap complete for {self._alias.name}")

    @work(thread=True)
    def action_update(self) -> None:
        self.app.call_from_thread(
            self.query_one("#bs-output", Static).update,
            "[dim]Syncing snippets…[/dim]",
        )
        code, out = engine.bootstrap_update(self._alias.name)
        msg = out.strip() or ("Snippets synced." if code == 0 else "Sync failed.")
        self.app.call_from_thread(
            self.query_one("#bs-output", Static).update,
            f"[{'#9ece6a' if code == 0 else '#f7768e'}]{msg}[/{'#9ece6a' if code == 0 else '#f7768e'}]",
        )
        self.app.call_from_thread(
            self.notify,
            msg,
            severity="information" if code == 0 else "error",
        )

    def action_connect_profile(self) -> None:
        with self.app.suspend():
            engine.connect_with_profile(self._alias.name)

    @work(thread=True)
    def action_remove(self) -> None:
        self.app.call_from_thread(
            self.query_one("#bs-output", Static).update,
            "[dim]Removing bootstrap profile…[/dim]",
        )
        code, out = engine.bootstrap_remove(self._alias.name)
        msg = out.strip() or ("Removed." if code == 0 else "Remove failed.")
        self.app.call_from_thread(
            self.query_one("#bs-output", Static).update,
            f"[{'#9ece6a' if code == 0 else '#f7768e'}]{msg}[/{'#9ece6a' if code == 0 else '#f7768e'}]",
        )
        if code == 0:
            self.app.call_from_thread(self._refresh_status)
        self.app.call_from_thread(
            self.notify,
            msg,
            severity="information" if code == 0 else "error",
        )
