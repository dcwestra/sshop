"""Wraps the okssh CLI for all mutation operations."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from sshop.markup import plain


def _find_okssh() -> str:
    # ~/.local/bin is where okssh is usually installed, but it isn't on PATH
    # when sshop is started from a desktop launcher
    found = shutil.which("okssh")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "okssh"
    return str(local) if local.exists() else "/usr/local/bin/okssh"


OKSSH_BIN = _find_okssh()

# Force CLI mode so okssh never tries to open whiptail dialogs
_CLI_ENV = {**os.environ, "HAS_WHIPTAIL": "0"}


def run(
    args: list[str],
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
    color: bool = False,
) -> tuple[int, str, str]:
    """Run a okssh subcommand synchronously. Returns (returncode, stdout, stderr).

    Captured calls never touch sshop's terminal: stdin is /dev/null unless
    input_text is given, and the child gets its own session so ssh can't
    open /dev/tty either. An unexpected prompt then fails fast instead of
    blocking forever on the raw-mode tty Textual owns.

    okssh prints plain text when captured; color=True asks it for ANSI
    colours anyway (for output popups, which render ANSI).
    """
    env = {**_CLI_ENV, **(extra_env or {})}
    if color:
        env["CLICOLOR_FORCE"] = "1"
    stdin_kw = ({"input": input_text} if input_text is not None
                else {"stdin": subprocess.DEVNULL})
    result = subprocess.run(
        [OKSSH_BIN, *args],
        capture_output=True,
        text=True,
        env=env,
        start_new_session=True,
        **stdin_kw,
    )
    return result.returncode, result.stdout, result.stderr


async def run_async(args: list[str]) -> tuple[int, str, str]:
    """Async variant for non-blocking calls from Textual workers (same
    terminal isolation as run())."""
    proc = await asyncio.create_subprocess_exec(
        OKSSH_BIN,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_CLI_ENV,
        start_new_session=True,
    )
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        # a cancelled worker (exclusive re-probe, screen closed) must not
        # leave okssh and its parallel ssh probes running — they share the
        # process group start_new_session created
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        # reap it now — an unawaited child lingers as a zombie and its
        # transport warns when collected after the loop is gone
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError, ProcessLookupError):
            pass
        raise
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def status_json() -> list[dict] | None:
    """Full-SSH reachability for all aliases via `okssh status --json`.

    Returns a list of {alias, host, reachable, latency_ms, last_connect}
    dicts, or None if the installed okssh doesn't support --json / output
    isn't parseable (callers fall back to TCP probes).
    """
    code, out, _err = await run_async(["status", "--json"])
    if code != 0:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


async def probe_alias(hostname: str, port: int = 22, timeout: int = 5) -> tuple[bool, int | None]:
    """TCP connect probe to SSH port. Returns (reachable, latency_ms).
    Fallback when `okssh status --json` is unavailable — measures network
    latency only, can't detect auth failures."""
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
    subprocess.run([OKSSH_BIN, "connect", alias], env=_CLI_ENV)


def remove_alias(alias: str, delete_keys: bool = False) -> tuple[int, str]:
    """Remove an alias non-interactively; optionally delete its key pair."""
    args = ["rm", alias, "--yes", "--keys" if delete_keys else "--keep-keys"]
    code, out, err = run(args)
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
    # okssh prompts before removing — without piped stdin it would read from
    # sshop's tty and hang the UI
    code, out, err = run(["tunnel", "rm", name], input_text="y\n")
    return code, err or out


def rotate_key(alias: str) -> None:
    """Interactive key rotation — blocks."""
    subprocess.run([OKSSH_BIN, "rotate", alias], env=_CLI_ENV)


def run_remote(alias: str, cmd: str) -> tuple[int, str]:
    code, out, err = run(["run", alias, cmd], color=True)
    return code, out + err


def rename_alias(old: str, new: str) -> tuple[int, str]:
    code, out, err = run(["rename", old, new])
    return code, err or out


def clone_alias(src: str, dest: str) -> None:
    """Interactive clone wizard — blocks."""
    subprocess.run([OKSSH_BIN, "clone", src, dest], env=_CLI_ENV)


def pin_alias(alias: str) -> tuple[int, str]:
    code, out, err = run(["pin", alias])
    return code, err or out


def unpin_alias(alias: str) -> tuple[int, str]:
    code, out, err = run(["unpin", alias])
    return code, err or out


def audit() -> tuple[int, str]:
    code, out, err = run(["audit"], color=True)
    return code, out + err


def export_aliases(ansible: bool = False) -> tuple[int, str]:
    """Export content on stdout: okssh's portable [alias] format, or an
    Ansible INI inventory. Returns (code, content-or-error)."""
    args = ["export", "--ansible", "-"] if ansible else ["export", "-"]
    code, out, err = run(args)
    return code, out if code == 0 else (err or out)


def agent_list() -> tuple[int, str]:
    code, out, err = run(["agent", "list"])
    return code, out + err


def parse_agent_list(raw: str, aliases: list[str]) -> set[str]:
    """Aliases marked loaded in `okssh agent list` ("<alias>  yes|no  <keyfile>").
    Compares whole first columns so "web" doesn't light up for "web2";
    ANSI is stripped in case okssh coloured its output."""
    wanted = set(aliases)
    loaded: set[str] = set()
    for line in plain(raw).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in wanted and parts[1] == "yes":
            loaded.add(parts[0])
    return loaded


def agent_add(alias: str) -> tuple[int, str]:
    code, out, err = run(["agent", "add", alias])
    return code, err or out


def agent_rm(alias: str) -> tuple[int, str]:
    code, out, err = run(["agent", "rm", alias])
    return code, err or out


def agent_clear() -> tuple[int, str]:
    # okssh prompts before clearing — pipe the confirmation (see tunnel_remove)
    code, out, err = run(["agent", "clear"], input_text="y\n")
    return code, err or out


def backup_list() -> tuple[int, str]:
    code, out, err = run(["backup"])
    return code, out + err


_BACKUP_ROW = re.compile(r"^\s*(\d+)\)\s+(.+)$")


def parse_backup_list(raw: str) -> list[tuple[str, str]]:
    """[(number, "timestamp  (N bytes)")] from `okssh backup` output."""
    rows = []
    for line in plain(raw).splitlines():
        mt = _BACKUP_ROW.match(line)
        if mt:
            rows.append((mt.group(1), mt.group(2).strip()))
    return rows


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
    subprocess.run([OKSSH_BIN, "connect", "--profile", alias], env=_CLI_ENV)


def diff() -> tuple[int, str]:
    code, out, err = run(["diff"], color=True)
    return code, out + err


def template_remove(name: str) -> tuple[int, str]:
    code, out, err = run(["template", "rm", name])
    return code, err or out


def bootstrap_install(alias: str) -> None:
    """Run okssh bootstrap <alias> — interactive, blocks."""
    subprocess.run([OKSSH_BIN, "bootstrap", alias], env=_CLI_ENV)


def bootstrap_update(alias: str) -> tuple[int, str]:
    code, out, err = run(["bootstrap", "update", alias])
    return code, out + err


def bootstrap_remove(alias: str) -> tuple[int, str]:
    code, out, err = run(["bootstrap", "remove", alias])
    return code, err or out


def add_alias(
    alias: str,
    host: str,
    user: str,
    port: int = 22,
    key_type: str = "ed25519",
    password: str = "",
    key_file: str = "",
    note: str = "",
    group: str = "",
    jump: str = "",
) -> tuple[int, str]:
    """Add a new alias non-interactively.

    Pass key_file to import an existing key (skip keygen + ssh-copy-id).
    Otherwise key_type + password are used to generate a new key.

    The password travels via the OKSSH_PASSWORD env var ("@env" sentinel
    in argv) so it never shows up in the process list.
    """
    key_spec = f"import:{key_file}" if key_file else key_type
    extra_env = {"OKSSH_PASSWORD": password} if password else None
    pass_arg = "@env" if password else ""
    args = ["add", alias, host, user, str(port), key_spec, pass_arg,
            note, group, jump]
    code, out, err = run(args, extra_env=extra_env)
    return code, err or out


def import_key(
    alias: str,
    key_file: str,
    host: str,
    user: str,
    port: int = 22,
    note: str = "",
    group: str = "",
    jump: str = "",
) -> tuple[int, str]:
    """Register an existing private key non-interactively."""
    args = ["import-key", alias, key_file, host, user, str(port), note, group, jump]
    code, out, err = run(args)
    return code, err or out


def tunnel_add() -> None:
    """Interactive tunnel wizard — blocks, call inside app.suspend()."""
    subprocess.run([OKSSH_BIN, "tunnel", "add"], env=_CLI_ENV)


def snip_add() -> None:
    """Interactive snippet add wizard — blocks, call inside app.suspend()."""
    subprocess.run([OKSSH_BIN, "snip", "add"], env=_CLI_ENV)


def snip_edit(name: str) -> None:
    """Interactive snippet edit wizard — blocks, call inside app.suspend()."""
    subprocess.run([OKSSH_BIN, "snip", "edit", name], env=_CLI_ENV)


def snip_delete(name: str) -> tuple[int, str]:
    code, out, err = run(["snip", "rm", name], input_text="y\n")
    return code, err or out


def snip_run_targets(name: str, targets: list[str], parallel: bool = False) -> None:
    """Run a snippet on specific hosts — interactive, call inside app.suspend()."""
    args = [OKSSH_BIN, "snip", "run", name] + targets
    if parallel:
        args.append("--parallel")
    subprocess.run(args, env=_CLI_ENV)


def snip_push(targets: list[str]) -> None:
    """Push snippets to bootstrapped hosts — interactive, call inside app.suspend()."""
    subprocess.run([OKSSH_BIN, "snip", "push"] + targets, env=_CLI_ENV)


def snip_run_group(name: str, group: str) -> None:
    """Run a snippet on all aliases in a group — interactive, call inside app.suspend()."""
    subprocess.run([OKSSH_BIN, "snip", "run", name, "--group", group], env=_CLI_ENV)
