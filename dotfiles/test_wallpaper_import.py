"""Adding a wallpaper, services/wallpaper-import.sh, with a stand-in zenity.

The picked image is copied into the library and its new path printed; the
same image again changes nothing, another one under a taken name gets a
number, and a cancelled dialog leaves the library alone.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from harness import QUICKSHELL, executable, temporary

SCRIPT = QUICKSHELL / "services/wallpaper-import.sh"
# The file dialog: prints $PICKED, or is cancelled when there is none.
ZENITY = """#!/bin/sh
[ -n "$PICKED" ] || exit 1
printf '%s\\n' "$PICKED"
"""


class WallpaperImport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.library = self.tmp / "Wallpapers/Nature"
        executable(self.tmp / "bin/zenity", ZENITY)

    def pick(self, path: Path | None) -> tuple[int, str]:
        result = subprocess.run(
            [str(SCRIPT), str(self.library)],
            env=dict(
                os.environ,
                PICKED=str(path or ""),
                PATH=f"{self.tmp / 'bin'}:{os.environ['PATH']}",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout.strip()

    def test_cancelled(self) -> None:
        self.assertEqual(self.pick(None), (1, ""))
        self.assertFalse(self.library.exists(), "nothing made")

    def test_added_once_and_numbered(self) -> None:
        first = self.tmp / "Downloads/lake.view.jpg"
        first.parent.mkdir()
        first.write_bytes(b"one lake")
        second = self.tmp / "lake.view.jpg"
        second.write_bytes(b"another lake")
        landed = self.library / "lake.view.jpg"
        self.assertEqual(self.pick(first), (0, str(landed)))
        self.assertEqual(landed.read_bytes(), b"one lake")
        self.assertEqual(self.pick(first), (0, str(landed)), "the same again")
        numbered = self.library / "lake.view-1.jpg"
        self.assertEqual(self.pick(second), (0, str(numbered)))
        self.assertEqual(numbered.read_bytes(), b"another lake")
        self.assertEqual(len(list(self.library.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
