"""Who the installer makes a user, with which password and which rights.

Phase 1 asks for a user name and two passwords and makes the user an
administrator through sudo (wheel); phase 4 lets sudo take a fingerprint.
Here: which names are taken, that the passwords go to chpasswd as typed and
on stdin only, that the rights are wheel's and sudo's rule valid and
readable by root alone, that the ESP is not world readable, that nothing
listens for logins, and that the root checks and the firewall rules hold.
"""

from __future__ import annotations

import ipaddress
import json
import os
import pwd
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from jupiter import __main__ as main
from jupiter import config, phase1, phase3

import installer  # noqa: F401  # puts the installer on sys.path
from harness import INSTALLER
from installer.test_phase1 import Installing

ISO_USERS = ["root", "bin", "nobody", "systemd-network", "dbus", "arch"]


def entries(*names: str) -> list[pwd.struct_passwd]:
    return [
        pwd.struct_passwd((name, "x", 0, 0, "", "/", "/bin/sh"))
        for name in names
    ]


class UserNames(unittest.TestCase):
    """phase1._is_new_user: a new account, as useradd and Arch name them."""

    def setUp(self) -> None:
        self.enterContext(
            mock.patch("pwd.getpwall", return_value=entries(*ISO_USERS))
        )

    def test_names_taken_or_malformed(self) -> None:
        for name in [
            *ISO_USERS,
            # greetd's login screen account, made in phase 2.
            "greeter",
            "",
            "Jane",
            "1jane",
            "-jane",
            "jane doe",
            "jane:x",
            "../jane",
            "jane\n",
            "jane/",
            "a" * 33,
            "jäne",
        ]:
            with self.subTest(name=name):
                self.assertFalse(phase1._is_new_user(name))

    def test_names_that_are_new(self) -> None:
        for name in ("jane", "_jane", "j-a_n3", "a" * 32):
            with self.subTest(name=name):
                self.assertTrue(phase1._is_new_user(name))


class Passwords(Installing):
    """Phase 1 from the first question to the last file (installer's
    test_phase1), here for what it does with the passwords."""

    PASSWORDS = (
        "",  # empty: asked again
        "",
        "pa:ss word ",  # a colon and spaces, kept as typed
        "pa:ss word ",
        "r00t",
        "r00t",
    )

    def install(self) -> list[list[str]]:
        answers = ["/dev/vdz", "box", "jane", "UTC", "en_US.UTF-8", "us", "y"]
        with (
            mock.patch("builtins.input", side_effect=answers),
            mock.patch("getpass.getpass", side_effect=list(self.PASSWORDS)),
            mock.patch.object(
                phase1, "_listed", return_value=lambda answer: True
            ),
        ):
            phase1.main()
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]

    def test_as_typed_on_stdin_only(self) -> None:
        calls = self.install()
        [chpasswd] = [call for call in calls if "chpasswd" in call]
        # chpasswd splits each line at its first colon only, and is not told
        # the passwords are hashes already (-e).
        self.assertEqual(
            chpasswd[:-1], ["arch-chroot", "-S", str(self.mnt), "chpasswd"]
        )
        self.assertEqual(chpasswd[-1], "jane:pa:ss word \nroot:r00t\n")
        arguments = json.dumps([call[:-1] for call in calls])
        for password in ("pa:ss", "r00t"):
            self.assertNotIn(password, arguments)

    def test_one_administrator_in_wheel(self) -> None:
        calls = self.install()
        [useradd] = [call[:-1] for call in calls if "useradd" in call]
        self.assertEqual(
            useradd[3:],
            ["useradd", "--create-home", "--groups", "wheel", "jane"],
        )
        sudoers = self.mnt / "etc/sudoers.d/10-wheel"
        self.assertEqual(sudoers.read_text(), "%wheel ALL=(ALL:ALL) ALL\n")
        self.assertNotIn("NOPASSWD", sudoers.read_text())
        self.assertEqual(sudoers.stat().st_mode & 0o777, 0o440)
        # sudo skips a file in sudoers.d whose name has a dot or ends in ~.
        self.assertNotIn(".", sudoers.name)
        self.assertFalse(sudoers.name.endswith("~"))
        if visudo := shutil.which("visudo"):
            checked = subprocess.run(
                [visudo, "-cf", str(sudoers)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                checked.returncode, 0, checked.stdout + checked.stderr
            )

    def test_nothing_listens_for_logins(self) -> None:
        calls = self.install()
        enabled = [
            call[call.index("enable") + 1 : -1]
            for call in calls
            if "systemctl" in call and "enable" in call
        ]
        self.assertEqual(enabled, [["NetworkManager", "systemd-timesyncd"]])
        self.assertNotIn("openssh", phase1.BASE)

    def test_the_esp_is_roots_alone(self) -> None:
        # The boot loader's random seed lives there; bootctl warns, and the
        # seed is no secret, when others can read it.
        calls = self.install()
        boot = [
            call[:-1]
            for call in calls
            if call[0] == "mount" and str(self.mnt / "boot") in call
        ]
        self.assertEqual(
            boot,
            [
                [
                    "mount",
                    "--mkdir",
                    "-o",
                    "fmask=0077,dmask=0077",
                    "/dev/vdz1",
                    f"{self.mnt}/boot",
                ]
            ],
        )


class Privileges(unittest.TestCase):
    def test_phases_3_and_4_refuse_root(self) -> None:
        for phases in (["3"], ["4"], ["2", "3"]):
            with (
                self.subTest(phases=phases),
                mock.patch("os.geteuid", return_value=0),
                mock.patch("sys.argv", ["jupiter", *phases]),
                mock.patch("sys.stderr"),
                self.assertRaises(SystemExit) as stopped,
            ):
                main.main()
            self.assertEqual(stopped.exception.code, 2)

    def test_phase_1_only_from_the_live_iso(self) -> None:
        with (
            mock.patch.object(phase1, "LIVE", False),
            self.assertRaisesRegex(
                SystemExit, "runs from the Arch Linux live ISO"
            ),
        ):
            phase1.main()


class Sources(unittest.TestCase):
    """What the installer fetches and runs, and what it opens to others."""

    def test_fetched_over_https(self) -> None:
        for url in (config.DOTFILES_REPO, phase3.PARU):
            self.assertTrue(url.startswith("https://"), url)
        bootstrap = (INSTALLER / "bootstrap.sh").read_text()
        self.assertIn("INSTALLER_REPO:-https://", bootstrap)
        check = (INSTALLER / "check.sh").read_text()
        self.assertIn("TESTING_REPO:-https://", check)
        # Updated fast-forward only: a rewritten upstream is not merged in.
        self.assertIn("pull --ff-only", bootstrap)

    def test_kde_connect_is_opened_to_local_networks_only(self) -> None:
        for network in phase3.LOCAL_NETWORKS:
            with self.subTest(network=network):
                parsed = ipaddress.ip_network(network)
                self.assertTrue(parsed.is_private or parsed.is_link_local)
                self.assertGreater(parsed.prefixlen, 0)

    def test_sudo_takes_a_finger_before_the_password(self) -> None:
        from jupiter import phase4

        self.assertEqual(
            phase4.FINGERPRINT.split(),
            ["auth", "sufficient", "pam_fprintd.so"],
        )
        self.assertEqual(Path("/etc/pam.d/sudo"), phase4.SUDO_PAM)


if __name__ == "__main__":
    os.environ.setdefault("LANG", "C")
    unittest.main()
