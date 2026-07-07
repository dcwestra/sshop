"""Tests for the pure display helpers in screens/home.py."""

from __future__ import annotations

import pytest

from sshop.screens.home import _group_color, _key_age_markup, _key_badge, _latency_markup


class TestKeyAgeMarkup:
    def test_no_age(self):
        assert "—" in _key_age_markup(None, 90)

    def test_auditing_disabled_shows_dim_age(self):
        out = _key_age_markup(400, None)
        assert out.startswith("[dim]")
        assert "1y" in out

    def test_fresh_key_green(self):
        assert _key_age_markup(10, 90) == "[green]10d[/green]"

    def test_warning_band_yellow(self):
        # >= 60% of threshold turns yellow
        assert _key_age_markup(60, 90).startswith("[yellow]")

    def test_overdue_red(self):
        assert _key_age_markup(90, 90).startswith("[red]")
        assert _key_age_markup(365, 90).startswith("[red]")

    @pytest.mark.parametrize("days,label", [
        (5, "5d"),
        (45, "1mo"),
        (365, "1y"),
        (400, "1y 1mo"),
    ])
    def test_labels(self, days, label):
        assert label in _key_age_markup(days, 9999)


class TestLatencyMarkup:
    def test_not_probed_yet(self):
        assert "○" in _latency_markup(None, None)

    def test_unreachable(self):
        assert "✗" in _latency_markup(None, False)

    def test_bands(self):
        assert "#9ece6a" in _latency_markup(10, True)     # green < 50ms
        assert "#e0af68" in _latency_markup(100, True)    # yellow 50-200ms
        assert "#f7768e" in _latency_markup(500, True)    # red > 200ms


def test_group_color_deterministic():
    assert _group_color("homelab") == _group_color("homelab")
    assert _group_color("") == "white"


def test_key_badge():
    assert _key_badge("ed25519") == "[ed]"
    assert _key_badge("rsa") == "[rsa]"
    assert _key_badge("") == "    "
