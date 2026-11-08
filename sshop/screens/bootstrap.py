from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Button, Static
from textual.containers import Horizontal, Vertical, VerticalScroll

from sshop import engine
from sshop.config import Alias, _parse_preferences
from sshop.markup import m, plain
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar


def _bootstrap_status(alias_name: str) -> str:
    """Read the bootstrap install date from preferences, or empty string."""
    return _parse_preferences().get(f"bootstrap_{alias_name}", "")


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
            with VerticalScroll(id="bs-output-scroll"):
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
    BootstrapScreen #bs-output-scroll {
        height: 1fr;
        border: solid #2a2b3d;
        padding: 1 2;
    }
    """

    def on_mount(self) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        self._installed = _bootstrap_status(self._alias.name)
        a = self._alias
        common = dict(name=a.name, host=a.hostname, user=a.user or "(default)")
        if self._installed:
            body = m(
                "[bold #ff9e64]Bootstrap — $name[/bold #ff9e64]\n\n"
                "  [#9ece6a]✓  Installed[/#9ece6a]  [dim]$date[/dim]\n\n"
                "  host  [#c0caf5]$host[/#c0caf5]    user  [#c0caf5]$user[/#c0caf5]\n\n"
                "  [dim]Ctrl+X s  →  fzf snippet picker active on remote[/dim]",
                date=self._installed, **common,
            )
        else:
            body = m(
                "[bold #ff9e64]Bootstrap — $name[/bold #ff9e64]\n\n"
                "  [#565f89]○  Not installed[/#565f89]\n\n"
                "  host  [#c0caf5]$host[/#c0caf5]    user  [#c0caf5]$user[/#c0caf5]\n\n"
                "  [dim]Install to deploy Ctrl+X s fzf snippet picker to the remote shell.[/dim]",
                **common,
            )
        self.query_one("#bs-status", Static).update(body)
        self.query_one("#bs-output", Static).update("")

    def _show_result(self, code: int, out: str, ok: str, failed: str) -> None:
        msg = plain(out).strip() or (ok if code == 0 else failed)
        color = "#9ece6a" if code == 0 else "#f7768e"
        self.query_one("#bs-output", Static).update(m(f"[{color}]$msg[/{color}]", msg=msg))
        self.notify(msg.splitlines()[-1] if msg else msg,
                    severity="information" if code == 0 else "error", markup=False)

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
        with self.app.suspend():
            engine.bootstrap_install(self._alias.name)
        self._refresh_status()
        if self._installed:
            self.notify(f"Bootstrap installed on {self._alias.name}", markup=False)
        else:
            self.notify(f"Bootstrap was not installed on {self._alias.name}",
                        severity="warning", markup=False)

    @work(thread=True)
    def action_update(self) -> None:
        out_widget = self.query_one("#bs-output", Static)
        self.app.call_from_thread(out_widget.update, "[dim]Syncing snippets…[/dim]")
        code, out = engine.bootstrap_update(self._alias.name)
        self.app.call_from_thread(self._show_result, code, out, "Snippets synced.", "Sync failed.")

    def action_connect_profile(self) -> None:
        with self.app.suspend():
            engine.connect_with_profile(self._alias.name)

    def action_remove(self) -> None:
        from sshop.modals import ConfirmModal
        self.app.push_screen(
            ConfirmModal(m("Remove the snippet widget from [bold]$a[/bold]?", a=self._alias.name),
                         confirm_label="Remove"),
            callback=lambda ok: self._do_remove() if ok else None,
        )

    @work(thread=True)
    def _do_remove(self) -> None:
        out_widget = self.query_one("#bs-output", Static)
        self.app.call_from_thread(out_widget.update, "[dim]Removing bootstrap profile…[/dim]")
        code, out = engine.bootstrap_remove(self._alias.name)
        if code == 0:
            self.app.call_from_thread(self._refresh_status)   # (clears the output pane)
        self.app.call_from_thread(self._show_result, code, out, "Removed.", "Remove failed.")
