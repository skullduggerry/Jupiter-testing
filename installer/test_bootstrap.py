"""bootstrap.sh's way to the installer: fetched or updated, then run with
the phases it was given, its answers read from the terminal.

git and python3 are stand-ins on a PATH of their own that record how they
were called, and the home is a temporary one. The script ends on
`python3 -m jupiter … </dev/tty`, so each run gets a terminal of its own (a
pty), which is also where the stand-in installer reads an answer from.
"""

from __future__ import annotations

import os
import pty
import shutil
import unittest
from pathlib import Path

from harness import INSTALLER, executable, temporary

BOOTSTRAP = INSTALLER / "bootstrap.sh"
REPO = "https://example.org/me/My-installer.git"
# Records its arguments; `clone URL DIR` leaves an installer in DIR, and
# `pull` fails where $OFFLINE is set.
GIT = """#!/bin/sh
echo "git $*" >>"$CALLS"
case " $* " in
    *" clone "*) mkdir -p "$3/jupiter" "$3/.git" && : >"$3/jupiter/__main__.py" ;;
    *" pull "*) [ -z "${OFFLINE-}" ] || exit 1 ;;
esac
"""
# The installer: where it runs, its arguments and a line typed at it.
PYTHON = """#!/bin/sh
read -r answer
echo "python3 $* in $PWD, typed: $answer" >>"$CALLS"
"""


class Bootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.calls = self.tmp / "calls"
        executable(self.tmp / "bin/git", GIT)
        executable(self.tmp / "bin/python3", PYTHON)
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.tmp / 'bin'}:/usr/bin",
            "CALLS": str(self.calls),
            "INSTALLER_REPO": REPO,
        }

    def clone(self, path: Path) -> Path:
        """A clone of the installer at path: bootstrap.sh in its place."""
        (path / "jupiter").mkdir(parents=True)
        (path / "jupiter/__main__.py").write_text("")
        (path / ".git").mkdir()
        shutil.copy(BOOTSTRAP, path / "bootstrap.sh")
        return path / "bootstrap.sh"

    def run_in_terminal(
        self, command: list[str], stdin: Path | None = None
    ) -> tuple[int, list[str], str]:
        """Run command on a terminal of its own where "yes" is typed; with
        stdin, that file is its standard input, as a pipe from curl is."""
        self.calls.write_text("")
        pid, terminal = pty.fork()
        if pid == 0:
            if stdin is not None:
                os.dup2(os.open(stdin, os.O_RDONLY), 0)
            os.execve(command[0], command, self.env)
        os.write(terminal, b"yes\n")
        shown = b""
        while True:
            try:
                data = os.read(terminal, 4096)
            except OSError:
                break
            if not data:
                break
            shown += data
        os.close(terminal)
        status = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
        return status, self.calls.read_text().splitlines(), shown.decode()

    def test_a_clone_updates_and_runs_itself_wherever_it_is(self) -> None:
        clone = self.tmp / "src/installer"
        script = self.clone(clone)
        status, calls, _ = self.run_in_terminal([str(script), "2", "3"])
        self.assertEqual(
            (status, calls),
            (
                0,
                [
                    f"git -C {clone} pull --ff-only",
                    f"python3 -m jupiter 2 3 in {clone}, typed: yes",
                ],
            ),
        )
        self.assertFalse(
            (self.home / "My-installer").exists(), "no second copy in the home"
        )

    def test_piped_from_curl_it_is_cloned_into_the_home(self) -> None:
        home = self.home / "My-installer"
        command = ["/usr/bin/bash", "-s", "--", "1"]
        status, calls, _ = self.run_in_terminal(command, stdin=BOOTSTRAP)
        self.assertEqual(
            (status, calls),
            (
                0,
                [
                    f"git clone {REPO} {home}",
                    f"python3 -m jupiter 1 in {home}, typed: yes",
                ],
            ),
            "the answers come from the terminal, not from the pipe",
        )

        status, calls, _ = self.run_in_terminal(command, stdin=BOOTSTRAP)
        self.assertEqual(calls[0], f"git -C {home} pull --ff-only", "again")

    def test_a_clone_it_cannot_update_runs_as_it_is(self) -> None:
        clone = self.tmp / "Jupiter-installer"
        script = self.clone(clone)
        self.env["OFFLINE"] = "1"
        status, calls, shown = self.run_in_terminal([str(script), "4"])
        self.assertEqual(status, 0)
        self.assertEqual(
            calls[-1], f"python3 -m jupiter 4 in {clone}, typed: yes"
        )
        self.assertIn(f"could not update {clone}", shown)

    def test_a_copy_without_git_is_not_cloned_over(self) -> None:
        clone = self.tmp / "unpacked"
        script = self.clone(clone)
        (clone / ".git").rmdir()
        status, calls, _ = self.run_in_terminal([str(script)])
        self.assertEqual(
            (status, calls),
            (0, [f"python3 -m jupiter in {clone}, typed: yes"]),
        )


if __name__ == "__main__":
    unittest.main()
