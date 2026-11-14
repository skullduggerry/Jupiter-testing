"""Phase 4's fingerprint: where fprintd finds a reader, a finger is enrolled
(if none is) and sudo's and polkit's PAM stacks take one first, keeping the
old file; polkit's from its package's (/usr/lib/pam.d) where /etc has none.

fprintd-list, fprintd-enroll and sudo are stand-ins on a PATH of their own,
and the PAM files are temporary ones, so nothing on this machine changes.
"""

import json
import os
import pwd
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import phase4

SUDO = (
    "#%PAM-1.0\n"
    "auth\t\tinclude\t\tsystem-auth\n"
    "account\t\tinclude\t\tsystem-auth\n"
)
POLKIT = (
    "#%PAM-1.0\n\n"
    "auth       include      system-auth\n"
    "account    include      system-auth\n"
)
DEVICE = (
    "found 1 devices\n"
    "Device at /net/reactivated/Fprint/Device/0\n"
    "Using device /net/reactivated/Fprint/Device/0\n"
)
NO_FINGER = DEVICE + "User {user} has no fingers enrolled for Sensor.\n"
A_FINGER = DEVICE + (
    "Fingerprints for user {user} on Sensor (press):\n"
    " - #0: right-index-finger\n"
)
# Records its arguments; fprintd-list prints $LISTING and exits $STATUS,
# fprintd-enroll exits $ENROLLED, and sudo runs `install` for real.
STAND_IN = f"""#!{sys.executable}
import json, os, shutil, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps([name, *args]) + "\\n")
if name == "fprintd-list":
    print(os.environ["LISTING"], end="")
    sys.exit(int(os.environ["STATUS"]))
if name == "fprintd-enroll":
    sys.exit(int(os.environ["ENROLLED"]))
if name == "sudo" and args[0] == "install":
    if os.path.exists(args[-1]):
        shutil.copy(args[-1], args[-1] + "~")
    shutil.copy(args[-2], args[-1])
"""


class Fingerprint(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.calls = tmp / "calls"
        self.calls.write_text("")
        self.pam = tmp / "sudo"
        self.pam.write_text(SUDO)
        stand_ins = tmp / "bin"
        stand_ins.mkdir()
        for name in ("fprintd-list", "fprintd-enroll", "sudo"):
            (stand_ins / name).write_text(STAND_IN)
            (stand_ins / name).chmod(0o755)
        self.user = pwd.getpwuid(os.getuid()).pw_name
        self.env = {
            "PATH": str(stand_ins),
            "CALLS": str(self.calls),
            "STATUS": "0",
            "ENROLLED": "0",
        }
        self.polkit = tmp / "etc-polkit-1"
        self.vendor = tmp / "usr-polkit-1"
        self.vendor.write_text(POLKIT)
        for name, value in {
            "SUDO_PAM": self.pam,
            "POLKIT_PAM": self.polkit,
            "POLKIT_VENDOR_PAM": self.vendor,
        }.items():
            self.enterContext(mock.patch.object(phase4, name, value))
        self.enterContext(mock.patch("builtins.print"))

    def set_up(self, listing: str, answer: str = "") -> list[list[str]]:
        self.calls.write_text("")
        environment = self.env | {"LISTING": listing.format(user=self.user)}
        with (
            mock.patch.dict(os.environ, environment),
            mock.patch("builtins.input", return_value=answer) as asked,
        ):
            phase4._fingerprint()
        self.asked = asked.called
        lines = self.calls.read_text().splitlines()
        return [json.loads(line) for line in lines]

    def test_enrolls_and_lets_sudo_take_a_finger(self) -> None:
        calls = self.set_up(NO_FINGER)
        self.assertEqual(calls[0], ["fprintd-list", self.user])
        self.assertEqual(calls[1], ["fprintd-enroll"])
        self.assertEqual(calls[2][:5], ["sudo", "install", "-b", "-m", "0644"])
        self.assertEqual(calls[2][-1], str(self.pam))
        self.assertEqual(
            self.pam.read_text(),
            "#%PAM-1.0\n" + phase4.FINGERPRINT + SUDO.split("\n", 1)[1],
        )
        self.assertEqual(Path(f"{self.pam}~").read_text(), SUDO)

    def test_polkit_takes_a_finger_from_its_packages_stack(self) -> None:
        calls = self.set_up(A_FINGER)
        self.assertEqual(calls[-1][-1], str(self.polkit))
        self.assertEqual(
            self.polkit.read_text(),
            "#%PAM-1.0\n" + phase4.FINGERPRINT + POLKIT.split("\n", 1)[1],
        )
        self.assertEqual(
            self.vendor.read_text(), POLKIT, "the package's stays"
        )
        self.assertFalse(Path(f"{self.polkit}~").exists())

    def test_polkit_keeps_a_stack_of_its_own(self) -> None:
        own = "#%PAM-1.0\nauth required pam_unix.so\n"
        self.polkit.write_text(own)
        self.set_up(A_FINGER)
        self.assertEqual(
            self.polkit.read_text(),
            "#%PAM-1.0\n" + phase4.FINGERPRINT + "auth required pam_unix.so\n",
        )
        self.assertEqual(Path(f"{self.polkit}~").read_text(), own)

    def test_again_changes_nothing(self) -> None:
        self.set_up(NO_FINGER)
        calls = self.set_up(A_FINGER)
        self.assertFalse(self.asked, "a finger is enrolled already")
        self.assertEqual(calls, [["fprintd-list", self.user]])
        self.assertEqual(self.pam.read_text().count("pam_fprintd"), 1)

    def test_no_reader(self) -> None:
        self.env["STATUS"] = "1"
        calls = self.set_up("No devices available\n")
        self.assertEqual(calls, [["fprintd-list", self.user]])
        self.assertEqual(self.pam.read_text(), SUDO)
        self.assertFalse(self.polkit.exists())

    def test_enrolling_can_wait(self) -> None:
        calls = self.set_up(NO_FINGER, answer="n")
        self.assertNotIn(["fprintd-enroll"], calls)
        self.assertIn("pam_fprintd", self.pam.read_text())

    def test_a_failed_enrolment_is_named(self) -> None:
        self.env["ENROLLED"] = "1"
        with mock.patch.object(phase4, "warn") as warned:
            self.set_up(NO_FINGER)
        warned.assert_called_once()
        self.assertIn("pam_fprintd", self.pam.read_text())

    def test_without_fprintd(self) -> None:
        (Path(self.env["PATH"]) / "fprintd-list").unlink()
        self.assertEqual(self.set_up(""), [])
        self.assertEqual(self.pam.read_text(), SUDO)


if __name__ == "__main__":
    unittest.main()
