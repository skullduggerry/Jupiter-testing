"""What phase 4's TPM step (jupiter/tpm.py) never does: bind the disk where
Secure Boot does not hold, bind it to anything but PCR 7 and PCR 15 zero, or
let the recovery key through its own hands. The machine and its stand-ins
are installer's test_tpm's.
"""

import os
import unittest
from pathlib import Path

from jupiter import tpm

from installer.test_tpm import CRYPTTAB, RECOVERY_KEY, Machine


class NoBindingWithout(Machine):
    """Anyone who can start their own code with Secure Boot off, or start a
    kernel image with another command line, could have the TPM unseal the
    key: nothing is enrolled then, and the passphrase stays."""

    def assert_nothing_enrolled(self) -> list[list[str]]:
        calls = self.enroll()
        self.assertFalse([c for c in calls if c[0] == "systemd-cryptenroll"])
        self.assertFalse([c for c in calls if c[0] == "mkinitcpio"])
        self.assertEqual(self.read(self.crypttab), CRYPTTAB)
        self.assertIn("the passphrase unlocks the disk", self.said())
        return calls

    def test_secure_boot_off(self) -> None:
        self.secure_boot(setup=False, on=False)
        self.assert_nothing_enrolled()
        said = self.said()
        self.assertIn("Secure Boot is off: turn it on", said)
        self.assertIn("the passphrase unlocks the disk", said)

    def test_setup_mode_enrols_the_keys_first(self) -> None:
        self.secure_boot(setup=True, on=False)
        calls = self.assert_nothing_enrolled()
        self.assertIn(["sbctl", "enroll-keys", "--microsoft"], calls)
        self.assertIn("Reboot, turn Secure Boot on", self.said())

    def test_keys_that_cannot_be_enrolled(self) -> None:
        self.secure_boot(setup=True, on=False)
        os.environ["ENROLL_FAILS"] = "1"
        self.assert_nothing_enrolled()
        said = self.said()
        self.assertIn("sbctl could not enrol the keys", said)

    def test_no_keys_of_its_own(self) -> None:
        (self.world / "keys").rmdir()
        self.assert_nothing_enrolled()
        said = self.said()
        self.assertIn("sudo sbctl create-keys", said)

    def test_no_secure_boot_in_the_firmware(self) -> None:
        for path in self.efivars.iterdir():
            path.unlink()
        self.assert_nothing_enrolled()
        said = self.said()
        self.assertIn("no Secure Boot", said)

    def test_not_booted_from_the_signed_image(self) -> None:
        self.stub.unlink()
        self.assert_nothing_enrolled()
        said = self.said()
        self.assertIn("did not start from the signed kernel image", said)

    def test_no_tpm(self) -> None:
        (self.tpm / "tpm_version_major").write_text("1\n")
        self.assert_nothing_enrolled()
        said = self.said()
        self.assertIn("No TPM 2.0", said)

    def test_an_unencrypted_system_is_left_as_it_is(self) -> None:
        stand_in = self.world / "bin/findmnt"
        stand_in.write_text("#!/bin/sh\necho /dev/vda2[/@]\n")
        self.assertEqual(self.enroll(), [])
        self.assertEqual(self.said(), "")


class Binding(Machine):
    def test_to_pcr_7_and_15_zero_only(self) -> None:
        calls = self.enroll()
        [enrolled] = [
            c
            for c in calls
            if c[0] == "systemd-cryptenroll" and "--recovery-key" not in c
        ]
        pcrs = [arg for arg in enrolled if arg.startswith("--tpm2-pcrs=")]
        self.assertEqual(pcrs, ["--tpm2-pcrs=7+15:sha256=" + "0" * 64])
        self.assertFalse(
            [a for a in enrolled if "pin" in a or "public-key" in a]
        )

    def test_the_recovery_key_never_passes_through_it(self) -> None:
        self.enroll()
        self.assertNotIn(RECOVERY_KEY, self.said())
        for path in Path(self.world).rglob("*"):
            if path.is_file():
                with self.subTest(path=path):
                    self.assertNotIn(RECOVERY_KEY, self.read(path))

    def test_a_header_backup_is_the_users_alone(self) -> None:
        backup = self.world / "header.img"
        self.answers = [str(backup)]
        self.enroll()
        self.assertEqual(backup.stat().st_mode & 0o777, 0o400)
        self.assertIn(tpm.BACKUP_HELP, self.said())


if __name__ == "__main__":
    unittest.main()
