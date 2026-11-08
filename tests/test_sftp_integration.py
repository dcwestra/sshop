"""End-to-end SftpScreen tests against in-process asyncssh servers:
host-key verification and ProxyJump tunnelling, no network or sshd needed."""

from __future__ import annotations

import asyncio

import pytest

asyncssh = pytest.importorskip("asyncssh")

from textual.app import App          # noqa: E402

from sshop.config import Alias       # noqa: E402
from sshop.screens.sftp import SftpScreen   # noqa: E402


class _JumpServer(asyncssh.SSHServer):
    def connection_requested(self, dest_host, dest_port, orig_host, orig_port):
        return True     # allow direct-tcpip, i.e. act as a ProxyJump hop


async def _server(tmp_path, name, client_pub, root, jump=False):
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    srv = await asyncssh.create_server(
        _JumpServer if jump else asyncssh.SSHServer, "127.0.0.1", 0,
        server_host_keys=[host_key],
        authorized_client_keys=asyncssh.import_authorized_keys(client_pub),
        sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(root)),
        allow_scp=False,
    )
    port = srv.sockets[0].getsockname()[1]
    return srv, port, host_key


@pytest.fixture
def client_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".ssh").mkdir()
    key = asyncssh.generate_private_key("ssh-ed25519")
    path = tmp_path / ".ssh" / "id_ed25519_t"
    key.write_private_key(str(path))
    return path, key.export_public_key().decode()


def _known(tmp_path, entries):
    (tmp_path / ".ssh" / "known_hosts").write_text(
        "".join(f"[127.0.0.1]:{port} {hk.export_public_key().decode()}" for port, hk in entries))


async def _open(alias, aliases, wait=4.0):
    result = {}

    class A(App):
        def on_mount(self):
            self.push_screen(SftpScreen(alias, aliases))

    app = A()
    async with app.run_test(size=(140, 40)) as pilot:
        for _ in range(int(wait / 0.1)):
            await asyncio.sleep(0.1)
            await pilot.pause()
            scr = app.screen
            bar = str(scr.query_one("#remote-pane").query_one("#fp-path").render())
            if "connecting" not in bar:
                break
        scr = app.screen
        result["bar"] = str(scr.query_one("#remote-pane").query_one("#fp-path").render())
        result["names"] = [e.name for e in scr.query_one("#remote-pane")._entries]
        result["conns"] = len(scr._conns)
        await pilot.press("escape")
        await pilot.pause()
        result["conns_after"] = len(scr._conns)
    return result


def test_unknown_host_key_is_refused(tmp_path, client_key):
    key_path, pub = client_key
    root = tmp_path / "root"; root.mkdir(); (root / "hello.txt").write_text("hi")

    async def go():
        srv, port, _hk = await _server(tmp_path, "t", pub, root)
        try:
            _known(tmp_path, [])            # nothing trusted
            a = Alias(name="t", hostname="127.0.0.1", port=str(port), identity_file=str(key_path))
            return await _open(a, [a])
        finally:
            srv.close()

    r = asyncio.run(go())
    assert "host key not trusted" in r["bar"]
    assert r["names"] == [] and r["conns"] == 0


def test_known_host_connects_and_lists(tmp_path, client_key):
    key_path, pub = client_key
    root = tmp_path / "root"; root.mkdir(); (root / "Report [draft].pdf").write_text("x")

    async def go():
        srv, port, hk = await _server(tmp_path, "t", pub, root)
        try:
            _known(tmp_path, [(port, hk)])
            a = Alias(name="t", hostname="127.0.0.1", port=str(port), identity_file=str(key_path))
            return await _open(a, [a])
        finally:
            srv.close()

    r = asyncio.run(go())
    assert "Report [draft].pdf" in r["names"]
    assert r["conns"] == 1 and r["conns_after"] == 0      # closed on dismiss


def test_proxyjump_tunnels_through_the_hop(tmp_path, client_key):
    key_path, pub = client_key
    root = tmp_path / "root"; root.mkdir(); (root / "behind-bastion.txt").write_text("x")

    async def go():
        jump, jport, jhk = await _server(tmp_path, "bastion", pub, root, jump=True)
        target, tport, thk = await _server(tmp_path, "inner", pub, root)
        try:
            _known(tmp_path, [(jport, jhk), (tport, thk)])
            bastion = Alias(name="bastion", hostname="127.0.0.1", port=str(jport),
                            identity_file=str(key_path))
            inner = Alias(name="inner", hostname="127.0.0.1", port=str(tport),
                          identity_file=str(key_path), proxy_jump="bastion")
            return await _open(inner, [bastion, inner])
        finally:
            jump.close(); target.close()

    r = asyncio.run(go())
    assert "behind-bastion.txt" in r["names"], r["bar"]
    assert r["conns"] == 2                                  # hop + target
