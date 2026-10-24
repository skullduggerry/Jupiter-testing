"""Screen Record's helper, services/screen-record.sh, with stand-ins for
xdg-user-dir and setpriv, so nothing records.

It prints the new file's path first, in Recordings/ of the videos folder,
or of ~/Videos where xdg-user-dirs has none (it names $HOME then), and hands
wf-recorder to setpriv so the recording ends with the shell.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from harness import QUICKSHELL, executable, temporary

SCRIPT = QUICKSHELL / "services/screen-record.sh"
XDG_USER_DIR = """#!/bin/sh
printf '%s\\n' "$VIDEOS"
"""
SETPRIV = """#!/bin/sh
printf '%s\\n' "$*" >"$HOME/setpriv"
"""


class ScreenRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.home = temporary(self)
        executable(self.home / "bin/xdg-user-dir", XDG_USER_DIR)
        executable(self.home / "bin/setpriv", SETPRIV)

    def record(self, videos: str) -> Path:
        result = subprocess.run(
            [str(SCRIPT), "DP-2"],
            env=dict(
                os.environ,
                HOME=str(self.home),
                VIDEOS=videos,
                PATH=f"{self.home / 'bin'}:{os.environ['PATH']}",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip())

    def test_a_file_in_recordings(self) -> None:
        file = self.record(str(self.home / "Films"))
        self.assertEqual(file.parent, self.home / "Films/Recordings")
        self.assertTrue(file.parent.is_dir())
        self.assertRegex(file.name, r"^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.mp4$")
        self.assertEqual(
            (self.home / "setpriv").read_text().strip(),
            f"--pdeathsig INT wf-recorder -o DP-2 -f {file}",
            "wf-recorder ends with the shell",
        )

    def test_without_a_videos_folder_of_its_own(self) -> None:
        for videos in (str(self.home) + "/", ""):
            with self.subTest(videos=videos):
                self.assertEqual(
                    self.record(videos).parent, self.home / "Videos/Recordings"
                )


if __name__ == "__main__":
    unittest.main()
