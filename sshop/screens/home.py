from __future__ import annotations

import re
import time
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Static
from textual.containers import Grid, Horizontal, Vertical
from textual import work

from sshop.config import (Alias, effective_threshold, files_snapshot, is_hidden,
                          keysync_stale, load_aliases, load_audit_threshold,
                          load_snippets, load_tunnels)
from sshop.markup import cell, m, plain
from sshop.widgets.stats_header import StatsHeader
from sshop.widgets.keybar import KeyBar
from sshop.worker import run_blocking
from sshop import engine


_HELP_TEXT = """\
[bold]Alias actions[/bold]
  [cyan]Enter[/cyan]  Connect to selected alias
  [cyan]c[/cyan]      Connect
  [cyan]P[/cyan]      Connect with ephemeral profile
  [cyan]e[/cyan]      Edit alias
  [cyan]a[/cyan]      Add new alias
  [cyan]I[/cyan]      Import an existing key
  [cyan]D[/cyan]      Delete alias
  [cyan]f[/cyan]      Open SFTP session
  [cyan]w[/cyan]      Send Wake-on-LAN
  [cyan]k[/cyan]      Rotate SSH key
  [cyan]p[/cyan]      Pin / unpin alias
  [cyan]n[/cyan]      Rename alias
  [cyan]C[/cyan]      Clone alias
  [cyan]x[/cyan]      Run remote command
  [cyan]g[/cyan]      Add / remove group tag
  [cyan]H[/cyan]      Show / hide hidden aliases

[bold]Screens[/bold]
  [cyan]t[/cyan]      Tunnels
  [cyan]s[/cyan]      Snippets
  [cyan]l[/cyan]      Connection log
  [cyan]G[/cyan]      SSH agent
  [cyan]b[/cyan]      Backups
  [cyan]m[/cyan]      Templates
  [cyan]B[/cyan]      Bootstrap

[bold]Global[/bold]
  [cyan]/[/cyan]      Filter aliases (Esc clears)
  [cyan]u[/cyan]      Key audit (all aliases)
  [cyan]d[/cyan]      Sync diff
  [cyan]E[/cyan]      Export aliases
  [cyan]r[/cyan]      Refresh alias list
  [cyan]?[/cyan]      This help
  [cyan]q[/cyan]      Quit\
"""


# (column key/label, width, Alias attribute it sorts by — None = not sortable)
_COLUMNS = [
    ("★",       1,    None),
    ("ALIAS",   None, "name"),
    ("HOST",    None, "hostname"),
    ("GROUP",   None, "group"),
    ("TYPE",    5,    "key_type"),
    ("LAST",    10,   "last_connect"),
    ("KEY AGE", 8,    "key_age_days"),
    ("PING",    8,    "latency_ms"),
    ("NOTE",    None, "note"),
]
_SORT_ATTR = {label: attr for label, _w, attr in _COLUMNS if attr}


def _filter_aliases(aliases: list[Alias], query: str) -> list[Alias]:
    """Token filter: every whitespace-separated token must appear (case-
    insensitive substring) somewhere in name/hostname/group/note."""
    tokens = query.strip().lower().split()
    if not tokens:
        return aliases
    result = []
    for a in aliases:
        haystack = f"{a.name} {a.hostname} {a.group} {a.note}".lower()
        if all(t in haystack for t in tokens):
            result.append(a)
    return result


def _key_age_markup(days: int | None, threshold: int | None) -> str:
    if days is None:
        return "[dim]—[/dim]"
    if days < 30:
        label = f"{days}d"
    elif days < 365:
        label = f"{days // 30}mo"
    else:
        y, mo = divmod(days, 365)
        label = f"{y}y" + (f" {mo // 30}mo" if mo >= 30 else "")
    if threshold is None:
        return f"[dim]{label}[/dim]"   # auditing disabled — show age but no colour
    if days >= threshold:
        return f"[red]{label}[/red]"
    if days >= threshold * 0.6:
        return f"[yellow]{label}[/yellow]"
    return f"[green]{label}[/green]"


def _group_color(group: str) -> str:
    if not group:
        return "white"
    total = sum(ord(c) for c in group)
    colors = ["cyan", "green", "yellow", "magenta", "#ff9e64", "bright_cyan"]
    return colors[total % len(colors)]


def _key_badge(key_type: str) -> str:
    # literal "[ed]" etc. — always render via cell()/$-variables, never inside
    # a markup string, where "[ed]" would be swallowed as a style tag
    return {"ed25519": "[ed]", "rsa": "[rsa]", "ecdsa": "[ec] "}.get(key_type, "    ")


def _latency_markup(ms: int | None, reachable: bool | None) -> str:
    # Bands sized for a full SSH handshake (okssh status --json), not raw
    # TCP RTT — LAN handshakes land around 100-300ms.
    if reachable is None:
        return "[dim]○[/dim]"
    if not reachable:
        return "[#f7768e]✗[/#f7768e]"
    if ms is None:
        return "[#9ece6a]●[/#9ece6a]"
    if ms < 300:
        return f"[#9ece6a]● {ms}ms[/#9ece6a]"
    if ms < 1000:
        return f"[#e0af68]● {ms}ms[/#e0af68]"
    return f"[#f7768e]● {ms}ms[/#f7768e]"


def _rotation_due(aliases: list[Alias], global_threshold: int | None) -> int:
    """Keys needing attention: older than their threshold, or configured but
    missing on disk (same rule as `okssh audit`, minus aliases without keys)."""
    due = 0
    for a in aliases:
        threshold = effective_threshold(a, global_threshold)
        if threshold is None or not a.identity_file:
            continue
        if a.key_age_days is None or a.key_age_days >= threshold:
            due += 1
    return due


class DetailPanel(Static):
    """Right-pane alias detail, updated on cursor move."""

    DEFAULT_CSS = """
    DetailPanel {
        width: 1fr;
        height: 100%;
        padding: 1 2;
        border: solid $primary-darken-2;
        overflow-y: auto;
    }
    """

    _KEYS = [
        ("↵", "connect"), ("P", "connect + profile"), ("f", "sftp"), ("e", "edit"),
        ("k", "rotate key"), ("p", "pin / unpin"), ("n", "rename"), ("C", "clone"),
        ("g", "tag / group"), ("x", "remote cmd"), ("w", "wake-on-LAN"),
        ("B", "bootstrap"), ("D", "delete"),
    ]

    def show(self, alias: Alias | None) -> None:
        if alias is None:
            self.update("")
            return
        color = _group_color(alias.group)
        key_display = alias.identity_file
        home = str(Path.home())
        if key_display.startswith(home):
            key_display = "~" + key_display[len(home):]

        # Fixed markup with $-slots: every value is inserted as literal text
        # (notes and paths may contain "[" — see sshop.markup)
        parts = [m("[bold #ff9e64]$name[/bold #ff9e64]", name=alias.name)]
        if alias.pinned:
            parts.append(m(" [#e0af68]★[/#e0af68]"))
        parts.append(m("\n"))
        if alias.note:
            parts.append(m("[dim]$note[/dim]\n", note=alias.note))
        rule = "[#2a2b3d]" + "─" * 26 + "[/#2a2b3d]"
        parts.append(m(
            rule + "\n\n"
            "  [dim] host[/dim]  [#c0caf5]$host[/#c0caf5]\n"
            "  [dim] user[/dim]  [#c0caf5]$user[/#c0caf5]\n"
            "  [dim] port[/dim]  [#c0caf5]$port[/#c0caf5]\n"
            "  [dim]  key[/dim]  [#565f89]$badge[/#565f89] [dim]$key[/dim]\n",
            host=alias.hostname, user=alias.user or "(default)", port=alias.port,
            badge=_key_badge(alias.key_type), key=key_display or "(none)",
        ))
        if alias.group:
            parts.append(m(f"  [dim]group[/dim]  [{color}]◆ $g[/{color}]\n", g=alias.group))
        else:
            parts.append(m("  [dim]group[/dim]  [dim]—[/dim]\n"))
        parts.append(m("  [dim] ping[/dim]  " + _latency_markup(alias.latency_ms, alias.reachable)))
        if alias.proxy_jump:
            parts.append(m("\n  [dim] jump[/dim]  [#565f89]$v[/#565f89]", v=alias.proxy_jump))
        if alias.wol_mac:
            parts.append(m("\n  [dim]  wol[/dim]  [#565f89]$v[/#565f89]", v=alias.wol_mac))
        if alias.last_connect:
            parts.append(m("\n  [dim] last[/dim]  $v", v=alias.last_connect))
        keys = "\n".join(
            f"  [bold #7aa2f7]{k:>2}[/bold #7aa2f7]  [#565f89]{d}[/#565f89]" for k, d in self._KEYS
        )
        parts.append(m("\n\n" + rule + "\n" + keys + "\n"))
        content = parts[0]
        for p in parts[1:]:
            content = content + p
        self.update(content)


class HomeScreen(Screen):
    BINDINGS = [
        # alias actions
        Binding("c", "connect", "Connect"),
        Binding("P", "connect_profile", "Connect+profile", show=False),
        Binding("e", "edit", "Edit"),
        Binding("a", "add", "Add"),
        Binding("I", "import_key", "Import key", show=False),
        Binding("D", "delete", "Delete", show=False),
        Binding("f", "sftp", "SFTP", show=False),
        Binding("w", "wake", "Wake", show=False),
        Binding("k", "rotate_key", "Rotate key", show=False),
        Binding("p", "pin_toggle", "Pin/unpin", show=False),
        Binding("n", "rename", "Rename", show=False),
        Binding("C", "clone", "Clone", show=False),
        Binding("x", "run_cmd", "Run cmd", show=False),
        Binding("g", "tag_alias", "Tag/group", show=False),
        Binding("H", "toggle_hidden", "Show hidden", show=False),
        # screens
        Binding("t", "tunnels", "Tunnels"),
        Binding("s", "snippets", "Snippets"),
        Binding("l", "log", "Log"),
        Binding("G", "agent", "Agent"),
        Binding("b", "backup", "Backup"),
        Binding("m", "templates", "Templates", show=False),
        Binding("B", "bootstrap", "Bootstrap", show=False),
        # global
        Binding("/", "filter_open", "Filter", show=False),
        Binding("escape", "filter_clear", "Clear filter", show=False),
        Binding("u", "audit", "Audit"),
        Binding("d", "diff", "Diff", show=False),
        Binding("E", "export", "Export"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("?", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    _DOUBLE_CLICK_S = 0.45
    _MOUSE_SELECT_WINDOW_S = 0.3

    def __init__(self):
        super().__init__()
        self._aliases: list[Alias] = []        # visible rows (hidden/filter/sort applied)
        self._all_aliases: list[Alias] = []    # everything on disk, hidden included
        self._global_threshold: int | None = 90
        self._filter_text: str = ""
        self._sort_col: str | None = None
        self._sort_reverse: bool = False
        self._show_hidden: bool = False
        self._last_mouse_down: float = 0.0
        self._last_click_row: int = -1
        self._last_click_time: float = 0.0
        self._keysync_stale: bool = False
        self._fs_snapshot: tuple | None = None
        self._col_keys: dict[str, object] = {}
        self._row_keys: dict[str, object] = {}
        self._columns_sig: tuple | None = None

    def compose(self) -> ComposeResult:
        yield StatsHeader(id="stats-header")
        with Horizontal(id="main-layout"):
            with Vertical(id="left-pane"):
                yield Input(placeholder="filter — name, host, group, note…",
                            id="filter-input")
                yield DataTable(id="alias-table", cursor_type="row", zebra_stripes=True)
            yield DetailPanel(id="detail-panel")
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one("#filter-input", Input).display = False
        self._reload()
        # the (hidden) filter input is first in the DOM and would otherwise
        # grab initial focus, sending every keystroke into an invisible box
        self.query_one("#alias-table", DataTable).focus()
        self._startup_audit_check()
        self.run_status_probes()
        # notice changes made outside sshop (okssh CLI, other terminals, sync)
        self.set_interval(2.0, self._check_external_changes)

    # ── loading / rendering ────────────────────────────────────────────────────

    def _check_external_changes(self) -> None:
        if files_snapshot() != self._fs_snapshot:
            self._reload()

    def _reload(self) -> None:
        """Re-read everything from disk, then redraw. Filtering, sorting and
        the hidden toggle only call _redraw() — no disk I/O per keystroke.
        (Not "_render": that name is Textual-internal on every Widget.)"""
        snap = files_snapshot()
        config_changed = self._fs_snapshot is not None and snap[0] != self._fs_snapshot[0]
        self._fs_snapshot = snap

        raw = load_aliases(show_hidden=True)
        # carry over probe results — reloading from disk must not blank PING
        probed = {a.name: (a.reachable, a.latency_ms) for a in self._all_aliases
                  if a.reachable is not None}
        for a in raw:
            if a.name in probed:
                a.reachable, a.latency_ms = probed[a.name]
        self._all_aliases = raw
        self._global_threshold = load_audit_threshold()

        try:
            counts = (sum(1 for a in raw if not is_hidden(a)),
                      len(load_tunnels()), len(load_snippets()))
        except Exception:
            counts = (len(raw), 0, 0)
        self.app.stats_counts = counts
        try:
            self.query_one("#stats-header", StatsHeader).update_stats(*counts)
        except Exception:
            pass

        self._redraw()
        self._check_keysync_stale()
        if config_changed:
            # aliases were added/removed/edited — refresh reachability too
            self.run_status_probes()

    def _check_keysync_stale(self) -> None:
        """okssh can't prompt for the key-sync passphrase under sshop, so it
        flags the archive stale instead — tell the user once per transition."""
        stale = keysync_stale()
        if stale and not self._keysync_stale:
            self.notify(
                "Key-sync archive is out of date — run "
                "[bold]okssh sync keys update[/bold] in a terminal to re-encrypt it.",
                severity="warning",
                timeout=12,
            )
        self._keysync_stale = stale

    def _sorted_aliases(self, aliases: list[Alias]) -> list[Alias]:
        if self._sort_col is None:
            return aliases  # default: pinned first, config order
        def sort_key(a: Alias):
            val = getattr(a, self._sort_col)
            if val is None:
                return (1, [])
            if isinstance(val, str):
                # natural sort: split on digit runs so IPs and db1/db10 sort correctly
                parts = [int(c) if c.isdigit() else c.lower()
                         for c in re.split(r'(\d+)', val)]
                return (0, parts)
            return (0, [val])
        return sorted(aliases, key=sort_key, reverse=self._sort_reverse)

    def _build_columns(self, table: DataTable) -> None:
        """(Re)create the columns so the sorted one carries ▲/▼ (DataTable has
        no public way to relabel a column). Also clears the rows."""
        table.clear(columns=True)
        indicator = "▼" if self._sort_reverse else "▲"
        self._col_keys = {}
        for label, width, attr in _COLUMNS:
            shown = f"{label} {indicator}" if attr and attr == self._sort_col else label
            self._col_keys[label] = table.add_column(shown, width=width, key=label)
        self._columns_sig = (self._sort_col, self._sort_reverse)

    def _redraw(self) -> None:
        """Hidden toggle + filter + sort over the loaded aliases → table."""
        cur = self._focused_alias()
        cur_name = cur.name if cur else None
        visible = [a for a in self._all_aliases if self._show_hidden or not is_hidden(a)]
        self._aliases = self._sorted_aliases(_filter_aliases(visible, self._filter_text))

        table = self.query_one("#alias-table", DataTable)
        if self._columns_sig != (self._sort_col, self._sort_reverse):
            self._build_columns(table)
        else:
            table.clear()

        self._row_keys = {}
        for a in self._aliases:
            color = _group_color(a.group)
            name_style = f"bold {'white' if a.agent_loaded else color}"
            rk = table.add_row(
                cell("★", "yellow") if a.pinned else cell(" "),
                cell(a.name, name_style),
                cell(a.hostname),
                cell(f"◆ {a.group}", color) if a.group else cell("—", "dim"),
                cell(_key_badge(a.key_type)),
                cell(a.last_connect[:10] if a.last_connect else "—"),
                _key_age_markup(a.key_age_days, effective_threshold(a, self._global_threshold)),
                _latency_markup(a.latency_ms, a.reachable),
                cell(a.note),
                key=a.name,
            )
            self._row_keys[a.name] = rk
        # keep the cursor on the same alias across reloads (background
        # refresh must not yank it back to the top)
        if cur_name:
            for i, a in enumerate(self._aliases):
                if a.name == cur_name:
                    table.move_cursor(row=i)
                    break
        detail = self.query_one("#detail-panel", DetailPanel)
        if self._aliases:
            idx = table.cursor_row if 0 <= table.cursor_row < len(self._aliases) else 0
            detail.show(self._aliases[idx])
        else:
            detail.show(None)

    def _focused_alias(self) -> Alias | None:
        table = self.query_one("#alias-table", DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self._aliases):
            return None
        return self._aliases[table.cursor_row]

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        attr = _SORT_ATTR.get(str(event.column_key.value))
        if attr is None:
            return
        if self._sort_col == attr:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = attr
            self._sort_reverse = False
        self._redraw()

    def on_mouse_down(self, event) -> None:
        self._last_mouse_down = time.monotonic()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter connects immediately; single mouse click requires a second click."""
        now = time.monotonic()
        if (now - self._last_mouse_down) > self._MOUSE_SELECT_WINDOW_S:
            # Keyboard Enter — always connect
            self.action_connect()
            return
        row = event.cursor_row
        if row == self._last_click_row and (now - self._last_click_time) < self._DOUBLE_CLICK_S:
            self._last_click_row = -1
            self.action_connect()
        else:
            self._last_click_row = row
            self._last_click_time = now

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#alias-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._aliases):
            self.query_one("#detail-panel", DetailPanel).show(self._aliases[idx])

    # ── alias actions ──────────────────────────────────────────────────────────

    def action_connect(self) -> None:
        alias = self._focused_alias()
        if alias:
            with self.app.suspend():
                engine.connect(alias.name)

    def action_sftp(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.screens.sftp import SftpScreen
            self.app.push_screen(SftpScreen(alias, self._all_aliases))

    def _after_action(self, result: tuple[int, str], ok_msg: str) -> None:
        """Shared completion handler: notify + reload on success, error otherwise.
        Messages carry alias names and okssh output — shown as literal text."""
        code, msg = result
        if code == 0:
            self.notify(ok_msg, markup=False)
            self._reload()
        else:
            self.notify(f"Error: {plain(msg).strip()}", severity="error", markup=False)

    def action_wake(self) -> None:
        alias = self._focused_alias()
        if alias:
            name = alias.name
            run_blocking(
                self,
                lambda: engine.wake(name),
                lambda res: self.notify(
                    plain(res[1]).strip() or f"Sent WOL to {name}",
                    severity="information" if res[0] == 0 else "error",
                    markup=False,
                ),
            )

    def action_rotate_key(self) -> None:
        alias = self._focused_alias()
        if alias:
            with self.app.suspend():
                engine.rotate_key(alias.name)
            self._reload()

    def action_pin_toggle(self) -> None:
        alias = self._focused_alias()
        if alias:
            fn = engine.unpin_alias if alias.pinned else engine.pin_alias
            label = "Unpinned" if alias.pinned else "Pinned"
            name = alias.name
            run_blocking(
                self,
                lambda: fn(name),
                lambda res: self._after_action(res, f"{label} {name}"),
            )

    def action_rename(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.modals import RenameModal
            old = alias.name   # captured now: a background reload may move the cursor
            self.app.push_screen(RenameModal(old), callback=lambda new: self._on_rename(old, new))

    def _on_rename(self, old: str, new_name: str | None) -> None:
        if new_name and new_name != old:
            run_blocking(
                self,
                lambda: engine.rename_alias(old, new_name),
                lambda res: self._after_action(res, f"Renamed to {new_name}"),
            )

    def action_clone(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.modals import CloneModal
            src = alias.name
            self.app.push_screen(CloneModal(src), callback=lambda dest: self._on_clone(src, dest))

    def _on_clone(self, src: str, dest: str | None) -> None:
        if dest:
            with self.app.suspend():
                engine.clone_alias(src, dest)
            self._reload()

    def action_run_cmd(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.modals import RunCmdModal
            name = alias.name
            self.app.push_screen(RunCmdModal(name), callback=lambda cmd: self._on_run_cmd(name, cmd))

    def _on_run_cmd(self, alias_name: str, cmd: str | None) -> None:
        if cmd:
            from sshop.modals import OutputModal
            self.notify(f"Running on {alias_name}…", markup=False)
            run_blocking(
                self,
                lambda: engine.run_remote(alias_name, cmd),
                lambda res: self.app.push_screen(
                    OutputModal(f"okssh run {alias_name}", res[1] or "(no output)")
                ),
            )

    def action_delete(self) -> None:
        alias = self._focused_alias()
        if alias:
            name = alias.name
            self.app.push_screen(
                ConfirmDelete(name, has_key=bool(alias.identity_file)),
                callback=lambda result: self._on_delete_confirmed(result, name),
            )

    def _on_delete_confirmed(self, result: tuple[bool, bool] | None, name: str) -> None:
        if not result or not result[0]:
            return
        delete_keys = result[1]
        suffix = " and its key files" if delete_keys else ""
        run_blocking(
            self,
            lambda: engine.remove_alias(name, delete_keys=delete_keys),
            lambda res: self._after_action(res, f"Deleted {name}{suffix}"),
        )

    # ── screen navigation ──────────────────────────────────────────────────────

    def action_add(self) -> None:
        from sshop.screens.add_alias import AddAliasScreen
        self.app.push_screen(AddAliasScreen(), callback=lambda _: self._reload())

    def action_import_key(self) -> None:
        from sshop.screens.import_key import ImportKeyScreen
        self.app.push_screen(ImportKeyScreen(), callback=lambda _: self._reload())

    def action_edit(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.screens.add_edit import AddEditScreen
            self.app.push_screen(AddEditScreen(alias.name), callback=lambda _: self._reload())

    def action_tunnels(self) -> None:
        from sshop.screens.tunnels import TunnelsScreen
        self.app.push_screen(TunnelsScreen())

    def action_snippets(self) -> None:
        from sshop.screens.snippets import SnippetsScreen
        alias = self._focused_alias()
        self.app.push_screen(SnippetsScreen(focused_alias=alias.name if alias else None))

    def action_log(self) -> None:
        from sshop.screens.log import LogScreen
        self.app.push_screen(LogScreen())

    def action_agent(self) -> None:
        from sshop.screens.agent import AgentScreen
        self.app.push_screen(AgentScreen())

    def action_backup(self) -> None:
        from sshop.screens.backup import BackupScreen
        self.app.push_screen(BackupScreen(), callback=lambda _: self._reload())

    # ── global actions ─────────────────────────────────────────────────────────

    def action_audit(self) -> None:
        from sshop.modals import AuditOutputModal, ThresholdModal

        def _after_audit(open_threshold: bool) -> None:
            if not open_threshold:
                return
            self.app.push_screen(ThresholdModal(load_audit_threshold()), _apply_threshold)

        def _apply_threshold(val: str | None) -> None:
            if val is None:
                return
            val = val.strip().lower()
            if val in ("off", "never", "disable", "disabled"):
                setting, ok_msg = "off", "Key rotation auditing disabled."
            elif val.isdigit() and int(val) > 0:
                setting, ok_msg = val, f"Rotation threshold set to {val} days."
            else:
                self.notify("Threshold must be a positive number of days, or 'off'",
                            severity="error")
                return
            run_blocking(
                self,
                lambda: engine.run(["prefer", "audit_threshold", setting]),
                lambda res: self._after_action((res[0], res[2] or res[1]), ok_msg),
            )

        run_blocking(
            self,
            engine.audit,
            lambda res: self.app.push_screen(
                AuditOutputModal(res[1] or "No issues found."), _after_audit
            ),
        )

    def action_diff(self) -> None:
        from sshop.modals import OutputModal

        def _done(res: tuple[int, str]) -> None:
            code, out = res
            label = "Sync Diff" + (" (no sync folder configured)" if code != 0 else "")
            self.app.push_screen(OutputModal(label, out or "No differences found."))

        run_blocking(self, engine.diff, _done)

    def action_export(self) -> None:
        from sshop.modals import ExportFormatModal
        self.app.push_screen(ExportFormatModal(), callback=self._on_export_format)

    def _on_export_format(self, fmt: str | None) -> None:
        if fmt is None:
            return
        from sshop.modals import OutputModal
        ansible = fmt == "ansible"
        stamp = time.strftime("%Y%m%d")
        path = Path.home() / (f"okssh-inventory-{stamp}.ini" if ansible
                              else f"okssh-export-{stamp}.txt")
        title = "Ansible inventory" if ansible else "okssh export"

        def _work() -> tuple[int, str, str]:
            code, content = engine.export_aliases(ansible=ansible)
            if code != 0 or not content.strip():
                return code, content, ""
            try:
                path.write_text(content)
                return code, content, "~" + str(path)[len(str(Path.home())):]
            except OSError as exc:
                return code, content, f"(not saved: {exc})"

        def _done(res: tuple[int, str, str]) -> None:
            code, content, saved = res
            if code != 0:
                self.notify(f"Export failed: {plain(content).strip()}", severity="error", markup=False)
            elif not content.strip():
                self.notify("No aliases to export", severity="warning")
            else:
                self.app.push_screen(OutputModal(f"{title} — saved to {saved}", content))

        run_blocking(self, _work, _done)

    def action_tag_alias(self) -> None:
        alias = self._focused_alias()
        if not alias:
            return
        from sshop.modals import TagModal
        name = alias.name
        self.app.push_screen(
            TagModal(name, alias.group),
            callback=lambda result: self._on_tag(name, result),
        )

    def _on_tag(self, alias_name: str, result) -> None:
        if not result:
            return
        action, group = result
        fn = engine.tag_alias if action == "tag" else engine.untag_alias
        label = f"Added tag '{group}'" if action == "tag" else f"Removed tag '{group}'"
        run_blocking(
            self,
            lambda: fn(alias_name, group),
            lambda res: self._after_action(res, label),
        )

    def action_filter_open(self) -> None:
        box = self.query_one("#filter-input", Input)
        box.display = True
        box.focus()

    def action_filter_clear(self) -> None:
        box = self.query_one("#filter-input", Input)
        if not box.display and not self._filter_text:
            return
        box.value = ""
        box.display = False
        self._filter_text = ""
        self._redraw()
        self.query_one("#alias-table", DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            # The "/" that opened the filter also lands in the input; slashes
            # can't occur in alias/host/group/note, so drop them outright.
            if "/" in event.value:
                event.input.value = event.value.replace("/", "")
                return  # the value change re-fires this handler
            self._filter_text = event.value
            self._redraw()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter keeps the filter active and moves focus to the table so the
        # next Enter connects to the highlighted match.
        if event.input.id == "filter-input":
            self.query_one("#alias-table", DataTable).focus()

    def action_toggle_hidden(self) -> None:
        self._show_hidden = not self._show_hidden
        self._redraw()
        state = "showing" if self._show_hidden else "hiding"
        self.notify(f"Now {state} hidden aliases")

    def action_connect_profile(self) -> None:
        alias = self._focused_alias()
        if alias:
            with self.app.suspend():
                engine.connect_with_profile(alias.name)

    def action_templates(self) -> None:
        from sshop.screens.templates import TemplatesScreen
        self.app.push_screen(TemplatesScreen())

    def action_bootstrap(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.screens.bootstrap import BootstrapScreen
            self.app.push_screen(BootstrapScreen(alias))

    def action_help(self) -> None:
        from sshop.modals import OutputModal
        self.app.push_screen(OutputModal("Keybindings", Text.from_markup(_HELP_TEXT)))

    def action_refresh(self) -> None:
        self._reload()
        self.run_status_probes()
        self.notify("Refreshed")

    def action_quit(self) -> None:
        self.app.exit()

    # ── background workers ─────────────────────────────────────────────────────

    def _startup_audit_check(self) -> None:
        # Computed from the key ages already loaded — no `okssh audit`
        # subprocess (whose exit code never signalled overdue keys anyway)
        due = _rotation_due(self._all_aliases, self._global_threshold)
        if due:
            self.notify(
                f"⚠ {due} key(s) due for rotation — press [bold]u[/bold] for the full audit",
                severity="warning",
                timeout=8,
            )

    @work(exclusive=True)
    async def run_status_probes(self) -> None:
        # Preferred: one `okssh status --json` call — full SSH reachability
        # (detects auth failures, honors jump hosts), probed in parallel by
        # okssh itself.
        results = await engine.status_json()
        if results is not None:
            by_alias = {r.get("alias"): r for r in results}
            probed = []
            for alias in self._all_aliases:
                r = by_alias.get(alias.name)
                if r is None:
                    continue
                alias.reachable = bool(r.get("reachable"))
                ms = r.get("latency_ms")
                alias.latency_ms = int(ms) if isinstance(ms, (int, float)) else None
                probed.append(alias)
            self._apply_probe_results(probed)
            return

        # Fallback (okssh without --json): plain TCP connect probes.
        import asyncio
        targets = [(a.name, a.hostname, a.port) for a in self._all_aliases if a.hostname]

        def _port(p: str) -> int:
            try:
                return int(p)
            except (TypeError, ValueError):
                return 22

        results = await asyncio.gather(
            *(engine.probe_alias(host, _port(port)) for _n, host, port in targets),
            return_exceptions=True,
        )
        outcome = {name: res for (name, _h, _p), res in zip(targets, results)
                   if not isinstance(res, Exception)}
        # apply to the CURRENT alias objects — a reload during the await
        # replaced self._all_aliases
        done = []
        for alias in self._all_aliases:
            if alias.name in outcome:
                alias.reachable, alias.latency_ms = outcome[alias.name]
                done.append(alias)
        self._apply_probe_results(done)

    def _apply_probe_results(self, aliases: list[Alias]) -> None:
        """Paint probe outcomes into the PING column (visible rows only)."""
        table = self.query_one("#alias-table", DataTable)
        ping_col_key = self._col_keys.get("PING")
        for alias in aliases:
            row_key = self._row_keys.get(alias.name)
            if row_key is None or ping_col_key is None:
                continue
            table.update_cell(
                row_key, ping_col_key,
                _latency_markup(alias.latency_ms, alias.reachable),
            )
        focused = self._focused_alias()
        if focused:
            self.query_one("#detail-panel", DetailPanel).show(focused)


# ── Confirm delete modal ───────────────────────────────────────────────────────

class ConfirmDelete(ModalScreen[tuple[bool, bool]]):
    """Returns (confirmed, delete_keys)."""

    DEFAULT_CSS = """
    ConfirmDelete {
        align: center middle;
    }
    ConfirmDelete > Grid {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr auto 3;
        padding: 1 2;
        width: 54;
        height: 10;
        border: solid $error;
        background: $surface;
    }
    ConfirmDelete Label {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }
    ConfirmDelete Checkbox {
        column-span: 2;
        width: 1fr;
        background: transparent;
        border: none;
    }
    ConfirmDelete Button { width: 100%; }
    """

    def __init__(self, alias_name: str, has_key: bool = False):
        super().__init__()
        self._alias_name = alias_name
        self._has_key = has_key

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label(m("Delete alias [bold]$a[/bold]?", a=self._alias_name))
            if self._has_key:
                yield Checkbox("Also delete key files", value=False, id="chk-keys")
            yield Button("Delete", variant="error", id="btn-yes")
            yield Button("Cancel", variant="default", id="btn-no")

    def on_mount(self) -> None:
        if self._has_key:
            self.query_one(Grid).styles.height = 13

    def on_button_pressed(self, event: Button.Pressed) -> None:
        delete_keys = (
            self._has_key and self.query_one("#chk-keys", Checkbox).value
        )
        self.dismiss((event.button.id == "btn-yes", delete_keys))

    def key_escape(self) -> None:
        self.dismiss((False, False))
