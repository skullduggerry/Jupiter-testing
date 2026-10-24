"""scripts/install-system.sh, into a stand-in root.

It installs every udev rule and pacman hook in etc/ and the script the hook
runs, where the hook looks for it, then runs that script once over the
desktop entries already there; it puts root's copy of the login screen's
installer, with greetd's config and the PAM stacks, where the Settings app
runs it through pkexec; it leaves udev alone outside the real root
(a stand-in udevadm on PATH would note a call), and running it twice is the
same as once.
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest

from harness import DOTFILES, executable, temporary

SCRIPT = DOTFILES / "scripts/install-system.sh"


class InstallSystem(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.root = self.tmp / "root"
        apps = self.root / "usr/share/applications"
        apps.mkdir(parents=True)
        (apps / "cloud.desktop").write_text(
            "[Desktop Entry]\nName=Cloud\nExec=cloud\n\n[org.example.Group]\nKey=value\n"
        )
        executable(
            self.tmp / "bin/udevadm",
            f'#!/bin/sh\necho "$*" >> "{self.tmp}/udevadm"\n',
        )

    def install(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.root)],
            env=dict(
                os.environ, PATH=f"{self.tmp / 'bin'}:{os.environ['PATH']}"
            ),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_installs_the_rules_and_hooks(self) -> None:
        result = self.install()
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        for source in [
            *DOTFILES.glob("etc/udev/rules.d/*.rules"),
            *DOTFILES.glob("etc/pacman.d/hooks/*.hook"),
        ]:
            target = self.root / source.relative_to(DOTFILES)
            with self.subTest(str(target.relative_to(self.root))):
                self.assertEqual(target.read_bytes(), source.read_bytes())
                self.assertEqual(oct(target.stat().st_mode & 0o777), "0o644")
        helper = self.root / "usr/local/lib/jupiter/uwsm-desktop-entries.py"
        self.assertTrue(os.access(helper, os.X_OK))
        hook = (
            DOTFILES / "etc/pacman.d/hooks/uwsm-desktop-entries.hook"
        ).read_text()
        self.assertEqual(
            re.findall(r"^Exec = (\S+)", hook, re.MULTILINE),
            ["/usr/local/lib/jupiter/uwsm-desktop-entries.py"],
            "the hook runs it where it is installed",
        )
        copy = self.root / "usr/local/share/applications/cloud.desktop"
        self.assertTrue(copy.exists(), "entries already there got their copy")
        self.assertFalse((self.tmp / "udevadm").exists(), "udev left alone")

    def test_roots_copy_of_the_login_screens_installer(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        greeter = self.root / "usr/local/lib/jupiter/greeter"
        for name, mode in (
            ("scripts/install-greeter.sh", "0o755"),
            ("etc/greetd/config.toml", "0o644"),
            ("etc/pam.d/greetd", "0o644"),
            ("etc/pam.d/greetd-greeter", "0o644"),
        ):
            with self.subTest(name):
                installed = greeter / name
                self.assertEqual(
                    installed.read_bytes(), (DOTFILES / name).read_bytes()
                )
                self.assertEqual(oct(installed.stat().st_mode & 0o777), mode)

    def test_twice_is_once(self) -> None:
        self.install()
        before = sorted(
            str(p.relative_to(self.root)) for p in self.root.rglob("*")
        )
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(
            sorted(
                str(p.relative_to(self.root)) for p in self.root.rglob("*")
            ),
            before,
        )


if __name__ == "__main__":
    unittest.main()
