#!/usr/bin/env python3
"""List Jupiter-dotfiles' QML files with a pasted private-use glyph, and fail
if there is one.

    scripts/pasted-glyphs.py DOTFILES

Tooling has silently emptied pasted private-use codepoints before -- the
calendar's month chevrons, and very nearly the bluetooth and wifi icons --
leaving `text: ""` and no error anywhere. Written as "\\u{F0141}" escapes they
are plain ASCII and cannot be lost, so scripts/lint.sh accepts no other form.
"""

import pathlib
import re
import sys

PRIVATE_USE = re.compile("[-\U000f0000-\U000ffffd]")

repo = pathlib.Path(sys.argv[1])
found = [
    path.relative_to(repo)
    for root in (".config/quickshell", "etc/greetd")
    for path in sorted((repo / root).rglob("*.qml"))
    if PRIVATE_USE.search(path.read_text(encoding="utf-8"))
]
for path in found:
    print(path)
sys.exit(1 if found else 0)
