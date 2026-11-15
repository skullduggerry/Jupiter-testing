"""Phase 4's TPM step (jupiter/tpm.py) against stand-ins: binding the root
volume to the TPM, its recovery key and header backup, and what it says
where something is missing.

The machine is a folder: its TPM (tpm_version_major, PCR 7), its EFI
variables (Secure Boot's state, systemd-stub's mark), /etc/crypttab, the
image's command line (/etc/kernel/cmdline) and the measurement log. Each command (sudo, findmnt, lsblk, cryptsetup,
systemd-cryptenroll, sbctl, mkinitcpio, install, chown) is a stand-in that
records its argv and stdin and answers from the LUKS header kept in
`header.json`, which systemd-cryptenroll's stand-in writes its slots into, as
the real one does.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import secureboot, tpm

PCR7 = "a2" * 32
RECOVERY_KEY = "fjvtrkhn-ghvuedtr-kbdunjtv-rldnhvcg-bhcrhdnv-gvthjtkf"
LUKS_UUID = "11111111-2222-3333-4444-555555555555"
VOLUME_KEY_ID = (
    "b7c790dc40a5191f93aa2a089926c9378f54441a6d08145890e7598aaec280a6"
)
CRYPTTAB = f"root UUID={LUKS_UUID} none discard,x-initrd.attach\n"
OPTIONS = "rootflags=subvol=@ rw zswap.enabled=0 quiet loglevel=3"
CMDLINE = f"root=/dev/mapper/root {OPTIONS}\n"
# As phase 1 wrote it before: by the file system's UUID.
OLD_CMDLINE = f"root=UUID=0a1b2c3d-1111-2222-3333-444455556666 {OPTIONS}\n"
GLOBAL = secureboot.GLOBAL
STAND_IN = f"""#!{sys.executable}
import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
if name == "sudo":
    os.execvp(args[0], args)
world = os.environ["WORLD"]
with open(os.path.join(world, "calls"), "a") as calls:
    calls.write(json.dumps([name, *args]) + "\\n")
header_path = os.path.join(world, "header.json")
header = json.load(open(header_path))
if name == "findmnt":
    print("/dev/mapper/root[/@]")
elif name == "lsblk":
    print("/dev/mapper/root btrfs")
    print("/dev/vda2       crypto_LUKS")
elif name == "sbctl" and args[0] == "status":
    print(json.dumps({{"installed": os.path.exists(os.path.join(world, "keys"))}}))
elif name == "sbctl" and args[0] == "enroll-keys":
    sys.exit(int(os.environ.get("ENROLL_FAILS", "0")))
elif name == "cryptsetup" and args[0] == "luksDump":
    print(json.dumps(header))
elif name == "cryptsetup" and args[0] == "luksUUID":
    print("{LUKS_UUID}")
elif name == "cryptsetup" and args[0] == "luksHeaderBackup":
    open(args[-1], "w").write("header")
elif name == "systemd-cryptenroll":
    tokens = header.setdefault("tokens", {{}})
    if "--recovery-key" in args:
        tokens[str(len(tokens))] = {{"type": "systemd-recovery"}}
        print("recovery key: " + os.environ["RECOVERY_KEY"])
    else:
        for key in [k for k, t in tokens.items() if t["type"] == "systemd-tpm2"]:
            del tokens[key]
        tokens[str(len(tokens) + 10)] = {{
            "type": "systemd-tpm2",
            "tpm2-pcrs": [7, 15],
            "tpm2-policy-hash": os.environ["POLICY"],
        }}
    json.dump(header, open(header_path, "w"))
elif name == "cat":
    # root's sudo cat of a file only root reads: allowed here for a moment.
    mode = os.stat(args[-1]).st_mode
    os.chmod(args[-1], 0o600)
    sys.stdout.write(open(args[-1]).read())
    os.chmod(args[-1], mode)
elif name == "mkinitcpio":
    sys.exit(int(os.environ.get("MKINITCPIO_FAILS", "0")))
elif name == "install":
    os.execvp("/usr/bin/install", ["install", *args])
elif name == "chown":
    pass
"""
COMMANDS = [
    "sudo",
    "findmnt",
    "lsblk",
    "sbctl",
    "cryptsetup",
    "systemd-cryptenroll",
    "mkinitcpio",
    "install",
    "chown",
    "cat",
]


class Machine(unittest.TestCase):
    """An encrypted system booted from its signed image, Secure Boot on."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.world = tmp
        stand_ins = tmp / "bin"
        stand_ins.mkdir()
        for command in COMMANDS:
            (stand_ins / command).write_text(STAND_IN)
            (stand_ins / command).chmod(0o755)
        (tmp / "calls").write_text("")
        (tmp / "header.json").write_text(json.dumps({"tokens": {}}))
        (tmp / "keys").mkdir()
        self.tpm = tmp / "tpm0"
        (self.tpm / "pcr-sha256").mkdir(parents=True)
        (self.tpm / "tpm_version_major").write_text("2\n")
        (self.tpm / "pcr-sha256/7").write_text(PCR7.upper() + "\n")
        self.efivars = tmp / "efivars"
        self.efivars.mkdir()
        self.secure_boot(setup=False, on=True)
        self.stub = self.efivars / f"StubInfo-{tpm.SYSTEMD_VENDOR}"
        self.stub.write_bytes(b"\x06\x00\x00\x00systemd-stub")
        self.crypttab = tmp / "crypttab"
        self.crypttab.write_text(CRYPTTAB)
        # Root's alone on a real system (0600, from systemd's package): the
        # step, which runs as the user, must read it through sudo.
        self.crypttab.chmod(0o000)
        self.cmdline = tmp / "cmdline"
        self.cmdline.write_text(CMDLINE)
        self.measured = tmp / "tpm2-measure.log"
        self.measured.write_text(
            "\x1e"
            + json.dumps(
                {
                    "pcr": 15,
                    "digests": [
                        {"hashAlg": "sha1", "digest": "00" * 20},
                        {"hashAlg": "sha256", "digest": VOLUME_KEY_ID},
                    ],
                    "content_type": "systemd",
                    "content": {"string": f"cryptsetup:root:{LUKS_UUID}"},
                }
            )
            + "\n"
        )
        for name, value in {
            "TPM": self.tpm,
            "STUB_INFO": self.stub,
            "CRYPTTAB": self.crypttab,
            "CMDLINE": self.cmdline,
            "MEASURE_LOG": self.measured,
        }.items():
            self.enterContext(mock.patch.object(tpm, name, value))
        self.enterContext(
            mock.patch.object(secureboot, "EFIVARS", self.efivars)
        )
        environment = {
            "PATH": f"{stand_ins}:/usr/bin",
            "WORLD": str(tmp),
            "POLICY": tpm.policy(PCR7),
            "RECOVERY_KEY": RECOVERY_KEY,
        }
        self.enterContext(mock.patch.dict(os.environ, environment))
        self.printed = self.enterContext(mock.patch("builtins.print"))
        self.answers: list[str] = [""]

    @staticmethod
    def read(path: Path) -> str:
        """A file only root reads, read as root would."""
        mode = path.stat().st_mode
        path.chmod(0o600)
        try:
            return path.read_text()
        finally:
            path.chmod(mode)

    def secure_boot(self, setup: bool, on: bool) -> None:
        for name, value in (("SetupMode", setup), ("SecureBoot", on)):
            (self.efivars / f"{name}-{GLOBAL}").write_bytes(
                b"\x06\x00\x00\x00" + bytes([value])
            )

    def enroll(self) -> list[list[str]]:
        (self.world / "calls").write_text("")
        with mock.patch("builtins.input", side_effect=self.answers):
            tpm.main()
        return [
            json.loads(line)
            for line in (self.world / "calls").read_text().splitlines()
        ]

    def said(self) -> str:
        return "\n".join(
            str(arg)
            for call in self.printed.call_args_list
            for arg in call.args
        )


class Binding(Machine):
    def test_binds_to_pcr_7_and_15_zero(self) -> None:
        calls = self.enroll()
        self.assertIn(
            [
                "systemd-cryptenroll",
                "--wipe-slot=tpm2",
                "--tpm2-device=auto",
                "--tpm2-pcrs=7+15:sha256=" + "0" * 64,
                "/dev/vda2",
            ],
            calls,
        )
        self.assertIn(
            ["systemd-cryptenroll", "--recovery-key", "/dev/vda2"], calls
        )

    def test_tries_the_tpm_and_fixes_the_root_volume_key(self) -> None:
        calls = self.enroll()
        self.assertEqual(
            self.read(self.crypttab),
            f"root UUID={LUKS_UUID} none discard,x-initrd.attach,"
            "tpm2-device=auto,tpm2-measure-pcr=yes,"
            f"fixate-volume-key={VOLUME_KEY_ID}\n",
        )
        self.assertEqual(
            self.read(self.crypttab.parent / "crypttab~"), CRYPTTAB
        )
        self.assertEqual(self.crypttab.stat().st_mode & 0o777, 0o600)
        self.assertIn(["mkinitcpio", "--allpresets"], calls)

    def test_run_again_changes_nothing(self) -> None:
        self.enroll()
        crypttab = self.read(self.crypttab)
        calls = self.enroll()
        self.assertEqual(
            [call[0] for call in calls],
            [
                "findmnt",
                "lsblk",
                "sbctl",
                "cryptsetup",  # luksDump: the TPM slot matches
                "cryptsetup",  # luksUUID
                "cat",  # the measurement log, through sudo
                "cat",  # crypttab, root's alone: it has its options
                "cryptsetup",  # luksDump: a recovery key is there
            ],
        )
        self.assertEqual(self.read(self.crypttab), crypttab)
        self.assertIn("nothing to change", self.said())

    def test_a_failed_image_build_is_built_again_by_a_rerun(self) -> None:
        os.environ["MKINITCPIO_FAILS"] = "1"
        with self.assertRaises(subprocess.CalledProcessError):
            self.enroll()
        self.assertEqual(self.read(self.crypttab), CRYPTTAB, "put back")
        del os.environ["MKINITCPIO_FAILS"]
        calls = self.enroll()
        self.assertIn(["mkinitcpio", "--allpresets"], calls)
        self.assertIn("tpm2-device=auto", self.read(self.crypttab))

    def test_enrols_again_once_pcr_7_changed(self) -> None:
        self.enroll()
        (self.tpm / "pcr-sha256/7").write_text("b3" * 32 + "\n")
        os.environ["POLICY"] = tpm.policy("b3" * 32)
        calls = self.enroll()
        enrolled = [c for c in calls if c[0] == "systemd-cryptenroll"]
        self.assertEqual(len(enrolled), 1)
        self.assertIn("--wipe-slot=tpm2", enrolled[0])
        self.assertIn("PCR 7 changed", self.said())

    def test_waits_a_boot_for_the_volume_key_measured(self) -> None:
        self.measured.unlink()
        self.enroll()
        self.assertEqual(
            self.read(self.crypttab),
            f"root UUID={LUKS_UUID} none discard,x-initrd.attach,"
            "tpm2-device=auto,tpm2-measure-pcr=yes\n",
        )
        self.assertIn("Reboot and run bootstrap.sh 4 again", self.said())

    def test_offers_a_header_backup(self) -> None:
        backup = self.world / "backup" / "header.img"
        backup.parent.mkdir()
        self.answers = [str(self.world / "nowhere/x"), str(backup)]
        calls = self.enroll()
        self.assertIn(
            [
                "cryptsetup",
                "luksHeaderBackup",
                "/dev/vda2",
                "--header-backup-file",
                str(backup),
            ],
            calls,
        )
        self.assertEqual(backup.stat().st_mode & 0o777, 0o400)
        self.assertIn(tpm.BACKUP_HELP, self.said())

    def test_skips_the_header_backup_on_an_empty_answer(self) -> None:
        calls = self.enroll()
        self.assertFalse([c for c in calls if "luksHeaderBackup" in c])


class NamingTheRoot(Machine):
    """An install whose image names the root by its file system's UUID, as
    phase 1 wrote it before: named by its opened volume instead."""

    def setUp(self) -> None:
        super().setUp()
        self.enroll()  # bound already: only the command line is left
        self.printed.reset_mock()
        self.cmdline.write_text(OLD_CMDLINE)

    def test_names_the_opened_volume_and_builds_the_image_again(self) -> None:
        calls = self.enroll()
        self.assertEqual(self.cmdline.read_text(), CMDLINE)
        self.assertEqual(self.cmdline.stat().st_mode & 0o777, 0o644)
        self.assertEqual(
            (self.world / "cmdline~").read_text(), OLD_CMDLINE, "kept"
        )
        self.assertEqual(
            [c for c in calls if c[0] == "mkinitcpio"],
            [["mkinitcpio", "--allpresets"]],
        )
        self.assertIn("now names the root as /dev/mapper/root", self.said())

    def test_leaves_the_tpm_slot_and_the_header_as_they_are(self) -> None:
        # PCR 7 does not cover the command line: nothing to enrol again,
        # and no header backup to offer (no input is asked for).
        self.answers = []
        calls = self.enroll()
        self.assertFalse([c for c in calls if c[0] == "systemd-cryptenroll"])
        self.assertNotIn(tpm.BACKUP_HELP, self.said())

    def test_keeps_the_rest_of_the_line(self) -> None:
        line = f"quiet {OLD_CMDLINE.strip()} console=ttyS0 myroot=UUID=x\n"
        self.cmdline.write_text(line)
        self.enroll()
        self.assertEqual(
            self.cmdline.read_text(),
            f"quiet {CMDLINE.strip()} console=ttyS0 myroot=UUID=x\n",
        )

    def test_run_again_changes_nothing(self) -> None:
        self.enroll()
        calls = self.enroll()
        self.assertFalse([c for c in calls if c[0] == "mkinitcpio"])
        self.assertIn("nothing to change", self.said())

    def test_a_failed_image_build_is_built_again_by_a_rerun(self) -> None:
        os.environ["MKINITCPIO_FAILS"] = "1"
        with self.assertRaises(subprocess.CalledProcessError):
            self.enroll()
        self.assertEqual(self.cmdline.read_text(), OLD_CMDLINE, "put back")
        del os.environ["MKINITCPIO_FAILS"]
        calls = self.enroll()
        self.assertIn(["mkinitcpio", "--allpresets"], calls)
        self.assertEqual(self.cmdline.read_text(), CMDLINE)

    def test_no_unified_kernel_image_is_left_alone(self) -> None:
        self.cmdline.unlink()
        calls = self.enroll()
        self.assertFalse([c for c in calls if c[0] == "mkinitcpio"])
        self.assertFalse(self.cmdline.exists())


class Policy(unittest.TestCase):
    def test_is_a_policy_pcr_of_7_and_15_in_sha256(self) -> None:
        # TPM2_PolicyPCR from an empty policy, by the TPM 2.0 spec (part 3,
        # 23.7), worked out here independently of tpm.policy.
        import hashlib

        pcrs = bytes.fromhex("00000001000b03808000")
        values = hashlib.sha256(bytes.fromhex(PCR7) + bytes(32)).digest()
        expected = hashlib.sha256(
            bytes(32) + bytes.fromhex("0000017f") + pcrs + values
        ).hexdigest()
        self.assertEqual(tpm.policy(PCR7), expected)


if __name__ == "__main__":
    unittest.main()
