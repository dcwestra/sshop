"""Tests for the home-screen alias filter."""

from __future__ import annotations

from sshop.config import Alias
from sshop.screens.home import _filter_aliases


def _fixtures() -> list[Alias]:
    return [
        Alias(name="truenas", hostname="192.168.1.10", group="homelab",
              note="NAS box"),
        Alias(name="pve1", hostname="192.168.1.21", group="homelab,prod",
              note="Proxmox node 1"),
        Alias(name="webprod", hostname="203.0.113.5", group="work",
              note="customer site"),
        Alias(name="pihole1", hostname="192.168.1.53", group="", note=""),
    ]


def test_empty_query_returns_all():
    aliases = _fixtures()
    assert _filter_aliases(aliases, "") == aliases
    assert _filter_aliases(aliases, "   ") == aliases


def test_matches_name():
    assert [a.name for a in _filter_aliases(_fixtures(), "true")] == ["truenas"]


def test_matches_hostname():
    assert [a.name for a in _filter_aliases(_fixtures(), "1.53")] == ["pihole1"]


def test_matches_group():
    assert [a.name for a in _filter_aliases(_fixtures(), "homelab")] == ["truenas", "pve1"]


def test_matches_note_case_insensitive():
    assert [a.name for a in _filter_aliases(_fixtures(), "PROXMOX")] == ["pve1"]


def test_multiple_tokens_all_must_match():
    # "homelab" matches truenas+pve1; "prod" narrows to pve1
    assert [a.name for a in _filter_aliases(_fixtures(), "homelab prod")] == ["pve1"]
    # tokens can hit different fields (name + note)
    assert [a.name for a in _filter_aliases(_fixtures(), "web customer")] == ["webprod"]


def test_no_match():
    assert _filter_aliases(_fixtures(), "zzz") == []
