"""Tests for engine.status_json parsing (okssh subprocess is monkeypatched)."""

from __future__ import annotations

import asyncio

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
