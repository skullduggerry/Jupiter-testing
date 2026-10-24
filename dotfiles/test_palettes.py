"""The Settings app's theme catalogue, .config/wallust/palettes.py, rendered
by the real wallust (with -s, its cache in a temporary folder).

The themes saved in colorschemes/ come first, marked custom and coloured as
saved; wallust's built-ins follow; every palette has the colours the shell
reads; and a theme wallust cannot render is left out rather than failing
the catalogue.
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

from harness import DOTFILES, executable, temporary

WALLUST_DIR = DOTFILES / ".config/wallust"
SCRIPT = WALLUST_DIR / "palettes.py"
KEYS = {
    "background",
    "foreground",
    "cursor",
    *(f"color{n}" for n in range(16)),
}
WALLUST = shutil.which(
    "wallust",
    path=os.environ.get("PATH", "")
    + os.pathsep
    + str(Path.home() / ".cargo/bin"),
)


def saved_colour(scheme: dict[str, Any], index: int) -> str:
    """A colour of a saved scheme, in either of the forms wallust reads: a
    "color" list, or color0 to color15 as `wallust run --save-scheme`
    writes them."""
    if "color" in scheme:
        return str(scheme["color"][index])
    return str(scheme[f"color{index}"])


@unittest.skipUnless(WALLUST, "needs wallust")
class Palettes(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.env = dict(os.environ, XDG_CACHE_HOME=str(self.tmp / "cache"))

    def catalogue(self) -> list[dict[str, Any]]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        themes: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        return themes

    def test_the_catalogue(self) -> None:
        themes = self.catalogue()
        saved = sorted(s.stem for s in WALLUST_DIR.glob("colorschemes/*.json"))
        self.assertEqual(
            [t["name"] for t in themes[: len(saved)]], saved, "first"
        )
        self.assertEqual([t["name"] for t in themes if t["custom"]], saved)
        self.assertGreater(len(themes), len(saved) + 10, "the built-ins after")
        self.assertEqual(
            [t["name"] for t in themes if set(t["palette"]) != KEYS],
            [],
            "every palette has what the shell reads",
        )
        self.assertEqual(
            [
                t["name"]
                for t in themes
                if not all(
                    re.fullmatch(r"#[0-9A-Fa-f]{6}", value)
                    for value in t["palette"].values()
                )
            ],
            [],
            "as colours",
        )
        for index, name in enumerate(saved):
            with self.subTest(f"{name} as saved"):
                scheme = json.loads(
                    (WALLUST_DIR / "colorschemes" / f"{name}.json").read_text()
                )
                palette = themes[index]["palette"]
                self.assertEqual(
                    (palette["background"].lower(), palette["color1"].lower()),
                    (
                        scheme["background"].lower(),
                        saved_colour(scheme, 1).lower(),
                    ),
                )

    def test_a_theme_that_does_not_render_is_left_out(self) -> None:
        themes = self.catalogue()
        failing = themes[-1]["name"]
        executable(
            self.tmp / "bin/wallust",
            f'#!/bin/sh\ncase " $* " in *" theme {failing} "*) exit 1 ;; esac\nexec {WALLUST} "$@"\n',
        )
        self.env["PATH"] = f"{self.tmp / 'bin'}:{os.environ['PATH']}"
        self.assertEqual(
            [t["name"] for t in self.catalogue()],
            [t["name"] for t in themes if t["name"] != failing],
        )


if __name__ == "__main__":
    unittest.main()
