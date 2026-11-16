""".config/.zshrc in zsh, in a throwaway home: its plugins are found
wherever the system keeps them (Arch's /usr/share/zsh/plugins/<name>,
NixOS's profile on XDG_DATA_DIRS, some there in share/<name>), each once and
in its order, and a missing one is left out without an error.

The plugins are stand-ins that say they were sourced.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

from harness import DOTFILES, environment, temporary

ZSHRC = DOTFILES / ".config/.zshrc"
PLUGINS = (
    "zsh-autosuggestions",
    "zsh-history-substring-search",
    "zsh-syntax-highlighting",
)


@unittest.skipUnless(shutil.which("zsh"), "needs zsh")
class Plugins(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        (self.tmp / "home").mkdir()

    def plugin(self, share: Path, name: str, nested: bool = True) -> None:
        folder = share / "zsh/plugins" / name if nested else share / name
        folder.mkdir(parents=True)
        (folder / f"{name}.zsh").write_text(
            f'print "{name} from {share.name}"\n'
        )

    def zsh(self, data_dirs: str | None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["zsh", "-f", "-c", f"source {ZSHRC}"],
            env=environment(
                HOME=str(self.tmp / "home"), XDG_DATA_DIRS=data_dirs
            ),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_from_the_systems_data_folders_in_order(self) -> None:
        nix = self.tmp / "nix"
        other = self.tmp / "other"
        self.plugin(nix, "zsh-autosuggestions")
        self.plugin(nix, "zsh-syntax-highlighting", nested=False)
        self.plugin(other, "zsh-history-substring-search")
        # A later folder's copy of one found already is not sourced again.
        self.plugin(other, "zsh-autosuggestions")
        done = self.zsh(f"{nix}:{other}")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            done.stdout.splitlines(),
            [
                "zsh-autosuggestions from nix",
                "zsh-history-substring-search from other",
                "zsh-syntax-highlighting from nix",
            ],
        )

    def test_none_found_is_no_error(self) -> None:
        for data_dirs in (str(self.tmp / "empty"), "", None):
            with self.subTest(data_dirs=data_dirs):
                done = self.zsh(data_dirs)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertNotIn("no such file", done.stderr)
                for name in PLUGINS:
                    if not Path(
                        f"/usr/share/zsh/plugins/{name}/{name}.zsh"
                    ).exists():
                        self.assertNotIn(name, done.stdout)


if __name__ == "__main__":
    unittest.main()
