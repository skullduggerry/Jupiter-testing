"""Phases 2 to 4 against stand-in commands, in a throwaway home, and the
drivers phase 1 picks, against stand-in hardware.

sudo, pacman, paru, systemctl, ufw and wallust only record how they were
called, and fail when an argument is $BROKEN, so nothing outside the
temporary folder changes. lsblk lists the file systems in $LSBLK: none,
unless a test names some.
"""

import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jupiter import phase1, phase2, phase3
from jupiter.common import INSTALLER_DIR, packages

RECORD = """#!/bin/sh
echo "${0##*/} $*" >> "$CALLS"
for arg; do [ "$arg" = "$BROKEN" ] && exit 1; done
exit 0
"""
# git clone URL DIR, leaving a PKGBUILD in DIR.
CLONE = RECORD.replace(
    "exit 0\n", 'echo "pkgname=paru" > "$3/PKGBUILD"\nexit 0\n'
)
NO_READER = """#!/bin/sh
echo "No devices available"
exit 1
"""
LSBLK = """#!/bin/sh
printf '%s\\n' $LSBLK
"""
PUSH_URL = "git@example.org:dotfiles.git"
INSTALL = "sudo pacman -S --needed --noconfirm"
USER_UNITS = "hyprpolkitagent gcr-ssh-agent.socket"
MASK = f"sudo systemctl mask {' '.join(phase2.TPM_UNITS)}"
# Where ufw is installed, phase 3 lets KDE Connect in from the local networks.
KDECONNECT = [
    f"sudo ufw allow from {network} to any app KDEConnect"
    for network in phase3.LOCAL_NETWORKS
]
# Phase 2 names the Wi-Fi rules after this machine's time zone, if it has one.
CODE = phase2.country(Path("/"))
REGDOM = (
    [
        f'sudo sed -i s/^#WIRELESS_REGDOM="{CODE}"$/'
        f'WIRELESS_REGDOM="{CODE}"/ /etc/conf.d/wireless-regdom'
    ]
    if CODE
    else []
)


def executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class Phases(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.calls = tmp / "calls"
        self.output = ""
        for name in ("sudo", "pacman", "paru", "systemctl", "ufw", "wallust"):
            executable(self.bin / name, RECORD)
        # Whatever this machine has, the tests' has no fingerprint reader.
        executable(self.bin / "fprintd-list", NO_READER)
        executable(self.bin / "lsblk", LSBLK)
        # Whatever this machine's root is, the tests' is not encrypted: the
        # TPM step (installer's test_tpm) leaves it alone.
        executable(self.bin / "findmnt", "#!/bin/sh\necho '/dev/vda2[/@]'\n")

        origin = tmp / "Jupiter-dotfiles"
        for name in ("hypr/hyprland.lua", "kitty/kitty.conf", ".zshrc"):
            executable(origin / ".config" / name, "")
        executable(origin / ".config/wallust/apply.sh", RECORD)
        executable(origin / "scripts/install-greeter.sh", "")
        executable(origin / "scripts/install-system.sh", "")
        git = ["git", "-C", str(origin)]
        author = ["-c", "user.name=test", "-c", "user.email=test"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, *author, "commit", "-qm", "init"], check=True)
        self.repo = self.home / origin.name

        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("XDG_")
        } | {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "DOTFILES_REPO": str(origin),
            "DOTFILES_PUSH_URL": PUSH_URL,
        }

    def jupiter(self, phase: str, answers: str = "") -> list[str]:
        self.calls.write_text("")
        self.output = subprocess.run(
            [sys.executable, "-m", "jupiter", phase],
            cwd=INSTALLER_DIR,
            env=self.env,
            input=answers,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return [line.rstrip() for line in self.calls.read_text().splitlines()]

    def test_phase2_installs_the_desktop(self) -> None:
        core = " ".join(packages("core.txt"))
        services = (
            "NetworkManager bluetooth power-profiles-daemon reflector.timer"
        )
        self.assertEqual(
            self.jupiter("2"),
            [
                "sudo pacman -Syu --noconfirm",
                f"{INSTALL} {core}",
                f"sudo systemctl enable {services}",
                f"sudo systemctl --global enable {USER_UNITS}",
                MASK,
                *REGDOM,
            ],
        )

    def test_phase2_keeps_the_tpm_units_of_an_encrypted_disk(self) -> None:
        self.env["LSBLK"] = "vfat crypto_LUKS btrfs"
        calls = self.jupiter("2")
        self.assertFalse([call for call in calls if " mask " in call])
        self.assertIn(f"sudo systemctl --global enable {USER_UNITS}", calls)

    def test_phase2_skips_a_broken_package(self) -> None:
        core = packages("core.txt")
        self.assertIn("bluez", core)
        self.env["BROKEN"] = "bluez"
        self.assertEqual(
            self.jupiter("2"),
            [
                "sudo pacman -Syu --noconfirm",
                f"{INSTALL} {' '.join(core)}",
                *(f"{INSTALL} {name}" for name in core),
                "sudo systemctl enable NetworkManager power-profiles-daemon "
                "reflector.timer",
                f"sudo systemctl --global enable {USER_UNITS}",
                MASK,
                *REGDOM,
            ],
        )
        self.assertIn("Failed to install, skipping: bluez", self.output)
        self.assertIn("Failed to install and skipped: bluez", self.output)

    def test_phase3_installs_both_lists(self) -> None:
        aur = packages("aur.txt")
        tools = ["base-devel", "git"] if aur else []
        official = " ".join(tools + packages("pacman.txt"))
        self.assertEqual(
            self.jupiter("3"),
            [
                "sudo pacman -Syu --noconfirm",
                f"{INSTALL} {official}",
                *KDECONNECT,
                *(f"paru --sync --aur --needed {name}" for name in aur),
            ],
        )

    def test_phase3_leaves_the_firewall_without_ufw(self) -> None:
        (self.bin / "ufw").unlink()
        self.env["PATH"] = str(self.bin)
        calls = self.jupiter("3")
        self.assertEqual([call for call in calls if "ufw" in call], [])

    def test_phase3_opens_no_port_for_a_skipped_kdeconnect(self) -> None:
        self.env["BROKEN"] = "kdeconnect"
        calls = self.jupiter("3")
        self.assertEqual([call for call in calls if "ufw" in call], [])

    @unittest.skipUnless(packages("aur.txt"), "needs an AUR package")
    def test_phase3_skips_a_broken_aur_package(self) -> None:
        aur = packages("aur.txt")
        broken = self.env["BROKEN"] = aur[0]
        calls = self.jupiter("3")
        self.assertEqual(
            calls[2:],
            [*KDECONNECT, *(f"paru --sync --aur --needed {n}" for n in aur)],
        )
        self.assertIn(f"Failed to install and skipped: {broken}", self.output)

    def without_paru(self) -> None:
        (self.bin / "paru").unlink()
        executable(self.bin / "git", CLONE)
        executable(self.bin / "makepkg", RECORD)
        self.env["PATH"] = str(self.bin)

    @unittest.skipUnless(packages("aur.txt"), "needs an AUR package")
    def test_phase3_skips_the_aur_without_paru(self) -> None:
        self.without_paru()
        self.env["BROKEN"] = "--syncdeps"
        clone, makepkg = self.jupiter("3", "y\n")[2 + len(KDECONNECT) :]
        self.assertTrue(clone.startswith(f"git clone {phase3.PARU} "))
        self.assertEqual(makepkg, "makepkg --syncdeps --install --noconfirm")
        skipped = " ".join(["paru", *packages("aur.txt")])
        self.assertIn(f"Failed to install and skipped: {skipped}", self.output)

    @unittest.skipUnless(packages("aur.txt"), "needs an AUR package")
    def test_phase3_builds_paru_only_once_its_pkgbuild_is_read(self) -> None:
        self.without_paru()
        [clone] = self.jupiter("3", "n\n")[2 + len(KDECONNECT) :]
        self.assertTrue(clone.startswith(f"git clone {phase3.PARU} "))
        self.assertIn("pkgname=paru", self.output)
        skipped = " ".join(["paru", *packages("aur.txt")])
        self.assertIn(f"Failed to install and skipped: {skipped}", self.output)

    def test_phase4_links_the_dotfiles(self) -> None:
        config = self.home / ".config"
        executable(config / "kitty/kitty.conf", "font_size 11\n")
        executable(self.home / ".zshrc", "# mine\n")
        (config / "waybar").symlink_to(self.repo / ".config/waybar")
        (config / "elsewhere").symlink_to("/nonexistent")

        calls = self.jupiter("4")

        for name in ("hypr", "kitty", "wallust"):
            target = (config / name).readlink()
            self.assertEqual(target, self.repo / ".config" / name)
        zshrc = (self.home / ".zshrc").readlink()
        self.assertEqual(zshrc, self.repo / ".config/.zshrc")
        [backup] = (self.home / ".dotfiles-backup").iterdir()
        kitty = backup / ".config/kitty/kitty.conf"
        self.assertEqual(kitty.read_text(), "font_size 11\n")
        self.assertEqual((backup / ".zshrc").read_text(), "# mine\n")
        self.assertFalse((config / "waybar").is_symlink())
        self.assertTrue((config / "elsewhere").is_symlink())
        push_url = subprocess.check_output(
            ["git", "-C", str(self.repo), "config", "remote.origin.pushurl"],
            text=True,
        )
        self.assertEqual(push_url.strip(), PUSH_URL)

        expected = [
            "systemctl --user mask dunst.service mako.service swaync.service",
            "apply.sh",
            f"sudo {self.repo}/scripts/install-system.sh",
            f"sudo {self.repo}/scripts/install-greeter.sh",
        ]
        manager = Path("/etc/systemd/system/display-manager.service")
        if (
            not manager.is_symlink()
            or manager.readlink().name == "greetd.service"
        ):
            expected.append("sudo systemctl enable greetd")
        user = pwd.getpwuid(os.getuid())
        if Path("/usr/bin/zsh").exists() and user.pw_shell != "/usr/bin/zsh":
            expected.append(f"sudo chsh --shell /usr/bin/zsh {user.pw_name}")
        self.assertEqual(calls, expected)

        self.jupiter("4")
        backups = list((self.home / ".dotfiles-backup").iterdir())
        self.assertEqual(backups, [backup])

    def test_phase4_backs_up_a_config_folder_outside_the_home(self) -> None:
        """XDG_CONFIG_HOME elsewhere: what is in the way there is moved
        under the backup by its whole path, not refused as outside the home."""
        config = self.home.parent / "elsewhere/config"
        self.env["XDG_CONFIG_HOME"] = str(config)
        executable(config / "kitty/kitty.conf", "font_size 11\n")

        self.jupiter("4")

        self.assertEqual(
            (config / "kitty").readlink(), self.repo / ".config/kitty"
        )
        [backup] = (self.home / ".dotfiles-backup").iterdir()
        kept = backup / config.relative_to(config.anchor) / "kitty/kitty.conf"
        self.assertEqual(kept.read_text(), "font_size 11\n")
        self.assertFalse((self.home / ".config").exists())

    def test_phase4_sets_up_a_clone_it_cannot_update(self) -> None:
        """Offline, or with commits the origin lacks: the links, the system
        files and the login screen do not wait for a pull."""
        self.jupiter("4")
        git = ["git", "-C", str(self.repo)]
        subprocess.run(
            [*git, "remote", "set-url", "origin", "/gone"], check=True
        )
        (self.home / ".config/kitty").unlink()

        calls = self.jupiter("4")

        self.assertIn(f"Could not update {self.repo}", self.output)
        self.assertEqual(
            (self.home / ".config/kitty").readlink(),
            self.repo / ".config/kitty",
        )
        self.assertIn(f"sudo {self.repo}/scripts/install-greeter.sh", calls)

    def test_a_failing_command_is_named(self) -> None:
        self.env["BROKEN"] = "-Syu"
        failed = subprocess.run(
            [sys.executable, "-m", "jupiter", "2"],
            cwd=INSTALLER_DIR,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Failed: sudo pacman -Syu --noconfirm", failed.stderr)

    @unittest.skipUnless(shutil.which("pacman"), "needs pacman")
    def test_official_packages_exist(self) -> None:
        drivers = [
            name for names in phase1.GRAPHICS.values() for name in names
        ]
        names = [
            *phase1.BASE,
            *phase1.MICROCODE.values(),
            *drivers,
            *phase1.NVIDIA,
            *packages("core.txt"),
            *packages("pacman.txt"),
        ]
        found = subprocess.run(
            ["pacman", "-Si", *names],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(found.returncode, 0, found.stderr)


class Lists(unittest.TestCase):
    """packages/: each package in one list, and the AUR's in aur.txt only."""

    def test_each_package_once(self) -> None:
        names = [
            *packages("core.txt"),
            *packages("pacman.txt"),
            *packages("aur.txt"),
        ]
        twice = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(twice, [])

    @unittest.skipUnless(shutil.which("pacman"), "needs pacman")
    def test_aur_packages_are_not_official(self) -> None:
        for name in packages("aur.txt"):
            found = subprocess.run(
                ["pacman", "-Si", name], capture_output=True, check=False
            )
            self.assertNotEqual(
                found.returncode, 0, f"{name} is official now: pacman.txt"
            )


class Country(unittest.TestCase):
    """The Wi-Fi rules' country, from the time zone and tzdata's zone.tab."""

    TABLE = (
        "# comments\n"
        "DE\t+5230+01322\tEurope/Berlin\tmost of Germany\n"
        "US\t+404251-0740023\tAmerica/New_York\tEastern (most areas)\n"
    )

    def country(self, zone: str | None) -> str | None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "etc").mkdir()
        (root / "usr/share/zoneinfo").mkdir(parents=True)
        (root / "usr/share/zoneinfo/zone.tab").write_text(self.TABLE)
        if zone:
            target = f"/usr/share/zoneinfo/{zone}"
            (root / "etc/localtime").symlink_to(target)
        return phase2.country(root)

    def test_by_time_zone(self) -> None:
        self.assertEqual(self.country("Europe/Berlin"), "DE")
        self.assertEqual(self.country("America/New_York"), "US")

    def test_none_for_utc_or_no_zone(self) -> None:
        self.assertIsNone(self.country("UTC"))
        self.assertIsNone(self.country(None))


class Disks(unittest.TestCase):
    def test_only_unused_disks_the_system_fits_on(self) -> None:
        gib = 2**30
        stick = {"type": "part", "mountpoints": ["/run/archiso/bootmnt"]}
        devices = [
            {"name": "/dev/fd0", "size": 4096, "type": "disk"},
            {"name": "/dev/loop0", "size": gib, "type": "loop"},
            {"name": "/dev/sda", "size": 64 * gib, "children": [stick]},
            {"name": "/dev/mmcblk0", "size": 0, "type": "disk"},
            {"name": "/dev/nvme0n1", "size": 512 * gib, "type": "disk"},
        ]
        for device in devices:
            device.setdefault("type", "disk")
            device.setdefault("mountpoints", [None])
        [target] = phase1.targets(devices)
        self.assertEqual(target["name"], "/dev/nvme0n1")


class Keyboard(unittest.TestCase):
    """The X layout phase 1 writes beside the console keymap."""

    TABLE = (
        "# consolelayout\txlayout\txmodel\txvariant\txoptions\n"
        "de-latin1\tde\tpc105\t-\tterminate:ctrl_alt_bksp\t-\n"
        "dvorak\tus\tpc105\tdvorak\tterminate:ctrl_alt_bksp\t-\n"
        "dvorak\tus\tpc105\tdvorak-alt-intl\tterminate:ctrl_alt_bksp\t-\n"
    )

    def test_layout_model_and_options(self) -> None:
        self.assertEqual(
            phase1.keyboard("de-latin1", self.TABLE),
            {
                "XKBLAYOUT": "de",
                "XKBMODEL": "pc105",
                "XKBOPTIONS": "terminate:ctrl_alt_bksp",
            },
        )

    def test_first_variant(self) -> None:
        xkb = phase1.keyboard("dvorak", self.TABLE)
        self.assertEqual(xkb["XKBLAYOUT"], "us")
        self.assertEqual(xkb["XKBVARIANT"], "dvorak")

    def test_unknown_keymap(self) -> None:
        self.assertEqual(phase1.keyboard("tr", self.TABLE), {})

    @unittest.skipUnless(phase1.KBD_MODEL_MAP.exists(), "needs systemd")
    def test_systemds_own_map(self) -> None:
        table = phase1.KBD_MODEL_MAP.read_text()
        layouts = {"us": "us", "de-latin1": "de", "fr": "fr"}
        for keymap, layout in layouts.items():
            xkb = phase1.keyboard(keymap, table)
            self.assertEqual(xkb["XKBLAYOUT"], layout, keymap)


class Drivers(unittest.TestCase):
    """What phase 1 installs for a CPU and PCI devices (class, vendor, ID)."""

    def drivers(self, cpu: str, *devices: tuple[str, str, int]) -> set[str]:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "proc").mkdir()
        (root / "proc/cpuinfo").write_text(f"vendor_id\t: {cpu}\n")
        (root / "sys/bus/pci/devices").mkdir(parents=True)
        for slot, (kind, vendor, model) in enumerate(devices):
            device = root / f"sys/bus/pci/devices/0000:0{slot}:00.0"
            device.mkdir()
            (device / "class").write_text(f"{kind}\n")
            (device / "vendor").write_text(f"{vendor}\n")
            (device / "device").write_text(f"{model:#06x}\n")
        return phase1.drivers(root)

    def test_intel_laptop(self) -> None:
        self.assertEqual(
            self.drivers(
                "GenuineIntel",
                ("0x030000", "0x8086", 0xA7A0),
                ("0x028000", "0x8086", 0x51F0),  # Wi-Fi, not a GPU
            ),
            {"intel-ucode", "mesa", "vulkan-intel", "intel-media-driver"},
        )

    def test_amd_desktop(self) -> None:
        self.assertEqual(
            self.drivers("AuthenticAMD", ("0x030000", "0x1002", 0x73BF)),
            {"amd-ucode", "mesa", "vulkan-radeon"},
        )

    def test_nvidia_turing_and_newer_alone(self) -> None:
        self.assertEqual(
            self.drivers("AuthenticAMD", ("0x030000", "0x10de", 0x2216)),
            {"amd-ucode", *phase1.NVIDIA},
        )

    def test_nvidia_before_turing(self) -> None:
        self.assertEqual(
            self.drivers("GenuineIntel", ("0x030000", "0x10de", 0x1B80)),
            {"intel-ucode", "mesa", "vulkan-nouveau"},
        )

    def test_hybrid_laptop(self) -> None:
        self.assertEqual(
            self.drivers(
                "GenuineIntel",
                ("0x030000", "0x8086", 0x9A49),
                ("0x030200", "0x10de", 0x25A0),
            ),
            {
                "intel-ucode",
                "mesa",
                "vulkan-intel",
                "intel-media-driver",
                *phase1.NVIDIA,
            },
        )

    def test_virtual_machine(self) -> None:
        self.assertEqual(
            self.drivers("AuthenticAMD", ("0x030000", "0x1af4", 0x1050)),
            {"amd-ucode"},
        )


if __name__ == "__main__":
    unittest.main()
