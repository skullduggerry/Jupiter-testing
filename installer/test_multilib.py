"""Phase 3's [multilib]: enabled in pacman.conf where a listed package is in
no enabled repository and the file has it commented out, as Arch ships it;
left alone otherwise.

pacman (-Slq lists $KNOWN) and sudo (runs `install` for real on the
temporary pacman.conf, records the rest) are stand-ins on a PATH of their
own.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import phase3

SHIPPED = """\
[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist

#[multilib]
#Include = /etc/pacman.d/mirrorlist
"""
STAND_IN = f"""#!{sys.executable}
import json, os, shutil, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps([name, *args]) + "\\n")
if name == "pacman" and args == ["-Slq"]:
    print("\\n".join(os.environ["KNOWN"].split()))
if name == "sudo" and args[0] == "install":
    if os.path.exists(args[-1]):
        shutil.copy(args[-1], args[-1] + "~")
    shutil.copy(args[-2], args[-1])
"""


class Multilib(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.conf = tmp / "pacman.conf"
        self.conf.write_text(SHIPPED)
        self.calls = tmp / "calls"
        self.calls.write_text("")
        for name in ("pacman", "sudo"):
            (tmp / name).write_text(STAND_IN)
            (tmp / name).chmod(0o755)
        self.enterContext(mock.patch.object(phase3, "PACMAN_CONF", self.conf))
        self.env = {
            "PATH": str(tmp),
            "CALLS": str(self.calls),
            "KNOWN": "mpv ufw",
        }
        self.printed = self.enterContext(mock.patch("builtins.print"))

    def run_step(self, names: list[str]) -> list[list[str]]:
        with mock.patch.dict(os.environ, self.env):
            phase3._multilib(names)
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]

    def test_enabled_for_a_package_only_it_has(self) -> None:
        calls = self.run_step(["mpv", "steam"])
        self.assertIn(
            "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n",
            self.conf.read_text(),
        )
        self.assertNotIn("#[multilib]", self.conf.read_text())
        self.assertEqual(Path(f"{self.conf}~").read_text(), SHIPPED)
        # A full sync, not a bare -Sy: no partial upgrade.
        self.assertEqual(calls[-1], ["sudo", "pacman", "-Syu", "--noconfirm"])
        said = " ".join(
            str(a) for c in self.printed.call_args_list for a in c.args
        )
        self.assertIn("Enabled [multilib]", said)
        self.assertIn("steam", said)

    def test_left_alone_when_every_package_is_known(self) -> None:
        calls = self.run_step(["mpv", "ufw"])
        self.assertEqual(self.conf.read_text(), SHIPPED)
        self.assertEqual(calls, [["pacman", "-Slq"]])

    def test_left_alone_when_already_enabled_or_changed(self) -> None:
        for text in (
            SHIPPED.replace("#[multilib]\n#Include", "[multilib]\nInclude"),
            SHIPPED.replace(
                "#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n", ""
            ),
        ):
            with self.subTest(text=text[-40:]):
                self.conf.write_text(text)
                self.calls.write_text("")
                calls = self.run_step(["steam"])
                self.assertEqual(self.conf.read_text(), text)
                self.assertEqual(calls, [["pacman", "-Slq"]])


if __name__ == "__main__":
    unittest.main()
