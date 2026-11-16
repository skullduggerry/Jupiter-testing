"""scripts/uwsm-desktop-entries.py, in a stand-in root.

Nextcloud's entry, as nextcloud-client 35 installs it, gets a copy in
/usr/local/share/applications without its [org.freedesktop.CloudProviders]
group and Implements= key, and the rest as it was; an entry uwsm takes as it
is gets none. The targets come on stdin as pacman's NeedsTargets passes them,
or are every entry when there are none. A copy goes once its entry is gone or
no longer needs one, and one this did not write is never touched. Where uwsm
is installed, its own validation refuses the entry and takes the copy.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

from harness import DOTFILES, executable, temporary

SCRIPT = DOTFILES / "scripts/uwsm-desktop-entries.py"
UWSM = Path("/usr/share/uwsm/modules")
NAME = "com.nextcloud.desktopclient.nextcloud.desktop"
NEXTCLOUD = """[Desktop Entry]
Categories=Utility;X-SuSE-SyncUtility;
Type=Application
Exec=nextcloud %u
Name=Nextcloud Desktop
Icon=Nextcloud
SingleMainWindow=true
Actions=Quit;

# Translations
Name[de]=Nextcloud Desktop
Implements=org.freedesktop.CloudProviders

[org.freedesktop.CloudProviders]
BusName=com.nextcloudgmbh.Nextcloud
ObjectPath=/com/nextcloudgmbh/Nextcloud

[Desktop Action Quit]
Exec=nextcloud --quit
Name=Quit Nextcloud
"""
CLEANED = """[Desktop Entry]
Categories=Utility;X-SuSE-SyncUtility;
Type=Application
Exec=nextcloud %u
Name=Nextcloud Desktop
Icon=Nextcloud
SingleMainWindow=true
Actions=Quit;

# Translations
Name[de]=Nextcloud Desktop

[Desktop Action Quit]
Exec=nextcloud --quit
Name=Quit Nextcloud
"""
KITTY = """[Desktop Entry]
Type=Application
Name=kitty
Exec=kitty

[X-Extra]
Key=value
"""


def uwsm_takes(path: Path) -> bool:
    sys.path.insert(0, str(UWSM))
    # uwsm's own modules, untyped, and pyxdg, which may have no stubs.
    from uwsm.main import (  # type: ignore[import-not-found, import-untyped, unused-ignore]
        check_entry_basic,
    )
    from xdg.DesktopEntry import (  # type: ignore[import-not-found, import-untyped, unused-ignore]
        DesktopEntry,
    )

    try:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            check_entry_basic(DesktopEntry(str(path)))
    except RuntimeError:
        return False
    return True


class DesktopEntries(unittest.TestCase):
    def setUp(self) -> None:
        self.root = temporary(self)
        apps = self.root / "usr/share/applications"
        apps.mkdir(parents=True)
        self.copies = self.root / "usr/local/share/applications"
        self.entry = apps / NAME
        self.entry.write_text(NEXTCLOUD)
        (apps / "kitty.desktop").write_text(KITTY)
        self.copy = self.copies / NAME

    def run_script(self, stdin: str | None) -> str:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=dict(os.environ, ROOT=str(self.root)),
            input=stdin if stdin is not None else "",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stderr.startswith("Traceback"))
        return result.stdout + result.stderr

    def test_a_copy_without_what_uwsm_refuses(self) -> None:
        self.run_script(
            f"usr/share/applications/{NAME}\nusr/share/applications/kitty.desktop\n"
            "usr/share/icons/x.png\n"
        )
        lines = self.copy.read_text().splitlines(keepends=True)
        self.assertTrue(
            lines[0].startswith(
                "# Written by Jupiter-dotfiles' uwsm-desktop-entries.py: "
            )
        )
        self.assertEqual("".join(lines[1:]), CLEANED)
        self.assertEqual(oct(self.copy.stat().st_mode & 0o777), "0o644")
        self.assertEqual(
            sorted(path.name for path in self.copies.iterdir()),
            [NAME],
            "kitty, with an X- group, needs none",
        )
        if (UWSM / "uwsm/main.py").exists():
            # uwsm also wants the entry's program on PATH, which nextcloud
            # is only where nextcloud-client is installed.
            executable(self.root / "bin/nextcloud", "#!/bin/sh\n")
            self.enterContext(
                unittest.mock.patch.dict(
                    os.environ,
                    PATH=f"{self.root / 'bin'}:{os.environ['PATH']}",
                )
            )
            self.assertFalse(uwsm_takes(self.entry), "uwsm refuses the entry")
            self.assertTrue(uwsm_takes(self.copy), "uwsm takes the copy")

    def test_copies_go_when_they_are_not_needed(self) -> None:
        self.run_script(f"usr/share/applications/{NAME}\n")
        # An upgrade that drops the group: the copy goes.
        self.entry.write_text(CLEANED)
        self.run_script(f"usr/share/applications/{NAME}\n")
        self.assertFalse(self.copy.exists())
        # Every entry when nothing is named, which also clears copies of
        # entries that are gone.
        self.entry.write_text(NEXTCLOUD)
        self.run_script(None)
        self.assertTrue(self.copy.exists(), "with no targets, every entry")
        self.entry.unlink()
        self.run_script(None)
        self.assertFalse(self.copy.exists(), "a removed package's copy goes")

    def test_someone_elses_copy_is_left(self) -> None:
        self.copies.mkdir(parents=True)
        self.copy.write_text("[Desktop Entry]\nName=Mine\n")
        output = self.run_script(f"usr/share/applications/{NAME}\n")
        self.assertEqual(self.copy.read_text(), "[Desktop Entry]\nName=Mine\n")
        self.assertIn("not written by this", output)
        self.entry.unlink()
        self.run_script(f"usr/share/applications/{NAME}\n")
        self.assertTrue(self.copy.exists(), "nor removed")


if __name__ == "__main__":
    unittest.main()
