"""Phase 4's TPM step on NixOS (jupiter/nixos/tpm.py) against stand-ins: binding the
root volume to the TPM, recording the crypttab options it needs in the
machine's settings and rebuilding, the recovery key, and what it says where
something is missing.

The machine is a folder: its TPM (tpm_version_major, PCR 7), its EFI
variables (Secure Boot's state, the stub's mark), hosts/box/settings.json
and the measurement log. Each command (sudo, findmnt, lsblk, cryptsetup,
systemd-cryptenroll, sbctl, nixos-rebuild, chown, cat) is a stand-in that
records its argv and answers from the LUKS header kept in `header.json`, as
the Arch installer's test_tpm does; what is the same there (the policy, the
header backup) is tested there.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from jupiter import secureboot
from jupiter import tpm as core
from jupiter.nixos import common, system, tpm

PCR7 = "a2" * 32
LUKS_UUID = "11111111-2222-3333-4444-555555555555"
VOLUME_KEY_ID = (
    "b7c790dc40a5191f93aa2a089926c9378f54441a6d08145890e7598aaec280a6"
)
SETTINGS = {"hostname": "box", "tpm": False, "volumeKey": None}
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
elif name == "sbctl":
    print(json.dumps({{"installed": True}}))
elif name == "cryptsetup" and args[0] == "luksDump":
    print(json.dumps(header))
elif name == "cryptsetup" and args[0] == "luksUUID":
    print("{LUKS_UUID}")
elif name == "systemd-cryptenroll":
    tokens = header.setdefault("tokens", {{}})
    if "--recovery-key" in args:
        tokens[str(len(tokens))] = {{"type": "systemd-recovery"}}
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
    sys.stdout.write(open(args[-1]).read())
elif name == "nixos-rebuild":
    sys.exit(int(os.environ.get("REBUILD_FAILS", "0")))
"""
COMMANDS = [
    "sudo",
    "findmnt",
    "lsblk",
    "sbctl",
    "cryptsetup",
    "systemd-cryptenroll",
    "nixos-rebuild",
    "cat",
]


class Machine(unittest.TestCase):
    """An encrypted system booted from a signed image, Secure Boot on."""

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
        self.tpm = tmp / "tpm0"
        (self.tpm / "pcr-sha256").mkdir(parents=True)
        (self.tpm / "tpm_version_major").write_text("2\n")
        (self.tpm / "pcr-sha256/7").write_text(PCR7.upper() + "\n")
        self.efivars = tmp / "efivars"
        self.efivars.mkdir()
        for flag, on in (("SetupMode", False), ("SecureBoot", True)):
            (self.efivars / f"{flag}-{secureboot.GLOBAL}").write_bytes(
                b"\x06\x00\x00\x00" + bytes([on])
            )
        self.stub = self.efivars / f"StubInfo-{core.SYSTEMD_VENDOR}"
        self.stub.write_bytes(b"\x06\x00\x00\x00lanzastub")
        self.measured = tmp / "tpm2-measure.log"
        self.measured.write_text(
            "\x1e"
            + json.dumps(
                {
                    "pcr": 15,
                    "digests": [
                        {"hashAlg": "sha256", "digest": VOLUME_KEY_ID}
                    ],
                    "content": {"string": f"cryptsetup:root:{LUKS_UUID}"},
                }
            )
            + "\n"
        )
        hosts = tmp / "repo/hosts"
        common.write_settings(hosts / "box", SETTINGS)
        self.settings_file = hosts / "box/settings.json"
        for module, name, value in (
            (core, "TPM", self.tpm),
            (core, "STUB_INFO", self.stub),
            (core, "MEASURE_LOG", self.measured),
            (tpm, "HOSTS", hosts),
            (common, "HOSTS", hosts),
            (system, "INSTALLER_DIR", tmp / "repo"),
            (secureboot, "EFIVARS", self.efivars),
        ):
            self.enterContext(mock.patch.object(module, name, value))
        self.enterContext(mock.patch.object(tpm, "host", return_value="box"))
        environment = {
            "PATH": f"{stand_ins}:/usr/bin",
            "WORLD": str(tmp),
            "POLICY": core.policy(PCR7),
        }
        self.enterContext(mock.patch.dict(os.environ, environment))
        self.printed = self.enterContext(mock.patch("builtins.print"))

    def enroll(self) -> list[list[str]]:
        (self.world / "calls").write_text("")
        with mock.patch("builtins.input", return_value=""):
            tpm.main()
        return [
            json.loads(line)
            for line in (self.world / "calls").read_text().splitlines()
        ]

    def settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = json.loads(self.settings_file.read_text())
        return settings

    def said(self) -> str:
        return "\n".join(
            str(arg)
            for call in self.printed.call_args_list
            for arg in call.args
        )


REBUILD = ["nixos-rebuild", "switch", "--sudo", "--flake"]


class Binding(Machine):
    def test_records_the_slot_and_the_key_and_rebuilds(self) -> None:
        calls = self.enroll()
        self.assertIn(
            [
                "systemd-cryptenroll",
                "--wipe-slot=tpm2",
                "--tpm2-device=auto",
                "--tpm2-pcrs=7+15:sha256=" + "0" * 64,
                "--tpm2-pcrlock=",
                "--tpm2-public-key=",
                "/dev/vda2",
            ],
            calls,
        )
        self.assertEqual(
            self.settings(),
            SETTINGS | {"tpm": True, "volumeKey": VOLUME_KEY_ID},
        )
        self.assertIn([*REBUILD, f"{self.world}/repo#box"], calls)

    def test_run_again_changes_nothing(self) -> None:
        self.enroll()
        calls = self.enroll()
        self.assertFalse([c for c in calls if c[0] == "nixos-rebuild"])
        self.assertFalse([c for c in calls if c[0] == "systemd-cryptenroll"])
        self.assertIn("nothing to change", self.said())

    def test_a_failed_rebuild_is_rebuilt_by_a_rerun(self) -> None:
        os.environ["REBUILD_FAILS"] = "1"
        with self.assertRaises(subprocess.CalledProcessError):
            self.enroll()
        self.assertEqual(self.settings(), SETTINGS, "put back")
        del os.environ["REBUILD_FAILS"]
        calls = self.enroll()
        self.assertIn([*REBUILD, f"{self.world}/repo#box"], calls)
        self.assertTrue(self.settings()["tpm"])

    def test_waits_a_boot_for_the_volume_key_measured(self) -> None:
        self.measured.unlink()
        self.enroll()
        self.assertEqual(
            self.settings(), SETTINGS | {"tpm": True, "volumeKey": None}
        )
        self.assertIn("Reboot and run bootstrap.sh 4 again", self.said())
        self.measured.write_text("")
        self.assertIsNone(core.volume_key_id("root", LUKS_UUID))


class Missing(Machine):
    def test_a_boot_not_from_a_signed_image(self) -> None:
        self.stub.unlink()
        calls = self.enroll()
        self.assertFalse([c for c in calls if c[0] == "systemd-cryptenroll"])
        self.assertIn("kernel image lanzaboote signed", self.said())

    def test_no_tpm(self) -> None:
        (self.tpm / "tpm_version_major").write_text("1\n")
        self.assertEqual(self.enroll()[2:], [])
        self.assertIn("No TPM 2.0 here", self.said())


if __name__ == "__main__":
    unittest.main()
