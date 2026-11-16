"""The tests every repo's check.sh shares, but Jupiter-testing's own: it
hands its arguments, as they are, to Jupiter-testing's check.sh, with its
own clone as its repo, and answers what that answered; a missing
Jupiter-testing is cloned first, and one too old to have a check.sh is
named. Here Jupiter-testing is a stand-in whose check.sh records how it was
run.

A module mixes Forwarding into its TestCase and names the script and the
variable it sets: dotfiles/test_check.py, installer/test_check.py,
nixos/test_check.py.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from . import executable, temporary

# A TestCase to the type checker alone: unittest collects every TestCase a
# module holds, and this one has no script to test.
if TYPE_CHECKING:
    Mixin = unittest.TestCase
else:
    Mixin = object

# Records its arguments and the repos it was given, and answers $ANSWER.
CHECK = """#!/bin/sh
echo "$*" >>"$CALLS"
echo "dotfiles=${JUPITER_DOTFILES-} installer=${JUPITER_INSTALLER-} nixos=${JUPITER_NIXOS-}" >>"$CALLS"
exit "${ANSWER:-0}"
"""


class Forwarding(Mixin):
    """Mixed into a TestCase: SCRIPT is the check.sh under test, VARIABLE
    the JUPITER_ variable naming its repo."""

    SCRIPT: ClassVar[Path]
    VARIABLE: ClassVar[str]

    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.testing = self.tmp / "Jupiter-testing"
        executable(self.testing / "check.sh", CHECK)
        self.calls = self.tmp / "calls"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("XDG_", "JUPITER_", "TESTING_REPO"))
        } | {
            "HOME": str(self.tmp / "home"),
            "CALLS": str(self.calls),
            "JUPITER_TESTING": str(self.testing),
        }

    def check(
        self, *arguments: str, script: Path | None = None, answer: int = 0
    ) -> tuple[int, list[str], str]:
        """Its exit code, how the stand-in ran, and what it printed."""
        self.calls.write_text("")
        result = subprocess.run(
            [str(script or self.SCRIPT), *arguments],
            cwd=self.tmp,
            env=self.env | {"ANSWER": str(answer)},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = self.calls.read_text().splitlines()
        return result.returncode, calls, result.stdout + result.stderr

    def test_the_arguments_as_they_are(self) -> None:
        for arguments in (
            (),
            ("lint", "dotfiles", "--fix"),
            ("test", "all", "--security", "-k", "Lock Screen"),
        ):
            with self.subTest(arguments=arguments):
                code, calls, _ = self.check(*arguments)
                self.assertEqual((code, calls[0]), (0, " ".join(arguments)))

    def test_its_clone_is_the_repo(self) -> None:
        _, calls, _ = self.check()
        self.assertIn(f"{self.VARIABLE}={self.SCRIPT.parent}", calls[1])

    def test_the_answer_is_jupiter_testings(self) -> None:
        for answer in (0, 1, 2):
            with self.subTest(answer=answer):
                self.assertEqual(self.check(answer=answer)[0], answer)

    def test_a_missing_jupiter_testing_is_cloned_first(self) -> None:
        origin = self.testing
        git = ["git", "-C", str(origin)]
        author = ["-c", "user.name=test", "-c", "user.email=test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, *author, "commit", "-qm", "init"], check=True)
        self.env["TESTING_REPO"] = str(origin)
        self.env["JUPITER_TESTING"] = str(self.tmp / "clone")
        code, calls, output = self.check("test", "installer")
        self.assertEqual((code, calls[0]), (0, "test installer"))
        self.assertIn("Cloning Jupiter-testing", output)
        self.assertTrue((self.tmp / "clone/check.sh").exists())

    def test_one_that_cannot_be_cloned(self) -> None:
        self.env["TESTING_REPO"] = str(self.tmp / "nowhere")
        self.env["JUPITER_TESTING"] = str(self.tmp / "clone")
        code, calls, output = self.check()
        self.assertEqual((code, calls), (2, []))
        self.assertIn("could not clone", output)

    def test_one_too_old_to_check(self) -> None:
        (self.testing / "check.sh").unlink()
        code, calls, output = self.check()
        self.assertEqual((code, calls), (2, []))
        self.assertIn("has no check.sh: update it", output)
