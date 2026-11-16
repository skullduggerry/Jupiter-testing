"""Jupiter-nixos' check.sh, and `bootstrap.sh check|lint|test`, which runs
it: both hand the checks to Jupiter-testing's (harness/forwarding.py says
what every repo's does), with JUPITER_NIXOS its own clone. Here also:
checking never updates the repo, as the Arch installer's (installer's
test_check).
"""

from __future__ import annotations

import unittest

from harness import NIXOS, executable
from harness.forwarding import Forwarding

BOOTSTRAP = NIXOS / "bootstrap.sh"
GIT = """#!/bin/sh
echo "git $*" >>"$CALLS"
exit 1
"""


class Check(Forwarding, unittest.TestCase):
    SCRIPT = NIXOS / "check.sh"
    VARIABLE = "nixos"

    def test_the_dotfiles_where_phase_3_cloned_them(self) -> None:
        dotfiles = self.tmp / "home/Jupiter-dotfiles"
        dotfiles.mkdir(parents=True)
        self.assertIn(f"dotfiles={dotfiles} ", self.check()[1][1])
        self.env["JUPITER_DOTFILES"] = "/elsewhere"
        self.assertIn("dotfiles=/elsewhere ", self.check()[1][1])


class Bootstrap(Check):
    """bootstrap.sh check|lint|test is check.sh, with no update first."""

    def check(
        self, *arguments: str, script: object = None, answer: int = 0
    ) -> tuple[int, list[str], str]:
        return super().check(
            *(arguments or ("check",)), script=BOOTSTRAP, answer=answer
        )

    def test_the_arguments_as_they_are(self) -> None:
        for arguments in (("check",), ("lint", "nixos", "--fix")):
            with self.subTest(arguments=arguments):
                code, calls, _ = self.check(*arguments)
                self.assertEqual((code, calls[0]), (0, " ".join(arguments)))

    def test_the_repo_is_not_updated_first(self) -> None:
        executable(self.tmp / "bin/git", GIT)
        self.env["PATH"] = f"{self.tmp / 'bin'}:{self.env['PATH']}"
        _, calls, _ = self.check("check")
        self.assertFalse([call for call in calls if call.startswith("git ")])


if __name__ == "__main__":
    unittest.main()
