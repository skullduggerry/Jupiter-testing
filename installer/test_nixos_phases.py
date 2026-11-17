"""Phases 2 to 4 on NixOS against stand-in commands, in a throwaway home,
and the entry point that runs them on either system.

sudo, systemctl, wallust, nixos-rebuild and fprintd-enroll only record how
they were called. The root is not encrypted (findmnt), so the keyring and
TPM steps leave it alone (their own tests: test_nixos_tpm.py,
security/test_keyring.py), and there is no fingerprint reader unless a test
gives one. The installer is told it is on NixOS by a stand-in os-release.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import __main__ as entry
from jupiter.common import INSTALLER_DIR
from jupiter.distro import System as Distro
from jupiter.nixos import common, phase4, system

from harness import executable
from installer import NIXOS

RECORD = """#!/bin/sh
echo "${0##*/} $*" >> "$CALLS"
exit 0
"""
PUSH_URL = "git@example.org:dotfiles.git"


class World(unittest.TestCase):
    """A home, stand-in commands, and a clone of stand-in dotfiles."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.tmp = tmp
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.calls = tmp / "calls"
        self.calls.write_text("")
        for name in (
            "sudo", "systemctl", "wallust", "nixos-rebuild", "fprintd-enroll",
        ):  # fmt: skip
            executable(self.bin / name, RECORD)
        executable(self.bin / "findmnt", "#!/bin/sh\necho '/dev/vda2[/@]'\n")
        executable(self.bin / "fprintd-list", "#!/bin/sh\nexit 1\n")
        origin = tmp / "Jupiter-dotfiles"
        for name in ("hypr/hyprland.lua", "kitty/kitty.conf", ".zshrc"):
            executable(origin / ".config" / name, "")
        executable(origin / ".config/wallust/apply.sh", RECORD)
        git = ["git", "-C", str(origin)]
        author = ["-c", "user.name=test", "-c", "user.email=test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, *author, "commit", "-qm", "init"], check=True)
        self.origin = origin
        self.repo = self.home / origin.name
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("XDG_")
        } | {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "DOTFILES_REPO": str(origin),
            "DOTFILES_PUSH_URL": PUSH_URL,
            "JUPITER_OS_RELEASE": str(NIXOS),
        }

    def recorded(self) -> list[str]:
        return [line.rstrip() for line in self.calls.read_text().splitlines()]


class Dotfiles(World):
    def jupiter(self, *phases: str, answers: str = "") -> list[str]:
        self.calls.write_text("")
        self.output = subprocess.run(
            [sys.executable, "-m", "jupiter", *phases],
            cwd=INSTALLER_DIR,
            env=self.env,
            input=answers,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return self.recorded()

    def test_links_the_dotfiles_and_sets_up_around_them(self) -> None:
        calls = self.jupiter("4")
        config = self.home / ".config"
        self.assertEqual(
            (config / "hypr").readlink(), self.repo / ".config/hypr"
        )
        self.assertEqual(
            (self.home / ".zshrc").readlink(), self.repo / ".config/.zshrc"
        )
        self.assertEqual(
            calls,
            [
                "systemctl --user mask dunst.service mako.service "
                "swaync.service",
                "apply.sh",
            ],
        )
        push = subprocess.run(
            ["git", "-C", str(self.repo), "remote", "get-url", "--push",
             "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
        self.assertEqual(push, PUSH_URL)
        # Root's copy of the greeter's installer is the system's: missing
        # here, it is named, not run from the clone.
        self.assertIn("install-greeter.sh is missing", self.output)
        self.assertIn("The disk is not encrypted", self.output)

    def test_run_again_backs_up_what_was_in_the_way(self) -> None:
        self.jupiter("4")
        kitty = self.home / ".config/kitty"
        kitty.unlink()
        kitty.mkdir()
        (kitty / "mine.conf").write_text("mine\n")
        self.jupiter("4")
        self.assertTrue(kitty.is_symlink())
        [backup] = (self.home / ".dotfiles-backup").iterdir()
        self.assertEqual(
            (backup / ".config/kitty/mine.conf").read_text(), "mine\n"
        )

    def test_without_wallust_the_first_login_renders(self) -> None:
        # Nor any other wallust: PATH is the stand-ins and git alone.
        (self.bin / "wallust").unlink()
        tools = self.tmp / "tools"
        tools.mkdir()
        (tools / "git").symlink_to(shutil.which("git") or "git")
        self.env["PATH"] = f"{self.bin}:{tools}"
        calls = self.jupiter("4")
        self.assertNotIn("apply.sh", calls)
        self.assertIn("wallust is missing", self.output)

    def test_a_reader_without_a_finger_offers_one(self) -> None:
        executable(
            self.bin / "fprintd-list",
            "#!/bin/sh\necho 'Device at /x'\necho 'User test has no fingers "
            "enrolled for Reader.'\n",
        )
        calls = self.jupiter("4", answers="\n")
        self.assertIn("fprintd-enroll", calls)
        calls = self.jupiter("4", answers="n\n")
        self.assertNotIn("fprintd-enroll", calls)

    def test_a_finger_enrolled_already_is_not_asked_for(self) -> None:
        executable(
            self.bin / "fprintd-list",
            "#!/bin/sh\necho 'Device at /x'\necho ' - #0: right-index'\n",
        )
        self.assertNotIn("fprintd-enroll", self.jupiter("4"))

    def test_the_login_screen_through_roots_copy(self) -> None:
        installer = executable(self.tmp / "root/install-greeter.sh", "")
        with (
            mock.patch.object(phase4, "INSTALL_GREETER", installer),
            mock.patch.dict(os.environ, self.env),
        ):
            phase4._install_greeter(self.repo)
        self.assertEqual(
            self.recorded(), [f"sudo {installer} --from {self.repo}"]
        )


class System(World):
    def hosts(self, *names: str) -> Path:
        hosts = self.tmp / "repo/hosts"
        for name in names:
            common.write_settings(hosts / name, {"hostname": name})
        self.enterContext(mock.patch.object(common, "HOSTS", hosts))
        self.enterContext(mock.patch.object(system, "rebuilt", False))
        self.enterContext(
            mock.patch.object(system, "INSTALLER_DIR", hosts.parent)
        )
        self.enterContext(mock.patch.dict(os.environ, self.env))
        return hosts

    def test_rebuilds_this_machines_configuration(self) -> None:
        hosts = self.hosts("box", "other")
        with mock.patch("socket.gethostname", return_value="box"):
            system.main()
        self.assertEqual(
            self.recorded(),
            [f"nixos-rebuild switch --sudo --flake {hosts.parent}#box"],
        )

    def test_a_machine_without_settings_is_named(self) -> None:
        self.hosts("other")
        with (
            mock.patch("socket.gethostname", return_value="box"),
            self.assertRaisesRegex(SystemExit, "settings for box .*other"),
        ):
            system.main()
        self.assertEqual(self.recorded(), [])

    def test_settings_are_json_whatever_they_hold(self) -> None:
        hosts = self.hosts()
        odd = {"hostname": 'box"; } evil = { ', "user": "${builtins}"}
        common.write_settings(hosts / "box", odd)
        self.assertEqual(common.read_settings("box"), odd)
        self.assertEqual(
            json.loads((hosts / "box/settings.json").read_text()), odd
        )


class Entry(unittest.TestCase):
    """python3 -m jupiter on NixOS: which phases, as whom, with a network;
    the same entry point as Arch's (installer's test_main)."""

    def run_main(
        self, *argv: str, live: bool = False, root: bool = False
    ) -> list[str]:
        ran: list[str] = []
        phases = {
            n: (lambda n=n: ran.append(f"nixos {n}"))
            for n in entry.NIXOS_PHASES
        }
        arch = {n: (lambda n=n: ran.append(f"arch {n}")) for n in entry.PHASES}
        with (
            mock.patch.object(sys, "argv", ["jupiter", *argv]),
            mock.patch.dict(entry.NIXOS_PHASES, phases),
            mock.patch.dict(entry.PHASES, arch),
            mock.patch.object(
                entry, "detect", return_value=Distro("nixos", live)
            ),
            mock.patch.object(entry, "online", return_value=True),
            mock.patch("os.geteuid", return_value=0 if root else 1000),
            mock.patch("builtins.print"),
        ):
            entry.main()
        return ran

    def test_the_default_phases(self) -> None:
        self.assertEqual(self.run_main(live=True, root=True), ["nixos 1"])
        self.assertEqual(self.run_main(), ["nixos 3", "nixos 4"])
        self.assertEqual(self.run_main("4", "2"), ["nixos 4", "nixos 2"])

    def test_phases_2_to_4_refuse_root(self) -> None:
        for phase in ("2", "3", "4"):
            with (
                self.subTest(phase=phase),
                mock.patch("sys.stderr"),
                self.assertRaises(SystemExit),
            ):
                self.run_main(phase, root=True)

    def test_phase_1_only_from_the_iso(self) -> None:
        with (
            mock.patch("sys.stderr") as stderr,
            self.assertRaises(SystemExit),
        ):
            self.run_main("1")
        said = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("the NixOS installation ISO", said)

    def test_offline_phases_say_how_to_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable(Path(tmp, "nm-online"), "#!/bin/sh\nexit 1\n")
            with mock.patch.dict(os.environ, {"PATH": tmp}):
                self.assertFalse(entry.online(live=False))
                self.assertTrue(entry.online(live=True))
            with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
                self.assertTrue(entry.online(live=False))
        with (
            mock.patch.object(sys, "argv", ["jupiter", "2"]),
            mock.patch.object(
                entry, "detect", return_value=Distro("nixos", False)
            ),
            mock.patch.object(entry, "online", return_value=False),
            mock.patch("os.geteuid", return_value=1000),
            self.assertRaisesRegex(SystemExit, "nmtui"),
        ):
            entry.main()

    def test_a_failing_command_is_named(self) -> None:
        def fail() -> None:
            raise subprocess.CalledProcessError(1, ["nixos-rebuild", "x y"])

        with (
            mock.patch.object(sys, "argv", ["jupiter", "2"]),
            mock.patch.dict(entry.NIXOS_PHASES, {2: fail}),
            mock.patch.object(
                entry, "detect", return_value=Distro("nixos", False)
            ),
            mock.patch.object(entry, "online", return_value=True),
            mock.patch("os.geteuid", return_value=1000),
            mock.patch("builtins.print"),
            self.assertRaisesRegex(SystemExit, "Failed: nixos-rebuild 'x y'"),
        ):
            entry.main()


class Rebuild(World):
    """Phases 2 and 3 are one rebuild on NixOS: once a run."""

    def test_phases_2_and_3_rebuild_once(self) -> None:
        hosts = self.tmp / "repo/hosts"
        common.write_settings(hosts / "box", {"hostname": "box"})
        with (
            mock.patch.object(common, "HOSTS", hosts),
            mock.patch.object(system, "INSTALLER_DIR", hosts.parent),
            mock.patch.object(system, "rebuilt", False),
            mock.patch.dict(os.environ, self.env),
            mock.patch("socket.gethostname", return_value="box"),
            mock.patch("builtins.print"),
        ):
            system.main()
            system.main()
        self.assertEqual(
            self.recorded(),
            [f"nixos-rebuild switch --sudo --flake {hosts.parent}#box"],
        )


if __name__ == "__main__":
    unittest.main()
