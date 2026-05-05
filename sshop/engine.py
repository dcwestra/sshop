"""Wraps the okssh CLI for all mutation operations."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

OKSSH_BIN = shutil.which("okssh") or "/usr/local/bin/okssh"

# Force CLI mode so okssh never tries to open whiptail dialogs
_CLI_ENV = {**os.environ, "HAS_WHIPTAIL": "0"}


def run(args: list[str], input_text: str | None = None) -> tuple[int, str, str]:
    """Run a okssh subcommand synchronously. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        [OKSSH_BIN, *args],
        capture_output=True,
        text=True,
        input=input_text,
        env=_CLI_ENV,
    )
    return result.returncode, result.stdout, result.stderr


async def run_async(args: list[str]) -> tuple[int, str, str]:
    """Async variant for non-blocking calls from Textual workers."""
    proc = await asyncio.create_subprocess_exec(
        OKSSH_BIN,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_CLI_ENV,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def probe_alias(hostname: str, port: int = 22, timeout: int = 5) -> tuple[bool, int | None]:
    """TCP connect probe to SSH port. Returns (reachable, latency_ms).
    Much faster than a full SSH handshake — measures network latency only."""
    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port),
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, elapsed_ms
    except Exception:
        return False, None


def connect(alias: str) -> None:
    """
    Hand the terminal to okssh connect. Called from within app.suspend() context.
    Blocks until the SSH session ends.
    """
    subprocess.run([OKSSH_BIN, "connect", alias])


def remove_alias(alias: str) -> tuple[int, str]:
    # pipe "y" to answer okssh's confirmation prompt
    code, out, err = run(["rm", alias], input_text="y\n")
    return code, err or out


def wake(alias: str) -> tuple[int, str]:
    code, out, err = run(["wake", alias])
    return code, err or out


def tunnel_start(name: str) -> tuple[int, str]:
    code, out, err = run(["tunnel", "start", name])
    return code, err or out


def tunnel_stop(name: str) -> tuple[int, str]:
    code, out, err = run(["tunnel", "stop", name])
    return code, err or out


def tunnel_remove(name: str) -> tuple[int, str]:
    code, out, err = run(["tunnel", "rm", name])
    return code, err or out


def snip_run(name: str, alias: str, parallel: bool = False) -> tuple[int, str]:
    args = ["snip", "run", name, alias]
    if parallel:
        args.append("--parallel")
    code, out, err = run(args)
    return code, out + err


def open_sftp(alias: str) -> None:
    """Open SFTP session — blocks until closed."""
    subprocess.run([OKSSH_BIN, "open", alias])


def rotate_key(alias: str) -> None:
    """Interactive key rotation — blocks."""
    subprocess.run([OKSSH_BIN, "rotate", alias])


def run_remote(alias: str, cmd: str) -> tuple[int, str]:
    code, out, err = run(["run", alias, cmd])
    return code, out + err


def rename_alias(old: str, new: str) -> tuple[int, str]:
    code, out, err = run(["rename", old, new])
    return code, err or out


def clone_alias(src: str, dest: str) -> None:
    """Interactive clone wizard — blocks."""
    subprocess.run([OKSSH_BIN, "clone", src, dest])


def pin_alias(alias: str) -> tuple[int, str]:
    code, out, err = run(["pin", alias])
    return code, err or out


def unpin_alias(alias: str) -> tuple[int, str]:
    code, out, err = run(["unpin", alias])
    return code, err or out


def audit() -> tuple[int, str]:
    code, out, err = run(["audit"])
    return code, out + err


def export_aliases(fmt: str = "") -> tuple[int, str]:
    args = ["export"] + ([f"--{fmt}"] if fmt else [])
    code, out, err = run(args)
    return code, out + err


def agent_list() -> tuple[int, str]:
    code, out, err = run(["agent", "list"])
    return code, out + err


def agent_add(alias: str) -> tuple[int, str]:
    code, out, err = run(["agent", "add", alias])
    return code, err or out


def agent_rm(alias: str) -> tuple[int, str]:
    code, out, err = run(["agent", "rm", alias])
    return code, err or out


def agent_clear() -> tuple[int, str]:
    code, out, err = run(["agent", "clear"])
    return code, err or out


def backup_list() -> tuple[int, str]:
    code, out, err = run(["backup"])
    return code, out + err


def backup_restore(n: int) -> tuple[int, str]:
    code, out, err = run(["backup", "restore", str(n)], input_text="y\n")
    return code, err or out


def tag_alias(alias: str, group: str) -> tuple[int, str]:
    code, out, err = run(["tag", alias, group])
    return code, err or out


def untag_alias(alias: str, group: str) -> tuple[int, str]:
    code, out, err = run(["untag", alias, group])
    return code, err or out


def connect_with_profile(alias: str) -> None:
    """Connect with ephemeral profile — blocks, call inside app.suspend()."""
    subprocess.run([OKSSH_BIN, "connect", "--profile", alias])


def diff() -> tuple[int, str]:
    code, out, err = run(["diff"])
    return code, out + err


def template_list() -> tuple[int, str]:
    code, out, err = run(["template", "list"])
    return code, out + err


def template_remove(name: str) -> tuple[int, str]:
    code, out, err = run(["template", "rm", name])
    return code, err or out


def bootstrap_install(alias: str) -> None:
    """Run okssh bootstrap <alias> — interactive, blocks."""
    subprocess.run([OKSSH_BIN, "bootstrap", alias])


def bootstrap_update(alias: str) -> tuple[int, str]:
    code, out, err = run(["bootstrap", "update", alias])
    return code, out + err


def bootstrap_remove(alias: str) -> tuple[int, str]:
    code, out, err = run(["bootstrap", "remove", alias])
    return code, err or out


def bootstrap_list() -> tuple[int, str]:
    code, out, err = run(["bootstrap", "list"])
    return code, out + err
