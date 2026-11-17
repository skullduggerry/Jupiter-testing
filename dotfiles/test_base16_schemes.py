"""The schemes NixOS's Stylix takes, .config/wallust/base16/*.json, as
scripts/base16-schemes.py renders them with the real wallust (with -s, its
cache in a temporary folder).

Each committed file is what the script makes of its theme now, so a change
to the template, to palette.jinja or to wallust shows up here; its slots
are the shell's palette as base16 names it, and the ones nvim's template
gets; a theme named is added, and one wallust does not know fails, naming
it, without a file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from harness import DOTFILES, temporary

SCRIPT = DOTFILES / "scripts/base16-schemes.py"
WALLUST_DIR = DOTFILES / ".config/wallust"
SCHEMES = WALLUST_DIR / "base16"
WALLUST = shutil.which(
    "wallust",
    path=os.environ.get("PATH", "")
    + os.pathsep
    + str(Path.home() / ".cargo/bin"),
)
# The terminal colours each accent slot is, as Colors.qml reads them.
ACCENTS = {
    "base08": "color1",
    "base0A": "color3",
    "base0B": "color2",
    "base0C": "color6",
    "base0D": "color4",
    "base0E": "color5",
}


def render(theme: str, template: str, root: Path) -> str:
    """One of the dotfiles' templates, rendered for a theme by wallust."""
    config = root / theme / template
    shutil.copytree(WALLUST_DIR / "templates", config / "templates")
    out = config / "out"
    (config / "wallust.toml").write_text(
        f"[templates]\nt = {{ src = '{template}', target = '{out}' }}\n"
    )
    assert WALLUST is not None
    subprocess.run(
        [WALLUST, "-d", str(config), "-q", "-s", "theme", theme],
        env=dict(os.environ, XDG_CACHE_HOME=str(root / "cache")),
        check=True,
        capture_output=True,
    )
    return out.read_text()


@unittest.skipUnless(WALLUST, "needs wallust")
class Schemes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)

    def make(self, *themes: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "-o",
                str(self.tmp / "out"),
                *themes,
            ],
            env=dict(os.environ, XDG_CACHE_HOME=str(self.tmp / "cache")),
            capture_output=True,
            text=True,
            check=False,
        )

    def scheme(self, theme: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            (self.tmp / "out" / f"{theme}.json").read_text()
        )
        return loaded

    def test_the_committed_schemes_are_what_the_script_makes(self) -> None:
        themes = sorted(path.stem for path in SCHEMES.glob("*.json"))
        self.assertIn("Oxocarbon-Dark", themes, "apply.sh's default")
        result = self.make(*themes)
        self.assertEqual(result.returncode, 0, result.stderr)
        for theme in themes:
            with self.subTest(theme):
                self.assertEqual(
                    (self.tmp / "out" / f"{theme}.json").read_text(),
                    (SCHEMES / f"{theme}.json").read_text(),
                    f"base16/{theme}.json is not what "
                    "scripts/base16-schemes.py makes of it: run the script",
                )

    def test_the_slots_are_the_shells_palette(self) -> None:
        for theme, variant in (
            ("Oxocarbon-Dark", "dark"),
            ("Catppuccin-Latte", "light"),
        ):
            with self.subTest(theme):
                self.assertEqual(self.make(theme).returncode, 0)
                scheme = self.scheme(theme)
                palette = json.loads(
                    render(theme, "quickshell.json", self.tmp)
                )
                self.assertEqual(
                    (scheme["system"], scheme["name"], scheme["variant"]),
                    ("base16", theme, variant),
                )
                slots = scheme["palette"]
                self.assertEqual(
                    slots["base00"], palette["background"].lower()
                )
                self.assertEqual(
                    slots["base05"], palette["foreground"].lower()
                )
                for slot, colour in ACCENTS.items():
                    self.assertEqual(slots[slot], palette[colour].lower())

    def test_nvim_gets_the_same_slots(self) -> None:
        theme = "Gruvbox-Dark"
        self.assertEqual(self.make(theme).returncode, 0)
        nvim = dict(
            re.findall(
                r"(base0[0-9A-F]) = '(#[0-9a-fA-F]{6})'",
                render(theme, "nvim.lua", self.tmp),
            )
        )
        self.assertEqual(len(nvim), 16)
        self.assertEqual(
            {slot: colour.lower() for slot, colour in nvim.items()},
            self.scheme(theme)["palette"],
        )

    def test_a_saved_colorscheme_goes_through_cs(self) -> None:
        theme = next(WALLUST_DIR.glob("colorschemes/*.json")).stem
        self.assertEqual(self.make(theme).returncode, 0)
        saved = json.loads(
            (WALLUST_DIR / "colorschemes" / f"{theme}.json").read_text()
        )
        self.assertEqual(
            self.scheme(theme)["palette"]["base00"],
            saved["background"].lower(),
        )

    def test_an_unknown_theme_fails_without_a_file(self) -> None:
        result = self.make("No-Such-Theme", "Nord")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No-Such-Theme", result.stderr)
        self.assertFalse((self.tmp / "out/No-Such-Theme.json").exists())
        self.assertTrue((self.tmp / "out/Nord.json").exists())


class WithoutWallust(unittest.TestCase):
    def test_says_so(self) -> None:
        tmp = temporary(self)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "-o", str(tmp)],
            env=dict(os.environ, PATH=str(tmp), HOME=str(tmp)),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            (result.returncode, result.stderr.strip()),
            (1, "wallust is not installed"),
        )


if __name__ == "__main__":
    unittest.main()
