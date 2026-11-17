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

    def iso(self) -> Path:
        """A PATH with the stand-ins in bin/ taken out, and only the tools
        bootstrap.sh itself needs: an ISO with neither git nor Python."""
        tools = self.tmp / "iso"
        tools.mkdir()
        for name in ("realpath", "dirname", "basename", "mkdir"):
            found = shutil.which(name)
            assert found, name
            (tools / name).symlink_to(found)
        (self.tmp / "bin/git").unlink()
        (self.tmp / "bin/python3").unlink()
        self.env["PATH"] = f"{self.tmp / 'bin'}:{tools}"
        return tools

    def test_on_arch_s_iso_pacman_brings_git(self) -> None:
        self.iso()
        # pacman installs git into PATH, as it would on the ISO; Python is
        # the ISO's own.
        executable(
            self.tmp / "bin/pacman",
            '#!/bin/sh\necho "pacman $*" >>"$CALLS"\n'
            f'{shutil.which("cp")} "{self.tmp}/git" "{self.tmp}/bin/git"\n',
        )
        executable(self.tmp / "git", GIT)
        executable(self.tmp / "bin/python3", PYTHON)
        home = self.home / "My-installer"
        status, calls, _ = self.run_in_terminal(
            ["/usr/bin/bash", "-s"], stdin=BOOTSTRAP
        )
        self.assertEqual(
            (status, calls),
            (
                0,
                [
                    "pacman -Sy --noconfirm git",
                    f"git clone {REPO} {home}",
                    f"python3 -m jupiter in {home}, typed: yes",
                ],
            ),
        )

    # bootstrap.sh's git() and python3() look for the real program with
    # `type -P`: `command -v` would find the function itself.
    def test_on_the_nixos_iso_git_and_python_come_from_nixpkgs(self) -> None:
        self.iso()
        # nix shell nixpkgs#X --command X ...: the program from a folder of
        # its own, as nixpkgs would bring it, not on PATH.
        nixpkgs = self.tmp / "nixpkgs"
        executable(nixpkgs / "git", GIT)
        executable(nixpkgs / "python3", PYTHON)
        executable(
            self.tmp / "bin/nix",
            '#!/bin/sh\nwhile [ "$1" != shell ]; do shift; done\n'
            'echo "nix shell $2" >>"$CALLS"\nshift 3\n'
            f'program="{nixpkgs}/$1"\nshift\nexec "$program" "$@"\n',
        )
        home = self.home / "My-installer"
        status, calls, _ = self.run_in_terminal(
            ["/usr/bin/bash", "-s", "--", "1"], stdin=BOOTSTRAP
        )
        self.assertEqual(
            (status, calls),
            (
                0,
                [
                    "nix shell nixpkgs#git",
                    f"git clone {REPO} {home}",
                    "nix shell nixpkgs#python3",
                    f"python3 -m jupiter 1 in {home}, typed: yes",
                ],
            ),
            "the answers still come from the terminal",
        )

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
