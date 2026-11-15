"""Jupiter installed in a VM by phases 1 and 2, end to end.

Skipped, naming why, where QEMU, swtpm, KVM, OVMF or the Arch ISO are
missing (vm/rig.py says how to get each). Not part of ./check.sh: an install
takes minutes. Run it with scripts/vm.sh, or one test:

    python3 -m unittest vm.test_install -k Before

Each install is kept in ~/.cache/jupiter-testing/vm and reused until the
installer changes; every test boots a copy of it, kept after the test in
~/.cache/jupiter-testing/vm/<Class>.<test> with a serial log per boot.
"""

from __future__ import annotations

import re
import shutil
import unittest

from harness import INSTALLER

from . import install, rig

REASON = rig.missing()
# Phase 1 as it was before encryption, to compare an install that declines it
# with.
BEFORE = "78a179a"


@unittest.skipIf(REASON, f"no VM: {REASON}")
class Booting(unittest.TestCase):
    """A copy of an installed machine, in a folder that stays if the test
    fails."""

    def machine(
        self,
        name: str,
        answers: install.Answers,
        disks: list[rig.Disk],
        revision: str | None = None,
    ) -> rig.Machine:
        base = install.installed(name, answers, disks, revision=revision)
        # The test's own folder for each machine it uses, kept after it to
        # read its serial logs from, and replaced by its next run.
        test = self.id().removeprefix("vm.test_install.")
        folder = install.VMS / f"{test}-{name}"
        rig.Machine(folder, disks).remove()
        machine = base.clone(folder)
        self.addCleanup(machine.kill)
        return machine


class Before(Booting):
    """Phase 1 as it was before encryption (BEFORE): the rig itself, and
    the boot time to compare with."""

    def test_boots_to_a_login_with_nothing_typed(self) -> None:
        machine = self.machine(
            "before", install.Answers(), [rig.Disk("system", 20)], BEFORE
        )
        machine.boot()
        machine.login("root", install.ROOT_PASSWORD, timeout=180)
        self.assertEqual(machine.sh("findmnt -no FSTYPE /").strip(), "btrfs")
        self.assertEqual(
            machine.sh("lsblk -dno FSTYPE /dev/vda2").strip(), "btrfs"
        )
        machine.sh(
            "systemctl is-system-running --wait", check=False, timeout=180
        )
        analyze = machine.sh("systemd-analyze")
        print(f"\n{analyze.strip()}")
        self.assertRegex(analyze, r"Startup finished in")
        failed = machine.sh("systemctl --failed --no-legend --plain")
        self.assertEqual(failed.strip(), "", "no unit fails")
        self.assertTrue(
            re.search(r"\bquiet\b", machine.sh("cat /proc/cmdline"))
        )
        machine.power_off()


ENCRYPTED = install.Answers(encrypt=True, data={"/dev/vdb": "/data"})
DISKS = [
    rig.Disk("system", 20),
    rig.Disk("data", 8),
    rig.Disk("other", 2, foreign=True),
]


class Encrypted(Booting):
    """The system and a data disk on LUKS2, with no TPM enrolled yet: the
    passphrase at boot, the data disk by its key file. A third disk holds
    another system and is left alone."""

    def boot(self, machine: rig.Machine) -> None:
        machine.boot()
        machine.type_passphrase(install.PASSPHRASE)
        machine.login("root", install.ROOT_PASSWORD, timeout=180)
        machine.sh(
            "systemctl is-system-running --wait", check=False, timeout=180
        )

    def test_opens_with_the_passphrase_and_mounts_the_data_disk(self) -> None:
        machine = self.machine("encrypted", ENCRYPTED, DISKS)
        self.boot(machine)
        self.assertEqual(
            machine.sh("lsblk -dno FSTYPE /dev/vda2 /dev/vdb1").split(),
            ["crypto_LUKS", "crypto_LUKS"],
        )
        self.assertEqual(
            machine.sh("findmnt -no SOURCE,FSTYPE /data").split(),
            ["/dev/mapper/data", "btrfs"],
        )
        self.assertEqual(machine.sh("stat -c %U /data").strip(), install.USER)
        self.assertIn("/dev/mapper/root", machine.sh("findmnt -no SOURCE /"))
        failed = machine.sh("systemctl --failed --no-legend --plain")
        self.assertEqual(failed.strip(), "", "no unit fails")
        print(f"\n{machine.sh('systemd-analyze').strip()}")
        machine.power_off()

    def test_the_other_disk_stays_as_it_was(self) -> None:
        machine = self.machine("encrypted", ENCRYPTED, DISKS)
        self.boot(machine)
        machine.power_off()
        other = machine.disk("other")
        self.assertEqual(
            rig.digest(other), other.with_suffix(".sha256").read_text()
        )

    def test_boots_without_the_data_disk(self) -> None:
        machine = self.machine("encrypted", ENCRYPTED, DISKS)
        machine.disks[1].attached = False
        self.boot(machine)
        state = machine.sh("systemctl is-system-running", check=False)
        self.assertEqual(state.strip(), "running")
        self.assertEqual(machine.sh("findmnt /data", check=False).strip(), "")
        print(f"\n{machine.sh('systemd-analyze').strip()}")
        machine.power_off()

    def test_trim_reaches_the_disk(self) -> None:
        machine = self.machine("encrypted", ENCRYPTED, DISKS)
        self.boot(machine)
        self.assertIn("allow_discards", machine.sh("dmsetup table root"))
        self.assertIn("allow_discards", machine.sh("dmsetup table data"))
        for mount in ("/", "/data"):
            machine.sh(
                f"head -c 512M /dev/urandom > {mount}/fill && sync",
                timeout=300,
            )
        system, data = machine.disk("system"), machine.disk("data")
        full = [system.stat().st_blocks, data.stat().st_blocks]
        machine.sh("rm /fill /data/fill && sync && fstrim -av", timeout=300)
        machine.power_off()
        freed = [
            (before - path.stat().st_blocks) * 512
            for before, path in zip(full, (system, data), strict=True)
        ]
        for amount in freed:
            self.assertGreater(amount, 400 * 2**20, freed)


# systemd-cryptenroll's recovery key: eight groups of eight modhex letters.
RECOVERY_KEY = re.compile(
    r"\b[cbdefghijklnrtuv]{8}(?:-[cbdefghijklnrtuv]{8}){7}\b"
)
STEP = (
    f"cd /home/{install.USER}/Jupiter-installer && "
    "python3 -c 'from jupiter import tpm; tpm.main()'"
)


class Enrolling(Booting):
    """Booting an encrypted install and running phase 4's TPM step on it."""

    def booted(self, machine: rig.Machine, passphrase: str | None) -> None:
        """Boot, typing the passphrase if one is given, and log in as root."""
        machine.boot()
        if passphrase is not None:
            machine.type_passphrase(passphrase)
        machine.login("root", install.ROOT_PASSWORD, timeout=240)

    def step(self, machine: rig.Machine, backup: str = "") -> str:
        """The TPM step as phase 4 runs it: as the user, through sudo (a root
        shell would hide what the user cannot read), with the installer as it
        is now; returns what it said."""
        with rig.mirror() as server:
            install.update(machine, server)
        machine.send(
            f'su --pty - {install.USER} -c "{STEP}"; echo :step:$?:\n'
        )
        said = ""
        while True:
            found = machine.expect(
                r"passphrase for disk [^\n]*?: ?|\[sudo\] password for \w+: ?|"
                r"Write a header backup to [^\n]*?: ?|:step:(\d+):",
                600,
            )
            said += machine.before + found.group(0)
            if found.group(1) is not None:
                self.assertEqual(found.group(1), "0", said[-3000:])
                return said
            if "[sudo]" in found.group(0):
                machine.answer_secret(install.USER_PASSWORD)
            elif "passphrase" in found.group(0):
                machine.answer_secret(install.PASSPHRASE)
            else:
                machine.send(f"{backup}\n")

    def enrolled(self) -> tuple[rig.Machine, str]:
        """The encrypted install with the TPM step run once; its output."""
        machine = self.machine("encrypted", ENCRYPTED, DISKS)
        self.booted(machine, install.PASSPHRASE)
        said = self.step(machine)
        return machine, said

    def reboot(self, machine: rig.Machine) -> None:
        machine.power_off()
        self.booted(machine, None)


class Tpm(Enrolling):
    """Phase 4's TPM step on the encrypted install, Secure Boot on with the
    keys phase 1 enrolled: the disk then opens with nothing typed, and with
    the passphrase or recovery key wherever the TPM will not."""

    def test_boots_with_nothing_typed(self) -> None:  # (a)
        machine, said = self.enrolled()
        self.assertRegex(said, RECOVERY_KEY, "a recovery key, shown once")
        crypttab = machine.sh("cat /etc/crypttab")
        self.assertRegex(
            crypttab, r"tpm2-measure-pcr=yes,fixate-volume-key=[0-9a-f]{64}"
        )
        self.reboot(machine)
        self.assertNotIn("assphrase", machine.console())
        self.assertEqual(
            machine.sh("findmnt -no SOURCE /data").strip(), "/dev/mapper/data"
        )
        tokens = machine.sh("systemd-cryptenroll /dev/vda2")
        self.assertRegex(tokens, r"tpm2")
        self.assertRegex(tokens, r"recovery")
        machine.sh(
            "systemctl is-system-running --wait", check=False, timeout=180
        )
        print(f"\n{machine.sh('systemd-analyze').strip()}")
        print(machine.sh("systemd-analyze pcrs 7 15").strip())
        machine.power_off()

    def test_run_again_changes_nothing(self) -> None:  # (f)
        machine, _ = self.enrolled()
        self.reboot(machine)
        header = machine.sh(
            "cryptsetup luksDump --dump-json-metadata /dev/vda2"
        )
        crypttab = machine.sh("cat /etc/crypttab")
        image = machine.sh("sha256sum /boot/EFI/Linux/arch-linux.efi")
        said = self.step(machine)
        self.assertIn("nothing to change", said)
        self.assertNotIn("passphrase", said)
        self.assertEqual(
            machine.sh("cryptsetup luksDump --dump-json-metadata /dev/vda2"),
            header,
        )
        self.assertEqual(machine.sh("cat /etc/crypttab"), crypttab)
        self.assertEqual(
            machine.sh("sha256sum /boot/EFI/Linux/arch-linux.efi"), image
        )
        machine.power_off()

    def test_a_fresh_tpm_asks_and_the_recovery_key_opens(self) -> None:  # (b)
        machine, said = self.enrolled()
        found = RECOVERY_KEY.search(said)
        assert found
        machine.power_off()
        shutil.rmtree(machine.folder / "tpm")
        self.booted(machine, found.group(0))
        self.assertIn("/dev/mapper/root", machine.sh("findmnt -no SOURCE /"))
        machine.power_off()

    def test_secure_boot_off_asks_for_the_passphrase(self) -> None:  # (b)
        machine, _ = self.enrolled()
        machine.power_off()
        machine.secure_boot_firmware = False
        self.booted(machine, install.PASSPHRASE)
        machine.power_off()

    def test_a_changed_image_does_not_boot(self) -> None:  # (c)
        for change in (
            # A byte of the signed image changed.
            "printf X | dd of=/boot/EFI/Linux/arch-linux.efi bs=1 "
            "seek=$(( $(stat -c %s /boot/EFI/Linux/arch-linux.efi) / 2 )) "
            "conv=notrunc",
            # The image built again with sbctl's hook left out: unsigned.
            # The image with its signature taken off: the PE security
            # directory zeroed and the certificates cut away.
            'python3 -c \'import struct,sys;p=sys.argv[1];b=bytearray(open(p,"rb").read());'
            'o=struct.unpack_from("<I",b,60)[0];m=struct.unpack_from("<H",b,o+24)[0];'
            'd=o+24+(112 if m==0x20b else 96)+4*8;a,n=struct.unpack_from("<II",b,d);'
            'struct.pack_into("<II",b,d,0,0);open(p,"wb").write(b[:a] if a else b)\' '
            "/boot/EFI/Linux/arch-linux.efi && "
            "! sbctl verify /boot/EFI/Linux/arch-linux.efi 2>&1 | grep -q 'is signed'",
        ):
            with self.subTest(change=change.split()[0]):
                machine, _ = self.enrolled()
                machine.sh(change, timeout=300)
                machine.power_off()
                machine.boot()
                with self.assertRaises(TimeoutError):
                    machine.expect(r"login: $|[Pp]assphrase", 120)
                self.assertRegex(
                    machine.console(),
                    r"(?i)security violation|access denied|not signed|failed",
                )
                machine.kill()

    def test_a_volume_put_in_its_place_gets_nothing(self) -> None:  # (d)
        machine, _ = self.enrolled()
        # From the running system, after the root opened, the TPM gives
        # nothing out: PCR 15 is no longer zero.
        refused = machine.sh(
            "/usr/lib/systemd/systemd-cryptsetup attach probe /dev/vda2 - "
            "tpm2-device=auto,headless=yes,token-only",
            check=False,
        )
        self.assertNotIn("probe", machine.sh("ls /dev/mapper"), refused)
        uuid = machine.sh("cryptsetup luksUUID /dev/vda2").strip()
        machine.power_off()
        # An attacker's volume, same UUID, a passphrase they know, a root of
        # theirs on it, written from the ISO: unsigned, so it starts with
        # Secure Boot off, as anyone with the machine in hand could.
        machine.secure_boot_firmware = False
        machine.boot(live=True)
        machine.login("root")
        machine.sh(
            f"printf attacker | cryptsetup luksFormat --type=luks2 --batch-mode "
            f"--uuid={uuid} --key-file=- /dev/vda2 && "
            "printf attacker | cryptsetup open --key-file=- /dev/vda2 evil && "
            "mkfs.btrfs -q -f /dev/mapper/evil && mount /dev/mapper/evil /mnt && "
            "btrfs subvolume create /mnt/@ && umount /mnt && cryptsetup close evil",
            timeout=300,
        )
        machine.power_off()
        machine.secure_boot_firmware = True
        machine.boot()
        # Its key is not the one fixed in the signed image: refused at once,
        # never mounted, and the boot stops.
        machine.type_passphrase("attacker")
        machine.expect(r"Failed to start .*Cryptography Setup for root", 120)
        with self.assertRaises(TimeoutError):
            machine.expect(r"login: $", 60)
        console = machine.console()
        # The initramfs gives no shell: root is locked there.
        self.assertNotRegex(console, r"Give root password|# $")
        machine.kill()

    def test_a_kernel_update_is_signed_and_still_unlocks(self) -> None:  # (e)
        machine, _ = self.enrolled()
        self.reboot(machine)
        before = machine.sh("stat -c %Y /boot/EFI/Linux/arch-linux.efi")
        with rig.mirror() as server:
            rig.use_mirror(machine, server)
            machine.sh(
                "pacman -S --noconfirm --noprogressbar linux", timeout=900
            )
        self.assertNotEqual(
            machine.sh("stat -c %Y /boot/EFI/Linux/arch-linux.efi"), before
        )
        verified = machine.sh("sbctl verify")
        self.assertRegex(verified, r"arch-linux\.efi is signed")
        self.assertRegex(verified, r"vmlinuz-linux is not signed")
        self.reboot(machine)
        self.assertNotIn("assphrase", machine.console())
        machine.power_off()


# What an install leaves that phase 1 decides, UUIDs left out.
SETTINGS = (
    "cat /etc/mkinitcpio.conf.d/jupiter.conf /boot/loader/loader.conf; "
    "sed 's/UUID=[0-9A-Fa-f-]*/UUID=x/' /etc/fstab /boot/loader/entries/*.conf; "
    "lsblk -lno NAME,FSTYPE,TYPE /dev/vda; ls /boot /boot/EFI; "
    "grep -v '^#' /etc/crypttab | grep . ; ls /etc/kernel /etc/mkinitcpio.d; "
    "cat /etc/vconsole.conf /etc/locale.conf /etc/hostname; "
    "systemctl list-unit-files --state=enabled,masked --no-legend; "
    "pacman -Qq"
)


class Declined(Booting):
    """Encryption declined: what phase 1 made before it asked (BEFORE)."""

    def settings(self, machine: rig.Machine) -> str:
        machine.boot()
        machine.login("root", install.ROOT_PASSWORD, timeout=240)
        found = machine.sh(SETTINGS, check=False)
        machine.power_off()
        return found

    def test_is_what_phase_1_made_before(self) -> None:  # (g)
        disks = [rig.Disk("system", 20)]
        declined = self.machine(
            "declined", install.Answers(encrypt=False), disks
        )
        before = self.machine("before", install.Answers(), disks, BEFORE)
        self.maxDiff = None
        self.assertEqual(self.settings(declined), self.settings(before))


class OutsideSetupMode(Enrolling):
    """Installed on firmware whose keys could not be enrolled: it installs
    all the same, the TPM step says what is left, and once the firmware is
    in Setup Mode, enrols the keys and then binds the disk."""

    def test_finishes_and_the_step_picks_it_up(self) -> None:  # (j)
        answers = install.Answers(
            encrypt=True, data={"/dev/vdb": "/data"}, secure_boot=False
        )
        machine = self.machine("outside", answers, DISKS)
        phases = (machine.folder / "phases.log").read_text()
        self.assertIn("This firmware has no Secure Boot", phases)
        self.booted(machine, install.PASSPHRASE)
        said = self.step(machine)
        self.assertIn("no Secure Boot", said)
        self.assertIn("the passphrase unlocks the disk", said)
        # The keys erased, as the firmware's menu does: Setup Mode.
        machine.power_off()
        machine.secure_boot_firmware = True
        self.booted(machine, install.PASSPHRASE)
        said = self.step(machine)
        self.assertIn("Enrolled the Secure Boot keys", said)
        self.assertIn("Reboot, turn Secure Boot on", said)
        machine.power_off()
        self.booted(machine, install.PASSPHRASE)
        said = self.step(machine)
        self.assertRegex(said, RECOVERY_KEY)
        self.reboot(machine)
        self.assertNotIn("assphrase", machine.console())
        machine.power_off()


PROCEDURE = INSTALLER / "docs/encrypt-an-existing-install.md"


class Converted(Enrolling):
    """docs/encrypt-an-existing-install.md, every bash block of it as
    written, on a system phase 1 installed before it encrypted (BEFORE):
    then phase 4's TPM step, and a boot with nothing typed."""

    def blocks(self) -> list[str]:
        text = PROCEDURE.read_text()
        return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)

    def run_block(self, machine: rig.Machine, block: str) -> None:
        """A block in the live shell, answering cryptsetup's questions."""
        machine.send(f"{{ {block}\n}} 2>&1; echo :block:$?:\n")
        while True:
            found = machine.expect(
                r"(?:Enter|Verify) passphrase[^\n]*?: ?|"
                r"\(Type 'yes' in capital letters\): ?|:block:(\d+):",
                3600,
            )
            if found.group(1) is not None:
                self.assertEqual(
                    found.group(1), "0", f"{block}\n{machine.before[-3000:]}"
                )
                return
            if "capital letters" in found.group(0):
                machine.send("YES\n")
            else:
                machine.answer_secret(install.PASSPHRASE)

    def test_the_procedure_encrypts_it_in_place(self) -> None:
        machine = self.machine(
            "before", install.Answers(), [rig.Disk("system", 20)], BEFORE
        )
        machine.boot()
        machine.login("root", install.ROOT_PASSWORD, timeout=240)
        machine.sh("echo kept > /home/jupiter/kept.txt")
        machine.power_off()
        machine.boot(live=True)
        machine.login("root")
        with rig.mirror() as server:
            rig.use_mirror(machine, server)
            for block in self.blocks():
                if "reboot" in block:
                    machine.sh("umount -R /mnt; cryptsetup close root")
                    machine.power_off()
                    break
                if "arch-chroot /mnt pacman" in block:
                    # The installed system's mirror list names the mirror
                    # its install had, on a port long gone.
                    machine.sh(
                        "cp /etc/pacman.d/mirrorlist /mnt/etc/pacman.d/"
                    )
                self.run_block(
                    machine,
                    block.replace("DISK=/dev/nvme0n1", "DISK=/dev/vda"),
                )
        self.assertIn("bootstrap.sh 4", self.blocks()[-1])
        self.booted(machine, install.PASSPHRASE)
        self.assertEqual(
            machine.sh("cat /home/jupiter/kept.txt").strip(), "kept"
        )
        self.assertEqual(
            machine.sh("lsblk -dno FSTYPE /dev/vda2").strip(), "crypto_LUKS"
        )
        said = self.step(machine)
        self.assertRegex(said, RECOVERY_KEY)
        self.reboot(machine)
        self.assertNotIn("assphrase", machine.console())
        machine.power_off()


if __name__ == "__main__":
    unittest.main()
