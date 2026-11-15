"""Installing Jupiter in a VM with phases 1 and 2, answered on the console.

`installed(name, answers)` installs once and keeps the powered-off machine in
~/.cache/jupiter-testing/vm/<name>, keyed by the installer's working tree:
a test that needs that system takes a clone of it (`Machine.clone`), so
each test starts from the same disk, firmware variables and TPM, and the
install runs again only when the installer changed.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field

from harness import INSTALLER

from . import rig

ROOT_PASSWORD = "root-in-the-vm"
USER = "jupiter"
USER_PASSWORD = "user-in-the-vm"
PASSPHRASE = "disk passphrase in the vm"
HOSTNAME = "jupiter-vm"
VMS = rig.CACHE / "vm"
# What phases 1 and 2 never run: a change to these needs no new install, and
# a test of them fetches the installer as it is into the VM (`update()`).
INSTALLED_ONLY = {
    "README.md",
    "bootstrap.sh",
    "check.sh",
    "pyproject.toml",
    "jupiter/phase3.py",
    "jupiter/phase4.py",
    "jupiter/tpm.py",
    "jupiter/keyring.py",
    "packages/pacman.txt",
    "packages/aur.txt",
}


@dataclass
class Answers:
    """What phase 1 is told. disk: the system disk's device."""

    disk: str = "/dev/vda"
    # None: phase 1 does not ask (before encryption).
    encrypt: bool | None = None
    # Each further disk phase 1 offers, by device: its mount point, or ""
    # to leave it alone.
    data: dict[str, str] = field(default_factory=dict)
    keymap: str = "us"
    # The firmware phase 1 runs on: OVMF with Secure Boot (in Setup Mode), or
    # without, as a machine whose keys cannot be enrolled during the install.
    secure_boot: bool = True

    def key(self) -> str:
        return repr(self)


def dialogue(answers: Answers) -> list[tuple[str, str]]:
    """Phase 1's questions in order, and the answers."""
    # The keymap first, loaded before any password; the disk with a default
    # only where one disk would take the system.
    lines: list[tuple[str, str]] = [
        (r"Keymap \[us\]: $", answers.keymap),
        (r"Disk(?: \[[^]]*\])?: $", answers.disk),
    ]
    if answers.encrypt is not None:
        lines.append(
            (
                rf"Encrypt {answers.disk}\? \[Y/n\] $",
                "" if answers.encrypt else "n",
            )
        )
    if answers.encrypt:
        lines += [
            (r"Passphrase for the disk: $", PASSPHRASE),
            (r"Repeat it: $", PASSPHRASE),
        ]
        for device, mount in answers.data.items():
            question = rf"Erase and encrypt {device} .*for data\? \[y/N\] $"
            if not mount:
                lines.append((question, "n"))
                continue
            lines += [
                (question, "y"),
                (r"Mount it at \[[^]]*\]: $", mount),
                (rf"Erase everything on {device}\? \[y/N\] $", "y"),
            ]
    lines += [
        (r"Hostname \[archlinux\]: $", HOSTNAME),
        (r"Username: $", USER),
        (rf"Password for {USER}: $", USER_PASSWORD),
        (r"Repeat it: $", USER_PASSWORD),
        (r"Password for root: $", ROOT_PASSWORD),
        (r"Repeat it: $", ROOT_PASSWORD),
        (r"Time zone \[UTC\]: $", "Europe/Berlin"),
        (r"Locale \[en_US.UTF-8\]: $", "en_US.UTF-8"),
        (rf"Erase everything on {answers.disk}\? \[y/N\] $", "y"),
    ]
    return lines


def fingerprint(
    answers: Answers, disks: list[rig.Disk], revision: str | None = None
) -> str:
    """What an install depends on: the installer's files (or its revision),
    the answers and the disks."""
    digest = hashlib.sha256(answers.key().encode())
    digest.update(repr(disks).encode())
    if revision:
        commit = subprocess.run(
            ["git", "-C", INSTALLER, "rev-parse", f"{revision}^{{commit}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        digest.update(commit.encode())
        return digest.hexdigest()[:16]
    for path in sorted(INSTALLER.rglob("*")):
        relative = path.relative_to(INSTALLER)
        if (
            path.is_file()
            and not relative.parts[0].startswith(".")
            and "__pycache__" not in relative.parts
            and str(relative) not in INSTALLED_ONLY
            and relative.parts[0] != "docs"
        ):
            digest.update(str(relative).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def serial_console(machine: rig.Machine) -> None:
    """On the ISO after phase 1: the installed system's kernel writes to
    the serial console too, where the rig reads it. A loader entry's
    options, or the UKI's command line rebuilt and signed again.

    The console's terminal type and size are given too: systemd asks a
    serial console for them otherwise, and waits a third of a second for an
    answer that never comes, several times a boot, where a laptop's screen
    answers at once. Boot times measured in the VM would be a second or two
    longer than any machine's."""
    console = (
        "console=tty0 console=ttyS0,115200 systemd.tty.term.console=vt220 "
        "systemd.tty.rows.console=24 systemd.tty.columns.console=80 "
        "systemd.tty.rows.ttyS0=24 systemd.tty.columns.ttyS0=80"
    )
    machine.sh(
        "if [ -f /mnt/etc/kernel/cmdline ]; then "
        f"sed -i 's/$/ {console}/' "
        "/mnt/etc/kernel/cmdline && arch-chroot /mnt mkinitcpio -P; "
        f"else sed -i '/^options/s/$/ {console}/' "
        "/mnt/boot/loader/entries/arch.conf; fi",
        timeout=600,
    )


def install(
    machine: rig.Machine,
    answers: Answers,
    phases: str = "1 2",
    revision: str | None = None,
) -> str:
    """Boot the ISO, run the phases, answer phase 1 and power off. Returns
    what the phases printed."""
    with rig.mirror(revision) as server:
        machine.boot(live=True)
        machine.login("root")
        rig.prepare_live(machine, server)
        # Through a pipe: pacman draws no progress bars, which the serial
        # console's 115200 baud would slow its downloads to a crawl with.
        machine.send(
            "cd /root/Jupiter-installer && "
            f"python3 -m jupiter {phases} 2>&1 | tee /root/phases.log; "
            "echo :phases:${PIPESTATUS[0]}:\n"
        )
        machine.answer(dialogue(answers), timeout=300)
        done = machine.expect(r":phases:(\d+):", timeout=3600)
        # All of it, the notices before the first question too.
        said = machine.console()
        if done.group(1) != "0":
            raise AssertionError(f"the phases failed:\n{said[-3000:]}")
        serial_console(machine)
        machine.sh("umount -R /mnt", check=False)
        machine.power_off()
        return said


def update(machine: rig.Machine, server: rig.Mirror) -> None:
    """On the installed system, logged in as root: the user's copy of the
    installer replaced by the one on the host, as it is now."""
    home = f"/home/{USER}"
    machine.sh(
        f"rm -rf {home}/Jupiter-installer && "
        f"curl -fsS {server.url}/installer.tar | tar -x -C {home} && "
        f"chown -R {USER}: {home}/Jupiter-installer"
    )


def installed(
    name: str,
    answers: Answers,
    disks: list[rig.Disk],
    tpm: bool = True,
    revision: str | None = None,
) -> rig.Machine:
    """A machine with Jupiter installed by phases 1 and 2 (of the installer
    as it is, or at a git revision), powered off, installed again only when
    the installer or the answers changed."""
    key = fingerprint(answers, disks, revision)
    folder = VMS / f"{name}-{key}"
    firmware = answers.secure_boot
    if (folder / "installed").exists():
        return rig.Machine(
            folder, disks, tpm=tpm, secure_boot_firmware=firmware
        )
    for old in VMS.glob(f"{name}-*"):
        shutil.rmtree(old)
    machine = rig.Machine(
        folder, disks, tpm=tpm, secure_boot_firmware=firmware
    )
    output = install(machine, answers, revision=revision)
    (folder / "phases.log").write_text(output)
    (folder / "installed").write_text(key)
    return machine
