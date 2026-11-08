"""Textual pilot tests for UI behaviour that broke before (headless, no okssh)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from textual.widgets import DataTable, Static
from textual.widgets.data_table import ColumnKey
from textual.containers import VerticalScroll

from sshop import config, engine

KEY_PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFakeFake test"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed config files + an engine that never shells out."""
    for name, rel in [("SSH_CONFIG", "ssh_config"), ("PREFS_FILE", "preferences"),
                      ("SNIPPETS_FILE", "snippets"), ("TUNNELS_FILE", "tunnels"),
                      ("HISTORY_LOG", "history.log"), ("TEMPLATES_FILE", "templates"),
                      ("TUNNEL_SOCK_DIR", "tunnel-socks")]:
        monkeypatch.setattr(config, name, tmp_path / rel)
    key = tmp_path / "id_ed25519_web"
    key.write_text("k")
    (tmp_path / "id_ed25519_web.pub").write_text(KEY_PUB)
    (tmp_path / "ssh_config").write_text(
        "Host web\n"
        "    # Note: [/etc/hosts] mirror\n"
        "    # Group: prod\n"
        "    HostName 192.0.2.10\n"
        "    User deploy\n"
        f"    IdentityFile {key}\n"
        + "".join(f"\nHost h{i}\n    HostName 192.0.2.{i}\n" for i in range(20, 26))
    )
    (tmp_path / "snippets").write_text(
        "[grepper]\ndescription=find [things]\n"
        "command=grep [a-z] log && sed 's/[/]/x/' f\nuse_sudo=no\ncreated=x\n\n")
    (tmp_path / "history.log").write_text("2026-07-01 10:00|web|5|0\n")

    async def no_status():
        return []
    monkeypatch.setattr(engine, "status_json", no_status)
    monkeypatch.setattr(engine, "OKSSH_BIN", "/nonexistent/okssh")
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def _plain(widget: Static) -> str:
    return str(widget.render())


def test_hostile_text_renders_literally(home):
    from sshop.app import SshopApp

    async def go():
        app = SshopApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            detail = app.screen.query_one("#detail-panel", Static)
            assert "[/etc/hosts] mirror" in _plain(detail)          # used to crash
            table = app.screen.query_one("#alias-table", DataTable)
            row = table.get_row_at(0)
            assert row[4].plain == "[ed]"                           # TYPE badge used to vanish
            assert row[8].plain == "[/etc/hosts] mirror"
            await pilot.press("s")
            await pilot.pause()
            snip = _plain(app.screen.query_one("#snip-detail", Static))
            assert "grep [a-z] log && sed 's/[/]/x/' f" in snip
            assert "find [things]" in snip
    run(go())


def test_help_renders_markup_and_scrolls(home):
    from sshop.app import SshopApp
    from sshop.modals import OutputModal

    async def go():
        app = SshopApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, OutputModal)
            text = _plain(app.screen.query_one("#output", Static))
            assert text.startswith("Alias actions") and "[bold]" not in text
            scroll = app.screen.query_one("#output-scroll", VerticalScroll)
            assert scroll.max_scroll_y > 0                      # long help is reachable
            await pilot.press("end")
            await pilot.pause()
            assert scroll.scroll_y > 0
            await pilot.press("escape")
    run(go())


def test_sort_indicator_and_filter_without_disk_io(home, monkeypatch):
    from sshop.app import SshopApp
    from sshop.screens import home as home_mod

    async def go():
        app = SshopApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            scr = app.screen
            table = scr.query_one("#alias-table", DataTable)
            scr.on_data_table_header_selected(SimpleNamespace(column_key=ColumnKey("ALIAS")))
            await pilot.pause()
            assert str(table.columns[ColumnKey("ALIAS")].label) == "ALIAS ▲"
            scr.on_data_table_header_selected(SimpleNamespace(column_key=ColumnKey("ALIAS")))
            await pilot.pause()
            assert str(table.columns[ColumnKey("ALIAS")].label) == "ALIAS ▼"

            calls = {"n": 0}
            real = home_mod.load_aliases

            def counting(*a, **kw):
                calls["n"] += 1
                return real(*a, **kw)
            monkeypatch.setattr(home_mod, "load_aliases", counting)
            await pilot.press("slash", "h", "2", "1")
            await pilot.pause()
            assert table.row_count == 1 and table.get_row_at(0)[1].plain == "h21"
            assert calls["n"] == 0                              # filtering is in memory
    run(go())


def test_log_q_goes_back(home):
    from sshop.app import SshopApp
    from sshop.screens.home import HomeScreen
    from sshop.screens.log import LogScreen

    async def go():
        app = SshopApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, LogScreen)
            await pilot.press("q")                              # used to type into the filter
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
    run(go())


def test_agent_and_backup_screens_parse_okssh_output(home, monkeypatch):
    from sshop.app import SshopApp

    monkeypatch.setattr(engine, "agent_list", lambda: (0, (
        "  \x1b[1mweb               \x1b[0m  \x1b[0;32myes\x1b[0m     id_ed25519_web\n")))
    monkeypatch.setattr(engine, "backup_list", lambda: (0, (
        "   1)  20261108-081442  (345 bytes)\n   2)  20261107-120000  (300 bytes)\n")))

    async def go():
        app = SshopApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("G")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            statuses = {str(table.get_row_at(i)[0]): str(table.get_row_at(i)[1])
                        for i in range(table.row_count)}
            assert "loaded" in statuses["web"] and "not" not in statuses["web"]
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("b")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table.row_count == 2 and str(table.get_row_at(0)[0]) == "1"
    run(go())


def test_run_on_picker_enter_runs_highlighted(home):
    from textual.app import App
    from sshop.screens.snippets import _RunOnModal

    result = {}

    class A(App):
        def on_mount(self):
            self.push_screen(_RunOnModal("grepper", ["h20", "web", "h21"], preselect="web"),
                             callback=lambda r: result.setdefault("r", r))

    async def go():
        app = A()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")                          # used to just toggle
            await pilot.pause()
    run(go())
    assert result["r"] == ["web"]
