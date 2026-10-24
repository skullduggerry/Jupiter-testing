"""Restarting hypridle on a new config, services/hypridle-restart.sh.

Only the hypridle of this Hyprland goes, the one whose environment has its
instance signature: another session's keeps running. Here two `sleep`s with
signatures of their own stand in for them, a stand-in pgrep names only
those, and stand-ins for hypridle and uwsm-app record how they were started
(in a scope of its own under uwsm).
"""

from __future__ import annotations

import os
import subprocess
import unittest

from harness import QUICKSHELL, executable, temporary

SCRIPT = QUICKSHELL / "services/hypridle-restart.sh"
PGREP = """#!/bin/sh
cat "$IDLERS"
"""
RECORD = """#!/bin/sh
printf '%s\\n' "${0##*/} $*" >>"$STARTED"
"""


class Restart(unittest.TestCase):
    def setUp(self) -> None:
        tmp = temporary(self)
        self.bin = tmp / "bin"
        executable(self.bin / "pgrep", PGREP)
        executable(self.bin / "hypridle", RECORD)
        executable(self.bin / "uwsm-app", RECORD)
        self.idlers = tmp / "idlers"
        self.started = tmp / "started"
        self.ours = self.idler("this-session")
        self.theirs = self.idler("another-session")
        self.idlers.write_text(f"{self.ours.pid}\n{self.theirs.pid}\n")

    def idler(self, signature: str) -> subprocess.Popen[bytes]:
        env = dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE=signature)
        process = subprocess.Popen(["sleep", "60"], env=env)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def restart(self, **extra: str) -> list[str]:
        self.started.write_text("")
        env = dict(
            os.environ,
            HYPRLAND_INSTANCE_SIGNATURE="this-session",
            IDLERS=str(self.idlers),
            STARTED=str(self.started),
            PATH=f"{self.bin}:{os.environ['PATH']}",
        )
        env.pop("UWSM_FINALIZE_VARNAMES", None)
        env.update(extra)
        subprocess.run(
            [str(SCRIPT), "/state/hypridle.conf"],
            env=env,
            check=False,
            timeout=10,
        )
        return self.started.read_text().splitlines()

    def test_only_this_sessions_is_restarted(self) -> None:
        self.assertEqual(self.restart(), ["hypridle -c /state/hypridle.conf"])
        self.assertEqual(self.ours.wait(timeout=5), -15, "this one stopped")
        self.assertIsNone(self.theirs.poll(), "another session's kept")

    def test_under_uwsm_in_a_scope_of_its_own(self) -> None:
        self.assertEqual(
            self.restart(UWSM_FINALIZE_VARNAMES="X"),
            ["uwsm-app -s b -- hypridle -c /state/hypridle.conf"],
        )


if __name__ == "__main__":
    unittest.main()
