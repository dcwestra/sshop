"""Reads okssh config files directly — no subprocess needed for display data."""

from __future__ import annotations

import configparser
import re
import time
from dataclasses import dataclass
from pathlib import Path

SSH_CONFIG = Path.home() / ".ssh" / "config"
OKSSH_DIR = Path.home() / ".config" / "okssh"
PREFS_FILE = OKSSH_DIR / "preferences"
SNIPPETS_FILE = OKSSH_DIR / "snippets"
TUNNELS_FILE = OKSSH_DIR / "tunnels"
HISTORY_LOG = OKSSH_DIR / "history.log"
TEMPLATES_FILE = OKSSH_DIR / "templates"


@dataclass
class Alias:
    name: str
    hostname: str = ""
    user: str = ""
    port: str = "22"
    identity_file: str = ""
    proxy_jump: str = ""
    note: str = ""
    group: str = ""
    server_alive_interval: str = ""
    # populated from preferences
    last_connect: str = ""
    pinned: bool = False
    wol_mac: str = ""          # okssh stores it as pref wol_mac_<alias>
    # populated at runtime
    key_type: str = ""   # ed25519 / rsa / ecdsa
    key_age_days: int | None = None
    audit_threshold: int | None = None   # None = use global
    agent_loaded: bool = False
    latency_ms: int | None = None
    reachable: bool | None = None


@dataclass
class Tunnel:
    name: str
    alias: str = ""
    forward_spec: str = ""
    tunnel_type: str = "local"   # local / remote / socks


@dataclass
class Snippet:
    name: str
    command: str = ""
    description: str = ""
    use_sudo: str = ""


def _parse_ssh_config() -> list[Alias]:
    """Parse ~/.ssh/config into Alias objects. Handles multi-line blocks."""
    if not SSH_CONFIG.exists():
        return []

    aliases: list[Alias] = []
    current: dict[str, str] = {}
    current_name: str | None = None

    def flush():
        nonlocal current, current_name
        if current_name and current_name != "*":
            a = Alias(name=current_name)
            a.hostname = current.get("hostname", "")
            a.user = current.get("user", "")
            a.port = current.get("port", "22")
            a.identity_file = current.get("identityfile", "")
            a.proxy_jump = current.get("proxyjump", "")
            a.server_alive_interval = current.get("serveraliveinterval", "")
            # extract metadata from comments stored alongside this block
            a.note = current.get("_note", "")
            a.group = current.get("_group", "")
            a.key_type = _key_type_from_path(a.identity_file)
            aliases.append(a)
        current = {}
        current_name = None

    with SSH_CONFIG.open() as fh:
        for line in fh:
            stripped = line.strip()

            # metadata comments are INSIDE the Host block (after the Host line)
            if current_name is not None and stripped.startswith("#"):
                m = re.match(r"^#\s*Note:\s*(.+)", stripped)
                if m:
                    current["_note"] = m.group(1)
                    continue
                m = re.match(r"^#\s*Group:\s*(.+)", stripped)
                if m:
                    current["_group"] = m.group(1)
                    continue

            if stripped.startswith("#") or not stripped:
                continue

            m = re.match(r"^Host\s+(.+)", stripped, re.IGNORECASE)
            if m:
                flush()
                current_name = m.group(1).strip()
                continue
            if re.match(r"^Match\s", stripped, re.IGNORECASE):
                flush()        # a Match block's options belong to no alias
                continue

            # "Key value", "Key=value" and "Key = value" are all valid
            m = re.match(r"^(\w+)\s*(?:=\s*|\s+)(.+)", stripped)
            if m and current_name is not None:
                current.setdefault(m.group(1).lower(), m.group(2).strip())   # first wins, like ssh

    flush()
    return aliases


def _parse_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    if path.exists():
        cp.read(path)
    return cp


def _parse_preferences() -> dict[str, str]:
    prefs: dict[str, str] = {}
    if not PREFS_FILE.exists():
        return prefs
    with PREFS_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                prefs[k.strip()] = v.strip()
    return prefs


def _key_type_from_path(path: str) -> str:
    p = path.lower()
    if "ed25519" in p:
        return "ed25519"
    if "ecdsa" in p or "_ec_" in p:
        return "ecdsa"
    if "rsa" in p:
        return "rsa"
    return ""


def _key_age_days(identity_file: str) -> int | None:
    """Return age of key file in days, or None if unavailable."""
    if not identity_file:
        return None
    path = Path(identity_file).expanduser()
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        return int((time.time() - mtime) / 86400)
    except OSError:
        return None


def load_audit_threshold(prefs: dict[str, str] | None = None) -> int | None:
    """Return global audit threshold in days, or None if auditing is disabled."""
    if prefs is None:
        prefs = _parse_preferences()
    raw = prefs.get("audit_threshold", "")
    if not raw:
        return 90
    if raw in ("off", "never", "disabled", "disable"):
        return None
    try:
        return int(raw)
    except ValueError:
        return 90


_UNSET = object()


def effective_threshold(alias: Alias, global_threshold=_UNSET) -> int | None:
    """Return effective audit threshold for this alias, or None if auditing is
    disabled. Pass global_threshold (from load_audit_threshold) when calling
    per row — otherwise every call re-reads the preferences file."""
    if alias.audit_threshold == 0:   # sentinel: per-host disabled
        return None
    if alias.audit_threshold is not None:
        return alias.audit_threshold
    if global_threshold is _UNSET:
        return load_audit_threshold()
    return global_threshold


def is_hidden(alias: Alias) -> bool:
    """In okssh's reserved "hidden" group (filtered from listings)."""
    return any(g.strip().lower() == "hidden" for g in alias.group.split(",") if g.strip())


def load_aliases(show_hidden: bool = False) -> list[Alias]:
    aliases = _parse_ssh_config()
    prefs = _parse_preferences()
    pinned_raw = prefs.get("pinned_aliases", "")
    pinned_set = {a.strip() for a in pinned_raw.split(",") if a.strip()}

    for a in aliases:
        a.last_connect = prefs.get(f"last_connect_{a.name}", "")
        a.pinned = a.name in pinned_set
        a.wol_mac = prefs.get(f"wol_mac_{a.name}", "")
        a.key_age_days = _key_age_days(a.identity_file)
        raw = prefs.get(f"audit_threshold_{a.name}", "")
        if raw in ("off", "never", "disabled", "disable"):
            a.audit_threshold = 0   # sentinel: per-host disabled
        elif raw:
            try:
                a.audit_threshold = int(raw)
            except ValueError:
                a.audit_threshold = None
        else:
            a.audit_threshold = None

    if not show_hidden:
        aliases = [a for a in aliases if not is_hidden(a)]

    # pinned first, then original config order
    aliases.sort(key=lambda a: (0 if a.pinned else 1))
    return aliases


def _parse_named_blocks(path: Path, header: str) -> list[dict[str, str]]:
    """Parse okssh-style repeated blocks: every block starts with the SAME
    section header (e.g. [tunnel]) and identifies itself via a name= field.
    configparser can't handle duplicate section names, so parse by hand."""
    blocks: list[dict[str, str]] = []
    if not path.exists():
        return blocks
    current: dict[str, str] | None = None
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line == f"[{header}]":
                if current and current.get("name"):
                    blocks.append(current)
                current = {}
                continue
            if current is not None and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                current[k.strip()] = v.strip()
    if current and current.get("name"):
        blocks.append(current)
    return blocks


TUNNEL_SOCK_DIR = OKSSH_DIR / "tunnel-socks"


def tunnel_running(name: str) -> bool:
    """True if the tunnel's SSH control socket exists (approximation of
    `okssh tunnel status` without spawning a subprocess per tunnel)."""
    return (TUNNEL_SOCK_DIR / f"{name}.sock").is_socket()


def load_tunnels() -> list[Tunnel]:
    tunnels = []
    for block in _parse_named_blocks(TUNNELS_FILE, "tunnel"):
        tunnels.append(Tunnel(
            name=block["name"],
            alias=block.get("alias", ""),
            forward_spec=block.get("forward", ""),
            tunnel_type=block.get("type", "local"),
        ))
    return tunnels


def load_snippets() -> list[Snippet]:
    cp = _parse_ini(SNIPPETS_FILE)
    snippets = []
    for section in cp.sections():
        s = Snippet(name=section)
        s.command = cp.get(section, "command", fallback="")
        s.description = cp.get(section, "description", fallback="")
        s.use_sudo = cp.get(section, "use_sudo", fallback="")
        snippets.append(s)
    return snippets


@dataclass
class Template:
    name: str
    user: str = ""
    port: str = ""
    group: str = ""
    key_type: str = ""
    note: str = ""
    server_alive_interval: str = ""


def load_templates() -> list[Template]:
    templates = []
    for block in _parse_named_blocks(TEMPLATES_FILE, "template"):
        templates.append(Template(
            name=block["name"],
            user=block.get("user", ""),
            port=block.get("port", ""),
            group=block.get("group", ""),
            key_type=block.get("key_type", ""),
            note=block.get("note", ""),
            server_alive_interval=block.get("alive", ""),
        ))
    return templates


def keysync_stale() -> bool:
    """True when okssh changed keys without a terminal to ask for the
    key-sync passphrase (e.g. an add from sshop), so keys.enc is outdated."""
    return bool(_parse_preferences().get("keys_sync_stale"))


def load_bootstrapped_aliases() -> list[str]:
    """Return alias names that have the snippet widget installed."""
    prefs = _parse_preferences()
    result = []
    for a in _parse_ssh_config():
        if prefs.get(f"bootstrap_{a.name}", ""):
            result.append(a.name)
    return result


def counts() -> tuple[int, int, int]:
    """(visible aliases, tunnels, snippets) for the StatsHeader."""
    return len(load_aliases()), len(load_tunnels()), len(load_snippets())


def files_snapshot() -> tuple:
    """Mtime fingerprint of every file sshop displays. Screens poll this to
    notice changes made outside sshop (okssh CLI, another terminal, sync)."""
    paths = (SSH_CONFIG, PREFS_FILE, SNIPPETS_FILE, TUNNELS_FILE,
             TEMPLATES_FILE, HISTORY_LOG)
    snap = []
    for p in paths:
        try:
            snap.append(p.stat().st_mtime_ns)
        except OSError:
            snap.append(0)
    return tuple(snap)


def load_history(alias_filter: str | None = None) -> list[dict[str, str]]:
    """Returns list of {timestamp, alias, duration, exit_code} dicts.
    okssh writes history.log as pipe-separated: timestamp|alias|duration|exit.
    alias_filter is a case-insensitive substring match."""
    entries = []
    if not HISTORY_LOG.exists():
        return entries
    with HISTORY_LOG.open() as fh:
        for line in fh:
            parts = line.strip().split("|")
            if len(parts) < 4:
                continue
            entry = {
                "timestamp": parts[0],
                "alias": parts[1],
                "duration": parts[2],
                "exit_code": parts[3],
            }
            if alias_filter and alias_filter.lower() not in entry["alias"].lower():
                continue
            entries.append(entry)
    return list(reversed(entries))
