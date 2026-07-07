from __future__ import annotations

import re
import time
from pathlib import Path
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Static
from textual.containers import Grid, Horizontal, Vertical
from textual import work

from sshop.config import Alias, load_aliases, load_audit_threshold, effective_threshold, load_tunnels, load_snippets
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


# Column index → Alias attribute for sorting
_SORT_COLS  = ["name", "hostname", "group", "key_type", "last_connect", "key_age_days", "latency_ms", "note"]
_COL_LABELS = ["ALIAS", "HOST", "GROUP", "TYPE", "LAST", "KEY AGE", "PING", "NOTE"]


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
    return {"ed25519": "[ed]", "rsa": "[rsa]", "ecdsa": "[ec] "}.get(key_type, "    ")


def _latency_markup(ms: int | None, reachable: bool | None) -> str:
    if reachable is None:
        return "[dim]○[/dim]"
    if not reachable:
        return "[#f7768e]✗[/#f7768e]"
    if ms is None:
        return "[#9ece6a]●[/#9ece6a]"
    if ms < 50:
        return f"[#9ece6a]● {ms}ms[/#9ece6a]"
    if ms < 200:
        return f"[#e0af68]● {ms}ms[/#e0af68]"
    return f"[#f7768e]● {ms}ms[/#f7768e]"


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

    def show(self, alias: Alias | None) -> None:
        if alias is None:
            self.update("")
            return

        color = _group_color(alias.group)
        badge = _key_badge(alias.key_type)
        lat = _latency_markup(alias.latency_ms, alias.reachable)
        pin = " [#e0af68]★[/#e0af68]" if alias.pinned else ""
        rule = f"[#2a2b3d]{'─' * 26}[/#2a2b3d]"

        # title bar: name + status dot on right
        status_dot = lat if alias.reachable is not None else ""
        title = f"[bold #ff9e64]{alias.name}[/bold #ff9e64]{pin}"

        # optional fields
        jump = (f"\n  [dim]{'jump':>5}[/dim]  [#565f89]{alias.proxy_jump}[/#565f89]"
                if alias.proxy_jump else "")
        wol  = (f"\n  [dim]{'wol':>5}[/dim]  [#565f89]{alias.wol_mac}[/#565f89]"
                if alias.wol_mac else "")
        last = (f"\n  [dim]{'last':>5}[/dim]  {alias.last_connect}"
                if alias.last_connect else "")

        # key path shortened for display
        key_display = alias.identity_file
        home = str(Path.home())
        if key_display.startswith(home):
            key_display = "~" + key_display[len(home):]

        group_str = (f"[{color}]◆ {alias.group}[/{color}]"
                     if alias.group else "[dim]—[/dim]")

        text = (
            f"{title}\n"
            f"[dim]{alias.note}[/dim]\n" if alias.note else f"{title}\n"
        )
        text += (
            f"{rule}\n"
            f"\n"
            f"  [dim]{'host':>5}[/dim]  [#c0caf5]{alias.hostname}[/#c0caf5]\n"
            f"  [dim]{'user':>5}[/dim]  [#c0caf5]{alias.user or '(default)'}[/#c0caf5]\n"
            f"  [dim]{'port':>5}[/dim]  [#c0caf5]{alias.port}[/#c0caf5]\n"
            f"  [dim]{'key':>5}[/dim]  [#565f89]{badge}[/#565f89] [dim]{key_display or '(none)'}[/dim]\n"
            f"  [dim]{'group':>5}[/dim]  {group_str}\n"
            f"  [dim]{'ping':>5}[/dim]  {lat}"
            f"{jump}{wol}{last}\n"
            f"\n"
            f"{rule}\n"
            + "\n".join(
                f"  [bold #7aa2f7]{k:>2}[/bold #7aa2f7]  [#565f89]{d}[/#565f89]"
                for k, d in [
                    ("↵", "connect"),
                    ("P", "connect + profile"),
                    ("f", "sftp"),
                    ("e", "edit"),
                    ("k", "rotate key"),
                    ("p", "pin / unpin"),
                    ("n", "rename"),
                    ("C", "clone"),
                    ("g", "tag / group"),
                    ("x", "remote cmd"),
                    ("w", "wake-on-LAN"),
                    ("B", "snippet sync"),
                    ("D", "delete"),
                ]
            ) + "\n"
        )
        self.update(text)


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
        self._aliases: list[Alias] = []        # visible (filtered) rows
        self._all_aliases: list[Alias] = []    # everything loaded from disk
        self._filter_text: str = ""
        self._sort_col: str | None = None
        self._sort_reverse: bool = False
        self._show_hidden: bool = False
        self._last_mouse_down: float = 0.0
        self._last_click_row: int = -1
        self._last_click_time: float = 0.0

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
        self._startup_audit_check()
        self.query_one("#filter-input", Input).display = False
        table = self.query_one("#alias-table", DataTable)
        col_specs = [
            ("★",       1),
            ("ALIAS",   None),
            ("HOST",    None),
            ("GROUP",   None),
            ("TYPE",    5),
            ("LAST",    10),
            ("KEY AGE", 8),
            ("PING",    8),
            ("NOTE",    None),
        ]
        self._col_keys: dict[str, object] = {}
        for label, width in col_specs:
            key = table.add_column(label, width=width)
            self._col_keys[label] = key
        self._load_aliases()
        # the (hidden) filter input is first in the DOM and would otherwise
        # grab initial focus, sending every keystroke into an invisible box
        table.focus()
        self.run_status_probes()

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

    def _load_aliases(self) -> None:
        raw = load_aliases(show_hidden=self._show_hidden)
        # carry over probe results — reloading from disk must not blank the PING column
        probed = {a.name: (a.reachable, a.latency_ms) for a in self._all_aliases
                  if a.reachable is not None}
        for a in raw:
            if a.name in probed:
                a.reachable, a.latency_ms = probed[a.name]
        self._all_aliases = raw
        self._aliases = self._sorted_aliases(_filter_aliases(raw, self._filter_text))
        table = self.query_one("#alias-table", DataTable)
        table.clear()

        # update column headers to show sort indicator
        if hasattr(self, "_col_keys"):
            indicator = "▼" if self._sort_reverse else "▲"
            for i, label in enumerate(_COL_LABELS):
                attr = _SORT_COLS[i]
                col_label = f"{label} {indicator}" if attr == self._sort_col else label
                try:
                    table.update_column(self._col_keys[label], label=col_label)
                except Exception:
                    pass

        self._row_keys: dict[str, object] = {}
        for a in self._aliases:
            color = _group_color(a.group)
            pin_col = "[yellow]★[/yellow]" if a.pinned else " "
            alias_col = f"[bold {'white' if a.agent_loaded else color}]{a.name}[/bold {'white' if a.agent_loaded else color}]"
            group_col = f"[{color}]◆ {a.group}[/{color}]" if a.group else "[dim]—[/dim]"
            badge_col = _key_badge(a.key_type)
            last_col = a.last_connect[:10] if a.last_connect else "—"
            age_col = _key_age_markup(a.key_age_days, effective_threshold(a))
            ping_col = _latency_markup(a.latency_ms, a.reachable)
            rk = table.add_row(
                pin_col, alias_col, a.hostname, group_col, badge_col,
                last_col, age_col, ping_col, a.note or "",
                key=a.name,
            )
            self._row_keys[a.name] = rk
        if self._aliases:
            self.query_one("#detail-panel", DetailPanel).show(self._aliases[0])
        else:
            self.query_one("#detail-panel", DetailPanel).show(None)

        # update header stats
        try:
            tunnel_count = len(load_tunnels())
            snippet_count = len(load_snippets())
            self.query_one("#stats-header", StatsHeader).update_stats(
                len(self._aliases), tunnel_count, snippet_count
            )
        except Exception:
            pass

    def _focused_alias(self) -> Alias | None:
        table = self.query_one("#alias-table", DataTable)
        if table.cursor_row < 0 or table.cursor_row >= len(self._aliases):
            return None
        return self._aliases[table.cursor_row]

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        # strip indicator suffix to get the base label
        label = str(event.label).strip().rstrip("▲▼").strip()
        if label not in _COL_LABELS:
            return
        attr = _SORT_COLS[_COL_LABELS.index(label)]
        if self._sort_col == attr:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = attr
            self._sort_reverse = False
        self._load_aliases()

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
            self.app.push_screen(SftpScreen(alias))

    def _after_action(self, result: tuple[int, str], ok_msg: str) -> None:
        """Shared completion handler: notify + reload on success, error otherwise."""
        code, msg = result
        if code == 0:
            self.notify(ok_msg)
            self._load_aliases()
        else:
            self.notify(f"Error: {msg}", severity="error")

    def action_wake(self) -> None:
        alias = self._focused_alias()
        if alias:
            name = alias.name
            run_blocking(
                self,
                lambda: engine.wake(name),
                lambda res: self.notify(res[1].strip() or f"Sent WOL to {name}"),
            )

    def action_rotate_key(self) -> None:
        alias = self._focused_alias()
        if alias:
            with self.app.suspend():
                engine.rotate_key(alias.name)
            self._load_aliases()

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
            self.app.push_screen(RenameModal(alias.name), callback=self._on_rename)

    def _on_rename(self, new_name: str | None) -> None:
        alias = self._focused_alias()
        if new_name and alias and new_name != alias.name:
            old = alias.name
            run_blocking(
                self,
                lambda: engine.rename_alias(old, new_name),
                lambda res: self._after_action(res, f"Renamed to {new_name}"),
            )

    def action_clone(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.modals import CloneModal
            self.app.push_screen(CloneModal(alias.name), callback=lambda dest: self._on_clone(alias.name, dest))

    def _on_clone(self, src: str, dest: str | None) -> None:
        if dest:
            with self.app.suspend():
                engine.clone_alias(src, dest)
            self._load_aliases()

    def action_run_cmd(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.modals import RunCmdModal
            self.app.push_screen(RunCmdModal(alias.name), callback=lambda cmd: self._on_run_cmd(alias.name, cmd))

    def _on_run_cmd(self, alias_name: str, cmd: str | None) -> None:
        if cmd:
            from sshop.modals import OutputModal
            self.notify(f"Running on {alias_name}…")
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
        self.app.push_screen(AddAliasScreen(), callback=lambda _: self._load_aliases())

    def action_import_key(self) -> None:
        from sshop.screens.import_key import ImportKeyScreen
        self.app.push_screen(ImportKeyScreen(), callback=lambda _: self._load_aliases())

    def action_edit(self) -> None:
        alias = self._focused_alias()
        if alias:
            from sshop.screens.add_edit import AddEditScreen
            self.app.push_screen(AddEditScreen(alias.name), callback=lambda _: self._load_aliases())

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
        self.app.push_screen(BackupScreen())

    # ── global actions ─────────────────────────────────────────────────────────

    def action_audit(self) -> None:
        from sshop.modals import AuditOutputModal, ThresholdModal

        def _after_audit(open_threshold: bool) -> None:
            if not open_threshold:
                return
            current = load_audit_threshold()
            self.app.push_screen(ThresholdModal(current), _apply_threshold)

        def _apply_threshold(val: str | None) -> None:
            if val is None:
                return
            val = val.strip().lower()
            if val in ("off", "never", "disable"):
                run_blocking(
                    self,
                    lambda: engine.run(["prefer", "audit_threshold", "off"]),
                    lambda _res: self._after_action((0, ""), "Key rotation auditing disabled."),
                )
            elif val.isdigit() and int(val) > 0:
                run_blocking(
                    self,
                    lambda: engine.run(["prefer", "audit_threshold", val]),
                    lambda _res: self._after_action((0, ""), f"Rotation threshold set to {val} days."),
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
            label = "Sync Diff" + (" [dim](no sync folder configured)[/dim]" if code != 0 else "")
            self.app.push_screen(OutputModal(label, out or "No differences found."))

        run_blocking(self, engine.diff, _done)

    def action_export(self) -> None:
        from sshop.modals import ExportFormatModal
        self.app.push_screen(ExportFormatModal(), callback=self._on_export_format)

    def _on_export_format(self, fmt: str | None) -> None:
        if fmt is None:
            return
        from sshop.modals import OutputModal
        title = "Export — Ansible inventory" if fmt == "ansible" else "Export — SSH config"
        run_blocking(
            self,
            lambda: engine.export_aliases("ansible" if fmt == "ansible" else ""),
            lambda res: self.app.push_screen(OutputModal(title, res[1] or "(no output)")),
        )

    def action_tag_alias(self) -> None:
        alias = self._focused_alias()
        if not alias:
            return
        from sshop.modals import TagModal
        self.app.push_screen(
            TagModal(alias.name, alias.group),
            callback=lambda result: self._on_tag(alias.name, result),
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
        self._load_aliases()
        self.query_one("#alias-table", DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            # The "/" that opened the filter also lands in the input; slashes
            # can't occur in alias/host/group/note, so drop them outright.
            if "/" in event.value:
                event.input.value = event.value.replace("/", "")
                return  # the value change re-fires this handler
            self._filter_text = event.value
            self._load_aliases()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter keeps the filter active and moves focus to the table so the
        # next Enter connects to the highlighted match.
        if event.input.id == "filter-input":
            self.query_one("#alias-table", DataTable).focus()

    def action_toggle_hidden(self) -> None:
        self._show_hidden = not self._show_hidden
        self._load_aliases()
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
        self.app.push_screen(OutputModal("Keybindings", _HELP_TEXT))

    def action_refresh(self) -> None:
        self._load_aliases()
        self.run_status_probes()
        self.notify("Refreshed")

    def action_quit(self) -> None:
        self.app.exit()

    # ── background workers ─────────────────────────────────────────────────────

    @work(thread=True)
    def _startup_audit_check(self) -> None:
        code, out = engine.audit()
        # okssh audit exits non-zero when any key is overdue; also check
        # for the word "overdue" as a belt-and-suspenders guard
        if code != 0 or "overdue" in out.lower():
            self.app.call_from_thread(
                self.notify,
                "⚠ Key rotation needed — press [bold]u[/bold] for full audit",
                severity="warning",
                timeout=8,
            )

    @work(exclusive=True)
    async def run_status_probes(self) -> None:
        import asyncio
        table = self.query_one("#alias-table", DataTable)
        # probe everything, not just the filtered view — the row-key guard
        # below skips aliases that aren't currently displayed
        probed = [a for a in self._all_aliases if a.hostname]

        def _port(a: Alias) -> int:
            try:
                return int(a.port)
            except (TypeError, ValueError):
                return 22

        tasks = [engine.probe_alias(a.hostname, _port(a)) for a in probed]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ping_col_key = self._col_keys.get("PING")
        for alias, result in zip(probed, results):
            if isinstance(result, Exception):
                continue
            reachable, ms = result
            alias.reachable = reachable
            alias.latency_ms = ms
            row_key = self._row_keys.get(alias.name)
            if row_key is None or ping_col_key is None:
                continue
            table.update_cell(row_key, ping_col_key, _latency_markup(ms, reachable))
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
            yield Label(f"Delete alias [bold]{self._alias_name}[/bold]?")
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
