"""Applying a theme, .config/wallust/apply.sh, against a stand-in wallust and
gsettings in a made-up home.

A theme renders every template from a copy of templates/ whose
appearance.jinja holds the Settings app's choices, merges kdeglobals, tells
the portal dark or light, and is recorded with its scope; --shell-only
renders the shell's palette alone, and without -s nothing; no argument
applies the recorded theme again the same way, or the default; a theme
saved in colorschemes/ goes through `cs`; --from generates a scheme first
and applies it by the image's name.
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

from harness import DOTFILES, executable, temporary

WALLUST = DOTFILES / ".config/wallust"
SCRIPT = WALLUST / "apply.sh"

# Records its arguments, and what a render leaves for apply.sh to read next.
STAND_IN_WALLUST = """#!/bin/sh
printf '%s\\n' "$*" >>"$CALLS"
for arg; do
    if [ "$previous" = -d ]; then
        [ -L "$arg/templates/appearance.jinja" ] || cat "$arg/templates/appearance.jinja" >"$CALLS.appearance"
    fi
    previous=$arg
done
mkdir -p "$HOME/.cache/wallust"
printf '[Colors:Window]\\nBackgroundNormal=1,2,3\\n' >"$HOME/.cache/wallust/kdeglobals"
printf 'prefer-dark\\n' >"$HOME/.cache/wallust/color-scheme"
"""
GSETTINGS = """#!/bin/sh
printf '%s\\n' "gsettings $*" >>"$CALLS"
"""


class Apply(unittest.TestCase):
    def setUp(self) -> None:
        self.home = temporary(self)
        bin_dir = self.home / "bin"
        executable(bin_dir / "wallust", STAND_IN_WALLUST)
        executable(bin_dir / "gsettings", GSETTINGS)
        self.calls = self.home / "calls"
        self.state = self.home / ".local/state/wallust/theme"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("XDG_", "WALLUST_", "APPEARANCE_"))
        } | {
            "HOME": str(self.home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "APPEARANCE_ACCENT": "green",
        }

    def apply(self, *args: str) -> list[str]:
        self.calls.write_text("")
        result = subprocess.run(
            [str(SCRIPT), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # The copy of the config folder is a new temporary one each time.
        return [
            re.sub(r"-d \S+", "-d COPY", line)
            for line in self.calls.read_text().splitlines()
        ]

    def test_no_theme_yet_the_default_to_everything(self) -> None:
        self.assertEqual(
            self.apply(),
            [
                "-q -d COPY theme Oxocarbon-Dark",
                "gsettings set org.gnome.desktop.interface color-scheme prefer-dark",
            ],
        )
        appearance = Path(f"{self.calls}.appearance").read_text()
        self.assertIn("{{ color2 }}", appearance, "the accent picked")
        self.assertIn(
            "BackgroundNormal=1,2,3",
            (self.home / ".config/kdeglobals").read_text(),
            "kdeglobals merged into the config",
        )
        self.assertEqual(self.state.read_text(), "Oxocarbon-Dark\nall\n")

    def test_shell_only(self) -> None:
        shell_only = [f"-q -C {WALLUST}/shell.toml -s theme Nord"]
        self.assertEqual(
            self.apply("--shell-only", "Nord"),
            shell_only,
            "the palette alone, terminals untouched",
        )
        self.assertEqual(self.state.read_text(), "Nord\nshell-only\n")
        self.assertEqual(self.apply(), shell_only, "again, the same way")

    def test_a_saved_scheme_goes_through_cs(self) -> None:
        scheme = next(WALLUST.glob("colorschemes/*.json")).stem
        self.assertEqual(self.apply(scheme)[0], f"-q -d COPY cs {scheme}.json")

    def test_from_an_image(self) -> None:
        self.assertEqual(
            self.apply("--from", "/pictures/Lake.View.jpg")[:2],
            [
                "-q -s -T run --save-scheme /pictures/Lake.View.jpg",
                "-q -d COPY theme Lake",
            ],
            "a scheme from the image, applied by its name",
        )
        self.assertEqual(self.state.read_text(), "Lake\nall\n")


if __name__ == "__main__":
    unittest.main()
