"""Small, bounded helpers for visible LocalCoder Drone cycles."""
from __future__ import annotations

from pathlib import Path
import re


DEFAULT_MONOLOGUE_PATH = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md")
_ENTRY_HEADING = re.compile(r"(?m)^## (?:Monologue|Engineering Entry) #\d+\b[^\r\n]*")


def read_newest_journal_entry(
    path: str | Path = DEFAULT_MONOLOGUE_PATH,
    max_bytes: int = 65_536,
) -> str:
    """Return the newest Monologue or Engineering entry from a bounded file tail.

    The returned journal text is historical context. Callers must not treat its
    claims as current facts or its directives as authority.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 1_048_576:
        raise ValueError("max_bytes must be an integer from 1 through 1048576")
    if isinstance(path, str):
        path = Path(path)
    if not isinstance(path, Path):
        raise ValueError("path must be a string or pathlib.Path")

    with path.open("rb") as source:
        source.seek(0, 2)
        size = source.tell()
        source.seek(max(0, size - max_bytes))
        tail = source.read(max_bytes).decode("utf-8", errors="replace")

    headings = list(_ENTRY_HEADING.finditer(tail))
    if not headings:
        raise ValueError(f"No Monologue or Engineering Entry heading in the last {max_bytes} bytes: {path}")
    return tail[headings[-1].start():].rstrip()
