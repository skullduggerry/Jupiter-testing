"""Phase 1 on NixOS (jupiter/nixos/phase1.py) from the first question to
nixos-install, with nothing real.

PATH holds only a stand-in that records how each command was called (and
answers the ones phase 1 reads), /mnt is a temporary folder, the repo phase
1 copies into the new home is a small stand-in, and the answers come from a
list: what phase 1 would run, on which disk, and what it writes into the
copy (settings.json, the hardware configuration), encrypted or not. The
disks are the Arch installer's tests' (harness/disks.py).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from jupiter import phase1 as disks
from jupiter.nixos import phase1

from harness.disks import KBD_MODEL_MAP, LSBLK

ESP = "4A3B-1C2D"
USER = "jupitertest"
PASSPHRASE = "a passphrase: typed\\ as is"
HARDWARE = "{ boot.kernelModules = [ ]; }\n"
STAND_IN = f"""#!{sys.executable}
import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
given = (
    name == "sfdisk" and "--json" not in args
    or name == "cryptsetup" and args[0] != "config"
    or "chpasswd" in args
)
data = sys.stdin.read() if given else ""
table = {{"partitiontable": {{"partitions": [
    {{"node": args[-1] + "1"}}, {{"node": args[-1] + "2"}}
]}}}}
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps([name, *args, data]) + "\\n")
print({{
    "lsblk": os.environ.get("LSBLK") or {json.dumps(json.dumps(LSBLK))},
    "timedatectl": "UTC\\nEurope/Berlin",
    "localectl": "us\\nde-latin1",
    "sfdisk": json.dumps(table) if "--json" in args else "",
    "blkid": "{ESP}",
    "nixos-generate-config": {json.dumps(HARDWARE)},
}}.get(name, ""), end="")
"""
COMMANDS = [
    "lsblk",
    "cryptsetup",
    "timedatectl",
    "localectl",
    "loadkeys",
    "sfdisk",
    "udevadm",
    "mkfs.fat",
    "mkfs.btrfs",
    "mount",
    "umount",
    "btrfs",
    "blkid",
    "nixos-generate-config",
    "git",
    "nix",
    "nixos-install",
    "nixos-enter",
]
ZONE_TAB = "# zone.tab\nDE\t+5230+01322\tEurope/Berlin\n"
OS_RELEASE = 'NAME=NixOS\nVERSION_ID="26.11"\nVARIANT_ID=installer\n'
WIFI = "[connection]\nid=home\ntype=wifi\n[wifi-security]\npsk=hunter2\n"


class Installing(unittest.TestCase):
    """The NixOS ISO of stand-ins, a temporary /mnt and an NVIDIA machine."""

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
        # Beside localectl, as systemd's package has it.
        model_map = tmp / "share/systemd/kbd-model-map"
        model_map.parent.mkdir(parents=True)
        model_map.write_text(KBD_MODEL_MAP)
        (tmp / "zone.tab").write_text(ZONE_TAB)
        (tmp / "os-release").write_text(OS_RELEASE)
        (tmp / "efi").mkdir()
        connections = tmp / "connections"
        connections.mkdir()
        (connections / "home.nmconnection").write_text(WIFI)
        # The repo phase 1 copies, small: a flake and the package.
        self.repo = tmp / "Jupiter-installer"
        (self.repo / "jupiter").mkdir(parents=True)
        (self.repo / "flake.nix").write_text("{ }\n")
        (self.repo / "jupiter/__main__.py").write_text("")
        (self.repo / "jupiter/__pycache__").mkdir()
        # The disks' steps are Arch's phase 1's, by its own constants.
        for name, value in {
            "MNT": self.mnt,
            "EFI": tmp / "efi",
            "ERASED": tmp / "jupiter-erased",
        }.items():
            self.enterContext(mock.patch.object(disks, name, value))
        for name, value in {
            "ZONE_TAB": tmp / "zone.tab",
            "OS_RELEASE": tmp / "os-release",
            "ISO_CONNECTIONS": connections,
            "INSTALLER_DIR": self.repo,
        }.items():
            self.enterContext(mock.patch.object(phase1, name, value))
        self.enterContext(
            mock.patch.object(phase1, "gpus", return_value=["nvidia"])
        )
        # Nothing but the stand-ins: an unexpected command fails to start.
        environment = {"PATH": str(stand_ins), "CALLS": str(self.calls)}
        self.enterContext(mock.patch.dict(os.environ, environment))
        self.printed = self.enterContext(mock.patch("builtins.print"))
        self.copy = self.mnt / "home" / USER / self.repo.name

    def calls_made(self) -> list[list[str]]:
        """Each command run, as [name, *args, stdin]."""
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]

    def settings(self) -> dict[str, Any]:
        path = self.copy / "hosts/box/settings.json"
        settings: dict[str, Any] = json.loads(path.read_text())
        return settings

    def firmware(self, setup: bool) -> None:
        """The firmware's Secure Boot variables: Setup Mode or not."""
        efivars = self.mnt.parent / "efi/efivars"
        efivars.mkdir(exist_ok=True)
        guid = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
        for name, value in (("SetupMode", setup), ("SecureBoot", False)):
            (efivars / f"{name}-{guid}").write_bytes(
                b"\x06\x00\x00\x00" + bytes([value])
            )


class Encrypting(Installing):
    """Phase 1 told to encrypt, with an empty disk for data at /data."""

    def install(self) -> list[list[str]]:
        answers = [
            "de-latin1",
            "/dev/vdz",
            "",  # encrypted, the default
            "",  # /dev/vdy: no, the default
            "y",  # /dev/vdx: for data
            "/nix/data",  # the system's
            "",  # /data, the default
            "y",  # erase it
            "box",
            USER,
            "Europe/Berlin",
            "de_DE.UTF-8",
            "y",
        ]
        passwords = [PASSPHRASE, PASSPHRASE, "secret-1", "secret-1"]
        passwords += ["secret-2", "secret-2"]
        with (
            mock.patch("builtins.input", side_effect=answers),
            mock.patch("getpass.getpass", side_effect=passwords),
        ):
            phase1.main()
        return self.calls_made()


class Declining(Installing):
    """Phase 1 told not to encrypt, with answers it asks again."""

    def install(self, erase: str = "y") -> list[list[str]]:
        answers = [
            "de-latin1",
            "",  # no default: three disks would take it
            "/dev/vdz",
            "n",  # not encrypted
            "Bad Host!",
            "box",
            USER,
            "Mars/Olympus",
            "Europe/Berlin",
            "klingon",
            "en_US.UTF-8",
            erase,
        ]
        passwords = ["secret-1", "secret-1", "secret-2", "secret-2"]
        with (
            mock.patch("builtins.input", side_effect=answers),
            mock.patch("getpass.getpass", side_effect=passwords),
        ):
            phase1.main()
        return self.calls_made()


class Encrypted(Encrypting):
    def test_the_settings_say_what_was_asked_and_found(self) -> None:
        calls = self.install()
        luks = {
            call[-2]: arg.removeprefix("--uuid=")
            for call in calls
            if call[:2] == ["cryptsetup", "luksFormat"]
            for arg in call
            if arg.startswith("--uuid=")
        }
        btrfs = {
            call[-2]: arg.removeprefix("--uuid=")
            for call in calls
            if call[0] == "mkfs.btrfs"
            for arg in call
            if arg.startswith("--uuid=")
        }
        self.assertEqual(
            self.settings(),
            {
                "hostname": "box",
                "user": USER,
                "timezone": "Europe/Berlin",
                "country": "DE",
                "locale": "de_DE.UTF-8",
                "keymap": "de-latin1",
                "xkb": {
                    "layout": "de",
                    "model": "pc105",
                    "options": "terminate:ctrl_alt_bksp",
                },
                "esp": ESP,
                "root": {
                    "luks": luks["/dev/vdz2"],
                    "filesystem": btrfs["/dev/mapper/root"],
                },
                "data": [
                    {
                        "name": "data",
                        "mount": "/data",
                        "luks": luks["/dev/vdx1"],
                        "filesystem": btrfs["/dev/mapper/data"],
                    }
                ],
                "gpus": ["nvidia"],
                "tpm": False,
                "volumeKey": None,
                "stateVersion": "26.11",
            },
        )

    def test_installs_from_the_copy_in_the_new_home(self) -> None:
        calls = self.install()
        run = [call[:-1] for call in calls]
        copy = str(self.copy)
        self.assertTrue((self.copy / "flake.nix").exists())
        self.assertFalse((self.copy / "jupiter/__pycache__").exists())
        self.assertEqual(
            (self.copy / "hosts/box/hardware-configuration.nix").read_text(),
            HARDWARE,
        )
        generate = [
            "nixos-generate-config", "--root", str(self.mnt),
            "--no-filesystems", "--show-hardware-config",
        ]  # fmt: skip
        install = [
            "nixos-install", "--root", str(self.mnt), "--no-root-passwd",
            "--no-channel-copy", "--flake", f"{copy}#box",
        ]  # fmt: skip
        tracked = ["git", "-C", copy, "add", "--", "hosts/box"]
        for command in (generate, tracked, install):
            self.assertIn(command, run)
        # The flake sees tracked files alone: added before it is built.
        self.assertLess(run.index(tracked), run.index(install))

    def test_the_subvolumes_and_their_mounts(self) -> None:
        run = [call[:-1] for call in self.install()]
        self.assertIn(
            ["btrfs", "subvolume", "create"]
            + [
                str(self.mnt / name) for name in ("@", "@home", "@log", "@nix")
            ],
            run,
        )
        self.assertIn(
            [
                "mount", "--mkdir", "-o", "compress=zstd,subvol=@nix",
                "/dev/mapper/root", str(self.mnt / "nix"),
            ],
            run,
        )  # fmt: skip

    def test_secure_boot_keys_before_the_install(self) -> None:
        self.firmware(setup=True)
        run = [call[:-1] for call in self.install()]
        keys = self.mnt / "var/lib/sbctl"
        create = [
            *phase1.NIX, "shell", "nixpkgs#sbctl", "--command", "sbctl",
            "create-keys", "--database-path", str(keys / "GUID"),
            "--export", str(keys / "keys"),
        ]  # fmt: skip
        enroll = [
            "nixos-enter", "--root", str(self.mnt), "--",
            "sbctl", "enroll-keys", "--microsoft",
        ]  # fmt: skip
        install = next(call for call in run if call[0] == "nixos-install")
        self.assertLess(run.index(create), run.index(install))
        self.assertGreater(run.index(enroll), run.index(install))
        self.assertEqual(keys.stat().st_mode & 0o777, 0o700)

    def test_no_enrolment_outside_setup_mode(self) -> None:
        self.firmware(setup=False)
        run = [call[:-1] for call in self.install()]
        self.assertFalse([call for call in run if "enroll-keys" in call])
        printed = " ".join(str(c.args) for c in self.printed.call_args_list)
        self.assertIn("not in Setup Mode", printed)

    def test_the_data_disk_is_its_users(self) -> None:
        run = [call[:-1] for call in self.install()]
        own = [
            "nixos-enter", "--root", str(self.mnt), "--",
            "chown", f"{USER}:", "/data",
        ]  # fmt: skip
        self.assertIn(own, run)
        home = [
            "nixos-enter", "--root", str(self.mnt), "--",
            "chown", "--recursive", f"{USER}:", f"/home/{USER}",
        ]  # fmt: skip
        self.assertIn(home, run)

    def test_carries_the_isos_wifi(self) -> None:
        self.install()
        saved = self.mnt / phase1.NM_CONNECTIONS / "home.nmconnection"
        self.assertEqual(saved.read_text(), WIFI)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)


class Unencrypted(Declining):
    def test_no_volume_no_keys(self) -> None:
        run = [call[:-1] for call in self.install()]
        self.assertFalse([call for call in run if call[0] == "cryptsetup"])
        self.assertFalse([call for call in run if call[0] == "nix"])
        settings = self.settings()
        self.assertIsNone(settings["root"]["luks"])
        self.assertEqual(settings["data"], [])
        self.assertIn(
            [
                "mkfs.btrfs",
                "--force",
                "--uuid=" + settings["root"]["filesystem"],
                "/dev/vdz2",
            ],
            run,
        )

    def test_asks_again_until_an_answer_is_valid(self) -> None:
        self.install()
        settings = self.settings()
        self.assertEqual(
            (settings["hostname"], settings["timezone"], settings["locale"]),
            ("box", "Europe/Berlin", "en_US.UTF-8"),
        )
        printed = " ".join(str(c.args) for c in self.printed.call_args_list)
        for refused in ("'Bad Host!'", "'Mars/Olympus'", "'klingon'"):
            self.assertIn(refused, printed)

    def test_nothing_is_erased_without_a_yes(self) -> None:
        with self.assertRaises(SystemExit):
            self.install(erase="")
        self.assertEqual(
            [call[0] for call in self.calls_made()],
            ["localectl", "loadkeys", "lsblk", "timedatectl"],
        )


class Refusing(Installing):
    def test_without_uefi(self) -> None:
        shutil.rmtree(self.mnt.parent / "efi")
        with self.assertRaisesRegex(SystemExit, "UEFI"):
            phase1.main()


class Found(unittest.TestCase):
    """What phase 1 reads off the machine, against stand-in files."""

    def test_the_country_of_a_time_zone(self) -> None:
        for zone, country in (
            ("Europe/Berlin", "DE"),
            ("UTC", None),
            ("Mars/Olympus", None),
        ):
            with self.subTest(zone=zone):
                self.assertEqual(phase1.country(zone, ZONE_TAB), country)

    def test_the_x_layout_of_a_keymap(self) -> None:
        self.assertEqual(phase1.keyboard("us", KBD_MODEL_MAP), {})
        self.assertEqual(
            phase1.keyboard("de-latin1", KBD_MODEL_MAP)["layout"], "de"
        )

    def test_the_gpus_drivers(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        devices = root / "sys/bus/pci/devices"
        for slot, (kind, vendor, device) in enumerate(
            (
                ("0x030000", "0x8086", "0x9a49"),  # Intel's
                ("0x030200", "0x10de", "0x2684"),  # NVIDIA's, Ada
                ("0x030000", "0x10de", "0x1c82"),  # NVIDIA's, Pascal
                ("0x020000", "0x1002", "0x1234"),  # AMD's, but a NIC
            )
        ):
            folder = devices / f"0000:0{slot}:00.0"
            folder.mkdir(parents=True)
            (folder / "class").write_text(f"{kind}\n")
            (folder / "vendor").write_text(f"{vendor}\n")
            (folder / "device").write_text(f"{device}\n")
        self.assertEqual(phase1.gpus(root), ["intel", "nouveau", "nvidia"])

    def test_the_kbd_model_map_beside_localectl(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "bin").mkdir()
        (root / "bin/localectl").write_text("")
        (root / "bin/localectl").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(root / "bin")}):
            self.assertEqual(
                phase1._kbd_model_map(),
                root.resolve() / "share/systemd/kbd-model-map",
            )
        with (
            mock.patch.dict(os.environ, {"PATH": str(root)}),
            self.assertRaisesRegex(SystemExit, "localectl"),
        ):
            phase1._kbd_model_map()


if __name__ == "__main__":
    unittest.main()
