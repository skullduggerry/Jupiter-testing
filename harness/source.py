"""Reading the dotfiles' sources for what a running test cannot show: which
branch a line is in, what an object declares.

Plain text with braces counted, not a QML or Lua parser: enough for code
written as qmlformat and stylua write it, where strings hold no unmatched
braces. A test that relies on it names what it looks for, so a rewrite that
it no longer understands fails rather than passing unseen.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from . import QUICKSHELL


class Block(NamedTuple):
    """An object or a block: where its `{` and `}` are, and its text."""

    start: int
    end: int
    text: str


def closing(text: str, opening: int) -> int:
    """The index of the `}` that closes the `{` at `opening`."""
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed brace at {opening}")


def objects(text: str, kind: str) -> Iterator[Block]:
    """Every `kind { … }` object in a QML file, nested ones included."""
    for match in re.finditer(rf"(?<![\w.]){re.escape(kind)}\s*\{{", text):
        opening = match.end() - 1
        end = closing(text, opening)
        yield Block(opening, end, text[opening : end + 1])


def conditions(text: str, index: int) -> list[str]:
    """The conditions of every `if (…) {` block `index` is inside, innermost
    first."""
    found = []
    depth = 0
    for position in range(index - 1, -1, -1):
        character = text[position]
        if character == "}":
            depth += 1
        elif character == "{":
            if depth:
                depth -= 1
                continue
            head = text[max(0, position - 400) : position]
            if match := re.search(r"if \((.*)\)\s*$", head):
                found.append(match.group(1))
    return found


def binding(block: str, name: str) -> str | None:
    """The expression a property is bound to in an object, its first line,
    or None where the object does not set it (nested objects aside)."""
    inner = block[1:-1]
    # Drop nested objects, so their properties are not taken for this one's.
    nested = r"(\b[A-Z]\w*(\.\w+)*|\bBehavior on [\w.]+)\s*\{"
    while match := re.search(nested, inner):
        opening = match.end() - 1
        inner = inner[: match.start()] + inner[closing(inner, opening) + 1 :]
    if found := re.search(rf"^\s*{re.escape(name)}:\s*(.+)$", inner, re.M):
        return found.group(1).strip()
    return None


def qml_files(root: Path = QUICKSHELL) -> list[Path]:
    return sorted(root.rglob("*.qml"))
