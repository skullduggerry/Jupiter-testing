"""Phase 1 from the first question to the last file, with nothing real.

PATH holds only a stand-in that records how each command was called (and
answers the ones phase 1 reads), /mnt is a temporary folder and the answers
come from a list, so no disk, mount or user is touched: what phase 1 would
run, on which disk, and what it writes into the new system.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import phase1
from jupiter.common import INSTALLER_DIR

GIB = 2**30
LSBLK = {
    "blockdevices": [
        {
            "name": "/dev/vdy",
            "size": 32 * GIB,
            "model": "Other",
            "type": "disk",
            "mountpoints": [None],
        },
        {
            "name": "/dev/vdz",
            "size": 64 * GIB,
            "model": "Target",
            "type": "disk",
            "mountpoints": [None],
        },
    ]
}
SFDISK = {
    "partitiontable": {
        "partitions": [{"node": "/dev/vdz1"}, {"node": "/dev/vdz2"}]
    }
}
UUID = "0a1b2c3d-1111-2222-3333-444455556666"
# What each command prints, and what pacstrap leaves that phase 1 writes into.
STAND_IN = f"""#!{sys.executable}
import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
given = name == "sfdisk" and "--json" not in args or "chpasswd" in args
data = sys.stdin.read() if given else ""
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps([name, *args, data]) + "\\n")
print({{
    "lsblk": {json.dumps(json.dumps(LSBLK))},
    "timedatectl": "UTC\\nEurope/Berlin",
    "localectl": "us\\nde-latin1",
    "sfdisk": {json.dumps(json.dumps(SFDISK))} if "--json" in args else "",
    "genfstab": "UUID={UUID} / btrfs rw 0 0",
    "findmnt": "{UUID}",
}}.get(name, ""), end="")
if name == "pacstrap":
    etc = os.path.join(args[1], "etc")
    os.makedirs(os.path.join(etc, "sudoers.d"), exist_ok=True)
    with open(os.path.join(etc, "locale.gen"), "w") as file:
        file.write("# locales\\n#de_DE.UTF-8 UTF-8\\n#en_US.UTF-8 UTF-8\\n")
"""
COMMANDS = [
    "lsblk",
    "timedatectl",
    "localectl",
    "sfdisk",
    "udevadm",
    "mkfs.fat",
    "mkfs.btrfs",
    "mount",
    "umount",
    "btrfs",
    "pacstrap",
    "genfstab",
    "arch-chroot",
    "findmnt",
]
KBD_MODEL_MAP = "de-latin1\tde\tpc105\t-\tterminate:ctrl_alt_bksp\t-\n"
USER = "jupitertest"


class Installing(unittest.TestCase):
    """A live ISO of stand-ins, a temporary /mnt and an NVIDIA machine."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.mnt = tmp / "mnt"
        self.mnt.mkdir()
        self.calls = tmp / "calls"
        self.calls.write_text("")
        stand_ins = tmp / "bin"
        stand_ins.mkdir()
        for command in COMMANDS:
            (stand_ins / command).write_text(STAND_IN)
            (stand_ins / command).chmod(0o755)
        (tmp / "locale.gen").write_text(
            "# The locales\n#de_DE.UTF-8 UTF-8\n#en_US.UTF-8 UTF-8\n"
        )
        (tmp / "kbd-model-map").write_text(KBD_MODEL_MAP)
        (tmp / "efi").mkdir()
        for name, value in {
            "LIVE": True,
            "MNT": self.mnt,
            "EFI": tmp / "efi",
            "LOCALE_GEN": tmp / "locale.gen",
            "KBD_MODEL_MAP": tmp / "kbd-model-map",
        }.items():
            self.enterContext(mock.patch.object(phase1, name, value))
        # A machine with only an NVIDIA card, whatever this one has.
        drivers = {"amd-ucode", *phase1.NVIDIA}
        self.enterContext(
            mock.patch.object(phase1, "drivers", return_value=drivers)
        )
        # Nothing but the stand-ins: an unexpected command fails to start.
        environment = {"PATH": str(stand_ins), "CALLS": str(self.calls)}
        self.enterContext(mock.patch.dict(os.environ, environment))
        self.enterContext(mock.patch("builtins.print"))


class PhaseOne(Installing):
    def install(self, erase: str = "y") -> list[list[str]]:
        answers = [
            "/dev/nope",  # not offered
            "/dev/vdz",
            "Bad Host!",  # not a hostname
            "box",
            USER,
            "Mars/Olympus",  # not a time zone
            "Europe/Berlin",
            "de_DE.UTF-8",
            "de-latin1",
            erase,
        ]
        passwords = [
            "secret-1",
            "typo",
            "secret-1",
            "secret-1",
            "secret-2",
            "secret-2",
        ]
        with (
            mock.patch("builtins.input", side_effect=answers),
            mock.patch("getpass.getpass", side_effect=passwords),
        ):
            phase1.main()
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]

    def test_installs_on_the_disk_confirmed(self) -> None:
        calls = self.install()
        mnt = str(self.mnt)
        run = [call[:-1] for call in calls]
        self.assertEqual(
            [call[0] for call in calls[:3]],
            ["lsblk", "timedatectl", "localectl"],
        )
        self.assertNotIn(
            "/dev/vdy", json.dumps(calls), "the other disk is left alone"
        )
        self.assertIn(
            [
                "sfdisk",
                "--wipe",
                "always",
                "--wipe-partitions",
                "always",
                "/dev/vdz",
            ],
            run,
        )
        layout = next(
            call[-1]
            for call in calls
            if call[0] == "sfdisk" and "--json" not in call
        )
        self.assertIn("size=1GiB, type=uefi", layout)
        for command in (
            ["mkfs.fat", "-F", "32", "/dev/vdz1"],
            ["mkfs.btrfs", "--force", "/dev/vdz2"],
            [
                "mount",
                "--mkdir",
                "-o",
                "compress=zstd,subvol=@home",
                "/dev/vdz2",
                f"{mnt}/home",
            ],
            [
                "mount",
                "--mkdir",
                "-o",
                "fmask=0077,dmask=0077",
                "/dev/vdz1",
                f"{mnt}/boot",
            ],
            [
                "arch-chroot",
                "-S",
                mnt,
                "useradd",
                "--create-home",
                "--groups",
                "wheel",
                USER,
            ],
            [
                "arch-chroot",
                "-S",
                mnt,
                "systemctl",
                "enable",
                "NetworkManager",
                "systemd-timesyncd",
            ],
            ["arch-chroot", "-S", mnt, "bootctl", "install"],
        ):
            self.assertIn(command, run)
        pacstrap = next(call for call in run if call[0] == "pacstrap")
        self.assertEqual(pacstrap[1:3], ["-K", mnt])
        self.assertTrue(
            {*phase1.BASE, "amd-ucode", *phase1.NVIDIA} <= set(pacstrap)
        )

    def test_passwords_go_over_stdin_only(self) -> None:
        calls = self.install()
        chpasswd = next(call for call in calls if "chpasswd" in call)
        self.assertEqual(chpasswd[-1], f"{USER}:secret-1\nroot:secret-2\n")
        arguments = json.dumps([call[:-1] for call in calls])
        self.assertNotIn("secret", arguments)

    def test_writes_the_new_systems_settings(self) -> None:
        self.install()
        etc = self.mnt / "etc"
        self.assertEqual((etc / "hostname").read_text(), "box\n")
        self.assertEqual(
            (etc / "locale.conf").read_text(), "LANG=de_DE.UTF-8\n"
        )
        self.assertIn(
            "\nde_DE.UTF-8 UTF-8\n", (etc / "locale.gen").read_text()
        )
        self.assertIn(
            "\n#en_US.UTF-8 UTF-8\n", (etc / "locale.gen").read_text()
        )
        self.assertEqual(
            (etc / "vconsole.conf").read_text(),
            "KEYMAP=de-latin1\nXKBLAYOUT=de\nXKBMODEL=pc105\n"
            "XKBOPTIONS=terminate:ctrl_alt_bksp\n",
        )
        self.assertEqual(
            os.readlink(etc / "localtime"), "/usr/share/zoneinfo/Europe/Berlin"
        )
        self.assertTrue((etc / "systemd/zram-generator.conf").exists())
        self.assertIn(f"UUID={UUID} / btrfs", (etc / "fstab").read_text())
        sudoers = etc / "sudoers.d/10-wheel"
        self.assertEqual(sudoers.read_text(), "%wheel ALL=(ALL:ALL) ALL\n")
        self.assertEqual(sudoers.stat().st_mode & 0o777, 0o440)
        self.assertEqual(
            (etc / "xdg/uwsm/env-hyprland").read_text(), phase1.NVIDIA_ENV
        )
        entry = (self.mnt / "boot/loader/entries/arch.conf").read_text()
        self.assertIn(f"options root=UUID={UUID} rootflags=subvol=@ rw", entry)

    def test_leaves_itself_in_the_new_home(self) -> None:
        calls = self.install()
        copy = self.mnt / "home" / USER / INSTALLER_DIR.name
        self.assertTrue((copy / "jupiter/phase1.py").exists())
        self.assertEqual(list(copy.rglob("__pycache__")), [])
        chown = [
            "arch-chroot",
            "-S",
            str(self.mnt),
            "chown",
            "--recursive",
            f"{USER}:",
            f"/home/{USER}/{copy.name}",
        ]
        self.assertEqual(calls[-1][:-1], chown)

    def test_nothing_without_a_yes(self) -> None:
        with self.assertRaises(SystemExit) as stopped:
            self.install(erase="")
        self.assertEqual(str(stopped.exception), "Nothing was changed.")
        calls = [
            call[0]
            for call in json.loads(
                f"[{','.join(self.calls.read_text().splitlines())}]"
            )
        ]
        self.assertEqual(calls, ["lsblk", "timedatectl", "localectl"])
        self.assertEqual(list(self.mnt.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
