"""The dotfiles' check.sh, which hands the checks to Jupiter-testing's
(harness/forwarding.py says what every repo's does)."""

from __future__ import annotations

import unittest

from harness import DOTFILES
from harness.forwarding import Forwarding


class Check(Forwarding, unittest.TestCase):
    SCRIPT = DOTFILES / "check.sh"
    VARIABLE = "dotfiles"


if __name__ == "__main__":
    unittest.main()
