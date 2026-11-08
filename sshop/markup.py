"""Safe rendering of user and okssh text.

Alias notes, snippet commands, filenames and okssh messages routinely contain
square brackets ("grep [a-z] log", "[/etc/hosts]", "Report [draft].pdf").
Interpolated into a markup string they either vanish silently or raise
MarkupError — which crashes the app at render time. So:

  • Static / modal text  → m("[bold]$name[/bold]", name=value)
                            ($-variables are inserted as literal text)
  • DataTable cells       → cell(value, "bold #7aa2f7")   (no markup parsing)
  • notifications         → self.notify(plain(msg), markup=False)

Never build markup with f-strings around values you didn't write yourself.
"""

from __future__ import annotations

import re

from rich.text import Text
from textual.content import Content

# CSI sequences (colours, cursor movement) — okssh output from older
# versions, or anything that forces colour
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def plain(text: str) -> str:
    """Strip ANSI escape sequences (e.g. okssh's coloured error lines)."""
    return _ANSI.sub("", text or "")


def m(template: str, **values: object) -> Content:
    """Markup template whose $name slots are filled with literal text."""
    return Content.from_markup(template, **{k: str(v) for k, v in values.items()})


def cell(value: object, style: str = "") -> Text:
    """A DataTable cell rendered verbatim (DataTable parses str cells as markup)."""
    return Text(str(value), style=style)
