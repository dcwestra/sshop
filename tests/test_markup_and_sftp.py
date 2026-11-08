"""Pure helpers: safe markup rendering and the SFTP ProxyJump plan."""

from __future__ import annotations

import pytest

from sshop.config import Alias
from sshop.markup import cell, m, plain
from sshop.screens.home import _key_badge, _rotation_due
from sshop.screens.import_key import clean_path
from sshop.screens.sftp import connection_plan

HOSTILE = ["[/etc/hosts] mirror", "grep [a-z] log", "sed 's/[/]/x/' f",
           "Report [draft].pdf", "path\\[x]", "trailing\\", "[bold]x[/bold]", "$HOME"]


@pytest.mark.parametrize("text", HOSTILE)
def test_m_inserts_values_literally(text):
    assert m("[bold #ff9e64]$v[/bold #ff9e64]!", v=text).plain == text + "!"


@pytest.mark.parametrize("text", HOSTILE)
def test_cell_is_not_markup(text):
    assert cell(text, "bold").plain == text


def test_key_badges_survive_rendering():
    # "[ed]" inside a markup string is a style tag and vanished — the TYPE
    # column was always blank before cell()
    assert cell(_key_badge("ed25519")).plain == "[ed]"
    assert m("$b", b=_key_badge("rsa")).plain == "[rsa]"


def test_plain_strips_ansi():
    assert plain("\x1b[0;31mError:\x1b[0m Alias exists") == "Error: Alias exists"
    assert plain("") == ""


def test_clean_path(tmp_path):
    home = str(tmp_path)
    assert clean_path("  '/a b/key.pem' ") == "/a b/key.pem"
    assert clean_path('"/x/y"') == "/x/y"
    assert clean_path("file:///home/u/My%20Keys/id") == "/home/u/My Keys/id"
    assert clean_path("") == ""
    assert not clean_path("~/k").startswith("~")


def test_rotation_due():
    old = Alias(name="old", identity_file="/k1", key_age_days=200)
    new = Alias(name="new", identity_file="/k2", key_age_days=5)
    gone = Alias(name="gone", identity_file="/k3", key_age_days=None)
    nokey = Alias(name="nokey")
    off = Alias(name="off", identity_file="/k4", key_age_days=500, audit_threshold=0)
    assert _rotation_due([old, new, gone, nokey, off], 90) == 2
    assert _rotation_due([old, gone], None) == 0          # auditing disabled


# ── SFTP connection plan ───────────────────────────────────────────────────────

def _by(*aliases):
    return {a.name: a for a in aliases}


def test_plan_direct_uses_hostname_or_alias():
    a = Alias(name="web", hostname="192.0.2.1", port="2222", user="u", identity_file="~/.ssh/k")
    (hop,) = connection_plan(a, _by(a))
    assert hop["host"] == "192.0.2.1" and hop["port"] == 2222 and hop["username"] == "u"
    assert hop["agent_path"] is None and not hop["client_keys"][0].startswith("~")
    bare = Alias(name="nas.lan")
    (hop,) = connection_plan(bare, _by(bare))
    assert hop["host"] == "nas.lan" and "username" not in hop   # asyncssh rejects None


def test_plan_follows_alias_jumps_recursively():
    edge = Alias(name="edge", hostname="203.0.113.1")
    bastion = Alias(name="bastion", hostname="10.0.0.1", proxy_jump="edge")
    db = Alias(name="db", hostname="10.0.0.5", proxy_jump="bastion")
    plan = connection_plan(db, _by(edge, bastion, db))
    assert [h["host"] for h in plan] == ["203.0.113.1", "10.0.0.1", "10.0.0.5"]


def test_plan_literal_and_chained_hops():
    db = Alias(name="db", hostname="10.0.0.5", proxy_jump="root@gw.example:2200,[2001:db8::1]:22")
    plan = connection_plan(db, _by(db))
    assert plan[0] == dict(host="gw.example", port=2200, username="root")
    assert "username" not in plan[1]            # never an explicit None
    assert plan[1]["host"] == "2001:db8::1" and plan[1]["port"] == 22
    assert plan[2]["host"] == "10.0.0.5"


def test_plan_detects_loops_and_none():
    a = Alias(name="a", hostname="h", proxy_jump="b")
    b = Alias(name="b", hostname="h", proxy_jump="a")
    with pytest.raises(ValueError):
        connection_plan(a, _by(a, b))
    c = Alias(name="c", hostname="h", proxy_jump="none")
    assert len(connection_plan(c, _by(c))) == 1
