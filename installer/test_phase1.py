"""Phase 1 from the first question to the last file, with nothing real.

PATH holds only a stand-in that records how each command was called (and
answers the ones phase 1 reads), /mnt is a temporary folder and the answers
come from a list, so no disk, mount or user is touched: what phase 1 would
run, on which disk, and what it writes into the new system, encrypted or
not.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import disks, questions, secureboot
from jupiter.arch import phase1
from jupiter.common import INSTALLER_DIR

from harness import no_stdin
from harness.disks import GIB, KBD_MODEL_MAP, LSBLK

UUID = "0a1b2c3d-1111-2222-3333-444455556666"
# What each command prints, and what pacstrap leaves that phase 1 writes into.
STAND_IN = f"""#!{sys.executable}
import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
# Every command's stdin, so a secret given to any is seen (the test's own
# stdin is /dev/null: one given nothing reads nothing).
data = sys.stdin.read()
disk = args[-1]
table = {{"partitiontable": {{"partitions": [
    {{"node": disk + "1"}}, {{"node": disk + "2"}}
]}}}}
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps([name, *args, data]) + "\\n")
print({{
    "lsblk": os.environ.get("LSBLK") or {json.dumps(json.dumps(LSBLK))},
    "timedatectl": "UTC\\nEurope/Berlin",
    "localectl": "us\\nde-latin1",
    "sfdisk": json.dumps(table) if "--json" in args else "",
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
    "cryptsetup",
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
    "loadkeys",
]
USER = "jupitertest"


def btrfs_formatted(run: list[list[str]]) -> list[str]:
    """The devices mkfs.btrfs formatted, each with a UUID phase 1 chose."""
    return [
        call[-1]
        for call in run
        if call[:2] == ["mkfs.btrfs", "--force"]
        and any(arg.startswith("--uuid=") for arg in call)
    ]


class Installing(unittest.TestCase):
    """A live ISO of stand-ins, a temporary /mnt and an NVIDIA machine."""

    def setUp(self) -> None:
        no_stdin(self)
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
        # The disks' steps are the shared disks.py's, by its own constants.
        for name, value in {
            "MNT": self.mnt,
            "EFI": tmp / "efi",
            "ERASED": tmp / "jupiter-erased",
        }.items():
            self.enterContext(mock.patch.object(disks, name, value))
        for name, setting in {
            "LIVE": True,
            "LOCALE_GEN": tmp / "locale.gen",
            "KBD_MODEL_MAP": tmp / "kbd-model-map",
            "IWD": tmp / "iwd",
        }.items():
            self.enterContext(mock.patch.object(phase1, name, setting))
        # A machine with only an NVIDIA card, whatever this one has.
        drivers = {"amd-ucode", *phase1.NVIDIA}
        self.enterContext(
            mock.patch.object(phase1, "drivers", return_value=drivers)
        )
        # Nothing but the stand-ins: an unexpected command fails to start.
        environment = {"PATH": str(stand_ins), "CALLS": str(self.calls)}
        self.enterContext(mock.patch.dict(os.environ, environment))
        self.printed = self.enterContext(mock.patch("builtins.print"))

    def calls_made(self) -> list[list[str]]:
        """Each command run, as [name, *args, stdin]."""
        return [
            json.loads(line) for line in self.calls.read_text().splitlines()
        ]


PASSPHRASE = "a passphrase: typed\\ as is"


class Encrypting(Installing):
    """Phase 1 told to encrypt, with an empty disk for data at /data."""

    # The disks phase 1 lists after the system disk, in lsblk's order, and
    # each answer: the empty ones are asked about, the others left alone.
    DATA_ANSWERS: tuple[str, ...] = (
        "",  # /dev/vdy: no, the default
        "y",  # /dev/vdx: for data
        "/boot/data",  # not a folder of its own
        "/root",  # the system's
        "",  # /data, the default
        "y",  # erase it
    )

    def firmware(self, setup: bool, secure_boot: bool = False) -> None:
        """The firmware's Secure Boot variables: Setup Mode or not."""
        efivars = self.mnt.parent / "efi/efivars"
        efivars.mkdir(exist_ok=True)
        guid = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
        attributes = b"\x06\x00\x00\x00"
        for name, value in (("SetupMode", setup), ("SecureBoot", secure_boot)):
            (efivars / f"{name}-{guid}").write_bytes(
                attributes + bytes([value])
            )

    def install(self) -> list[list[str]]:
        answers = [
            "de-latin1",
            "/dev/vdz",
            "",  # encrypted, the default
            *self.DATA_ANSWERS,
            "box",
            USER,
            "UTC",
            "en_US.UTF-8",
            "y",
        ]
        passwords = [
            PASSPHRASE,
            PASSPHRASE,
            "secret-1",
            "secret-1",
            "secret-2",
            "secret-2",
        ]
        with (
            mock.patch("builtins.input", side_effect=answers) as asked,
            mock.patch("getpass.getpass", side_effect=passwords) as typed,
        ):
            phase1.main()
        self.questions = [call.args[0] for call in asked.call_args_list]
        self.prompts = [call.args[0] for call in typed.call_args_list]
        return self.calls_made()

    def luks_uuid(self, calls: list[list[str]], partition: str) -> str:
        """The UUID phase 1 gave the LUKS volume on a partition."""
        [uuid] = [
            arg.removeprefix("--uuid=")
            for call in calls
            if call[:2] == ["cryptsetup", "luksFormat"] and partition in call
            for arg in call
            if arg.startswith("--uuid=")
        ]
        return uuid


class Declining(Installing):
    """Phase 1 told not to encrypt: the questions it always asked."""

    def install(self, erase: str = "y") -> list[list[str]]:
        answers = [
            "de-latin1",
            "",  # no default: three disks would take it
            "/dev/nope",  # not offered
            "/dev/vdz",
            "n",  # not encrypted
            "Bad Host!",  # not a hostname
            "box",
            USER,
            "Mars/Olympus",  # not a time zone
            "Europe/Berlin",
            "de_DE.UTF-8",
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


class PhaseOne(Declining):
    def test_installs_on_the_disk_confirmed(self) -> None:
        calls = self.install()
        mnt = str(self.mnt)
        run = [call[:-1] for call in calls]
        self.assertEqual(
            [call[0] for call in calls[:4]],
            ["localectl", "loadkeys", "lsblk", "timedatectl"],
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
        self.assertIn("/dev/vdz2", btrfs_formatted(run))
        for command in (
            ["mkfs.fat", "-F", "32", "/dev/vdz1"],
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
            # Unencrypted too, systemd-boot updates with systemd.
            [
                "arch-chroot",
                "-S",
                mnt,
                "systemctl",
                "enable",
                "systemd-boot-update.service",
            ],
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
        self.assertTrue(entry.endswith(" quiet loglevel=3\n"), entry)

    def test_boots_without_waiting(self) -> None:
        """No menu, and an initramfs that only finds the root."""
        self.install()
        hooks = (self.mnt / "etc/mkinitcpio.conf.d/jupiter.conf").read_text()
        self.assertEqual(hooks, f"HOOKS=({phase1.HOOKS})\n")
        for hook in ("kms", "fsck", "keymap", "consolefont"):
            self.assertNotIn(hook, phase1.HOOKS.split())
        for hook in ("udev", "block", "filesystems", "keyboard"):
            self.assertIn(hook, phase1.HOOKS.split())
        loader = self.mnt / "boot/loader/loader.conf"
        self.assertEqual(loader.read_text(), "timeout 0\n")

    def test_keeps_a_timeout_bootctl_set(self) -> None:
        loader = self.mnt / "boot/loader/loader.conf"
        loader.parent.mkdir(parents=True)
        loader.write_text("default arch.conf\ntimeout 5\n")
        self.install()
        self.assertEqual(loader.read_text(), "default arch.conf\ntimeout 5\n")

    def test_leaves_itself_in_the_new_home(self) -> None:
        calls = self.install()
        copy = self.mnt / "home" / USER / INSTALLER_DIR.name
        self.assertTrue((copy / "jupiter/arch/phase1.py").exists())
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
        self.assertEqual(
            calls, ["localectl", "loadkeys", "lsblk", "timedatectl"]
        )
        self.assertEqual(list(self.mnt.iterdir()), [])


class EncryptedInstall(Encrypting):
    def test_asks_for_the_passphrase_twice_after_the_disk(self) -> None:
        self.install()
        self.assertEqual(
            self.questions[:3],
            ["Keymap [us]: ", "Disk: ", "Encrypt /dev/vdz? [Y/n] "],
        )
        self.assertEqual(
            self.prompts[:2], ["Passphrase for the disk: ", "Repeat it: "]
        )

    def test_puts_the_system_on_luks2(self) -> None:
        calls = self.install()
        mnt = str(self.mnt)
        luks = self.luks_uuid(calls, "/dev/vdz2")
        run = [call[:-1] for call in calls]
        format_ = [
            "cryptsetup",
            "luksFormat",
            "--type=luks2",
            "--batch-mode",
            f"--uuid={luks}",
            "--key-file=-",
            "/dev/vdz2",
        ]
        opened = ["cryptsetup", "open", "--key-file=-", "/dev/vdz2", "root"]
        for command in (
            format_,
            opened,
            [
                "mount",
                "--mkdir",
                "-o",
                "compress=zstd,subvol=@home",
                "/dev/mapper/root",
                f"{mnt}/home",
            ],
            ["mkfs.fat", "-F", "32", "/dev/vdz1"],
        ):
            self.assertIn(command, run)
        self.assertLess(run.index(format_), run.index(opened))
        self.assertIn("/dev/mapper/root", btrfs_formatted(run))
        self.assertNotIn("/dev/vdz2", btrfs_formatted(run))

    def test_opens_the_root_in_the_initramfs_with_trim(self) -> None:
        calls = self.install()
        crypttab = (self.mnt / "etc/crypttab").read_text().splitlines()
        root = self.luks_uuid(calls, "/dev/vdz2")
        data = self.luks_uuid(calls, "/dev/vdx1")
        self.assertEqual(
            crypttab,
            [
                f"root UUID={root} none "
                "discard,x-initrd.attach,tpm2-measure-pcr=yes",
                f"data UUID={data} /etc/cryptsetup-keys.d/data.key "
                "discard,nofail,x-systemd.device-timeout=10s",
            ],
        )
        hooks = (self.mnt / "etc/mkinitcpio.conf.d/jupiter.conf").read_text()
        self.assertEqual(hooks, f"HOOKS=({phase1.ENCRYPTED_HOOKS})\n")
        names = phase1.ENCRYPTED_HOOKS.split()
        for hook in ("systemd", "sd-vconsole", "sd-encrypt", "block"):
            self.assertIn(hook, names)
        for hook in ("base", "udev", "encrypt", "keymap", "kms", "fsck"):
            self.assertNotIn(hook, names)
        # Every keyboard's driver: the passphrase may be typed on another.
        self.assertLess(names.index("keyboard"), names.index("autodetect"))
        self.assertLess(names.index("sd-vconsole"), names.index("sd-encrypt"))
        # Built again once crypttab is there, after pacstrap built one.
        run = [call[:-1] for call in calls]
        rebuild = [
            "arch-chroot",
            "-S",
            str(self.mnt),
            "mkinitcpio",
            "--allpresets",
        ]
        self.assertIn(rebuild, run)
        pacstrap = next(
            i for i, call in enumerate(run) if call[0] == "pacstrap"
        )
        self.assertGreater(run.index(rebuild), pacstrap)
        # Typed in the console keymap chosen.
        self.assertIn(
            "KEYMAP=de-latin1\n", (self.mnt / "etc/vconsole.conf").read_text()
        )

    def test_makes_the_chosen_disk_a_data_disk(self) -> None:
        calls = self.install()
        mnt = self.mnt
        run = [call[:-1] for call in calls]
        key = mnt / "etc/cryptsetup-keys.d/data.key"
        data = self.luks_uuid(calls, "/dev/vdx1")
        layout = next(
            call[-1]
            for call in calls
            if call[0] == "sfdisk"
            and "/dev/vdx" in call
            and "--json" not in call
        )
        self.assertEqual(layout, f"label: gpt\ntype={disks.DATA_TYPE}\n")
        [btrfs] = [
            call
            for call in run
            if call[0] == "mkfs.btrfs" and "/dev/mapper/data" in call
        ]
        filesystem = btrfs[2].removeprefix("--uuid=")
        for command in (
            [
                "sfdisk",
                "--wipe",
                "always",
                "--wipe-partitions",
                "always",
                "/dev/vdx",
            ],
            ["cryptsetup", "open", "--key-file=-", "/dev/vdx1", "data"],
            [
                "cryptsetup",
                "luksAddKey",
                "--batch-mode",
                "--pbkdf=pbkdf2",
                "--pbkdf-force-iterations=1000",
                "--new-key-slot=1",
                "--key-file=-",
                "/dev/vdx1",
                str(key),
            ],
            # The key file's slot tried first, before the passphrase's.
            [
                "cryptsetup",
                "config",
                "--key-slot=1",
                "--priority=prefer",
                "/dev/vdx1",
            ],
            [
                "mkfs.btrfs",
                "--force",
                f"--uuid={filesystem}",
                "/dev/mapper/data",
            ],
            [
                "mount",
                "--mkdir",
                "-o",
                "compress=zstd",
                "/dev/mapper/data",
                f"{mnt}/data",
            ],
            ["arch-chroot", "-S", str(mnt), "chown", f"{USER}:", "/data"],
        ):
            self.assertIn(command, run)
        self.assertTrue(data)
        fstab = (mnt / "etc/fstab").read_text()
        self.assertTrue(
            fstab.endswith(
                f"UUID={filesystem} /data btrfs "
                "compress=zstd,nofail,x-systemd.device-timeout=10s 0 0\n"
            ),
            fstab,
        )
        self.assertEqual(len(key.read_bytes()), 64)

    def test_lists_the_disks_it_leaves_alone(self) -> None:
        self.install()
        printed = [
            str(call.args[0])
            for call in self.printed.call_args_list
            if call.args
        ]
        self.assertIn(
            "  /dev/vdw  500 GiB  Windows: left alone (gpt, vfat, ntfs)",
            printed,
        )
        self.assertIn(
            "  /dev/sda  32 GiB  Stick: left alone (in use)", printed
        )
        asked = [
            q for q in self.questions if q.startswith("Erase and encrypt")
        ]
        self.assertEqual(
            asked,
            [
                "Erase and encrypt /dev/vdy  32 GiB  Other for data? [y/N] ",
                "Erase and encrypt /dev/vdx  8 GiB  Data for data? [y/N] ",
            ],
        )
        self.assertIn("Erase everything on /dev/vdx? [y/N] ", self.questions)
        self.assertIn("Mount it at [/data]: ", self.questions)

    def test_a_data_disk_needs_its_own_yes(self) -> None:
        self.DATA_ANSWERS = ("", "y", "", "n")  # no to erasing /dev/vdx
        calls = self.install()
        self.assertNotIn("/dev/vdx", json.dumps(calls))
        self.assertEqual(
            (self.mnt / "etc/crypttab").read_text().count("\n"), 1
        )
        self.assertFalse((self.mnt / "etc/cryptsetup-keys.d").exists())


class Keymap(Encrypting):
    def test_is_asked_and_loaded_before_any_password_is_typed(self) -> None:
        loaded_by_then = []
        new_password = questions.new_password

        def asked(*args: str) -> str:
            loaded_by_then.append("loadkeys" in self.calls.read_text())
            return new_password(*args)

        with mock.patch.object(questions, "new_password", side_effect=asked):
            self.install()
        self.assertEqual(self.questions[0], "Keymap [us]: ")
        self.assertEqual(
            loaded_by_then, [True, True, True]
        )  # disk, user, root
        self.assertIn(["loadkeys", "de-latin1", ""], self.calls_made())


class Rerun(Encrypting):
    """Phase 1 again after an attempt that failed past partitioning: its
    volumes still open, its data disk half made."""

    def test_closes_what_the_last_attempt_left_open(self) -> None:
        devices = json.loads(json.dumps(LSBLK))
        target = devices["blockdevices"][1]
        target["children"] = [
            {"name": "/dev/vdz2", "size": 63 * GIB, "type": "part",
             "mountpoints": [None], "fstype": "crypto_LUKS",
             "children": [{"name": "/dev/mapper/root", "size": 63 * GIB,
                           "type": "crypt", "mountpoints": [None],
                           "fstype": "btrfs"}]},
        ]  # fmt: skip
        os.environ["LSBLK"] = json.dumps(devices)
        calls = [call[:-1] for call in self.install()]
        close = ["cryptsetup", "close", "/dev/mapper/root"]
        self.assertIn(close, calls)
        self.assertLess(
            calls.index(close),
            calls.index(["sfdisk", "--wipe", "always", "--wipe-partitions",
                         "always", "/dev/vdz"]),
        )  # fmt: skip
        self.assertEqual([c[0] for c in calls].count("lsblk"), 2, "read again")

    def test_leaves_a_volume_in_use_open(self) -> None:
        devices = json.loads(json.dumps(LSBLK))
        devices["blockdevices"][4]["children"][0]["children"] = [
            {"name": "/dev/mapper/stick", "size": GIB, "type": "crypt",
             "mountpoints": ["/somewhere"]},
        ]  # fmt: skip
        os.environ["LSBLK"] = json.dumps(devices)
        calls = self.install()
        self.assertFalse(
            [c for c in calls if c[:2] == ["cryptsetup", "close"]]
        )

    def test_remembers_the_data_disks_it_erases(self) -> None:
        self.install()
        self.assertEqual(disks.ERASED.read_text(), "/dev/vdx\n")

    def test_offers_again_a_data_disk_it_had_begun(self) -> None:
        disks.ERASED.write_text("/dev/vdw\n")  # as if it had made it
        self.DATA_ANSWERS = (*self.DATA_ANSWERS, "")  # no to it this time
        self.install()
        self.assertIn(
            "Erase and encrypt /dev/vdw  500 GiB  Windows for data? [y/N] ",
            self.questions,
        )


class DiskChoice(Encrypting):
    def test_says_what_each_disk_holds_and_offers_no_default(self) -> None:
        self.install()
        printed = [
            str(c.args[0]) for c in self.printed.call_args_list if c.args
        ]
        for line in (
            "  /dev/vdy  32 GiB  Other  (empty)",
            "  /dev/vdz  64 GiB  Target  (empty)",
            "  /dev/vdw  500 GiB  Windows  (gpt, vfat, ntfs)",
        ):
            self.assertIn(line, printed)
        self.assertIn("Disk: ", self.questions)

    def test_offers_the_only_disk_as_the_default(self) -> None:
        devices = {"blockdevices": [LSBLK["blockdevices"][1]]}
        os.environ["LSBLK"] = json.dumps(devices)
        self.DATA_ANSWERS = ()
        self.install()
        self.assertIn("Disk [/dev/vdz]: ", self.questions)


class Wifi(Encrypting):
    """The networks the live ISO joined with iwctl, joined again after the
    reboot through NetworkManager."""

    def test_carries_a_wpa_network_over_root_only(self) -> None:
        phase1.IWD.mkdir()
        # As iwd writes it (iwd.network(5)): the backslash escaped, a
        # leading space as \s, the escapes a NetworkManager keyfile reads.
        (phase1.IWD / "Home Net.psk").write_text(
            "[Security]\nPreSharedKey=abcd\nPassphrase=\\spa\\\\ss word\n"
        )
        (phase1.IWD / "=caf\u00e9.psk").write_text(
            "[Security]\nPassphrase=x\n"
        )
        (phase1.IWD / "Cafe.open").write_text("")
        (phase1.IWD / "Hex only.psk").write_text(
            "[Security]\nPreSharedKey=ab\n"
        )
        self.install()
        folder = self.mnt / phase1.NM_CONNECTIONS
        self.assertEqual(
            sorted(p.name for p in folder.iterdir()), ["Home Net.nmconnection"]
        )
        saved = folder / "Home Net.nmconnection"
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        text = saved.read_text()
        for line in ("id=Home Net", "type=wifi", "ssid=Home Net",
                     "key-mgmt=wpa-psk", "psk=\\spa\\\\ss word"):  # fmt: skip
            self.assertIn(f"\n{line}\n", "\n" + text)

    def test_none_without_iwd(self) -> None:
        self.install()
        self.assertFalse((self.mnt / phase1.NM_CONNECTIONS).exists())


class SignedBoot(Encrypting):
    """Encrypted: a unified kernel image, signed with keys of the system's
    own, enrolled when the firmware is in Setup Mode."""

    def chroot(self, calls: list[list[str]]) -> list[list[str]]:
        prefix = ["arch-chroot", "-S", str(self.mnt)]
        return [call[3:-1] for call in calls if call[:3] == prefix]

    def test_builds_a_unified_kernel_image_only(self) -> None:
        calls = self.install()
        self.assertEqual(
            (self.mnt / "etc/kernel/cmdline").read_text(),
            "root=/dev/mapper/root rootflags=subvol=@ rw zswap.enabled=0"
            " quiet loglevel=3\n",
        )
        preset = (self.mnt / "etc/mkinitcpio.d/linux.preset").read_text()
        self.assertIn("PRESETS=('default')\n", preset)
        self.assertIn('default_uki="/boot/EFI/Linux/arch-linux.efi"\n', preset)
        self.assertNotIn("_image=", preset)
        self.assertNotIn("fallback", preset.replace("# ", ""))
        self.assertFalse((self.mnt / "boot/loader/entries/arch.conf").exists())
        self.assertEqual(
            (self.mnt / "boot/loader/loader.conf").read_text(), "timeout 0\n"
        )
        pacstrap = next(call for call in calls if call[0] == "pacstrap")
        self.assertTrue({"sbctl", "tpm2-tss"} <= set(pacstrap))
        # Written before pacstrap builds the first image.
        self.assertTrue(
            (self.mnt / "etc/kernel/cmdline").stat().st_mtime
            <= (self.mnt / "etc/fstab").stat().st_mtime
        )

    def test_signs_systemd_boot_and_the_image(self) -> None:
        self.firmware(setup=True)
        chroot = self.chroot(self.install())
        boot = "/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
        order = [
            ["sbctl", "create-keys"],
            ["sbctl", "enroll-keys", "--microsoft", "--firmware-builtin"],
            ["sbctl", "sign", "--save", "--output", f"{boot}.signed", boot],
            ["bootctl", "install"],
            ["systemctl", "enable", "systemd-boot-update.service"],
            ["mkinitcpio", "--allpresets"],
        ]
        indexes = [chroot.index(command) for command in order]
        self.assertEqual(indexes, sorted(indexes), chroot)

    def test_enrols_keys_only_in_setup_mode(self) -> None:
        for setup, secure_boot in ((False, True), (False, False)):
            with self.subTest(setup=setup, secure_boot=secure_boot):
                self.calls.write_text("")
                self.printed.reset_mock()  # this subtest's output alone
                for path in self.mnt.iterdir():
                    shutil.rmtree(path)
                self.firmware(setup, secure_boot)
                chroot = self.chroot(self.install())
                self.assertIn(["sbctl", "create-keys"], chroot)
                self.assertFalse(
                    [call for call in chroot if "enroll-keys" in call]
                )
                printed = [
                    call.args[0]
                    for call in self.printed.call_args_list
                    if call.args
                ]
                self.assertIn(secureboot.SETUP_MODE_HELP, printed)

    def test_says_when_the_firmware_has_no_secure_boot(self) -> None:
        self.install()
        printed = [c.args[0] for c in self.printed.call_args_list if c.args]
        self.assertEqual(printed[0], secureboot.NO_SECURE_BOOT_HELP)

    def test_goes_on_when_the_keys_cannot_be_enrolled(self) -> None:
        self.firmware(setup=True)
        self.calls.write_text("")
        stand_in = Path(os.environ["PATH"]) / "arch-chroot"
        stand_in.write_text(
            stand_in.read_text() + "if 'enroll-keys' in args: sys.exit(1)\n"
        )
        chroot = self.chroot(self.install())
        self.assertIn(["mkinitcpio", "--allpresets"], chroot)
        warnings = [c.args[0] for c in self.printed.call_args_list if c.args]
        self.assertIn("phase 4 says what is left", "".join(map(str, warnings)))

    def test_enrols_microsofts_alone_where_the_defaults_are_refused(
        self,
    ) -> None:
        # sbctl refuses firmware defaults it cannot trust (non-volatile).
        self.firmware(setup=True)
        self.calls.write_text("")
        stand_in = Path(os.environ["PATH"]) / "arch-chroot"
        stand_in.write_text(
            stand_in.read_text()
            + "if '--firmware-builtin' in args: sys.exit(1)\n"
        )
        chroot = self.chroot(self.install())
        enrolled = [call for call in chroot if "enroll-keys" in call]
        self.assertEqual(
            enrolled,
            [
                ["sbctl", "enroll-keys", "--microsoft", "--firmware-builtin"],
                ["sbctl", "enroll-keys", "--microsoft"],
            ],
        )
        warnings = [c.args[0] for c in self.printed.call_args_list if c.args]
        self.assertNotIn("Could not enrol", "".join(map(str, warnings)))


if __name__ == "__main__":
    unittest.main()
