"""The Kvantum theme's template, .config/wallust/templates/Wallust.svg, is
what scripts/kvantum-template.py makes of the KvMojave theme Kvantum
installs.

So a hand edit to the template, or a Kvantum update that changed KvMojave,
shows up here: change the script instead, or run it again.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from harness import DOTFILES, temporary

SCRIPT = DOTFILES / "scripts/kvantum-template.py"
TEMPLATE = DOTFILES / ".config/wallust/templates/Wallust.svg"
SOURCE = Path("/usr/share/Kvantum/KvMojave/KvMojave.svg")


class KvantumTemplate(unittest.TestCase):
    @unittest.skipUnless(SOURCE.exists(), "needs Kvantum's KvMojave theme")
    def test_the_template_is_what_the_script_makes(self) -> None:
        made = temporary(self) / "Wallust.svg"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(SOURCE), str(made)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            made.read_text(),
            TEMPLATE.read_text(),
            "templates/Wallust.svg is not what scripts/kvantum-template.py "
            "makes of the installed KvMojave: run the script again, or make "
            "the edit in it",
        )


if __name__ == "__main__":
    unittest.main()
