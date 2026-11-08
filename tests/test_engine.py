"""Tests for engine: status_json parsing, okssh output parsers, and the
subprocess isolation every captured okssh call relies on."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time

import pytest

from sshop import engine


def _fake_run_async(code: int, out: str):
    async def fake(args):
        assert args == ["status", "--json"]
        return code, out, ""
    return fake


def test_status_json_parses(monkeypatch):
    payload = (
        '[\n'
        '  {"alias":"web1","host":"192.0.2.10","reachable":true,'
        '"latency_ms":142,"last_connect":"2026-07-01 10:00"},\n'
        '  {"alias":"dead","host":"192.0.2.99","reachable":false,'
        '"latency_ms":null,"last_connect":""}\n'
        ']\n'
    )
    monkeypatch.setattr(engine, "run_async", _fake_run_async(0, payload))
    data = asyncio.run(engine.status_json())
    assert data is not None and len(data) == 2
    assert data[0]["reachable"] is True and data[0]["latency_ms"] == 142
    assert data[1]["reachable"] is False and data[1]["latency_ms"] is None


def test_status_json_empty(monkeypatch):
    monkeypatch.setattr(engine, "run_async", _fake_run_async(0, "[]\n"))
    assert asyncio.run(engine.status_json()) == []


@pytest.mark.parametrize("code,out", [
    (1, ""),                                  # old okssh: unknown flag → die
    (0, "Error: something\n"),                # non-JSON output
    (0, '{"not": "a list"}'),                 # wrong shape
])
def test_status_json_falls_back_to_none(monkeypatch, code, out):
    monkeypatch.setattr(engine, "run_async", _fake_run_async(code, out))
    assert asyncio.run(engine.status_json()) is None


# ── okssh output parsers (exact formats okssh prints, plain and coloured) ──────

AGENT_PLAIN = (
    "\n  ALIAS              LOADED   KEY FILE\n  ────────────\n"
    "  web                 yes     id_ed25519_web\n"
    "  web2                no      id_ed25519_web2\n"
)
# what okssh < 3.11 printed when captured — colour codes glued to the fields
AGENT_ANSI = ("  \x1b[1mweb               \x1b[0m  \x1b[0;32myes\x1b[0m     id_ed25519_web\n"
              "  \x1b[1mweb2              \x1b[0m  \x1b[2mno\x1b[0m      id_ed25519_web2\n")


@pytest.mark.parametrize("raw", [AGENT_PLAIN, AGENT_ANSI])
def test_parse_agent_list(raw):
    assert engine.parse_agent_list(raw, ["web", "web2", "db"]) == {"web"}


BACKUP_PLAIN = ("\n  SSH config backups  (most recent first)\n\n"
                "   1)  20261108-081442  (345 bytes)\n"
                "   2)  20261107-120000-2  (300 bytes)\n\n"
                "  Restore with: okssh backup restore <N>\n")
BACKUP_ANSI = "  \x1b[1m 1)\x1b[0m  20261108-081442  \x1b[2m(345 bytes)\x1b[0m\n"


def test_parse_backup_list():
    assert engine.parse_backup_list(BACKUP_PLAIN) == [
        ("1", "20261108-081442  (345 bytes)"),
        ("2", "20261107-120000-2  (300 bytes)"),
    ]
    assert engine.parse_backup_list(BACKUP_ANSI) == [("1", "20261108-081442  (345 bytes)")]
    assert engine.parse_backup_list("\n  No backups found in /x\n\n") == []


# ── subprocess isolation (a fake okssh that reports what it saw) ───────────────

FAKE = """#!{py}
import json, os, sys
data = sys.stdin.read()
print(json.dumps({{
    "args": sys.argv[1:],
    "stdin_tty": os.isatty(0),
    "stdin": data,
    "own_session": os.getsid(0) == os.getpid(),
    "color": os.environ.get("CLICOLOR_FORCE"),
    "whiptail": os.environ.get("HAS_WHIPTAIL"),
    "secret": os.environ.get("OKSSH_PASSWORD"),
}}))
"""


@pytest.fixture
def fake_okssh(tmp_path, monkeypatch):
    path = tmp_path / "okssh"
    path.write_text(FAKE.format(py=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(engine, "OKSSH_BIN", str(path))
    return path


def _seen(out: str) -> dict:
    return json.loads(out)


def test_run_never_shares_the_terminal(fake_okssh):
    code, out, _ = engine.run(["status"])
    seen = _seen(out)
    assert code == 0
    assert seen["stdin_tty"] is False and seen["stdin"] == ""   # /dev/null → immediate EOF
    assert seen["own_session"] is True                          # can't open sshop's /dev/tty
    assert seen["whiptail"] == "0"
    assert seen["color"] is None


def test_run_input_and_color(fake_okssh):
    _, out, _ = engine.run(["snip", "rm", "x"], input_text="y\n", color=True)
    seen = _seen(out)
    assert seen["stdin"] == "y\n" and seen["color"] == "1"


def test_add_alias_password_only_via_env(fake_okssh):
    code, msg = engine.add_alias("web", "192.0.2.1", "root", password="hunter2")
    seen = _seen(msg)
    assert "hunter2" not in seen["args"] and "@env" in seen["args"]
    assert seen["secret"] == "hunter2"


def test_export_args(fake_okssh):
    _, out = engine.export_aliases()
    assert _seen(out)["args"] == ["export", "-"]
    _, out = engine.export_aliases(ansible=True)
    assert _seen(out)["args"] == ["export", "--ansible", "-"]


def test_run_async_isolated(fake_okssh):
    code, out, _ = asyncio.run(engine.run_async(["status", "--json"]))
    seen = _seen(out)
    assert seen["stdin_tty"] is False and seen["own_session"] is True


def test_run_async_cancel_kills_process_group(tmp_path, monkeypatch):
    # okssh status --json spawns ssh children; cancelling the worker must not
    # leave them running
    marker = tmp_path / "child.pid"
    script = tmp_path / "okssh"
    script.write_text(f"#!/bin/sh\nsleep 30 &\necho $! > {marker}\nwait\n")
    script.chmod(0o755)
    monkeypatch.setattr(engine, "OKSSH_BIN", str(script))

    async def go():
        task = asyncio.create_task(engine.run_async(["status", "--json"]))
        for _ in range(50):
            if marker.exists() and marker.read_text().strip():
                break
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    child = int(marker.read_text())
    for _ in range(40):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    os.kill(child, 9)
    pytest.fail("grandchild still running after cancel")
