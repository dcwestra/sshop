"""Parser tests for sshop.config — the seam between sshop and okssh's files.

Every fixture here mirrors the format okssh actually writes (see
write_config_block, tunnel_write, template_write, snip_write and the
history append in cmd_connect). If okssh changes a format, these fail.
"""

from __future__ import annotations

import pytest

from sshop import config


@pytest.fixture
def okssh_home(tmp_path, monkeypatch):
    """Point every config-file constant at a temp dir; return the dir."""
    monkeypatch.setattr(config, "SSH_CONFIG", tmp_path / "ssh_config")
    monkeypatch.setattr(config, "PREFS_FILE", tmp_path / "preferences")
    monkeypatch.setattr(config, "SNIPPETS_FILE", tmp_path / "snippets")
    monkeypatch.setattr(config, "TUNNELS_FILE", tmp_path / "tunnels")
    monkeypatch.setattr(config, "HISTORY_LOG", tmp_path / "history.log")
    monkeypatch.setattr(config, "TEMPLATES_FILE", tmp_path / "templates")
    monkeypatch.setattr(config, "TUNNEL_SOCK_DIR", tmp_path / "tunnel-socks")
    return tmp_path


# ── ~/.ssh/config ──────────────────────────────────────────────────────────────

SSH_CONFIG_SAMPLE = """\
Host web1
    # Note: primary web box
    # Group: prod,homelab
    # WOL: aa:bb:cc:dd:ee:ff
    HostName 192.0.2.10
    User deploy
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_web1
    ProxyJump bastion
    ServerAliveInterval 60

Host *
    ForwardAgent no

Host db1
    HostName 192.0.2.20
    IdentityFile ~/.ssh/id_rsa_db1

Host secretbox
    # Group: hidden
    HostName 192.0.2.30
"""


def test_parse_ssh_config_fields(okssh_home):
    (okssh_home / "ssh_config").write_text(SSH_CONFIG_SAMPLE)
    aliases = config._parse_ssh_config()
    names = [a.name for a in aliases]
    assert names == ["web1", "db1", "secretbox"]  # Host * excluded

    web1 = aliases[0]
    assert web1.hostname == "192.0.2.10"
    assert web1.user == "deploy"
    assert web1.port == "2222"
    assert web1.note == "primary web box"
    assert web1.group == "prod,homelab"
    assert web1.wol_mac == "aa:bb:cc:dd:ee:ff"
    assert web1.proxy_jump == "bastion"
    assert web1.server_alive_interval == "60"
    assert web1.key_type == "ed25519"

    db1 = aliases[1]
    assert db1.user == ""          # unset field stays empty
    assert db1.port == "22"        # default port
    assert db1.key_type == "rsa"


def test_load_aliases_hidden_and_pinned(okssh_home):
    (okssh_home / "ssh_config").write_text(SSH_CONFIG_SAMPLE)
    (okssh_home / "preferences").write_text(
        "pinned_aliases=db1\nlast_connect_web1=2026-07-01 10:00\n"
    )
    aliases = config.load_aliases()
    assert [a.name for a in aliases] == ["db1", "web1"]  # pinned first, hidden gone
    assert aliases[0].pinned is True
    assert aliases[1].last_connect == "2026-07-01 10:00"

    everything = config.load_aliases(show_hidden=True)
    assert "secretbox" in [a.name for a in everything]


def test_audit_threshold_parsing(okssh_home):
    (okssh_home / "ssh_config").write_text(SSH_CONFIG_SAMPLE)
    (okssh_home / "preferences").write_text(
        "audit_threshold=120\naudit_threshold_web1=off\naudit_threshold_db1=30\n"
    )
    assert config.load_audit_threshold() == 120
    aliases = {a.name: a for a in config.load_aliases()}
    assert config.effective_threshold(aliases["web1"]) is None    # per-host off
    assert config.effective_threshold(aliases["db1"]) == 30       # per-host override


def test_audit_threshold_defaults(okssh_home):
    assert config.load_audit_threshold() == 90       # no prefs file → default
    (okssh_home / "preferences").write_text("audit_threshold=off\n")
    assert config.load_audit_threshold() is None     # globally disabled


@pytest.mark.parametrize("path,expected", [
    ("~/.ssh/id_ed25519_web1", "ed25519"),
    ("~/.ssh/id_rsa_db1", "rsa"),
    ("~/.ssh/id_ecdsa_x", "ecdsa"),
    ("", ""),
    ("~/.ssh/mykey.pem", ""),
])
def test_key_type_from_path(path, expected):
    assert config._key_type_from_path(path) == expected


# ── history.log — okssh writes "timestamp|alias|duration|exit" ────────────────

def test_load_history_pipe_format(okssh_home):
    (okssh_home / "history.log").write_text(
        "2026-06-30 22:04|truenas|249|0\n"
        "2026-07-01 06:18|webbox|4|255\n"
        "malformed line without pipes\n"
    )
    entries = config.load_history()
    assert len(entries) == 2
    assert entries[0]["alias"] == "webbox"        # newest first
    assert entries[0]["exit_code"] == "255"
    assert entries[1]["duration"] == "249"


def test_load_history_substring_filter(okssh_home):
    (okssh_home / "history.log").write_text(
        "2026-06-30 22:04|truenas|249|0\n"
        "2026-07-01 06:18|webbox|4|0\n"
    )
    assert len(config.load_history("tru")) == 1
    assert len(config.load_history("TRUE")) == 1   # case-insensitive
    assert len(config.load_history("nope")) == 0
    assert len(config.load_history(None)) == 2


# ── tunnels — repeated [tunnel] blocks with name= fields ───────────────────────

def test_load_tunnels_named_blocks(okssh_home):
    (okssh_home / "tunnels").write_text(
        "\n[tunnel]\nname=db-tun\nalias=web1\nforward=5432:localhost:5432\n"
        "type=local\ncreated=2026-05-01 10:00\n\n"
        "\n[tunnel]\nname=proxy\nalias=db1\nforward=1080\ntype=socks\n"
        "created=2026-05-02 11:00\n\n"
    )
    tunnels = config.load_tunnels()
    assert [t.name for t in tunnels] == ["db-tun", "proxy"]
    assert tunnels[0].forward_spec == "5432:localhost:5432"
    assert tunnels[0].tunnel_type == "local"
    assert tunnels[1].alias == "db1"
    assert tunnels[1].tunnel_type == "socks"


def test_tunnel_running_no_socket(okssh_home):
    assert config.tunnel_running("db-tun") is False
    # a plain file is not a socket either
    (okssh_home / "tunnel-socks").mkdir()
    (okssh_home / "tunnel-socks" / "db-tun.sock").write_text("")
    assert config.tunnel_running("db-tun") is False


# ── templates — repeated [template] blocks with name= fields ───────────────────

def test_load_templates_named_blocks(okssh_home):
    (okssh_home / "templates").write_text(
        "[template]\nname=work\nuser=ubuntu\nport=2222\ngroup=work\n"
        "key_type=ed25519\nnote=\nalive=60\n\n"
        "[template]\nname=lab\nuser=root\nport=22\ngroup=homelab\n"
        "key_type=rsa\nnote=lab box\nalive=\n\n"
    )
    templates = config.load_templates()
    assert [t.name for t in templates] == ["work", "lab"]
    assert templates[0].port == "2222"
    assert templates[0].server_alive_interval == "60"
    assert templates[1].note == "lab box"


def test_parse_named_blocks_missing_file(okssh_home):
    assert config.load_tunnels() == []
    assert config.load_templates() == []


# ── snippets — [name] sections, use_sudo=yes|no ────────────────────────────────

def test_load_snippets(okssh_home):
    (okssh_home / "snippets").write_text(
        "\n[restart-stack]\ndescription=Restart the stack\n"
        "command=docker compose up -d\nuse_sudo=yes\ncreated=2026-04-24 21:53\n\n"
        "[uptime]\ndescription=\ncommand=uptime\nuse_sudo=no\ncreated=2026-04-25 09:00\n\n"
    )
    snippets = config.load_snippets()
    assert [s.name for s in snippets] == ["restart-stack", "uptime"]
    assert snippets[0].use_sudo == "yes"
    assert snippets[0].command == "docker compose up -d"
    assert snippets[1].use_sudo == "no"
