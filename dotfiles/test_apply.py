"""Applying a theme, .config/wallust/apply.sh, against a stand-in wallust and
gsettings in a made-up home.

A theme renders every template from a copy of templates/ whose
appearance.jinja holds the Settings app's choices, merges kdeglobals, tells
the portal dark or light, and is recorded with its scope; --shell-only
renders the shell's palette alone, and without -s nothing; no argument
applies the recorded theme again the same way, or the default; a theme
saved in colorschemes/ goes through `cs`; --from generates a scheme first
and applies it by the image's name. On NixOS, the home-manager generation
Jupiter-installer builds (a stand-in here, whose activations record
themselves) is switched to the theme's specialisation, or the plain one,
unless it is already active.
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
# A home-manager generation's activate: records itself, then marks its
# generation the active one, where home-manager does.
ACTIVATE = """#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd -P)
printf 'activate %s %s\\n' "${here##*/}" "$HOME_MANAGER_BACKUP_EXT" >>"$CALLS"
[ -z "${BROKEN-}" ] || exit 1
mkdir -p "$HOME/.local/state/home-manager/gcroots"
ln -sfn "$here" "$HOME/.local/state/home-manager/gcroots/current-home"
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
            # Not NixOS, unless a test makes it so, whatever this machine is.
            "JUPITER_HOME_GENERATION": str(self.home / "no-generation"),
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

    def nixos(self, *themes: str) -> None:
        """A home-manager generation with a specialisation per theme."""
        generation = self.home / "home"
        executable(generation / "activate", ACTIVATE)
        for theme in themes:
            executable(
                generation / "specialisation" / theme / "activate", ACTIVATE
            )
        self.env["JUPITER_HOME_GENERATION"] = str(generation)

    def activations(self, calls: list[str]) -> list[str]:
        return [call for call in calls if call.startswith("activate ")]

    def test_on_nixos_a_theme_switches_to_its_specialisation(self) -> None:
        self.nixos("Nord", "Oxocarbon-Dark")
        self.assertEqual(
            self.activations(self.apply("Nord")),
            ["activate Nord before-stylix"],
        )
        self.assertEqual(
            self.activations(self.apply("Nord")),
            [],
            "already active: no activation",
        )
        self.assertEqual(
            self.activations(self.apply()), [], "nor at the next login"
        )
        self.assertEqual(
            self.activations(self.apply("Oxocarbon-Dark")),
            ["activate Oxocarbon-Dark before-stylix"],
        )

    def test_on_nixos_another_theme_takes_the_plain_generation(self) -> None:
        self.nixos("Nord")
        self.apply("Nord")
        self.assertEqual(
            self.activations(self.apply("Dracula")),
            ["activate home before-stylix"],
            "the default theme's, rather than another theme's colours",
        )
        self.assertEqual(self.activations(self.apply("Dracula")), [])

    def test_on_nixos_shell_only_leaves_the_apps(self) -> None:
        self.nixos("Nord")
        self.assertEqual(
            self.activations(self.apply("--shell-only", "Nord")), []
        )

    def test_on_nixos_a_failed_activation_still_applies_the_theme(
        self,
    ) -> None:
        self.nixos("Nord")
        self.env["BROKEN"] = "1"
        self.calls.write_text("")
        result = subprocess.run(
            [str(SCRIPT), "Nord"],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("home-manager's activation failed", result.stderr)
        self.assertEqual(self.state.read_text(), "Nord\nall\n")


if __name__ == "__main__":
    unittest.main()
