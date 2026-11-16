"""nixos/desktop-entries.py, which runs the dotfiles' uwsm-desktop-entries.py
over the system profile's applications as it is built (login.nix's
environment.extraSetup): an entry uwsm would refuse is replaced by its
cleaned copy, the link into the store it was gone; the others stay links.
"""

import subprocess
import sys
import unittest

from harness import DOTFILES, NIXOS, temporary

SCRIPT = NIXOS / "nixos/desktop-entries.py"
CLEANER = DOTFILES / "scripts/uwsm-desktop-entries.py"
NEXTCLOUD = """[Desktop Entry]
Name=Nextcloud
Exec=nextcloud
Implements=org.freedesktop.CloudProviders

[org.freedesktop.CloudProviders]
BusName=com.nextcloudgmbh.Nextcloud
"""
KITTY = "[Desktop Entry]\nName=kitty\nExec=kitty\n"


class Cleaning(unittest.TestCase):
    def test_only_what_uwsm_refuses_is_rewritten(self) -> None:
        tmp = temporary(self)
        store = tmp / "store"
        store.mkdir()
        (store / "nextcloud.desktop").write_text(NEXTCLOUD)
        (store / "kitty.desktop").write_text(KITTY)
        profile = tmp / "sw/share/applications"
        profile.mkdir(parents=True)
        for name in ("nextcloud.desktop", "kitty.desktop"):
            (profile / name).symlink_to(store / name)
        done = subprocess.run(
            [sys.executable, str(SCRIPT), str(CLEANER), str(profile)],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(done.stdout, "cleaned nextcloud.desktop\n")
        nextcloud = profile / "nextcloud.desktop"
        self.assertFalse(nextcloud.is_symlink())
        text = nextcloud.read_text()
        self.assertNotIn("Implements=", text)
        self.assertNotIn("[org.freedesktop.CloudProviders]", text)
        self.assertIn("Exec=nextcloud", text)
        self.assertEqual((store / "nextcloud.desktop").read_text(), NEXTCLOUD)
        self.assertTrue((profile / "kitty.desktop").is_symlink())

    def test_a_profile_without_applications(self) -> None:
        tmp = temporary(self)
        done = subprocess.run(
            [sys.executable, str(SCRIPT), str(CLEANER), str(tmp / "none")],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(done.stdout, "")


if __name__ == "__main__":
    unittest.main()
