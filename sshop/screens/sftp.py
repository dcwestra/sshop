from __future__ import annotations

import datetime
import shutil
import stat as stat_mod
from dataclasses import dataclass
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.containers import Horizontal, Vertical

from sshop.config import Alias, load_aliases, load_tunnels, load_snippets
from sshop.widgets.keybar import KeyBar
from sshop.widgets.stats_header import StatsHeader


# ── file entry ─────────────────────────────────────────────────────────────────

@dataclass
class FEntry:
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0

    @property
    def size_str(self) -> str:
        if self.is_dir:
            return ""
        for unit, div in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
            if self.size >= div:
                return f"{self.size / div:.1f} {unit}"
        return f"{self.size} B"

    @property
    def mtime_str(self) -> str:
        if not self.mtime:
            return ""
        return datetime.datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")


_UP = FEntry(name="..", is_dir=True)


def _list_local(path: Path) -> list[FEntry]:
    entries: list[FEntry] = []
    try:
        items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for item in items:
            try:
                s = item.stat()
                entries.append(FEntry(item.name, item.is_dir(), s.st_size, s.st_mtime))
            except OSError:
                entries.append(FEntry(item.name, item.is_dir()))
    except PermissionError:
        pass
    return entries


async def _list_remote(sftp, path: str) -> list[FEntry]:
    entries: list[FEntry] = []
    try:
        names = await sftp.readdir(path)
        names_sorted = sorted(
            [n for n in names if n.filename not in (".", "..")],
            key=lambda n: (not stat_mod.S_ISDIR(n.attrs.permissions or 0), n.filename.lower()),
        )
        for n in names_sorted:
            entries.append(FEntry(
                name=n.filename,
                is_dir=stat_mod.S_ISDIR(n.attrs.permissions or 0),
                size=n.attrs.size or 0,
                mtime=float(n.attrs.mtime or 0),
            ))
    except Exception:
        pass
    return entries


async def _rmtree_remote(sftp, path: str) -> None:
    for n in await sftp.readdir(path):
        if n.filename in (".", ".."):
            continue
        child = path.rstrip("/") + "/" + n.filename
        if stat_mod.S_ISDIR(n.attrs.permissions or 0):
            await _rmtree_remote(sftp, child)
        else:
            await sftp.remove(child)
    await sftp.rmdir(path)


# ── file pane widget ───────────────────────────────────────────────────────────

class FilePane(Vertical):
    DEFAULT_CSS = """
    FilePane {
        width: 1fr;
        height: 1fr;
        border: round #2a2b3d;
    }
    FilePane.active {
        border: round #7aa2f7;
    }
    FilePane #fp-path {
        height: 1;
        padding: 0 1;
        background: #13141f;
        color: #565f89;
    }
    FilePane DataTable {
        height: 1fr;
        border: none;
    }
    """

    def __init__(self, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._entries: list[FEntry] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="fp-path")
        yield DataTable(cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        self._ck_name = t.add_column("Name", width=None)
        self._ck_size = t.add_column("Size", width=9)
        self._ck_mtime = t.add_column("Modified", width=17)

    def populate(self, path: str, entries: list[FEntry]) -> None:
        self._entries = entries
        t = self.query_one(DataTable)
        t.clear()
        self.query_one("#fp-path", Static).update(
            f"[dim]{self._label}[/dim]  [#7aa2f7]{path}[/#7aa2f7]"
        )
        t.add_row("[dim]  ..[/dim]", "", "", key="__up__")
        for i, e in enumerate(entries):
            if e.is_dir:
                name = f"[bold #7dcfff]▶ {e.name}/[/bold #7dcfff]"
            else:
                name = f"  [#c0caf5]{e.name}[/#c0caf5]"
            t.add_row(name, f"[dim]{e.size_str}[/dim]", f"[dim]{e.mtime_str}[/dim]", key=f"_e{i}_")

    def selected_entry(self) -> FEntry | None:
        t = self.query_one(DataTable)
        row = t.cursor_row
        if row == 0:
            return _UP
        idx = row - 1
        if 0 <= idx < len(self._entries):
            return self._entries[idx]
        return None

    def set_active(self, active: bool) -> None:
        (self.add_class if active else self.remove_class)("active")


# ── SFTP screen ────────────────────────────────────────────────────────────────

class SftpScreen(Screen):
    BINDINGS = [
        Binding("tab", "switch_pane", "Switch pane", show=False),
        Binding("c", "copy", "Copy →/←"),
        Binding("d", "delete_entry", "Delete", show=False),
        Binding("r", "refresh_panes", "Refresh", show=False),
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close", show=False),
    ]

    DEFAULT_CSS = """
    SftpScreen {
        layout: vertical;
        background: #1a1b26;
    }
    #sftp-body {
        height: 1fr;
        padding: 1 1 0 1;
    }
"""

    def __init__(self, alias: Alias) -> None:
        super().__init__()
        self._alias = alias
        self._conn = None
        self._sftp = None
        self._local_path = Path.home()
        self._remote_path = "."
        self._active = "local"

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="stats-header")
        with Horizontal(id="sftp-body"):
            yield FilePane("Local", id="local-pane")
            yield FilePane("Remote", id="remote-pane")
        yield KeyBar(rows=[[
            ("↵", "open dir"), ("Tab", "switch pane"), ("c", "copy →/←"),
            ("d", "delete"), ("r", "refresh"), ("Esc", "close"),
        ]])

    def on_mount(self) -> None:
        try:
            self.query_one("#stats-header", StatsHeader).update_stats(
                len(load_aliases()), len(load_tunnels()), len(load_snippets())
            )
        except Exception:
            pass
        self._refresh_local()
        self.query_one("#local-pane", FilePane).set_active(True)
        self.query_one("#local-pane", FilePane).query_one(DataTable).focus()
        self.query_one("#remote-pane", FilePane).query_one("#fp-path", Static).update(
            f"[dim]Remote[/dim]  [#565f89]{self._alias.user or 'default'}@{self._alias.hostname}[/#565f89]"
            f"  [dim]connecting…[/dim]"
        )
        self._connect()

    # ── local ──────────────────────────────────────────────────────────────────

    def _refresh_local(self) -> None:
        self.query_one("#local-pane", FilePane).populate(
            str(self._local_path), _list_local(self._local_path)
        )

    # ── remote connection ──────────────────────────────────────────────────────

    @work
    async def _connect(self) -> None:
        import asyncssh
        try:
            kwargs: dict = dict(
                host=self._alias.hostname,
                port=int(self._alias.port or 22),
                username=self._alias.user or None,
                connect_timeout=15,
                known_hosts=None,
            )
            key = self._alias.identity_file
            if key:
                kwargs["client_keys"] = [str(Path(key).expanduser())]
            self._conn = await asyncssh.connect(**kwargs)
            self._sftp = await self._conn.start_sftp_client()
            try:
                self._remote_path = await self._sftp.realpath(".")
            except Exception:
                self._remote_path = "/"
            await self._refresh_remote()
        except Exception as exc:
            self.query_one("#remote-pane", FilePane).query_one("#fp-path", Static).update(
                f"[dim]Remote[/dim]  [#f7768e]✗ {exc}[/#f7768e]"
            )
            self.notify(f"SFTP connection failed: {exc}", severity="error")

    async def _refresh_remote(self) -> None:
        if self._sftp is None:
            return
        entries = await _list_remote(self._sftp, self._remote_path)
        self.query_one("#remote-pane", FilePane).populate(self._remote_path, entries)

    # ── navigation ─────────────────────────────────────────────────────────────

    def action_switch_pane(self) -> None:
        self._active = "remote" if self._active == "local" else "local"
        self.query_one("#local-pane", FilePane).set_active(self._active == "local")
        self.query_one("#remote-pane", FilePane).set_active(self._active == "remote")
        self.query_one(f"#{self._active}-pane", FilePane).query_one(DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        local_table = self.query_one("#local-pane", FilePane).query_one(DataTable)
        self._active = "local" if event.control is local_table else "remote"
        self.query_one("#local-pane", FilePane).set_active(self._active == "local")
        self.query_one("#remote-pane", FilePane).set_active(self._active == "remote")
        entry = self._active_pane().selected_entry()
        if entry is None or not entry.is_dir:
            return
        if self._active == "local":
            self._local_path = (
                self._local_path.parent if entry.name == ".."
                else self._local_path / entry.name
            )
            self._refresh_local()
        else:
            self._navigate_remote(entry.name)

    def _active_pane(self) -> FilePane:
        return self.query_one(f"#{self._active}-pane", FilePane)

    @work
    async def _navigate_remote(self, name: str) -> None:
        if self._sftp is None:
            return
        new = (
            str(Path(self._remote_path).parent)
            if name == ".."
            else self._remote_path.rstrip("/") + "/" + name
        )
        try:
            self._remote_path = await self._sftp.realpath(new)
        except Exception as exc:
            self.notify(f"Cannot navigate: {exc}", severity="error")
            return
        await self._refresh_remote()

    def action_refresh_panes(self) -> None:
        self._refresh_local()
        self._do_refresh_remote()

    @work
    async def _do_refresh_remote(self) -> None:
        await self._refresh_remote()

    # ── copy ───────────────────────────────────────────────────────────────────

    def action_copy(self) -> None:
        if self._sftp is None:
            self.notify("Not connected yet", severity="warning")
            return
        entry = self._active_pane().selected_entry()
        if entry is None or entry.name == "..":
            return
        if self._active == "local":
            src = str(self._local_path / entry.name)
            # for dirs, dst is the remote parent so asyncssh places dirname/ inside it
            dst = self._remote_path if entry.is_dir else self._remote_path.rstrip("/") + "/" + entry.name
            self._copy_worker(src, dst, "upload", entry.name, entry.is_dir)
        else:
            src = self._remote_path.rstrip("/") + "/" + entry.name
            dst = str(self._local_path) if entry.is_dir else str(self._local_path / entry.name)
            self._copy_worker(src, dst, "download", entry.name, entry.is_dir)

    @work
    async def _copy_worker(self, src: str, dst: str, direction: str, name: str, is_dir: bool) -> None:
        try:
            if direction == "upload":
                await self._sftp.put(src, dst, recurse=is_dir)
                await self._refresh_remote()
            else:
                await self._sftp.get(src, dst, recurse=is_dir)
                self._refresh_local()
            self.notify(f"[#9ece6a]Copied {name}[/#9ece6a]")
        except Exception as exc:
            self.notify(f"Copy failed: {exc}", severity="error")

    # ── delete ─────────────────────────────────────────────────────────────────

    def action_delete_entry(self) -> None:
        if self._sftp is None and self._active == "remote":
            self.notify("Not connected", severity="warning")
            return
        entry = self._active_pane().selected_entry()
        if entry is None or entry.name == "..":
            self.notify("Select a file or directory to delete", severity="warning")
            return
        self._delete_worker(entry.name, entry.is_dir)

    @work
    async def _delete_worker(self, name: str, is_dir: bool) -> None:
        try:
            if self._active == "local":
                target = self._local_path / name
                shutil.rmtree(target) if is_dir else target.unlink()
                self._refresh_local()
            else:
                path = self._remote_path.rstrip("/") + "/" + name
                await (_rmtree_remote(self._sftp, path) if is_dir else self._sftp.remove(path))
                await self._refresh_remote()
            self.notify(f"Deleted {name}")
        except Exception as exc:
            self.notify(f"Delete failed: {exc}", severity="error")

    # ── close ──────────────────────────────────────────────────────────────────

    def action_dismiss_screen(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self.dismiss()
