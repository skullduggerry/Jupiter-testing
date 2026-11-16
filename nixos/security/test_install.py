"""What Jupiter-nixos' phase 1 does with the disk's passphrase, the
passwords, the data disks' key files and the disks it was not given, with
nixos/test_phase1's stand-ins: every command recorded with its arguments and
what it read on stdin, /mnt a temporary folder. On NixOS the configuration
lands in the world-readable store, so neither a password nor the passphrase
may reach it: they go on stdin, and nowhere else.
"""

import json
import unittest

from nixos.test_phase1 import PASSPHRASE, USER, Declining, Encrypting

NOT_CHOSEN = ("/dev/vdy", "/dev/vdw", "/dev/sda", "/dev/sr0")
SECRETS = (PASSPHRASE, "secret-1", "secret-2")


class Secrets(Encrypting):
    def test_the_passphrase_goes_to_cryptsetup_on_stdin_alone(self) -> None:
        calls = self.install()
        given = [call for call in calls if PASSPHRASE in call[-1]]
        self.assertEqual(
            sorted({call[0] for call in given}), ["cryptsetup"], given
        )
        for call in given:
            self.assertEqual(call[-1], PASSPHRASE, "as typed, no newline")

    def test_passwords_go_to_chpasswd_inside_the_system(self) -> None:
        calls = self.install()
        [chpasswd] = [call for call in calls if "chpasswd" in call]
        self.assertEqual(
            chpasswd[:-1],
            ["nixos-enter", "--root", str(self.mnt), "--", "chpasswd"],
        )
        self.assertEqual(chpasswd[-1], f"{USER}:secret-1\nroot:secret-2\n")

    def test_no_secret_in_an_argument_or_a_file(self) -> None:
        calls = self.install()
        arguments = json.dumps([call[:-1] for call in calls])
        files = [
            path
            for path in self.mnt.rglob("*")
            if path.is_file() and not path.name.endswith(".key")
        ]
        self.assertTrue(files, "phase 1 wrote nothing to look in")
        for secret in SECRETS:
            # As typed, and as JSON writes it (the passphrase has a \\).
            for form in (secret, json.dumps(secret)[1:-1]):
                with self.subTest(secret=form):
                    self.assertNotIn(form, arguments)
                    for path in files:
                        text = path.read_text(errors="replace")
                        self.assertNotIn(form, text, path)

    def test_the_key_file_is_roots_alone(self) -> None:
        self.install()
        key = self.mnt / "etc/cryptsetup-keys.d/data.key"
        self.assertEqual(key.stat().st_mode & 0o777, 0o400)
        self.assertEqual(key.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(key.read_bytes()), 64)


class DisksNotChosen(Encrypting):
    def test_are_never_named(self) -> None:
        calls = self.install()
        named = json.dumps([call[:-1] for call in calls if call[0] != "lsblk"])
        for disk in NOT_CHOSEN:
            with self.subTest(disk=disk):
                self.assertNotIn(disk, named)


class Unencrypted(Declining):
    def test_no_secret_in_an_argument_or_a_file(self) -> None:
        calls = self.install()
        arguments = json.dumps([call[:-1] for call in calls])
        for secret in ("secret-1", "secret-2"):
            self.assertNotIn(secret, arguments)
            for path in self.mnt.rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret, path.read_text(errors="replace"))


if __name__ == "__main__":
    unittest.main()
