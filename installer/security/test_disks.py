"""What phase 1 does with the disk passphrase, the data disks' key files and
the disks it was not given (installer's test_phase1 for the rest).

The same stand-ins as test_phase1: every command phase 1 runs is recorded
with its arguments and what it read on stdin, and /mnt is a temporary
folder. The machine has, besides the system disk /dev/vdz: an empty
/dev/vdy and /dev/vdx, Windows' disk /dev/vdw and the ISO's stick /dev/sda,
which is mounted.
"""

import json
import os
import unittest

from jupiter import phase1

from installer.test_phase1 import PASSPHRASE, Declining, Encrypting

NOT_CHOSEN = ("/dev/vdy", "/dev/vdw", "/dev/sda", "/dev/sr0")


class Passphrase(Encrypting):
    def test_goes_on_stdin_as_typed(self) -> None:
        calls = self.install()
        cryptsetup = [
            call
            for call in calls
            if call[0] == "cryptsetup" and call[1] != "config"
        ]
        self.assertEqual(
            [call[1] for call in cryptsetup],
            ["luksFormat", "open", "luksFormat", "open", "luksAddKey"],
        )
        for call in cryptsetup:
            with self.subTest(call=call[1]):
                # No newline: none follows it when it is typed at boot.
                self.assertEqual(call[-1], PASSPHRASE)
                self.assertIn("--key-file=-", call)

    def test_never_in_arguments_files_or_output(self) -> None:
        calls = self.install()
        # Compared as they are, not as JSON, which escapes its backslash.
        arguments = [arg for call in calls for arg in call[:-1]]
        self.assertFalse([arg for arg in arguments if PASSPHRASE in arg])
        stdin = [call[-1] for call in calls if call[0] != "cryptsetup"]
        self.assertFalse([data for data in stdin if PASSPHRASE in data])
        for path in self.mnt.rglob("*"):
            if path.is_file() and not path.is_symlink():
                with self.subTest(path=path):
                    self.assertNotIn(PASSPHRASE.encode(), path.read_bytes())
        printed = [
            str(arg)
            for call in self.printed.call_args_list
            for arg in call.args
        ]
        self.assertFalse([line for line in printed if PASSPHRASE in line])


class KeyFiles(Encrypting):
    def test_only_root_reads_them(self) -> None:
        self.install()
        keys = self.mnt / "etc/cryptsetup-keys.d"
        self.assertEqual(keys.stat().st_mode & 0o777, 0o700)
        key = keys / "data.key"
        self.assertEqual(key.stat().st_mode & 0o777, 0o400)
        self.assertNotEqual(key.read_bytes(), PASSPHRASE.encode())

    def test_each_is_new_and_random(self) -> None:
        self.install()
        key = (self.mnt / "etc/cryptsetup-keys.d/data.key").read_bytes()
        self.assertEqual(len(key), 64)
        self.assertGreater(len(set(key)), 16)

    def test_are_never_written_over(self) -> None:
        keys = self.mnt / "etc/cryptsetup-keys.d"
        keys.mkdir(parents=True)
        (keys / "data.key").write_bytes(b"old")
        os.chmod(keys / "data.key", 0o400)
        # Made with O_EXCL: phase 1 stops rather than write over one.
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual((keys / "data.key").read_bytes(), b"old")


class EncryptedRoot(Encrypting):
    def test_is_named_by_its_opened_volume_never_by_a_uuid(self) -> None:
        """A file system's UUID is no secret (the image on the ESP names
        it) and a disk without encryption can carry it: mounted in the
        root's place with no volume opened, PCR 15 is still zero and the
        TPM gives the key out. /dev/mapper/root only systemd-cryptsetup
        makes."""
        self.install()
        line = (self.mnt / "etc/kernel/cmdline").read_text()
        self.assertIn("root=/dev/mapper/root ", line)
        for name in ("UUID=", "LABEL=", "PARTUUID=", "PARTLABEL=", "/dev/vd"):
            with self.subTest(name=name):
                self.assertNotIn(name, line)


class DisksNotChosen(Encrypting):
    def test_are_never_named_by_a_command(self) -> None:
        calls = self.install()
        for call in calls:
            for disk in NOT_CHOSEN:
                with self.subTest(call=call[:3], disk=disk):
                    self.assertFalse(
                        [arg for arg in call[1:-1] if arg.startswith(disk)]
                    )
        # The keymap's list and loadkeys name no disk; then lsblk is first.
        self.assertEqual(
            [call[:2] for call in calls[:3]],
            [["localectl", "list-keymaps"], ["loadkeys", "de-latin1"],
             ["lsblk", "--json"]],
        )  # fmt: skip

    def test_a_disk_with_something_on_it_is_not_offered(self) -> None:
        self.install()
        offered = " ".join(self.questions)
        for disk in ("/dev/vdw", "/dev/sda", "/dev/sr0"):
            self.assertNotIn(disk, offered)

    def test_data_goes_in_a_folder_of_its_own(self) -> None:
        valid = phase1._mount_point({"/taken"})
        for path in ("/data", "/mnt/data", "/srv/media", "/data2"):
            with self.subTest(path=path):
                self.assertTrue(valid(path))
        for path in (
            "/",
            "/root",
            "/boot/data",
            "/home",
            "/home/jane/data",
            "/etc/x",
            "/var/lib/x",
            "/usr",
            "data",
            "/Data",
            "/da ta",
            "/../etc",
            "/taken",
        ):
            with self.subTest(path=path):
                self.assertFalse(valid(path))


class Unencrypted(Declining):
    """Encryption declined: no other disk is even asked about."""

    def test_no_other_disk_is_named(self) -> None:
        calls = self.install()
        named = json.dumps([call[1:-1] for call in calls])
        for disk in (*NOT_CHOSEN, "/dev/vdx"):
            self.assertNotIn(disk, named)
        self.assertFalse([call for call in calls if call[0] == "cryptsetup"])


if __name__ == "__main__":
    unittest.main()
