"""scripts/nixos-check.sh, CI's NixOS checks: what it evaluates and builds
with the laid-out dotfiles, and that one failing check neither hides the
others nor passes.

nix, Hyprland, qs and python3 are stand-ins that record how they were
called: nix "builds" each package as a folder of stand-ins, Hyprland
rejects a config whose path holds $REJECT, and the QML suites exit with
$QML.
"""

from __future__ import annotations

import os
import subprocess
import unittest

from harness import TESTING, executable, temporary

SCRIPT = TESTING / "scripts/nixos-check.sh"
RECORD = 'echo "${0##*/} $*" >> "$CALLS"\n'
NIX = f"""#!/bin/sh
{RECORD}case "$1 $*" in
    eval\\ *) [ -z "${{BROKEN-}}" ] || exit 1; echo /nix/store/x-nixos.drv ;;
    *pkgs.hyprland.out*) echo "$PKGS/hyprland" ;;
    *pkgs.quickshell.out*) echo "$PKGS/quickshell" ;;
    *pkgs.python3.out*) echo "$PKGS/python3" ;;
    *) echo /nix/store/x-helper ;;
esac
"""
HYPRLAND = f"""#!/bin/sh
{RECORD}case " $* " in
    *" --version "*) echo "Hyprland 0.57.1" ;;
    *"${{REJECT:-none}}"*) echo "error: unknown option"; exit 1 ;;
    *) echo "config ok" ;;
esac
"""
QS = f'#!/bin/sh\n{RECORD}echo "qs 0.3.2"\n'
PYTHON = f'#!/bin/sh\n{RECORD}echo "in $PWD"\nexit "${{QML:-0}}"\n'


class NixosCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.root = temporary(self)
        for repo in ("dotfiles", "installer", "testing"):
            (self.root / f"Jupiter-{repo}").mkdir()
        pkgs = self.root / "pkgs"
        executable(self.root / "bin/nix", NIX)
        executable(pkgs / "hyprland/bin/Hyprland", HYPRLAND)
        executable(pkgs / "quickshell/bin/qs", QS)
        executable(pkgs / "python3/bin/python3", PYTHON)
        self.calls = self.root / "calls"
        self.env = {
            "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "PKGS": str(pkgs),
        }

    def run_check(self, **env: str) -> tuple[int, list[str], str]:
        self.calls.write_text("")
        done = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.root,
            env=self.env | env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = self.calls.read_text().splitlines()
        return done.returncode, calls, done.stdout + done.stderr

    def test_everything_checked_with_the_laid_out_dotfiles(self) -> None:
        status, calls, output = self.run_check()
        self.assertEqual(status, 0, output)
        self.assertIn("all NixOS checks passed", output)
        nix = [c for c in calls if c.startswith("nix ")]
        self.assertTrue(nix[0].startswith("nix eval --raw "), nix)
        for call in nix:
            with self.subTest(call=call):
                # The lock as committed, the dotfiles as pushed.
                self.assertIn("--no-write-lock-file", call)
                self.assertIn(
                    "--override-input dotfiles "
                    f"path:{self.root}/Jupiter-dotfiles",
                    call,
                )
        verified = [c for c in calls if "--verify-config" in c]
        self.assertEqual(
            [c.split(" -c ")[1] for c in verified],
            [
                f"{self.root}/Jupiter-dotfiles/.config/hypr/hyprland.lua",
                f"{self.root}/Jupiter-dotfiles/etc/greetd/hyprland.lua",
            ],
        )
        self.assertIn(
            "python3 -m harness.run dotfiles/test_qml.py "
            "dotfiles/security/test_lock_screen.py",
            calls,
        )
        self.assertIn(f"in {self.root}/Jupiter-testing", output)

    def test_a_rejected_config_fails_after_the_qml_suites(self) -> None:
        status, calls, output = self.run_check(REJECT="greetd")
        self.assertEqual(status, 1)
        self.assertIn(
            "FAIL  etc/greetd/hyprland.lua does not verify with NixOS's "
            "Hyprland",
            output,
        )
        self.assertNotIn("all NixOS checks passed", output)
        self.assertTrue([c for c in calls if c.startswith("python3 ")])

    def test_failing_qml_suites_fail(self) -> None:
        status, _, output = self.run_check(QML="1")
        self.assertEqual(status, 1)
        self.assertIn(
            "FAIL  the QML suites fail in NixOS's Quickshell", output
        )

    def test_a_system_that_does_not_evaluate_stops_there(self) -> None:
        status, calls, output = self.run_check(BROKEN="1")
        self.assertEqual(status, 1)
        self.assertIn("FAIL  hosts/example does not evaluate", output)
        self.assertEqual(len(calls), 1, calls)


if __name__ == "__main__":
    unittest.main()
