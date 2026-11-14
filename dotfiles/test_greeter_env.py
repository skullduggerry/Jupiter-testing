"""etc/greetd/quickshell/greeter-env.py: the sessions the login screen can
start, each with the argv greetd's start_session takes, whether fprintd has
a reader (through a stand-in gdbus), and what it prints.
Who it offers is security/test_login_screen.py's.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from harness import DOTFILES, executable, load, temporary

HELPER = DOTFILES / "etc/greetd/quickshell/greeter-env.py"
helper = load(HELPER)


class Sessions(unittest.TestCase):
    def test_sessions_with_their_argv(self) -> None:
        tmp = temporary(self)
        sessions = tmp / "wayland-sessions"
        sessions.mkdir()
        (sessions / "hyprland-uwsm.desktop").write_text(
            "[Desktop Entry]\nName=Hyprland (uwsm-managed)\n"
            'Exec=uwsm start -e -D Hyprland "hyprland.desktop"\n'
            "[Desktop Action Other]\nName=Not this\nExec=not-this\n"
        )
        (sessions / "broken.desktop").write_text(
            '[Desktop Entry]\nName=Broken\nExec=sh -c "unbalanced\n'
        )
        (sessions / "unnamed.desktop").write_text(
            "[Desktop Entry]\nExec=something\n"
        )
        (sessions / "notes.txt").write_text("not a session\n")
        self.assertEqual(
            helper.list_sessions((str(sessions), str(tmp / "missing"))),
            [
                {
                    "id": "hyprland-uwsm",
                    "name": "Hyprland (uwsm-managed)",
                    "exec": 'uwsm start -e -D Hyprland "hyprland.desktop"',
                    "command": [
                        "uwsm",
                        "start",
                        "-e",
                        "-D",
                        "Hyprland",
                        "hyprland.desktop",
                    ],
                }
            ],
            "quotes and other groups handled, broken ones left out",
        )


class ThisMachine(unittest.TestCase):
    """The machine the tests run on, as the greeter sees it."""

    @unittest.skipUnless(
        Path("/usr/share/wayland-sessions").is_dir(), "no sessions installed"
    )
    def test_someone_to_log_in_to_a_session(self) -> None:
        run = subprocess.run(
            [sys.executable, str(HELPER)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        environment = json.loads(run.stdout)
        self.assertTrue(environment["users"])
        self.assertTrue(
            any(
                "Hyprland" in session["name"]
                for session in environment["sessions"]
            )
        )


class Reader(unittest.TestCase):
    """fprintd's GetDevices, through a stand-in gdbus that records its
    argv and answers as the real one does."""

    def setUp(self) -> None:
        self.bin = temporary(self)
        self.calls = self.bin / "calls"
        self.enterContext(mock.patch.dict(os.environ, {"PATH": str(self.bin)}))

    def gdbus(self, answer: str, status: int = 0) -> None:
        executable(
            self.bin / "gdbus",
            f'#!/bin/sh\necho "$*" >>{self.calls}\n'
            f"printf '%s\\n' \"{answer}\"\nexit {status}\n",
        )

    def test_a_reader(self) -> None:
        self.gdbus("([objectpath '/net/reactivated/Fprint/Device/0'],)")
        self.assertTrue(helper.has_reader())
        self.assertEqual(
            self.calls.read_text().split(),
            [
                "call", "--system", "--dest", "net.reactivated.Fprint",
                "--object-path", "/net/reactivated/Fprint/Manager",
                "--method", "net.reactivated.Fprint.Manager.GetDevices",
            ],
        )  # fmt: skip

    def test_no_reader(self) -> None:
        self.gdbus("(@ao [],)")
        self.assertFalse(helper.has_reader())

    def test_no_fprintd(self) -> None:
        self.gdbus("Error: GDBus.Error:ServiceUnknown", status=1)
        self.assertFalse(helper.has_reader())

    def test_no_gdbus(self) -> None:
        self.assertFalse(helper.has_reader())


if __name__ == "__main__":
    unittest.main()
