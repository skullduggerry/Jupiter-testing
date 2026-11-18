"""The shortcuts overlay's keymap helper, against xkbcommon's own layouts.

keymap.py has to say what every key types in every layout (a dead key as its
accent, no control characters), tell an ISO layout from an ANSI one by the key
left of Z, and compile with Hyprland's options and pass on
resolve_binds_by_sym, which it asks a stand-in hyprctl on PATH for here; with
no Hyprland to answer it keeps xkbcommon's defaults. Where the loader finds
no xkbcommon by name (NixOS), it takes the one the shell running it has
loaded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from typing import Any
from unittest import mock

from harness import QUICKSHELL, executable, load, temporary

HELPER = QUICKSHELL / "services/keymap.py"
HYPRCTL = """#!/bin/sh
case "$3" in
    input:kb_options) echo '{"option": "input:kb_options", "str": "ctrl:swapcaps", "set": true }' ;;
    input:resolve_binds_by_sym) echo '{"option": "input:resolve_binds_by_sym", "bool": true, "set": true }' ;;
    *) echo '{"option": "'"$3"'", "str": "[[EMPTY]]", "set": false }' ;;
esac
"""


class Keymap(unittest.TestCase):
    def setUp(self) -> None:
        self.root = temporary(self)
        executable(self.root / "bin/hyprctl", HYPRCTL)
        self.nowhere = str(self.root / "nowhere")

    def keymap(
        self, layouts: str, variants: str, path: str, ok: bool = True
    ) -> Any:
        result = subprocess.run(
            [sys.executable, str(HELPER), layouts, variants],
            env=dict(os.environ, PATH=path),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return json.loads(result.stdout) if ok else None

    def test_what_every_key_types(self) -> None:
        # No hyprctl at all: xkbcommon's defaults.
        plain = self.keymap("us,de", ",", self.nowhere)
        us, de = (layout["keys"] for layout in plain["layouts"])
        self.assertIs(plain["resolveBySym"], False)
        self.assertEqual(
            [layout["iso"] for layout in plain["layouts"]],
            [False, True],
            "us is ANSI, de ISO",
        )
        self.assertEqual(
            us["AD01"], {"code": 24, "syms": ["q", "Q"], "text": ["q", "Q"]}
        )
        self.assertEqual(us["AD06"]["text"], ["y", "Y"])
        self.assertEqual(de["AD06"]["text"], ["z", "Z"], "de swaps Y and Z")
        self.assertEqual(de["AE11"]["text"], ["ß", "?"])
        self.assertEqual(de["TLDE"]["text"], ["^", "°"], "a dead circumflex")
        self.assertEqual(de["AE12"]["text"], ["´", "`"], "dead acute, grave")
        self.assertEqual(de["RALT"]["syms"][0], "ISO_Level3_Shift")
        self.assertEqual(
            us["RTRN"], {"code": 36, "syms": ["Return", ""], "text": ["", ""]}
        )
        self.assertEqual(us["SPCE"]["text"], ["", ""])
        self.assertEqual(us["PRSC"]["syms"][0], "Print")

    def test_hyprlands_options(self) -> None:
        swapped = self.keymap("us", "", f"{self.root / 'bin'}:/usr/bin")
        keys = swapped["layouts"][0]["keys"]
        self.assertEqual(keys["CAPS"]["syms"][0], "Control_L")
        self.assertEqual(keys["LCTL"]["syms"][0], "Caps_Lock")
        self.assertIs(swapped["resolveBySym"], True)

    def test_an_unknown_layout(self) -> None:
        self.keymap("no-such-layout", "", self.nowhere, ok=False)

    def test_without_xkbcommon_by_name_the_shells_own(self) -> None:
        keymap = load(HELPER)
        real = keymap.ctypes.CDLL
        # This process stands in for the shell, with xkbcommon loaded.
        real("libxkbcommon.so.0")
        opened = []

        def cdll(name: str) -> Any:
            opened.append(name)
            if "/" not in name:
                raise OSError(f"{name}: cannot open shared object file")
            return real(name)

        with (
            mock.patch.object(keymap.ctypes, "CDLL", cdll),
            mock.patch.object(keymap.os, "getppid", return_value=os.getpid()),
        ):
            keymap.library()
        self.assertEqual(opened[0], "libxkbcommon.so.0")
        self.assertTrue(
            opened[1].startswith("/") and "/libxkbcommon.so.0" in opened[1],
            opened,
        )

        # A path with a space in it, and nothing to find.
        maps = self.root / "maps"
        maps.write_text(
            "7f00-7f01 r--p 00000000 00:25 1      /usr/lib/libc.so.6\n"
            f"7f01-7f02 r-xp 00000000 00:25 2      {self.root}/a dir/libxkbcommon.so.0.13.2\n"
        )
        self.assertEqual(
            keymap.loaded("libxkbcommon.so.0", str(maps)),
            f"{self.root}/a dir/libxkbcommon.so.0.13.2",
        )
        with self.assertRaises(SystemExit):
            keymap.loaded("libxkbcommon.so.0", str(self.root / "none"))


if __name__ == "__main__":
    unittest.main()
