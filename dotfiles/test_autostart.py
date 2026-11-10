"""The Settings app's autostart helper against a made-up set of folders.

It has to agree with systemd-xdg-autostart-generator, which is what starts
autostart apps under uwsm: which entries count on this desktop, a user file
masking the system one, Hidden= for off. And switching an entry off and on
again must leave nothing behind, while a user's own changes to an entry stay.
systemctl is a stand-in on PATH, reporting one unit running.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from typing import Any

from harness import QUICKSHELL, executable, temporary

HELPER = QUICKSHELL / "settings/autostart.py"
SYSTEMCTL = (
    '#!/bin/sh\necho \'[{"unit": "app-plain@autostart.service", "sub": "running"},'
    ' {"unit": "app-with\\\\x2daction@autostart.service", "sub": "dead"}]\'\n'
)


def entry(name: str, *extra: str) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        "Exec=true",
        *extra,
    ]
    return "\n".join(lines) + "\n"


class Autostart(unittest.TestCase):
    def setUp(self) -> None:
        root = temporary(self)
        system = root / "xdg/autostart"
        self.user = root / "config/autostart"
        apps = root / "data/applications"
        for directory in (system, apps):
            directory.mkdir(parents=True)
        for name, text in {
            "plain": entry("Plain", "Comment=Starts everywhere"),
            "kde-only": entry("KDE only", "OnlyShowIn=KDE;"),
            "not-here": entry("Not here", "NotShowIn=Hyprland;GNOME;"),
            "skipped": entry("Skipped", "X-systemd-skip=true"),
            "phase": entry(
                "Phase",
                "OnlyShowIn=GNOME;",
                "X-GNOME-Autostart-Phase=Initialization",
            ),
            "missing": entry("Missing", "TryExec=no-such-program-anywhere"),
            "shipped-off": entry("Shipped off", "Hidden=true"),
            "with-action": entry("With action")
            + "\n[Desktop Action new]\nName=New\nExec=true --new\n",
        }.items():
            (system / f"{name}.desktop").write_text(text)
        (apps / "my-app.desktop").write_text(entry("My app", "Icon=my-icon"))
        executable(root / "bin/systemctl", SYSTEMCTL)
        self.env = dict(
            os.environ,
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_CONFIG_DIRS=str(root / "xdg"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_DATA_DIRS=str(root / "none"),
            XDG_CURRENT_DESKTOP="Hyprland",
            PATH=f"{root / 'bin'}:{os.environ.get('PATH', '')}",
        )

    def run_helper(self, *args: str, ok: bool = True) -> str:
        result = subprocess.run(
            [sys.executable, str(HELPER), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode == 0, ok, f"{' '.join(args)}: {result.stderr}"
        )
        return result.stdout

    def listing(self) -> dict[str, dict[str, Any]]:
        return {
            item["id"]: item for item in json.loads(self.run_helper("list"))
        }

    def test_what_counts_on_this_desktop(self) -> None:
        found = self.listing()
        self.assertEqual(
            sorted(found), ["plain", "shipped-off", "with-action"]
        )
        self.assertEqual(found["plain"]["state"], "running")
        self.assertEqual(
            found["with-action"]["state"], "dead", "an escaped unit name"
        )
        self.assertEqual(found["plain"]["comment"], "Starts everywhere")
        self.assertIs(
            found["shipped-off"]["enabled"], False, "a Hidden system entry"
        )

    def test_an_entry_that_cannot_be_read_costs_only_itself(self) -> None:
        """An app removed leaves its link in ~/.config/autostart behind."""
        self.user.mkdir(parents=True)
        (self.user / "gone.desktop").symlink_to("/nonexistent/gone.desktop")
        (self.user / "folder.desktop").mkdir()
        unreadable = self.user / "unreadable.desktop"
        unreadable.write_text(entry("Unreadable"))
        unreadable.chmod(0)
        self.assertEqual(
            sorted(self.listing()), ["plain", "shipped-off", "with-action"]
        )

    def test_off_and_on_again_leaves_nothing(self) -> None:
        self.run_helper("set", "plain", "off")
        override = self.user / "plain.desktop"
        self.assertIn("Hidden=true", override.read_text())
        self.assertIs(self.listing()["plain"]["enabled"], False)
        self.run_helper("set", "plain", "on")
        self.assertFalse(override.exists(), "on left the copy behind")
        self.assertIs(self.listing()["plain"]["enabled"], True)

    def test_hidden_goes_in_the_desktop_entry_group(self) -> None:
        self.run_helper("set", "with-action", "off")
        text = (self.user / "with-action.desktop").read_text()
        self.assertLess(
            text.index("Hidden=true"), text.index("[Desktop Action new]")
        )
        self.run_helper("set", "with-action", "on")

    def test_a_hidden_system_entry_can_be_switched_on(self) -> None:
        self.run_helper("set", "shipped-off", "on")
        self.assertIs(self.listing()["shipped-off"]["enabled"], True)

    def test_a_users_own_copy_stays(self) -> None:
        mine = self.user / "plain.desktop"
        mine.parent.mkdir(parents=True)
        mine.write_text(entry("Plain", "Exec=true --mine"))
        self.run_helper("set", "plain", "off")
        self.run_helper("set", "plain", "on")
        self.assertIn("--mine", mine.read_text())
        self.assertIn("Hidden=false", mine.read_text())

    def test_an_app_of_ones_own(self) -> None:
        self.run_helper("add", "my-app")
        added = self.listing()["my-app"]
        self.assertTrue(added["custom"])
        self.assertEqual(added["icon"], "my-icon")
        self.run_helper("set", "my-app", "off")
        self.assertTrue(
            (self.user / "my-app.desktop").exists(),
            "switching a user's entry off deleted it",
        )
        self.run_helper("set", "my-app", "on")
        self.run_helper("remove", "my-app")
        self.assertNotIn("my-app", self.listing())
        self.run_helper("remove", "plain", ok=False)
        self.run_helper("add", "no-such-app", ok=False)


if __name__ == "__main__":
    unittest.main()
