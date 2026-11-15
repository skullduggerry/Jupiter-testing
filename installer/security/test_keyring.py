"""Phase 4's login keyring (jupiter/keyring.py): on an encrypted system, made
unencrypted where there is none, an encrypted one re-keyed by gnome-keyring's
own dialog with nothing of the password passing through the installer, and
never one written over or deleted; on an unencrypted one, nothing made and
nothing re-keyed.

The dialog needs a desktop, so the flow's tests stand in for it: answered
(the keyring rewritten unencrypted, as an empty new password does) or
dismissed. The real gnome-keyring-daemon, on a session bus of its own in a
throwaway home with no display, takes the dialog's calls as keyring.py makes
them, over one connection: the prompt it hands out is shown, fails for want
of a display, and the daemon lives on, as it did not when a second gdbus
showed the prompt (its runtime folder short: the control socket's path must
stay under 108 bytes), once it owns its name on the bus, which `--unlock`
does not wait for.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jupiter import keyring, tpm

from harness import SECRET, environment

NEEDED = ("gnome-keyring-daemon", "dbus-run-session", "gdbus")
MISSING = [name for name in NEEDED if not shutil.which(name)]
INSTALLER = Path(keyring.__file__).resolve().parents[1]


class Keyrings(unittest.TestCase):
    """keyring.py in this process, its keyrings folder a temporary one."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.keyrings = tmp / "keyrings"
        self.enterContext(
            mock.patch.object(keyring, "folder", return_value=self.keyrings)
        )
        self.printed = self.enterContext(mock.patch("builtins.print"))
        # An encrypted root, unless a test says otherwise.
        self.root = self.enterContext(
            mock.patch.object(
                tpm, "root_volume", return_value=("root", "/dev/vda2")
            )
        )
        # It reaches nothing through another program.
        self.enterContext(
            mock.patch("subprocess.Popen", side_effect=AssertionError)
        )


class Folder(Keyrings):
    def test_makes_an_unencrypted_one_only_root_and_you_read(self) -> None:
        keyring.main()
        login = self.keyrings / "login.keyring"
        self.assertEqual(login.read_text(), keyring.PLAIN)
        self.assertEqual(login.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.keyrings.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.keyrings / "default").read_text(), "login")

    def test_leaves_an_unencrypted_one_as_it_is(self) -> None:
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        login.write_text("[keyring]\ndisplay-name=Login\n\n[1]\nsecret=x\n")
        (self.keyrings / "default").write_text("other")
        keyring.main()
        self.assertEqual(
            login.read_text(),
            "[keyring]\ndisplay-name=Login\n\n[1]\nsecret=x\n",
        )
        self.assertEqual((self.keyrings / "default").read_text(), "other")

    def test_keeps_the_default_another_keyring_is(self) -> None:
        self.keyrings.mkdir()
        (self.keyrings / "default").write_text("other")
        keyring.main()
        self.assertEqual((self.keyrings / "default").read_text(), "other")
        self.assertEqual(
            (self.keyrings / "login.keyring").read_text(), keyring.PLAIN
        )

    def test_never_writes_over_one_that_appears(self) -> None:
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        with mock.patch.object(Path, "exists", return_value=False):
            login.write_text("theirs")
            with self.assertRaises(FileExistsError):
                keyring.main()
        self.assertEqual(login.read_text(), "theirs")

    def test_without_a_session_bus_says_where_to_run_it(self) -> None:
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        login.write_bytes(keyring.ENCRYPTED_MAGIC + b"secrets")
        with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": ""}):
            keyring.main()
        self.assertEqual(
            login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )
        self.assertEqual(
            sorted(p.name for p in self.keyrings.iterdir()), ["login.keyring"]
        )


class Unencrypted(Keyrings):
    """A root not on LUKS: an unencrypted keyring would lie on the disk in
    the clear, so none is made and none re-keyed."""

    def test_makes_none(self) -> None:
        self.root.return_value = None
        keyring.main()
        self.assertFalse(self.keyrings.exists())
        said = " ".join(
            str(a) for c in self.printed.call_args_list for a in c.args
        )
        self.assertIn("The disk is not encrypted", said)

    def test_leaves_an_encrypted_one_encrypted(self) -> None:
        self.root.return_value = None
        self.keyrings.mkdir()
        login = self.keyrings / "login.keyring"
        login.write_bytes(keyring.ENCRYPTED_MAGIC + b"secrets")
        with mock.patch("builtins.input", side_effect=AssertionError):
            keyring.main()
        self.assertEqual(
            login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )
        self.assertEqual(
            [p.name for p in self.keyrings.iterdir()], ["login.keyring"]
        )


class ReKeying(Keyrings):
    """An encrypted login keyring, as a password login leaves it, on an
    encrypted disk, phase 4 run from the desktop."""

    def setUp(self) -> None:
        super().setUp()
        self.keyrings.mkdir()
        self.login = self.keyrings / "login.keyring"
        self.login.write_bytes(keyring.ENCRYPTED_MAGIC + b"secrets")
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "WAYLAND_DISPLAY": "wayland-1",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
                },
            )
        )

    def rekey(self, answer: str, consent: str = "") -> int:
        """keyring.main() with the dialog answered (empty) or dismissed;
        how often it was shown."""

        def dialog() -> None:
            if answer == "empty":
                self.login.write_text("[keyring]\ndisplay-name=Login\n")

        with (
            mock.patch.object(
                keyring, "_change_password", side_effect=dialog
            ) as shown,
            mock.patch("builtins.input", return_value=consent),
            mock.patch("getpass.getpass", side_effect=AssertionError),
        ):
            keyring.main()
        return shown.call_count

    def copies(self) -> list[str]:
        return sorted(
            p.name
            for p in self.keyrings.iterdir()
            if p.name != "login.keyring"
        )

    def test_the_dialog_with_an_empty_password_leaves_it_unencrypted(
        self,
    ) -> None:
        self.assertEqual(self.rekey("empty"), 1)
        self.assertTrue(self.login.read_text().startswith("[keyring]"))
        [copy] = self.copies()
        self.assertTrue(
            (self.keyrings / copy)
            .read_bytes()
            .startswith(keyring.ENCRYPTED_MAGIC)
        )

    def test_a_dismissed_dialog_changes_nothing(self) -> None:
        self.assertEqual(self.rekey("cancel"), 1)
        self.assertEqual(
            self.login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )
        self.assertEqual(self.copies(), [])

    def test_asks_first(self) -> None:
        self.assertEqual(self.rekey("empty", consent="n"), 0)
        self.assertEqual(
            self.login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )

    def test_only_from_the_desktop(self) -> None:
        del os.environ["WAYLAND_DISPLAY"]
        self.assertEqual(self.rekey("empty"), 0)
        self.assertEqual(
            self.login.read_bytes(), keyring.ENCRYPTED_MAGIC + b"secrets"
        )


@unittest.skipIf(MISSING, f"needs {', '.join(MISSING)}")
class GnomeKeyring(unittest.TestCase):
    """The real daemon takes the dialog's calls as keyring.py makes them,
    and lives on: the prompt it hands out is shown over the connection that
    asked for it (whose dialog a desktop would show, and here cannot)."""

    def test_shows_the_dialog_and_lives_on(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory(dir="/tmp")))
        session = f"""
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
printf %s "$KEYRING_PASSWORD" | gnome-keyring-daemon --unlock --components=secrets >/dev/null 2>&1
# --unlock can return before the daemon owns its name; a call then would
# have D-Bus start a second daemon. Wait for the name, starting nothing.
gdbus wait --session --timeout 30 org.freedesktop.secrets
cd {INSTALLER} && {sys.executable} -c \\
    'from jupiter import keyring; keyring._change_password(); print("returned")'
gdbus call --session --dest org.freedesktop.DBus \\
    --object-path /org/freedesktop/DBus \\
    --method org.freedesktop.DBus.NameHasOwner org.freedesktop.secrets
"""
        done = subprocess.run(
            ["dbus-run-session", "--", "sh", "-c", session],
            env=environment(
                HOME=str(home),
                XDG_DATA_HOME=str(home / "data"),
                XDG_RUNTIME_DIR=str(home / "r"),
                KEYRING_PASSWORD=SECRET,
                # No display: the dialog would open on the desktop running
                # the tests, and wait there for an answer.
                WAYLAND_DISPLAY=None,
                DISPLAY=None,
            ),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        self.assertEqual(done.stdout.split(), ["returned", "(true,)"])
        login = home / "data/keyrings/login.keyring"
        self.assertTrue(
            login.read_bytes().startswith(keyring.ENCRYPTED_MAGIC),
            "no answer, no change",
        )


if __name__ == "__main__":
    unittest.main()
