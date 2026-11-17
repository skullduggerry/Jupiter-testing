"""Phase 3's [multilib]: enabled in pacman.conf where a listed package is in
no enabled repository and the file has it commented out, as Arch ships it;
left alone otherwise. And the 32-bit drivers of the installed graphics
drivers, for a package from [multilib], rather than the first provider
pacman's --noconfirm takes (NVIDIA's). And pacman's look (Color, ILoveCandy,
VerbosePkgLists), turned on in [options] for pacman and paru.

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

from jupiter.arch import phase3

OPTIONS = """\
[options]
#UseSyslog
#Color
#NoProgressBar
CheckSpace
#VerbosePkgLists
ParallelDownloads = 5

"""
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
if name == "pacman" and args == ["-Slq", "multilib"]:
    if not os.environ.get("MULTILIB"):
        sys.exit(1)  # error: repository "multilib" was not found
    print("\\n".join(os.environ["MULTILIB"].split()))
if name == "pacman" and args == ["-Qq"]:
    print("\\n".join(os.environ["INSTALLED"].split()))
if name == "sudo" and args[0] == "install":
    if os.path.exists(args[-1]):
        shutil.copy(args[-1], args[-1] + "~")
    shutil.copy(args[-2], args[-1])
"""


class Pacman(unittest.TestCase):
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


class Multilib(Pacman):
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


class Look(Pacman):
    def look(self) -> list[list[str]]:
        with mock.patch.dict(os.environ, self.env):
            phase3._look()
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]

    def test_turned_on_as_arch_ships_it(self) -> None:
        self.conf.write_text(OPTIONS + SHIPPED)
        calls = self.look()
        self.assertEqual(
            self.conf.read_text(),
            OPTIONS.replace("#Color\n", "Color\nILoveCandy\n").replace(
                "#VerbosePkgLists", "VerbosePkgLists"
            )
            + SHIPPED,
        )
        self.assertEqual(Path(f"{self.conf}~").read_text(), OPTIONS + SHIPPED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:4], ["sudo", "install", "-b", "-m"])

    def test_left_alone_once_on(self) -> None:
        self.conf.write_text(OPTIONS + SHIPPED)
        self.look()
        looked = self.conf.read_text()
        self.calls.write_text("")
        self.assertEqual(self.look(), [])
        self.assertEqual(self.conf.read_text(), looked)

    def test_an_option_on_elsewhere_is_not_repeated(self) -> None:
        text = "[options]\nILoveCandy\nColor\n\n" + SHIPPED
        self.conf.write_text(text)
        self.look()
        self.assertEqual(
            self.conf.read_text(),
            "[options]\nILoveCandy\nVerbosePkgLists\nColor\n\n" + SHIPPED,
        )

    def test_only_options_is_changed(self) -> None:
        # A repository's commented-out lines are not pacman's options.
        text = "[options]\n\n[core]\n#Color\n"
        self.assertEqual(
            phase3._with_look(text),
            "[options]\nColor\nILoveCandy\nVerbosePkgLists\n\n[core]\n#Color\n",
        )

    def test_a_file_without_options_is_left_alone(self) -> None:
        self.assertEqual(self.look(), [])
        self.assertEqual(self.conf.read_text(), SHIPPED)


class Lib32Drivers(Pacman):
    def drivers(self, multilib: str, installed: str) -> list[str]:
        self.env["MULTILIB"] = multilib
        self.env["INSTALLED"] = installed
        with mock.patch.dict(os.environ, self.env):
            return phase3._lib32_drivers(["mpv", "steam"])

    def test_an_amd_machine_gets_radeons(self) -> None:
        self.assertEqual(
            self.drivers("steam lib32-mesa", "mesa vulkan-radeon linux"),
            ["lib32-mesa", "lib32-vulkan-radeon"],
        )

    def test_an_nvidia_machine_gets_nvidias(self) -> None:
        self.assertEqual(
            self.drivers("steam", "nvidia-open nvidia-utils"),
            ["lib32-nvidia-utils"],
        )

    def test_none_without_a_multilib_package_or_multilib(self) -> None:
        self.assertEqual(self.drivers("lib32-mesa", "mesa"), [])
        self.assertEqual(self.drivers("", "mesa"), [])


if __name__ == "__main__":
    unittest.main()
