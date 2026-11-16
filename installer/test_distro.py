"""jupiter/distro.py: which system the installer is on, told by archiso's
mark and os-release, and a system it does not know refused rather than
guessed, as phase 1 erases disks. Stand-in files in a temporary folder."""

import unittest
from pathlib import Path
from unittest import mock

from jupiter import distro

from harness import temporary

ARCH = 'NAME="Arch Linux"\nID=arch\nBUILD_ID=rolling\n'
NIXOS = 'NAME=NixOS\nID=nixos\nVERSION_ID="26.11"\n'
NIXOS_ISO = NIXOS + "VARIANT_ID=installer\n"


class Detect(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.release = self.tmp / "os-release"
        self.archiso = self.tmp / "archiso"
        self.enterContext(
            mock.patch.object(distro, "OS_RELEASE", self.release)
        )
        self.enterContext(mock.patch.object(distro, "ARCHISO", self.archiso))

    def detect(self, text: str | None, archiso: bool = False) -> distro.System:
        if text is not None:
            self.release.write_text(text)
        if archiso:
            self.archiso.mkdir()
        return distro.detect()

    def test_each_system_installed_and_live(self) -> None:
        for name, text, archiso, expected in (
            ("Arch installed", ARCH, False, ("arch", False)),
            ("Arch's ISO", ARCH, True, ("arch", True)),
            ("NixOS installed", NIXOS, False, ("nixos", False)),
            ("NixOS's ISO", NIXOS_ISO, False, ("nixos", True)),
            (
                "quoted",
                "ID='nixos'\nVARIANT_ID=\"installer\"\n",
                False,
                ("nixos", True),
            ),
        ):
            with self.subTest(name):
                found = self.detect(text, archiso)
                self.assertEqual((found.name, found.live), expected)
                self.release.unlink()
                if archiso:
                    self.archiso.rmdir()

    def test_another_system_is_refused_by_its_name(self) -> None:
        for text, named in (
            (
                'ID=ubuntu\nPRETTY_NAME="Ubuntu 24.04.5 LTS"\n',
                "Ubuntu 24.04.5 LTS",
            ),
            ("ID=manjaro\nID_LIKE=arch\n", "manjaro"),
            (None, "a system without os-release"),
        ):
            with self.subTest(named), self.assertRaises(SystemExit) as refused:
                self.detect(text)
            self.assertIn(named, str(refused.exception))
            self.assertIn("Arch Linux and NixOS only", str(refused.exception))
            self.release.unlink(missing_ok=True)

    def test_an_installer_variant_elsewhere_is_no_nixos_iso(self) -> None:
        # Only NixOS's ISO counts as live by os-release; another system's
        # VARIANT_ID=installer is refused all the same.
        with self.assertRaises(SystemExit):
            self.detect("ID=fedora\nVARIANT_ID=installer\n")


class Entry(unittest.TestCase):
    """The entry point runs the detected system's phases, and nothing on a
    system it refused."""

    def test_arch_and_nixos_get_their_own_phases(self) -> None:
        from jupiter import __main__ as entry

        for name, table in (("arch", "PHASES"), ("nixos", "NIXOS_PHASES")):
            ran: list[str] = []
            phases = {
                n: (lambda n=n, name=name, ran=ran: ran.append(f"{name} {n}"))
                for n in getattr(entry, table)
            }
            with (
                self.subTest(name),
                mock.patch.dict(getattr(entry, table), phases),
                mock.patch.object(
                    entry, "detect", return_value=distro.System(name, False)
                ),
                mock.patch.object(entry, "LIVE", False),
                mock.patch.object(entry, "online", return_value=True),
                mock.patch("os.geteuid", return_value=1000),
                mock.patch("sys.argv", ["jupiter", "4"]),
                mock.patch("builtins.print"),
            ):
                entry.main()
            self.assertEqual(ran, [f"{name} 4"])

    def test_nothing_runs_on_a_system_refused(self) -> None:
        from jupiter import __main__ as entry

        ran: list[int] = []
        phases = {n: (lambda n=n: ran.append(n)) for n in entry.PHASES}
        with (
            mock.patch.dict(entry.PHASES, phases),
            mock.patch.object(entry, "detect", side_effect=SystemExit("no")),
            mock.patch("sys.argv", ["jupiter", "1"]),
            self.assertRaises(SystemExit),
        ):
            entry.main()
        self.assertEqual(ran, [])

    def test_the_tests_installer_is_arch_unless_told(self) -> None:
        # installer/__init__.py's stand-in: the Arch suites run as on Arch.
        self.assertEqual(Path(distro.OS_RELEASE).name, "arch-os-release")
